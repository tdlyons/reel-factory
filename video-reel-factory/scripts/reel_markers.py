#!/usr/bin/env python3
"""
reel_markers.py: the one list of speech that pins a cut to a single platform.

This file exists so that the scan in reel-prep.py and the gate in reel-verify.py
can never drift apart. They used to keep separate lists, and the verify list was
the shorter of the two, which meant the CTA-leak gate quietly passed cuts that
prep had already flagged. Anything added here is seen by both.

PLATFORM_MARKERS  what prep scans for when it plans the neutral cut point.
NEUTRAL_FORBIDDEN what verify refuses to hear in a rendered neutral cut. It is a
                  superset of PLATFORM_MARKERS, enforced by a check below, so the
                  gate can only ever be stricter than the scan.

Custom `--keywords` are not patterns and do not live in either list. They are
matched by collapsed form through find_keyword_spans (prep, word level) and
find_keyword_hits (verify, text level), both built on collapse() below, so the
two sides cannot disagree about whether a keyword was spoken.

Patterns are matched case-insensitively against a lowercased transcript, so
write them lowercase.

Requires: Python 3.8+ (standard library only).
"""

import re

# Phrases that pin a cut to one platform. If the speaker says any of these,
# everything from that point on belongs to that platform only, and the neutral
# cut has to end before it.
PLATFORM_MARKERS = [
    # "comment, tear down": Whisper attaches the comma to the word, so the
    # separator has to tolerate punctuation or the most important marker is missed.
    (r"\bcomment[,:.]?\s+[\"“']?\w+", "comment-keyword CTA"),
    (r"\binstagram\b", "names Instagram"),
    (r"\breel\b", "names 'reel'"),
    (r"\btiktok\b", "names TikTok"),
    (r"\blink in (the )?bio\b", "link-in-bio CTA"),
    (r"\bcheck the comments?\b|\bin the comments?\b", "link-in-comments CTA"),
    (r"\bdm me\b|\bdms?\b", "DM CTA"),
    (r"\bsubscribe\b", "YouTube-specific CTA"),
]

# Speech that is only ever a problem in a cut meant to serve every platform.
# Add here rather than to PLATFORM_MARKERS when a phrase should fail the gate
# without also moving the planned cut point.
NEUTRAL_EXTRA = []

NEUTRAL_FORBIDDEN = list(PLATFORM_MARKERS) + list(NEUTRAL_EXTRA)

# The gate must never be narrower than the scan. This is the bug that made the
# shared module necessary, so it is checked at import time rather than trusted.
# A real exception rather than an assert, because python3 -O strips asserts and
# this check has to survive that.
if not set(p for p, _ in PLATFORM_MARKERS) <= set(p for p, _ in NEUTRAL_FORBIDDEN):
    raise RuntimeError("NEUTRAL_FORBIDDEN must contain every pattern in PLATFORM_MARKERS")


def collapse(s):
    """
    Reduce text to bare lowercase letters.

    Whisper renders a shouted coined keyword as ordinary words, so TEARDOWN
    comes back as "tear down" and a literal token match misses it. Both the
    presence check and the absence check compare collapsed forms.
    """
    return re.sub(r"[^a-z]", "", str(s).lower())


def find_keyword_hits(text, keywords):
    """
    Which of `keywords` are audible in `text`, comparing collapsed forms.
    Returns the keywords as the caller spelled them.

    The text-level half of the pair. find_keyword_spans is the word-level half
    and applies the same collapsed-form rule, so a keyword one of them sees is a
    keyword the other sees.
    """
    flat = collapse(text)
    return [k for k in keywords if collapse(k) and collapse(k) in flat]


def find_keyword_spans(words, keywords):
    """
    Where in a word-level transcript each of `keywords` was spoken.

    Prep needs a word index, not just a yes or no, because a keyword hit moves
    the neutral cut point. It also has to match the way verify matches, on the
    collapsed form: prep used to match the literal token `\\bteardown\\b` while
    verify matched the collapsed form, so on a recording where Whisper wrote
    "tear down" prep planned no cut and verify then hard-failed with no cut point
    to fall back on. One implementation, one answer.

    `words` is reel-prep.py's list of {"word", "start", "end"}. Returns one hit
    per occurrence: {"keyword", "word_index", "end_index"}, where the indices are
    the first and last word the collapsed keyword spans.
    """
    hits = []
    if not keywords or not words:
        return hits
    # Collapse the whole transcript, remembering which word each surviving
    # character came from, so a match maps straight back to a word index.
    chars, owner = [], []
    for i, w in enumerate(words):
        for ch in collapse(w.get("word", "")):
            chars.append(ch)
            owner.append(i)
    flat = "".join(chars)
    for k in keywords:
        ck = collapse(k)
        if not ck:
            continue
        pos = flat.find(ck)
        while pos >= 0:
            hits.append({"keyword": k, "word_index": owner[pos],
                         "end_index": owner[pos + len(ck) - 1]})
            pos = flat.find(ck, pos + len(ck))
    hits.sort(key=lambda h: h["word_index"])
    return hits
