# Reel Factory

**From the Vault. Built by Tom Lyons. https://vault.lyonsinternational.com**

Reel Factory is a Claude Code skill that takes one raw talking-head recording and produces the finished vertical cuts you would otherwise spend an evening assembling: a hook card that is fully opaque on the first frame, burned-in captions timed to the words that were actually spoken, motion-graphic cards carrying the numbers the video is arguing about, a separate platform-neutral cut that ends before any platform-specific call to action, a YouTube thumbnail, an Instagram cover frame with the hook on it, and per-platform copy that is scored against a hard threshold and rewritten for up to five rounds. Between each of those stages sits a gate that either passes or stops the run, including one that re-transcribes the rendered file to prove the neutral cut does not still say "comment TEARDOWN".

The skill ends at finished files on disk. Nothing in it can post on your behalf, because nothing in it can post at all.

## What you get out of it

For a single recording, the pipeline produces:

| file | what it is |
|---|---|
| `REPORT.md` | duration, resolution, mirror verdict, every platform-locking phrase spoken, and the neutral cut point with a confidence rating |
| `prep.json` | word-level transcript, caption lines clamped to end just before the next one starts, silent gaps, cut plan |
| `transcript.json`, `words.json` | raw Whisper output and a flat word list with timings |
| `audio.wav` | a 16 kHz mono copy of the source audio, the wav Whisper was handed, left on disk so you can hear what the model heard. It is a by-product rather than a cache, rewritten on every run, and it is a verbatim copy of what was said, so delete it when you are done |
| `prep_trim.json`, `cards_trim.json`, `trimmed.mov` | only when you cut filler: the prep and cards remapped to the trimmed timeline, and the trimmed source built from the command `reel-trim.py` prints |
| `<project>/index.html` | the Hyperframes composition: the frame-0 hook, captions and your motion-graphic cards, animated with GSAP |
| `preview/preview-<t>s.png`, `preview-sheet.png` | the composition on top of the real footage at the times you chose, before anything renders. `preview-0s.png` is what the frame-0 reviewer grades |
| `renders/overlay.mov` | the transparent overlay, rendered at 1080x1920 |
| `<name>.mp4` | the full cut, footage plus overlay, audio cleaned, loudness normalised to -14 LUFS and encoded as 48 kHz stereo AAC, with an optional sound on each card entrance |
| `<name>-neutral.mp4` | the same video cut before the platform-specific call to action, ending at the cut on live footage so it loops |
| verify report | pass or fail on each gate, per cut, as text or JSON |
| `thumbnail.jpg` | 1280x720 YouTube thumbnail built from a frame of the finished cut, with hook text |
| `cover-instagram.jpg` | 1080x1920 Instagram cover with the hook inside the grid-safe band |
| `cover-gridcrop.jpg` | the 4:5 centre crop Instagram will actually show in your profile grid, so you can check the hook survives it |
| platform copy | a caption per platform, scored on five dimensions, gated at 90, rewritten for up to five rounds and escalated to you if it still fails |

## What it actually takes to run

Someone has to record the video. The skill does no generation, no voice cloning and no avatar work. It starts from a file you made.

Someone has to approve the result. The last phase is a hard stop where you watch the cut for repetition, read the captions, look at the thumbnail and the grid crop, and check that every claim on a card traces to a real source. Whisper mishears names and technical terms constantly, and those mistakes end up on screen in your voice with your face under them.

You supply the card data. The numbers on the motion graphics cannot come from the footage, they come from whatever analysis or dataset sits behind the video, so you hand them over and the skill builds the cards.

Wall clock for a 60 second recording, once everything is installed: transcription runs for a couple of minutes on CPU, a preview frame takes a few seconds, the overlay render takes roughly a minute per 20 seconds of output, and the verify step re-transcribes the finished cut. Most of the remaining time is you looking at previews and candidate frames, which is the part the pipeline is deliberately built around rather than trying to automate.

Cost: nothing in the documented path bills per run. Whisper, ffmpeg, the Hyperframes render and the Playwright screenshots all execute on your own machine. Three things to know before you assume the whole thing is self-contained. `hyperframes snapshot` sends frames to Gemini for vision analysis whenever `GEMINI_API_KEY` or `GOOGLE_API_KEY` is set in your environment, which is a paid API call, so the skill always passes `--describe false` to keep it local. The `hyperframes` CLI is a third-party package from HeyGen with its own telemetry setting and its own remote `publish`, `cloud` and `lambda` subcommands, none of which this skill calls; INSTALL.md step 7 tells you how to read and change the telemetry setting. And the project config `reel-compose.py` writes carries three keys beyond the dimensions and duration: a `paths` block, a `$schema` URL, and a `registry` URL pointing at a branch of HeyGen's GitHub repository, so the CLI can reach out to that registry when a composition asks for a block from it. The compositions this skill generates do not use registry blocks.

On licences: `hyperframes` version 0.7.92, the version INSTALL.md pins, declares `"license": "Apache-2.0"` in its `package.json`. That was also true of the 0.7.66 and 0.7.107 copies checked alongside it. Older 0.6.x releases declared no licence field at all. Check the version you actually install rather than taking this README's word for it: `npx hyperframes@0.7.92 --version`, then read the `license` field of the copy npm put in your cache.

## Install

```bash
mkdir -p ~/.claude/skills && cp -R video-reel-factory ~/.claude/skills/
```

Then start a new Claude Code session. Full prerequisites and a check for each one are in [INSTALL.md](INSTALL.md).

## Quickstart

```bash
SKILL=~/.claude/skills/video-reel-factory
WS=~/my-reels          # a working directory of your own, see INSTALL.md step 7

# Absolute, because step 4 changes directory and these are referenced after it.
RAW=$PWD/raw.mp4       # your recording, sitting in the directory you are standing in
PREP=$PWD/raw_prep     # where reel-prep.py writes, next to the recording
CARDS=$PWD/cards.json  # you write this one by hand in step 2

# 1. prep: transcribe, plan the cut, check for a mirrored source
python3 $SKILL/scripts/reel-prep.py "$RAW" --keywords TEARDOWN
less "$PREP/REPORT.md"           # read this before anything else

# 2. cards: write cards.json by hand, using $SKILL/examples/cards.example.json as the shape.
#    It must hold exactly one hook card, which is pinned to frame 0.
#    If the take repeats itself, run reel-trim.py here (SKILL.md Phase 2.5) and use
#    its trimmed prep, cards and source from this point on.

# 3. compose both variants from the one cards.json
python3 $SKILL/scripts/reel-compose.py --prep "$PREP/prep.json" --cards "$CARDS" \
  --project $WS/video-projects/drop --gsap $WS/vendor/gsap.min.js
python3 $SKILL/scripts/reel-compose.py --prep "$PREP/prep.json" --cards "$CARDS" \
  --project $WS/video-projects/drop-neutral --cut 62.7 --gsap $WS/vendor/gsap.min.js

# 4. look before you render: lint, then preview on the real footage
cd $WS
npx hyperframes@0.7.92 lint video-projects/drop
python3 $SKILL/scripts/reel-preview.py --project $WS/video-projects/drop \
  --source "$RAW" --at 0,4,12,24,40 --outdir "$WS/preview"

# 5. render the transparent overlay (absolute output path)
npx hyperframes@0.7.92 render video-projects/drop --format=mov --fps=30 --quality=high \
  -o "$WS/video-projects/drop/renders/overlay.mov"

# 6. composite the overlay onto the footage, full length.
# The placeholder is deliberate, and ffmpeg will reject the command until you deal
# with it. Read the mirror verdict in REPORT.md: if the source is mirrored, replace
# the placeholder with hflip, and if it is not, delete the placeholder and the comma
# after it. A wrong flip is unrecoverable once it ships, so nothing here guesses.
ffmpeg -y -i "$RAW" -i "$WS/video-projects/drop/renders/overlay.mov" -filter_complex \
 "[0:v]<<<ADD hflip HERE ONLY IF THE PREP REPORT SAID FLIP>>>,fps=30,\
  scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[bg];\
  [bg][1:v]overlay=0:0:format=auto:shortest=1[v];\
  [0:a]highpass=f=90,afftdn=nr=10,acompressor=threshold=-18dB:ratio=3:attack=8:release=180,\
  loudnorm=I=-14:TP=-1.5:LRA=11[a]" \
 -map "[v]" -map "[a]" -c:v libx264 -preset medium -crf 19 -pix_fmt yuv420p -r 30 \
 -c:a aac -ar 48000 -ac 2 -b:a 192k -movflags +faststart drop.mp4

# For the neutral cut, repeat steps 4 and 5 against video-projects/drop-neutral,
# then run the command reel-compose.py --cut printed. It is this same recipe plus
# the trim and a short audio fade, with the flip already resolved from the prep
# report. Substitute three things into it: SRC becomes "$RAW", overlay.mov becomes
# "$WS/video-projects/drop-neutral/renders/overlay.mov", and OUT-neutral.mp4
# becomes drop-neutral.mp4 so step 7 finds it. If REPORT.md found no speech that
# locks the video to one platform, there is no neutral cut to build: skip the
# second compose in step 3 and verify the one file you have.

# Optional: a sound on every card entrance, from an effect you have the rights to.
# Write to a new name, then use that file in step 7.
#   python3 $SKILL/scripts/reel-sfx.py --video drop.mp4 --cards "$CARDS" \
#     --sfx whoosh.wav --out drop-sfx.mp4

# 7. verify the rendered files
python3 $SKILL/scripts/reel-verify.py drop.mp4 --profile instagram --keywords TEARDOWN
python3 $SKILL/scripts/reel-verify.py drop-neutral.mp4 --profile neutral \
  --keywords TEARDOWN --expect-duration 62.7
```

In practice you do not type most of this. You hand Claude Code the recording and the card data and say "make a reel from this recording", and the skill walks the chain and stops at each gate. The commands above are what it runs, and what to fall back to when you want to redo one stage by hand.

## The pipeline

```
  raw recording
       |
       v
  [1] PREP            whisper transcript, caption lines, silent gaps,
       |              platform-marker scan, neutral cut point, mirror check
       |
       |--- GATE A ---> low cut confidence, mirror unknown, or under 40 words
       |                 -> stop and ask the owner
       v
  [2] CARDS           you supply the data, the skill builds a frame-0 hook plus
       |              stat / table / bars / list / compare / quote / image
       |              graphics into cards.json
       |
       |--- GATE B ---> captions proofread, every number sourced, no overlaps,
       |                 chart labels match data, exactly one hook
       v
  [2.5] TRIM          optional: cut repeats, remapping source, captions, cards
       |              and the cut point together
       |--- GATE C ---> re-transcribe the trimmed audio against the captions
       v
  [3] COMPOSE         html + gsap composition, duration owned in one place
       |              lint (0 errors) -> PREVIEW ON THE REAL FOOTAGE
       |              -> frame-0 judge -> render overlay.mov -> composite
       |              -> optional card sound
       v
  [4] VERIFY          file valid, 48 kHz stereo audio, 9:16, duration matches
       |              spec, no blank frames, NO CTA LEAK (re-transcribes the render)
       |
       |--- any FAIL is a hard stop, fix and re-render
       v
  [5] THUMBNAIL       frame candidates from the finished cut, hook text,
       |              1280x720 thumbnail, 1080x1920 cover, 4:5 grid-crop check
       v
  [6] COPY            per-platform captions, scored by four reviewers on six
       |              dimensions, gated at 90, up to 5 rewrite rounds
       v
  [7] APPROVAL        the owner reads the captions, looks at the thumbnail and the
       |              grid crop, checks every claim, and says yes
       v
  finished files on disk. you post them.
```

## Prerequisites

Claude Code, python3, Node.js 18 or newer, ffmpeg and ffprobe, the OpenAI Whisper Python package, the `hyperframes` npm package run through npx, a vendored copy of GSAP, Playwright for the preview and thumbnail steps, optionally tesseract for the mirrored-source check, and optionally a short sound effect of your own for the card sound. Step by step setup with a verification command for each is in [INSTALL.md](INSTALL.md).

## Package layout

```
README.md              this file
INSTALL.md             prerequisites, with a check for each one
LICENSE                MIT
.gitignore
video-reel-factory/    the skill itself, this is the folder you copy
  SKILL.md
  scripts/
    reel-prep.py         transcribe, plan cuts, detect platform-locking speech
    reel_markers.py      the one list of platform-locking phrases, shared by prep and verify
    reel_cards.py        the motion-graphics card library
    reel-compose.py      assemble the composition from prep.json + cards.json
    reel-trim.py         cut filler, keeping source, captions, cards and cut point in step
    reel-preview.py      the composition on the real footage at chosen times, before rendering
    reel-sfx.py          optional sound on every card entrance, timed from cards.json
    reel-verify.py       deterministic gates on the rendered file
    reel-keywords.mjs    optional rotating CTA keyword picker
  references/
    hook-library.md      openers and rules for the frame-0 hook
  assets/
    reel-thumbnail-template.html
    reel-cover-template.html
    screenshot-thumb.mjs
  examples/
    cards.example.json
```

## What was removed from the private version, and why

This started as one person's internal skill and was wired into their business. The following came out.

Publishing. The private version ended by creating drafts through a social scheduling API and recording them in a database. All of it is gone, along with the posting script and the scheduler and the account resolution logic. The human approval gate that used to sit before publishing is now the final phase, and the skill hands you files instead of pushing them anywhere. That leaves you with one less integration to configure and no credential in this package that could post as you.

Business plumbing. Logging to a private database, a local review console, email and chat notifications, and a workflow that posted to one specific community. None of it means anything outside the account it was built for.

Identity. Handles, brand names, team names, channel names, and hardcoded paths into one person's repository. The comment-to-DM setup block that `reel-keywords.mjs --setup` prints was rewritten to name no particular vendor; it now says "ManyChat or similar" and describes the trigger rather than one product's menus. The skill refers to "the owner", meaning whoever the video belongs to.

Private performance data. The private version read a file of hook patterns that regenerates daily from one account's real metrics, and consulted a log of that account's social experiments. Those numbers describe one audience. The scoring loop is still here, the hook library keeps the general patterns without the numbers, and if you keep your own record of what works, the skill will read it.

Personal styles and media. The private version has extra card styles, fonts and templates built around one person's brand and show, and a stock sound effect for the card sound. None of it ships. The card sound script is here, and it uses an effect you supply, since the private one is a generated clip with no licence that clearly allows redistributing it.

What stayed is the part that was worth giving away: the order of operations, the named gates, and the reasons each gate exists. Cards get fact-checked before they are composed because a chart that contradicts its own label is worse than no chart. You look at a preview on the real footage before rendering because a preview costs seconds and a render costs minutes. The rendered file gets verified rather than trusted because an ffmpeg filter can silently no-op. The copy gets scored against a hard threshold because "good enough" drifts downward when nobody is measuring. And a person approves the whole drop, because the machine gates check the file and the reviewers check the copy, and neither of them can tell you the video is right.

## License

MIT. See [LICENSE](LICENSE).

Two third-party pieces this package tells you to fetch are not MIT and are not distributed here. GSAP ships under GreenSock's own licence, not MIT; its terms are linked from the header of the file you download and from https://gsap.com/standard-license, and you should read them before shipping GSAP inside a commercial project. `hyperframes` is HeyGen's, and INSTALL.md step 7 covers what it declares.

---

*Reel Factory is a free release from the Vault, built by Tom Lyons. More guides, skills and prompts, all free, at https://vault.lyonsinternational.com*
