#!/usr/bin/env python3
"""Evidence-backed, deterministic unblock controller (SPEC-185).

The controller deliberately packages and records an unblock attempt; it never
selects remediation or dispatches a worker.  All evidence references are
project-relative and SHA-256 pinned so a packet cannot be reused after its
blocker evidence changes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from lifecycle import BLOCKER_CLASSES, transition_allowed, validate_blocked
from loop_events import open_run_log
from spec_frontmatter import is_nfr_family, parse_spec_file, write_spec_frontmatter
from status_store import StatusStore

LIFECYCLE_TO_METRIC_BLOCKER = {
    "technical_infeasibility": "implementation",
    "safety_constraint": "unknown",
    "evidence_unavailable": "evidence_gap",
    "critical_external_constraint": "external_input",
    "unknown_critical_failure": "unknown",
}
SAFE_CLASSES = {"technical_infeasibility", "evidence_unavailable"}
SKIP_CLASSES = {"safety_constraint", "critical_external_constraint"}
OUTCOMES = {"succeeded", "failed", "skipped"}
CONFIDENCE = {"demonstrated", "supported", "hypothesis", "not_established"}


class UnblockError(ValueError):
    """A closed gate or invalid attempt contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _relative(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise UnblockError("evidence path must be project-relative") from exc
    return path


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _attempts_dir(root: Path) -> Path:
    return root / "knowledge" / "attempts"


def _load_attempts(root: Path, spec_id: str) -> list[dict[str, Any]]:
    attempts = []
    for path in sorted(_attempts_dir(root).glob("*.md")) if _attempts_dir(root).exists() else []:
        try:
            parsed = parse_spec_file(path).frontmatter
        except Exception:
            continue
        if parsed.get("spec_id") == spec_id and parsed.get("kind") == "unblock_attempt":
            attempts.append(dict(parsed))
    return attempts


def prepare(spec_file: Path, project_root: Path, run_id: str, *, retry_override: bool = False) -> dict[str, Any]:
    """Validate a blocked spec and return a pinned packet without mutating it."""
    spec_file, project_root = Path(spec_file), Path(project_root)
    project_root = project_root.resolve()
    if not spec_file.is_absolute():
        spec_file = project_root / spec_file
    spec_file = spec_file.resolve()
    parsed = parse_spec_file(spec_file)
    fm = parsed.frontmatter
    if is_nfr_family(fm) or str(fm.get("id", "")).startswith("EVAL-"):
        raise UnblockError("NFR-family and eval fixtures cannot be unblocked")
    if fm.get("status") != "blocked":
        raise UnblockError("only currently blocked specs can be prepared")
    errors = validate_blocked(fm)
    if errors:
        raise UnblockError("; ".join(errors))
    blocker_class = str(fm["blocker_class"])
    if blocker_class not in LIFECYCLE_TO_METRIC_BLOCKER:
        raise UnblockError("unmapped lifecycle blocker class")
    evidence_ref = str(fm["blocker_evidence"])
    evidence_path = _relative(project_root, evidence_ref)
    if not evidence_path.is_file():
        raise UnblockError("actionable blocker evidence is missing or unverifiable")
    evidence_hash = _hash(evidence_path)
    fingerprint = hashlib.sha256(json.dumps({
        "spec_id": fm["id"], "class": blocker_class, "reason": fm["block_reason"],
        "since": fm["blocked_since"], "evidence": evidence_ref, "sha256": evidence_hash,
    }, sort_keys=True).encode()).hexdigest()
    prior = _load_attempts(project_root, str(fm["id"]))
    if not retry_override and any(a.get("fingerprint") == fingerprint and a.get("automatic") for a in prior):
        raise UnblockError("automatic attempt already recorded for unchanged blocker fingerprint")
    eligibility = "eligible" if blocker_class in SAFE_CLASSES else "skipped"
    return {
        "schema_version": 1, "packet_id": f"{run_id}:{fm['id']}:{fingerprint[:12]}",
        "run_id": run_id, "spec_id": fm["id"], "spec_path": str(spec_file.relative_to(project_root)),
        "source_blocked_since": fm["blocked_since"], "blocker_class": blocker_class,
        "metric_blocker_class": LIFECYCLE_TO_METRIC_BLOCKER[blocker_class],
        "blocker_scope": fm["blocker_scope"], "fingerprint": fingerprint,
        "evidence": [{"path": evidence_ref, "sha256": evidence_hash}], "prior_attempts": prior,
        "eligibility": eligibility, "bounded_task": str(fm["unblock_condition"]),
        "guardrails": ["no scope expansion", "preserve original blocker evidence", "verify pinned evidence"],
        "verification_gate": "linked before/after evidence and explicit command result",
        "retry_override": bool(retry_override),
    }


def _validate_causal(outcome: str, causal: Mapping[str, Any], verification: Mapping[str, Any]) -> None:
    confidence = causal.get("confidence")
    if confidence not in CONFIDENCE:
        raise UnblockError("unknown causal confidence")
    before = verification.get("before_evidence")
    after = verification.get("after_evidence")
    if confidence in {"demonstrated", "supported"} and not (before and after):
        raise UnblockError("demonstrated/supported cause requires before and after evidence")
    if outcome == "succeeded" and not verification.get("passed"):
        raise UnblockError("successful attempt requires a passing verification gate")


def record_attempt(packet: Mapping[str, Any], project_root: Path, *, outcome: str,
                   intervention: str, verification: Mapping[str, Any],
                   causal: Mapping[str, Any], automatic: bool = True,
                   reason: str = "") -> Path:
    """Persist one immutable, validated attempt artifact and return its path."""
    if outcome not in OUTCOMES:
        raise UnblockError("unknown attempt outcome")
    if packet.get("eligibility") == "skipped" and outcome != "skipped":
        raise UnblockError("unsafe/external blocker must be recorded as skipped")
    if outcome == "skipped" and not reason:
        raise UnblockError("skipped attempt requires a reason")
    _validate_causal(outcome, causal, verification)
    root = Path(project_root)
    evidence = packet.get("evidence", [])
    for item in evidence:
        path = _relative(root, str(item.get("path", "")))
        if not path.is_file() or _hash(path) != item.get("sha256"):
            raise UnblockError("pinned evidence changed; prepare again")
    attempt_id = f"{packet['packet_id']}-{outcome}"
    target = _attempts_dir(root) / f"{attempt_id.replace(':', '_')}.md"
    if target.exists():
        raise UnblockError("attempt artifact already exists and is immutable")
    data = {
        "kind": "unblock_attempt", "schema_version": 1, "attempt_id": attempt_id,
        "run_id": packet["run_id"], "spec_id": packet["spec_id"], "created_at": _now(),
        "source_blocked_since": packet["source_blocked_since"], "fingerprint": packet["fingerprint"],
        "blocker_class": packet["blocker_class"], "metric_blocker_class": packet["metric_blocker_class"],
        "outcome": outcome, "automatic": bool(automatic), "intervention": intervention,
        "reason": reason, "evidence": list(evidence), "verification": dict(verification),
        "causal": dict(causal),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True) + "---\n\n# Unblock attempt\n", encoding="utf-8")
    open_run_log(root, str(packet["run_id"])).emit("unblock_attempt_recorded", packet["spec_id"], attempt_id=attempt_id, outcome=outcome)
    return target


def finalize(packet: Mapping[str, Any], attempt_path: Path, project_root: Path) -> str:
    """Apply only evidence-backed ``blocked -> ready`` recovery; otherwise retain blocked."""
    root = Path(project_root)
    attempt = parse_spec_file(Path(attempt_path)).frontmatter
    if attempt.get("fingerprint") != packet.get("fingerprint"):
        raise UnblockError("attempt does not belong to packet")
    spec_path = _relative(root, str(packet["spec_path"]))
    if attempt.get("outcome") != "succeeded":
        return "blocked"
    if not attempt.get("verification", {}).get("passed"):
        raise UnblockError("cannot finalize without passing verification")
    if not transition_allowed("blocked", "ready"):
        raise UnblockError("lifecycle rejects blocked -> ready")
    def mutate(fm: dict[str, Any]) -> dict[str, Any]:
        if fm.get("status") not in {"blocked", "ready"} or fm.get("blocked_since") != packet.get("source_blocked_since"):
            raise UnblockError("spec blocker changed; prepare again")
        fm["status"] = "ready"
        fm.setdefault("unblock_history", []).append({"attempt": attempt["attempt_id"], "at": _now()})
        return fm
    current = parse_spec_file(spec_path).frontmatter
    if current.get("status") != "blocked" or current.get("blocked_since") != packet.get("source_blocked_since"):
        raise UnblockError("spec blocker changed; prepare again")
    try:
        StatusStore.for_specs_dir(spec_path.parent).transition_commit_backed(
            spec_path, "ready", run_id=str(packet["run_id"]), source="coordinator-unblock",
            note=f"unblock attempt {attempt['attempt_id']}",
        )
    except Exception as exc:
        raise UnblockError(f"durable unblock transition failed: {exc}") from exc
    write_spec_frontmatter(spec_path, mutate)
    open_run_log(root, str(packet["run_id"])).emit("spec_unblocked", packet["spec_id"], attempt_id=attempt["attempt_id"], transition="blocked->ready")
    return "ready"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare",))
    parser.add_argument("spec_file", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run-id", required=True)
    ns = parser.parse_args()
    print(json.dumps(prepare(ns.spec_file, ns.root, ns.run_id), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
