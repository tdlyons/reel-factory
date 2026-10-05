#!/usr/bin/env python3
"""
reel_cards_example_brand.py: the `example-brand` style. The `panel` look in a
different set of colours, and a template for your own recolour.

TO MAKE YOUR OWN STYLE FROM THIS FILE:
  1. Copy it next to itself as reel_cards_<yourname>.py, for example
     reel_cards_acme.py. The part after reel_cards_ becomes the style name, with
     underscores read as dashes, so reel_cards_acme_dark.py is --style acme-dark.
  2. Change the hex values in COLOURS below to your brand colours.
  3. Compose with --style <yourname>. Nothing else needs registering:
     reel-compose.py finds every reel_cards_*.py file in this folder.

Everything else (card shapes, motion, zones, captions, validation) comes from
reel_cards_panel.py by reference, so this file never drifts from it.
"""

import reel_cards_panel as _panel

SUMMARY = "panel recoloured, a template to copy for your own brand colours"

COLOURS = {
    "--accent": "#8B7CF6",        # your main brand colour: spine, highlights, bars
    "--accent-soft": "#D4CCFF",   # a lighter tint of it, for kickers and small labels
    "--tone": "#9C9AB0",          # a neutral second colour for secondary blocks
    "--mark": "#F1EEFF",          # the reference line on a bars card
    "--glass": "rgba(14,12,22,.86)",   # panel background, keep it dark and slightly see-through
    "--surface": "#0B0A12",       # solid background, only used by the endcard
    "--on-accent": "#FFFFFF",     # text on top of --accent: white for a dark accent, near-black for a light one
    # Fonts are variables too. Uncomment to set your own (it must be installed
    # on the machine that renders, or vendored into the project's assets/):
    # "--font-head": '"Your Display Font","Arial Narrow",sans-serif',
}


def base_css():
    return _panel.base_css(COLOURS)


captions = _panel.captions
render_card = _panel.render_card
REGISTRY = _panel.REGISTRY
estimate_box = _panel.estimate_box


if __name__ == "__main__":
    css = base_css()
    for var, value in COLOURS.items():
        state = "ok  " if f"{var}:{value}" in css else "FAIL"
        print(f"  {state} {var:<14} {value}")
