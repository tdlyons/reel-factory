#!/usr/bin/env python3
"""
reel-compose.py: assemble a Hyperframes composition from prep.json + cards.json.

Takes the mechanical output of reel-prep.py (captions, cut points) and a small
cards.json describing which motion graphics to show, and writes a valid
composition plus its project config.

The composition's duration is declared in three places that must agree:
hyperframes.json, the root data-duration attribute, and SLOT_DURATION. Drift
between them silently produces a truncated render, so this script owns all
three and refuses to emit if they disagree.

One cards.json serves both cuts. Every reel needs exactly one `hook` card,
which is pinned to t=0 and fully opaque on the first frame, and the build is
refused without it.

The neutral cut (--cut) ends on live footage at the cut point. No end card and
no frozen tail: a full-bleed card at the end of a vertical video stops it dead
and breaks the loop. Endcards are dropped with a note on every run unless --cut
is given together with --endcard, which restores the old 4.3 second end card
tail for work that is not going to a social feed.

It also prints the exact composite command for the variant it built, so the
full-length and neutral recipes stay identical filter for filter. The mirror
decision in that command comes from the prep report, and when prep could not
tell, the command carries a placeholder rather than a guess. The audio is
encoded as 48 kHz stereo AAC, see ENCODE below for why both numbers matter.

Requires:
  Python 3.8+ (standard library only)
  reel_cards.py next to this file (imported automatically, any working directory)
  a local assets/gsap.min.js in the project, see --gsap
  npx hyperframes to lint, snapshot and render the composition afterwards

Example:
  python3 reel-compose.py --prep prep/prep.json --cards cards.json \\
      --project ./video-projects/my-reel

  # platform variant: end at the cut, on live footage
  python3 reel-compose.py --prep prep/prep.json --cards cards.json \\
      --project ./video-projects/my-reel-neutral --cut 62.7

cards.json:
{
  "cards": [
    {"type":"hook","out":3.9,"kicker":"I left it running overnight","text":"12,000 records. **0 clicks**."},
    {"type":"stat","at":4.4,"out":9.2,"eyebrow":"Overnight run","value":12000,
     "sub":"records processed while I was **asleep**"}
  ],
  "caption_moves": [{"at":30.0,"top":1100,"size":52}]
}
"""

import argparse, json, shutil, sys
from pathlib import Path

# Resolve this script's own directory so `import reel_cards` works from any
# working directory, and so a symlinked copy still finds its library.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import reel_cards as C
except ImportError:
    sys.exit("error: could not import reel_cards.py.\n"
             "       It must sit in the same directory as reel-compose.py.")

FPS = 30
TAIL = 4.3   # seconds of end card after a platform cut, only with --endcard
EXIT_CLEAR = 0.5   # a card's exit tween has to finish before the last frame
FADE_OUT = 0.3     # audio fade on the neutral cut's last moment, so it ends without a click

# Dead air: the longest stretch with no card on screen before the composer says
# so. Tighter at the start, because the first seconds decide whether anyone stays.
DEAD_AIR_EARLY = 3.0     # within the first DEAD_AIR_WINDOW seconds
DEAD_AIR_LATE = 5.0      # after it
DEAD_AIR_WINDOW = 30.0

# The composite is one recipe with a trim bolted on, so both cuts share these.
# Any difference between the two produces two files that do not match: a source
# that is not already 1080x1920 fails the 9:16 gate without the scale and crop,
# and audio that skipped the chain ships at whatever loudness the room had.
NORMALISE_V = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
CLEAN_A = ("highpass=f=90,afftdn=nr=10,"
           "acompressor=threshold=-18dB:ratio=3:attack=8:release=180,"
           "loudnorm=I=-14:TP=-1.5:LRA=11")
# -ar 48000 is not optional. loudnorm resamples to 192 kHz internally, and the
# AAC encoder then writes 96 kHz audio unless told otherwise, which QuickTime and
# iPhone play as silence. -ac 2 because a 1-channel track is routed to a centre
# speaker on some multi-channel playback devices and plays silent there; stereo
# plays everywhere, and a mono recording simply lands on both channels.
# reel-verify.py fails a cut that is not 48 or 44.1 kHz, or not 2 channels.
ENCODE = ("-c:v libx264 -preset medium -crf 19 -pix_fmt yuv420p "
          "-c:a aac -ar 48000 -ac 2 -b:a 192k -movflags +faststart")

# Printed instead of a flip decision when prep could not read any in-frame text.
# A wrong flip is unrecoverable once it ships, which is why the detector refuses
# to guess, so this refuses too. Pasted as-is, ffmpeg rejects it.
FLIP_PLACEHOLDER = "<<<ADD hflip HERE ONLY IF THE PREP REPORT SAID FLIP>>>"


def resolve_flip(prep):
    """
    Three states, matching reel-prep.py's detector: flip, do not flip, cannot tell.
    Returns (filter fragment, a line explaining the choice).
    """
    mirror = prep.get("mirror") or {}
    verdict = mirror.get("suggest_flip")
    if verdict is True:
        return "hflip,", ("mirror: prep says the source IS mirrored, so the composite needs hflip. "
                          "Look at a frame and confirm before you render.")
    if verdict is False:
        return "", "mirror: prep says the source is NOT mirrored, so the composite must not flip it."
    reason = mirror.get("note") or mirror.get("reason") or "prep could not tell"
    return FLIP_PLACEHOLDER + ",", (
        f"mirror: CANNOT TELL ({reason}). Nothing here will guess for you, so the composite "
        "carries a placeholder. Pull a frame: if text in the room reads backwards, replace the "
        "placeholder with hflip, and if it does not, delete the placeholder and the comma "
        "after it.")


def composite_command(cut, fps, flip, finished_audio=False, endcard_tail=False,
                      out_name=None):
    """
    The composite for one variant, as printable lines. The full-length and the
    neutral cut are one recipe: the neutral cut only adds the trim, a short audio
    fade, and with --endcard the frozen tail the end card sits on.
    """
    audio = "" if finished_audio else CLEAN_A
    if cut is None:
        out_name = out_name or "OUT.mp4"
        a_chain = audio or "anull"
        return [
            "ffmpeg -y -i SRC -i overlay.mov -filter_complex \\",
            f'  "[0:v]{flip}fps={fps},{NORMALISE_V}[bg];\\',
            "   [bg][1:v]overlay=0:0:format=auto:shortest=1[v];\\",
            f'   [0:a]{a_chain}[a]" \\',
            f'  -map "[v]" -map "[a]" {ENCODE} -r {fps} {out_name}',
        ]
    out_name = out_name or "OUT-neutral.mp4"
    tail_v = f",tpad=stop_mode=clone:stop_duration={TAIL}" if endcard_tail else ""
    if endcard_tail:
        fade = f"afade=t=out:st={round(cut - 0.5, 2)}:d=0.5,apad=pad_dur={TAIL}"
    else:
        fade = f"afade=t=out:st={round(cut - FADE_OUT, 2)}:d={FADE_OUT}"
    a_chain = f"atrim=0:{cut},asetpts=PTS-STARTPTS," + (f"{audio}," if audio else "") + fade
    return [
        "ffmpeg -y -i SRC -i overlay.mov -filter_complex \\",
        f'  "[0:v]trim=0:{cut},setpts=PTS-STARTPTS,{flip}fps={fps},{NORMALISE_V}{tail_v}[bg];\\',
        "   [bg][1:v]overlay=0:0:format=auto:shortest=1[v];\\",
        f'   [0:a]{a_chain}[a]" \\',
        f'  -map "[v]" -map "[a]" {ENCODE} -r {fps} {out_name}',
    ]


def dead_air(cards, duration):
    """
    Stretches with no card on screen that run longer than the limits above, as
    (start, length) pairs. The hook counts as a card. A tail with no card is
    deliberate, since the video should end on live footage, so the gap after the
    last card is never reported.
    """
    spans = sorted((c.get("at", 0), c.get("out", duration)) for c in cards)
    gaps, prev = [], 0.0
    for at, out in spans:
        limit = DEAD_AIR_EARLY if prev < DEAD_AIR_WINDOW else DEAD_AIR_LATE
        if at - prev > limit:
            gaps.append((round(prev, 2), round(at - prev, 2)))
        prev = max(prev, out)
    return gaps


def load_json(path, label):
    p = Path(path).expanduser()
    if not p.exists():
        sys.exit(f"error: {label} not found: {p}")
    try:
        with open(p) as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        sys.exit(f"error: {label} is not valid JSON ({p}): {e}")


def build_parser():
    ap = argparse.ArgumentParser(
        prog="reel-compose.py",
        description="Build a Hyperframes composition (index.html + hyperframes.json) from "
                    "reel-prep.py output and a cards.json spec.",
        epilog="example:\n"
               "  python3 reel-compose.py --prep prep/prep.json --cards cards.json \\\n"
               "      --project ./video-projects/my-reel --cut 62.7\n\n"
               "run `python3 reel_cards.py --list` to see the card types cards.json accepts.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prep", required=True,
                    help="prep.json written by reel-prep.py (captions, probe data, cut plan)")
    ap.add_argument("--cards", required=True,
                    help="cards.json describing the motion graphics: {\"cards\": [...]}")
    ap.add_argument("--project", required=True,
                    help="hyperframes project dir, created if absent")
    ap.add_argument("--cut", type=float, default=None,
                    help="end the composition here (seconds), on live footage, for the "
                         "platform-neutral variant. Omit to keep the full length")
    ap.add_argument("--endcard", action="store_true",
                    help="with --cut only: add a 4.3s frozen tail and render the endcard on it. "
                         "Not for social cuts, where an end card breaks the loop")
    ap.add_argument("--finished-audio", action="store_true",
                    help="the source audio is already mixed and levelled, so the printed composite "
                         "skips the highpass, denoise, compressor and loudnorm chain built for raw "
                         "mic recordings and only re-encodes it")
    ap.add_argument("--fps", type=int, default=FPS,
                    help=f"frames per second for the composition (default: {FPS})")
    ap.add_argument("--caption-top", type=int, default=None,
                    help="move the caption band off its default y, needed when the bottom of "
                         "the frame is occupied by a reaction PiP or burned-in UI")
    ap.add_argument("--gsap", default=None,
                    help="path to a gsap.min.js to copy into the project's assets/. GSAP must be "
                         "local because headless Chrome will not reliably fetch a CDN at render time")
    return ap


def main():
    ap = build_parser()
    a = ap.parse_args()
    if a.endcard and a.cut is None:
        ap.error("--endcard only applies to a --cut variant")

    prep = load_json(a.prep, "prep.json")
    spec = load_json(a.cards, "cards.json")
    if "cards" not in spec:
        sys.exit("error: cards.json must be an object with a top-level \"cards\" list.")
    if "caption_lines" not in prep or "probe" not in prep:
        sys.exit("error: prep.json is missing 'caption_lines' or 'probe'. "
                 "Regenerate it with reel-prep.py.")

    # Caption timings go into the inline GSAP timeline unescaped, the same sink as
    # the card numbers, and prep.json is a file the owner is told to hand-edit. A
    # string here is rejected by name before anything is written to disk.
    try:
        prep["caption_lines"] = C.normalise_caption_lines(prep["caption_lines"])
    except C.CardValueError as e:
        sys.exit(f"error: {e}")

    # Checked before the project is written, so a typo in --gsap does not leave a
    # half-built project behind for someone to find and trust later.
    gsap_src = None
    if a.gsap:
        gsap_src = Path(a.gsap).expanduser()
        if not gsap_src.exists():
            sys.exit(f"error: --gsap file not found: {gsap_src}")

    # Resolved now, created later. Nothing is written until every input has been
    # validated, so a bad card or a card that outlives the composition leaves no
    # half-built project behind for someone to find and trust.
    proj = Path(a.project).expanduser().resolve()

    W, H = 1080, 1920
    src_dur = prep["probe"]["duration"]

    # ---- cards, validated before any of their numbers are used
    try:
        cards = [C.normalise_card(i, c) for i, c in enumerate(spec["cards"])]
        moves = C.normalise_caption_moves(spec.get("caption_moves"))
    except C.CardValueError as e:
        sys.exit(f"error: {e}")

    # ---- HARD RULE: a visible hook on frame 0.
    # A viewer decides in the first frame. A reel whose first graphic arrives at
    # 3s has already lost the scroll, so this is a build error, not a warning.
    hooks = [c for c in cards if c.get("type") == "hook"]
    if not hooks:
        sys.exit("error: REFUSING TO BUILD, no hook card.\n"
                 "       Every reel needs a visible hook on screen at frame 0. Add\n"
                 '       {"type":"hook","out":<seconds>,"kicker":"...","text":"..."} to cards.json.\n'
                 "       The hook is pinned to t=0 and renders fully opaque with no fade-in.")
    if len(hooks) > 1:
        sys.exit(f"error: REFUSING TO BUILD, {len(hooks)} hook cards. Expected exactly 1.")
    hook = hooks[0]
    if hook.get("out") is None or hook["out"] <= 0:
        sys.exit("error: REFUSING TO BUILD, the hook card needs an 'out' time greater than 0.")
    if hook.get("at") not in (None, 0):
        print(f"  NOTE: the hook card's 'at' of {hook['at']}s is ignored. A hook is always "
              "pinned to 0, because a hook that arrives late is not a hook.")
    hook["at"] = 0

    # ---- duration, owned in one place
    if a.cut is not None:
        # A card whose entrance is at or after the cut never appears in this
        # variant. Dropping it is right, dropping it silently is not: every other
        # drop path here says which card went and why, and a card that vanished
        # without a word reads like the composer ignored cards.json.
        if a.cut <= hook["out"]:
            sys.exit(f"error: the cut at {a.cut}s lands while the hook is still on screen "
                     f"(out {hook['out']}s). That is not a cut point, check neutral_cut in prep.json.")
        surviving = []
        for c in cards:
            if c.get("type") == "endcard" and not a.endcard:
                print(f"  NOTE: dropped the endcard at {c.get('at')}s. The neutral cut ends on live "
                      "footage at the cut point, because a full-bleed card at the end of a vertical "
                      "video stops it dead and breaks the loop. Pass --endcard to render one anyway.")
                continue
            if c.get("type") != "endcard" and c.get("at", 0) >= a.cut:
                print(f"  NOTE: dropped the {c.get('type')} card at {c.get('at')}s. The cut lands at "
                      f"{a.cut}s, so this card would never appear in this variant. It still renders "
                      "on the full-length one.")
                continue
            surviving.append(c)
        cards = surviving
        kept = []
        for c in cards:
            if c.get("type") == "endcard":
                # The endcard always lands on the cut point, so its authored 'at'
                # is overwritten rather than honoured. Say so, because a cut moved
                # after cards.json was written otherwise looks like it was ignored.
                if c.get("at") != a.cut:
                    print(f"  NOTE: moved the endcard from {c.get('at')}s to the cut point at "
                          f"{a.cut}s. An endcard always opens on the cut.")
                c["at"] = a.cut
                kept.append(c)
                continue
            # With an end card the exit clears 1.8s before it lands. Without one
            # the exit tween only has to finish before the last frame.
            limit = round(a.cut - (1.8 if a.endcard else EXIT_CLEAR), 2)
            what = "clear the end card" if a.endcard else "finish its exit before the last frame"
            if c.get("out", 0) > limit:
                clamped = limit
                if clamped < c.get("at", 0) + 0.5:
                    # The rule is half a second of screen time, not zero: a card
                    # clamped to less than that flashes on and off, which reads as
                    # a glitch rather than a graphic, and a clamp at or before the
                    # entrance leaves it fading in and never leaving.
                    print(f"  NOTE: dropped the {c.get('type')} card at {c.get('at')}s. Pulling "
                          f"its exit back to {clamped}s to {what} would leave it on "
                          f"screen for under 0.5s, so there is no room left for it here. It still "
                          "renders on the full-length cut.")
                    continue
                c["out"] = clamped
            kept.append(c)
        cards = kept
        duration = round(a.cut + (TAIL if a.endcard else 0), 2)
    else:
        # An endcard is a full-bleed opaque card with no 'out', so on the full cut
        # it fades in and never leaves, covering the last several seconds of video
        # including the spoken call to action. It belongs to the neutral cut only,
        # which is what lets one cards.json serve both runs.
        for c in [c for c in cards if c.get("type") == "endcard"]:
            print(f"  NOTE: dropped the endcard at {c.get('at')}s. An endcard has no 'out' time, "
                  "so on the full-length cut it would fade in and stay, covering the rest of "
                  "the video including the spoken CTA. Carry the CTA on a normal card over live "
                  "footage instead.")
        cards = [c for c in cards if c.get("type") != "endcard"]
        duration = round(src_dur, 2)

    # ---- captions, trimmed to the cut
    lines = prep["caption_lines"]
    if a.cut is not None:
        lines = [l for l in lines if l["start"] < a.cut - 0.25]
        for l in lines:
            l["end"] = min(l["end"], a.cut)
            # Keep a word only if it ENDS by the cut. A word that starts before
            # the cut and finishes after it has its audio truncated, and the
            # caption would highlight a word the viewer never hears finish.
            l["words"] = [w for w in l["words"] if w["e"] <= a.cut]
            if l["words"]:
                l["text"] = " ".join(str(w.get("w", "")) for w in l["words"])
        lines = [l for l in lines if l["words"]]
        moves = [m for m in moves if m["at"] < duration]

    cap_css, cap_html, cap_js = C.captions(lines)
    cap_js += C.caption_moves_js(moves)

    css_parts, html_parts, js_parts = [C.BASE_CSS, cap_css], [], [cap_js]
    if a.caption_top is not None:
        css_parts.append(f"\n#caps{{top:{a.caption_top}px}}")
    for i, c in enumerate(cards):
        if c.get("type") != "endcard" and c.get("out", 0) > duration:
            sys.exit(f"error: card {i} ({c['type']}) exits at {c['out']}s but the composition "
                     f"is {duration}s")
        try:
            css, html, js = C.render_card(i, c)
        except C.CardValueError as e:
            sys.exit(f"error: {e}")
        css_parts.append(css); html_parts.append(html); js_parts.append(js)

    # ---- dead air: long stretches of talking head with nothing to look at.
    # Advisory. Fill a gap with something that shows the claim being made at that
    # moment, or leave it; a card that carries nothing is worse than the gap.
    for start, length in dead_air(cards, duration):
        print(f"  WARN: {length}s with no card from {start}s. Over {DEAD_AIR_EARLY:g}s in the first "
              f"{DEAD_AIR_WINDOW:g}s, or {DEAD_AIR_LATE:g}s after that, is dead air on a vertical feed.")
    on_at_end = [c for c in cards if c.get("type") != "endcard" and c.get("out", 0) >= duration - 0.05]
    for c in on_at_end:
        print(f"  WARN: the {c['type']} card is still on screen at the last frame. End on live "
              "footage so the video loops.")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width={W}, height={H}">
<style>{''.join(css_parts)}</style></head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{duration}"
     data-fps="{a.fps}" data-width="{W}" data-height="{H}">
{''.join(html_parts)}
{cap_html}
</div>
<script src="assets/gsap.min.js"></script>
<script>
const SLOT_DURATION = {duration};
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{''.join(js_parts)}
tl.to({{}}, {{ duration: SLOT_DURATION }}, 0);
window.__timelines["main"] = tl;
</script>
</body></html>"""

    # ---- the three declarations must agree, or the render silently truncates.
    # A real check rather than an assert, because python3 -O strips asserts and
    # this is the one guard standing between a drifted duration and a truncated
    # render that nothing downstream would notice.
    if (f'data-duration="{duration}"' not in html
            or f"const SLOT_DURATION = {duration};" not in html):
        sys.exit("error: internal check failed, the composition's duration declarations do not "
                 "agree.\n       Refusing to write a project that would render truncated.")

    # Everything above this line can still refuse the run. From here it writes.
    (proj / "assets").mkdir(parents=True, exist_ok=True)
    (proj / "renders").mkdir(exist_ok=True)

    cfg_path = proj / "hyperframes.json"
    cfg = json.load(open(cfg_path)) if cfg_path.exists() else {
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
    }
    cfg.update({"width": W, "height": H, "fps": a.fps, "duration": duration})
    with open(cfg_path, "w") as fh:
        json.dump(cfg, fh, indent=2)
    (proj / "index.html").write_text(html)

    # gsap must be local, headless Chrome will not reliably fetch a CDN at render time
    gs = proj / "assets" / "gsap.min.js"
    if not gs.exists():
        if gsap_src is not None:
            shutil.copy(gsap_src, gs)
        else:
            for cand in (proj.parent).glob("*/assets/gsap.min.js"):
                shutil.copy(cand, gs); break
            else:
                print("  WARN: no local gsap.min.js found, so the render will be blank.")
                print("        Pass --gsap /path/to/gsap.min.js, or download the minified GSAP")
                print(f"        build from https://gsap.com/ into {gs}")

    for c in cards:
        if c.get("type") == "image" and not (proj / str(c["src"])).exists():
            print(f"  WARN: image card at {c['at']}s points at {c['src']}, which is not in "
                  f"{proj}. Copy it in before rendering or the card renders empty.")

    flip, flip_note = resolve_flip(prep)

    kinds = ", ".join(f"{c['type']}@{c['at']}s" for c in cards)
    print(f"OK {proj}/index.html")
    print(f"  {duration}s @ {a.fps}fps, {len(lines)} caption lines, {len(cards)} cards")
    print(f"  cards: {kinds}")
    print(f"  {flip_note}")
    if moves:
        print(f"  caption moves: " + ", ".join(f"@{m['at']}s" for m in moves))
    if a.cut is not None:
        if a.endcard:
            print(f"  platform cut at {a.cut}s plus a {TAIL}s end card")
        else:
            print(f"  platform cut at {a.cut}s, ending on live footage")
    if a.finished_audio:
        print("  audio: finished mix, re-encoded only")
    print(f"\n  composite with (SRC is your recording, overlay.mov the absolute path of the render):")
    for line in composite_command(a.cut, a.fps, flip, a.finished_audio, a.endcard):
        print(f"    {line}")


if __name__ == "__main__":
    main()
