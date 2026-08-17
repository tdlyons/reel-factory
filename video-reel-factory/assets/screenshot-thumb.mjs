#!/usr/bin/env node
/**
 * screenshot-thumb.mjs: render a thumbnail or cover HTML file to PNG at 2x (retina).
 *
 * Requires: Node 18+ and Playwright with its Chromium browser.
 *   npm install playwright && npx playwright install chromium
 *
 * Install Playwright inside ~/.claude/skills/video-reel-factory/ or in $HOME, not
 * in the directory you happen to be running from. This file does a bare import,
 * and ESM resolves that from THIS file's location upwards, never from the current
 * working directory. PLAYWRIGHT_MODULE overrides the whole question.
 *
 * Example:
 *   node screenshot-thumb.mjs thumbnail.html thumb-2x.png            # 1280x720 YouTube thumbnail
 *   node screenshot-thumb.mjs cover.html cover-2x.png 1080 1920      # 9:16 reel cover
 *
 * Notes learned the hard way:
 *  - The background image (thumb-bg.jpg / cover-bg.jpg) must sit next to the HTML
 *    file, because the templates reference it relatively.
 *  - Playwright ships as CommonJS, so the chromium export is read defensively below.
 *  - ESM ignores NODE_PATH, and a bare import resolves from this file's directory
 *    upwards rather than from the current working directory. Installing Playwright
 *    into the folder you run the pipeline from does nothing for this script. Put it
 *    in the skill folder, or set PLAYWRIGHT_MODULE to the installation's directory.
 */

import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { existsSync, statSync } from "node:fs";

const USAGE = `usage: node screenshot-thumb.mjs <html> <out.png> [width] [height]

  <html>     path to the HTML file to render
  <out.png>  where to write the PNG (rendered at deviceScaleFactor 2)
  [width]    viewport width in CSS pixels (default: 1280)
  [height]   viewport height in CSS pixels (default: 720)

Pass 1080 1920 for a vertical reel cover. Requires Playwright, installed where this
script can resolve it (its own skill folder, or $HOME):
  cd ~/.claude/skills/video-reel-factory && npm install playwright
  npx playwright install chromium

If Playwright lives somewhere else, point PLAYWRIGHT_MODULE at that installation:
  PLAYWRIGHT_MODULE=/path/to/node_modules/playwright node screenshot-thumb.mjs ...`;

const args = process.argv.slice(2);
if (args.includes("--help") || args.includes("-h")) {
  console.log(USAGE);
  process.exit(0);
}

const htmlPath = args[0];
const outPath = args[1];
const width = Number(args[2] || 1280);
const height = Number(args[3] || 720);

if (!htmlPath || !outPath) {
  console.error(USAGE);
  process.exit(1);
}
if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
  console.error("error: width and height must be positive numbers.\n\n" + USAGE);
  process.exit(1);
}

const htmlAbs = resolve(htmlPath);
if (!existsSync(htmlAbs)) {
  console.error(`error: HTML file not found: ${htmlAbs}`);
  process.exit(1);
}

// Resolution order: PLAYWRIGHT_MODULE if set, then a normal package import.
// ESM ignores NODE_PATH, so a global install needs either `npm link playwright`
// or PLAYWRIGHT_MODULE pointing at it. Nothing here hardcodes an install path.
async function loadPlaywright() {
  const override = process.env.PLAYWRIGHT_MODULE;
  if (override) {
    let target = resolve(override);
    if (existsSync(target) && statSync(target).isDirectory()) target = resolve(target, "index.js");
    return import(pathToFileURL(target).href);
  }
  return import("playwright");
}

let chromium;
try {
  const pw = await loadPlaywright();
  chromium = pw.chromium ?? pw.default?.chromium;
  if (!chromium) throw new Error("the loaded module did not export chromium");
} catch (err) {
  console.error(
    "error: Playwright is not available, so the screenshot cannot be taken.\n" +
    "\n" +
    "This file imports Playwright by name, and ESM resolves that from this file's\n" +
    "own directory upwards, not from where you ran the command. Install it in the\n" +
    "skill folder (or anywhere above it, such as $HOME):\n" +
    "  cd ~/.claude/skills/video-reel-factory && npm install playwright\n" +
    "  npx playwright install chromium\n" +
    "\n" +
    "If Playwright is already installed somewhere else, point this script at it:\n" +
    "  PLAYWRIGHT_MODULE=/path/to/node_modules/playwright node screenshot-thumb.mjs ...\n" +
    "\n" +
    `underlying error: ${err.message}`
  );
  process.exit(1);
}

let browser;
try {
  browser = await chromium.launch();
} catch (err) {
  console.error(
    "error: Playwright is installed but Chromium would not launch.\n" +
    "Install the browser binary with:\n" +
    "  npx playwright install chromium\n" +
    "\n" +
    `underlying error: ${err.message}`
  );
  process.exit(1);
}

const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 2 });
await page.goto(pathToFileURL(htmlAbs).href);
await page.waitForTimeout(400);
await page.screenshot({ path: resolve(outPath) });
await browser.close();
console.log(`screenshot written (${width}x${height} @2x): ` + resolve(outPath));
