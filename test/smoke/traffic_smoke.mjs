// SPEC-BUG-171/172: Headless-browser smoke harness for the Traffic view.
//
// Runs as part of the opt-in `make smoke-full` (NOT the fast `make smoke`).
//
// Covered behaviors:
//   - Direction toggle: All / REQ / All / RES / All round-trips. "All" shows
//     every entry, REQ + RES partition it, and the "Showing N of M" footer
//     matches the visible rows (SPEC-BUG-171).
//   - History direction + time "All" options never send direction=All or a
//     NaN time bound (SPEC-BUG-171).
//   - Detail-panel copy buttons put the payload on the clipboard as valid JSON
//     without line numbers (SPEC-BUG-172).
//
// Live WebSocket inserts are blocked so row counts are deterministic.
//
// Skips gracefully (exit 0) when Chrome/playwright-core/node is unavailable
// (handled by lib/harness.mjs + the Makefile node guard).

import { isDeepStrictEqual } from 'node:util';
import { withHarness, makeChecker } from './lib/harness.mjs';

const ROWS = '#timeline-content .table-row:not([data-detail-for])';

const failures = await withHarness(async ({ page, base }) => {
  const { check, failures } = makeChecker();

  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: base });
  for (let i = 0; i < 3; i++) {
    await fetch(base + '/api/tools/call', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ server: 'alpha', tool: 'echo', arguments: { message: 'smoke ' + i } }),
    });
  }

  const trafficURLs = [];
  page.on('request', (r) => { if (r.url().includes('/api/traffic?')) trafficURLs.push(r.url()); });
  await page.routeWebSocket('**/ws', () => {});
  await page.goto(base);
  await page.waitForSelector(ROWS, { timeout: 10000 });
  // Let the dashboard's own startup traffic settle before taking the baseline.
  await page.waitForTimeout(1500);

  // The dashboard can emit its own traffic (e.g. a tools/list refresh) at any
  // moment, so every view is compared with the API's count at that moment.
  async function apiTotal(direction) {
    const q = new URLSearchParams({ page_size: '1' });
    if (direction) q.set('direction', direction);
    return (await (await fetch(base + '/api/traffic?' + q)).json()).total_count;
  }
  async function clickDir(i, direction) {
    await page.locator('#dir-toggle button').nth(i).click();
    await page.waitForTimeout(700);
    const view = await page.evaluate((sel) => ({
      rows: document.querySelectorAll(sel).length,
      dirs: [...new Set([...document.querySelectorAll(sel + ' [data-col=dir]')].map((e) => e.textContent.trim()))],
      info: document.getElementById('timeline-scroll-info').textContent,
    }), ROWS);
    view.expected = await apiTotal(direction);
    return view;
  }
  function footerMatches(s) {
    const m = s.info.match(/Showing (\d+) of (\d+)/);
    return !m || Number(m[1]) === s.rows;
  }

  // --- Direction toggle (SPEC-BUG-171) --------------------------------------
  // A new entry can land between the click and the API count, so allow the
  // view to trail the API by the few entries one refresh produces.
  const near = (v) => v.rows > 0 && v.rows <= v.expected && v.expected - v.rows <= 2;
  const REQ = 'client\u2192server';
  const RES = 'server\u2192client';
  for (const [step, i, dir, label] of [
    ['All (already active)', 0, '', 'ALL'],
    ['REQ', 1, REQ, 'REQ'],
    ['All after REQ', 0, '', 'ALL'],
    ['RES', 2, RES, 'RES'],
    ['All after RES', 0, '', 'ALL'],
  ]) {
    const v = await clickDir(i, dir);
    check(`${step} shows its ${v.expected} entries (got ${v.rows})`, near(v));
    if (label === 'ALL') {
      check(`${step} includes both directions`, v.dirs.includes('REQ') && v.dirs.includes('RES'));
    } else {
      check(`${step} shows only ${label} rows`, v.dirs.length === 1 && v.dirs[0] === label);
    }
    check(`${step} footer matches visible rows`, footerMatches(v));
  }

  // --- Copy buttons (SPEC-BUG-172) ------------------------------------------
  await page.locator(ROWS).nth(1).click();
  await page.waitForSelector('#timeline-content .traffic-panel-copy', { timeout: 5000 });
  const rowID = await page.evaluate(() => document.querySelector('#timeline-content .row-expanded').dataset.id);
  const detail = await (await fetch(base + '/api/traffic/' + rowID)).json();
  const pair = [detail.entry, detail.matched].filter(Boolean);
  const captured = {
    request: pair.find((e) => e.direction === REQ),
    response: pair.find((e) => e.direction === RES),
  };
  for (const [idx, label] of [[0, 'request'], [1, 'response']]) {
    await page.locator('#timeline-content .traffic-panel-copy').nth(idx).click();
    await page.waitForTimeout(300);
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    let parsed;
    try { parsed = JSON.parse(clip); } catch { /* not JSON */ }
    check(`${label} copy is valid JSON`, parsed !== undefined);
    check(`${label} copy has no line-number prefix`, !/^\d+\{/.test(clip));
    check(`${label} copy equals the captured payload`,
      captured[label] !== undefined && isDeepStrictEqual(parsed, JSON.parse(captured[label].payload)));
  }

  // --- History "All" options (SPEC-BUG-171) ---------------------------------
  await page.click('.tab[data-route="history"]');
  await page.waitForTimeout(1500);
  trafficURLs.length = 0;
  for (const [toggle, i] of [['#history-dir-toggle', 1], ['#history-dir-toggle', 0], ['#history-time-toggle', 1], ['#history-time-toggle', 0]]) {
    await page.locator(toggle + ' button').nth(i).click();
    await page.waitForTimeout(600);
  }
  check('History toggles never send direction=All or from_ts=NaN',
    trafficURLs.length > 0 && !trafficURLs.some((u) => /direction=All|from_ts=NaN/.test(u)));

  return failures;
});

if (failures.length > 0) {
  console.error(`\nSMOKE FAILED: ${failures.length} check(s) failed: ${failures.join('; ')}`);
  process.exit(1);
}
console.log('\nSMOKE PASSED: all Traffic view interactive behaviors verified.');
process.exit(0);
