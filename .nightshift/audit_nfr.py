#!/usr/bin/env python3
"""SPEC-066: Audit which non-done specs may be affected by a newly added NFR.

Usage:
    audit_nfr.py --nfr-id NFR-001 --specs-dir path/ [--format text|json]
    audit_nfr.py --check-all --specs-dir path/ [--format text|json]

Match strategy: a non-done spec matches the NFR if any of:
  (a) spec's domain: value appears in the NFR's scope_tags
  (b) "layer-N" where N is spec's layer: value appears in scope_tags
  (c) any token from spec's touches: list appears in scope_tags

If the NFR has no scope_tags (or an empty list), ALL non-done specs are returned
(unknown scope = conservative: applies everywhere).

Retired NFRs produce a message and no report. Individual NFR audits always exit
0; ``--check-all`` is the reconciliation gate and exits 1 for any unreconciled
active-NFR match.

Exit codes:
    0  Individual audit, or --check-all with no unreconciled matches
    1  Usage error (NFR not found, bad specs-dir)
    1  --check-all found one or more unreconciled matches
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from spec_frontmatter import nfr_is_bound_or_waived, nfr_match_reasons

_NON_DONE_STATUSES = frozenset({"draft", "ready", "in_progress", "blocked", "planning", "superseded"})


def _parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        if line.strip().startswith("# "):
            return line.strip()[2:].strip()
    return ""


def _load_specs(specs_dir: Path) -> list[dict[str, Any]]:
    specs = []
    for path in sorted(specs_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = _parse_frontmatter(text)
        if fm.get("id"):
            fm["_body"] = text
            fm["_title"] = _extract_title(text)
            specs.append(fm)
    return specs


def audit(
    nfr_id: str,
    specs_dir: Path,
    fmt: str,
) -> None:
    specs = _load_specs(specs_dir)

    nfr = next((s for s in specs if str(s.get("id", "")) == nfr_id), None)
    if nfr is None:
        print(
            json.dumps({"error": f"NFR not found: {nfr_id}. "
                        f"Check that the file exists in {specs_dir}"}),
            file=sys.stderr,
        )
        sys.exit(1)

    nfr_status = str(nfr.get("status", "")).lower()
    if nfr_status == "retired":
        msg = f"NFR {nfr_id} is retired — no impact report generated."
        if fmt == "json":
            print(json.dumps({
                "nfr_id": nfr_id,
                "nfr_title": nfr.get("_title", ""),
                "status": "retired",
                "affected_specs": [],
                "notes": msg,
            }, indent=2))
        else:
            print(f"[audit-nfr] {msg}")
        sys.exit(0)

    raw_tags = nfr.get("scope_tags") or []
    scope_tags: set[str] = {str(t).lower() for t in raw_tags if isinstance(t, str)}
    unscoped = len(scope_tags) == 0

    nfr_title = nfr.get("_title", "")
    nfr_sid = str(nfr.get("id", ""))

    affected: list[dict[str, Any]] = []
    total_scanned = 0

    for s in specs:
        sid = str(s.get("id", ""))
        if sid == nfr_sid:
            continue
        # Skip NFR-family specs
        if sid.startswith("NFR-") or str(s.get("type", "")).lower() == "nfr":
            continue
        status = str(s.get("status", "")).lower()
        if status not in _NON_DONE_STATUSES:
            continue
        total_scanned += 1

        if unscoped:
            reasons = ["no scope_tags on NFR — conservative, all non-done specs returned"]
        else:
            reasons = nfr_match_reasons(s, nfr)
            if not reasons:
                continue

        affected.append({
            "id": sid,
            "title": s.get("_title", ""),
            "status": status,
            "layer": s.get("layer"),
            "domain": str(s.get("domain") or ""),
            "priority": s.get("priority") or 99,
            "match_reasons": reasons,
        })

    affected.sort(key=lambda x: (x.get("priority") or 99, x.get("layer") or 99))

    if fmt == "json":
        print(json.dumps({
            "nfr_id": nfr_id,
            "nfr_title": nfr_title,
            "scope_tags": sorted(scope_tags),
            "total_non_done_scanned": total_scanned,
            "affected_specs": affected,
        }, indent=2))
    else:
        scope_str = ", ".join(sorted(scope_tags)) if scope_tags else "(none — conservative)"
        print(f"[audit-nfr] NFR: {nfr_id} — {nfr_title}")
        print(f"  scope_tags: {scope_str}")
        print(f"  Scanned {total_scanned} non-done spec(s), found {len(affected)} match(es).")
        if not affected:
            print("  No affected specs found.")
        else:
            for sp in affected:
                reasons_str = ", ".join(sp["match_reasons"])
                print(f"  [{sp['status']}] {sp['id']}: {sp['title']} (via: {reasons_str})")

    sys.exit(0)


def check_all(specs_dir: Path, fmt: str) -> None:
    """Fail closed when an active NFR match is neither bound nor waived."""
    specs = _load_specs(specs_dir)
    active_nfrs = [
        spec for spec in specs
        if (str(spec.get("id", "")).startswith("NFR-") or str(spec.get("type", "")).lower() == "nfr")
        and str(spec.get("status", "")).lower() == "active"
    ]
    candidates = [
        spec for spec in specs
        if not (str(spec.get("id", "")).startswith("NFR-") or str(spec.get("type", "")).lower() == "nfr")
        and str(spec.get("status", "")).lower() in {"draft", "ready", "in_progress", "blocked"}
    ]
    unreconciled = []
    for spec in candidates:
        for nfr in active_nfrs:
            reasons = nfr_match_reasons(spec, nfr)
            if reasons and not nfr_is_bound_or_waived(spec, nfr):
                unreconciled.append({
                    "spec_id": str(spec.get("id", "")),
                    "nfr_id": str(nfr.get("id", "")),
                    "match_reasons": reasons,
                })
    if fmt == "json":
        print(json.dumps({"active_nfrs": len(active_nfrs), "unreconciled": unreconciled}, indent=2))
    elif unreconciled:
        for item in unreconciled:
            print(f"[audit-nfr] UNRECONCILED {item['spec_id']} ↔ {item['nfr_id']} (via: {', '.join(item['match_reasons'])})")
    else:
        print("[audit-nfr] OK — all active NFR matches are bound or waived.")
    sys.exit(1 if unreconciled else 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit which non-done specs may be affected by a newly added NFR. "
            "Audit one NFR, or use --check-all as the static reconciliation gate."
        )
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--nfr-id", help="NFR ID to audit (e.g. NFR-001)")
    selector.add_argument("--check-all", action="store_true", help="fail on every unreconciled active-NFR match")
    parser.add_argument("--specs-dir", required=True, type=Path,
                        help="Path to the specs/ directory")
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        help="Output format (default: text)")
    args = parser.parse_args()

    if not args.specs_dir.exists():
        print(
            json.dumps({"error": f"specs-dir not found: {args.specs_dir}"}),
            file=sys.stderr,
        )
        sys.exit(1)

    if args.check_all:
        check_all(args.specs_dir, args.format)
    audit(args.nfr_id, args.specs_dir, args.format)


if __name__ == "__main__":
    main()
