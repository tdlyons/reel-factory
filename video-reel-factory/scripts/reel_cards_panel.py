#!/usr/bin/env python3
"""
reel_cards_panel.py: the `panel` card style. Dark glass panels with a rounded
accent spine down the left edge, condensed caps for headlines, and a slide-in
entrance. Select it with reel-compose.py --style panel.

It implements the same style interface as reel_cards.py (the `clean` style):

  base_css()            the page CSS: palette, fonts, card shape, caption band
  captions(lines)       phrase captions, shared with clean and restyled here
  render_card(i, card)  one card as (css, html, js) fragments
  REGISTRY              card type -> card function

and it accepts exactly the same cards.json fields, so one cards.json renders in
any style. Validation is shared too: every card goes through
reel_cards.normalise_card before it is drawn.

The palette and the fonts reach the CSS only through the :root variables in
THEME, never as literal values inside a card. That is what lets a recolour be a
ten line file (see reel_cards_example_brand.py): it passes new values to
base_css() and reuses everything else here by reference, so an improvement to
the motion or the geometry reaches every recolour automatically. Keep it that
way when you edit a card: write var(--accent), never a hex value.

Fonts are system stacks, so nothing has to be vendored for this style to
render. On a machine without a condensed face the headline falls back to a
regular sans, which is still legible, only wider.

Every card obeys the render contract:
  - state changes use paired gsap.set() and tl.to(), never tl.call(), because
    callbacks do not fire reliably when the renderer seeks frames out of order
  - no backdrop-filter: headless Chrome rasterises it inconsistently across
    seeked frames, which shows up as banded panels
  - nothing depends on Date.now() or Math.random()

Requires: Python 3.8+ (standard library only) and reel_cards.py beside it.
"""

import re

SUMMARY = "dark: glass panels with an accent spine, condensed caps, slide-in from the left"

import reel_cards as _clean
from reel_cards import _esc, _attr, _rich, ZONE_TOP, ZONE_LOWER, HOOK_TOP, CAPTION_TOP

# The whole look, as CSS custom properties. A recolour overrides some of these
# through base_css(overrides) and nothing else.
THEME = {
    "--accent": "#5CC8FF",        # spine, highlighted words, bars, the hook's bar
    "--accent-soft": "#B8E6FF",   # kickers, rail tags, small readouts
    "--tone": "#8A96A8",          # secondary blocks: list bullets, the left compare side
    "--mark": "#E8EEF5",          # the reference rule on a bars card
    "--ink": "#FFFFFF",           # body text
    "--muted": "#8E96A3",         # labels
    "--glass": "rgba(10,12,16,.86)",   # panel body, translucent over the footage
    "--surface": "#07090D",       # opaque full-bleed background (endcard only)
    "--on-accent": "#061018",     # text drawn on an accent fill. Use white on a dark accent
    "--font-head": '"Avenir Next Condensed","Roboto Condensed","Arial Narrow","Helvetica Neue",Arial,sans-serif',
    "--font-text": '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif',
    "--font-mono": 'ui-monospace,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace',
}

# A value goes into a <style> block unescaped, so it may not close a rule or
# the block. Colours, rgba(), and quoted font names all pass this.
_SAFE_VALUE = re.compile(r'^[#(),.%\w\s"\'-]+$')

# Horizontal placement shared by every panel card.
LEFT = 66
WIDTH = 900


def base_css(overrides=None):
    """
    The page CSS. `overrides` maps THEME variable names to new values; an unknown
    name is refused rather than silently ignored, because a typo there would ship
    a half-recoloured style that looks fine until someone compares renders.
    """
    theme = dict(THEME)
    for k, v in (overrides or {}).items():
        if k not in THEME:
            raise SystemExit(f"panel: unknown theme variable {k!r}. Known: {', '.join(THEME)}")
        if not isinstance(v, str) or not _SAFE_VALUE.match(v):
            raise SystemExit(f"panel: theme value for {k} is not a plain CSS value: {v!r}")
        theme[k] = v
    root = ";".join(f"{k}:{v}" for k, v in theme.items())
    return f"""
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1080px;height:1920px;overflow:hidden;background:transparent}}
:root{{{root}}}
body{{font-family:var(--font-text);-webkit-font-smoothing:antialiased}}
#root{{position:relative;width:1080px;height:1920px}}
/* A panel card is a rounded accent spine plus a dark glass body. */
.card{{position:absolute;opacity:0;display:flex;align-items:stretch;
  filter:drop-shadow(0 24px 60px rgba(0,0,0,.55))}}
.spine{{width:26px;flex:0 0 26px;background:var(--accent);
  border-radius:26px 0 0 26px;transform-origin:50% 0}}
.pbody{{flex:1;min-width:0;background:var(--glass);border-radius:0 26px 26px 0;
  border:1px solid color-mix(in srgb, var(--accent) 30%, transparent);border-left:none;
  padding:26px 34px 28px}}
.ac{{color:var(--accent)}}
/* the thin rail that runs above a panel's content */
.rail{{display:flex;align-items:center;gap:14px;margin-bottom:14px;min-height:16px}}
.rail .tag{{font-family:var(--font-mono);font-size:22px;font-weight:600;
  letter-spacing:.2em;text-transform:uppercase;color:var(--accent-soft);white-space:nowrap}}
.rail .dash{{flex:1;height:5px;border-radius:3px;background:linear-gradient(
  90deg,var(--accent) 0%,var(--tone) 60%,transparent 100%)}}
.rail .pip{{width:13px;height:13px;border-radius:50%;background:var(--tone);flex:0 0 13px}}
/* captions */
#caps{{position:absolute;left:56px;right:56px;top:{CAPTION_TOP}px;height:170px;
  display:flex;align-items:center;justify-content:center}}
.cline{{position:absolute;width:100%;text-align:center;opacity:0;
  font-size:58px;font-weight:700;letter-spacing:-.01em;line-height:1.18}}
.cw{{color:#fff;text-shadow:0 4px 18px rgba(0,0,0,.95),0 2px 5px rgba(0,0,0,.9);
  padding:0 8px;display:inline-block;border-radius:6px}}
.cw.on{{color:var(--on-accent);background:var(--accent);text-shadow:none}}
"""


# Phrase captions: same markup and timeline as clean, restyled by base_css.
captions = _clean.captions


def _rail(tag):
    tag_html = f'<span class="tag">{_esc(tag)}</span>' if tag else ""
    return f'<div class="rail"><span class="pip"></span>{tag_html}<span class="dash"></span></div>'


def _shell(cid, inner, extra_class=""):
    cls = f"card {extra_class}".strip()
    return f'<div class="{cls}" id="{cid}"><div class="spine"></div><div class="pbody">{inner}</div></div>'


def _in_out(cid, at, out, x_from=-46):
    """
    The shared entrance: the spine wipes down while the panel slides in from
    the left, then both leave the same way. set() and to() pairs only, so
    seeking to any frame reproduces the same state.
    """
    return f"""
tl.set("#{cid}",{{opacity:0,x:{x_from},y:0}},0);
tl.set("#{cid} .spine",{{scaleY:0}},0);
tl.to("#{cid}",{{opacity:1,x:0,duration:.42,ease:"power3.out"}},{at});
tl.to("#{cid} .spine",{{scaleY:1,duration:.34,ease:"power2.out"}},{at});
tl.to("#{cid}",{{opacity:0,x:{x_from},duration:.36,ease:"power2.in"}},{out});"""


def _box(cid, c, default_y, width=WIDTH, x=LEFT):
    return f"#{cid}{{left:{x}px;top:{c.get('y', default_y)}px;width:{width}px}}"


# --------------------------------------------------------------------------
# CARDS
# --------------------------------------------------------------------------

def hook(i, c):
    """
    The opening hook. HARD RULE: on screen at frame 0, fully opaque, no entrance
    animation. Pinned to 0 by render_card. The **accent** phrase renders as a
    solid accent bar, which survives a downscale to thumbnail size far better
    than coloured text on glass.
    """
    cid = f"hk{i}"
    css = f"""
#{cid}{{left:60px;top:{c.get('y', HOOK_TOP)}px;width:960px;opacity:1}}
#{cid} .k{{font-family:var(--font-mono);font-size:{c.get('kicker_size', 42)}px;font-weight:700;
  letter-spacing:.08em;text-transform:uppercase;color:var(--accent-soft);margin-bottom:14px;
  line-height:1.1}}
#{cid} .h{{font-family:var(--font-head);font-stretch:condensed;font-size:{c.get('size', 92)}px;
  font-weight:800;color:var(--ink);line-height:1;letter-spacing:.005em;text-transform:uppercase;
  text-wrap:balance}}
#{cid} .h .ac{{display:inline-block;background:var(--accent);color:var(--on-accent);
  padding:0 16px 6px;border-radius:10px;margin-top:8px}}"""
    inner = ((f'<div class="k">{_esc(c["kicker"])}</div>' if c.get("kicker") else "")
             + f'<div class="h">{_rich(c["text"])}</div>')
    html = _shell(cid, inner).replace(f'id="{cid}"', f'id="{cid}" style="opacity:1"', 1)
    js = f"""
tl.set("#{cid}",{{opacity:1,x:0,y:0}},0);
tl.set("#{cid} .spine",{{scaleY:1}},0);
tl.to("#{cid}",{{opacity:0,x:-46,duration:.38,ease:"power2.in"}},{c['out']});"""
    return css, html, js


def stat(i, c):
    """A number counting up, large, in the accent colour."""
    cid = f"stat{i}"
    css = f"""
{_box(cid, c, ZONE_TOP)}
#{cid} .v{{font-family:var(--font-head);font-stretch:condensed;font-size:{c.get('size', 148)}px;
  font-weight:800;color:var(--accent);line-height:.92;font-variant-numeric:tabular-nums}}
#{cid} .sub{{font-size:32px;color:var(--ink);margin-top:14px;font-weight:500;line-height:1.28}}"""
    inner = (_rail(c.get("eyebrow", "")) + f'<div class="v" id="{cid}v">0</div>'
             f'<div class="sub">{_rich(c.get("sub", ""))}</div>')
    js = _in_out(cid, c["at"], c["out"]) + f"""
(()=>{{const o={{v:0}};
tl.to(o,{{v:{c['value']},duration:{c.get('count_dur', 1.7)},ease:"power2.out",
  onUpdate:()=>{{document.getElementById("{cid}v").textContent=
    Math.round(o.v).toLocaleString();}}}},{c['at'] + 0.28});}})();"""
    return css, _shell(cid, inner), js


def table(i, c):
    """Rows that light up in turn and scroll when there are more than fit."""
    cid = f"tbl{i}"
    cols = c["columns"]
    widths = c.get("widths") or [1.7]
    colw = c.get("colw", 160)
    h = c.get("height", 420)
    clip_h = max(120, h - 150)
    row_h = 54
    last = len(cols) - 1

    def cells(vals, cls):
        out = ""
        for k, v in enumerate(vals):
            style = f"flex:{widths[0]}" if k == 0 else f"width:{colw}px;text-align:right"
            hi = " hi" if k == last and k > 0 else ""
            out += f'<span class="{cls}{hi}" style="{style}">{_esc(v)}</span>'
        return out

    rows = "".join(f'<div class="r" id="{cid}r{j}">{cells(r, "td")}</div>'
                   for j, r in enumerate(c["rows"]))
    css = f"""
{_box(cid, c, ZONE_LOWER)}
#{cid} .hd{{display:flex;font-family:var(--font-mono);font-size:20px;font-weight:600;
  letter-spacing:.12em;text-transform:uppercase;color:var(--accent-soft);
  border-bottom:2px solid color-mix(in srgb, var(--accent) 50%, transparent);padding-bottom:10px}}
#{cid} .clip{{position:relative;height:{clip_h}px;overflow:hidden;
  -webkit-mask-image:linear-gradient(#000 78%,transparent);mask-image:linear-gradient(#000 78%,transparent)}}
#{cid} .rows{{position:absolute;top:0;left:0;width:100%}}
#{cid} .r{{display:flex;height:{row_h}px;border-bottom:1px solid rgba(255,255,255,.10);
  align-items:center;font-size:26px;font-weight:500;color:var(--ink)}}
#{cid} .td,#{cid} .th{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:10px}}
#{cid} .r .td{{font-variant-numeric:tabular-nums}}
#{cid} .r .td.hi{{color:var(--accent);font-weight:700}}"""
    inner = (_rail(c.get("tag", "")) + f'<div class="hd">{cells(cols, "th")}</div>'
             f'<div class="clip"><div class="rows" id="{cid}b">{rows}</div></div>')
    js = _in_out(cid, c["at"], c["out"])
    for j in range(len(c["rows"])):
        t = round(c["at"] + 0.34 + j * 0.12, 2)
        js += f"""
tl.set("#{cid}r{j}",{{opacity:0,x:-18}},0);
tl.to("#{cid}r{j}",{{opacity:1,x:0,duration:.3,ease:"power2.out"}},{t});"""
    travel = max(0, len(c["rows"]) * row_h - (clip_h - 30))
    if travel:
        js += f"""
tl.set("#{cid}b",{{y:0}},0);
tl.to("#{cid}b",{{y:{-travel},duration:{max(1, c['out'] - c['at'] - 3)},ease:"none"}},{c['at'] + 1.6});"""
    return css, _shell(cid, inner), js


def bars(i, c):
    """
    Bars that grow in turn, with an optional dashed reference rule at the mean.
    Use the rule when the point is that values are flat.
    """
    cid = f"bar{i}"
    series = c["series"]
    mx = max(s["value"] for s in series) or 1
    avg = sum(s["value"] for s in series) / len(series)
    bh = c.get("bar_height", 230)
    cols = "".join(
        f'<div class="bc"><div class="b" id="{cid}b{k}" style="height:{round(s["value"] / mx * 100, 1)}%"></div></div>'
        for k, s in enumerate(series))
    labels = "".join(f'<span>{_esc(s["label"])}</span>' for s in series)
    values = "".join(f'<span id="{cid}v{k}">{_esc(s["value"])}</span>' for k, s in enumerate(series))
    rule = ""
    if c.get("rule"):
        rp = round(avg / mx * bh)
        rule = (f'<div class="rule" style="bottom:{rp}px"></div>'
                f'<div class="rlab" style="bottom:{rp + 10}px">{_esc(c["rule"].get("label", ""))}</div>')
    css = f"""
{_box(cid, c, ZONE_LOWER)}
#{cid} h4{{font-family:var(--font-head);font-stretch:condensed;font-size:44px;font-weight:800;
  color:var(--ink);text-transform:uppercase;letter-spacing:.01em;line-height:1.05}}
#{cid} .sub{{font-size:22px;color:var(--muted);margin-top:6px}}
#{cid} .plot{{position:relative;height:{bh}px;display:flex;align-items:flex-end;gap:14px;margin-top:22px}}
#{cid} .bc{{flex:1;height:100%;display:flex;align-items:flex-end}}
#{cid} .b{{width:100%;border-radius:8px 8px 0 0;transform-origin:50% 100%;
  background:linear-gradient(180deg,var(--accent),color-mix(in srgb, var(--accent) 45%, var(--tone)))}}
#{cid} .lb,#{cid} .vl{{display:flex;gap:14px;margin-top:10px}}
#{cid} .lb span,#{cid} .vl span{{flex:1;text-align:center;white-space:nowrap}}
#{cid} .lb span{{font-size:20px;color:var(--muted)}}
#{cid} .vl span{{font-size:22px;font-weight:700;color:var(--ink);font-variant-numeric:tabular-nums;opacity:0}}
#{cid} .rule{{position:absolute;left:0;right:0;height:0;border-top:4px dashed var(--mark);opacity:0}}
#{cid} .rlab{{position:absolute;right:0;font-family:var(--font-mono);font-size:20px;font-weight:600;
  color:var(--mark);letter-spacing:.08em;text-transform:uppercase;opacity:0}}
#{cid} .note{{margin-top:20px;font-size:26px;font-weight:600;color:var(--ink);opacity:0}}"""
    inner = (_rail(c.get("eyebrow", ""))
             + (f'<h4>{_esc(c["title"])}</h4>' if c.get("title") else "")
             + (f'<div class="sub">{_esc(c["sub"])}</div>' if c.get("sub") else "")
             + f'<div class="plot">{cols}{rule}</div><div class="lb">{labels}</div>'
             f'<div class="vl">{values}</div>'
             + f'<div class="note" id="{cid}n">{_rich(c.get("note", ""))}</div>')
    js = _in_out(cid, c["at"], c["out"])
    for k in range(len(series)):
        t = round(c["at"] + 0.4 + k * 0.1, 2)
        js += f"""
tl.set("#{cid}b{k}",{{scaleY:0}},0);
tl.to("#{cid}b{k}",{{scaleY:1,duration:.5,ease:"power3.out"}},{t});
tl.to("#{cid}v{k}",{{opacity:1,duration:.25}},{round(t + 0.3, 2)});"""
    if c.get("rule"):
        ra = c["rule"].get("at", c["at"] + 8)
        js += f"""
tl.to("#{cid} .rule",{{opacity:1,duration:.5,ease:"power2.inOut"}},{ra});
tl.to("#{cid} .rlab",{{opacity:1,duration:.3}},{ra + 0.2});"""
    if c.get("note"):
        js += f'\ntl.to("#{cid}n",{{opacity:1,duration:.4}},{c.get("note_at", c["at"] + 9)});'
    return css, _shell(cid, inner), js


def lister(i, c):
    """Steps or rules as rounded pills, revealed one at a time."""
    cid = f"lst{i}"
    items = c["items"]
    step = c.get("stagger", 0.9)
    css = f"""
{_box(cid, c, ZONE_LOWER)}
#{cid} h4{{font-family:var(--font-head);font-stretch:condensed;font-size:50px;font-weight:800;
  color:var(--ink);margin-bottom:20px;text-transform:uppercase;letter-spacing:.01em;line-height:1.05}}
#{cid} .row{{display:flex;align-items:center;gap:16px;margin-bottom:12px}}
#{cid} .bul{{width:64px;flex:0 0 64px;height:34px;border-radius:17px;background:var(--tone)}}
#{cid} .row:nth-child(3n+1) .bul{{background:var(--accent)}}
#{cid} .row:nth-child(3n+2) .bul{{background:var(--accent-soft)}}
#{cid} .tx{{font-size:32px;font-weight:600;color:var(--ink);line-height:1.22}}"""
    rows = "".join(f'<div class="row" id="{cid}r{j}"><span class="bul"></span>'
                   f'<span class="tx">{_rich(t)}</span></div>' for j, t in enumerate(items))
    inner = (_rail(c.get("eyebrow", ""))
             + (f'<h4>{_esc(c["title"])}</h4>' if c.get("title") else "")
             + f'<div class="rows">{rows}</div>')
    js = _in_out(cid, c["at"], c["out"])
    for j in range(len(items)):
        t = round(c["at"] + 0.4 + j * step, 2)
        js += f"""
tl.set("#{cid}r{j}",{{opacity:0,x:-22}},0);
tl.to("#{cid}r{j}",{{opacity:1,x:0,duration:.34,ease:"power2.out"}},{t});"""
    return css, _shell(cid, inner), js


def compare(i, c):
    """A against B. The right side carries the accent, so put the answer there."""
    cid = f"cmp{i}"
    css = f"""
{_box(cid, c, ZONE_LOWER)}
#{cid} h4{{font-family:var(--font-head);font-stretch:condensed;font-size:46px;font-weight:800;
  color:var(--ink);margin-bottom:20px;text-transform:uppercase;letter-spacing:.01em;line-height:1.05}}
#{cid} .pair{{display:flex;gap:18px}}
#{cid} .s{{flex:1;padding:22px 20px;border-radius:8px 22px 22px 8px;
  background:rgba(255,255,255,.07);border-left:7px solid var(--tone)}}
#{cid} .s.hi{{border-left-color:var(--accent);background:color-mix(in srgb, var(--accent) 14%, transparent)}}
#{cid} .lab{{font-family:var(--font-mono);font-size:21px;color:var(--accent-soft);font-weight:600;
  letter-spacing:.14em;text-transform:uppercase}}
#{cid} .v{{font-family:var(--font-head);font-stretch:condensed;font-size:66px;font-weight:800;
  color:var(--ink);margin-top:8px;line-height:1.02;font-variant-numeric:tabular-nums}}
#{cid} .note{{font-size:21px;color:var(--muted);margin-top:8px;line-height:1.3}}"""
    sides = ""
    for j, s in enumerate((c["left"], c["right"])):
        hi = " hi" if j == 1 else ""
        sides += (f'<div class="s{hi}" id="{cid}s{j}"><div class="lab">{_esc(s.get("label", ""))}</div>'
                  f'<div class="v">{_esc(s.get("value", ""))}</div>'
                  f'<div class="note">{_esc(s.get("note", ""))}</div></div>')
    inner = (_rail(c.get("eyebrow", ""))
             + (f'<h4>{_rich(c["title"])}</h4>' if c.get("title") else "")
             + f'<div class="pair">{sides}</div>')
    js = _in_out(cid, c["at"], c["out"])
    for j in range(2):
        t = round(c["at"] + 0.36 + j * 0.24, 2)
        js += f"""
tl.set("#{cid}s{j}",{{opacity:0,y:16}},0);
tl.to("#{cid}s{j}",{{opacity:1,y:0,duration:.34,ease:"power2.out"}},{t});"""
    return css, _shell(cid, inner), js


def quote(i, c):
    """One line, large, in condensed caps. For the sentence you want screenshotted."""
    cid = f"qt{i}"
    css = f"""
{_box(cid, c, ZONE_TOP)}
#{cid} .q{{font-family:var(--font-head);font-stretch:condensed;font-size:{c.get('size', 72)}px;
  font-weight:800;color:var(--ink);line-height:1.04;letter-spacing:.005em;text-transform:uppercase;
  text-wrap:balance}}
#{cid} .attr{{font-family:var(--font-mono);font-size:24px;color:var(--accent-soft);margin-top:18px;
  letter-spacing:.12em;text-transform:uppercase}}"""
    inner = (_rail("") + f'<div class="q">{_rich(c["text"])}</div>'
             + (f'<div class="attr">{_esc(c["attr"])}</div>' if c.get("attr") else ""))
    return css, _shell(cid, inner), _in_out(cid, c["at"], c["out"])


def image(i, c):
    """
    A screenshot or UI insert inside a panel. `src` is a path relative to the
    project directory: copy the file in before rendering. Crop it tight first.
    """
    cid = f"img{i}"
    width = c.get("width", WIDTH)
    x = c.get("x", LEFT)
    css = f"""
{_box(cid, c, ZONE_TOP, width=width, x=x)}
#{cid} .shot{{border-radius:14px;overflow:hidden;
  border:1px solid color-mix(in srgb, var(--accent) 30%, transparent)}}
#{cid} .shot img{{width:100%;display:block}}"""
    inner = _rail(c.get("label", "")) + f'<div class="shot"><img src="{_attr(c["src"])}" alt=""></div>'
    return css, _shell(cid, inner), _in_out(cid, c["at"], c["out"])


def endcard(i, c):
    """
    Full-bleed opaque close, on the --surface colour. Not for social cuts:
    rendered only by reel-compose.py --cut --endcard.
    """
    cid = f"end{i}"
    css = f"""
#{cid}{{position:absolute;inset:0;background:var(--surface);opacity:0;filter:none;display:flex;
  flex-direction:column;align-items:center;justify-content:center;padding:0 110px}}
#{cid} .t{{font-family:var(--font-head);font-stretch:condensed;font-size:96px;font-weight:800;
  color:var(--ink);text-align:center;line-height:1.0;text-transform:uppercase}}
#{cid} .s{{font-size:33px;color:var(--muted);margin-top:24px;text-align:center;line-height:1.35;max-width:780px}}
#{cid} .pill{{margin-top:58px;background:var(--accent);color:var(--on-accent);font-family:var(--font-head);
  font-stretch:condensed;font-size:52px;font-weight:800;padding:22px 58px;border-radius:999px;
  text-transform:uppercase}}
#{cid} .foot{{position:absolute;bottom:150px;font-family:var(--font-mono);font-size:24px;
  letter-spacing:.18em;text-transform:uppercase;color:var(--accent-soft);font-weight:600}}"""
    html = (f'<div class="card" id="{cid}">'
            f'<div class="t">{_esc(c.get("title", ""))}</div>'
            f'<div class="s">{_esc(c.get("sub", ""))}</div>'
            f'<div class="pill">{_esc(c.get("pill", ""))}</div>'
            f'<div class="foot">{_esc(c.get("foot", ""))}</div></div>')
    js = f"""
tl.set("#{cid}",{{opacity:0}},0);
tl.to("#{cid}",{{opacity:1,duration:.34,ease:"power2.out"}},{c['at']});"""
    return css, html, js


REGISTRY = {
    "hook": hook, "stat": stat, "table": table, "bars": bars,
    "list": lister, "compare": compare, "quote": quote, "image": image,
    "endcard": endcard,
}


def render_card(i, c):
    return _clean.render_with(REGISTRY, i, c)


if __name__ == "__main__":
    print(__doc__.strip().splitlines()[0])
    print("\nTheme variables (override them in a copy of reel_cards_example_brand.py):")
    for k, v in THEME.items():
        print(f"  {k:<14} {v}")
