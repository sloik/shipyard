// SPEC-BUG-150: Headless-browser smoke harness for the Servers view.
//
// Extends the SPEC-BUG-149 pattern to a second view. Runs as part of the
// opt-in `make smoke-full` (NOT the fast `make smoke`).
//
// The interactive behavior under test is the server enable/disable Switch
// toggle (index.html toggleServer -> PUT /api/servers/{name}/enabled). The
// endpoint flips a gateway policy flag (server.go handleServerEnabledPUT ->
// SetServerEnabled); it does NOT kill the child process, so the re-render is
// instant and deterministic — ideal for a headless assertion.
//
// Covered behaviors (the "alpha" stub child is the togglable card; the
// built-in "shipyard" self card cannot be disabled):
//   - Servers tab renders cards from config (self + alpha) without traffic.
//   - The alpha card starts with switch-on.
//   - Clicking the Switch round-trips: switch-on -> disabled state
//     (switch-off + "Blocked by gateway policy" banner) -> back to switch-on.
//     This is a real interactive re-render, not a static DOM presence check.
//
// Skips gracefully (exit 0) when Chrome/playwright-core/node is unavailable
// (handled by lib/harness.mjs + the Makefile node guard).

import { withHarness, makeChecker } from './lib/harness.mjs';

const ALPHA = '.server-card[data-server="alpha"]';

const failures = await withHarness(async ({ page, base }) => {
  const { check, failures } = makeChecker();

  async function openServers() {
    await page.click('.tab[data-route="servers"]');
    await page.waitForSelector('.server-card[data-server="shipyard"]', { timeout: 10000 });
  }

  await page.goto(base);
  await openServers();

  // --- Cards render from config (precondition) ------------------------------
  check('self "shipyard" card renders in Servers view',
    await page.$('.server-card[data-server="shipyard"]') !== null);
  await page.waitForSelector(ALPHA, { timeout: 5000 });
  check('alpha stub server card renders in Servers view', await page.$(ALPHA) !== null);

  // The alpha (online) card carries a Switch toggle. waitForReady guarantees
  // alpha is online, so an enabled switch must exist; a missing one is a real
  // failure, not a skip (avoids a vacuous pass).
  const onSwitch = await page.$(`${ALPHA} button.switch.switch-on`);
  check('alpha card starts with an enabled Switch (switch-on)', onSwitch !== null);

  if (onSwitch) {
    // --- Toggle OFF: card must re-render into the gateway-disabled state ----
    await onSwitch.click();
    // toggleServer() does PUT then loadServers() (a full re-render). Wait for
    // the disabled-state Switch to appear, which proves the re-render fired and
    // reflects the new gateway-policy state — not a static toggle of a class.
    await page.waitForSelector(`${ALPHA} button.switch.switch-off`, { timeout: 5000 });
    check('toggle off: alpha card shows disabled Switch (switch-off)',
      await page.$(`${ALPHA} button.switch.switch-off`) !== null);
    // The gateway-disabled branch renders the "Blocked by gateway policy" banner.
    const blockedText = await page.$eval(ALPHA, (el) => el.textContent || '');
    check('toggle off: alpha card shows "Blocked by gateway policy" banner',
      blockedText.includes('Blocked by gateway policy'));

    // --- Toggle back ON: card must re-render back to the enabled state ------
    const offSwitch = await page.$(`${ALPHA} button.switch.switch-off`);
    await offSwitch.click();
    await page.waitForSelector(`${ALPHA} button.switch.switch-on`, { timeout: 5000 });
    check('toggle on: alpha card returns to enabled Switch (switch-on)',
      await page.$(`${ALPHA} button.switch.switch-on`) !== null);
    const restoredText = await page.$eval(ALPHA, (el) => el.textContent || '');
    check('toggle on: alpha card no longer shows the blocked banner',
      !restoredText.includes('Blocked by gateway policy'));
  }

  return failures;
});

if (failures.length > 0) {
  console.error(`\nSMOKE FAILED: ${failures.length} check(s) failed: ${failures.join('; ')}`);
  process.exit(1);
}
console.log('\nSMOKE PASSED: all Servers view interactive behaviors verified.');
process.exit(0);
