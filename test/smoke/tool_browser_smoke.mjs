// SPEC-BUG-149: Headless-browser smoke harness for the Tool Browser.
//
// Drives real clicks against a live Shipyard instance to catch DOM/runtime
// regressions that the Go source-scan tests (internal/web/ui_layout_test.go)
// cannot see — e.g. the SPEC-BUG-148 double-toggle bug where two handlers
// cancelled to a net-zero visible change while source-scan reported all green.
//
// Covered behaviors (group "shipyard" = the built-in self group, always rendered):
//   AC1 - a single header click toggles is-collapsed exactly once (visible).
//   AC2 - collapse survives a tool-selection re-render AND a page reload.
//   AC3 - launches/tears down its own ephemeral Shipyard process.
//   AC4 - skips (exit 0) with a clear reason when Chrome is unavailable.
//
// Usage: `make smoke`. The Makefile builds the binaries, supplies their paths
// via env, and guards on node presence. This script guards on Chrome presence.
//
// Env (set by the Makefile):
//   SHIPYARD_BIN   - path to the built `shipyard` binary (required)
//   STUBCHILD_BIN  - path to the built test stub child server (required)
//   CHROME_BIN     - path to a Chrome/Chromium executable (optional; falls back
//                    to the standard macOS Google Chrome location)

import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import net from 'node:net';

const DEFAULT_CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

function skip(reason) {
  console.log(`SKIP: ${reason}`);
  process.exit(0);
}

function fail(reason) {
  console.error(`FAIL: ${reason}`);
  process.exit(1);
}

// --- Resolve Chrome (AC4: skip gracefully if absent) -----------------------
import { existsSync as fsExists } from 'node:fs';

const chromePath = process.env.CHROME_BIN || DEFAULT_CHROME;
if (!fsExists(chromePath)) {
  skip(`Chrome not found at "${chromePath}" (set CHROME_BIN to override)`);
}

// playwright-core is an optional dev dependency; if it's missing, skip too.
let chromium;
try {
  ({ chromium } = await import('playwright-core'));
} catch {
  skip('playwright-core not installed (run `npm install` in the repo root)');
}

const shipyardBin = process.env.SHIPYARD_BIN;
const stubchildBin = process.env.STUBCHILD_BIN;
if (!shipyardBin || !stubchildBin) {
  fail('SHIPYARD_BIN and STUBCHILD_BIN must be set (run via `make smoke`)');
}

// --- Pick an ephemeral port (NOT the dev default 9417) ----------------------
function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function waitForReady(base, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(base + '/api/servers', { signal: AbortSignal.timeout(1000) });
      if (res.ok) {
        const servers = await res.json();
        // Wait for BOTH the self "shipyard" group and the stub "alpha" server,
        // so a clickable alpha tool item reliably exists for the AC2
        // tool-selection step (mirrors cmd/shipyard/e2e_smoke_test.go).
        if (
          Array.isArray(servers) &&
          servers.length >= 2 &&
          servers[0].name === 'shipyard' &&
          servers.some((s) => s.name === 'alpha')
        ) {
          return;
        }
      }
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error(`shipyard did not become ready at ${base} within ${timeoutMs}ms`);
}

// --- Main -------------------------------------------------------------------
const workDir = mkdtempSync(join(tmpdir(), 'shipyard-smoke-'));
const port = await freePort();
const base = `http://127.0.0.1:${port}`;

// Minimal config: runConfig() exits(1) on an empty servers map, so we point one
// server at the test stub child (mirrors cmd/shipyard/e2e_smoke_test.go). The
// built-in "shipyard" self group renders regardless and is what we drive.
const configPath = join(workDir, 'config.json');
writeFileSync(
  configPath,
  JSON.stringify({
    servers: { alpha: { command: stubchildBin, args: [], cwd: workDir } },
    web: { port },
  }),
);

let serverProc;
let browser;
let failures = [];

function check(label, ok) {
  if (ok) {
    console.log(`  PASS  ${label}`);
  } else {
    console.log(`  FAIL  ${label}`);
    failures.push(label);
  }
}

try {
  serverProc = spawn(shipyardBin, ['--headless', '--config', configPath], {
    cwd: workDir,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let serverLog = '';
  serverProc.stdout.on('data', (d) => (serverLog += d));
  serverProc.stderr.on('data', (d) => (serverLog += d));
  serverProc.on('exit', (code) => {
    if (code && code !== 0 && !browser) {
      console.error(`shipyard exited early (code ${code}):\n${serverLog}`);
    }
  });

  await waitForReady(base);

  browser = await chromium.launch({ executablePath: chromePath, headless: true });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();

  const SELF = '.tool-group[data-server="shipyard"]';
  const HEADER = `${SELF} .tool-group-header`;
  const ITEMS = `${SELF} .tool-group-items`;

  async function openTools() {
    await page.click('.tab[data-route="tools"]');
    await page.waitForSelector(HEADER, { timeout: 10000 });
  }

  // Instrument DOMTokenList.toggle so we can assert the click flips is-collapsed
  // EXACTLY once (the SPEC-BUG-148 bug was two handlers toggling = net zero).
  async function installToggleCounter() {
    await page.evaluate(() => {
      window.__isCollapsedToggles = 0;
      const orig = DOMTokenList.prototype.toggle;
      DOMTokenList.prototype.toggle = function (...args) {
        if (args[0] === 'is-collapsed') window.__isCollapsedToggles++;
        return orig.apply(this, args);
      };
    });
  }

  const isCollapsed = () =>
    page.$eval(SELF, (el) => el.classList.contains('is-collapsed'));
  const itemsDisplay = () =>
    page.$eval(ITEMS, (el) => getComputedStyle(el).display);
  const toggleCount = () => page.evaluate(() => window.__isCollapsedToggles);

  await page.goto(base);
  await openTools();

  // Confirm the self group renders before asserting on it.
  check('self "shipyard" group header renders in Tools view', await page.$(HEADER) !== null);

  // --- AC1: one header click toggles collapse exactly once, visibly ---------
  await installToggleCounter();
  const before = await isCollapsed();
  check('group starts expanded (not collapsed)', before === false);

  await page.click(HEADER);
  await page.waitForTimeout(50);

  const afterCollapsed = await isCollapsed();
  const afterDisplay = await itemsDisplay();
  const toggles = await toggleCount();
  check('AC1: one click adds is-collapsed', afterCollapsed === true);
  check('AC1: one click hides items (display:none)', afterDisplay === 'none');
  check('AC1: is-collapsed toggled exactly once', toggles === 1);

  // Click again -> expands (proves it is a real toggle, not stuck).
  await page.click(HEADER);
  await page.waitForTimeout(50);
  check('second click re-expands group', (await isCollapsed()) === false);
  check('second click shows items again', (await itemsDisplay()) !== 'none');

  // --- AC2 part 1: collapse survives a tool-selection re-render -------------
  await page.click(HEADER); // collapse again
  await page.waitForTimeout(50);
  check('group collapsed again before tool-select', (await isCollapsed()) === true);

  // Click a tool in a DIFFERENT (still-expanded) group so the item is visible;
  // the self group must remain collapsed through the resulting re-render.
  const toolItem = await page.$(
    '.tool-group:not([data-server="shipyard"]):not(.is-collapsed) .tool-item[data-server][data-tool]',
  );
  // waitForReady guarantees alpha is online, so the item must exist; a missing
  // item is a real failure, not a skip (avoids a vacuous pass).
  check('a clickable tool item exists in another group', toolItem !== null);
  if (toolItem) {
    const toolName = await toolItem.getAttribute('data-tool');
    await toolItem.click();
    // selectTool() calls renderToolSidebar() and marks the item is-active
    // (index.html:2576) — waiting for is-active proves a re-render actually
    // fired, so the retention assertion below is not checking a static DOM.
    await page.waitForSelector(`.tool-item.is-active[data-tool="${toolName}"]`, { timeout: 5000 });
    await page.waitForSelector(SELF, { timeout: 5000 });
    check('AC2: collapse retained across tool selection re-render', (await isCollapsed()) === true);
  }

  // --- AC2 part 2: collapse survives a page reload (localStorage) -----------
  await page.reload();
  await openTools();
  check('AC2: collapse persisted across reload', (await isCollapsed()) === true);

  await browser.close();
  browser = null;
} catch (err) {
  fail(err && err.stack ? err.stack : String(err));
} finally {
  // AC3: always tear down our own instance, even on assertion failure.
  if (browser) {
    try {
      await browser.close();
    } catch {
      /* ignore */
    }
  }
  if (serverProc && serverProc.exitCode === null) {
    serverProc.kill('SIGTERM');
  }
  try {
    rmSync(workDir, { recursive: true, force: true });
  } catch {
    /* ignore */
  }
}

if (failures.length > 0) {
  console.error(`\nSMOKE FAILED: ${failures.length} check(s) failed: ${failures.join('; ')}`);
  process.exit(1);
}
console.log('\nSMOKE PASSED: all Tool Browser interactive behaviors verified.');
process.exit(0);
