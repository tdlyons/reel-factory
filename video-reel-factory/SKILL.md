---
name: video-reel-factory
description: Turn one raw talking-head recording into finished vertical cuts with captions, motion-graphic cards, a YouTube thumbnail, an Instagram cover frame and per-platform copy, checked by deterministic gates. Use when someone hands over a video file and says "make a reel from this recording", "cut this for Instagram and LinkedIn", "add captions and graphics to this clip", "turn this recording into a short", or invokes /video-reel-factory. Produces finished files on disk and never publishes anything.
---

# Reel Factory

One recording in, platform-ready files out. A person records and approves. Everything between those two points happens here.

**Nothing in this skill publishes.** There is no draft creation, no scheduler, no posting API. The pipeline ends with finished files on disk and a summary of which gates passed. The person whose video it is posts it.

Throughout this skill, "ask the owner" means stop and ask the person whose video this is. Do not decide on their behalf and carry on.

---

## The chain

```
prep -> cards -> compose -> render -> composite -> VERIFY -> thumbnail + cover
      -> copy -> score -> OWNER APPROVES (cut, captions, cards, thumb, cover, copy) -> hand off files
```

Scripts live in this skill's own `scripts/` folder. Every command below assumes the skill is installed at `~/.claude/skills/video-reel-factory/`. Set a shell variable once and reuse it:

```bash
SKILL=~/.claude/skills/video-reel-factory
```

You also need a working directory holding a `video-projects/` folder and a `vendor/gsap.min.js`. That layout is this skill's own convention rather than anything Hyperframes defines, so make it by hand; `hyperframes init` scaffolds a single composition project instead and leaves it sitting where later commands may pick it up. INSTALL.md steps 7 and 8 cover both. Call the directory `$WS` below.

```bash
WS=~/my-reels     # contains video-projects/ and vendor/gsap.min.js
```

---

## Phase 1: Prep (mechanical, no decisions)

```bash
python3 $SKILL/scripts/reel-prep.py <video.mp4>
```

If the recording contains a spoken call to action keyword (the "comment WORD and I will send it" pattern), pass it so the cut planner knows where platform-specific speech starts:

```bash
python3 $SKILL/scripts/reel-prep.py <video.mp4> --keywords TEARDOWN
```

`--keywords` takes a comma separated list. `--model` selects the Whisper model (default `small`). `--outdir` overrides the output directory, which otherwise defaults to `<video>_prep` next to the source.

Outputs land in that directory: `transcript.json`, `words.json`, `prep.json`, `REPORT.md`, and `audio.wav`. That last one is a 16 kHz mono copy of the source audio, the wav Whisper was handed, left on disk rather than in a temporary directory so you can listen back to exactly what the model heard. It is a by-product and not a cache: every run extracts it again and overwrites it. It is a verbatim copy of everything the speaker said, so delete it once the drop is finished.

**Read `REPORT.md` before doing anything else.** It gives you the duration and resolution, the caption lines, every platform-locking phrase that was spoken, and the neutral cut point with a confidence rating.

**If `neutral_cut.needed` is false, there is only one cut.** No platform-specific speech was found, so the full take is already safe everywhere and there is nothing to trim. Build one composition, skip the `--cut` compose in Phase 3, and verify that one file. Do not build two cuts out of habit.

**Gate A. Stop and ask the owner if any of these are true:**

- `neutral_cut.confidence` is `low`. There was no silent gap before the call to action, so the cut will clip a word.
- The mirror check returns `suggest_flip: null`. It found no legible in-frame text and is refusing to guess. Pull a frame and look at it yourself: if text reads backwards the source is mirrored, and if not, it is not. A wrong flip is unrecoverable once it ships. `true` means the check is confident the source is mirrored, which is still worth a glance before you trust it. `false` means do not flip.
- Fewer than 40 words came back. That usually means bad audio or the wrong file, and everything downstream is built on the transcript.

The mirror check needs `tesseract` installed. Without it the check reports `checked: false` and you decide visually, which is the same work Gate A asks for anyway.

The phrases prep scans for live in `scripts/reel_markers.py`, and Phase 4's leak gate reads the same list from the same file, so a phrase added there is caught by both. Add to that file rather than to either script.

---

## Phase 2: Cards (this is where judgement lives)

The card data is never in the footage. It comes from whatever analysis, dataset or argument sits behind the video, so you have to supply it. Watch what the speaker actually claims and build cards that show those claims.

Card types are defined in `scripts/reel_cards.py`:

| type | use it for |
|---|---|
| `stat` | the one number the video is built around |
| `table` | scrolling rows, proof the data is real |
| `bars` | a distribution, with an optional reference rule |
| `list` | steps or rules, revealed in sequence |
| `compare` | A against B where the gap is the argument |
| `quote` | the sentence you want screenshotted |
| `endcard` | full-bleed close, neutral cut only |

Write one `cards.json` and use it for both cuts. See `examples/cards.example.json` for the shape. Every card needs an `at` time, and every card except `endcard` needs an `out` time. Time each card to land while the speaker is saying that thing, using the caption line timings in `prep.json` to find the moment.

The `endcard` is the exception that makes one file serve both runs. It has no `out`, so it fades in and stays, which is right at the close of the neutral cut and wrong anywhere else. `reel-compose.py` drops endcards from the full-length composition and prints a line saying it did. On the `--cut` run it overwrites the endcard's authored `at` with the cut point, since an endcard always opens on the cut, and prints a line when the two differed.

A card whose `out` runs past the cut is pulled back to 1.8 seconds before it, to clear the end card. If that clamped exit is less than half a second after the card's own `at`, the card is dropped rather than flashed on screen for a few frames or, at the extreme, left fading in and never leaving. The boundary is exact: on a cut at 20.0 seconds the clamp lands at 18.2, so a card at 17.70 is kept and the same card at 17.71 is dropped. A card whose `at` is at or after the cut is dropped too, since it would never appear. Every drop prints a NOTE naming the card and the reason, and none of them touches the full-length cut.

Numeric fields are validated before they reach the composition. `at`, `out`, `y`, `value`, `size`, `count_dur`, `colw`, `widths`, `height`, `note_at`, `bar_height`, `stagger`, `rule.at` and each `series[].value` have to be real numbers, because those go into CSS and into the animation timeline unescaped. So do the caption timings in `prep.json`: `caption_lines[].start`, `.end`, and each `words[].s` and `.e`. A string in any of them stops the run with the field named, before anything is written.

Required fields are checked the same way. A `quote` without `text`, a `bars` series entry without a `label`, a `table` whose `rows` is not a list: each stops the run naming the field rather than throwing from inside a render function.

On a `table`, only `widths[0]` is read, as the flex weight of the label column. Every other column is a fixed `colw` pixels and right aligned, so the rest of the `widths` list is validated and then ignored.

Cards default to one of two vertical bands: `stat` and `quote` sit at the top of the frame at y=150, and `table`, `bars`, `list` and `compare` sit in the lower third at y=1000. On a 1080x1920 vertical selfie a face can occupy roughly y=280 to y=1200, so the lower band starts inside that range and a tightly framed speaker can end up under a card. That is one of the things the Phase 3 snapshot is for. Override the vertical position per card with `y` when a card lands on the face.

**Gate B. Before composing, check every card:**

- Every number traces to a real source rather than one you inferred while writing the card.
- Quotation marks mean the audio actually contains those words. Whisper produces garbled and self-contradicting lines, and tidying one into something readable and then putting quote marks around it invents a quote the speaker never said. Paraphrase without quote marks, or quote the mess verbatim, or cut the card. A `quote` card is the thing most likely to get screenshotted and quoted back, so it is the worst place in the pipeline to smooth a transcript.
- `at` and `out` sit inside the video duration and do not overlap another card in the same screen zone.
- On a `bars` card with a reference rule, the rule's claim matches the data. If the bars visibly vary, do not write "flat". Write what is true. A caption that argues with its own chart is the fastest way to lose an audience that was about to believe you.

---

## Phase 3: Compose and render

The full take keeps the spoken call to action, which locks it to one platform. The neutral cut ends before that and closes on an end card, which makes it safe everywhere else.

**Check `neutral_cut.needed` in `prep.json` first.** When it is false there is no `cut_at` to pass, because nothing in the recording locks it to a platform. Run only the first command below, without `--cut`, and verify that one file with `--profile neutral`. That one file serves every platform. It also has no end card, since endcards render on the `--cut` variant only, so the piece ends on its last frame. When `needed` is true, run both commands.

```bash
# Full length, keeps the spoken CTA. Endcards are dropped from this one.
python3 $SKILL/scripts/reel-compose.py --prep <prep.json> --cards cards.json \
  --project $WS/video-projects/<name> --gsap $WS/vendor/gsap.min.js

# Neutral, cut before the CTA, closes on the endcard
python3 $SKILL/scripts/reel-compose.py --prep <prep.json> --cards cards.json \
  --project $WS/video-projects/<name>-neutral --cut <neutral_cut.cut_at> \
  --gsap $WS/vendor/gsap.min.js
```

`--cut` trims the composition and adds a 4.3 second end card tail, so the neutral composition runs `cut + 4.3` seconds. Remember that number, Phase 4 checks it.

`--gsap` points at the local GSAP build you vendored in INSTALL.md step 8. GSAP has to be a local file because headless Chrome will not reliably fetch a CDN at render time, and a missing GSAP renders a blank overlay rather than failing loudly. Without `--gsap` the composer looks for a copy in a sibling project in the same workspace and warns if it finds none.

`--fps` defaults to 30, and it only sets the composition's own frame rate. If you change it, change it in the two commands below as well: `hyperframes render --fps=`, and the `fps=` filter and the `-r` flag in the composite. The composite command `reel-compose.py --cut` prints already carries whatever you passed; the full-length one below is written for 30 and you edit it by hand.

`--caption-top` moves the caption band off its default vertical position, which you need when the bottom of the frame is occupied by a reaction overlay or burned-in UI.

Then, for each project:

```bash
cd $WS
npx hyperframes@0.7.92 lint video-projects/<name>                       # must be 0 errors
npx hyperframes@0.7.92 snapshot video-projects/<name> --at 3,12,24,40 --describe false
```

**Look at the contact sheet.** Snapshots catch what lint cannot: overlapping captions, a card covering the speaker's face, a chart whose label contradicts its own bars. Fix and re-snapshot before you render. A render takes minutes and a snapshot takes seconds.

`--describe false` keeps snapshot local. Without it, snapshot sends frames to Gemini for vision analysis whenever `GEMINI_API_KEY` or `GOOGLE_API_KEY` is set in the environment, which is a paid API call.

Render the alpha overlay. Budget roughly a minute per 20 seconds of output, so run it in the background:

```bash
npx hyperframes@0.7.92 render video-projects/<name> --format=mov --fps=30 --quality=high \
  -o "<ABSOLUTE path>/renders/overlay.mov"
```

`-o` resolves against the current working directory rather than the project, so always pass an absolute path.

Composite the overlay onto the footage. **For the neutral cut, run the command `reel-compose.py --cut` printed.** It is this same recipe plus the trim and the end card tail, and it already resolved the flip from the prep report, so do not retype it. For the full-length version:

```bash
ffmpeg -y -i <SRC> -i overlay.mov -filter_complex \
 "[0:v]<<<ADD hflip HERE ONLY IF THE PREP REPORT SAID FLIP>>>,fps=30,\
  scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[bg];\
  [bg][1:v]overlay=0:0:format=auto:shortest=1[v];\
  [0:a]highpass=f=90,afftdn=nr=10,acompressor=threshold=-18dB:ratio=3:attack=8:release=180,\
  loudnorm=I=-14:TP=-1.5:LRA=11[a]" \
 -map "[v]" -map "[a]" -c:v libx264 -preset medium -crf 19 -pix_fmt yuv420p -r 30 \
 -c:a aac -b:a 192k -movflags +faststart <OUT>.mp4
```

Deal with the placeholder before you run it, and ffmpeg will refuse the command until you do. Read the mirror verdict in `REPORT.md`: if the source is mirrored, replace the placeholder with `hflip`, and if it is not, delete the placeholder and the comma after it. Never default to flipping. A wrong flip is unrecoverable once it has shipped, which is why the detector refuses to guess and this command refuses too.

Every other filter here is load-bearing. The scale and crop are what make a source that is not already 1080x1920 pass the 9:16 gate, and the audio chain is what puts the file at -14 LUFS. Both cuts get all of it, or the two files do not match.

---

## Phase 4: VERIFY (the gate that matters)

Never skip this. It inspects the rendered file rather than your intent. A filter can silently no-op and leave you shipping 94 seconds of video that you believe is 67 seconds long, and the only way to know is to measure the output.

```bash
python3 $SKILL/scripts/reel-verify.py <neutral>.mp4 --profile neutral \
  --keywords TEARDOWN --expect-duration <cut + 4.3>

python3 $SKILL/scripts/reel-verify.py <full>.mp4 --profile instagram \
  --keywords TEARDOWN
```

Gates: file valid, 9:16 aspect, duration matches spec, no blank frames, and no CTA leak. The last one re-transcribes the render and asserts that no platform-specific speech survived the cut, using the shared list in `scripts/reel_markers.py` plus anything you passed to `--keywords`. The `instagram` profile inverts that check and asserts the keyword is actually audible. Both directions match on the collapsed form, because Whisper renders a shouted TEARDOWN as "tear down".

Pass `--keywords` on both runs. Under `neutral` it makes the drop's own keyword forbidden, which is the specific mistake this gate exists to catch, and without it only the built-in markers are checked. Under `instagram` it is what the run has to assert, so without it that gate has nothing to check and reports `SKIP` rather than a pass, and the summary line says so.

The blank-frame gate samples eight frames from 4% to 97% of the duration, so the end card is inside the window. It flags a frame that is one flat colour edge to edge, and a frame that is near enough to uniform to have no picture in it and is also blown to white or dead black. The two-part rule is deliberate. A full-bleed white end card is legitimately bright, measuring 225 to 232 mean luma, and a bare mean test failed six of ten real end cards, one of them by 0.02. The spread test is what actually catches a blank, including a card whose background painted but whose text never did, because that frame is uniform. The one shape neither test can see is a card that painted its background and some decoration but not its text: it measures the same as a legitimate sparse end card, and no threshold separates them. That one is caught by looking at the snapshot in Phase 3, which is the other reason not to skip it.

The frame gate and the CTA gate both refuse to report a clean pass when they could not take their measurement. If fewer than half the sampled frames decode, the frame gate FAILS. If some but not all decode, it reports `SKIP` with an INCOMPLETE note, and the summary says the run is not a clean pass. If the audio that decodes falls short of the container's stated duration by more than `--tolerance`, or if it is full length but Whisper heard almost nothing in it, the CTA gate FAILS. That is not pedantry: a render killed part way through keeps a valid moov atom, so it probes at full length while most of the file is missing, and an absence check reading an empty or truncated transcript would call it a clean cut.

`--tolerance` defaults to 0.6 seconds, and it governs both the duration check and how far the decoded audio may fall short of the container. `--model` defaults to `small` for the re-transcription, matching `reel-prep.py`. Keep them matched. On one test recording of "comment TEARDOWN below", `small` heard the keyword and `base` heard "comment down" and lost it, which on the neutral cut is a false PASS on the one check that matters and on the Instagram cut is a false FAIL. `--json` prints machine-readable results, including when the file itself is unreadable, and carries a `skipped` list. Exit code 0 means every gate that ran passed; read the summary line for whether they all ran in full.

**Any FAIL is a hard stop.** Fix it and re-render. Do not ship a failing cut and do not downgrade it to a caveat in your summary. A neutral cut that still says "comment TEARDOWN" is a public, permanent mistake on a platform where that instruction means nothing, and it is fully detectable before anyone sees it.

---

## Phase 5: Thumbnail and cover frame

Every drop ships both. YouTube wants a 1280x720 custom thumbnail. The Instagram cover frame is the first thing anyone sees in the grid.

**Work in a fresh, empty directory for each video.** Every command in this phase writes fixed filenames (`cand_*.png`, `thumbnail.html`, `thumb-bg.jpg`, `thumb-2x.png`, `thumbnail.jpg`, `cover.html`, `cover-bg.jpg`, `cover-2x.png`, `cover-instagram.jpg`, `cover-gridcrop.jpg`) into the current directory, and every ffmpeg call passes `-y`. Run this phase twice for two videos in one directory and the first video's thumbnail and cover are overwritten without a prompt.

**Step 1: pull frame candidates from the FINISHED cut**, not the source, so you can see what the cards and captions are doing at that moment:

```bash
for t in 4 11 19 27 35; do
  ffmpeg -v error -y -ss $t -i <final>.mp4 -frames:v 1 -update 1 cand_$t.png
done
```

Look at them. You want a face mid-expression with no caption line crossing it and no card covering it. Reject any frame where a caption word sits over the mouth.

**Step 2: build the YouTube thumbnail** from the template in this skill's `assets/`:

```bash
cp "$SKILL/assets/reel-thumbnail-template.html" thumbnail.html
cp cand_<chosen>.png thumb-bg.jpg      # MUST sit next to thumbnail.html
```

Yes, that copies a PNG to a `.jpg` name. The extension is cosmetic here: the template references `thumb-bg.jpg` by that exact filename, and Chromium reads the real format from the file's own bytes rather than its name. Keep the name.

Fill the four slots by editing the file: `%%KICKER%%`, `%%HEAD_LINE1%%`, `%%HEAD_HIGHLIGHT%%`, `%%BRAND%%`. The headline is 2 to 5 words that read at phone size. Do not paste the caption hook in and let it wrap.

```bash
node "$SKILL/assets/screenshot-thumb.mjs" "$PWD/thumbnail.html" "$PWD/thumb-2x.png"
ffmpeg -y -i thumb-2x.png -vf scale=1280:720 -q:v 2 thumbnail.jpg
```

The template never crops the 9:16 frame to 16:9. It blurs a copy of the frame for the background field and shows the frame intact in a panel, because a centre crop of a vertical frame throws away the whole composition.

**Step 3: build the Instagram cover, with the hook on it.**

A bare video frame is not a cover. In the grid, and in feed before play, the cover is the only thing carrying the promise, so it gets hook text the same way the YouTube thumbnail does.

```bash
cp "$SKILL/assets/reel-cover-template.html" cover.html
ffmpeg -v error -y -ss <t> -i <final>.mp4 -frames:v 1 -update 1 cover-bg.jpg
# fill %%KICKER%% %%HEAD_LINE1%% %%HEAD_HIGHLIGHT%% %%HANDLE%%, then:
node "$SKILL/assets/screenshot-thumb.mjs" "$PWD/cover.html" "$PWD/cover-2x.png" 1080 1920
ffmpeg -y -i cover-2x.png -vf scale=1080:1920 -q:v 2 cover-instagram.jpg
```

Instagram crops the cover to a centred 4:5 for the profile grid, which on a 1080x1920 image is `y=285..1635`. The template keeps the hook inside that band and above the reaction overlay, so it survives the crop. Check the crop before shipping:

```bash
ffmpeg -y -i cover-instagram.jpg -vf "crop=1080:1350:0:285" -q:v 2 cover-gridcrop.jpg
```

Look at `cover-gridcrop.jpg`. If the hook is cut off, move the text. Do not shrink it.

**Step 4: read `thumbnail.jpg` and look at it.** Headline legible at thumbnail size, nothing covering a face, panel not showing a half-drawn card mid-animation. Fix before moving on.

---

## Phase 6: Copy, with a scoring loop

Write captions per platform. The platform that got the full cut gets the spoken keyword in the caption too. The platforms on the neutral cut point at the first comment instead, since a link in the body suppresses reach on most of them.

Then score the copy before you hand it over. Run three independent reviewers over it, gate every dimension at **90**, and rewrite and rescore for up to **5 rounds**:

| dimension | fails if |
|---|---|
| accuracy | any number contradicts the source data or the video, or anything in quotation marks is not what the audio actually says |
| hook | the first line does not stop a scroll on its own |
| platform fit | Instagram caption over 2200 characters, a link in a LinkedIn body, a missing YouTube title |
| voice | LLM tics such as the "not X, it's Y" reframe, "worth naming", mic-drop closing lines |
| CTA clarity | the ask is ambiguous or absent |

Use the Agent tool for the reviewers, one per perspective, and rewrite between rounds. If a dimension still fails after 5 rounds, hand it to the owner with the failing note attached rather than quietly shipping it at 84.

If the owner keeps a record of which hooks have worked on their account, read it and trust it over your instincts about what a good hook looks like.

---

## Phase 7: The owner approves, then posts (hard stop)

The machine gates check the file. The reviewers check the copy. Neither can tell you the video is right. Send everything and **stop**.

Files to hand over:

```
<final>.mp4                 (each cut)
thumbnail.jpg
cover-instagram.jpg
cover-gridcrop.jpg
```

Ask for an answer on each of these:

1. **The cut.** Pacing, where it starts, where it ends.
2. **The captions.** Wording and placement. Whisper mishears names, brands and technical terms constantly, and every caption line is on screen in the speaker's voice with their face under it. They read the captions before those ship, not after.
3. **The cards.** The claims on screen are the ones that get screenshotted and quoted back.
4. **The thumbnail and the cover.** Frame choice and hook text on both. Send the grid crop alongside the cover. The cover is the last asset anyone remembers to look at and the first one an audience sees.
5. **The copy.** Paste every platform caption into the message. Do not make someone open a file to find out what they are approving.
6. **Anything you decided for them.** A flip call, a cut point, a platform you dropped, a scoring dimension that never reached 90.

If a caption word is wrong, fix `caption_lines` in `prep.json` and re-render. Do not correct a misheard word in the platform copy only and leave it wrong on screen.

Then tell the owner plainly what exists on disk, which gates passed, and what you decided on their behalf. Posting is theirs. This skill has no ability to post and should not acquire one.

---

## Optional: rotating CTA keywords

If the owner runs a comment-to-DM automation, a single permanent keyword makes every video look like it points at the same asset. A pool fixes that while still resolving to one destination, and it gives rough attribution, since a comment saying LEDGER came from the video that used LEDGER.

```bash
node $SKILL/scripts/reel-keywords.mjs --peek     # show the next pick, record nothing
node $SKILL/scripts/reel-keywords.mjs --list     # the pool with usage history
node $SKILL/scripts/reel-keywords.mjs --setup \
  --destination https://example.com/the-thing --label "the pinned comment"
node $SKILL/scripts/reel-keywords.mjs \
  --destination https://example.com/the-thing    # pick one and record it as used
```

`--setup` prints the one-time automation setup block: the trigger to create, the full keyword list to paste into it, and the single reply every keyword should send. Two of the four modes print the destination, `--setup` in that reply and the default pick in its JSON, so pass `--destination` on both. Without it the output carries a placeholder string instead of a URL and nobody downstream can tell what it was meant to be. `--peek` prints only the keyword and `--list` only the usage table, so neither needs it. `--label` is the human name for that destination and only affects the `--setup` prose. `--pool <file>` replaces the built-in 20 keywords with your own, as either a JSON array of strings or one keyword per line.

Pick the keyword with `--peek` before recording, because it has to match what was actually said on camera. Record it as spent only after the video is approved and posted.

**This is the one part of the pipeline that writes outside the working directory.** The usage ledger lives at `$XDG_STATE_HOME/reel-factory/keywords.json`, falling back to `~/.local/state/reel-factory/keywords.json`, and it is created on first write along with its parent directories. Override the location with `--ledger <path>` or the `REEL_KEYWORDS_LEDGER` environment variable. `--peek`, `--list` and `--setup` write nothing. Least recently used wins, so the pool cycles fully before any word repeats.

`--destination`, `--label` and `--pool` also read `REEL_KEYWORDS_DESTINATION`, `REEL_KEYWORDS_LABEL` and `REEL_KEYWORDS_POOL` from the environment.

---

## Standing facts

- The card data never comes from the footage. If you cannot source a number, do not put it on screen.
- A snapshot is seconds and a render is minutes. Look before you render, every time.
- A rendered video sitting on disk costs nothing. A wrong file already posted costs cleanup on every platform it reached.

---

*Part of the Reel Factory release from DATT AI Campus. Built by Tom Lyons.*
