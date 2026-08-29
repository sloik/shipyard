#!/usr/bin/env python3
"""Parent-owned drive-to-done state machine for blocked Nightshift specs.

The module records evidence outcomes and produces bounded worker briefs.  It does
not launch workers, change lifecycle state, commit, or merge; those effects remain
with the kickoff parent and the ordinary fresh-main evidence/verifier gates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import yaml
from ac_review import validate as validate_ac_review
from loop_events import open_run_log
from unblock_spec import prepare


class LadderError(ValueError):
    """Invalid drive-to-done request or evidence result."""


RUNG_PLAN = (
    {"rung": 1, "name": "bounded repair", "effect": "run the default unblock flow"},
    {"rung": 2, "name": "work-to-done", "effect": "dispatch one evidence-only implementer"},
    {"rung": 3, "name": "coverage / runtime-capture", "effect": "annotate per-AC evidence without changing AC text"},
    {"rung": 4, "name": "AC review", "effect": "request SPEC-260 review when available"},
    {"rung": 5, "name": "authorize", "effect": "stop and ask the user to authorize"},
)
ESCALATING_OUTCOMES = frozenset({"failed", "skipped", "unavailable"})
RESULT_OUTCOMES = ESCALATING_OUTCOMES | {"passed", "awaiting_evidence"}


def _start_rung(from_rung: int | None) -> int:
    if from_rung is None:
        return 1
    if from_rung not in {2, 3, 4}:
        raise LadderError("--from-rung must be 2 through 4")
    return from_rung


def _reviewer_available(root: Path) -> bool:
    return (
        Path(__file__).with_name("ac_review.py").is_file()
        and (root / ".claude" / "agents" / "nightshift-ac-reviewer.md").is_file()
    )


def _max_loosened(root: Path) -> int:
    """Read the optional reviewer cap; malformed config remains conservative."""
    try:
        data: dict[str, Any] = {}
        for document in yaml.safe_load_all((root / "config.yaml").read_text(encoding="utf-8")):
            if isinstance(document, dict):
                data.update(document)
        value = data.get("unblock", {}).get("ac_review", {}).get("max_loosened_per_pass", 2)
        return value if isinstance(value, int) and value >= 0 else 2
    except (OSError, yaml.YAMLError, AttributeError):
        return 2


def plan_ladder(spec_file: Path, project_root: Path, run_id: str, *,
                from_rung: int | None = None) -> dict[str, Any]:
    """Return the opt-in ladder plan and admission verdict without mutation."""
    start = _start_rung(from_rung)
    packet = prepare(spec_file, project_root, run_id, allow_escalation=True)
    return {
        "mode": "drive to done",
        "run_id": run_id,
        "spec_id": packet["spec_id"],
        "from_rung": start,
        "admission": packet,
        "plan": [dict(item) for item in RUNG_PLAN if item["rung"] >= start],
    }


def build_worker_brief(packet: Mapping[str, Any], *, rung: int) -> str:
    """Build a bounded evidence-only brief; it confers no parent authority."""
    if rung not in {1, 2, 3, 4}:
        raise LadderError("worker briefs are available only for rungs 1 through 4")
    evidence = ", ".join(item["path"] for item in packet.get("evidence", []))
    guardrails = "\n".join(f"- {item}" for item in packet["guardrails"])
    rung_instruction = {
        1: "Perform only the bounded unblock repair.",
        2: (
            "Work the spec toward done. Subagents are permitted within this bounded rung. "
            "Resilience ladder: capability probe -> smallest safe repair -> post-repair "
            "probe -> one fresh-worker or transport-rebind probe."
        ),
        3: (
            "Assess every AC for cited covered-by or runtime-captured evidence; do not "
            "change acceptance-criterion text."
        ),
        4: "Return only the independent SPEC-260 AC-review verdict and its evidence.",
    }[rung]
    return (
        f"Drive to done rung {rung} for {packet['spec_id']}.\n"
        f"Bounded task: {packet['bounded_task']}\n"
        f"Rung instruction: {rung_instruction}\n"
        f"Pinned evidence: {evidence}\n"
        f"Prior attempts: {json.dumps(packet['prior_attempts'], sort_keys=True)}\n"
        f"Guardrails:\n{guardrails}\n"
        "The worker must not change lifecycle state or merge; it returns only "
        "intervention and verification evidence.\n"
        f"Verification gate: {packet['verification_gate']}\n"
    )


def _refs(packet: Mapping[str, Any], result: Mapping[str, Any]) -> list[str]:
    refs = result.get("evidence_refs")
    if refs is None:
        refs = [item["path"] for item in packet.get("evidence", [])]
    if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
        raise LadderError("evidence_refs must be a list of project-relative paths")
    for ref in refs:
        path = Path(ref)
        if path.is_absolute() or ".." in path.parts:
            raise LadderError("evidence_refs must be project-relative")
    return refs


def _emit(root: Path, packet: Mapping[str, Any], rung: int, outcome: str,
          refs: list[str]) -> dict[str, Any]:
    record = {"rung": rung, "outcome": outcome, "evidence_refs": refs}
    open_run_log(root, str(packet["run_id"])).emit(
        "unblock_rung", packet["spec_id"], **record,
    )
    return record


def _result(results: Mapping[int, Mapping[str, Any]], rung: int) -> Mapping[str, Any]:
    value = results.get(rung, {"outcome": "awaiting_evidence"})
    outcome = value.get("outcome")
    if outcome not in RESULT_OUTCOMES:
        raise LadderError(f"invalid rung {rung} outcome")
    return value


def _verified_done(result: Mapping[str, Any]) -> bool:
    return (
        result.get("outcome") == "passed"
        and result.get("evidence_gate") == "pass"
        and result.get("verifier") == "pass"
    )


def drive_to_done(spec_file: Path, project_root: Path, run_id: str, *,
                  from_rung: int | None = None, dry_run: bool = False,
                  results: Mapping[int, Mapping[str, Any]] | None = None,
                  reviewer_available: bool | None = None) -> dict[str, Any]:
    """Advance sequentially through recorded rung evidence.

    A ``done`` return is an evidence conclusion for the parent.  This function
    deliberately performs no lifecycle transition; the parent must still run the
    ordinary fresh-main gate and terminal commit path.
    """
    root = Path(project_root).resolve()
    summary = plan_ladder(spec_file, root, run_id, from_rung=from_rung)
    if dry_run:
        return summary
    packet = summary["admission"]
    result_map = results or {}
    entered: list[dict[str, Any]] = []
    current = summary["from_rung"]

    if current == 1 and packet["eligibility"] == "skipped":
        entered.append(_emit(root, packet, 1, "skipped", _refs(packet, {})))
        current = 2

    while current <= 4:
        if current == 4:
            available = _reviewer_available(root) if reviewer_available is None else reviewer_available
            if not available:
                entered.append(_emit(root, packet, 4, "unavailable", _refs(packet, {})))
                current = 5
                break
        rung_result = _result(result_map, current)
        outcome = str(rung_result["outcome"])
        if current == 4:
            verdict = rung_result.get("ac_review")
            review_errors = validate_ac_review(verdict, max_loosened=_max_loosened(root)) if isinstance(verdict, dict) else ["missing AC-review verdict"]
            vetoed = not review_errors and any(item.get("verdict") == "veto" for item in verdict["acs"])
            if vetoed:
                entered.append(_emit(root, packet, 4, "veto", _refs(packet, rung_result)))
                subsequent = rung_result.get("post_veto_attempt")
                if not isinstance(subsequent, Mapping) or subsequent.get("outcome") != "failed":
                    return {
                        **summary, "terminal_state": "blocked", "last_rung": 4,
                        "human_action_needed": False, "rungs": entered,
                        "next_action": "record one subsequent failed implementer attempt before authorization",
                    }
                entered.append(_emit(root, packet, 4, "failed", _refs(packet, subsequent)))
                current = 5
                break
            if review_errors:
                outcome = "failed"
        if outcome == "passed" and not _verified_done(rung_result):
            raise LadderError("a passed rung requires the ordinary evidence gate and fresh verifier")
        entered.append(_emit(root, packet, current, outcome, _refs(packet, rung_result)))
        if _verified_done(rung_result):
            return {
                **summary, "terminal_state": "done", "last_rung": current,
                "human_action_needed": False, "rungs": entered,
                "lifecycle_action": "parent must apply the ordinary fresh-main done path",
            }
        if outcome not in ESCALATING_OUTCOMES:
            return {
                **summary, "terminal_state": "blocked", "last_rung": current,
                "human_action_needed": False, "rungs": entered,
                "next_action": build_worker_brief(packet, rung=current),
            }
        current += 1

    entered.append(_emit(root, packet, 5, "authorization_required", _refs(packet, {})))
    return {
        **summary, "terminal_state": "blocked", "last_rung": 5,
        "human_action_needed": True, "rungs": entered,
        "next_action": "ask the user to authorize the recorded drive-to-done proposal",
    }


def _load_results(path: Path | None) -> dict[int, Mapping[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise LadderError("results file must contain an object keyed by rung")
    if not all(isinstance(value, dict) for value in payload.values()):
        raise LadderError("each rung result must be an object")
    return {int(key): value for key, value in payload.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_file", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--to-done", action="store_true", required=True)
    parser.add_argument("--from-rung", type=int, choices=(2, 3, 4))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--results", type=Path, help="recorded worker/verifier evidence keyed by rung")
    args = parser.parse_args(argv)
    result = drive_to_done(
        args.spec_file, args.root, args.run_id, from_rung=args.from_rung,
        dry_run=args.dry_run, results=_load_results(args.results),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
