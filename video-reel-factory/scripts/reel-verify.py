#!/usr/bin/env python3
"""
reel-verify.py: deterministic goal checks on a RENDERED reel.

Everything here inspects the finished file, not the intent. The pipeline can
believe it cut at 62.4s and still ship 94s because an ffmpeg filter silently
no-oped, and the only way to know is to measure the output.

The load-bearing check is NO_CTA_LEAK: re-transcribe the rendered cut and
assert that no platform-specific speech survived. Shipping a neutral video that
says "comment TEARDOWN" is the single most embarrassing failure this pipeline
can produce, and it is fully detectable.

Requires:
  Python 3.8+ plus openai-whisper for transcription (pip install -U openai-whisper)
  reel_markers.py next to this file (imported automatically, any working directory)
  ffmpeg and ffprobe on PATH

Example:
  python3 reel-verify.py rendered.mp4 --profile neutral --expect-duration 67.0
  python3 reel-verify.py rendered.mp4 --profile neutral --keywords TEARDOWN
  python3 reel-verify.py rendered.mp4 --profile instagram --keywords TEARDOWN
  python3 reel-verify.py rendered.mp4 --profile neutral --json

Non-zero means do not post. Zero means every gate that ran passed, which is not
quite the same thing: a gate can report SKIP because it had nothing to check or
could not finish its measurement, and the summary line says so when one does.
Read the summary, not only the exit code.
"""

import argparse, json, shutil, subprocess, sys, tempfile
from pathlib import Path

# Resolve this script's own directory so `import reel_markers` works from any
# working directory, and so a symlinked copy still finds its library.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from reel_markers import NEUTRAL_FORBIDDEN, collapse, find_keyword_hits
except ImportError:
    sys.exit("error: could not import reel_markers.py.\n"
             "       It must sit in the same directory as reel-verify.py.")

INSTALL_HINTS = {
    "ffmpeg": "Install ffmpeg. macOS: brew install ffmpeg. Debian/Ubuntu: sudo apt install ffmpeg.",
    "ffprobe": "ffprobe ships with ffmpeg. macOS: brew install ffmpeg. Debian/Ubuntu: sudo apt install ffmpeg.",
}


def require_tool(name):
    """Fail with a readable message instead of a FileNotFoundError traceback."""
    if shutil.which(name) is None:
        sys.exit(f"error: '{name}' was not found on PATH.\n       {INSTALL_HINTS.get(name, '')}".rstrip())


def run(c, **k):
    try:
        return subprocess.run(c, capture_output=True, text=True, **k)
    except FileNotFoundError:
        sys.exit(f"error: '{c[0]}' was not found on PATH.\n       {INSTALL_HINTS.get(c[0], '')}".rstrip())


def _fps(rate):
    """ffprobe reports r_frame_rate as a fraction like '30000/1001'."""
    try:
        num, den = (str(rate).split("/") + ["1"])[:2]
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0


def probe(p):
    r = run(["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(p)])
    if r.returncode != 0 or not r.stdout.strip():
        # Not a hard exit: an unreadable file is exactly what FILE_VALID is for,
        # so report it through the gates and keep the exit code meaningful.
        return {"duration": 0.0, "w": None, "h": None, "fps": 0, "has_audio": False,
                "size_mb": 0.0, "ffprobe_error": (r.stderr.strip() or "ffprobe produced no output")}
    d = json.loads(r.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {"duration": float(d.get("format", {}).get("duration", 0)),
            "w": v.get("width"), "h": v.get("height"),
            "fps": _fps(v.get("r_frame_rate")) if v.get("r_frame_rate") else 0,
            "has_audio": bool(a), "size_mb": round(int(d.get("format", {}).get("size", 0)) / 1048576, 1)}


# A frame is flat when its brightest and darkest pixels are the same, whatever
# its mean. WHITE_FLOOR and BLACK_CEIL sit inside limited range on purpose: the
# pipeline encodes -pix_fmt yuv420p, where a pure white frame measures YAVG 233
# and a pure black one 16, so a full-range 250/4 test can never fire.
FLAT_SPREAD = 12        # YMAX minus YMIN at or below this means one colour
NEAR_FLAT_SPREAD = 40   # at or below this, near enough to blank for its mean to count
WHITE_FLOOR = 230       # YAVG at or above this, on a near-flat frame, is blown out
BLACK_CEIL = 20         # YAVG at or below this, on a near-flat frame, is dead black

# What each test catches, measured on frames this pipeline rendered and
# composited itself. The spread test catches a frame that is one colour edge to
# edge: pure white (spread 0), pure black (0), mid-grey (0), a card whose
# background painted but whose text never did (0), and a card whose children all
# rendered at zero opacity (0). The mean bounds are a second pass, and they apply
# only to a frame that is ALREADY nearly uniform, because a full-bleed white end
# card is legitimately bright. Ten real end cards, from a one-word close to a
# dense four-slot one, measured YAVG 225.0 to 232.5 at spreads of 153 to 184, and
# six of them failed a bare YAVG >= 230 test, one of them by 0.02. The second
# pass catches a frame that is mostly one value with a small deviant patch, for
# example a near-black frame with a stray blob (spread 38, YAVG 16.4). It does
# NOT catch a luminance ramp across the whole frame: on a ramp the mean falls
# away from the bound about as fast as the spread grows, so a white ramp at
# spread 13 already measures YAVG 221.6 and passes. No blank this pipeline emits
# is a ramp. Every blank the renderer actually produces is flat, spread 0 to 2,
# and the spread test alone catches all of them.
#
# What a luma histogram cannot see: a card that painted its background AND some
# decoration but not its text. One measured YAVG 232.87 at spread 162, which sits
# between a legitimate one-word end card at 231.77 and a legitimately empty one
# at 232.46, so no threshold separates them. That failure shape belongs to the
# compose-time snapshot check, where you look at the frame, and not to this gate.

# Where in the file to sample. Runs into the tail deliberately, because the end
# card is the last thing drawn and a blank or half-drawn one has to be visible
# to this gate rather than falling off the end of the sampling window.
SAMPLE_FIRST = 0.04
SAMPLE_LAST = 0.97


def _luma_stats(png):
    """
    YMIN, YAVG and YMAX for one still, from ffmpeg's signalstats filter.

    One call, printing every key signalstats emits, and the three that matter are
    read out of it. Returns None when the metrics are not there, which the caller
    counts as a frame it failed to measure rather than a frame that looked fine.
    """
    r = run(["ffmpeg", "-v", "error", "-i", str(png), "-vf",
             "signalstats,metadata=print:file=-", "-f", "null", "-"])
    vals = {}
    for line in r.stdout.splitlines():
        key, _, val = line.strip().partition("=")
        name = key.rsplit(".", 1)[-1]
        if name in ("YMIN", "YAVG", "YMAX"):
            try:
                vals[name] = float(val)
            except ValueError:
                pass
    if len(vals) < 3:
        return None
    return vals


def blank_frames(path, dur, n=8):
    """
    Sample frames across the whole output and flag any that carry no picture.

    A renderer that seeks onto an unpopulated timeline emits pure white, which in
    limited range reads YAVG 233, and a composite that lost its video stream emits
    pure black at 16. A flat MID-GREY frame sits at 124 and clears any mean bound
    there is, so the spread between YMIN and YMAX carries the check: a frame whose
    lightest and darkest pixel are the same has nothing drawn on it. The mean
    bounds are a second pass over frames that are already nearly uniform, for the
    almost-blank ones carrying a little encoder noise, a vignette or a gradient.

    Returns (bad, sampled, wanted). `sampled` counts frames actually measured. A
    truncated file keeps a valid moov atom at the front, so it probes clean while
    no frame decodes, and every extraction fails silently. A caller that asked for
    8 frames and measured 0 has not inspected the video and must not call it clean.
    """
    bad, sampled = [], 0
    if dur <= 0 or n < 2:
        return bad, sampled, 0
    with tempfile.TemporaryDirectory() as td:
        for i in range(n):
            frac = SAMPLE_FIRST + (SAMPLE_LAST - SAMPLE_FIRST) * i / (n - 1)
            t = dur * frac
            f = Path(td) / f"f{i}.png"
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path),
                 "-frames:v", "1", "-vf", "scale=64:-1", str(f)])
            if not f.exists():
                continue
            st = _luma_stats(f)
            if st is None:
                continue
            sampled += 1
            spread = st["YMAX"] - st["YMIN"]
            why = None
            if spread <= FLAT_SPREAD:
                why = "flat, one colour edge to edge"
            elif spread <= NEAR_FLAT_SPREAD and st["YAVG"] >= WHITE_FLOOR:
                why = "near-uniform and blown out to white"
            elif spread <= NEAR_FLAT_SPREAD and st["YAVG"] <= BLACK_CEIL:
                why = "near-uniform and dead black"
            if why:
                bad.append({"at": round(t, 2), "yavg": round(st["YAVG"], 1),
                            "spread": round(spread, 1), "why": why})
    return bad, sampled, n


# When a decode is long enough that silence in it is a fault rather than a short
# clip, and how few letters count as having heard nothing. See transcribe().
SILENT_MIN_AUDIO = 3.0
HEARD_FLOOR = 12


def transcribe(path, model="small", expect_dur=None, tolerance=0.6):
    """
    Re-transcribe the rendered file. Returns (text, error).

    `error` is None when the transcription can be trusted, and otherwise a string
    saying why it cannot. It is never an empty transcript reported as success: a
    truncated render hands Whisper a short or header-only wav, Whisper returns
    little or nothing, and an absence check reading that would report that no
    platform speech survived when in fact nothing was heard at all. The caller
    fails the gate on `error`.

    Two ways that goes wrong, and both are checked. The audio can come up SHORT of
    the container's own duration, which is what a truncation looks like: an mp4
    written with +faststart keeps a complete moov atom at the front, so ffprobe
    keeps reporting the full length no matter how much of the file is missing, and
    the decoded audio is the only honest measurement of how much is really there.
    That is measured against `tolerance`, the same slack the duration gate allows,
    because anything looser lets most of a render go missing while the run still
    reads clean. Or the audio can be full length and SILENT, which is not a cut
    CTA either, only a broken mix.

    A missing whisper package or an unloadable model still exits outright. Those
    are setup problems rather than measurements of this file.
    """
    try:
        import whisper
    except ImportError:
        sys.exit("error: the 'whisper' Python package is not installed, so the CTA-leak gate "
                 "cannot run.\n"
                 "       Install it with: pip install -U openai-whisper\n"
                 "       Refusing to report a pass without it.")
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "a.wav"
        r = run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1",
                 "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
        if not wav.exists():
            return "", ("ffmpeg could not extract any audio from the render, so nothing was "
                        f"heard to check: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else 'no error output'}")
        got = probe(wav)["duration"]
        if expect_dur and expect_dur > 1 and (expect_dur - got) > tolerance:
            return "", (f"only {round(got, 2)}s of audio decoded out of the {round(expect_dur, 2)}s "
                        f"the container claims, {round(expect_dur - got, 2)}s short of it against a "
                        f"{tolerance}s tolerance. The file is truncated or its audio is broken, so the "
                        "silence that follows is not evidence of a clean cut")
        try:
            m = whisper.load_model(model)
        except Exception as e:
            sys.exit(f"error: Whisper could not load the '{model}' model, so the CTA-leak gate "
                     "cannot run.\n"
                     "       Models download on first use, so check the name (tiny, base, small,\n"
                     "       medium, large) and your network connection.\n"
                     f"       {type(e).__name__}: {e}")
        text = m.transcribe(str(wav), language="en", fp16=False).get("text", "")
        # Full-length audio that Whisper heard nothing in is the same false pass
        # as a truncated decode wearing different clothes: the absence check would
        # report that no platform speech survived, when the truth is that no
        # speech was there to survive. HEARD_FLOOR letters is a couple of words,
        # well under any real line of narration and above Whisper's habit of
        # answering silence with "you" or "Thank you.".
        if got > SILENT_MIN_AUDIO and len(collapse(text)) < HEARD_FLOOR:
            return "", (f"{round(got, 2)}s of audio decoded but almost nothing was heard in it "
                        f"(Whisper returned {text.strip()[:40]!r}). Silence is not evidence that the "
                        "CTA was cut, only that nothing was audible")
        return text, None


def build_parser():
    ap = argparse.ArgumentParser(
        prog="reel-verify.py",
        description="Measure a rendered reel against deterministic gates: valid file, 9:16 "
                    "aspect, duration, no blank frames, and no platform-specific speech left "
                    "in a neutral cut. Exits non-zero if any gate fails.",
        epilog="example:\n"
               "  python3 reel-verify.py neutral.mp4 --profile neutral --expect-duration 67.0\n"
               "  python3 reel-verify.py full.mp4 --profile instagram --keywords TEARDOWN\n\n"
               "needs ffmpeg and ffprobe on PATH, plus the openai-whisper package.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="path to the rendered .mp4 to check")
    ap.add_argument("--profile", choices=["neutral", "instagram"], default="neutral",
                    help="neutral: assert NO platform-specific speech survived (default). "
                         "instagram: the full-length cut that keeps the spoken CTA, assert the "
                         "keyword IS present")
    ap.add_argument("--expect-duration", type=float, default=None,
                    help="expected output duration in seconds. Adds the DURATION_MATCHES_SPEC gate")
    ap.add_argument("--tolerance", type=float, default=0.6,
                    help="seconds of slack allowed on --expect-duration, and the same slack "
                         "allowed between the container's stated duration and the audio that "
                         "actually decodes out of it (default: 0.6)")
    ap.add_argument("--keywords", default="",
                    help="comma-separated CTA keywords. Under --profile instagram they MUST be "
                         "audible; under --profile neutral they must NOT be, and are checked "
                         "alongside the built-in platform markers. Matched on the collapsed form, "
                         "because Whisper renders TEARDOWN as 'tear down'")
    ap.add_argument("--model", default="small",
                    help="Whisper model used for the re-transcription: tiny, base, small, "
                         "medium, large (default: small, the same default reel-prep.py uses. "
                         "A weaker model can miss a keyword a stronger one hears, and on the "
                         "neutral profile a missed keyword is a pass that should have been a fail)")
    ap.add_argument("--json", action="store_true",
                    help="emit the full gate report as JSON instead of a human-readable table")
    return ap


def main():
    import re
    a = build_parser().parse_args()

    require_tool("ffprobe")
    require_tool("ffmpeg")

    src = Path(a.video).expanduser()
    if not src.exists():
        sys.exit(f"error: not found: {src}")

    gates, info = [], probe(src)

    def gate(name, ok, detail, skipped=False):
        gates.append({"gate": name, "pass": bool(ok), "detail": detail, "skipped": bool(skipped)})

    def report_and_exit():
        failed = [g for g in gates if not g["pass"]]
        skipped = [g for g in gates if g["skipped"]]
        passed = not failed
        # A gate that did not run, or that only got part of its measurement, is not
        # a gate that passed, so the summary says so.
        if failed:
            summary = "GATES FAILED, DO NOT POST"
        elif skipped:
            summary = ("EVERY GATE THAT RAN PASSED, but " + ", ".join(g["gate"] for g in skipped)
                       + " did not run in full. That is not a clean pass, decide deliberately")
        else:
            summary = "ALL GATES PASSED, safe to post"
        if a.json:
            print(json.dumps({"video": str(src), "profile": a.profile,
                              "pass": passed, "skipped": [g["gate"] for g in skipped],
                              "summary": summary, "gates": gates, "probe": info}, indent=1))
        else:
            print(f"\n  {src.name}  [{a.profile}]")
            for g in gates:
                mark = "SKIP" if g["skipped"] else ("PASS" if g["pass"] else "FAIL")
                print(f"  {mark}  {g['gate']:<24} {g['detail']}")
            print(f"\n  {summary}\n")
        sys.exit(0 if passed else 1)

    keywords = [k.strip() for k in a.keywords.split(",") if k.strip()]

    # --- structural
    gate("FILE_VALID", info["duration"] > 1 and info["w"] and info["has_audio"],
         info.get("ffprobe_error") or
         f"{info['w']}x{info['h']} @ {round(info['fps'],2)}fps, {round(info['duration'],2)}s, "
         f"audio {'yes' if info['has_audio'] else 'MISSING'}")

    # An unreadable file is exactly what FILE_VALID is for. Report it through the
    # normal table, so --json still emits something parseable, and stop before the
    # later gates try to sample frames or transcribe a file ffprobe could not open.
    if info.get("ffprobe_error"):
        gate("VERTICAL_9x16", False, "not checked, the file could not be read")
        if a.expect_duration is not None:
            gate("DURATION_MATCHES_SPEC", False, "not checked, the file could not be read")
        gate("NO_BLANK_FRAMES", False, "not checked, the file could not be read")
        gate("NO_CTA_LEAK" if a.profile == "neutral" else "CTA_PRESENT", False,
             "not checked, the file could not be read")
        report_and_exit()

    gate("VERTICAL_9x16", info["h"] and info["w"] and abs((info["w"] / info["h"]) - 9 / 16) < 0.02,
         f"aspect {round(info['w']/info['h'],4) if (info['h'] and info['w']) else '?'} (want 0.5625)")

    if a.expect_duration is not None:
        d = abs(info["duration"] - a.expect_duration)
        gate("DURATION_MATCHES_SPEC", d <= a.tolerance,
             f"rendered {round(info['duration'],2)}s vs expected {a.expect_duration}s "
             f"(delta {round(d,2)}s)")

    # --- visual integrity
    blanks, sampled, wanted = blank_frames(src, info["duration"])
    if sampled * 2 < wanted:
        # Nothing was measured, so there is nothing to be clean. A file truncated
        # mid-write keeps its moov atom and probes fine while no frame decodes,
        # and every extraction above failed quietly.
        gate("NO_BLANK_FRAMES", False,
             f"could not sample the video: only {sampled} of {wanted} frames decoded. "
             "The file is truncated or its video stream is broken")
    elif blanks:
        gate("NO_BLANK_FRAMES", False,
             f"{len(blanks)} blank frame(s) of {sampled} sampled: {blanks}")
    elif sampled < wanted:
        # Enough decoded to judge what was seen, not enough to judge the file. A
        # frame that will not decode is a broken file whatever the frames around it
        # look like, and this gate could not take its full measurement, so it is
        # hedged rather than passed. The summary line says so too.
        gate("NO_BLANK_FRAMES", True,
             f"INCOMPLETE: no blank frames in the {sampled} of {wanted} frames that decoded, "
             f"but {wanted - sampled} did not decode at all. The file is damaged or truncated, "
             "so this is not a clean pass", skipped=True)
    else:
        gate("NO_BLANK_FRAMES", True, f"clean, {sampled}/{wanted} frames sampled")

    # --- the one that matters
    cta_gate = "NO_CTA_LEAK" if a.profile == "neutral" else "CTA_PRESENT"
    if a.profile == "instagram" and not keywords:
        # Nothing to assert the presence of, so the transcription is skipped rather
        # than run for nothing, and it is reported as skipped rather than as a pass.
        gate(cta_gate, True,
             "SKIPPED, --profile instagram checks that a keyword IS audible and none "
             "was given. Pass --keywords to run it", skipped=True)
        report_and_exit()

    text, audio_err = transcribe(src, a.model, info["duration"], a.tolerance)
    if audio_err:
        gate(cta_gate, False, f"could not check: {audio_err}")
        report_and_exit()
    text = text.lower()

    if a.profile == "neutral":
        leaks = []
        for pat, label in NEUTRAL_FORBIDDEN:
            for m in re.finditer(pat, text):
                leaks.append({"label": label, "phrase": m.group(0)[:40]})
        # A keyword the owner named is platform-specific speech by definition, so
        # the neutral cut must not contain it either. Collapsed-form match, because
        # Whisper renders TEARDOWN as "tear down" and a literal token would miss it.
        for k in find_keyword_hits(text, keywords):
            leaks.append({"label": f"custom keyword '{k}'", "phrase": collapse(k)})
        gate("NO_CTA_LEAK", not leaks,
             "no platform-specific speech survived the cut" if not leaks
             else f"LEAKED: {leaks}. This cut says something only one platform should hear")
    else:
        # Whisper renders coined words as ordinary ones (TEARDOWN to "tear down"),
        # so match on the collapsed form rather than the literal token.
        heard = set(find_keyword_hits(text, keywords))
        missing = [k for k in keywords if k not in heard]
        gate("CTA_PRESENT", not missing,
             "keyword spoken" if not missing else f"expected CTA not heard: {missing}")

    report_and_exit()


if __name__ == "__main__":
    main()
