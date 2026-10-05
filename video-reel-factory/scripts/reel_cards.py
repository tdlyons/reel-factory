#!/usr/bin/env python3
"""
reel_cards.py: the motion-graphics card library.

Each card is a small function that returns (css, html, js) fragments for a
Hyperframes composition. The generator in reel-compose.py assembles them.

Why a library: the card DATA can never come from the footage, it comes from
whatever analysis sits behind the video. So the cards themselves have to be
reusable shells that any video can fill, otherwise every video is a bespoke
build.

This module is the `clean` style, the default for reel-compose.py --style: white
surfaces, a single blue accent, a system font stack, heavy whitespace. It also
holds the validation every style shares (normalise_card and the caption checks)
and the one-word `pulse` caption mode. Rebrand by changing ACCENT, INK and MUTED
below, or pass --style panel for the dark look in reel_cards_panel.py. Cards land in one of two bands: `stat`, `quote` and `image` at the
top of the frame (ZONE_TOP, y=150), and `table`, `bars`, `list` and `compare` in
the lower third (ZONE_LOWER, y=1000). On a 1080x1920 vertical selfie a face can
reach as low as y=1200, so the lower band starts inside it on tight framing. Look
at a preview and move a card with its own `y` when it lands on the speaker.

ZONE_TOP sits inside the strip Instagram covers with its own UI (y < 269), so a
card left there for an Instagram cut is partly under the Reels wordmark. The
`hook` card is the one card meant to live at the top regardless. See the safe
zone section of SKILL.md.

The `hook` card is the exception to every timing rule. It is pinned to t=0, it
is fully opaque on the first rendered frame, and it has no entrance animation,
because a viewer decides in the first frame and a hook that fades in has already
lost the ones who scrolled. reel-compose.py refuses to build without exactly one.

Every card obeys the render contract:
  - state changes use paired gsap.set(), never tl.call(), because callbacks do
    not fire reliably when the renderer seeks frames out of order
  - nothing depends on Date.now() or Math.random()
  - numeric fields are validated by normalise_card() before they are written into
    CSS or into the timeline, because those two sinks are not escaped and card
    data comes from outside this repo

Requires: Python 3.8+ (standard library only). Imported by reel-compose.py.

Example:
  python3 reel_cards.py --help      # list the card types and their fields
"""

import json
import math

SUMMARY = "light: white rounded cards, one blue accent, system font, soft rise-in motion"

ACCENT = "#0071e3"
INK = "#1d1d1f"
MUTED = "#86868b"

# Default vertical positions on a 1080x1920 vertical frame, overridable per card
# with `y`. Read the note in the module docstring before treating them as safe.
ZONE_TOP = 150
ZONE_LOWER = 1000
# The caption band's top edge. 1440 puts the text centre at roughly 79% of the
# frame height. The old 1690 put captions at 88 to 97%, which is under the
# platform UI on YouTube Shorts (channel name, title) and under the username and
# caption text on Instagram Reels, so on a phone the captions were hidden.
CAPTION_TOP = 1440
HOOK_TOP = 132


class CardValueError(ValueError):
    """A cards.json field held something the renderer refuses to interpolate."""


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _attr(s):
    """Escape a value for a double-quoted HTML attribute. _esc alone leaves '"' open."""
    return _esc(s).replace('"', "&quot;").replace("'", "&#39;")


def _num(v, field, i=None, kind=None, where=None):
    """
    Validate a numeric field before it is interpolated into CSS, an HTML style
    attribute or the GSAP timeline.

    Text fields go through _esc, but numbers are written raw into a <style> block
    and into JavaScript, so a string field value could close the style tag and
    open a script element. Card data is authored from external analysis, and
    caption timings are hand-edited in prep.json, so this is reachable in ordinary
    use rather than only under attack. Anything that is not a finite number is
    rejected by name here rather than reaching headless Chrome.

    Real JSON numbers are returned unchanged, so a well-formed card renders
    exactly the same bytes as before.
    """
    where = where or (f"card {i} ({kind})" if i is not None else "card")
    if isinstance(v, bool) or v is None:
        raise CardValueError(f"{where}: field '{field}' must be a number, got {v!r}")
    if isinstance(v, (int, float)):
        n = float(v)
        if not math.isfinite(n):
            raise CardValueError(f"{where}: field '{field}' must be a finite number, got {v!r}")
        return v
    if isinstance(v, str):
        try:
            n = float(v)
        except ValueError:
            raise CardValueError(
                f"{where}: field '{field}' must be a number, got the string {v!r}. "
                "Numeric fields are written straight into CSS and into the "
                "animation timeline, so only real numbers are accepted.")
        if not math.isfinite(n):
            raise CardValueError(f"{where}: field '{field}' must be a finite number, got {v!r}")
        try:
            return int(v)
        except ValueError:
            return n
    raise CardValueError(f"{where}: field '{field}' must be a number, got {type(v).__name__}")


def _num_field(c, key, field_label, i, kind):
    """Coerce c[key] in place when present, leaving absent fields to their defaults."""
    if key in c and c[key] is not None:
        c[key] = _num(c[key], field_label, i, kind)


# The non-numeric fields each card type cannot be rendered without, and the type
# each one has to be. Numbers are handled by _num above; these exist so a card
# missing its 'text' or its 'rows' stops with the field named, the same way a bad
# number does, instead of a raw KeyError or AttributeError thrown from inside a
# render function halfway through building the page. None means presence only.
REQUIRED_FIELDS = {
    "hook":    {"text": None},
    "stat":    {"value": None},
    "table":   {"columns": list, "rows": list},
    "bars":    {"series": list},
    "list":    {"items": list},
    "compare": {"left": dict, "right": dict},
    "quote":   {"text": None},
    "image":   {"src": None},
    "endcard": {},
}


def _require_fields(i, kind, c):
    for field, want in REQUIRED_FIELDS.get(kind, {}).items():
        if field not in c or c[field] is None:
            raise CardValueError(f"card {i} ({kind}): missing required field '{field}'")
        if want is not None and not isinstance(c[field], want):
            raise CardValueError(
                f"card {i} ({kind}): field '{field}' must be a JSON "
                f"{'list' if want is list else 'object'}, got {type(c[field]).__name__}")
    if kind == "table":
        for k, row in enumerate(c["rows"]):
            if not isinstance(row, list):
                raise CardValueError(
                    f"card {i} (table): rows[{k}] must be a list of cell values, "
                    f"got {type(row).__name__}")
    if kind == "bars" and not c["series"]:
        raise CardValueError(f"card {i} (bars): 'series' is empty, there is nothing to chart")


def normalise_card(i, c):
    """
    Return a copy of one card with every field validated.

    Called by reel-compose.py the moment cards.json is loaded, and again by
    render_card, so a caller using this module directly gets the same protection.
    Idempotent: running it on an already-validated card changes nothing.
    """
    if not isinstance(c, dict):
        raise CardValueError(f"card {i} must be a JSON object, got {type(c).__name__}")
    kind = c.get("type")
    c = dict(c)
    _require_fields(i, kind, c)
    for key in ("at", "out", "y", "value", "size", "count_dur", "colw",
                "height", "note_at", "bar_height", "stagger",
                "kicker_size", "width", "x"):
        _num_field(c, key, key, i, kind)

    if c.get("widths") is not None:
        w = c["widths"]
        if not isinstance(w, list):
            raise CardValueError(f"card {i} ({kind}): 'widths' must be a list of numbers")
        c["widths"] = [_num(x, f"widths[{k}]", i, kind) for k, x in enumerate(w)]

    if isinstance(c.get("rule"), dict) and c["rule"].get("at") is not None:
        rule = dict(c["rule"])
        rule["at"] = _num(rule["at"], "rule.at", i, kind)
        c["rule"] = rule

    if isinstance(c.get("series"), list):
        series = []
        for k, s in enumerate(c["series"]):
            if not isinstance(s, dict):
                raise CardValueError(
                    f"card {i} ({kind}): series[{k}] must be a JSON object with a "
                    f"'label' and a 'value', got {type(s).__name__}")
            if "value" not in s:
                raise CardValueError(f"card {i} ({kind}): series[{k}] needs a 'value'")
            if "label" not in s:
                raise CardValueError(f"card {i} ({kind}): series[{k}] needs a 'label'")
            s = dict(s)
            s["value"] = _num(s["value"], f"series[{k}].value", i, kind)
            series.append(s)
        c["series"] = series

    return c


def _rich(s):
    """Minimal **bold** to accent span, so card copy can emphasise one phrase."""
    out, parts = "", str(s).split("**")
    for i, p in enumerate(parts):
        out += f'<b class="ac">{_esc(p)}</b>' if i % 2 else _esc(p)
    return out


BASE_CSS = f"""
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;overflow:hidden;background:transparent}}
:root{{--blue:{ACCENT};--ink:{INK};--muted:{MUTED}}}
body{{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Helvetica Neue",Arial,sans-serif;
  -webkit-font-smoothing:antialiased}}
#root{{position:relative;width:1080px;height:1920px}}
.card{{position:absolute;background:#fff;border-radius:32px;
  box-shadow:0 30px 90px rgba(0,0,0,.32);opacity:0}}
.ac{{color:var(--blue)}}
.eyebrow{{font-size:24px;font-weight:600;letter-spacing:.18em;text-transform:uppercase;color:var(--muted)}}
/* captions */
#caps{{position:absolute;left:60px;right:60px;top:{CAPTION_TOP}px;height:170px;
  display:flex;align-items:center;justify-content:center}}
.cline{{position:absolute;width:100%;text-align:center;opacity:0;
  font-size:60px;font-weight:700;letter-spacing:-.02em;line-height:1.16}}
.cw{{color:#fff;text-shadow:0 4px 18px rgba(0,0,0,.95),0 2px 5px rgba(0,0,0,.9);
  padding:0 6px;display:inline-block;border-radius:10px}}
.cw.on{{color:#fff;background:var(--blue)}}
"""


def base_css():
    """
    The page CSS for this style: reset, palette, card surface and caption band.

    Part of the style interface that reel-compose.py calls on whichever style
    --style names: base_css(), captions(lines), render_card(i, card) and
    REGISTRY. A style module that provides those four can be swapped in without
    touching the composer. See the Styles section of README.md.
    """
    return BASE_CSS


def normalise_caption_lines(lines):
    """
    Validate the four timing fields in prep.json's caption_lines.

    Same sink as the numeric card fields, and the same treatment. Every line's
    'start' and 'end', and every word's 's' and 'e', are serialised into the
    inline GSAP timeline with json.dumps, which does not escape '/', so a string
    in any of them can close the script element and run inside the page headless
    Chrome executes at lint, snapshot and render time. reel-prep.py always writes
    rounded floats, but SKILL.md tells the owner to hand-edit caption_lines and
    re-render, so a "1.5" left in quotes has to stop the run rather than emit a
    corrupt script block.

    Returns a validated copy. Text is escaped elsewhere; only the timings are raw.
    """
    if not isinstance(lines, list):
        raise CardValueError(f"prep.json: 'caption_lines' must be a list, got {type(lines).__name__}")
    out = []
    for i, ln in enumerate(lines):
        if not isinstance(ln, dict):
            raise CardValueError(
                f"prep.json: caption_lines[{i}] must be a JSON object, got {type(ln).__name__}")
        ln = dict(ln)
        for key in ("start", "end"):
            if key not in ln or ln[key] is None:
                raise CardValueError(f"prep.json: caption_lines[{i}] is missing '{key}'")
            ln[key] = _num(ln[key], key, where=f"prep.json: caption_lines[{i}]")
        words = ln.get("words")
        if not isinstance(words, list):
            raise CardValueError(
                f"prep.json: caption_lines[{i}].words must be a list, "
                f"got {type(words).__name__}")
        checked = []
        for j, w in enumerate(words):
            if not isinstance(w, dict):
                raise CardValueError(
                    f"prep.json: caption_lines[{i}].words[{j}] must be a JSON object, "
                    f"got {type(w).__name__}")
            w = dict(w)
            for key in ("s", "e"):
                if key not in w or w[key] is None:
                    raise CardValueError(
                        f"prep.json: caption_lines[{i}].words[{j}] is missing '{key}'")
                w[key] = _num(w[key], key, where=f"prep.json: caption_lines[{i}].words[{j}]")
            checked.append(w)
        ln["words"] = checked
        out.append(ln)
    return out


CAPTION_MOVE_BOX = ("top", "height", "left", "right")
CAPTION_ALIGN = ("left", "center", "right")


def normalise_caption_moves(moves):
    """
    Validate cards.json's optional top-level "caption_moves" list.

    Each entry re-seats the caption band at one moment, for a video whose layout
    changes part way through (a wide talking head, then a full-frame screenshot
    with the face in a corner) where no single caption position is clear of both.
    Every value is written into the inline timeline, so the numbers go through
    _num and 'align' must be one of three words. Returns a validated copy.
    """
    if moves is None:
        return []
    if not isinstance(moves, list):
        raise CardValueError(f"cards.json: 'caption_moves' must be a list, got {type(moves).__name__}")
    out = []
    for k, m in enumerate(moves):
        where = f"cards.json: caption_moves[{k}]"
        if not isinstance(m, dict):
            raise CardValueError(f"{where} must be a JSON object, got {type(m).__name__}")
        if "at" not in m:
            raise CardValueError(f"{where} is missing 'at'")
        clean = {"at": _num(m["at"], "at", where=where)}
        for key in CAPTION_MOVE_BOX + ("size",):
            if key in m and m[key] is not None:
                clean[key] = _num(m[key], key, where=where)
        if m.get("align") is not None:
            if m["align"] not in CAPTION_ALIGN:
                raise CardValueError(
                    f"{where}: 'align' must be one of {', '.join(CAPTION_ALIGN)}, got {m['align']!r}")
            clean["align"] = m["align"]
        if len(clean) == 1:
            raise CardValueError(
                f"{where} moves nothing. Give it at least one of "
                f"{', '.join(CAPTION_MOVE_BOX)}, size or align.")
        out.append(clean)
    return sorted(out, key=lambda m: m["at"])


def caption_moves_js(moves):
    """
    One gsap.set() per move, on the band (#caps) and on every line (.cline).
    set() rather than to() so seeking to any frame reproduces the same state,
    which is the render contract every card obeys.
    """
    js = []
    for m in moves:
        box = {k: f"{m[k]}px" for k in CAPTION_MOVE_BOX if k in m}
        line = {}
        if "size" in m:
            line["fontSize"] = f"{m['size']}px"
        if "align" in m:
            line["textAlign"] = m["align"]
        if box:
            js.append(f'tl.set("#caps",{json.dumps(box)},{m["at"]});')
        if line:
            js.append(f'tl.set(".cline",{json.dumps(line)},{m["at"]});')
    return ("\n" + "\n".join(js)) if js else ""


def captions(lines, cid="caps"):
    """
    Word-timed captions from prep.json. Lines are clamped upstream, and their
    timings are validated by normalise_caption_lines before they reach here.
    """
    html = []
    for i, ln in enumerate(lines):
        spans = "".join(
            f'<span class="cw" id="w{i}_{j}">{_esc(w["w"])}</span>'
            for j, w in enumerate(ln["words"]))
        html.append(f'<div class="cline" id="l{i}">{spans}</div>')
    data = [{"s": ln["start"], "e": ln["end"],
             "w": [{"s": w["s"], "e": w["e"]} for w in ln["words"]]} for ln in lines]
    js = f"""
const LINES = {json.dumps(data)};
LINES.forEach((L,i)=>{{
  tl.set("#l"+i,{{opacity:0}},0);
  tl.set("#l"+i,{{opacity:1}},L.s);
  tl.set("#l"+i,{{opacity:0}},L.e);
  L.w.forEach((w,j)=>{{
    tl.set("#w"+i+"_"+j,{{className:"cw"}},0);
    tl.set("#w"+i+"_"+j,{{className:"cw on"}},w.s);
    tl.set("#w"+i+"_"+j,{{className:"cw"}},w.e);
  }});
}});"""
    return "", f'<div id="{cid}">{"".join(html)}</div>', js


# Pulse captions: one word at a time, all caps, centre frame, hard swap.
# 1060 puts the word's centre at about 59% of the frame height, just below the
# chin on a typical selfie framing and well clear of the platform UI at the
# bottom. It also sits across the lower card band (y=1000), so a table, bars,
# list or compare card shown under pulse captions wants its own `y`.
PULSE_TOP = 1060
PULSE_MAX_HOLD = 1.10   # a word never stays longer than this, even before a pause
PULSE_MIN_HOLD = 0.12   # nor shorter than this, unless the next word starts first


def pulse_words(lines):
    """
    Flatten caption lines into one timed word list with no overlaps.

    Whisper's word timings are contiguous and occasionally run backwards, so a
    naive minimum hold pushes a short word past its neighbour's start and two
    words show at once. Starts are forced monotonic first, then each end is
    clamped to the next start, and the result is checked rather than trusted.
    """
    words = [w for ln in lines for w in ln["words"] if str(w.get("w", "")).strip()]
    out, last = [], None
    for w in words:
        s = w["s"] if last is None else max(w["s"], last)
        out.append({"w": str(w["w"]).strip(), "s": round(s, 3), "e": w["e"]})
        last = s
    for k, w in enumerate(out):
        nxt = out[k + 1]["s"] if k + 1 < len(out) else None
        e = max(w["e"], w["s"] + PULSE_MIN_HOLD)
        e = min(e, w["s"] + PULSE_MAX_HOLD)
        if nxt is not None:
            e = min(e, nxt)
        w["e"] = round(e, 3)
    for k in range(len(out) - 1):
        if out[k]["e"] > out[k + 1]["s"]:
            raise CardValueError(
                f"pulse captions: word {k} ({out[k]['w']!r}) still overlaps the next word "
                "after clamping. Refusing to build captions that stack.")
    return out


def pulse_captions(lines, cid="caps"):
    """
    The `pulse` caption mode (reel-compose.py --captions pulse). Style
    independent: white heavy caps with a black outline read on any footage and
    next to any card style. A style module may define its own pulse_captions to
    restyle it; the composer uses this one otherwise.

    Each word is its own .cline, so caption_moves and --caption-top move and
    resize pulse captions exactly as they do phrase captions.
    """
    words = pulse_words(lines)
    css = f"""
#{cid}{{top:{PULSE_TOP}px;height:150px}}
#{cid} .cline{{font-family:"Arial Black","Helvetica Neue",Arial,sans-serif;font-size:86px;
  font-weight:900;letter-spacing:0;line-height:1;text-transform:uppercase;color:#fff;
  -webkit-text-stroke:8px #000;paint-order:stroke fill;
  text-shadow:0 5px 0 rgba(0,0,0,.85),0 8px 26px rgba(0,0,0,.6)}}"""
    html = "".join(f'<div class="cline" id="p{k}">{_esc(w["w"])}</div>'
                   for k, w in enumerate(words))
    data = [{"s": w["s"], "e": w["e"]} for w in words]
    js = f"""
const PULSE = {json.dumps(data)};
PULSE.forEach((w,k)=>{{
  tl.set("#p"+k,{{opacity:0}},0);
  tl.set("#p"+k,{{opacity:1}},w.s);
  tl.set("#p"+k,{{opacity:0}},w.e);
}});"""
    return css, f'<div id="{cid}">{html}</div>', js


# --------------------------------------------------------------------------
# CARDS
# --------------------------------------------------------------------------

def stat(i, c):
    """A number counting up. For the one figure the video is built around."""
    cid = f"stat{i}"
    css = f"""
#{cid}{{left:70px;top:{c.get('y', ZONE_TOP)}px;width:940px;padding:44px 48px 40px}}
#{cid} .v{{font-size:{c.get('size',152)}px;font-weight:700;letter-spacing:-.04em;
  color:var(--ink);line-height:.95;font-variant-numeric:tabular-nums}}
#{cid} .sub{{font-size:30px;color:var(--ink);margin-top:16px;font-weight:500}}
#{cid} .eyebrow{{margin-bottom:14px}}"""
    html = (f'<div class="card" id="{cid}">'
            f'<div class="eyebrow">{_esc(c.get("eyebrow",""))}</div>'
            f'<div class="v" id="{cid}v">0</div>'
            f'<div class="sub">{_rich(c.get("sub",""))}</div></div>')
    val = c["value"]
    js = f"""
tl.set("#{cid}",{{opacity:0,y:-40,scale:.96}},0);
tl.to("#{cid}",{{opacity:1,y:0,scale:1,duration:.5,ease:"back.out(1.5)"}},{c['at']});
(()=>{{const o={{v:0}};
tl.to(o,{{v:{val},duration:{c.get('count_dur',1.9)},ease:"power2.out",
  onUpdate:()=>{{document.getElementById("{cid}v").textContent=
    Math.round(o.v).toLocaleString();}}}},{c['at']+0.3});}})();
tl.to("#{cid}",{{opacity:0,y:-30,duration:.45,ease:"power2.in"}},{c['out']});"""
    return css, html, js


def table(i, c):
    """A scrolling data table. Proof that real rows exist behind the claim."""
    cid = f"tbl{i}"
    cols = c["columns"]
    # Only widths[0] is used, as the flex weight of the label column. Every other
    # column is a fixed colw px and right aligned, so the rest of this list is
    # validated and then ignored. Documented that way in CARD_FIELDS.
    widths = c.get("widths") or ([1.7] + [1] * (len(cols) - 1))
    def cells(vals, cls):
        out = ""
        for k, v in enumerate(vals):
            style = (f"flex:{widths[k]}" if k == 0 else f"width:{c.get('colw',160)}px;text-align:right")
            out += f'<span class="{cls}{k}" style="{style}">{_esc(v)}</span>'
        return out
    rows = "".join(f'<div class="trow">{cells(r,"td")}</div>' for r in c["rows"])
    # 420 ends the card at y=1420 from the lower band, above the caption band at
    # CAPTION_TOP. Taller tables scroll further but sit on the captions.
    h = c.get("height", 420)
    css = f"""
#{cid}{{left:60px;top:{c.get('y', ZONE_LOWER)}px;width:960px;height:{h}px;overflow:hidden}}
#{cid} .thead{{display:flex;padding:22px 30px 16px;font-size:20px;font-weight:600;
  letter-spacing:.1em;text-transform:uppercase;color:var(--muted);
  border-bottom:2px solid #e8e8ea;background:#fff}}
#{cid} .clip{{position:absolute;top:78px;left:0;width:100%;height:{h-78}px;overflow:hidden}}
#{cid} .body{{position:absolute;top:0;left:0;width:100%}}
#{cid} .trow{{display:flex;padding:16px 30px;font-size:24px;
  border-bottom:1px solid #f0f0f2;align-items:center}}
#{cid} .td0{{font-weight:600;color:var(--ink);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;padding-right:12px}}
#{cid} .td1,#{cid} .td2{{font-variant-numeric:tabular-nums;color:var(--muted)}}
#{cid} .td3{{font-variant-numeric:tabular-nums;font-weight:700;color:var(--blue)}}
#{cid} .fade{{position:absolute;bottom:0;left:0;width:100%;height:120px;
  background:linear-gradient(transparent,#fff);pointer-events:none}}
#{cid}tag{{position:absolute;left:60px;top:{c.get('y',ZONE_LOWER)-75}px;background:var(--blue);
  color:#fff;font-size:24px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
  padding:12px 24px;border-radius:999px;opacity:0}}"""
    html = (f'<div id="{cid}tag">{_esc(c.get("tag",""))}</div>'
            f'<div class="card" id="{cid}">'
            f'<div class="thead">{cells(cols,"th")}</div>'
            f'<div class="clip"><div class="body" id="{cid}b">{rows}</div></div>'
            f'<div class="fade"></div></div>')
    travel = max(0, len(c["rows"]) * 57 - (h - 200))
    js = f"""
tl.set("#{cid}",{{opacity:0,y:50}},0);
tl.to("#{cid}",{{opacity:1,y:0,duration:.5,ease:"power3.out"}},{c['at']});
tl.to("#{cid}tag",{{opacity:1,duration:.35}},{c['at']+0.3});
tl.fromTo("#{cid}b",{{y:0}},{{y:{-travel},duration:{max(1,c['out']-c['at']-3)},ease:"none"}},{c['at']+0.8});
tl.to(["#{cid}","#{cid}tag"],{{opacity:0,y:-30,duration:.45,ease:"power2.in"}},{c['out']});"""
    return css, html, js


def bars(i, c):
    """
    A labelled bar chart with an optional reference rule. Use the rule when the
    point is that values are FLAT, because drawing it at the mean makes the
    claim visible instead of asserted.
    """
    cid = f"bar{i}"
    series = c["series"]
    mx = max(s["value"] for s in series) or 1
    avg = sum(s["value"] for s in series) / len(series)
    bh = c.get("bar_height", 230)
    cells = "".join(
        f'<div class="bw"><div class="bc"><div class="bar" id="{cid}b{k}"></div></div>'
        f'<div class="bl">{_esc(s["label"])}</div>'
        f'<div class="bv" id="{cid}v{k}">{_esc(s["value"])}</div></div>'
        for k, s in enumerate(series))
    rule = ""
    if c.get("rule"):
        rp = round(avg / mx * bh)
        rule = (f'<div class="rule" style="bottom:{rp}px"></div>'
                f'<div class="rlab" style="bottom:{rp+8}px">{_esc(c["rule"].get("label",""))}</div>')
    css = f"""
#{cid}{{left:60px;top:{c.get('y',ZONE_LOWER)}px;width:960px;padding:38px 40px 30px}}
#{cid} h4{{font-size:30px;font-weight:700;color:var(--ink);letter-spacing:-.02em;margin-bottom:6px}}
#{cid} .sub{{font-size:22px;color:var(--muted);margin-bottom:30px}}
#{cid} .bars{{display:flex;gap:14px;align-items:flex-end;height:300px;position:relative}}
#{cid} .bw{{flex:1;display:flex;flex-direction:column;align-items:center}}
#{cid} .bc{{height:{bh}px;width:100%;display:flex;align-items:flex-end}}
#{cid} .bar{{width:100%;background:var(--blue);border-radius:10px 10px 0 0;height:0%}}
#{cid} .bl{{font-size:19px;color:var(--muted);margin-top:12px;white-space:nowrap}}
#{cid} .bv{{font-size:22px;font-weight:700;color:var(--ink);margin-top:4px;
  font-variant-numeric:tabular-nums;opacity:0}}
#{cid} .rule{{position:absolute;left:0;right:0;height:0;border-top:5px dashed #ff3b30;opacity:0}}
#{cid} .rlab{{position:absolute;right:0;font-size:20px;font-weight:700;color:#ff3b30;
  background:#fff;padding:2px 8px;border-radius:6px;opacity:0}}
#{cid} .note{{margin-top:22px;font-size:26px;font-weight:600;color:var(--ink);
  opacity:0;text-align:center}}"""
    html = (f'<div class="card" id="{cid}">'
            f'<h4>{_esc(c.get("title",""))}</h4>'
            f'<div class="sub">{_esc(c.get("sub",""))}</div>'
            f'<div class="bars">{cells}{rule}</div>'
            f'<div class="note" id="{cid}n">{_rich(c.get("note",""))}</div></div>')
    js = [f"""
tl.set("#{cid}",{{opacity:0,y:50}},0);
tl.to("#{cid}",{{opacity:1,y:0,duration:.5,ease:"power3.out"}},{c['at']});"""]
    for k, s in enumerate(series):
        pct = round(s["value"] / mx * 100, 1)
        js.append(f'tl.to("#{cid}b{k}",{{height:"{pct}%",duration:.55,ease:"power3.out"}},{round(c["at"]+0.6+k*0.13,2)});')
        js.append(f'tl.to("#{cid}v{k}",{{opacity:1,duration:.25}},{round(c["at"]+0.9+k*0.13,2)});')
    if c.get("rule"):
        ra = c["rule"].get("at", c["at"] + 8)
        js.append(f'tl.to("#{cid} .rule",{{opacity:1,duration:.9,ease:"power2.inOut"}},{ra});')
        js.append(f'tl.to("#{cid} .rlab",{{opacity:1,duration:.4}},{ra+0.3});')
    if c.get("note"):
        js.append(f'tl.to("#{cid}n",{{opacity:1,duration:.5}},{c.get("note_at", c["at"]+9)});')
    js.append(f'tl.to("#{cid}",{{opacity:0,y:-30,duration:.5,ease:"power2.in"}},{c["out"]});')
    return css, html, "\n".join(js)


def lister(i, c):
    """Sequential bullet reveal. For steps, rules, or a short ranked list."""
    cid = f"lst{i}"
    items = c["items"]
    rows = "".join(
        f'<div class="li" id="{cid}i{k}"><span class="n">{k+1}</span>'
        f'<span class="t">{_rich(t)}</span></div>' for k, t in enumerate(items))
    css = f"""
#{cid}{{left:60px;top:{c.get('y',ZONE_LOWER)}px;width:960px;padding:40px 44px}}
#{cid} h4{{font-size:32px;font-weight:700;color:var(--ink);margin-bottom:26px;letter-spacing:-.02em}}
#{cid} .li{{display:flex;align-items:flex-start;gap:20px;margin-bottom:20px;opacity:0}}
#{cid} .n{{flex:none;width:44px;height:44px;border-radius:50%;background:var(--blue);
  color:#fff;font-size:22px;font-weight:700;display:flex;align-items:center;justify-content:center}}
#{cid} .t{{font-size:29px;color:var(--ink);line-height:1.35;padding-top:5px}}"""
    html = (f'<div class="card" id="{cid}"><h4>{_esc(c.get("title",""))}</h4>{rows}</div>')
    js = [f"""
tl.set("#{cid}",{{opacity:0,y:50}},0);
tl.to("#{cid}",{{opacity:1,y:0,duration:.5,ease:"power3.out"}},{c['at']});"""]
    step = c.get("stagger", 0.9)
    for k in range(len(items)):
        js.append(f'tl.to("#{cid}i{k}",{{opacity:1,y:0,duration:.4,ease:"power2.out"}},{round(c["at"]+0.5+k*step,2)});')
        js.append(f'tl.set("#{cid}i{k}",{{y:14}},0);')
    js.append(f'tl.to("#{cid}",{{opacity:0,y:-30,duration:.45,ease:"power2.in"}},{c["out"]});')
    return css, html, "\n".join(js)


def compare(i, c):
    """Two-up A/B. For 'this vs that' claims where the gap is the point."""
    cid = f"cmp{i}"
    a, b = c["left"], c["right"]
    def side(s, k):
        return (f'<div class="s" id="{cid}{k}"><div class="lab">{_esc(s.get("label",""))}</div>'
                f'<div class="v">{_esc(s.get("value",""))}</div>'
                f'<div class="note">{_esc(s.get("note",""))}</div></div>')
    css = f"""
#{cid}{{left:60px;top:{c.get('y',ZONE_LOWER)}px;width:960px;padding:38px 40px}}
#{cid} h4{{font-size:29px;font-weight:700;color:var(--ink);margin-bottom:26px;text-align:center}}
#{cid} .row{{display:flex;gap:26px;align-items:stretch}}
#{cid} .s{{flex:1;text-align:center;padding:26px 18px;border-radius:22px;background:#f5f5f7;opacity:0}}
#{cid} .s.hi{{background:#e8f2fd}}
#{cid} .lab{{font-size:21px;color:var(--muted);font-weight:600;letter-spacing:.05em;text-transform:uppercase}}
#{cid} .v{{font-size:66px;font-weight:700;color:var(--ink);letter-spacing:-.03em;
  margin-top:12px;font-variant-numeric:tabular-nums}}
#{cid} .note{{font-size:21px;color:var(--muted);margin-top:10px;line-height:1.3}}"""
    html = (f'<div class="card" id="{cid}"><h4>{_rich(c.get("title",""))}</h4>'
            f'<div class="row">{side(a,"a")}{side(b,"b")}</div></div>')
    js = f"""
tl.set("#{cid}",{{opacity:0,y:50}},0);
tl.to("#{cid}",{{opacity:1,y:0,duration:.5,ease:"power3.out"}},{c['at']});
tl.set("#{cid}a",{{x:-24}},0); tl.set("#{cid}b",{{x:24}},0);
tl.to("#{cid}a",{{opacity:1,x:0,duration:.45,ease:"power3.out"}},{c['at']+0.35});
tl.to("#{cid}b",{{opacity:1,x:0,duration:.45,ease:"power3.out"}},{c['at']+0.6});
tl.to("#{cid}",{{opacity:0,y:-30,duration:.45,ease:"power2.in"}},{c['out']});"""
    return css, html, js


def quote(i, c):
    """One line, large. For the sentence you want screenshotted."""
    cid = f"qt{i}"
    css = f"""
#{cid}{{left:70px;top:{c.get('y',ZONE_TOP)}px;width:940px;padding:46px 50px}}
#{cid} .q{{font-size:{c.get('size',56)}px;font-weight:700;color:var(--ink);
  line-height:1.14;letter-spacing:-.025em}}
#{cid} .attr{{font-size:24px;color:var(--muted);margin-top:20px}}"""
    html = (f'<div class="card" id="{cid}"><div class="q">{_rich(c["text"])}</div>'
            + (f'<div class="attr">{_esc(c["attr"])}</div>' if c.get("attr") else "")
            + "</div>")
    js = f"""
tl.set("#{cid}",{{opacity:0,y:34,scale:.97}},0);
tl.to("#{cid}",{{opacity:1,y:0,scale:1,duration:.5,ease:"back.out(1.4)"}},{c['at']});
tl.to("#{cid}",{{opacity:0,y:-26,duration:.45,ease:"power2.in"}},{c['out']});"""
    return css, html, js


def hook(i, c):
    """
    The opening hook. HARD RULE: it is on screen at frame 0, fully opaque, with
    no entrance animation. A viewer decides in the first frame, so a hook that
    fades in over half a second has already lost the ones who scrolled.

    This is the only card type with no `at`: it is pinned to 0. Give it `out`.

    The kicker is 42px rather than the 24px an eyebrow uses. At eyebrow size it
    measured about 9px tall on a 300px-wide phone thumbnail and read as
    decoration, which matters because the sharpest element (a digit, an offer)
    tends to land in the kicker. Override with `kicker_size` only to go bigger.

    The claim uses text-wrap:balance so its lines come out even and a short word
    is not stranded at the end of line one away from its noun. The renderer is
    Chrome, which supports it natively.
    """
    cid = f"hk{i}"
    css = f"""
#{cid}{{left:60px;top:{c.get('y', HOOK_TOP)}px;width:960px;padding:44px 50px 48px;opacity:1}}
#{cid} .k{{font-size:{c.get('kicker_size',42)}px;font-weight:800;letter-spacing:.04em;
  text-transform:uppercase;color:var(--blue);margin-bottom:14px;line-height:1.1}}
#{cid} .h{{font-size:{c.get('size',68)}px;font-weight:700;color:var(--ink);
  line-height:1.06;letter-spacing:-.032em;text-wrap:balance}}"""
    html = (f'<div class="card" id="{cid}" style="opacity:1">'
            + (f'<div class="k">{_esc(c["kicker"])}</div>' if c.get("kicker") else "")
            + f'<div class="h">{_rich(c["text"])}</div></div>')
    # Visible at t=0 with no tween in, so the first rendered frame already has it.
    # The inline opacity:1 above covers the moment before the timeline runs.
    js = f"""
tl.set("#{cid}",{{opacity:1,y:0,scale:1}},0);
tl.to("#{cid}",{{opacity:0,y:-30,duration:.42,ease:"power2.in"}},{c['out']});"""
    return css, html, js


def image(i, c):
    """
    A timed screenshot or UI insert, styled like the rest of the library (white
    rounded card, same shadow) so a product screen reads as part of the video
    rather than a pasted-in frame. `src` is a path relative to the project
    directory: copy the PNG into the project before rendering. Crop it tight to
    the thing the video points at, because a full browser window squeezed into a
    900px card leaves the one field that matters unreadable.
    """
    cid = f"img{i}"
    width = c.get("width", 900)
    x = c.get("x", (1080 - width) // 2)
    css = f"""
#{cid}{{left:{x}px;top:{c.get('y', ZONE_TOP)}px;width:{width}px;padding:26px 26px 32px}}
#{cid} .lbl{{font-size:24px;font-weight:600;letter-spacing:.18em;text-transform:uppercase;
  color:var(--muted);margin-bottom:16px;text-align:center}}
#{cid} img{{width:100%;display:block;border-radius:16px;box-shadow:0 6px 24px rgba(0,0,0,.18)}}"""
    label_html = f'<div class="lbl">{_esc(c["label"])}</div>' if c.get("label") else ""
    html = f'<div class="card" id="{cid}">{label_html}<img src="{_attr(c["src"])}" alt=""></div>'
    js = f"""
tl.set("#{cid}",{{opacity:0,y:40,scale:.97}},0);
tl.to("#{cid}",{{opacity:1,y:0,scale:1,duration:.5,ease:"back.out(1.4)"}},{c['at']});
tl.to("#{cid}",{{opacity:0,y:-30,duration:.45,ease:"power2.in"}},{c['out']});"""
    return css, html, js


def endcard(i, c):
    """
    Full-bleed opaque close. Opaque is the point: it covers the frozen last
    frame of the base video so the piece ends deliberately instead of trailing.

    Not for social cuts. A full-bleed card at the end stops the video dead and
    breaks the loop, so reel-compose.py only renders one when --cut is run with
    --endcard, for work that is not going to a vertical feed.
    """
    cid = f"end{i}"
    css = f"""
#{cid}{{position:absolute;inset:0;background:#fff;opacity:0;border-radius:0;box-shadow:none;
  display:flex;flex-direction:column;align-items:center;justify-content:center;padding:0 110px}}
#{cid} .mk{{display:grid;grid-template-columns:repeat(2,34px);grid-template-rows:repeat(2,34px);
  gap:12px;margin-bottom:56px}}
#{cid} .mk i{{display:block;width:34px;height:34px;border-radius:9px;background:#d2d2d7}}
#{cid} .mk i.on{{background:var(--blue)}}
#{cid} .t{{font-size:82px;font-weight:700;letter-spacing:-.035em;color:var(--ink);
  text-align:center;line-height:1.05}}
#{cid} .s{{font-size:33px;color:#6e6e73;margin-top:26px;text-align:center;
  line-height:1.35;max-width:760px}}
#{cid} .pill{{margin-top:62px;background:var(--blue);color:#fff;font-size:44px;font-weight:700;
  padding:28px 56px;border-radius:999px;letter-spacing:-.01em}}
#{cid} .foot{{position:absolute;bottom:150px;font-size:26px;letter-spacing:.16em;
  text-transform:uppercase;color:var(--muted);font-weight:600}}"""
    html = (f'<div class="card" id="{cid}">'
            f'<div class="mk"><i></i><i class="on"></i><i></i><i></i></div>'
            f'<div class="t">{_esc(c.get("title",""))}</div>'
            f'<div class="s">{_esc(c.get("sub",""))}</div>'
            f'<div class="pill">{_esc(c.get("pill",""))}</div>'
            f'<div class="foot">{_esc(c.get("foot",""))}</div></div>')
    js = f"""
tl.set("#{cid}",{{opacity:0}},0);
tl.to("#{cid}",{{opacity:1,duration:.34,ease:"power2.out"}},{c['at']});
tl.from("#{cid} .t",{{y:26,opacity:0,duration:.42,ease:"power3.out"}},{c['at']+0.12});
tl.from("#{cid} .s",{{y:18,opacity:0,duration:.42,ease:"power3.out"}},{c['at']+0.26});
tl.from("#{cid} .pill",{{scale:.9,opacity:0,duration:.42,ease:"back.out(1.7)"}},{c['at']+0.42});
tl.to("#{cid} .pill",{{scale:1.04,duration:.5,ease:"sine.inOut",yoyo:true,repeat:3}},{c['at']+1.1});"""
    return css, html, js


REGISTRY = {
    "hook": hook, "stat": stat, "table": table, "bars": bars,
    "list": lister, "compare": compare, "quote": quote, "image": image,
    "endcard": endcard,
}

# Documentation for --help and for anyone writing cards.json by hand.
# Every card except hook takes "at" (seconds), and every card except endcard
# takes "out" (seconds). "y" overrides the vertical position on the 1080x1920 frame.
CARD_FIELDS = {
    "hook": "text (required, supports **accent**), kicker, size, kicker_size, y. "
            "REQUIRED once per reel. Takes no 'at': it is pinned to 0, fully opaque on "
            "frame 0, with no entrance animation",
    "stat": "value (number, required), eyebrow, sub (supports **accent**), size, count_dur, y",
    "table": "columns (list, required), rows (list of lists, required), tag, "
             "widths (list of numbers; only widths[0] is read, as the flex weight of the "
             "first column, and it defaults to 1.7. Later entries are validated and then "
             "ignored, because every other column is sized by colw), colw, height, y",
    "bars": "series (list of {label,value}, required), title, sub, note (supports **accent**), "
            "note_at, rule ({label, at}), bar_height, y",
    "list": "items (list of strings, required, supports **accent**), title, stagger, y",
    "compare": "left and right ({label,value,note}, both required), title (supports **accent**), y",
    "quote": "text (required, supports **accent**), attr, size, y",
    "image": "src (required, a path relative to the project dir; copy the file in "
             "before rendering), label, width, x, y",
    "endcard": "title, sub, pill, foot. Takes no 'out', it runs to the end of the composition. "
               "Not for social cuts: rendered only by reel-compose.py --cut --endcard",
}


def render_with(registry, i, c):
    """
    Check one card's timing fields, validate it, and render it with the card
    function the given style registry maps its type to. Every style routes
    through here, so a card is validated the same way whichever style draws it.
    """
    t = c.get("type")
    if t not in registry:
        raise SystemExit(f"unknown card type '{t}'. Available: {', '.join(sorted(registry))}")
    if t == "hook":
        c = dict(c)
        c["at"] = 0
    elif "at" not in c:
        raise SystemExit(f"card {i} ({t}) is missing required field 'at'")
    if t != "endcard" and "out" not in c:
        raise SystemExit(f"card {i} ({t}) needs an 'out' time (endcard is the only card that may run to the end)")
    return registry[t](i, normalise_card(i, c))


def render_card(i, c):
    return render_with(REGISTRY, i, c)


def _cli():
    import argparse
    ap = argparse.ArgumentParser(
        prog="reel_cards.py",
        description="Motion-graphics card library used by reel-compose.py. "
                    "Run it directly to list the card types and the fields each one accepts.",
        epilog="example:\n"
               "  python3 reel_cards.py --list\n\n"
               "cards.json looks like:\n"
               '  {"cards": [{"type":"quote","at":1.2,"out":6.0,"text":"one line"}]}',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true",
                    help="print every card type with its accepted fields (this is the default)")
    ap.parse_args()
    print("Card types. Every card except hook takes 'at' (seconds); every card except endcard "
          "also takes 'out'.\n")
    for name in sorted(CARD_FIELDS):
        print(f"  {name:<9} {CARD_FIELDS[name]}")
    print("\nAccent colour, ink and muted grey are the ACCENT / INK / MUTED constants in this file.")


if __name__ == "__main__":
    _cli()
