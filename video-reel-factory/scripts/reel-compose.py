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

One cards.json serves both cuts. Endcards are dropped from the full-length run,
because an endcard has no 'out' time and would otherwise cover the tail of the
video, including the spoken call to action.

With --cut it also prints the exact composite command for that cut, matching the
full-length recipe filter for filter. The mirror decision in that command comes
from the prep report, and when prep could not tell, the command carries a
placeholder rather than a guess.

Requires:
  Python 3.8+ (standard library only)
  reel_cards.py next to this file (imported automatically, any working directory)
  a local assets/gsap.min.js in the project, see --gsap
  npx hyperframes to lint, snapshot and render the composition afterwards

Example:
  python3 reel-compose.py --prep prep/prep.json --cards cards.json \\
      --project ./video-projects/my-reel

  # platform variant: cut early and close on an end card
  python3 reel-compose.py --prep prep/prep.json --cards cards.json \\
      --project ./video-projects/my-reel-neutral --cut 62.7

cards.json:
{
  "cards": [
    {"type":"stat","at":1.4,"out":9.2,"eyebrow":"Overnight run","value":12000,
     "sub":"records processed while I was **asleep**"},
    {"type":"endcard","at":62.7,"title":"The full teardown","pill":"Link in the comments"}
  ]
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
TAIL = 4.3   # seconds of end card after a platform cut

# The composite is one recipe with a trim bolted on, so both cuts share these.
# Any difference between the two produces two files that do not match: a source
# that is not already 1080x1920 fails the 9:16 gate without the scale and crop,
# and audio that skipped the chain ships at whatever loudness the room had.
NORMALISE_V = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
CLEAN_A = ("highpass=f=90,afftdn=nr=10,"
           "acompressor=threshold=-18dB:ratio=3:attack=8:release=180,"
           "loudnorm=I=-14:TP=-1.5:LRA=11")
ENCODE = ("-c:v libx264 -preset medium -crf 19 -pix_fmt yuv420p "
          "-c:a aac -b:a 192k -movflags +faststart")

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


def composite_command(cut, fps, flip, out_name="OUT-neutral.mp4"):
    """
    The neutral composite, identical to the full-length recipe apart from the trim
    and the end card tail. Returned as printable lines.
    """
    fade_at = round(cut - 0.5, 2)
    return [
        "ffmpeg -y -i SRC -i overlay.mov -filter_complex \\",
        f'  "[0:v]trim=0:{cut},setpts=PTS-STARTPTS,{flip}fps={fps},{NORMALISE_V},'
        f'tpad=stop_mode=clone:stop_duration={TAIL}[bg];\\',
        "   [bg][1:v]overlay=0:0:format=auto:shortest=1[v];\\",
        f"   [0:a]atrim=0:{cut},asetpts=PTS-STARTPTS,{CLEAN_A},"
        f'afade=t=out:st={fade_at}:d=0.5,apad=pad_dur={TAIL}[a]" \\',
        f'  -map "[v]" -map "[a]" {ENCODE} -r {fps} {out_name}',
    ]


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
                    help="trim content here (seconds) and close on the endcard, for the "
                         "platform-neutral variant. Omit to keep the full length")
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
    a = build_parser().parse_args()

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
    except C.CardValueError as e:
        sys.exit(f"error: {e}")

    # ---- duration, owned in one place
    if a.cut is not None:
        # A card whose entrance is at or after the cut never appears in this
        # variant. Dropping it is right, dropping it silently is not: every other
        # drop path here says which card went and why, and a card that vanished
        # without a word reads like the composer ignored cards.json.
        surviving = []
        for c in cards:
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
            if c.get("out", 0) > a.cut:
                clamped = round(a.cut - 1.8, 2)   # clear before the endcard lands
                if clamped < c.get("at", 0) + 0.5:
                    # The rule is half a second of screen time, not zero: a card
                    # clamped to less than that flashes on and off, which reads as
                    # a glitch rather than a graphic, and a clamp at or before the
                    # entrance leaves it fading in and never leaving.
                    print(f"  NOTE: dropped the {c.get('type')} card at {c.get('at')}s. Pulling "
                          f"its exit back to {clamped}s to clear the end card would leave it on "
                          f"screen for under 0.5s, so there is no room left for it here. It still "
                          "renders on the full-length cut.")
                    continue
                c["out"] = clamped
            kept.append(c)
        cards = kept
        duration = round(a.cut + TAIL, 2)
    else:
        # An endcard is a full-bleed opaque card with no 'out', so on the full cut
        # it fades in and never leaves, covering the last several seconds of video
        # including the spoken call to action. It belongs to the neutral cut only,
        # which is what lets one cards.json serve both runs.
        for c in [c for c in cards if c.get("type") == "endcard"]:
            print(f"  NOTE: dropped the endcard at {c.get('at')}s. An endcard has no 'out' time, "
                  "so on the full-length cut it would fade in and stay, covering the rest of "
                  "the video including the spoken CTA. Endcards render on the --cut variant only.")
        cards = [c for c in cards if c.get("type") != "endcard"]
        duration = round(src_dur, 2)

    # ---- captions, trimmed to the cut
    lines = prep["caption_lines"]
    if a.cut is not None:
        lines = [l for l in lines if l["start"] < a.cut - 0.25]
        for l in lines:
            l["end"] = min(l["end"], a.cut)
            l["words"] = [w for w in l["words"] if w["s"] < a.cut]
        lines = [l for l in lines if l["words"]]

    cap_css, cap_html, cap_js = C.captions(lines)

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

    flip, flip_note = resolve_flip(prep)

    kinds = ", ".join(f"{c['type']}@{c['at']}s" for c in cards)
    print(f"OK {proj}/index.html")
    print(f"  {duration}s @ {a.fps}fps, {len(lines)} caption lines, {len(cards)} cards")
    print(f"  cards: {kinds}")
    print(f"  {flip_note}")
    if a.cut is not None:
        print(f"  platform cut at {a.cut}s plus a {TAIL}s end card")
        print(f"\n  composite with:")
        for line in composite_command(a.cut, a.fps, flip):
            print(f"    {line}")


if __name__ == "__main__":
    main()
