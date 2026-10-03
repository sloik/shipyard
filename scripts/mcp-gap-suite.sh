#!/usr/bin/env bash
# SPEC-BUG-181 R3: run the MCP 2026 gap suite and report which known gaps
# (G1-G7) are still open. The suite is build-tagged (`mcpgap`), so it never
# runs in `go test ./...`, `make quality`, or CI.
#
# Usage:
#   scripts/mcp-gap-suite.sh                      # report; exit 1 while any gap is open
#   scripts/mcp-gap-suite.sh --expect-open G1,G2  # exit 0 only if exactly these gaps are open
#
# Exit codes: 0 = expectation met (or all gaps closed), 1 = gaps open /
# expectation not met, 2 = harness problem (build failure, a gap with no test).
set -euo pipefail

cd "$(dirname "$0")/.."

expect=""
if [ "${1:-}" = "--expect-open" ]; then
	expect="${2:?--expect-open needs a comma-separated gap list}"
fi

json="$(mktemp)"
trap 'rm -f "$json"' EXIT
set +e
go test -tags mcpgap -count=1 -run '^TestMCPGap_G[0-9]+_' -json ./... >"$json" 2>&1
set -e

python3 - "$json" "$expect" <<'PY'
import json, re, sys

path, expect = sys.argv[1], sys.argv[2]
known = [f"G{i}" for i in range(1, 8)]
status = {}  # test name -> pass/fail
build_problems = []
with open(path) as fh:
    for line in fh:
        line = line.strip()
        if not line.startswith("{"):
            if line:
                build_problems.append(line)
            continue
        ev = json.loads(line)
        test = ev.get("Test", "")
        if ev.get("Action") in ("pass", "fail") and test and "/" not in test:
            status[f'{ev["Package"]}.{test}'] = ev["Action"]
        if ev.get("Action") == "fail" and not test and ev.get("Package") and not any(
            k.startswith(ev["Package"] + ".") for k in status
        ):
            build_problems.append(f'package {ev["Package"]} failed without a gap test result')

by_gap = {g: [] for g in known}
for name, result in sorted(status.items()):
    m = re.search(r"\.TestMCPGap_(G\d+)_", name)
    if m and m.group(1) in by_gap:
        by_gap[m.group(1)].append((name, result))

problems = list(build_problems)
open_gaps = []
print("MCP 2026 gap suite (SPEC-BUG-181)")
for gap in known:
    tests = by_gap[gap]
    if not tests:
        problems.append(f"{gap}: no TestMCPGap_{gap}_* case ran")
        print(f"  {gap}: MISSING")
        continue
    failed = [n for n, r in tests if r == "fail"]
    state = "OPEN" if failed else "closed"
    if failed:
        open_gaps.append(gap)
    print(f"  {gap}: {state} ({len(tests)} case(s))")
    for n, r in tests:
        print(f"      {r:4}  {n}")

print(f"open gaps: {','.join(open_gaps) or 'none'}")
if problems:
    print("harness problems:", *problems, sep="\n  ")
    sys.exit(2)
if expect:
    want = sorted(g.strip() for g in expect.split(",") if g.strip())
    if sorted(open_gaps) != want:
        print(f"expected open gaps {','.join(want)}, got {','.join(open_gaps) or 'none'}")
        sys.exit(1)
    print("expectation met")
    sys.exit(0)
sys.exit(1 if open_gaps else 0)
PY
