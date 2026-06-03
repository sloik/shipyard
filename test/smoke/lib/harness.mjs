// SPEC-BUG-150: shared scaffolding for the headless-browser smoke harnesses.
//
// Extracted verbatim from the SPEC-BUG-149 Tool Browser harness so both the
// fast `make smoke` (Tool Browser) and the opt-in `make smoke-full` (Tool
// Browser + Servers) reuse one launch/teardown/skip implementation (R3).
//
// Responsibilities:
//   - resolve Chrome + playwright-core, SKIP (exit 0) gracefully if absent (AC3)
//   - pick an ephemeral port (NOT the dev default 9417)
//   - write a minimal config pointing one server at the test stub child
//     (runConfig() exits(1) on an empty servers map, so the "alpha" stub is
//     required; the built-in "shipyard" self group renders regardless)
//   - launch a `--headless` shipyard, wait until BOTH the self group and the
//     "alpha" stub are ready, then hand back a Playwright page
//   - tear down the process + tmpdir on the way out, even on failure (AC3/teardown)
//
// Env (set by the Makefile):
//   SHIPYARD_BIN   - path to the built `shipyard` binary (required)
//   STUBCHILD_BIN  - path to the built test stub child server (required)
//   CHROME_BIN     - path to a Chrome/Chromium executable (optional; falls back
//                    to the standard macOS Google Chrome location)

import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync, existsSync as fsExists } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import net from 'node:net';

const DEFAULT_CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

export function skip(reason) {
  console.log(`SKIP: ${reason}`);
  process.exit(0);
}

export function fail(reason) {
  console.error(`FAIL: ${reason}`);
  process.exit(1);
}

// Resolve Chrome + playwright-core (AC3: skip gracefully if either is absent).
// Returns { chromium, chromePath }.
export async function resolveBrowser() {
  const chromePath = process.env.CHROME_BIN || DEFAULT_CHROME;
  if (!fsExists(chromePath)) {
    skip(`Chrome not found at "${chromePath}" (set CHROME_BIN to override)`);
  }
  let chromium;
  try {
    ({ chromium } = await import('playwright-core'));
  } catch {
    skip('playwright-core not installed (run `npm install` in the repo root)');
  }
  return { chromium, chromePath };
}

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
        // so the views under test render a populated, clickable DOM.
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

// Launch an ephemeral headless Shipyard + Chrome and run `body({ page, base })`.
// Always tears down the browser, server process, and tmpdir (even on throw).
// `body` returns an array of failure labels (empty = all passed).
//
// Returns the array of failure labels so the caller can set the exit code.
export async function withHarness(body) {
  const { chromium, chromePath } = await resolveBrowser();

  const shipyardBin = process.env.SHIPYARD_BIN;
  const stubchildBin = process.env.STUBCHILD_BIN;
  if (!shipyardBin || !stubchildBin) {
    fail('SHIPYARD_BIN and STUBCHILD_BIN must be set (run via `make smoke` / `make smoke-full`)');
  }

  const workDir = mkdtempSync(join(tmpdir(), 'shipyard-smoke-'));
  const port = await freePort();
  const base = `http://127.0.0.1:${port}`;

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

    const failures = await body({ page, base });

    await browser.close();
    browser = null;
    return failures;
  } finally {
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
}

// A small check() helper bound to a fresh failures array. Returns { check, failures }.
export function makeChecker() {
  const failures = [];
  function check(label, ok) {
    if (ok) {
      console.log(`  PASS  ${label}`);
    } else {
      console.log(`  FAIL  ${label}`);
      failures.push(label);
    }
  }
  return { check, failures };
}
