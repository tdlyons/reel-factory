#!/usr/bin/env node
/**
 * reel-keywords.mjs: pick the comment-to-DM keyword for a drop.
 *
 * Why a pool rather than one permanent word: comment-to-DM tools generally
 * cannot create keyword triggers by API, so a fresh keyword per video would
 * mean building a new automation by hand every single day. But a single
 * permanent keyword makes every video look like it points at the same asset,
 * because a repeat viewer sees the same word five times and assumes it is one
 * thing on loop.
 *
 * A pool fixes both. Comment triggers accept MULTIPLE keywords on one
 * automation, so every word in the pool lives in a single hand-built
 * automation pointing at one destination. Set it up once; this script only
 * picks which word to say in each video.
 *
 * Every keyword resolves to the same place, so the back catalogue keeps
 * funnelling to whatever is currently pinned. Choosing the least-recently-used
 * word also gives rough attribution: a comment saying LEDGER came from the
 * video that used LEDGER.
 *
 * Requires: Node 18+ (node: builtins only, no npm packages).
 *
 * Example:
 *   node reel-keywords.mjs --peek
 *   node reel-keywords.mjs --destination https://example.com/free-guide --label "the guide"
 *
 * State: a small JSON ledger of usage counts, by default at
 *   $XDG_STATE_HOME/reel-factory/keywords.json
 *   (falling back to ~/.local/state/reel-factory/keywords.json)
 * Override with --ledger <path> or REEL_KEYWORDS_LEDGER.
 */

import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join, isAbsolute, resolve } from "node:path";
import { homedir } from "node:os";

// Chosen so a stray comment can never trigger one by accident, and so each
// implies "there is a thing you get" without naming a specific topic.
const DEFAULT_POOL = [
  "TEARDOWN", "BLUEPRINT", "PLAYBOOK", "RECEIPTS", "BREAKDOWN",
  "TOOLKIT", "VAULT", "STACK", "ENGINE", "LEDGER",
  "AUDIT", "ROADMAP", "SIGNAL", "PROOF", "NUMBERS",
  "RUNBOOK", "DOSSIER", "ARCHIVE", "SCHEMATIC", "FIELDNOTES",
];

const USAGE = `reel-keywords.mjs: pick the comment-to-DM keyword for a drop, least recently used first.

usage:
  node reel-keywords.mjs                 pick a keyword and record it as spent
  node reel-keywords.mjs --peek          show the next pick, record nothing
  node reel-keywords.mjs --list          show the pool with usage history
  node reel-keywords.mjs --setup         print the one-time automation setup block
  node reel-keywords.mjs --help          this message

options:
  --ledger <path>       usage ledger to read and write
                        (default: $XDG_STATE_HOME/reel-factory/keywords.json,
                         else ~/.local/state/reel-factory/keywords.json;
                         env: REEL_KEYWORDS_LEDGER)
  --destination <url>   where every keyword resolves to, printed in the output and
                        in --setup (env: REEL_KEYWORDS_DESTINATION)
  --label <text>        human name for that destination, used in --setup prose
                        (default: "the destination"; env: REEL_KEYWORDS_LABEL)
  --pool <file>         keyword pool to use instead of the built-in 20: either a JSON
                        array of strings, or one keyword per line
                        (env: REEL_KEYWORDS_POOL)

notes:
  The ledger is created on first write, parent directories included. Nothing is
  written by --peek, --list or --setup.
`;

function fail(msg) {
  console.error(`error: ${msg}\n\nRun with --help for usage.`);
  process.exit(1);
}

// ---- args
const argv = process.argv.slice(2);
const flags = new Set();
const opts = {};
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--help" || a === "-h") { console.log(USAGE); process.exit(0); }
  else if (a === "--peek" || a === "--list" || a === "--setup") flags.add(a);
  else if (a === "--ledger" || a === "--destination" || a === "--label" || a === "--pool") {
    const v = argv[++i];
    if (v === undefined) fail(`${a} needs a value`);
    opts[a.slice(2)] = v;
  } else fail(`unrecognised argument: ${a}`);
}

// ---- config
const stateHome = process.env.XDG_STATE_HOME || join(homedir(), ".local", "state");
const ledgerPath = resolve(
  opts.ledger || process.env.REEL_KEYWORDS_LEDGER || join(stateHome, "reel-factory", "keywords.json")
);
const destination =
  opts.destination || process.env.REEL_KEYWORDS_DESTINATION ||
  "<no destination configured: pass --destination or set REEL_KEYWORDS_DESTINATION>";
const label = opts.label || process.env.REEL_KEYWORDS_LABEL || "the destination";

function loadPool() {
  const src = opts.pool || process.env.REEL_KEYWORDS_POOL;
  if (!src) return DEFAULT_POOL;
  const p = isAbsolute(src) ? src : resolve(src);
  if (!existsSync(p)) fail(`keyword pool file not found: ${p}`);
  const raw = readFileSync(p, "utf8").trim();
  let list;
  if (raw.startsWith("[")) {
    try { list = JSON.parse(raw); } catch (e) { fail(`keyword pool file is not valid JSON: ${e.message}`); }
  } else {
    list = raw.split(/\r?\n/);
  }
  list = list.map((k) => String(k).trim()).filter(Boolean);
  if (!list.length) fail(`keyword pool file is empty: ${p}`);
  return list;
}

const POOL = loadPool();

// ---- ledger
function load() {
  if (!existsSync(ledgerPath)) return { used: {} };
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(ledgerPath, "utf8"));
  } catch (e) {
    fail(`ledger is not valid JSON (${ledgerPath}): ${e.message}\n       Delete it to start a fresh rotation.`);
  }
  if (!parsed || typeof parsed !== "object" || typeof parsed.used !== "object" || parsed.used === null) {
    return { used: {} };
  }
  return parsed;
}

function save(s) {
  mkdirSync(dirname(ledgerPath), { recursive: true });
  writeFileSync(ledgerPath, JSON.stringify(s, null, 2));
}

const state = load();

if (flags.has("--setup")) {
  console.log(`
Comment-to-DM automation, one-time setup. You never touch this again.

  1. In your comment-to-DM tool (ManyChat or similar), create a new automation
     with a "post or reel comments" trigger.
  2. Apply it to: all posts and reels, so the back catalogue keeps working.
  3. In the keyword list, paste all ${POOL.length} of these:

${POOL.join(", ")}

  4. Response DM, one message, the same for every keyword:

     "Here it is:
      ${destination}"

  5. Turn it on.

Every keyword lands in the same place, so the DM never needs editing. Pin the
current drop at ${label} and every video, old and new, points at it.
`);
  process.exit(0);
}

if (flags.has("--list")) {
  const rows = POOL.map((k) => ({ keyword: k, uses: state.used[k]?.count || 0, last: state.used[k]?.last || "never" }))
    .sort((a, b) => a.uses - b.uses || (a.last < b.last ? -1 : 1));
  console.log(`ledger: ${ledgerPath}${existsSync(ledgerPath) ? "" : " (not created yet)"}`);
  console.log("keyword      uses  last used");
  for (const r of rows) console.log(`${r.keyword.padEnd(12)} ${String(r.uses).padStart(4)}  ${r.last}`);
  process.exit(0);
}

// Least-recently-used, so the pool cycles fully before any word repeats.
const ranked = [...POOL].sort((a, b) => {
  const A = state.used[a], B = state.used[b];
  if (!A && !B) return POOL.indexOf(a) - POOL.indexOf(b);
  if (!A) return -1;
  if (!B) return 1;
  if (A.count !== B.count) return A.count - B.count;
  return A.last < B.last ? -1 : 1;
});
const pick = ranked[0];

if (flags.has("--peek")) {
  console.log(pick);
  process.exit(0);
}

const today = new Date().toISOString().slice(0, 10);
state.used[pick] = { count: (state.used[pick]?.count || 0) + 1, last: today };
save(state);

const used = Object.values(state.used).reduce((n, v) => n + (v?.count || 0), 0);
console.log(JSON.stringify({
  keyword: pick,
  destination,
  spoken: `Comment ${pick} and I'll send it over.`,
  on_screen: `Comment "${pick}"`,
  pool_position: `${used} ${used === 1 ? "drop" : "drops"} used, ${POOL.length} keywords in rotation`,
  ledger: ledgerPath,
}, null, 2));
