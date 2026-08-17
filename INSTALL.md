# Install

Every step below has a check you can run. If a check fails, the pipeline will fail later at a worse moment, so fix it now.

## 1. Install the skill

Copy the `video-reel-factory` folder into your Claude Code skills directory. Create that directory first: on a fresh Claude Code install it does not exist yet, and `cp -R` into a missing destination copies the folder's contents rather than the folder, which lands the skill as `~/.claude/skills/SKILL.md` and breaks every `$SKILL/scripts/...` path.

```bash
mkdir -p ~/.claude/skills && cp -R video-reel-factory ~/.claude/skills/
```

Check:

```bash
ls ~/.claude/skills/video-reel-factory/SKILL.md \
   ~/.claude/skills/video-reel-factory/scripts \
   ~/.claude/skills/video-reel-factory/assets
```

The skill folder is self contained. Scripts, HTML templates and the example cards file all live inside it, and every command in `SKILL.md` refers to them through `~/.claude/skills/video-reel-factory/`. Nothing needs to be copied into a separate tools directory.

Start a new Claude Code session after copying so the skill is picked up.

## 2. Claude Code

The skill is a set of instructions for Claude Code. It has no standalone runner.

Check: `claude --version`

Install instructions live at https://claude.com/claude-code

## 3. python3

The pipeline scripts (`reel-prep.py`, `reel_markers.py`, `reel_cards.py`, `reel-compose.py`, `reel-verify.py`) use the Python standard library plus openai-whisper for transcription, covered in step 6. Nothing else. Python 3.8 or newer is enough.

Check: `python3 --version`

## 4. ffmpeg and ffprobe

Used constantly: probing the source, extracting audio, sampling frames, compositing the overlay onto the footage, resizing the thumbnail. Both binaries must be on your PATH.

Check:

```bash
ffmpeg -version | head -1
ffprobe -version | head -1
```

macOS: `brew install ffmpeg`. Debian or Ubuntu: `sudo apt install ffmpeg`. Windows: use WSL, or install a build that puts both binaries on PATH.

## 5. Node.js

Needed for `npx hyperframes`, for the screenshot script, and for the optional keyword picker. Node 18 or newer, because the scripts use top-level await and `node:` imports.

Check: `node --version`

## 6. Whisper (transcription)

`reel-prep.py` transcribes the source with word-level timestamps, and `reel-verify.py` re-transcribes the rendered file to prove no platform-specific speech survived the cut. Both do `import whisper` at the point of use, so the OpenAI Whisper Python package has to be installed.

```bash
pip3 install -U openai-whisper
```

This pulls in PyTorch, which is a large download. It runs entirely on your machine and costs nothing per transcription.

Check:

```bash
python3 -c "import whisper; whisper.load_model('small'); print('whisper ok')"
```

The first run of any model downloads its weights. Both scripts default to the `small` model, and they should stay matched, because the two halves of the CTA check are only comparable if they heard the same thing. The model choice is not cosmetic: on one test recording of "comment TEARDOWN below", `reel-verify.py` running `small` heard the keyword and `base` heard "comment down" and lost it. On the neutral cut that miss is a false pass on the one gate that matters, and on the Instagram cut it is a false failure. Pre-fetch the model with `python3 -c "import whisper; whisper.load_model('small')"` if you want the first real run to be fast.

`reel-prep.py` also leaves an `audio.wav` in its output directory, the 16 kHz mono wav it fed to Whisper. It is a by-product rather than a cache: nothing reads it back, and every run extracts it again and overwrites it. It is a verbatim copy of everything that was said, so delete it when the drop is finished.

## 7. Hyperframes

Hyperframes is HeyGen's HTML-to-video renderer. It turns the composition that `reel-compose.py` writes (an HTML page driven by GSAP) into a transparent MOV overlay, and it provides the `lint` and `snapshot` checks the skill leans on. It is published on npm as `hyperframes` and runs locally through headless Chrome.

Pin the version. A bare `npx hyperframes` resolves and executes whatever is newest on every single run, and it reads your raw footage. The commands in this skill are written against 0.7.92:

```bash
npx hyperframes@0.7.92 --version
npx hyperframes@0.7.92 doctor
```

`doctor` reports missing system dependencies, including the Chrome build it renders with. Follow whatever it asks for.

Drop the pin when you want to, deliberately, after reading that release's own notes. Nothing in the skill requires 0.7.92 beyond the flags it uses: `render --format=mov --fps --quality=high -o`, `snapshot --at --describe false`, `lint`, `doctor`.

**Telemetry.** The CLI collects anonymous usage telemetry and has a subcommand for it. Run this before your first render and decide:

```bash
npx hyperframes@0.7.92 telemetry status
```

On 0.7.92 with no prior configuration, that reports `Status: enabled`. It also prints how to turn it off, which at the time of writing is `hyperframes telemetry disable`, or the environment variables `HYPERFRAMES_NO_TELEMETRY=1` and `DO_NOT_TRACK=1`. Read what your own copy prints rather than trusting this paragraph.

While it is enabled, every command you run sends a `cli_command` event, and `render` additionally sends a `render_complete` or `render_error` event carrying the render's fps, quality, elapsed time and machine details such as GPU renderer and free memory. Both ride the same switch, so disabling telemetry stops both. Read that off your own copy the same way: in 0.7.92 the events are named in `dist/cli.js`.

**What leaves your machine.** Rendering, linting and snapshotting run locally. Three things do not follow that rule and are worth knowing about. `hyperframes snapshot` will send frames to Gemini for vision analysis if `GEMINI_API_KEY` or `GOOGLE_API_KEY` is set in your environment, which is a paid API call, so the skill always passes `--describe false`. The CLI has `publish`, `cloud` and `lambda` subcommands that upload to remote services, none of which this skill ever calls. And the project config `reel-compose.py` writes contains three keys beyond the width, height, fps and duration it owns: `paths`, a `$schema` URL, and a `registry` URL pointing at `raw.githubusercontent.com/heygen-com/hyperframes/main/registry`, an unpinned branch of HeyGen's GitHub repository, which the CLI can fetch from when a composition asks for a registry block. The compositions this skill generates do not use registry blocks, and the keys stay because they are what a Hyperframes project config is expected to carry.

**Licence.** The 0.7.92 package declares `"license": "Apache-2.0"` in its `package.json`. The same was true of the 0.7.66 and 0.7.107 copies checked alongside it. The older 0.6.x line declared no licence field at all, so if you read that somewhere it was about those releases. Read it off the copy you actually installed:

```bash
npx hyperframes@0.7.92 --version                 # populates the npm cache
find ~/.npm/_npx -path "*/hyperframes/package.json" -exec \
  python3 -c "import json,sys; p=json.load(open(sys.argv[1])); print(p['version'], p.get('license'))" {} \;
```

**Make a working directory.** "Workspace" in this skill means one directory of your own with a `video-projects/` folder inside it. That is this skill's convention, not a Hyperframes concept, and `hyperframes init` does not produce it: `init` scaffolds a single composition project (`hyperframes.json`, `index.html`, `package.json`, `meta.json`, `AGENTS.md`, `CLAUDE.md`) in the directory you name, which then sits at the root of your workspace where later commands may pick it up instead of the project you meant. Skip `init` and make the folders yourself:

```bash
mkdir -p ~/my-reels/video-projects ~/my-reels/vendor
```

Pass project paths under `video-projects/` to `reel-compose.py --project`, and run `npx hyperframes@0.7.92` commands from `~/my-reels`.

Check: `ls -d ~/my-reels/video-projects`

## 8. GSAP

The composition animates with GSAP, and the renderer loads it from the project's own `assets/gsap.min.js`. A CDN reference is not reliable inside headless Chrome at render time, so it has to be a local file. A missing GSAP renders a blank overlay rather than failing loudly, which is why this step gets a check.

Download one copy into the `vendor/` folder you made in step 7, and let `reel-compose.py --gsap` copy it into each project from there. Pin the exact version rather than the `gsap@3` range, so the file you verified is the file you keep getting, and pass `--fail` so a CDN error page cannot land on disk pretending to be a script:

```bash
curl --fail -L -o ~/my-reels/vendor/gsap.min.js \
  https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js
```

Verify it. That URL served this exact file when this document was written:

```bash
shasum -a 256 ~/my-reels/vendor/gsap.min.js
# 28033e449a31ebcc396e5be8b13b63152bf03094288fb5867034321927bce087
```

If your hash differs, do not shrug it off. Compare against the checksum GreenSock and the registry publish for that version before you use the file.

Then pass it on every compose:

```bash
python3 ~/.claude/skills/video-reel-factory/scripts/reel-compose.py \
  --prep <prep.json> --cards cards.json \
  --project ~/my-reels/video-projects/<name> \
  --gsap ~/my-reels/vendor/gsap.min.js
```

Without `--gsap`, `reel-compose.py` looks for a `gsap.min.js` in a sibling project inside the same workspace and copies that if it finds one, and prints a warning if it cannot.

Either way it only ever copies into a project that has no `assets/gsap.min.js` yet. Recomposing into an existing project leaves the copy already sitting there untouched, whatever you pass to `--gsap`, so after you update the vendored file delete the old one out of each project you want it refreshed in.

GSAP is not MIT. The file's own header reads "Copyright 2024, GreenSock. All rights reserved. Subject to the terms at https://gsap.com/standard-license", so read those terms before you ship GSAP inside a commercial project.

Check: `ls ~/my-reels/vendor/gsap.min.js` and, after a compose, `ls <project>/assets/gsap.min.js`

## 9. Playwright (thumbnail and cover step only)

`assets/screenshot-thumb.mjs` opens the thumbnail and cover HTML templates in headless Chromium and screenshots them at 2x. Nothing else in the pipeline uses it, so if you skip the thumbnail step you can skip this.

Install it where the script can find it. `screenshot-thumb.mjs` imports Playwright by name, and ESM resolves a bare import from the importing module's own directory upwards, never from the directory you happen to be standing in. So installing into your working directory does nothing for this script, and neither does a global install. Install inside the skill folder, or anywhere above it such as `$HOME`:

```bash
cd ~/.claude/skills/video-reel-factory && npm install playwright
npx playwright install chromium
```

If Playwright already lives somewhere else, point the script straight at it instead of reinstalling:

```bash
export PLAYWRIGHT_MODULE=/path/to/node_modules/playwright
```

Check by exercising the real path, because a check that passes where the actual script fails is worse than no check. First the script's own front door, then a genuine render:

```bash
node ~/.claude/skills/video-reel-factory/assets/screenshot-thumb.mjs --help

cd /tmp && printf '%s\n' \
  '<!doctype html><meta charset="utf-8">' \
  '<body style="margin:0;background:#0071e3;color:#fff;font:700 64px sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">' \
  'playwright ok</body>' > pw-check.html
node ~/.claude/skills/video-reel-factory/assets/screenshot-thumb.mjs \
  "$PWD/pw-check.html" "$PWD/pw-check.png" 640 360
```

The second command prints the path it wrote and leaves a 1280x720 PNG, twice the 640x360 viewport. If it prints an error about Playwright not being available, the install landed somewhere the script cannot resolve; if it prints an error about Chromium not launching, run `npx playwright install chromium`.

## 10. tesseract (optional)

`reel-prep.py` guesses whether the source is mirrored by OCRing a frame and its mirror image and comparing confidence. Selfie captures are usually mirrored, which makes any text in the room read backwards, and a wrong flip cannot be undone after the fact.

```bash
brew install tesseract      # macOS
sudo apt install tesseract-ocr
```

Check: `tesseract --version`

Without it, the prep report says the check did not run and you decide by looking at a frame. That is the same decision the skill asks you to make anyway when the check returns "cannot tell", so tesseract is a convenience rather than a requirement.

## Verify the whole set

```bash
python3 --version
node --version
ffmpeg -version | head -1
ffprobe -version | head -1
npx hyperframes@0.7.92 --version
python3 -c "import whisper; print('whisper ok')"
ls ~/my-reels/video-projects ~/my-reels/vendor/gsap.min.js
node ~/.claude/skills/video-reel-factory/assets/screenshot-thumb.mjs --help | head -1
tesseract --version | head -1     # optional
ls ~/.claude/skills/video-reel-factory/SKILL.md
```

That covers everything except the one check that has to actually run a browser. Do the two-command Playwright check from step 9 as well, since it is the only one that proves the screenshot step will work.

If every line prints, run the pipeline on a short test clip before you trust it with something you care about.
