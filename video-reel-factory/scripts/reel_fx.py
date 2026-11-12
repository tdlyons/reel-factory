#!/usr/bin/env python3
"""
reel_fx.py: the effects library.

One list of every effect the skill can produce, and the code that produces it.
The list is the source of truth: `python3 reel_fx.py --list` prints it, and
`--json` exports it, so a page or a menu built from it cannot promise an effect
the code does not have.

Effects come in two kinds, because the pipeline has two layers.

  Drawn in the overlay (the Hyperframes composition), as cards in cards.json:
    title      text over the footage with a named text motion and a named look
    checklist  items that tick on one at a time
    cutaway    a full-frame photo or clip with a named transition in and out
  plus two caption modes, `keyword` and `stack`.

  Applied to the footage or the sound in the ffmpeg composite, as top-level keys
  in cards.json next to "cards":
    "footage": [{"move": "push-in", "at": 4.0, "out": 9.0}]   camera moves
    "grade": "warm"                                            a colour grade
    "music": {"file": "bed.mp3"}                               a music bed, ducked

Every style gets these: reel_cards.render_with falls back to REGISTRY here when
a style has no card of that type, and the looks read the style's own CSS
variables, so a title on the `panel` style is drawn in the panel palette.

The cards obey the render contract in reel_cards.py: paired tl.set() and
tl.to(), no tl.call(), no fromTo(), nothing that reads the clock or a random
number. Every piece of a staggered text motion is written out as its own
statement here in Python, so the page carries no loop that could reorder.

Requires: Python 3.8+ (standard library only). Imported by reel-compose.py.

Example:
  python3 reel_fx.py --list
  python3 reel_fx.py --json > effects.json
"""

import json
import math

import reel_cards as C
from reel_cards import _esc, _attr, _num, CardValueError

W, H = 1080, 1920

# --------------------------------------------------------------------------
# TEXT MOTIONS
# --------------------------------------------------------------------------
# grain  what moves on its own: each letter, each word, each line, or the block
# frm/to the start and end state of one piece
# stag   seconds between one piece starting and the next
# order  which piece goes first: start (reading order), centre (middle out),
#        edges (both ends in)
# mask   the piece slides out from behind a hidden edge instead of fading
TEXT_MOTIONS = {
    # --- letter by letter
    "blur-in": dict(grain="char", frm={"opacity": 0, "filter": "blur(10px)", "y": 8},
                    to={"opacity": 1, "filter": "blur(0px)", "y": 0}, dur=.5, ease="power2.out",
                    stag=.028, say="Letters come into focus out of a soft blur."),
    "letter-rise": dict(grain="char", frm={"opacity": 0, "yPercent": 75},
                        to={"opacity": 1, "yPercent": 0}, dur=.5, ease="back.out(1.8)",
                        stag=.03, say="Each letter lifts up into place with a small bounce."),
    "typewriter": dict(grain="char", kind="type", stag=.045,
                       say="Letters type on, one at a time."),
    "letters-up": dict(grain="char", mask=True, frm={"yPercent": 112}, to={"yPercent": 0},
                       dur=.52, ease="power3.out", stag=.028,
                       say="Letters slide up from behind a hidden line."),
    "letters-down": dict(grain="char", mask=True, frm={"yPercent": -112}, to={"yPercent": 0},
                         dur=.52, ease="power3.out", stag=.028,
                         say="Letters drop down from behind a hidden line."),
    "from-centre": dict(grain="char", order="centre", frm={"opacity": 0, "y": 12, "scale": .78},
                        to={"opacity": 1, "y": 0, "scale": 1}, dur=.48, ease="power2.out",
                        stag=.03, say="The middle letters show first, then it spreads outward."),
    "from-edges": dict(grain="char", order="edges", frm={"opacity": 0, "y": 12, "scale": .78},
                       to={"opacity": 1, "y": 0, "scale": 1}, dur=.48, ease="power2.out",
                       stag=.03, say="The two ends show first, then it closes to the middle."),
    # --- word by word
    "word-fade": dict(grain="word", frm={"opacity": 0}, to={"opacity": 1}, dur=.5,
                      ease="sine.inOut", stag=.15, say="Words fade in one after another."),
    "word-bounce": dict(grain="word", frm={"opacity": 0, "scale": .4},
                        to={"opacity": 1, "scale": 1}, dur=.85, ease="elastic.out(1,0.55)",
                        stag=.09, say="Words pop in with a springy bounce."),
    "word-rise": dict(grain="word", frm={"opacity": 0, "y": 28}, to={"opacity": 1, "y": 0},
                      dur=.5, ease="power3.out", stag=.07, say="Words rise up into place."),
    "word-build": dict(grain="word", order="centre", frm={"opacity": 0, "scale": .5},
                       to={"opacity": 1, "scale": 1}, dur=.55, ease="back.out(1.5)", stag=.08,
                       say="The line builds outward from its middle word."),
    "slide-right": dict(grain="word", frm={"opacity": 0, "x": -24}, to={"opacity": 1, "x": 0},
                        dur=.42, ease="power2.out", stag=.06,
                        say="Words slide a short way in from the left."),
    "slide-down": dict(grain="word", frm={"opacity": 0, "y": -24}, to={"opacity": 1, "y": 0},
                       dur=.42, ease="power2.out", stag=.06,
                       say="Words drop a short way in from above."),
    "word-depth": dict(grain="word", frm={"opacity": 0, "z": -260, "y": 26,
                                          "transformPerspective": 700},
                       to={"opacity": 1, "z": 0, "y": 0, "transformPerspective": 700},
                       dur=.7, ease="power2.out", stag=.1,
                       say="Words fly forward from the back of the screen."),
    # --- line by line
    "line-reveal": dict(grain="line", mask=True, frm={"yPercent": 112}, to={"yPercent": 0},
                        dur=.6, ease="power4.out", stag=.14,
                        say="Each line slides up from behind a hidden edge."),
    "line-slide": dict(grain="line", frm={"opacity": 0, "x": -44}, to={"opacity": 1, "x": 0},
                       dur=.52, ease="power3.out", stag=.16,
                       say="Lines slide in from the left, one at a time."),
    # --- the whole block
    "settle": dict(grain="all", frm={"opacity": 0, "scale": .975}, to={"opacity": 1, "scale": 1},
                   dur=.5, ease="power2.out", say="A quiet fade with a tiny settle. The calm one."),
    "shimmer": dict(grain="all", kind="shimmer", dur=1.1,
                    say="The text fades in and a band of light sweeps across it."),
    "grow-in": dict(grain="all", frm={"opacity": 0, "scale": .8}, to={"opacity": 1, "scale": 1},
                    dur=.52, ease="power3.out", say="The text grows toward you as it fades in."),
    "ease-down": dict(grain="all", frm={"opacity": 0, "scale": 1.2}, to={"opacity": 1, "scale": 1},
                      dur=.56, ease="power2.out", say="The text starts large and eases down to size."),
    "focus-pull": dict(grain="all", frm={"opacity": 0, "filter": "blur(14px)", "scale": 1.05},
                       to={"opacity": 1, "filter": "blur(0px)", "scale": 1}, dur=.7,
                       ease="power2.out", say="A heavy blur pulls into sharp focus."),
    "slide-in": dict(grain="all", frm={"opacity": 0, "x": 46}, to={"opacity": 1, "x": 0},
                     dur=.52, ease="power3.out", say="The text slides in from the right."),
    "fade-through": dict(grain="all", frm={"opacity": 0, "scale": .92},
                         to={"opacity": 1, "scale": 1}, dur=.32, ease="power1.out",
                         say="A fast, clean fade. Good for swapping one line for the next."),
}
DEFAULT_MOTION = "word-rise"

# How a title leaves. Exits move the whole block, and they ease in (they speed
# up as they go), because something leaving should get out of the way.
TEXT_EXITS = {
    "fade": dict(to={"opacity": 0}, dur=.35, ease="power1.in", say="Fades out."),
    "blur-away": dict(to={"opacity": 0, "y": -24, "filter": "blur(8px)"}, dur=.45,
                      ease="power2.in", say="Blurs and lifts away."),
    "lift": dict(to={"opacity": 0, "y": -34}, dur=.4, ease="power2.in", say="Lifts up and out."),
    "drop": dict(to={"opacity": 0, "y": 34}, dur=.4, ease="power2.in", say="Drops down and out."),
    "shrink": dict(to={"opacity": 0, "scale": .86}, dur=.38, ease="power2.in",
                   say="Shrinks back and out."),
}
DEFAULT_EXIT = "fade"

# What the text sits on.
TITLE_LOOKS = {
    "plain": "Bold white text straight on the footage.",
    "plate": "The text on a card surface, in the colours of the style.",
    "takeover": "A giant phrase fills the whole frame over a dark wash.",
    "rule": "A title with a coloured rule that draws in under it. The title card.",
    "ticker": "A phrase sweeps across a coloured band, like a news ticker.",
}

# --------------------------------------------------------------------------
# TRANSITIONS (for the cutaway card)
# --------------------------------------------------------------------------
TRANSITIONS = {
    "cut": "A clean instant cut. No blend.",
    "fade": "The shot dissolves in over the footage.",
    "zoom": "The shot pushes through the frame toward you.",
    "whip": "A fast sideways swipe hands off the frame.",
    "blur": "The shot pulls into focus out of a heavy blur.",
    "wipe": "The shot wipes down over the last one.",
}
# Slow movement on a cutaway while it is up, so a photo never sits frozen.
CUTAWAY_MOVES = {
    "push": "A slow push in.",
    "pull": "A slow pull back.",
    "pan": "A slow drift sideways.",
    "none": "No movement.",
}

# --------------------------------------------------------------------------
# FOOTAGE MOVES, GRADES, MUSIC (the ffmpeg composite)
# --------------------------------------------------------------------------
FOOTAGE_MOVES = {
    "push-in": "A slow push in on the speaker. The cinematic default.",
    "pull-out": "A slow pull back that opens up the frame.",
    "punch-in": "A hard zoom cut, to hit one line.",
    "pan": "A slow drift across the frame.",
    "reframe": "A smooth move to a tighter framing, held, then back.",
}
MOVE_DEFAULT_AMOUNT = {"push-in": 1.12, "pull-out": 1.12, "punch-in": 1.18, "pan": 1.12,
                       "reframe": 1.25}

# Each grade is a plain ffmpeg filter chain. It goes on the footage before the
# overlay is laid on, so it never touches a card or a caption.
GRADES = {
    "cinematic": ("eq=contrast=1.09:saturation=1.08,"
                  "colorbalance=rs=-0.07:bs=0.07:rm=0.01:bm=-0.01:rh=0.06:bh=-0.07",
                  "Richer contrast, with teal in the shadows and amber in the highlights."),
    "warm": ("colorbalance=rm=0.07:bm=-0.07:rh=0.05:bh=-0.06,eq=saturation=1.06",
             "A sunlit warmth."),
    "cool": ("colorbalance=rm=-0.06:bm=0.07:rs=-0.03:bs=0.05,eq=saturation=0.97",
             "A calm, cool cast."),
    "film": ("curves=all='0/0.065 0.5/0.5 1/0.955',eq=saturation=0.86",
             "Soft contrast, lifted blacks, a little less colour."),
    "mono": ("hue=s=0,eq=contrast=1.08", "Black and white."),
}

MUSIC_DEFAULT_LEVEL = -20.0   # dB applied to the music file before the mix

CAPTION_STYLES = {
    "phrase": "A line at a time, and each word lights up as it is spoken.",
    "pulse": "One word at a time, big, in capitals, centre frame.",
    "keyword": "The whole line at once, with one key word picked out in colour.",
    "stack": "Two bold lines that stack in, one after the other.",
    "none": "No captions, for footage that already has them.",
}

# The fields each fx card accepts, for --list and for whoever writes cards.json.
CARD_FIELDS = {
    "title": "text (required, supports **accent**, \\n for a line break), motion, exit, look, "
             "sub (rule look only), size, y, align (left, center, right)",
    "checklist": "items (list of strings, required, supports **accent**), title, stagger, y",
    "cutaway": "src (required, a photo or a video clip, a path relative to the project dir), "
               "in, exit (transition names), move (push, pull, pan, none), from (seconds into "
               "a clip to start at)",
}


def _where(i, kind):
    return f"card {i} ({kind})"


def _choice(c, key, options, default, i, kind):
    v = c.get(key, default)
    if v not in options:
        raise CardValueError(f"{_where(i, kind)}: '{key}' is {v!r}. Choose one of: "
                             f"{', '.join(options)}")
    return v


def _js(props):
    return json.dumps(props, separators=(",", ":"))


# --------------------------------------------------------------------------
# shared CSS. Reads the style's variables where it has them (the panel style
# sets --accent, --glass, --font-head; the clean style sets --blue and --ink)
# and falls back to plain values, so every style gets a title that matches it.
# --------------------------------------------------------------------------
BASE_CSS = """
:root{--fx-accent:var(--accent,var(--blue,#0071e3));--fx-on-accent:var(--on-accent,#fff);
  --fx-plate:var(--glass,#fff);--fx-plate-ink:var(--ink,#1d1d1f);
  --fx-head:var(--font-head,inherit)}
.fxt{position:absolute;left:70px;width:940px;opacity:0;font-family:var(--fx-head);
  font-weight:800;letter-spacing:-.025em;line-height:1.08;color:#fff;
  text-shadow:0 4px 22px rgba(0,0,0,.9),0 2px 6px rgba(0,0,0,.85)}
.fxt .ac{color:var(--fx-accent)}
.fxt.plate{background:var(--fx-plate);color:var(--fx-plate-ink);text-shadow:none;
  border-radius:30px;padding:42px 48px;box-shadow:0 30px 90px rgba(0,0,0,.34)}
.fxl{display:block}
.fxw{display:inline-block;white-space:nowrap}
.fxp{display:inline-block;will-change:transform}
.fxm{display:inline-block;overflow:hidden;vertical-align:bottom;padding:.14em .04em;margin:-.14em -.04em}
.fxshim{background:linear-gradient(100deg,#fff 0%,#fff 42%,var(--fx-accent) 50%,#fff 58%,#fff 100%);
  background-size:300% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;
  text-shadow:none;filter:drop-shadow(0 4px 14px rgba(0,0,0,.85))}
.fxscrim{position:absolute;left:0;top:0;width:1080px;height:1920px;background:rgba(0,0,0,.74);opacity:0}
.fxrule{height:10px;border-radius:5px;background:var(--fx-accent);margin-top:22px;
  transform-origin:0 50%}
.fxsub{font-size:34px;font-weight:600;letter-spacing:0;margin-top:20px;opacity:0}
.fxband{position:absolute;left:0;width:1080px;background:var(--fx-accent);overflow:hidden;opacity:0}
.fxband .run{position:absolute;left:0;top:0;white-space:nowrap;font-family:var(--fx-head);font-weight:800;
  color:var(--fx-on-accent);letter-spacing:-.01em}
.fxchk{position:absolute;left:60px;width:960px;padding:40px 44px;opacity:0;
  background:var(--fx-plate);color:var(--fx-plate-ink);border-radius:30px;
  box-shadow:0 30px 90px rgba(0,0,0,.34)}
.fxchk h4{font-family:var(--fx-head);font-size:34px;font-weight:700;margin-bottom:26px;letter-spacing:-.02em}
.fxchk .li{display:flex;align-items:flex-start;gap:20px;margin-bottom:20px;opacity:0}
.fxchk .tick{flex:none;width:46px;height:46px;border-radius:50%;background:var(--fx-accent);
  display:flex;align-items:center;justify-content:center}
.fxchk .tick svg{width:26px;height:26px;stroke:var(--fx-on-accent);stroke-width:4.5;fill:none;
  stroke-linecap:round;stroke-linejoin:round}
.fxchk .t{font-size:30px;line-height:1.35;padding-top:4px}
.fxchk .ac{color:var(--fx-accent);font-weight:700}
.fxcut{position:absolute;left:0;top:0;width:1080px;height:1920px;overflow:hidden;opacity:0;
  background:#000}
.fxcut img,.fxcut video{position:absolute;left:0;top:0;width:1080px;height:1920px;object-fit:cover}
"""


def base_css():
    return BASE_CSS


# --------------------------------------------------------------------------
# splitting text into the pieces a motion moves
# --------------------------------------------------------------------------
def _segments(text):
    """'a **b c** d' -> [('a ', False), ('b c', True), (' d', False)]."""
    return [(p, bool(k % 2)) for k, p in enumerate(str(text).split("**")) if p]


def _words(text):
    """Every word of one line as (word, accent)."""
    out = []
    for seg, accent in _segments(text):
        out += [(w, accent) for w in seg.split()]
    return out


def _wrap(text, per_line):
    """Greedy wrap of one paragraph into lines of at most per_line characters,
    keeping the ** accent marks balanced on every line."""
    lines, cur, n = [], [], 0
    for w, accent in _words(text):
        if cur and n + 1 + len(w) > per_line:
            lines.append(cur)
            cur, n = [], 0
        cur.append((w, accent))
        n += len(w) + (1 if n else 0)
    if cur:
        lines.append(cur)
    return lines


def split_text(text, grain, cid, size, width=940, mask=False):
    """
    The HTML for a title's text, split to the grain a motion needs, and the ids
    of the pieces in reading order. Line breaks come from \\n in the text when
    there are any, otherwise from a wrap sized to the font.
    """
    per_line = max(6, int(width / (size * 0.5)))
    lines = []
    for para in str(text).split("\n"):
        if not para.strip():
            continue
        lines += _wrap(para, per_line) if "\n" not in str(text) else [_words(para)]
    ids, html, k = [], [], 0

    def piece(inner):
        nonlocal k
        pid = f"{cid}p{k}"
        k += 1
        ids.append(pid)
        span = f'<span class="fxp" id="{pid}">{inner}</span>'
        return f'<span class="fxm">{span}</span>' if mask else span

    for line in lines:
        if grain == "line":
            inner = " ".join(f'<b class="ac">{_esc(w)}</b>' if a else _esc(w) for w, a in line)
            html.append(f'<span class="fxl">{piece(inner)}</span>')
            continue
        words = []
        for w, a in line:
            cls = ' class="ac"' if a else ""
            if grain == "char":
                chars = "".join(piece(f"<b{cls}>{_esc(ch)}</b>" if a else _esc(ch)) for ch in w)
                words.append(f'<span class="fxw">{chars}</span>')
            elif grain == "word":
                words.append(piece(f"<b{cls}>{_esc(w)}</b>" if a else _esc(w)))
            else:
                words.append(f"<b{cls}>{_esc(w)}</b>" if a else _esc(w))
        html.append(f'<span class="fxl">{" ".join(words)}</span>')
    if grain == "all":
        pid = f"{cid}p0"
        return f'<span class="fxp" id="{pid}" style="display:block">{"".join(html)}</span>', [pid]
    return "".join(html), ids


def _order(n, how):
    """The start slot of each of n pieces: reading order, middle out, or ends in."""
    mid = (n - 1) / 2
    if how == "centre":
        return [abs(k - mid) for k in range(n)]
    if how == "edges":
        return [mid - abs(k - mid) for k in range(n)]
    return list(range(n))


def motion_js(name, ids, at):
    """The timeline statements that play one text motion on the given pieces."""
    m = TEXT_MOTIONS[name]
    slots = _order(len(ids), m.get("order", "start"))
    js = []
    if m.get("kind") == "type":
        for pid, s in zip(ids, slots):
            js.append(f'tl.set("#{pid}",{{opacity:0}},0);')
            js.append(f'tl.set("#{pid}",{{opacity:1}},{round(at + s * m["stag"], 3)});')
        return "\n".join(js), at + len(ids) * m["stag"]
    if m.get("kind") == "shimmer":
        pid = ids[0]
        js.append(f'tl.set("#{pid}",{{opacity:0,backgroundPosition:"100% 0"}},0);')
        js.append(f'tl.to("#{pid}",{{opacity:1,duration:.3,ease:"power1.out"}},{at});')
        js.append(f'tl.to("#{pid}",{{backgroundPosition:"0% 0",duration:{m["dur"]},'
                  f'ease:"power2.inOut"}},{round(at + .15, 3)});')
        return "\n".join(js), at + .15 + m["dur"]
    to = dict(m["to"], duration=m["dur"], ease=m["ease"])
    stag = m.get("stag", 0)
    for pid, s in zip(ids, slots):
        js.append(f'tl.set("#{pid}",{_js(m["frm"])},0);')
        js.append(f'tl.to("#{pid}",{_js(to)},{round(at + s * stag, 3)});')
    return "\n".join(js), at + max(slots) * stag + m["dur"]


def exit_js(name, sel, out):
    e = TEXT_EXITS[name]
    return f'tl.to("{sel}",{_js(dict(e["to"], duration=e["dur"], ease=e["ease"]))},{out});'


# --------------------------------------------------------------------------
# CARDS
# --------------------------------------------------------------------------
def title(i, c):
    """
    Text over the footage, with a named motion in, a named exit and a named look.
    This is the card every text motion in TEXT_MOTIONS plays on.
    """
    kind = "title"
    if not str(c.get("text") or "").strip():
        raise CardValueError(f"{_where(i, kind)}: missing required field 'text'")
    look = _choice(c, "look", TITLE_LOOKS, "plain", i, kind)
    motion = _choice(c, "motion", TEXT_MOTIONS, DEFAULT_MOTION, i, kind)
    leave = _choice(c, "exit", TEXT_EXITS, DEFAULT_EXIT, i, kind)
    align = _choice(c, "align", ("left", "center", "right"), "center" if look != "rule" else "left",
                    i, kind)
    at, out = c["at"], c["out"]
    cid = f"ti{i}"

    if look == "ticker":
        size = c.get("size", 64)
        y = c.get("y", 300)
        band_h = round(size * 1.7)
        css = (f"\n#{cid}{{top:{y}px;height:{band_h}px}}"
               f"\n#{cid} .run{{font-size:{size}px;line-height:{band_h}px}}")
        plain = " ".join(w for w, _ in _words(c["text"]))
        html = (f'<div class="fxband" id="{cid}"><div class="run" id="{cid}r">'
                f'{_esc(plain)}</div></div>')
        run = max(1.2, out - at)
        js = f"""
tl.set("#{cid}",{{opacity:0,scaleY:.2}},0);
tl.to("#{cid}",{{opacity:1,scaleY:1,duration:.3,ease:"power3.out"}},{at});
tl.set("#{cid}r",{{x:{W},xPercent:0}},0);
tl.to("#{cid}r",{{x:0,xPercent:-100,duration:{round(run, 3)},ease:"none"}},{at});
tl.to("#{cid}",{{opacity:0,scaleY:.2,duration:.3,ease:"power2.in"}},{out});"""
        return css, html, js

    takeover = look == "takeover"
    size = c.get("size", 150 if takeover else 76 if look != "plate" else 60)
    width = 844 if look == "plate" else 940
    m = TEXT_MOTIONS[motion]
    inner, ids = split_text(c["text"], m["grain"], cid, size, width, m.get("mask", False))
    if m.get("kind") == "shimmer":
        inner = inner.replace('class="fxp"', 'class="fxp fxshim"', 1)
    if takeover:
        y = c.get("y", 300)
        box = f"top:{y}px;height:{1560 - y}px;display:flex;flex-direction:column;justify-content:center;"
    else:
        box = f"top:{c.get('y', 300)}px;"
    css = (f"\n#{cid}{{{box}font-size:{size}px;text-align:{align}"
           + (";text-transform:uppercase;line-height:.98" if takeover else "") + "}")
    extra_html, extra_js = "", []
    if look == "rule":
        extra_html = f'<div class="fxrule" id="{cid}u"></div>'
        extra_js.append(f'tl.set("#{cid}u",{{scaleX:0}},0);')
        extra_js.append(f'tl.to("#{cid}u",{{scaleX:1,duration:.6,ease:"power3.out"}},{round(at + .12, 3)});')
        if c.get("sub"):
            extra_html += f'<div class="fxsub" id="{cid}s">{C._rich(c["sub"])}</div>'
            extra_js.append(f'tl.set("#{cid}s",{{opacity:0,y:14}},0);')
            extra_js.append(f'tl.to("#{cid}s",{{opacity:1,y:0,duration:.45,ease:"power2.out"}},'
                            f'{round(at + .4, 3)});')
    scrim = f'<div class="fxscrim" id="{cid}k"></div>' if takeover else ""
    html = (scrim + f'<div class="fxt{" plate" if look == "plate" else ""}" id="{cid}">'
            f'{inner}{extra_html}</div>')
    play, _ = motion_js(motion, ids, round(at + (.12 if look == "plate" else 0), 3))
    js = [f'tl.set("#{cid}",{{opacity:0}},0);']
    if look == "plate":
        js.append(f'tl.set("#{cid}",{{y:30}},0);')
        js.append(f'tl.to("#{cid}",{{opacity:1,y:0,duration:.4,ease:"power3.out"}},{at});')
    else:
        js.append(f'tl.set("#{cid}",{{opacity:1}},{at});')
    if takeover:
        js.append(f'tl.set("#{cid}k",{{opacity:0}},0);')
        js.append(f'tl.to("#{cid}k",{{opacity:1,duration:.25,ease:"power1.out"}},{at});')
        js.append(f'tl.to("#{cid}k",{{opacity:0,duration:.35,ease:"power1.in"}},{out});')
    js.append(play)
    js += extra_js
    js.append(exit_js(leave, f"#{cid}", out))
    return css, html, "\n".join(js)


def checklist(i, c):
    """Items that tick on one at a time. For steps done, or what is included."""
    kind = "checklist"
    items = c.get("items")
    if not isinstance(items, list) or not items:
        raise CardValueError(f"{_where(i, kind)}: 'items' must be a list with at least one item")
    cid = f"ck{i}"
    at, out = c["at"], c["out"]
    tick = '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.6 4.6L19 7.5"/></svg>'
    rows = "".join(
        f'<div class="li" id="{cid}i{k}"><span class="tick" id="{cid}t{k}">{tick}</span>'
        f'<span class="t">{C._rich(t)}</span></div>' for k, t in enumerate(items))
    css = f"\n#{cid}{{top:{c.get('y', C.ZONE_LOWER)}px}}"
    head = f'<h4>{_esc(c["title"])}</h4>' if c.get("title") else ""
    html = f'<div class="fxchk" id="{cid}">{head}{rows}</div>'
    js = [f'tl.set("#{cid}",{{opacity:0,y:50}},0);',
          f'tl.to("#{cid}",{{opacity:1,y:0,duration:.5,ease:"power3.out"}},{at});']
    step = c.get("stagger", 0.8)
    for k in range(len(items)):
        t = round(at + 0.45 + k * step, 3)
        js.append(f'tl.set("#{cid}i{k}",{{opacity:0,x:-16}},0);')
        js.append(f'tl.to("#{cid}i{k}",{{opacity:1,x:0,duration:.35,ease:"power2.out"}},{t});')
        js.append(f'tl.set("#{cid}t{k}",{{scale:0}},0);')
        js.append(f'tl.to("#{cid}t{k}",{{scale:1,duration:.42,ease:"back.out(2.4)"}},{round(t + .1, 3)});')
    js.append(f'tl.to("#{cid}",{{opacity:0,y:-30,duration:.45,ease:"power2.in"}},{out});')
    return css, html, "\n".join(js)


VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v")

_CUT_IN = {
    "cut": None,
    "fade": ({"opacity": 0}, {"opacity": 1, "duration": .4, "ease": "power1.inOut"}),
    "zoom": ({"opacity": 0, "scale": 1.6, "filter": "blur(14px)"},
             {"opacity": 1, "scale": 1, "filter": "blur(0px)", "duration": .45, "ease": "power3.out"}),
    "whip": ({"opacity": 1, "x": W, "filter": "blur(26px)"},
             {"x": 0, "filter": "blur(0px)", "duration": .34, "ease": "power4.out"}),
    "blur": ({"opacity": 0, "filter": "blur(34px)"},
             {"opacity": 1, "filter": "blur(0px)", "duration": .55, "ease": "power2.out"}),
    "wipe": ({"opacity": 1, "clipPath": "inset(0% 0% 100% 0%)"},
             {"clipPath": "inset(0% 0% 0% 0%)", "duration": .5, "ease": "power3.inOut"}),
}
_CUT_OUT = {
    "cut": None,
    "fade": {"opacity": 0, "duration": .4, "ease": "power1.inOut"},
    "zoom": {"opacity": 0, "scale": 1.6, "filter": "blur(14px)", "duration": .4, "ease": "power3.in"},
    "whip": {"x": -W, "filter": "blur(26px)", "duration": .32, "ease": "power4.in"},
    "blur": {"opacity": 0, "filter": "blur(34px)", "duration": .5, "ease": "power2.in"},
    "wipe": {"clipPath": "inset(100% 0% 0% 0%)", "duration": .5, "ease": "power3.inOut"},
}


def cutaway(i, c):
    """
    A full-frame photo or clip laid over the speaker, with a named transition in
    and out. The speaker's audio carries on underneath. Cards and captions drawn
    after it sit on top of it like on any other footage.
    """
    kind = "cutaway"
    if not c.get("src"):
        raise CardValueError(f"{_where(i, kind)}: missing required field 'src'")
    t_in = _choice(c, "in", TRANSITIONS, "cut", i, kind)
    t_out = _choice(c, "exit", TRANSITIONS, "cut", i, kind)
    move = _choice(c, "move", CUTAWAY_MOVES, "push", i, kind)
    at, out = c["at"], c["out"]
    if out - at < 0.8:
        raise CardValueError(f"{_where(i, kind)}: a cutaway needs at least 0.8s on screen")
    cid, mid = f"cw{i}", f"cw{i}m"
    src = str(c["src"])
    is_video = src.lower().endswith(VIDEO_EXT)
    start = _num(c.get("from", 0), "from", i, kind)
    if is_video:
        media = (f'<video id="{mid}" src="{_attr(src)}" muted playsinline preload="auto" '
                 f'data-start="{at}" data-duration="{round(out - at, 3)}" '
                 f'data-media-start="{start}" data-track-index="{40 + i}"></video>')
    else:
        media = f'<img id="{mid}" src="{_attr(src)}" alt="">'
    html = f'<div class="fxcut" id="{cid}">{media}</div>'
    js = [f'tl.set("#{cid}",{{opacity:0}},0);']
    frm_to = _CUT_IN[t_in]
    if frm_to is None:
        js.append(f'tl.set("#{cid}",{{opacity:1}},{at});')
    else:
        frm, to = frm_to
        # the from-state is held from 0, but invisible until `at`
        js.append(f'tl.set("#{cid}",{_js(dict(frm, opacity=0))},0);')
        js.append(f'tl.set("#{cid}",{_js(frm)},{at});')
        js.append(f'tl.to("#{cid}",{_js(to)},{at});')
    # one continuous camera move for as long as the shot is up
    hold = round(out - at + .5, 3)
    if move == "push":
        js.append(f'tl.set("#{mid}",{{scale:1}},0);')
        js.append(f'tl.to("#{mid}",{{scale:1.09,duration:{hold},ease:"none"}},{at});')
    elif move == "pull":
        js.append(f'tl.set("#{mid}",{{scale:1.09}},0);')
        js.append(f'tl.to("#{mid}",{{scale:1,duration:{hold},ease:"none"}},{at});')
    elif move == "pan":
        js.append(f'tl.set("#{mid}",{{scale:1.1,x:-36}},0);')
        js.append(f'tl.to("#{mid}",{{x:36,duration:{hold},ease:"none"}},{at});')
    leave = _CUT_OUT[t_out]
    if leave is None:
        js.append(f'tl.set("#{cid}",{{opacity:0}},{out});')
    else:
        js.append(f'tl.to("#{cid}",{_js(leave)},{out});')
        js.append(f'tl.set("#{cid}",{{opacity:0}},{round(out + leave["duration"], 3)});')
    return "", html, "\n".join(js)


REGISTRY = {"title": title, "checklist": checklist, "cutaway": cutaway}


# --------------------------------------------------------------------------
# CAPTION MODES
# --------------------------------------------------------------------------
def _keyword_index(words):
    """The word to pick out: one marked "k": true in prep.json, else the longest."""
    for j, w in enumerate(words):
        if w.get("k") is True:
            return j
    best, best_len = 0, -1
    for j, w in enumerate(words):
        n = len("".join(ch for ch in str(w.get("w", "")) if ch.isalnum()))
        if n >= best_len:
            best, best_len = j, n
    return best


def keyword_captions(lines, cid="caps"):
    """The whole line at once, one key word picked out in the accent colour."""
    html = []
    for i, ln in enumerate(lines):
        key = _keyword_index(ln["words"])
        spans = "".join(
            f'<span class="cw{" on" if j == key else ""}">{_esc(w["w"])}</span>'
            for j, w in enumerate(ln["words"]))
        html.append(f'<div class="cline" id="l{i}">{spans}</div>')
    data = [{"s": ln["start"], "e": ln["end"]} for ln in lines]
    js = f"""
const LINES = {json.dumps(data)};
LINES.forEach((L,i)=>{{
  tl.set("#l"+i,{{opacity:0,scale:.9}},0);
  tl.set("#l"+i,{{opacity:1}},L.s);
  tl.to("#l"+i,{{scale:1,duration:.2,ease:"back.out(2.2)"}},L.s);
  tl.set("#l"+i,{{opacity:0}},L.e);
}});"""
    css = "\n.cline{text-transform:uppercase;font-weight:800}"
    return css, f'<div id="{cid}">{"".join(html)}</div>', js


def stack_captions(lines, cid="caps"):
    """Two bold rows per line. The second row stacks in when its first word is said."""
    html, data = [], []
    for i, ln in enumerate(lines):
        ws = ln["words"]
        half = math.ceil(len(ws) / 2)
        rows = [ws[:half], ws[half:]]
        parts = []
        for r, row in enumerate(rows):
            if not row:
                continue
            text = " ".join(_esc(w["w"]) for w in row)
            parts.append(f'<div class="srow{" two" if r else ""}" id="l{i}r{r}">{text}</div>')
        html.append(f'<div class="cline" id="l{i}">{"".join(parts)}</div>')
        data.append({"s": ln["start"], "e": ln["end"],
                     "r": [row[0]["s"] for row in rows if row]})
    js = f"""
const LINES = {json.dumps(data)};
LINES.forEach((L,i)=>{{
  tl.set("#l"+i,{{opacity:0}},0);
  tl.set("#l"+i,{{opacity:1}},L.s);
  tl.set("#l"+i,{{opacity:0}},L.e);
  L.r.forEach((t,r)=>{{
    tl.set("#l"+i+"r"+r,{{opacity:0,y:26}},0);
    tl.to("#l"+i+"r"+r,{{opacity:1,y:0,duration:.22,ease:"power3.out"}},Math.max(L.s,t-0.04));
  }});
}});"""
    css = """
.cline{text-transform:uppercase;font-weight:800;line-height:1.04}
.srow{color:#fff;text-shadow:0 4px 18px rgba(0,0,0,.95),0 2px 5px rgba(0,0,0,.9)}
.srow.two{color:var(--fx-accent)}"""
    return css, f'<div id="{cid}">{"".join(html)}</div>', js


CAPTION_FUNCS = {"keyword": keyword_captions, "stack": stack_captions}


# --------------------------------------------------------------------------
# THE COMPOSITE: footage moves, grade, music
# --------------------------------------------------------------------------
def normalise_footage(moves, duration=None):
    """Validate the top-level "footage" list. Returns the moves sorted by time."""
    if moves is None:
        return []
    if not isinstance(moves, list):
        raise CardValueError('"footage" must be a list of moves')
    out = []
    for k, m in enumerate(moves):
        where = f"footage[{k}]"
        if not isinstance(m, dict):
            raise CardValueError(f"{where} must be a JSON object")
        name = m.get("move")
        if name not in FOOTAGE_MOVES:
            raise CardValueError(f"{where}: 'move' is {name!r}. Choose one of: "
                                 f"{', '.join(FOOTAGE_MOVES)}")
        at = _num(m.get("at"), "at", where=where)
        end = _num(m.get("out"), "out", where=where)
        if end - at < 0.3:
            raise CardValueError(f"{where}: 'out' must be at least 0.3s after 'at'")
        amount = _num(m.get("amount", MOVE_DEFAULT_AMOUNT[name]), "amount", where=where)
        if not 1.02 <= amount <= 1.6:
            raise CardValueError(f"{where}: 'amount' is the zoom, from 1.02 to 1.6, got {amount}")
        x = _num(m.get("x", 0.5), "x", where=where)
        y = _num(m.get("y", 0.38), "y", where=where)
        x_to = _num(m.get("x_to", 1 - x if name == "pan" and "x" in m else 0.9), "x_to", where=where)
        if name == "pan" and "x" not in m:
            x = 0.1
        for label, v in (("x", x), ("y", y), ("x_to", x_to)):
            if not 0 <= v <= 1:
                raise CardValueError(f"{where}: '{label}' is a position from 0 to 1, got {v}")
        if duration is not None and at >= duration:
            continue
        out.append({"move": name, "at": at, "out": end if duration is None else min(end, duration),
                    "amount": amount, "x": x, "y": y, "x_to": x_to})
    out.sort(key=lambda m: m["at"])
    for a, b in zip(out, out[1:]):
        if b["at"] < a["out"]:
            raise CardValueError(f"footage: the {a['move']} at {a['at']}s and the {b['move']} at "
                                 f"{b['at']}s overlap. One camera move at a time.")
    return out


def footage_filter(moves, fps):
    """
    The ffmpeg filters for the camera moves, or "" when there are none.

    zoompan with d=1 turns each input frame into one output frame, so it works
    on live video. The picture is scaled to double size first: zoompan places
    its window on whole pixels, and at 1x a slow push visibly steps.
    `in` is the input frame number, so in/fps is the time in seconds.
    """
    if not moves:
        return ""
    t = f"(in/{fps})"
    z_terms, x_terms, y_terms = [], [], []
    for m in moves:
        a, b, amt = m["at"], m["out"], m["amount"]
        win = f"between({t},{a},{b})"
        p = f"clip(({t}-{a})/{round(b - a, 4)},0,1)"
        fx = str(m["x"])
        if m["move"] == "punch-in":
            z = str(amt)
        elif m["move"] == "push-in":
            z = f"(1+{round(amt - 1, 4)}*{p})"
        elif m["move"] == "pull-out":
            z = f"({amt}-{round(amt - 1, 4)}*{p})"
        elif m["move"] == "pan":
            z = str(amt)
            fx = f"({m['x']}+{round(m['x_to'] - m['x'], 4)}*{p})"
        else:   # reframe: ease in over r seconds, hold, ease back out
            r = round(min(0.45, (b - a) / 3), 4)
            up = f"clip(({t}-{a})/{r},0,1)"
            down = f"clip(({b}-{t})/{r},0,1)"
            e = f"(({up})*({up})*(3-2*({up}))*({down})*({down})*(3-2*({down})))"
            z = f"(1+{round(amt - 1, 4)}*{e})"
        z_terms.append(f"{win}*({z}-1)")
        x_terms.append(f"{win}*{fx}")
        y_terms.append(f"{win}*{m['y']}")
    zexpr = "1+" + "+".join(z_terms)
    xexpr = f"(iw-iw/zoom)*({'+'.join(x_terms)})"
    yexpr = f"(ih-ih/zoom)*({'+'.join(y_terms)})"
    return (f"scale={W * 2}:{H * 2}:flags=bicubic,"
            f"zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':d=1:s={W}x{H}:fps={fps}")


def normalise_grade(name):
    if name in (None, "", "none"):
        return None
    if name not in GRADES:
        raise CardValueError(f'"grade" is {name!r}. Choose one of: {", ".join(GRADES)}, or none')
    return name


def grade_filter(name):
    return GRADES[name][0] if name else ""


def normalise_music(m):
    """Validate the top-level "music" object: {"file": ..., "level": dB, "duck": bool}."""
    if m is None:
        return None
    if isinstance(m, str):
        m = {"file": m}
    if not isinstance(m, dict) or not m.get("file"):
        raise CardValueError('"music" must be {"file": "<path to your music>"}')
    f = str(m["file"])
    if any(ch in f for ch in '"`$\\\n'):
        raise CardValueError('"music.file" has a character that cannot go in a shell command')
    level = _num(m.get("level", MUSIC_DEFAULT_LEVEL), "level", where="music")
    if not -40 <= level <= 0:
        raise CardValueError(f'"music.level" is in dB, from -40 to 0, got {level}')
    duck = m.get("duck", True)
    if not isinstance(duck, bool):
        raise CardValueError('"music.duck" must be true or false')
    return {"file": f, "level": level, "duck": duck}


def music_chain(music, voice_label, duration):
    """
    The filter lines that mix a music bed under the voice, and the output label.
    Input 2 is the music, looped with -stream_loop. With duck on, the voice
    drives a compressor on the music, so the bed dips whenever someone speaks
    and comes back up in the gaps.
    """
    fade_at = round(max(0, duration - 0.8), 3)
    bed = (f"[2:a]atrim=0:{round(duration, 3)},asetpts=PTS-STARTPTS,aresample=48000,"
           f"volume={music['level']}dB,afade=t=in:d=0.5,afade=t=out:st={fade_at}:d=0.8[bed]")
    if music["duck"]:
        return [bed,
                f"[{voice_label}]asplit[vox][key]",
                "[bed][key]sidechaincompress=threshold=0.05:ratio=4:attack=18:release=380[duck]",
                "[vox][duck]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.89[a]"], "a"
    return [bed, f"[{voice_label}][bed]amix=inputs=2:normalize=0:duration=first,"
                 "alimiter=limit=0.89[a]"], "a"


# --------------------------------------------------------------------------
# THE LIST
# --------------------------------------------------------------------------
def catalogue():
    """Every effect, grouped. This is what --list prints and --json exports."""
    def rows(d):
        return [{"name": k, "what": (v["say"] if isinstance(v, dict) else v[1] if isinstance(v, tuple) else v)}
                for k, v in d.items()]
    return [
        {"key": "text-motion", "label": "Text motion", "how": 'a "title" card, field "motion"',
         "items": rows(TEXT_MOTIONS)},
        {"key": "text-exit", "label": "Text exits", "how": 'a "title" card, field "exit"',
         "items": rows(TEXT_EXITS)},
        {"key": "title-look", "label": "Title looks", "how": 'a "title" card, field "look"',
         "items": rows(TITLE_LOOKS)},
        {"key": "captions", "label": "Caption styles", "how": "reel-compose.py --captions <name>",
         "items": rows(CAPTION_STYLES)},
        {"key": "footage", "label": "Camera moves", "how": 'the top-level "footage" list',
         "items": rows(FOOTAGE_MOVES)},
        {"key": "transitions", "label": "Transitions",
         "how": 'a "cutaway" card, fields "in" and "exit"', "items": rows(TRANSITIONS)},
        {"key": "cutaway-move", "label": "Cutaway movement", "how": 'a "cutaway" card, field "move"',
         "items": rows(CUTAWAY_MOVES)},
        {"key": "grade", "label": "Colour grades", "how": 'the top-level "grade"',
         "items": rows(GRADES)},
    ]


def _cli():
    import argparse
    ap = argparse.ArgumentParser(
        prog="reel_fx.py",
        description="The effects library used by reel-compose.py. Run it to list every effect.",
        epilog="example:\n  python3 reel_fx.py --list\n  python3 reel_fx.py --json > effects.json",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="print every effect (the default)")
    ap.add_argument("--json", action="store_true", help="print the list as JSON")
    a = ap.parse_args()
    cat = catalogue()
    if a.json:
        print(json.dumps(cat, indent=2))
        return
    for group in cat:
        print(f"\n{group['label']}  ({group['how']})")
        for it in group["items"]:
            print(f"  {it['name']:<14} {it['what']}")
    print("\nCards these add to every style:")
    for name in sorted(CARD_FIELDS):
        print(f"  {name:<10} {CARD_FIELDS[name]}")
    print('\nMusic: the top-level "music": {"file": "<your track>", "level": -20, "duck": true}')


if __name__ == "__main__":
    _cli()
