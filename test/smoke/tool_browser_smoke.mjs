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
// SPEC-BUG-150: launch/teardown/skip scaffolding now lives in lib/harness.mjs
// so this fast Tool-Browser path and the opt-in `make smoke-full` share it.
//
// Usage: `make smoke`. The Makefile builds the binaries, supplies their paths
// via env, and guards on node presence. lib/harness.mjs guards on Chrome.

import { withHarness, makeChecker } from './lib/harness.mjs';

const failures = await withHarness(async ({ page, base }) => {
  const { check, failures } = makeChecker();

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

  return failures;
});

if (failures.length > 0) {
  console.error(`\nSMOKE FAILED: ${failures.length} check(s) failed: ${failures.join('; ')}`);
  process.exit(1);
}
console.log('\nSMOKE PASSED: all Tool Browser interactive behaviors verified.');
process.exit(0);
