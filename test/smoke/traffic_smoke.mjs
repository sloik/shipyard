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

  // --- Filter bar layout (SPEC-BUG-175) -------------------------------------
  const bar = await page.evaluate(() => {
    const box = (el) => { const b = el.getBoundingClientRect(); return { x: b.x, y: b.y, w: b.width, h: b.height, bottom: b.bottom, right: b.right }; };
    const barBox = box(document.getElementById('filter-bar'));
    const labels = [...document.querySelectorAll('#filter-bar .input-label')].map((l) => ({ y: box(l).y, size: getComputedStyle(l).fontSize }));
    const controls = [...document.querySelectorAll('#filter-bar .input-group > :not(.input-label), #clear-filters-btn')].map(box);
    const counts = [...document.querySelectorAll('#timeline-content *')]
      .filter((e) => e.children.length === 0 && /\bentries\b/.test(e.textContent) && e.getClientRects().length > 0);
    return {
      server: box(document.getElementById('filter-server')).w,
      method: box(document.getElementById('filter-method')).w,
      labels, barBox, controls, countEls: counts.length, badge: !!document.getElementById('traffic-count'),
    };
  });
  check(`Server/Method selects are 160px (got ${bar.server}/${bar.method})`, bar.server === 160 && bar.method === 160);
  check('filter labels are 11px', bar.labels.length === 3 && bar.labels.every((l) => l.size === '11px'));
  check('filter labels share one baseline', new Set(bar.labels.map((l) => Math.round(l.y))).size === 1);
  check('filter controls fit inside the filter bar',
    bar.controls.every((c) => c.y >= bar.barBox.y && c.bottom <= bar.barBox.bottom && c.right <= bar.barBox.right));
  check('no filter-bar entry badge', !bar.badge);
  check(`one visible entry count (got ${bar.countEls})`, bar.countEls === 1);

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

  // --- Live rows match a reload (SPEC-BUG-173/174) --------------------------
  // A fresh page with the WebSocket connected, so the tool call's rows arrive live.
  const live = await page.context().newPage();
  await live.goto(base);
  await live.waitForSelector(ROWS, { timeout: 10000 });
  await live.waitForTimeout(1000);
  await fetch(base + '/api/tools/call', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ server: 'alpha', tool: 'echo', arguments: { message: 'live' } }),
  });
  await live.waitForTimeout(1000);
  const newest = (await (await fetch(base + '/api/traffic?method=tools%2Fcall&page_size=2')).json()).items;
  const liveRes = newest.find((e) => e.direction === RES);
  const liveReq = newest.find((e) => e.direction === REQ);
  async function cells(id) {
    return live.evaluate((rowID) => {
      const row = document.querySelector(`#timeline-content .table-row[data-id="${rowID}"]:not([data-detail-for])`);
      if (!row) return null;
      const text = (col) => row.querySelector(`[data-col=${col}]`).textContent.trim();
      return { method: text('method'), status: text('status'), latency: text('latency') };
    }, id);
  }
  const liveCells = { res: await cells(liveRes?.id), req: await cells(liveReq?.id) };
  check('live RES row shows the correlated method', liveCells.res?.method === 'tools/call');
  check('live REQ row is no longer pending', liveCells.req !== null && liveCells.req.status !== 'pending');
  check('live REQ row shows a latency', liveCells.req !== null && /\d+m?s/.test(liveCells.req.latency));
  await live.reload();
  await live.waitForSelector(ROWS, { timeout: 10000 });
  const reloaded = { res: await cells(liveRes?.id), req: await cells(liveReq?.id) };
  check('live rows render the same as after a reload', isDeepStrictEqual(liveCells, reloaded));
  // The single entry count follows live rows (SPEC-BUG-175).
  await fetch(base + '/api/tools/call', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ server: 'alpha', tool: 'echo', arguments: { message: 'count' } }),
  });
  await live.waitForTimeout(1000);
  const liveCount = await live.evaluate((sel) => ({
    rows: document.querySelectorAll(sel).length,
    info: document.getElementById('timeline-scroll-info').textContent,
  }), ROWS);
  const countMatch = liveCount.info.match(/Showing (\d+) of (\d+)/);
  check(`entry count follows live rows (${liveCount.info}, ${liveCount.rows} rows)`,
    countMatch !== null && Number(countMatch[1]) === liveCount.rows && Number(countMatch[2]) === liveCount.rows);
  const notification = await live.evaluate((sel) => [...document.querySelectorAll(sel)]
    .filter((r) => r.querySelector('[data-col=method]').textContent.trim() === 'notifications/initialized')
    .map((r) => r.querySelector('[data-col=status]').textContent.trim()), ROWS);
  check('notifications/initialized row is not pending', notification.length > 0 && !notification.includes('pending'));

  // --- Empty state matches the design (SPEC-BUG-176) ------------------------
  const empty = await page.context().newPage();
  await empty.setViewportSize({ width: 1440, height: 900 });
  await empty.routeWebSocket('**/ws', () => {});
  await empty.route('**/api/traffic?*', (r) => r.fulfill({ json: { items: [], total_count: 0 } }));
  await empty.goto(base);
  await empty.waitForSelector('#timeline-empty .empty-title', { state: 'visible', timeout: 10000 });
  const es = await empty.evaluate(() => {
    const box = (s) => document.querySelector(s).getBoundingClientRect();
    const style = (s) => getComputedStyle(document.querySelector(s));
    const view = box('#view-timeline');
    const icon = box('#timeline-empty .empty-icon');
    const cards = box('#onboard-cards');
    return {
      title: document.querySelector('#timeline-empty .empty-title').textContent.trim(),
      titleSize: style('#timeline-empty .empty-title').fontSize,
      desc: document.querySelector('#timeline-empty .empty-desc').textContent.trim(),
      stepTitles: [...document.querySelectorAll('#timeline-empty .step-title')].map((e) => e.textContent.trim()),
      code: document.querySelector('#timeline-empty .step-code')?.textContent.trim(),
      cardsWidth: cards.width,
      chipBg: style('#timeline-empty .step-number').backgroundColor,
      // Centre of the icon-to-cards block relative to the view's centre.
      offset: Math.abs((icon.top + cards.bottom) / 2 - (view.top + view.bottom) / 2),
    };
  });
  check('empty state copy matches the design',
    es.title === 'No traffic yet'
    && es.desc === 'Start your MCP server through Shipyard to see traffic here.'
    && es.stepTitles.join('|') === 'Wrap your MCP server|Point your AI client at Shipyard'
    && es.code === 'shipyard wrap -- npx -y @mcp/server /tmp');
  check(`empty state title is 20px (got ${es.titleSize})`, es.titleSize === '20px');
  check(`empty state steps are 480px wide (got ${es.cardsWidth})`, es.cardsWidth === 480);
  check(`step chips use the solid accent (got ${es.chipBg})`, es.chipBg === 'rgb(31, 111, 235)');
  check(`empty state is vertically centred (offset ${Math.round(es.offset)}px)`, es.offset <= 4);

  return failures;
});

if (failures.length > 0) {
  console.error(`\nSMOKE FAILED: ${failures.length} check(s) failed: ${failures.join('; ')}`);
  process.exit(1);
}
console.log('\nSMOKE PASSED: all Traffic view interactive behaviors verified.');
process.exit(0);
