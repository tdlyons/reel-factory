#!/usr/bin/env python3
"""
reel-cut.py — clean-cut a raw talking-head take before reel-prep sees it.

Removes dead air, breath pauses, retakes, false starts, filler-only blips and
"let me redo that" asides. The output is a clean MP4 that the rest of the reel
factory treats as if the speaker had recorded it in one perfect take, so nothing
downstream (captions, cards, platform cut) needs remapping.

It merges two approaches:
  * waveform cutting: the WAVEFORM decides where to cut. Speech
    blocks come from two silencedetect passes: a hard threshold for the in
    point (breath-proof) and a soft one for the out point (keeps word tails).
    Whisper times are only used to know WHICH words are in a block; they are
    off by up to 0.3s and are never used as cut points. Splitting on every
    >=0.25s silence also exposes restarts that Whisper merges into one sentence.
  * herk-edit-kit (Nate Herk, MIT): cut BETWEEN phrases, never inside one. A
    filler or stutter inside a phrase is flagged, not cut, because cutting it
    clips the words around it. Keep a short natural beat after a comma or a
    sentence end so the edit does not feel rushed. Re-transcribe the result
    and compare the words, because a clipped word can still look fine on paper.

Usage:
  # 1. plan: transcribe, map speech, propose decisions. Nothing is rendered.
  python3 reel-cut.py plan <raw.mp4> --outdir <dir> [--model small]

  # 2. review CUT-PLAN.md (the judgement step), then render and verify:
  python3 reel-cut.py apply --plan <dir>/cut-plan.json --out <dir>/clean.mp4 \\
      [--keep 4,9] [--cut 12] [--no-verify]

Outputs:
  words.json       Whisper words with timings (reused on re-runs)
  cut-plan.json    every speech block with KEEP/CUT, reason, confidence, flags
  CUT-PLAN.md      the same, readable. Read this before applying.
  clean.mp4        the cut video, one-pass frame-accurate render, stereo AAC
  cut-edl.json     kept source ranges (seconds and frames)
  CUT-VERIFY.md    re-transcription diff: words lost or added at the joins
"""

import argparse, difflib, json, math, re, subprocess, sys
from pathlib import Path

# ---------------------------------------------------------------- thresholds
# Locked -30/-38 dB first. A room that records hot fails these, and the
# rescue calibration then sets the thresholds from the noise floor.
MIN_SILENCE = 0.25
IN_DB, OUT_DB = -30, -38
IN_OFFSET, OUT_OFFSET, FLOOR_GUARD = 14, 22, 10

# A pause inside a block this long or longer is split out. silencedetect works
# on peak amplitude, so one click resets it and real pauses hide inside blocks
# ("So, Claude, so Claude" had 0.48s and 0.32s gaps and was one block). The
# 20ms RMS envelope does not have that blind spot.
MIN_PAUSE = 0.12
# Screen motion that counts as a demonstration (scroll, click, page change).
# Looping GIFs in a web page sit near the 97th percentile; real scrolls are far above.
DEMO_MIN = 15.0

# Natural beats kept after a block (seconds of the source's own room tone).
BEAT_COMMA = 0.10
BEAT_SENTENCE = 0.16
# A pause removed mid-sentence still keeps a word gap: Nate measured 0.04s
# median between words in tight reels. Zero sounds robotic.
BEAT_WORD = 0.05

FILLERS = {"um", "uh", "ah", "er", "erm", "hmm", "mm", "uhm", "umm"}
STOP = set("a an and are as at be but by for from i if in is it of on or so "
           "that this to was we with you your they their there what when where "
           "why how like just".split()) | FILLERS
# Emphasis that looks like a stutter but is meant ("never, never", "very very").
EMPHATIC = {"no", "never", "very", "really", "so", "go", "yeah", "yes", "bye", "ha"}
REDO = re.compile(r"\b(let me (redo|re-do|start|try) (that|again|over)|start (again|over)|"
                  r"one more time|take (two|three|2|3)|redo that|scratch that|"
                  r"(okay|ok),? (again|from the top))\b", re.I)

# Whisper drops disfluencies unless the prompt shows it they are wanted.
PROMPT = "Um, so, uh, I- I mean, like, you know, the the thing is, uh, okay."


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def tok(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


# ---------------------------------------------------------------- probing
def probe(path):
    d = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", str(path)]).stdout or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
    num, den = (v.get("r_frame_rate", "30/1").split("/") + ["1"])[:2]
    return {"duration": float(d.get("format", {}).get("duration", 0)),
            "fps": float(num) / float(den or 1),
            "width": v.get("width"), "height": v.get("height"),
            "channels": a.get("channels")}


# ---------------------------------------------------------------- transcript
def transcribe(path, outdir, model_name):
    out = outdir / "words.json"
    if out.exists():
        return json.load(open(out))
    wav = outdir / "cut-audio.wav"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "1",
         "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])
    import whisper
    model = whisper.load_model(model_name)
    res = model.transcribe(str(wav), word_timestamps=True, language="en",
                           fp16=False, initial_prompt=PROMPT)
    words = [{"w": w["word"].strip(), "s": round(w["start"], 3), "e": round(w["end"], 3)}
             for seg in res["segments"] for w in seg.get("words", []) if w["word"].strip()]
    json.dump(words, open(out, "w"), indent=1)
    wav.unlink(missing_ok=True)
    return words


# ---------------------------------------------------------------- speech map
def silences(path, db, d=MIN_SILENCE):
    err = run(["ffmpeg", "-nostdin", "-i", str(path), "-af",
               f"silencedetect=noise={db}dB:d={d}", "-f", "null", "-"]).stderr
    return ([float(m) for m in re.findall(r"silence_start: (-?[\d.]+)", err)],
            [float(m) for m in re.findall(r"silence_end: ([\d.]+)", err)])


def calibrate(path):
    """Thresholds anchored to the speaker's level (p90 of 0.1s RMS windows)."""
    err = run(["ffmpeg", "-nostdin", "-i", str(path), "-af",
               "aresample=48000,asetnsamples=n=4800,astats=metadata=1:reset=1,"
               "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
               "-f", "null", "-"]).stdout
    vals = sorted(float(m) for m in re.findall(r"RMS_level=(-?[\d.]+)", err)
                  if m not in ("-inf",))
    if len(vals) < 20:
        return IN_DB, OUT_DB
    speech, floor = vals[int(len(vals) * 0.90)], vals[int(len(vals) * 0.10)]
    out_db = max(speech - OUT_OFFSET, floor + FLOOR_GUARD)
    return round(max(speech - IN_OFFSET, out_db + 6)), round(out_db)


def invert(starts, ends, duration):
    blocks, cursor, quiet = [], 0.0, False
    for t, kind in sorted([(t, "s") for t in starts] + [(t, "e") for t in ends]):
        if kind == "s" and not quiet:
            if t - cursor > 0.05:
                blocks.append([max(0.0, cursor), t])
            quiet = True
        elif kind == "e":
            cursor, quiet = t, False
    if not quiet and duration - cursor > 0.05:
        blocks.append([cursor, duration])
    return blocks


def degenerate(blocks, duration):
    if not blocks:
        return True
    if sum(e - s for s, e in blocks) > 0.95 * duration:
        return True
    tiny = sum(1 for s, e in blocks if e - s < 0.4)
    return len(blocks) > 10 and tiny / len(blocks) > 0.7


def speech_map(path, duration):
    in_db, out_db, how = IN_DB, OUT_DB, "locked"
    blocks = invert(*silences(path, out_db), duration)
    if degenerate(blocks, duration):
        in_db, out_db = calibrate(path)
        how = "calibrated"
        blocks = invert(*silences(path, out_db), duration)
    onsets = sorted(silences(path, in_db)[1])  # hard-threshold silence_end = voice onset
    out = []
    for s, e in blocks:
        onset = next((o for o in onsets if s - 0.05 <= o <= e), s)
        out.append({"start": round(s, 4), "end": round(e, 4), "onset": round(max(onset, s), 4)})
    return out, {"in_db": in_db, "out_db": out_db, "how": how}


def attach_words(blocks, words):
    """Each word goes to exactly one block: the one holding its midpoint, else nearest."""
    for b in blocks:
        b["words"] = []
    for w in words:
        mid = (w["s"] + w["e"]) / 2
        best = min(blocks, key=lambda b: 0 if b["start"] <= mid <= b["end"]
                   else min(abs(mid - b["start"]), abs(mid - b["end"])))
        # Whisper times drift, so a word in a silent gap still belongs to its
        # nearest block; dropping it hides it from the retake detector.
        if best["start"] - 1.0 <= mid <= best["end"] + 1.0:
            best["words"].append(w)
    for i, b in enumerate(blocks):
        b["i"] = i
        b["text"] = " ".join(w["w"] for w in b["words"])
        b["gap_after"] = round(blocks[i + 1]["start"] - b["end"], 3) if i + 1 < len(blocks) else None
    return blocks


# Whisper's stock lines when it is fed noise or silence.
HALLUCINATIONS = {"thank you for watching", "thanks for watching", "thank you", "bye",
                  "you", "thanks", "okay", "please subscribe", "subscribe"}


def transcribe_blocks(path, blocks, outdir, model_name):
    """Transcribe every block from its own audio.

    One whole-file pass is not safe for deciding cuts: on a 6-minute take its
    timestamps drifted 20s and the entire spoken CTA was attached to the next
    block, leaving a loud 20s block that looked empty and would have been cut
    as "no speech". Per-block text cannot drift between blocks."""
    cache = outdir / "block-words.json"
    key = [[b["start"], b["end"]] for b in blocks]
    if cache.exists():
        c = json.load(open(cache))
        if c.get("key") == key:
            for b, ws in zip(blocks, c["words"]):
                b["words"] = ws
            return _relabel(blocks)
    import whisper
    model = whisper.load_model(model_name)
    audio = whisper.load_audio(str(path))
    sr = 16000
    for b in blocks:
        b["words"] = []
        if b["end"] - b["start"] < 0.3:
            continue
        s0 = max(0.0, b["start"] - 0.1)
        seg = audio[int(s0 * sr):int((b["end"] + 0.1) * sr)]
        res = model.transcribe(seg, word_timestamps=True, language="en", fp16=False,
                               initial_prompt=PROMPT, condition_on_previous_text=False)
        ws = [{"w": w["word"].strip(), "s": round(s0 + w["start"], 3), "e": round(s0 + w["end"], 3)}
              for sg in res["segments"] for w in sg.get("words", []) if w["word"].strip()]
        said = " ".join(tok(w["w"]) for w in ws).strip()
        echo = set(said.split()) <= {tok(x) for x in PROMPT.split()}
        if said in HALLUCINATIONS or (echo and len(said.split()) > 3):
            ws = []
        b["words"] = ws
    json.dump({"key": key, "words": [b["words"] for b in blocks]}, open(cache, "w"))
    return _relabel(blocks)


def split_sentences(blocks, env, thr):
    """Split a block at a sentence end that sits on a short dip in the waveform.

    Speakers restart lines without pausing long ("That's about it to the changes
    to the des- That's about it for changes to the desktop app"), so the pause
    split misses them. A sentence end is a real phrase boundary, so cutting at
    the quietest 20ms window between the two words (the reel-trim method) is
    still between phrases, as long as that window is near the pause level."""
    out = []
    for b in blocks:
        cur = dict(b, words=[])
        for k, w in enumerate(b["words"]):
            cur["words"].append(w)
            ends = w["w"].rstrip().rstrip(".").rstrip().endswith(("-", "?", "!")) or \
                w["w"].rstrip().endswith((".", "?", "!"))
            comma = w["w"].rstrip().endswith((",", ";", ":"))
            if not (ends or comma) or k == len(b["words"]) - 1:
                continue
            nxt = b["words"][k + 1]
            # The quietest 20ms between the two words. Speakers run sentences
            # together ("cool. So" never drops below -24 dB), so a sentence end
            # takes a dip up to 18 dB above the pause level; a comma needs a real pause.
            t, v = _span(env, w["e"] - 0.05, nxt["s"] + 0.05)
            if not v or min(v) >= thr + (18 if ends else 0):
                continue
            at = t[v.index(min(v))]
            if not cur["start"] < at < b["end"]:
                continue
            cur["end"] = round(at, 4)
            out.append(cur)
            cur = {"start": round(at + 0.02, 4), "end": b["end"], "onset": round(at + 0.02, 4),
                   "words": []}
        out.append(cur)
    for i, b in enumerate(out):
        b["i"] = i
        b["gap_after"] = round(out[i + 1]["start"] - b["end"], 3) if i + 1 < len(out) else None
    return _relabel(out)


def _relabel(blocks):
    for b in blocks:
        b["text"] = " ".join(w["w"] for w in b["words"])
    return blocks


def envelope(path):
    """20ms RMS envelope in dB: (times, values)."""
    out = run(["ffmpeg", "-nostdin", "-i", str(path), "-vn", "-af",
               "aresample=48000,asetnsamples=n=960,astats=metadata=1:reset=1,"
               "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
               "-f", "null", "-"]).stdout
    times = [float(x) for x in re.findall(r"pts_time:([\d.]+)", out)]
    vals = [float(x) if re.match(r"-?[\d.]+$", x) else -120.0
            for x in re.findall(r"RMS_level=(\S+)", out)]
    n = min(len(times), len(vals))
    return times[:n], vals[:n]


def _span(env, a, b):
    import bisect
    t, v = env
    i, j = bisect.bisect_left(t, a), bisect.bisect_right(t, b)
    return t[i:j], v[i:j]


def quiet_runs(env, a, b, thr, min_len):
    t, v = _span(env, a, b)
    runs, st = [], None
    for x, y in zip(t + [b], v + [999]):
        if y < thr and st is None:
            st = x
        elif y >= thr and st is not None:
            if x - st >= min_len:
                runs.append((st, x))
            st = None
    return runs


def quietest(env, a, b):
    t, v = _span(env, a, b)
    return t[v.index(min(v))] if v else a


def refine(blocks, env, thr):
    """Split blocks at every real pause, then pull each edge in to the words.

    Two problems this fixes on real footage: pauses that clicks hid from
    silencedetect stay inside a block, and a block can run 2s past its last
    word because mouse and keyboard noise sits above the threshold."""
    out = []
    for b in blocks:
        if not b["words"]:
            out.append(b)
            continue
        cuts = quiet_runs(env, b["start"], b["end"], thr, MIN_PAUSE)
        edges = [b["start"]] + [x for r in cuts for x in r] + [b["end"]]
        spans = [(edges[k], edges[k + 1]) for k in range(0, len(edges), 2)]
        parts = [{"start": s, "end": e, "words": []} for s, e in spans if e - s > 0.04]
        if not parts:
            out.append(b)
            continue
        for w in b["words"]:
            mid = (w["s"] + w["e"]) / 2
            best = min(parts, key=lambda p: 0 if p["start"] <= mid <= p["end"]
                       else min(abs(mid - p["start"]), abs(mid - p["end"])))
            best["words"].append(w)
        for p in parts:
            t, v = _span(env, p["start"], p["end"])
            p["onset"] = next((x for x, y in zip(t, v) if y >= thr + 6), p["start"])
            if p["words"]:
                first, last = p["words"][0]["s"], p["words"][-1]["e"]
                if p["end"] > last + 0.4:
                    p["end"] = quietest(env, last, last + 0.4) + 0.02
                if p["onset"] < first - 0.4:
                    p["onset"] = p["start"] = quietest(env, first - 0.4, first)
            p.update({k: round(p[k], 4) for k in ("start", "end", "onset")})
            out.append(p)
    for i, b in enumerate(out):
        b["i"] = i
        b["gap_after"] = round(out[i + 1]["start"] - b["end"], 3) if i + 1 < len(out) else None
    return _relabel(out)


def motion(path, crop):
    out = run(["ffmpeg", "-nostdin", "-i", str(path), "-an", "-vf",
               f"fps=10,crop={crop},scale=160:-1,format=gray,tblend=all_mode=difference,"
               "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
               "-f", "null", "-"]).stdout
    return [float(x) for x in re.findall(r"YAVG=([\d.]+)", out)]


def screen_events(path):
    """Find scrolls and clicks in a screen recording baked into the frame.

    The screen half is the one that is mostly still with big spikes; the
    face half moves a little all the time. No such half = no demo detection."""
    halves = {"top": motion(path, "iw:ih/2:0:0"), "bottom": motion(path, "iw:ih/2:0:ih/2")}
    pick, best = None, 0.0
    for name, m in halves.items():
        if len(m) < 50:
            continue
        srt = sorted(m)
        med, p99 = srt[len(m) // 2], srt[int(len(m) * 0.99)]
        if med < 0.5 and p99 >= 20 and p99 > best:
            pick, best = name, p99
    if pick is None:
        return None, []
    m = halves[pick]
    srt = sorted(m)
    thr = max(DEMO_MIN, 2 * srt[int(len(m) * 0.97)])
    events = []
    for k, x in enumerate(m):
        if x < thr:
            continue
        t = k / 10
        if events and t - events[-1][1] <= 0.6:
            events[-1][1] = t + 0.1
        else:
            events.append([t, t + 0.1])
    return pick, [tuple(e) for e in events]


def add_demos(blocks, events):
    """Keep the moments the speaker is showing something while not talking.

    Only inside a pause between two kept lines, never over any speech (a
    retake that is being cut can be playing while he scrolls)."""
    kept = sorted((b for b in blocks if b["decision"] == "KEEP"), key=lambda b: b["onset"])
    speech = [(b["onset"], b["end"]) for b in blocks if b["words"]]
    demos = []
    for p, n in zip(kept, kept[1:]):
        if n["onset"] - p["end"] < 0.5:
            continue
        for es, ee in events:
            s, e = max(es - 0.1, p["end"]), min(ee + 0.3, n["onset"])
            for a, b in speech:
                if a < e and b > s:          # overlaps speech: keep the side that is clear
                    if a - s >= e - b:
                        e = min(e, a)
                    else:
                        s = max(s, b)
            if e - s >= 0.2:
                demos.append((s, e))
    for s, e in demos:
        blocks.append({"i": len(blocks), "kind": "demo", "start": round(s, 4), "end": round(e, 4),
                       "onset": round(s, 4), "words": [], "text": "", "gap_after": None,
                       "decision": "KEEP", "reason": "screen changes while silent (scroll or click)",
                       "confidence": "medium", "flags": []})
    return blocks


# ---------------------------------------------------------------- decisions
def content(tokens):
    return [t for t in tokens if t and t not in STOP]


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a and b else 0.0


def is_prefix_restart(a, b):
    """Block a is an abandoned start of block b: b opens with a's words."""
    a, b = [t for t in a if t not in FILLERS], [t for t in b if t not in FILLERS]
    if not a or len(a) >= len(b):
        return False
    n = len(a)
    if n == 1 and a[0] in EMPHATIC:
        return False
    if n <= 4:
        # "So, Claude," then "so Claude shipped": the fragment comes back whole
        # within the first couple of words of the next line
        return any(b[o:o + n] == a for o in range(3 if n > 1 else 1))
    match = sum(1 for x, y in zip(a, b[:n]) if x == y)
    return match / n >= 0.6


def repeats_across_pauses(blocks):
    """Words said, a pause, then the same words again: "So, Claude, | so Claude
    shipped". Read the whole take as one word stream and look at every pause.
    If the whole blocks just before it are repeated right after it, they are
    the abandoned try. Only whole blocks are cut, so no cut lands mid-phrase."""
    stream = [(t, b["i"]) for b in blocks for t in (tok(w["w"]) for w in b["words"]) if t]
    cut = {}
    for p in range(1, len(stream)):
        if stream[p][1] == stream[p - 1][1]:
            continue                                  # not a block boundary
        # the retry may open with a connector the first try lacked ("So read through them")
        skip = 1 if stream[p][0] in STOP and p + 1 < len(stream) else 0
        for L in range(min(12, p, len(stream) - p - skip), 0, -1):
            if p - L > 0 and stream[p - L - 1][1] == stream[p - L][1]:
                continue                              # A must start at a boundary too
            a = [t for t, _ in stream[p - L:p]]
            if a != [t for t, _ in stream[p:p + L]] and \
                    (not skip or L < 3 or a != [t for t, _ in stream[p + 1:p + 1 + L]]):
                continue
            if L == 1 and (a[0] in EMPHATIC or a[0] in FILLERS):
                continue
            for _, bi in stream[p - L:p]:
                cut[bi] = " ".join(a)
            break
    return cut


def decide(blocks, lookahead=4, window=25.0):
    for b in blocks:
        b.update(decision="KEEP", reason="", confidence="", flags=[])
    for bi, words in repeats_across_pauses(blocks).items():
        blk = next(b for b in blocks if b["i"] == bi)
        blk.update(decision="CUT", reason=f"said again straight after the pause ('{words}')",
                   confidence="high")
    for i, b in enumerate(blocks):
        toks = [tok(w["w"]) for w in b["words"]]
        toks = [t for t in toks if t]
        if b["decision"] == "CUT":
            continue
        if not toks:
            b.update(decision="CUT", reason="no speech (breath, click or room noise)", confidence="high")
            continue
        if all(t in FILLERS for t in toks):
            b.update(decision="CUT", reason=f"filler with silence both sides ({b['text']})",
                     confidence="high")
            continue
        if REDO.search(b["text"]):
            b.update(decision="CUT", reason="direction to camera", confidence="high")
            continue
        complete = len(re.findall(r"[.?!]\s", b["text"]))  # finished sentences before the end
        if b["text"].rstrip(" .").endswith(("-", "\u2014")) and i + 1 < len(blocks):
            if complete == 0 and len(toks) <= 6:
                b.update(decision="CUT", reason="cut off mid-sentence, restarted after",
                         confidence="high")
                continue
            b["flags"].append("ends on a cut-off fragment with no pause to cut at")
        # 1-3 words alone between long silences: usually talking to someone off
        # camera. Gaps are measured to the nearest blocks that hold words, since
        # breath and click blocks sit in between. Never the first or last line.
        # A cluster of close blocks ("Any lunch | left? | Uh, sure.") counts as one.
        prev = next((o for o in reversed(blocks[:i]) if o["words"]), None)
        if prev is None or b["onset"] - prev["end"] >= 1.0:
            group, words_n = [b], len(toks)
            for o in blocks[i + 1:]:
                if not o["words"]:
                    continue
                if o["onset"] - group[-1]["end"] >= 0.75:
                    break
                group.append(o)
                words_n += len(o["words"])
            nxt = next((o for o in blocks[group[-1]["i"] + 1:] if o["words"]), None)
            if prev and nxt and words_n <= 5 and group[-1]["end"] - b["onset"] < 2.5 \
                    and group[-1]["text"].rstrip().endswith((".", "?", "!")) \
                    and nxt["onset"] - group[-1]["end"] >= 0.75:
                for g in group:
                    g.update(decision="CUT", reason="short isolated line, likely an "
                             "off-camera aside", confidence="medium")
                continue
        worded = [o for o in blocks[i + 1:] if o["words"] and o.get("kind") != "demo"]
        for o in worded[:lookahead]:
            j = o["i"]
            first = o is worded[0]
            if o["start"] - b["end"] > window:
                break
            otoks = [t for t in (tok(w["w"]) for w in o["words"]) if t]
            # an unfinished line whose words come back at the start of the next one
            t = b["text"].rstrip()
            if (t.endswith("...") or not t.endswith((".", "?", "!"))) and first:
                grams = {tuple(otoks[k:k + 3]) for k in range(min(len(otoks) - 2, 6))}
                tail = toks[-8:]
                hit = next((k for k in range(len(tail) - 2) if tuple(tail[k:k + 3]) in grams), None)
                if hit is not None:
                    # only the tail is the abandoned part; with real content
                    # before it and no dip to cut at, flag rather than lose it
                    if len(toks) - len(tail) + hit > 6:
                        b["flags"].append(f"tail restarts in block {j}, no pause to cut at")
                    else:
                        b.update(decision="CUT", reason=f"unfinished, restarted in block {j}",
                                 confidence="medium")
                        break
            # "Now it can open up in a separate session. | Open up in a separate
            # tab...": the next line opens with a run of this line's words
            if first and not re.search(r"[.?!]\s", b["text"]):
                hit = next((L for L in range(min(len(otoks), len(toks) - 1), 3, -1)
                            for k in range(1, len(toks) - L + 1) if toks[k:k + L] == otoks[:L]), None)
                if hit:
                    if len(toks) <= 12:
                        b.update(decision="CUT", reason=f"next line restarts with {hit} of its words",
                                 confidence="medium")
                        break
                    b["flags"].append(f"next line restarts with {hit} of its words, no pause to cut at")
            # same opening run of words, said again: the later one is the take
            run_len = next((k for k, (x, y) in enumerate(zip(toks, otoks)) if x != y),
                           min(len(toks), len(otoks)))
            if run_len >= 4 and first:
                b.update(decision="CUT", reason=f"retake, block {j} restarts with the same "
                         f"{run_len} words", confidence="medium")
                break
            if first and is_prefix_restart(toks, otoks):
                b.update(decision="CUT", reason=f"false start, restarted in block {j}",
                         confidence="high")
                break
            # "it can do parallel." then "It can run tasks in parallel sessions":
            # the same line said again, more fully
            ca, cb = content(toks), content(otoks)
            clause = [t for t in (tok(x) for x in re.split(r"[,;:]", b["text"])[-1].split()) if t]
            cc = content(clause)
            if first and len(clause) >= 3 and clause[:2] == otoks[:2] \
                    and len(clause) < len(otoks) and cc \
                    and len(set(cc) & set(cb)) / len(set(cc)) >= 0.5:
                if re.search(r"[.?!]\s", b["text"]):   # more than one sentence: cutting
                    b["flags"].append(f"last clause restated in block {j}, no pause to cut at")
                    continue                          # it all would lose the first one
                b.update(decision="CUT", reason=f"restated more fully in block {j}",
                         confidence="medium")
                break
            score = jaccard(ca, cb)
            same_open = toks[:3] == otoks[:3] and len(toks) >= 3 and len(ca) >= 3
            if min(len(set(ca)), len(set(cb))) < 2:
                score = 0.0                           # one shared word proves nothing
            if score >= 0.45 or (score >= 0.30 and same_open):
                b.update(decision="CUT", reason=f"retake, block {j} is the later take "
                         f"(overlap {score:.2f})",
                         confidence="high" if score >= 0.45 else "medium")
                break
            # A retake follows its first try. Once a different full line has been
            # said in between, a later similar line is new content, not a retake.
            if len(otoks) > 4 and score < 0.3:
                break
        # in-phrase problems are flagged only: cutting inside a phrase clips words
        for x, y in zip(toks, toks[1:]):
            if x == y and x not in EMPHATIC:
                b["flags"].append(f"stutter '{x} {y}' inside a phrase")
        inner = [t for t in toks if t in FILLERS]
        if inner and b["decision"] == "KEEP":
            b["flags"].append(f"filler inside a phrase ({', '.join(inner)})")
    # Short pieces stranded between two cut takes ("It can open up." "It can.")
    # are part of the same stumble.
    worded = [b for b in blocks if b["words"]]
    k = 0
    while k < len(worded):
        if worded[k]["decision"] != "KEEP" or k == 0 or worded[k - 1]["decision"] != "CUT":
            k += 1
            continue
        run_ = []
        m = k
        while m < len(worded) and worded[m]["decision"] == "KEEP" and len(worded[m]["words"]) <= 4:
            run_.append(worded[m])
            m += 1
        if run_ and m < len(worded) and worded[m]["decision"] == "CUT" and "aside" not in worded[m]["reason"]:
            for r in run_:
                r.update(decision="CUT", reason="stumble between two cut takes", confidence="medium")
        k = max(m, k + 1)
    return blocks


# ---------------------------------------------------------------- clips
def beat_after(b):
    t = b["text"].rstrip()
    if t.endswith((".", "?", "!")):
        return BEAT_SENTENCE
    if t.endswith((",", ":", ";")):
        return BEAT_COMMA
    return BEAT_WORD if t else 0.0


def clips_from(blocks, fps, duration):
    """Kept blocks -> frame ranges. In: hard onset, zero pad. Out: soft end, +1 frame,
    plus a natural beat taken from the gap that follows (never past the next onset)."""
    clips = []
    last = math.floor(duration * fps)
    kept = sorted((b for b in blocks if b["decision"] == "KEEP"), key=lambda b: b["onset"])
    for k, b in enumerate(kept):
        nxt = kept[k + 1] if k + 1 < len(kept) else None
        end = b["end"] + beat_after(b)
        if b["gap_after"] is not None:
            end = min(end, b["end"] + b["gap_after"])
        if nxt is not None:
            end = min(end, nxt["onset"])
        fi, fo = math.floor(b["onset"] * fps), min(math.ceil(end * fps) + 1, last)
        if clips and fi <= clips[-1]["out_frame"] + 1:
            clips[-1]["out_frame"] = max(clips[-1]["out_frame"], fo)
            clips[-1]["blocks"].append(b["i"])
            clips[-1]["text"] += " " + b["text"]
        else:
            clips.append({"in_frame": fi, "out_frame": fo, "blocks": [b["i"]], "text": b["text"]})
    return clips


# ---------------------------------------------------------------- render + verify
def render(src, clips, fps, out):
    parts = []
    for n, c in enumerate(clips):
        s, e = c["in_frame"] / fps, c["out_frame"] / fps
        parts.append(f"[0:v]trim=start={s:.4f}:end={e:.4f},setpts=PTS-STARTPTS[v{n}];"
                     f"[0:a]atrim=start={s:.4f}:end={e:.4f},asetpts=PTS-STARTPTS[a{n}];")
    fc = "".join(parts) + "".join(f"[v{n}][a{n}]" for n in range(len(clips))) + \
        f"concat=n={len(clips)}:v=1:a=1[outv][outa]"
    filt = Path(out).with_suffix(".filter.txt")
    filt.write_text(fc)
    # one pass, one re-encode: separately encoded segments drift lip sync
    r = run(["ffmpeg", "-nostdin", "-y", "-i", str(src), "-filter_complex_script", str(filt),
             "-map", "[outv]", "-map", "[outa]", "-c:v", "libx264", "-preset", "medium",
             "-crf", "16", "-r", f"{fps}", "-c:a", "aac", "-ac", "2", "-b:a", "256k",
             "-movflags", "+faststart", str(out)])
    if r.returncode != 0:
        sys.exit(r.stderr[-2000:])
    filt.unlink(missing_ok=True)


def verify(out, clips, fps, model_name, outdir):
    """Re-transcribe the cut and diff it against the words we meant to keep."""
    vdir = outdir / "_verify"
    vdir.mkdir(exist_ok=True)
    (vdir / "words.json").unlink(missing_ok=True)
    heard = transcribe(out, vdir, model_name)
    expect = [tok(w) for c in clips for w in c["text"].split()]
    got = [tok(w["w"]) for w in heard]
    expect, got = [t for t in expect if t], [t for t in got if t]
    # joins on the cut timeline, for locating problems
    joins, t = [], 0.0
    for c in clips[:-1]:
        t += (c["out_frame"] - c["in_frame"]) / fps
        joins.append(round(t, 2))
    lost, added = [], []
    sm = difflib.SequenceMatcher(a=expect, b=got, autojunk=False)
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op == "equal":
            continue
        at = heard[min(b1, len(heard) - 1)]["s"] if heard else 0.0
        near = min(joins, key=lambda j: abs(j - at)) if joins else None
        near_join = near is not None and abs(near - at) < 1.0
        if a2 > a1 and not set(expect[a1:a2]) <= FILLERS:
            lost.append((" ".join(expect[a1:a2]), " ".join(got[b1:b2]), at, near if near_join else None))
        elif b2 > b1 and a2 == a1 and not set(got[b1:b2]) <= FILLERS:
            added.append((" ".join(got[b1:b2]), at, near if near_join else None))
    ratio = sm.ratio()
    md = [f"# Cut verify\n", f"Word match: **{ratio:.1%}** ({len(got)} heard, {len(expect)} expected)\n",
          f"Joins: {len(joins)}\n"]
    at_join = [x for x in lost if x[3] is not None]
    md.append("## Words that differ AT a join (check these by ear)\n")
    md += [f"- {at:.2f}s (join {j}s): expected `{e}`, heard `{g or '—'}`" for e, g, at, j in at_join] or ["- none"]
    md.append("\n## Other differences (usually Whisper guessing differently)\n")
    other = [f"- {at:.2f}s: expected `{e}`, heard `{g or '—'}`" for e, g, at, j in lost if j is None]
    other += [f"- {at:.2f}s: heard extra `{g}`" for g, at, j in added]
    md += other or ["- none"]
    (outdir / "CUT-VERIFY.md").write_text("\n".join(md) + "\n")
    return ratio, at_join


# ---------------------------------------------------------------- commands
def write_plan_md(plan, path):
    bl = plan["blocks"]
    cut = [b for b in bl if b["decision"] == "CUT"]
    flagged = [b for b in bl if b["flags"]]
    raw, kept = plan["probe"]["duration"], plan["kept_seconds"]
    md = [f"# Cut plan: {Path(plan['source']).name}\n",
          f"- Raw {raw:.1f}s, clean {kept:.1f}s, removes {raw - kept:.1f}s "
          f"({(raw - kept) / raw:.0%})",
          f"- Thresholds: in {plan['thresholds']['in_db']} dB / out {plan['thresholds']['out_db']} dB "
          f"({plan['thresholds']['how']})",
          f"- {len(bl)} speech blocks, {len(cut)} cut, {len(flagged)} flagged\n",
          "Read every line. The detector cannot tell emphasis from a stutter, and it misses",
          "retakes that are worded differently. Override with `--keep i,j` / `--cut k`.\n",
          "| # | src | decision | text | reason / flags |", "|---|---|---|---|---|"]
    for b in sorted(bl, key=lambda b: b["onset"]):
        note = b["reason"] + ("; " if b["reason"] and b["flags"] else "") + "; ".join(b["flags"])
        conf = f" ({b['confidence']})" if b["confidence"] else ""
        txt = b["text"].replace("|", "/")[:90] or (f"[screen demo {b['end'] - b['onset']:.1f}s]"
                                                    if b.get("kind") == "demo" else "")
        md.append(f"| {b['i']} | {b['onset']:.2f} | {b['decision']}{conf} | {txt} | {note} |")
    Path(path).write_text("\n".join(md) + "\n")


def cmd_plan(a):
    src = Path(a.video).expanduser().resolve()
    outdir = Path(a.outdir).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)
    p = probe(src)
    print("[1/3] mapping speech on the waveform")
    blocks, th = speech_map(src, p["duration"])
    blocks = attach_words(blocks, [])
    print(f"[2/3] transcribing {len(blocks)} blocks one by one (whisper:{a.model})")
    blocks = transcribe_blocks(src, blocks, outdir, a.model)
    env = envelope(src)
    blocks = refine(blocks, env, th["out_db"])
    blocks = split_sentences(blocks, env, th["out_db"])
    n = sum(len(b["words"]) for b in blocks)
    if n < 20:
        sys.exit(f"only {n} words came back: bad audio or wrong file")
    blocks = decide(blocks)
    screen, events = (None, []) if a.no_demo else screen_events(src)
    blocks = add_demos(blocks, events)
    clips = clips_from(blocks, p["fps"], p["duration"])
    kept = sum(c["out_frame"] - c["in_frame"] for c in clips) / p["fps"]
    plan = {"source": str(src), "probe": p, "thresholds": th, "model": a.model,
            "screen": screen, "screen_events": events,
            "kept_seconds": round(kept, 2), "blocks": blocks}
    json.dump(plan, open(outdir / "cut-plan.json", "w"), indent=1)
    write_plan_md(plan, outdir / "CUT-PLAN.md")
    cut = [b for b in blocks if b["decision"] == "CUT"]
    print(f"[3/3] {len(blocks)} blocks, {len(cut)} proposed cuts, "
          f"{p['duration']:.1f}s -> {kept:.1f}s")
    print(f"  thresholds in {th['in_db']} / out {th['out_db']} dB ({th['how']})")
    print(f"  screen recording: {screen or 'none found'}, {len(events)} scroll/click events, "
          f"{sum(1 for b in blocks if b.get('kind') == 'demo')} demo moments kept")
    print(f"  read {outdir / 'CUT-PLAN.md'}")


def cmd_apply(a):
    plan_path = Path(a.plan).expanduser()
    plan = json.load(open(plan_path))
    ids = lambda s: {int(x) for x in s.split(",") if x.strip()} if s else set()
    keep, cut = ids(a.keep), ids(a.cut)
    # --set-in 99=244.92: start a block later, to drop a leading word at a dip
    # you measured on the loudness curve (never inside a word)
    for spec in filter(None, a.set_in.split(",")):
        bi, t = spec.split("=")
        b = next(x for x in plan["blocks"] if x["i"] == int(bi))
        b["onset"] = b["start"] = float(t)
        b["words"] = [w for w in b["words"] if (w["s"] + w["e"]) / 2 >= float(t)]
        b["text"] = " ".join(w["w"] for w in b["words"])
    for b in plan["blocks"]:
        if b["i"] in keep:
            b.update(decision="KEEP", reason="revived by review")
        if b["i"] in cut:
            b.update(decision="CUT", reason=b["reason"] or "cut by review", confidence="review")
    p = plan["probe"]
    clips = clips_from(plan["blocks"], p["fps"], p["duration"])
    plan["kept_seconds"] = round(sum(c["out_frame"] - c["in_frame"] for c in clips) / p["fps"], 2)
    json.dump(plan, open(plan_path, "w"), indent=1)
    write_plan_md(plan, plan_path.with_name("CUT-PLAN.md"))
    out = Path(a.out).expanduser()
    print(f"rendering {len(clips)} clips, {p['duration']:.1f}s -> {plan['kept_seconds']:.1f}s")
    render(plan["source"], clips, p["fps"], out)
    edl = {"source": plan["source"], "fps": p["fps"], "clips": [
        {**c, "src_in": round(c["in_frame"] / p["fps"], 4),
         "src_out": round(c["out_frame"] / p["fps"], 4)} for c in clips]}
    json.dump(edl, open(out.with_name("cut-edl.json"), "w"), indent=1)
    print(f"  {out}")
    if a.no_verify:
        return
    print("verifying: re-transcribing the cut")
    ratio, at_join = verify(out, clips, p["fps"], plan.get("model", "small"), out.parent)
    print(f"  word match {ratio:.1%}, {len(at_join)} difference(s) at joins "
          f"-> {out.parent / 'CUT-VERIFY.md'}")
    if at_join:
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("plan")
    p1.add_argument("video")
    p1.add_argument("--outdir", required=True)
    p1.add_argument("--model", default="small")
    p1.add_argument("--no-demo", action="store_true",
                    help="never keep silent screen moments (no screen in the frame)")
    p2 = sub.add_parser("apply")
    p2.add_argument("--plan", required=True)
    p2.add_argument("--out", required=True)
    p2.add_argument("--keep", default="")
    p2.add_argument("--cut", default="")
    p2.add_argument("--set-in", default="", help="ID=SECONDS[,ID=SECONDS]")
    p2.add_argument("--no-verify", action="store_true")
    a = ap.parse_args()
    cmd_plan(a) if a.cmd == "plan" else cmd_apply(a)


if __name__ == "__main__":
    main()
