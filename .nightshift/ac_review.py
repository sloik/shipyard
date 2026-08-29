#!/usr/bin/env python3
"""Schema gate for independent AC-loosening reviews (SPEC-260)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


VERDICTS = {"approve", "veto", "redirect"}
KINDS = {"loosened", "covered-by", "runtime-captured", "moved-to"}


def review(proposal: dict[str, Any]) -> dict[str, Any]:
    """Make the conservative, evidence-only reviewer decision for every AC."""
    acs = proposal.get("acs", [])
    rung2 = str(proposal.get("rung2_evidence", ""))
    no_rung2 = not rung2 or "zero commits" in rung2 or "zero verifier" in rung2
    decisions = []
    for item in acs if isinstance(acs, list) else []:
        result = dict(item)
        if no_rung2:
            result["verdict"] = "veto"
            result["evidence"] = "missing rung-2 commits and verifier rounds"
        elif item.get("covered_by"):
            result["verdict"] = "redirect"
            result["redirect"] = str(item["covered_by"])
            result["evidence"] = "done spec satisfies the proposed criterion verbatim"
        else:
            result["verdict"] = "veto"
            result["evidence"] = "independent reviewer needs a cited covering spec/AC or runtime gate"
        decisions.append(result)
    return {**proposal, "acs": decisions}


def validate(payload: dict[str, Any], *, max_loosened: int = 2) -> list[str]:
    """Return deterministic schema/rule failures; empty means auditable."""
    errors: list[str] = []
    for key in ("spec_id", "reviewer_run_id", "rung2_evidence", "smallest_change_evidence", "acs"):
        if not payload.get(key):
            errors.append(f"missing required field: {key}")
    acs = payload.get("acs")
    if not isinstance(acs, list) or not acs:
        return errors + ["acs must be a non-empty list"]
    loosened = 0
    for index, item in enumerate(acs):
        prefix = f"acs[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if not item.get("id"):
            errors.append(f"{prefix}.id is required")
        verdict = item.get("verdict")
        if verdict not in VERDICTS:
            errors.append(f"{prefix}.verdict must be approve, veto, or redirect")
        if not item.get("evidence"):
            errors.append(f"{prefix}.evidence is required")
        proposal = item.get("proposal")
        if not isinstance(proposal, dict):
            errors.append(f"{prefix}.proposal is required")
            continue
        original, proposed, kind = proposal.get("original"), proposal.get("new"), proposal.get("kind")
        if not isinstance(original, str) or not original.strip():
            errors.append(f"{prefix}.proposal.original is required; an AC may never be deleted")
        if not isinstance(proposed, str) or not proposed.strip():
            errors.append(f"{prefix}.proposal.new is required; an AC may never be deleted")
        if kind not in KINDS:
            errors.append(f"{prefix}.proposal.kind is invalid")
        if kind == "loosened" and verdict == "approve":
            loosened += 1
        if verdict == "redirect" and not item.get("redirect"):
            errors.append(f"{prefix}.redirect is required for redirect")
    if loosened > max_loosened:
        errors.append(f"approves {loosened} loosenings; maximum is {max_loosened}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("validate", help="only supported operation")
    parser.add_argument("verdict", type=Path)
    parser.add_argument("--max-loosened", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.verdict.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"SCHEMA: reject: {exc}")
        return 1
    errors = validate(payload, max_loosened=args.max_loosened) if isinstance(payload, dict) else ["verdict must be an object"]
    for error in errors:
        print(f"SCHEMA: reject: {error}")
    print("GATE: " + ("accept" if not errors else "reject"))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
