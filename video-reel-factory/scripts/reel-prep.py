#!/usr/bin/env python3
"""
reel-prep.py: the mechanical front half of a talking-head edit.

Takes a raw recording and produces everything the composition builder needs:
a word-level transcript, caption lines already grouped and clamped, detected
platform-specific speech, and clean cut points for each platform variant.

This is the part that requires zero judgement, so it should never be done by
hand. What it deliberately does NOT do is choose motion graphics, because that
needs to know what the video is about and guessing produces generic cards.

Requires:
  Python 3.8+ plus openai-whisper for transcription (pip install -U openai-whisper)
  reel_markers.py next to this file (imported automatically, any working directory)
  ffmpeg and ffprobe on PATH
  tesseract on PATH, optional, only used for the mirrored-source check

Example:
  python3 reel-prep.py recording.mp4 --model small --outdir ./prep --keywords TEARDOWN

Outputs into <outdir>/:
  transcript.json   full Whisper output
  words.json        flat word list with timings
  prep.json         caption lines, cut points, platform plan, probe data
  REPORT.md         human-readable summary, read this first
  audio.wav         16 kHz mono copy of the source audio. It is a by-product of
                    the transcription step, not a cache: every run extracts it
                    again and overwrites whatever was there. Delete it when you are
                    done; it is a verbatim copy of everything the speaker said.
"""

import argparse, json, re, shutil, subprocess, sys
from pathlib import Path

# Resolve this script's own directory so `import reel_markers` works from any
# working directory, and so a symlinked copy still finds its library.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from reel_markers import PLATFORM_MARKERS, find_keyword_spans
except ImportError:
    sys.exit("error: could not import reel_markers.py.\n"
             "       It must sit in the same directory as reel-prep.py.")

INSTALL_HINTS = {
    "ffmpeg": "Install ffmpeg. macOS: brew install ffmpeg. Debian/Ubuntu: sudo apt install ffmpeg.",
    "ffprobe": "ffprobe ships with ffmpeg. macOS: brew install ffmpeg. Debian/Ubuntu: sudo apt install ffmpeg.",
    "tesseract": "Install tesseract. macOS: brew install tesseract. Debian/Ubuntu: sudo apt install tesseract-ocr.",
}


def require_tool(name):
    """Fail with a readable message instead of a FileNotFoundError traceback."""
    if shutil.which(name) is None:
        sys.exit(f"error: '{name}' was not found on PATH.\n       {INSTALL_HINTS.get(name, '')}".rstrip())


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except FileNotFoundError:
        sys.exit(f"error: '{cmd[0]}' was not found on PATH.\n       {INSTALL_HINTS.get(cmd[0], '')}".rstrip())


def probe(path):
    r = run(["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)])
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(f"error: ffprobe could not read {path}\n       {r.stderr.strip() or 'no output from ffprobe'}")
    d = json.loads(r.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
    num, den = (v.get("r_frame_rate", "30/1").split("/") + ["1"])[:2]
    try:
        fps = round(float(num) / float(den or 1), 3)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {
        "duration": round(float(d.get("format", {}).get("duration", 0)), 2),
        "size_mb": round(int(d.get("format", {}).get("size", 0)) / 1048576, 1),
        "width": v.get("width"), "height": v.get("height"), "fps": fps,
        "vcodec": v.get("codec_name"), "acodec": a.get("codec_name"),
        "channels": a.get("channels"),
        "vertical": bool((v.get("height") or 0) > (v.get("width") or 0)),
    }


def detect_mirrored(path, outdir):
    """
    Selfie captures are usually mirrored, which makes in-frame text read
    backwards. A wrong flip is unrecoverable, so this reports a signal and
    never decides. It returns THREE states, not two: True, False, or None
    for "no legible text, cannot tell".

    Method: OCR the frame and its mirror, and compare tesseract's MEAN
    CONFIDENCE. Word count does not work. On real footage both orientations
    returned 4 tokens while confidence separated them 7.7 vs 38.3. Sparse
    background text also needs --psm 11, a crop, an upscale and a contrast
    boost or tesseract reads nothing at all.
    """
    if shutil.which("tesseract") is None:
        return {"checked": False,
                "reason": "tesseract not installed (" + INSTALL_HINTS["tesseract"] + ")",
                "suggest_flip": None}

    def conf(img):
        r = run(["tesseract", str(img), "stdout", "--psm", "11", "tsv"])
        vals = []
        for line in r.stdout.splitlines()[1:]:
            f = line.split("\t")
            if len(f) >= 12 and f[11].strip() and len(f[11].strip()) > 2:
                try:
                    c = float(f[10])
                except ValueError:
                    continue
                if c >= 0:
                    vals.append(c)
        return (sum(vals) / len(vals) if vals else 0.0), len(vals)

    best = {"as_is": 0.0, "flipped": 0.0, "tokens": 0}
    # Sample a few frames and a few bands, because text can sit anywhere in frame.
    for t in (2, 12, 30):
        for band, crop in (("top", "crop=iw:ih/3:0:0"), ("mid", "crop=iw:ih/3:0:ih/3")):
            a_png = outdir / f"_m_{t}_{band}.png"
            b_png = outdir / f"_m_{t}_{band}_f.png"
            vf = f"{crop},scale=iw*2:ih*2,eq=contrast=1.6:brightness=0.02,format=gray"
            run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(path),
                 "-frames:v", "1", "-vf", vf, str(a_png)])
            if not a_png.exists():
                continue
            run(["ffmpeg", "-v", "error", "-y", "-i", str(a_png), "-vf", "hflip", str(b_png)])
            ca, na = conf(a_png)
            cb, nb = conf(b_png)
            if max(ca, cb) > max(best["as_is"], best["flipped"]):
                best = {"as_is": round(ca, 1), "flipped": round(cb, 1), "tokens": max(na, nb),
                        "sample": f"{t}s/{band}"}
            for f in (a_png, b_png):
                f.unlink(missing_ok=True)

    hi, lo = max(best["as_is"], best["flipped"]), min(best["as_is"], best["flipped"])
    # Demand real text AND a real margin. A ratio test alone gets too strict at
    # high confidence (60 vs 41 is decisive but fails a 1.5x rule), so gate on
    # an absolute gap instead. Two low readings are noise, not evidence.
    if hi < 30 or (hi - lo) < 10:
        return {"checked": True, **best, "suggest_flip": None,
                "note": "no legible in-frame text, decide visually, do not guess"}
    return {"checked": True, **best,
            "suggest_flip": best["flipped"] > best["as_is"],
            "note": "confirm visually before rendering, a wrong flip is unrecoverable"}


def transcribe(path, outdir, model_name):
    require_tool("ffmpeg")
    # Whisper is fed a wav, so one is extracted here. It is left on disk rather
    # than written to a temporary directory, which makes it easy to listen back to
    # what the model was actually given, but it is a by-product and not a cache:
    # this runs unconditionally with -y and nothing anywhere reads an existing
    # copy, so every run overwrites it. It is a verbatim copy of the source audio,
    # and it is named in this script's docstring and in the summary it prints, so
    # nobody is surprised to find it there.
    wav = outdir / "audio.wav"
    r = run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1",
             "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
    if not wav.exists():
        sys.exit("error: ffmpeg could not extract audio from the source.\n"
                 f"       {r.stderr.strip() or 'no error output'}")
    try:
        import whisper
    except ImportError:
        sys.exit("error: the 'whisper' Python package is not installed.\n"
                 "       Install it with: pip install -U openai-whisper\n"
                 "       (it also needs ffmpeg on PATH, and downloads its model on first run)")
    try:
        model = whisper.load_model(model_name)
    except Exception as e:
        sys.exit(f"error: Whisper could not load the '{model_name}' model.\n"
                 "       Models download on first use, so check the name (tiny, base, small,\n"
                 "       medium, large) and your network connection.\n"
                 f"       {type(e).__name__}: {e}")
    res = model.transcribe(str(wav), word_timestamps=True, language="en", fp16=False)
    with open(outdir / "transcript.json", "w") as fh:
        json.dump(res, fh, indent=1)
    words = []
    for seg in res["segments"]:
        for w in seg.get("words", []):
            t = w["word"].strip()
            if t:
                words.append({"word": t, "start": round(w["start"], 2), "end": round(w["end"], 2)})
    # Whisper splits "$10,000" into "$10" + ",000", so rejoin orphan punctuation.
    merged = []
    for w in words:
        if merged and (w["word"] in (",", ".") or (w["word"][0] in ",." and len(w["word"]) > 1)):
            merged[-1]["word"] += w["word"]
            merged[-1]["end"] = w["end"]
            continue
        merged.append(dict(w))
    with open(outdir / "words.json", "w") as fh:
        json.dump(merged, fh, indent=1)
    return merged


def caption_lines(words, max_words=4, max_chars=24):
    lines, cur = [], []
    for w in words:
        cur.append(w)
        joined = " ".join(x["word"] for x in cur)
        if len(cur) >= max_words or len(joined) > max_chars or w["word"].endswith((".", "?", "!")):
            lines.append(cur); cur = []
    if cur:
        lines.append(cur)
    # A line is clamped to vanish just before the next one appears, or they stack
    # on screen. The 0.2s floor below wins over that clamp, so two lines starting
    # less than 0.2s apart do still overlap for the remainder. That is deliberate:
    # a caption flashed for 40ms reads as a glitch, and it is rare enough to fix
    # by hand in prep.json when it happens.
    out = []
    for i, ln in enumerate(lines):
        s = ln[0]["start"]
        e = ln[-1]["end"] + 0.12
        if i + 1 < len(lines):
            e = min(e, lines[i + 1][0]["start"] - 0.01)
        out.append({"start": s, "end": max(e, s + 0.2),
                    "text": " ".join(x["word"] for x in ln),
                    "words": [{"s": x["start"], "e": x["end"], "w": x["word"]} for x in ln]})
    return out


def find_markers(words, extra_keywords):
    """Where does platform-specific speech begin?"""
    joined = " ".join(w["word"].lower() for w in words)
    hits = []
    # The built-in list is matched as written, as regex patterns over the joined
    # transcript. Verify reads the same list from the same file.
    for pat, label in PLATFORM_MARKERS:
        for m in re.finditer(pat, joined):
            # map char offset back to a word index
            prefix = joined[:m.start()]
            widx = len(prefix.split())
            if widx < len(words):
                hits.append({"at": words[widx]["start"], "label": label,
                             "phrase": m.group(0)[:40]})
    # Custom keywords are NOT regex. They go through the shared collapsed-form
    # matcher, the same one verify's gate uses, because Whisper renders a shouted
    # TEARDOWN as "tear down" and a literal token match here would plan no cut
    # while the gate downstream still hard-failed on it.
    for h in find_keyword_spans(words, extra_keywords):
        i, j = h["word_index"], h["end_index"]
        phrase = " ".join(w["word"] for w in words[i:j + 1])
        hits.append({"at": words[i]["start"],
                     "label": f"custom keyword '{h['keyword']}'",
                     "phrase": phrase[:40]})
    hits.sort(key=lambda h: h["at"])
    return hits


def find_gaps(words, min_gap=0.5):
    gaps = []
    for a, b in zip(words, words[1:]):
        g = b["start"] - a["end"]
        if g >= min_gap:
            gaps.append({"from": a["end"], "to": b["start"], "gap": round(g, 2),
                         "after": a["word"], "before": b["word"]})
    return gaps


def pick_cut(words, markers, gaps):
    """
    The neutral cut ends before the first platform-specific phrase, at the
    nearest silent gap so the audio never clips mid-word.
    """
    if not markers:
        return {"needed": False, "reason": "no platform-specific speech found, one cut serves every platform"}
    first = markers[0]["at"]
    before = [g for g in gaps if g["to"] <= first]
    if not before:
        return {"needed": True, "cut_at": round(max(0.0, first - 0.3), 2),
                "confidence": "low",
                "reason": f"no silent gap before '{markers[0]['phrase']}' at {first}s, cut may clip a word"}
    g = before[-1]
    return {"needed": True,
            "cut_at": round(g["from"] + min(0.4, g["gap"] * 0.6), 2),
            "confidence": "high",
            "gap": g,
            "reason": f"last clean gap before {markers[0]['label']} at {first}s"}


def build_parser():
    ap = argparse.ArgumentParser(
        prog="reel-prep.py",
        description="Transcribe a talking-head recording and plan its platform cuts. "
                    "Writes transcript.json, words.json, prep.json, REPORT.md and "
                    "audio.wav (a 16 kHz mono copy of the source audio, rewritten every run).",
        epilog="example:\n"
               "  python3 reel-prep.py recording.mp4 --model small --keywords TEARDOWN\n\n"
               "needs ffmpeg and ffprobe on PATH, plus the openai-whisper package.\n"
               "tesseract is optional and only powers the mirrored-source check.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="path to the raw recording")
    ap.add_argument("--outdir", default=None,
                    help="where to write the outputs (default: <video-dir>/<video-name>_prep)")
    ap.add_argument("--model", default="small",
                    help="Whisper model name: tiny, base, small, medium, large (default: small). "
                         "Bigger is slower and more accurate")
    ap.add_argument("--keywords", default="",
                    help="comma-separated extra CTA keywords to treat as platform-specific speech, "
                         "for example TEARDOWN,BLUEPRINT")
    return ap


def main():
    a = build_parser().parse_args()

    require_tool("ffprobe")
    require_tool("ffmpeg")

    src = Path(a.video).expanduser()
    if not src.exists():
        sys.exit(f"error: not found: {src}")
    outdir = Path(a.outdir).expanduser() if a.outdir else src.parent / f"{src.stem}_prep"
    outdir.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] probing {src.name}")
    info = probe(src)
    print(f"      {info['width']}x{info['height']} @ {info['fps']}fps, {info['duration']}s, {info['size_mb']}MB")

    print("[2/4] checking for mirrored source")
    mirror = detect_mirrored(src, outdir)

    print(f"[3/4] transcribing (whisper:{a.model}), this is the slow part")
    words = transcribe(src, outdir, a.model)
    if not words:
        sys.exit("error: Whisper returned no words. Check that the source actually has speech audio.")
    print(f"      {len(words)} words, {words[0]['start']}s to {words[-1]['end']}s")

    print("[4/4] planning cuts")
    kws = [k.strip() for k in a.keywords.split(",") if k.strip()]
    lines = caption_lines(words)
    markers = find_markers(words, kws)
    gaps = find_gaps(words)
    cut = pick_cut(words, markers, gaps)

    prep = {"source": str(src), "probe": info, "mirror": mirror,
            "n_words": len(words), "caption_lines": lines,
            "platform_markers": markers, "silent_gaps": gaps[:40], "neutral_cut": cut}
    with open(outdir / "prep.json", "w") as fh:
        json.dump(prep, fh, indent=1)

    # ---- report
    R = []
    R.append(f"# Edit prep: {src.name}\n")
    R.append(f"`{info['width']}x{info['height']}` @ {info['fps']}fps, **{info['duration']}s**, {info['size_mb']} MB, "
             f"{'vertical' if info['vertical'] else 'horizontal'}\n")
    R.append("## Mirrored?\n")
    if mirror.get("checked"):
        verdict = {True: "FLIP IT", False: "do not flip", None: "CANNOT TELL, decide visually"}[mirror.get("suggest_flip")]
        R.append(f"OCR confidence **{mirror.get('as_is')}** as-is vs **{mirror.get('flipped')}** flipped "
                 f"({mirror.get('tokens')} tokens, sample {mirror.get('sample', 'n/a')}) gives "
                 f"**{verdict}**. {mirror['note']}\n")
    else:
        R.append(f"Not checked ({mirror.get('reason')}). Look at a frame: if on-screen text reads backwards, add `hflip`.\n")
    R.append("## Platform-specific speech\n")
    if markers:
        R.append("These phrases lock the footage to one platform:\n")
        for m in markers:
            R.append(f"- **{m['at']}s**, {m['label']}: \"{m['phrase']}\"")
        R.append("")
    else:
        R.append("None found. One cut works everywhere.\n")
    R.append("## Neutral cut\n")
    if cut.get("needed"):
        R.append(f"Cut at **{cut['cut_at']}s** ({cut['confidence']} confidence). {cut['reason']}\n")
        if cut.get("gap"):
            R.append(f"Lands in a {cut['gap']['gap']}s gap after \"...{cut['gap']['after']}\".\n")
        R.append(f"The full-length platform keeps all {info['duration']}s. The neutral cut gets "
                 f"{cut['cut_at']}s plus an end card.\n")
    else:
        R.append(f"{cut['reason']}\n")
    R.append("## Captions\n")
    R.append(f"{len(lines)} lines, in `prep.json` under `caption_lines`. Each line is clamped to end "
             "just before the next one starts, except where that would leave it on screen for under "
             "0.2s, in which case the 0.2s floor wins and those two lines overlap. Rare, and visible "
             "in a snapshot.\n")
    R.append("## Next\n")
    R.append("Feed `prep.json` to the composition builder. Decide the motion-graphics cards by hand, "
             "because that needs to know what the video is actually about.\n")
    (outdir / "REPORT.md").write_text("\n".join(R))

    print(f"\nOK  {outdir}/")
    print(f"  REPORT.md   read this first")
    print(f"  prep.json   {len(lines)} caption lines, cut plan")
    print(f"  audio.wav   16 kHz mono copy of the source audio, rewritten every run, delete when done")
    if cut.get("needed"):
        print(f"\n  neutral cut at {cut['cut_at']}s ({cut['confidence']} confidence)")
    if mirror.get("suggest_flip"):
        print("  source looks MIRRORED, confirm before rendering")


if __name__ == "__main__":
    main()
