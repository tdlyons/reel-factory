#!/usr/bin/env python3
"""
reel-preview.py: see any moment of a composed reel on the real footage, without
rendering it.

`hyperframes snapshot` shows the overlay on a white page, so it cannot tell you
whether a card lands on a face, whether a white caption sits on a white shirt,
or what frame 0 actually looks like to someone scrolling. This can. For each
requested time it copies the composition, puts the real video frame behind it,
seeks the composition's own timeline to that moment and screenshots the page.
It is the same page, fonts and timeline the renderer uses, so what comes out
matches the render at that moment, in a few seconds a frame instead of minutes.

Run it after composing and BEFORE `hyperframes render`, every time. Every defect
that is visible after a render was visible here first, and fixing it here costs
a recompose instead of a re-render.

Before taking any screenshot it syntax-checks the composition's inline script
with `node --check`. A card field that breaks the script makes every card and
caption vanish while the page still loads and looks plausible, which otherwise
reads as "the preview is not seeking" rather than "the composition is broken".

Requires:
  Python 3.8+ (standard library only)
  ffmpeg on PATH, to pull the source frame
  Node.js 18+ and Playwright, through ../assets/screenshot-thumb.mjs
  (INSTALL.md step 9 covers Playwright)

Example:
  python3 reel-preview.py --project ./video-projects/my-reel \\
      --source raw.mp4 --at 0,4.5,12,25 --outdir ./preview
"""

import argparse, json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

SHOT = Path(__file__).resolve().parent.parent / "assets" / "screenshot-thumb.mjs"
SKIP = {"index.html", "renders", "snapshots", "node_modules"}
SHEET_W, SHEET_H = 324, 576   # contact sheet tile, a 0.3x 1080x1920 frame


def require_tool(name, hint):
    if shutil.which(name) is None:
        sys.exit(f"error: '{name}' was not found on PATH.\n       {hint}")


def check_script(html):
    """node --check on the largest inline script. Returns None or the error text."""
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    if not scripts:
        return "the composition has no inline <script>, so there is no timeline to seek"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(max(scripts, key=len))
        path = fh.name
    try:
        r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        return None if r.returncode == 0 else (r.stderr.strip()[:1200] or "node --check failed")
    finally:
        Path(path).unlink(missing_ok=True)


def seek_snippet(t):
    """
    Pause every registered timeline and park it at t. Hyperframes compositions
    register on window.__timelines. Run once at parse time and again on load, so
    the frame is seeked whether or not anything loads late.
    """
    return (
        "<script>(function(){function seek(){var m=window.__timelines||{};"
        f"for(var k in m){{var tl=m[k];if(tl&&tl.pause){{tl.pause();tl.time({t},false);}}}}}}"
        "seek();window.addEventListener('load',function(){setTimeout(seek,50);});})();</script>\n")


def parse_times(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            t = float(part)
        except ValueError:
            sys.exit(f"error: --at value {part!r} is not a number of seconds")
        if t < 0:
            sys.exit(f"error: --at value {part!r} is negative")
        out.append(t)
    if not out:
        sys.exit("error: --at is empty")
    return out


def build_parser():
    ap = argparse.ArgumentParser(
        prog="reel-preview.py",
        description="Screenshot a composed reel at chosen times, on top of the real source "
                    "frame, before rendering it. Writes preview-<t>s.png per time and a "
                    "preview-sheet.png contact sheet.",
        epilog="example:\n"
               "  python3 reel-preview.py --project ./video-projects/my-reel \\\n"
               "      --source raw.mp4 --at 0,4.5,12,25 --outdir ./preview\n\n"
               "always include 0, one time inside every distinct shot layout, and one per card.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True,
                    help="the hyperframes project reel-compose.py wrote (holds index.html)")
    ap.add_argument("--source", required=True,
                    help="the video the overlay will sit on. If you trimmed with reel-trim.py, "
                         "this is the trimmed source, so the times line up")
    ap.add_argument("--at", required=True, help="comma-separated times in seconds")
    ap.add_argument("--outdir", required=True, help="where to write the PNGs")
    ap.add_argument("--hflip", action="store_true",
                    help="mirror the source frame, matching a composite that uses hflip")
    return ap


def main():
    a = build_parser().parse_args()
    require_tool("ffmpeg", "Install ffmpeg. macOS: brew install ffmpeg. Debian/Ubuntu: sudo apt install ffmpeg.")
    require_tool("node", "Install Node.js 18 or newer.")
    if not SHOT.exists():
        sys.exit(f"error: screenshot script not found at {SHOT}. It ships in the skill's assets/.")

    proj = Path(a.project).expanduser().resolve()
    index = proj / "index.html"
    if not index.exists():
        sys.exit(f"error: no composition at {index}. Run reel-compose.py first.")
    source = Path(a.source).expanduser().resolve()
    if not source.exists():
        sys.exit(f"error: source not found: {source}")
    times = parse_times(a.at)

    W, H, duration = 1080, 1920, None
    cfg = proj / "hyperframes.json"
    if cfg.exists():
        try:
            c = json.loads(cfg.read_text())
            W, H = int(c.get("width", W)), int(c.get("height", H))
            duration = float(c["duration"]) if "duration" in c else None
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    if duration is not None:
        late = [t for t in times if t >= duration]
        if late:
            sys.exit(f"error: {', '.join(f'{t:g}' for t in late)}s is past the end of the "
                     f"composition ({duration}s)")

    html = index.read_text()
    if "</body>" not in html:
        sys.exit(f"error: {index} has no </body>, so there is nowhere to inject the seek")
    err = check_script(html)
    if err:
        sys.exit("error: the composition's script does not parse, so every card and caption "
                 "would vanish.\n       Usually a text value in a numeric card field.\n\n" + err)

    out = Path(a.outdir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    vf = ["-vf", "hflip"] if a.hflip else []

    made = []
    for t in times:
        work = Path(tempfile.mkdtemp(prefix="reel-preview-"))
        try:
            # The composition's own assets (gsap, images, fonts) must sit beside the copy.
            for child in proj.iterdir():
                if child.name in SKIP or child.name.startswith("."):
                    continue
                if child.is_dir():
                    shutil.copytree(child, work / child.name)
                else:
                    shutil.copy2(child, work / child.name)

            bg = work / "preview-bg.png"
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-ss", str(t),
                                "-i", str(source), *vf, "-frames:v", "1", "-update", "1", str(bg)],
                               capture_output=True, text=True)
            if r.returncode != 0 or not bg.exists():
                sys.exit(f"error: could not pull a frame at {t}s from {source}\n{r.stderr.strip()}")

            # The real frame behind the overlay, scaled and cropped the way the
            # composite's scale+crop does, and the timeline parked at t.
            inject = ("<style>html,body{background:#000 url('preview-bg.png') center/cover "
                      "no-repeat !important}</style>\n" + seek_snippet(t))
            (work / "index.html").write_text(html.replace("</body>", inject + "</body>", 1))

            png = out / f"preview-{t:g}s.png"
            r = subprocess.run(["node", str(SHOT), str(work / "index.html"), str(png),
                                str(W), str(H)], capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"error: screenshot failed at {t}s\n{(r.stderr or r.stdout).strip()}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        made.append(png)
        print(f"  {png}")

    if len(made) > 1:
        sheet = out / "preview-sheet.png"
        inputs = []
        for p in made:
            inputs += ["-i", str(p)]
        n = len(made)
        fc = "".join(f"[{i}:v]scale={SHEET_W}:{SHEET_H}[s{i}];" for i in range(n))
        fc += "".join(f"[s{i}]" for i in range(n)) + f"hstack=inputs={n}"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", *inputs,
                            "-filter_complex", fc, "-frames:v", "1", "-update", "1", str(sheet)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            print(f"\n  contact sheet: {sheet}")
        else:
            print(f"  WARN: contact sheet failed: {r.stderr.strip()}")
    print("\n  Look at these before rendering: frame 0's hook, every card against the face,\n"
          "  every caption against what is behind it, and the safe zone on these pixels.")


if __name__ == "__main__":
    main()
