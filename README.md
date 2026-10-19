# Reel Factory

**From the Vault. Built by Tom Lyons. https://vault.lyonsinternational.com**

Reel Factory is a Claude Code skill that takes one raw talking-head recording and produces the finished vertical cuts you would otherwise spend an evening assembling: a hook card that is fully opaque on the first frame, burned-in captions timed to the words that were actually spoken, motion-graphic cards carrying the numbers the video is arguing about, a separate platform-neutral cut that ends before any platform-specific call to action, a YouTube thumbnail, an Instagram cover frame with the hook on it, and per-platform copy that is scored against a hard threshold and rewritten for up to five rounds. Between each of those stages sits a gate that either passes or stops the run, including one that re-transcribes the rendered file to prove the neutral cut does not still say "comment TEARDOWN".

The skill ends at finished files on disk. Nothing in it can post on your behalf, because nothing in it can post at all.

## First, three questions

Before it touches the recording, the skill asks you three things, and everything after depends on the answers.

1. **What kind of video is this, and who is it for?** The subject type.
2. **Which card style?** The look of the motion graphics. See [Styles](#styles).
3. **Which caption style?** Phrase, pulse or cinematic. See [Caption styles](#caption-styles).

| subject | what it is | what changes |
|---|---|---|
| Tool | one thing that already shipped, shown on screen, usable today | the hook says what it does and what it costs; the cut is checked for the steps on screen and an honest limitation; the reviewers score whether your viewer can actually reach it today, already has the problem, can see it work in under a minute, and hears what it does badly |
| News | something real just happened, and why it matters to your viewer | the hook carries the outcome with its number; the cut is checked for the concrete case and the complicating fact; the reviewers score whether your viewer already cares, whether it bridges to their work, whether the claim fits in one sentence, whether it is fresh, and whether every number is sourced |
| Other | anything else | you describe it, and the skill uses the closer template or a type you add yourself |

Both types follow the same six beats: DECLARE (the claim, inside the first three seconds), ASSESS (who it touches), ISOLATE (the one exact thing), PROCESS (shown on screen), BUILD (the limitation or the complicating fact) and REVEAL (one action, over live footage). The skill starts from a finished recording, so use the beats to plan and record, and the skill uses them to check the cut, suggest cards for each beat, and write and score the copy. SKILL.md has the full beat table, both rubrics, and a short section on adding your own subject type.

## What you get out of it

For a single recording, the pipeline produces:

| file | what it is |
|---|---|
| `REPORT.md` | duration, resolution, mirror verdict, every platform-locking phrase spoken, and the neutral cut point with a confidence rating |
| `prep.json` | word-level transcript, caption lines clamped to end just before the next one starts, silent gaps, cut plan |
| `transcript.json`, `words.json` | raw Whisper output and a flat word list with timings |
| `audio.wav` | a 16 kHz mono copy of the source audio, the wav Whisper was handed, left on disk so you can hear what the model heard. It is a by-product rather than a cache, rewritten on every run, and it is a verbatim copy of what was said, so delete it when you are done |
| `clean.mp4`, `CUT-PLAN.md`, `CUT-VERIFY.md` | only for a raw take: the take with dead air, breath pauses, retakes, false starts and off-camera asides removed, the plan you review before it renders, and a re-transcription check of every join |
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

The first thing you tell your AI assistant is the three answers, along with the file:

> Make a reel from raw.mp4. It is a Tool video for small shop owners who feel behind on AI. Panel style, phrase captions. The card numbers are in results.csv.

If you leave any of the three out, the skill asks before it starts. The commands below are what it runs, for when you want to run a stage yourself.

```bash
SKILL=~/.claude/skills/video-reel-factory
WS=~/my-reels          # a working directory of your own, see INSTALL.md step 7
STYLE=clean            # card style: clean, panel, example-brand, or your own (--list-styles)
CAPS=phrase            # caption style: phrase, pulse, or none for pre-captioned footage

# Absolute, because step 4 changes directory and these are referenced after it.
RAW=$PWD/raw.mp4       # your recording, sitting in the directory you are standing in
PREP=$PWD/raw_prep     # where reel-prep.py writes, next to the recording
CARDS=$PWD/cards.json  # you write this one by hand in step 2

# 0. clean cut (raw takes only): remove pauses, retakes and asides, then prep clean.mp4
#    python3 $SKILL/scripts/reel-cut.py plan "$RAW" --outdir "$PWD/cut"
#    read cut/CUT-PLAN.md, then:
#    python3 $SKILL/scripts/reel-cut.py apply --plan cut/cut-plan.json --out "$PWD/cut/clean.mp4"
#    and set RAW=$PWD/cut/clean.mp4 before step 1 (SKILL.md Phase 0.5)

# 1. prep: transcribe, plan the cut, check for a mirrored source
python3 $SKILL/scripts/reel-prep.py "$RAW" --keywords TEARDOWN
less "$PREP/REPORT.md"           # read this before anything else

# 2. cards: write cards.json by hand, using $SKILL/examples/cards.example.json as the shape.
#    It must hold exactly one hook card, which is pinned to frame 0.
#    If the take repeats itself, run reel-trim.py here (SKILL.md Phase 2.5) and use
#    its trimmed prep, cards and source from this point on.

# 3. compose both variants from the one cards.json
python3 $SKILL/scripts/reel-compose.py --prep "$PREP/prep.json" --cards "$CARDS" \
  --project $WS/video-projects/drop --style $STYLE --captions $CAPS --gsap $WS/vendor/gsap.min.js
python3 $SKILL/scripts/reel-compose.py --prep "$PREP/prep.json" --cards "$CARDS" \
  --project $WS/video-projects/drop-neutral --cut 62.7 --style $STYLE --captions $CAPS \
  --gsap $WS/vendor/gsap.min.js

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
  [0] GATE 0          subject type and viewer, card style, caption style
       |
       v
  [0.5] CLEAN CUT     raw takes only: cut dead air, retakes, false starts and
       |              asides on the waveform, keep screen demos
       |--- GATE 0.5 -> read the kept lines, keep the second take, verify joins
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

## Styles

### What a style is

A style is one Python module in the skill's `scripts/` folder that decides how the cards look and move. It defines the page CSS, the HTML for each card type, and the GSAP animation for each, through four names the composer calls: `base_css()`, `captions(lines)`, `render_card(i, card)` and `REGISTRY`. Every style supports the same card types with the same fields, and every card is validated by the same shared code before a style draws it, so one `cards.json` renders in any style. You pick one with `--style`, and `reel-compose.py --list-styles` lists what is installed.

| style | what it looks like | use it when |
|---|---|---|
| `clean` (default) | white rounded cards with a soft shadow, one blue accent, the system font, a gentle rise-in | you want the graphics to read as calm and neutral, or the footage is busy and needs light cards to sit on it |
| `panel` | dark translucent glass panels with a rounded accent spine down the left edge, condensed capitals for headlines, monospaced labels, a slide-in from the left while the spine wipes down | you want a technical, high-contrast look, or the footage is bright and white cards would disappear into it |
| `example-brand` | `panel` with a violet palette and white text on the accent | you want your own colours: copy this file |

The cover and thumbnail templates in `assets/` take the same colours through four variables at the top of each file, with the values for each shipped style listed in a comment beside them.

### Make your own, easiest first

**1. Recolour.** Copy `scripts/reel_cards_example_brand.py` to `scripts/reel_cards_yourname.py`. Change the hex values in its `COLOURS` block: the accent, a lighter tint of it, a neutral second colour, the reference-line colour, the panel glass, the solid surface, and the colour of text that sits on the accent (white on a dark accent, near-black on a light one). Compose with `--style yourname`. There is nothing to register: any file named `reel_cards_<name>.py` in that folder is a style called `<name>`, with underscores read as dashes. Running the file directly prints `ok` for every colour it applied. Copy the same values into the cover and thumbnail templates.

**2. A new look.** Copy `reel_cards_panel.py` (dark) or `reel_cards.py` (light) to a new `reel_cards_<name>.py`. Keep the four interface names and every card type, then change the shapes, the type, the spacing and the motion. Keep colours in CSS variables, the way `panel` does, so a recolour of your new style is a ten line file. Compose the shipped `examples/cards.example.json` with it, lint it, and preview it on real footage before you use it on a real drop.

**3. Advanced extras.** Two things the private version has that do not ship here, described so your assistant can build them.

A screen-share panel is a composition that shows a screen recording inside a framed panel in the upper part of the frame, with the speaker still visible underneath, so a tutorial can show the screen and the face at once. The recording plays as its own layer at the bottom of the composition, the frame is drawn above it in the style's colours, and the cards and captions sit on top. The panel grows open at a set time and closes at another, and any card that would collide with it is hidden while it is up.

Explainer scenes are full-frame animated scenes that replace the talking head for a few seconds at the key beats, acting the idea out (two things racing, a meter filling, a door unlocking) rather than restating it as text. A recurring mascot character appears in every scene to point at the problem and react to the answer, and the speaker stays on screen in a small round face bubble in a corner, cut out of the original footage during the composite step. Between scenes the video returns to the normal talking head with cards. Each scene is hand-authored HTML, CSS and GSAP that follows the same render contract as the cards.

### Rules every style keeps

- The `hook` card is fully opaque on frame 0, with no entrance animation. It may only animate out.
- Text stays inside the Instagram content box, x 65 to 950 and y 269 to 1560. The hook is the one exception, allowed to sit at the top for the few seconds it is on screen.
- The caption band stays clear: every card ends at least 20px above it, and a caption is readable against whatever is behind it. The shipped styles size their lower cards to end by y=1420 above the band at y=1440, and the composer warns when a card's content grows it into the band.
- No card or caption covers the face, the mouth, the hands, or anything the speaker is showing. Check it on the preview of the real footage, card by card.
- State changes are paired `gsap.set()` and `tl.to()` calls, never `tl.call()`, with no `backdrop-filter` and nothing that reads the clock or a random number, so every frame renders the same however the renderer seeks.

### Have your assistant build one

Hand this README to your AI assistant along with your brand colours (and a screenshot of your brand if you have one), and ask it to make a style from them. Ask for a recolour first. It is the quickest to check, and you can move to a new look once the colours are right.

### Caption styles

| captions | what it looks like | how |
|---|---|---|
| Phrase (default) | a short line at a time near the bottom, with the spoken word highlighted in the style's accent | `--captions phrase` |
| Pulse | one word at a time in heavy white capitals with a black outline, centre frame, swapping hard with no fade | `--captions pulse` |
| Cinematic | phrase captions with one oversized hero word per sentence, placed in the empty space around the speaker, with the hero word partly behind them | built with a separate tool, below |

Pulse is fast and loud. Its words never overlap in time, because the composer forces word times into order and refuses to build if two would show at once. It sits across the lower card band, so give lower cards a `y` below the word, or move the captions while those cards are up, and check the preview.

Cinematic captions need a matte of the person so the hero word can sit behind them, so this skill does not draw them. Build them with the free Hyperframes `embedded-captions` skill: install it with `npx hyperframes skills update embedded-captions`, pick a column-flow identity such as `cream` or `editorial`, run its prepare script to build the matte and the safe zones, write the caption file (one hero word per sentence, chosen because it is a number, a place, a result or the stressed word, with filler dropped and one special treatment saved for the two or three biggest moments), preview, and render. Then use that rendered file as the source footage for the rest of this pipeline and compose with `--captions none`, so the normal caption layer is off while the hook and cards are still drawn.

Never mix two caption styles in one video. Whatever the style, the safe zone, the opaque hook on frame 0, and the caption proof read all still apply.

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
    reel-cut.py          clean-cut a raw take: dead air, retakes, false starts, asides
    reel-prep.py         transcribe, plan cuts, detect platform-locking speech
    reel_markers.py      the one list of platform-locking phrases, shared by prep and verify
    reel_cards.py        the `clean` card style, plus the validation and pulse captions every style shares
    reel_cards_panel.py  the `panel` card style
    reel_cards_example_brand.py   `panel` recoloured, the file to copy for your own colours
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

Personal styles and media. The private version has card styles, fonts and templates built around one person's brand and show, a screen-share panel, an explainer scene kit with a mascot, and a stock sound effect for the card sound. None of that ships. The `panel` style here is a generic rebuild of one of those looks on system fonts with a neutral palette, and the screen-share panel and explainer scenes are described under [Styles](#styles) for you to build yourself. The card sound script is here, and it uses an effect you supply, since the private one is a generated clip with no licence that clearly allows redistributing it.

What stayed is the part that was worth giving away: the order of operations, the named gates, and the reasons each gate exists. Cards get fact-checked before they are composed because a chart that contradicts its own label is worse than no chart. You look at a preview on the real footage before rendering because a preview costs seconds and a render costs minutes. The rendered file gets verified rather than trusted because an ffmpeg filter can silently no-op. The copy gets scored against a hard threshold because "good enough" drifts downward when nobody is measuring. And a person approves the whole drop, because the machine gates check the file and the reviewers check the copy, and neither of them can tell you the video is right.

## License

MIT. See [LICENSE](LICENSE).

Two third-party pieces this package tells you to fetch are not MIT and are not distributed here. GSAP ships under GreenSock's own licence, not MIT; its terms are linked from the header of the file you download and from https://gsap.com/standard-license, and you should read them before shipping GSAP inside a commercial project. `hyperframes` is HeyGen's, and INSTALL.md step 7 covers what it declares.

---

*Reel Factory is a free release from the Vault, built by Tom Lyons. More guides, skills and prompts, all free, at https://vault.lyonsinternational.com*
