#!/usr/bin/env python3
"""
reel-sfx.py: put a sound effect on every card entrance of a finished reel.

It reads the card times straight out of cards.json, so the sound cannot drift
away from the graphics. Mixing the hits by hand, with the times pasted into a
shell array, works once and then silently rots the moment a card moves.

No sound ships with this skill. Bring a short effect you have the rights to use
(a soft whoosh or swell, under a second) and pass it with --sfx, or set
REEL_SFX to its path. A swell that rises for its first few tenths of a second
should be placed as is: its quiet front is what makes it peak as the card
finishes sliding in, so do not trim it.

The level defaults are a starting point, measured with one soft swell (peak
around -13.6 dBFS) against one speaking voice:
  --volume   1.7   gain on each hit. At 0.55 the effect lifted the track by
                   0.4 dB, which is inaudible. At 3.4 it was clean but loud.
  --headroom 0.88  applied to the whole mix before the limiter. Without it the
                   output peaked at -0.5 dB with hundreds of samples on the
                   limiter ceiling.
  --ceiling  0.87  the limiter's ceiling, about -1.2 dBTP.
A soft swell cannot be made punchy with volume. Past a point the limiter clamps
voice and effect together and the whole track squashes. If every card needs to
click, use a sound with a sharp front edge rather than raising --volume.

After mixing it measures every hit (RMS in a 0.5s window, against the same
moment of the input) and prints how many cleared 2 dB, the point where an
effect reads as audible under speech. Hits under the loudest words are masked,
and that is normal.

Requires:
  Python 3.8+ (standard library only)
  ffmpeg and ffprobe on PATH

Example:
  python3 reel-sfx.py --video composite.mp4 --cards cards.json --sfx whoosh.wav --out final.mp4
  python3 reel-sfx.py --video composite.mp4 --at 0,4.3,9.9 --sfx whoosh.wav --out final.mp4
"""

import argparse, json, math, os, shutil, struct, subprocess, sys
from pathlib import Path

DEF_VOLUME = 1.7
DEF_HEADROOM = 0.88
DEF_CEILING = 0.87
AUDIBLE_DB = 2.0
END_GUARD = 0.3   # a hit this close to the end, or later, is skipped


def require_tool(name):
    if shutil.which(name) is None:
        sys.exit(f"error: '{name}' was not found on PATH.\n"
                 "       Install ffmpeg. macOS: brew install ffmpeg. Debian/Ubuntu: sudo apt install ffmpeg.")


def duration_of(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        sys.exit(f"error: ffprobe could not read {path}\n{r.stderr.strip()}")


def card_times(cards_path):
    """Entrance time of every card. The hook is pinned to 0; an endcard is not an entrance beat."""
    try:
        spec = json.loads(Path(cards_path).expanduser().read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"error: could not read cards.json ({cards_path}): {e}")
    if not isinstance(spec, dict) or not isinstance(spec.get("cards"), list):
        sys.exit("error: cards.json must be an object with a top-level \"cards\" list.")
    times = []
    for i, c in enumerate(spec["cards"]):
        if not isinstance(c, dict) or c.get("type") == "endcard":
            continue
        if c.get("type") == "hook":
            times.append(0.0)
            continue
        try:
            times.append(float(c["at"]))
        except (KeyError, TypeError, ValueError):
            sys.exit(f"error: card {i} ({c.get('type')}) has no numeric 'at'")
    return sorted(set(times))


def parse_times(spec):
    try:
        return sorted({float(x) for x in spec.split(",") if x.strip()})
    except ValueError:
        sys.exit(f"error: --at must be comma-separated seconds, got {spec!r}")


def rms_db(path, t, dur=0.5):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(t), "-t", str(dur),
         "-i", str(path), "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
        capture_output=True)
    n = len(r.stdout) // 4
    if not n:
        return -99.0
    s = struct.unpack(f"{n}f", r.stdout[:n * 4])
    return 20 * math.log10(math.sqrt(sum(x * x for x in s) / n) + 1e-9)


def mix(video, sfx, times, out, volume, headroom, ceiling):
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video)]
    filt, mixin = "", "[0:a]"
    for i, t in enumerate(times, start=1):
        cmd += ["-i", str(sfx)]
        ms = int(round(t * 1000))
        filt += f"[{i}:a]adelay={ms}|{ms},volume={volume}[s{i}];"
        mixin += f"[s{i}]"
    filt += (f"{mixin}amix=inputs={len(times) + 1}:normalize=0:duration=first,"
             f"volume={headroom},alimiter=limit={ceiling}:level=false[a]")
    # Same audio contract as the composite: 48 kHz stereo AAC. See reel-compose.py.
    cmd += ["-filter_complex", filt, "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
            "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"error: ffmpeg mix failed\n{r.stderr.strip()}")


def build_parser():
    ap = argparse.ArgumentParser(
        prog="reel-sfx.py",
        description="Mix a sound effect onto every card entrance of a composited reel, reading "
                    "the times from cards.json, then report how many hits are audible.",
        epilog="example:\n"
               "  python3 reel-sfx.py --video composite.mp4 --cards cards.json \\\n"
               "      --sfx whoosh.wav --out final.mp4\n\n"
               "no sound ships with the skill. Use one you have the rights to.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True, help="the composited reel, no effects on it yet")
    ap.add_argument("--out", required=True, help="where to write the reel with effects")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--cards", help="the cards.json this cut was composed from")
    g.add_argument("--at", help="comma-separated times in seconds, when there is no cards.json")
    ap.add_argument("--sfx", default=os.environ.get("REEL_SFX"),
                    help="the sound effect file (default: $REEL_SFX)")
    ap.add_argument("--volume", type=float, default=DEF_VOLUME,
                    help=f"gain on each hit (default: {DEF_VOLUME})")
    ap.add_argument("--headroom", type=float, default=DEF_HEADROOM,
                    help=f"gain on the whole mix before the limiter (default: {DEF_HEADROOM})")
    ap.add_argument("--ceiling", type=float, default=DEF_CEILING,
                    help=f"limiter ceiling, linear (default: {DEF_CEILING})")
    ap.add_argument("--no-verify", action="store_true", help="skip the audibility measurement")
    return ap


def main():
    a = build_parser().parse_args()
    require_tool("ffmpeg")
    require_tool("ffprobe")

    if not a.sfx:
        sys.exit("error: no sound effect given. Pass --sfx <file> or set REEL_SFX.\n"
                 "       None ships with the skill, use a short effect you have the rights to.")
    sfx = Path(a.sfx).expanduser()
    if not sfx.exists():
        sys.exit(f"error: no sound effect at {sfx}")
    video = Path(a.video).expanduser()
    if not video.exists():
        sys.exit(f"error: video not found: {video}")
    out = Path(a.out).expanduser()
    if out.resolve() == video.resolve():
        sys.exit("error: --out must differ from --video, ffmpeg cannot overwrite its own input")

    for name, v in (("volume", a.volume), ("headroom", a.headroom), ("ceiling", a.ceiling)):
        if not (math.isfinite(v) and v > 0):
            sys.exit(f"error: --{name} must be a positive number")

    times = parse_times(a.at) if a.at else card_times(a.cards)
    # A neutral cut ends early, so cards.json can carry entrances past its end.
    # Those cards were dropped by reel-compose.py, so their hits are dropped here.
    dur = duration_of(video)
    late = [t for t in times if t > dur - END_GUARD]
    times = [t for t in times if t <= dur - END_GUARD and t >= 0]
    if late:
        print(f"  NOTE: skipped {len(late)} hit(s) at or past the end of this cut: "
              + ", ".join(f"{t:g}s" for t in late))
    if not times:
        sys.exit("error: no card times inside this video, nothing to place")

    print(f"  {len(times)} hits, {sfx.name}, gain {a.volume}, headroom {a.headroom}, "
          f"ceiling {a.ceiling}")
    mix(video, sfx, times, out, a.volume, a.headroom, a.ceiling)
    print(f"OK {out}")

    if a.no_verify:
        return
    # Compare each hit against the input, compensating for the headroom trim so
    # the comparison is like for like.
    comp = 20 * math.log10(a.headroom)
    lifts = [rms_db(out, t) - (rms_db(video, t) + comp) for t in times]
    heard = sum(1 for x in lifts if x > AUDIBLE_DB)
    print(f"  audible: {heard}/{len(times)} over {AUDIBLE_DB:g} dB, average {sum(lifts)/len(lifts):+.1f} dB, "
          f"quietest {min(lifts):+.1f} dB")
    if heard < len(times) * 0.5:
        print("  NOTE: under half the hits clear 2 dB. Hits under the loudest words are\n"
              "        masked and that is normal, but if it is most of them the sound is too\n"
              "        soft for this track. Use one with a sharper front edge rather than\n"
              "        raising --volume, which only drives the limiter and squashes the voice.")
    r = subprocess.run(["ffmpeg", "-nostdin", "-i", str(out), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "max_volume" in line or "mean_volume" in line:
            print("  " + line.split("] ")[-1])


if __name__ == "__main__":
    main()
