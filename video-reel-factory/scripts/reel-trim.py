#!/usr/bin/env python3
"""
reel-trim.py: cut filler and repeated phrases out of a reel, everywhere at once.

Cutting a phrase out of a talking-head take is not one edit, it is four that
have to agree: the source video, the caption word timings, the card cues, and
the neutral cut point. Do any of them by hand and they drift apart. This owns
all four from one list of cuts.

It writes a trimmed prep.json and a trimmed cards.json, and prints the ffmpeg
command that builds the matching trimmed source. Build that ONE trimmed source,
then compose and composite both variants from it.

What it remaps:
  prep.json   caption_lines (every word), probe.duration, neutral_cut.cut_at,
              platform_markers[].at, silent_gaps, and source (set to the
              trimmed file, with the original recorded under "trim")
  cards.json  every card's at and out, a bars card's rule.at and note_at, and
              the top-level caption_moves. The hook stays pinned to 0.

How a caption word is treated:
  A word wholly inside a cut is gone. A word that straddles a cut boundary is
  the interesting case, because cut points come from the audio and word
  boundaries come from Whisper, and the two disagree by tens of milliseconds.
  So a word can straddle on paper while staying fully audible. It is KEPT,
  clamped to the boundary, when at least KEEP_FRACTION of it survives, and
  dropped only when most of it is gone. Dropping every straddler silently
  deletes captions for words the viewer clearly hears.

Finding cut points, do not eyeball them:
  1. Read the phrase's word timings out of prep.json.
  2. Scan 20ms RMS windows either side for the quietest trough. A splice in a
     trough is inaudible; one mid-phoneme is obvious.
  3. Test the join before committing: concatenate the two sides and
     re-transcribe that window. A cut 50ms early can turn "valuable" into
     "value boy", and a pause inside a spoken acronym looks exactly like a
     word boundary.

Requires:
  Python 3.8+ (standard library only)
  reel_cards.py next to this file, for the same field validation compose uses
  ffmpeg to build the trimmed source afterwards (the command is printed)

Example:
  python3 reel-trim.py --prep prep.json --cards cards.json \\
      --cuts 14.48-15.72,28.02-29.79 \\
      --out-prep prep_trim.json --out-cards cards_trim.json
"""

import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import reel_cards as C
except ImportError:
    sys.exit("error: could not import reel_cards.py.\n"
             "       It must sit in the same directory as reel-trim.py.")

KEEP_FRACTION = 0.4   # share of a straddling word that must survive for it to stay
LINE_TAIL = 0.06      # seconds a caption line lingers after its last word
LINE_GAP = 0.02       # minimum gap between one line's end and the next one's start


def parse_cuts(spec, duration):
    cuts = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            a, b = part.split("-")
            a, b = float(a), float(b)
        except ValueError:
            sys.exit(f"error: bad cut {part!r}, expected START-END in seconds, e.g. 14.48-15.72")
        if b <= a:
            sys.exit(f"error: cut {part!r} ends before it starts")
        if a < 0 or b > duration + 0.01:
            sys.exit(f"error: cut {part!r} falls outside the recording (0 to {duration}s)")
        cuts.append((a, b))
    if not cuts:
        sys.exit("error: --cuts is empty")
    cuts.sort()
    for (a1, b1), (a2, b2) in zip(cuts, cuts[1:]):
        if a2 < b1:
            sys.exit(f"error: cuts {a1}-{b1} and {a2}-{b2} overlap")
    return cuts


def make_mapper(cuts):
    """
    Source seconds to trimmed seconds. A moment inside a cut returns None, or
    with clamp=True, the point the cut collapsed to.
    """
    def m(t, clamp=False):
        removed = 0.0
        for a, b in cuts:
            if t >= b:
                removed += b - a
            elif t > a:
                return round(a - removed, 3) if clamp else None
        return round(t - removed, 3)
    return m


def load_json(path, label):
    p = Path(path).expanduser()
    if not p.exists():
        sys.exit(f"error: {label} not found: {p}")
    try:
        with open(p) as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        sys.exit(f"error: {label} is not valid JSON ({p}): {e}")


def survivor(w, cuts):
    """The part of one word that survives the cuts, or None if most of it is gone."""
    dur = max(1e-6, w["e"] - w["s"])
    for a, b in cuts:
        if w["e"] <= a or w["s"] >= b:
            continue
        if w["s"] >= a and w["e"] <= b:
            return None
        before = max(0.0, a - w["s"])
        after = max(0.0, w["e"] - b)
        if before >= after and before / dur >= KEEP_FRACTION:
            return {**w, "e": a - 1e-4}
        if after > before and after / dur >= KEEP_FRACTION:
            return {**w, "s": b + 1e-4}
        return None
    return w


def build_parser():
    ap = argparse.ArgumentParser(
        prog="reel-trim.py",
        description="Remove filler and repeated phrases from a reel, keeping the source, the "
                    "caption timings, the card cues and the neutral cut point in step.",
        epilog="example:\n"
               "  python3 reel-trim.py --prep prep.json --cards cards.json \\\n"
               "      --cuts 14.48-15.72,28.02-29.79 \\\n"
               "      --out-prep prep_trim.json --out-cards cards_trim.json\n\n"
               "then build the trimmed source with the ffmpeg command it prints, and compose\n"
               "from prep_trim.json and cards_trim.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prep", required=True, help="prep.json written by reel-prep.py")
    ap.add_argument("--cards", required=True, help="cards.json, an object with a \"cards\" list")
    ap.add_argument("--cuts", required=True,
                    help="comma-separated START-END ranges in source seconds to remove")
    ap.add_argument("--out-prep", required=True, help="where to write the trimmed prep.json")
    ap.add_argument("--out-cards", required=True, help="where to write the trimmed cards.json")
    ap.add_argument("--out-source", default="trimmed.mov",
                    help="file name the printed ffmpeg command writes the trimmed source to, and "
                         "that the trimmed prep.json records as its source (default: trimmed.mov)")
    ap.add_argument("--platform-cut", type=float, default=None,
                    help="a source time to remap and print, for a cut point you chose by hand. "
                         "prep.json's own neutral_cut.cut_at is remapped automatically")
    return ap


def main():
    a = build_parser().parse_args()

    prep = load_json(a.prep, "prep.json")
    spec = load_json(a.cards, "cards.json")
    if not isinstance(spec, dict) or not isinstance(spec.get("cards"), list):
        sys.exit("error: cards.json must be an object with a top-level \"cards\" list, "
                 "like {\"cards\": [...]}, not a bare list.")
    if "caption_lines" not in prep or "probe" not in prep:
        sys.exit("error: prep.json is missing 'caption_lines' or 'probe'. "
                 "Regenerate it with reel-prep.py.")
    try:
        lines_in = C.normalise_caption_lines(prep["caption_lines"])
        cards_in = [C.normalise_card(i, c) for i, c in enumerate(spec["cards"])]
        moves_in = C.normalise_caption_moves(spec.get("caption_moves"))
    except C.CardValueError as e:
        sys.exit(f"error: {e}")

    src_dur = float(prep["probe"]["duration"])
    cuts = parse_cuts(a.cuts, src_dur)
    m = make_mapper(cuts)
    removed = sum(b - x for x, b in cuts)
    new_dur = round(src_dur - removed, 3)

    # ---- captions
    kept_lines, dropped = [], []
    for L in lines_in:
        ws = []
        for w in L["words"]:
            sw = survivor(w, cuts)
            s = e = None
            if sw is not None:
                s, e = m(sw["s"]), m(sw["e"])
            if s is None or e is None:
                dropped.append(str(w.get("w", "")))
                continue
            ws.append({**w, "s": s, "e": e})
        if not ws:
            continue
        L = dict(L)
        L["words"] = ws
        L["start"] = ws[0]["s"]
        L["end"] = round(ws[-1]["e"] + LINE_TAIL, 3)
        L["text"] = " ".join(str(w.get("w", "")) for w in ws)
        kept_lines.append(L)
    # No line may outlive the next one's start.
    for i, L in enumerate(kept_lines[:-1]):
        L["end"] = round(min(L["end"], kept_lines[i + 1]["start"] - LINE_GAP), 3)

    out_prep = dict(prep)
    out_prep["caption_lines"] = kept_lines
    out_prep["probe"] = dict(prep["probe"], duration=new_dur)
    out_prep["source"] = a.out_source
    out_prep["trim"] = {"from": prep.get("source"), "cuts": [list(c) for c in cuts],
                        "removed": round(removed, 3)}

    markers = []
    for mk in prep.get("platform_markers") or []:
        at = m(mk.get("at", 0))
        if at is not None:
            markers.append(dict(mk, at=at))
    out_prep["platform_markers"] = markers

    gaps = []
    for g in prep.get("silent_gaps") or []:
        f, t = m(g.get("from", 0)), m(g.get("to", 0))
        if f is not None and t is not None:
            gaps.append(dict(g, **{"from": f, "to": t}))
    out_prep["silent_gaps"] = gaps

    nc = prep.get("neutral_cut") or {}
    nc_line = None
    if nc.get("needed") and nc.get("cut_at") is not None:
        new_cut = m(float(nc["cut_at"]), clamp=True)
        out_prep["neutral_cut"] = dict(nc, cut_at=new_cut)
        nc_line = f"  neutral cut {nc['cut_at']}s -> {new_cut}s (written to the trimmed prep.json)"

    # ---- cards
    cards, notes = [], []
    for i, c in enumerate(cards_in):
        c = dict(c)
        kind = c.get("type")
        if kind != "hook" and c.get("at") is not None:
            c["at"] = m(c["at"], clamp=True)
        if c.get("out") is not None:
            c["out"] = m(c["out"], clamp=True)
        if c.get("note_at") is not None:
            c["note_at"] = m(c["note_at"], clamp=True)
        if isinstance(c.get("rule"), dict) and c["rule"].get("at") is not None:
            c["rule"] = dict(c["rule"], at=m(c["rule"]["at"], clamp=True))
        start = 0 if kind == "hook" else c.get("at", 0)
        if c.get("out") is not None and c["out"] - start < 0.5:
            notes.append(f"  NOTE: dropped card {i} ({kind}). Its whole on-screen window fell "
                         "inside the cuts, so it would flash for under 0.5s.")
            continue
        cards.append(c)

    moves = []
    for mv in moves_in:
        moves.append(dict(mv, at=m(mv["at"], clamp=True)))

    out_cards = dict(spec)
    out_cards["cards"] = cards
    if moves or "caption_moves" in spec:
        out_cards["caption_moves"] = moves

    if not any(c.get("type") == "hook" for c in cards):
        notes.append("  NOTE: the trimmed cards.json has no hook card, so reel-compose.py "
                     "will refuse it until you add one.")

    with open(Path(a.out_prep).expanduser(), "w") as fh:
        json.dump(out_prep, fh, indent=1)
    with open(Path(a.out_cards).expanduser(), "w") as fh:
        json.dump(out_cards, fh, indent=2)

    print(f"OK {len(cuts)} cut(s), {removed:.2f}s removed")
    print(f"  duration {src_dur:.2f}s -> {new_dur:.2f}s")
    print(f"  captions: {len(kept_lines)} lines, {len(dropped)} words dropped"
          + (f": {' '.join(dropped)}" if dropped else ""))
    print(f"  cards: {len(cards)} kept of {len(cards_in)}")
    for n in notes:
        print(n)
    if nc_line:
        print(nc_line)
    if a.platform_cut is not None:
        print(f"  platform cut {a.platform_cut}s -> {m(a.platform_cut, clamp=True)}s")
    print(f"  wrote {a.out_prep} and {a.out_cards}")

    # ---- the trimmed source, as one ffmpeg command
    keep, prev = [], 0.0
    for x, b in cuts:
        if x > prev:
            keep.append((prev, x))
        prev = b
    if prev < src_dur:
        keep.append((prev, None))
    v = aud = ""
    for i, (s, e) in enumerate(keep):
        rng = f"start={s}" + (f":end={e}" if e is not None else "")
        v += f"[0:v]trim={rng},setpts=PTS-STARTPTS[v{i}];"
        aud += f"[0:a]atrim={rng},asetpts=PTS-STARTPTS[a{i}];"
    pairs = "".join(f"[v{i}][a{i}]" for i in range(len(keep)))
    print("\n  build the trimmed source with (SRC is the original recording):")
    print("    ffmpeg -y -i SRC -filter_complex \\")
    print(f'      "{v}{aud}{pairs}concat=n={len(keep)}:v=1:a=1[tv][ta]" \\')
    print('      -map "[tv]" -map "[ta]" -c:v libx264 -preset medium -crf 14 -pix_fmt yuv420p \\')
    print(f"      -c:a pcm_s16le -ar 48000 {a.out_source}")
    print("\n  Then re-transcribe the trimmed audio and compare it to the trimmed captions\n"
          "  before composing (Gate C in SKILL.md). The mirror verdict carries over unchanged.")


if __name__ == "__main__":
    main()
