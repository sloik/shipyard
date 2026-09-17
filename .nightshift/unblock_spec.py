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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

import scope_guard
from lifecycle import BLOCKER_CLASSES, MANUAL_TRIAGE_CLASSES, transition_allowed, validate_blocked
from loop_events import open_run_log
from spec_frontmatter import is_nfr_family, parse_spec_file, write_spec_frontmatter
from status_store import StatusStore

LIFECYCLE_TO_METRIC_BLOCKER = {
    "technical_infeasibility": "implementation",
    "safety_constraint": "unknown",
    "evidence_unavailable": "evidence_gap",
    "critical_external_constraint": "external_input",
    "unknown_critical_failure": "unknown",
    # SPEC-300-002 R3/R8: mirrors record_metrics.BLOCKER_CLASS_ENUM's
    # `scope_violation` so a scope-blocked spec's packet carries the same
    # metric class as its terminal commit trailer.
    "scope_violation": "scope_violation",
}
SAFE_CLASSES = {"technical_infeasibility", "evidence_unavailable"}
SKIP_CLASSES = {"safety_constraint", "critical_external_constraint"}
# SPEC-300-002 R2/R8: never auto-eligible via SAFE_CLASSES -- a scope
# violation only becomes eligible once every offending path named in
# `block_reason` is covered by a `## Scope Amendments` row on main
# (see `_scope_amendments_cover_block_reason`), never by class membership
# alone. This is deliberately its own set, not folded into SKIP_CLASSES,
# because SKIP_CLASSES has no path-by-path re-check: it is permanently
# skipped, while scope_violation is conditionally skipped.
SCOPE_VIOLATION_CLASS = "scope_violation"
# SPEC-355: the top-level blocker fields `finalize()` relocates into
# `unblock_history[-1].resolved_blocker` on a successful `blocked -> ready`
# transition. Shared with `validate_specs.py`'s mechanical check so the two
# never drift on which fields count as "live blocker state".
RESOLVED_BLOCKER_FIELDS = (
    "blocker_class",
    "block_reason",
    "blocked_since",
    "unblock_condition",
    "blocker_scope",
    "blocker_evidence",
)
OUTCOMES = {"succeeded", "failed", "skipped"}
CONFIDENCE = {"demonstrated", "supported", "hypothesis", "not_established"}
# SPEC-351: a distinct eligibility for a spec/AC pair whose independent
# verification has already failed on the same AC(s) 2+ times across this
# spec's own recorded attempts plus its immediate parent's (SPEC-235's
# audit: SPEC-235-001 failed independent verification 3-4 times, always
# citing the same ACs). This is never derived from SAFE_CLASSES/SKIP_CLASSES
# membership -- it only ever narrows an otherwise-"eligible" packet, so a
# spec/AC combination that has not repeated sees no behavior change (R5).
AC_REVIEW_ELIGIBILITY = "eligible-for-ac-review"
# SPEC-300-002: the block_reason shape check 6 writes for a scope violation
# (SKILL.md "Step 6 evidence gate — check 6"), one entry per offending path:
# "<repo-relative-path> (<scope_guard reason code>)", comma-separated.
_SCOPE_BLOCK_REASON_ENTRY_RE = re.compile(r"([^\s,()][^,()]*?)\s*\(([a-z_]+)\)")
_SCOPE_AMENDMENTS_HEADING_RE = re.compile(
    r"^## Scope Amendments\s*$([\s\S]*?)(?=^## |\Z)", re.MULTILINE
)


def _scope_amendment_globs(spec_text: str) -> list[str]:
    """Return every non-empty `Path or glob` cell from `## Scope Amendments`.

    Mirrors `validate_specs.py`'s row-shape parsing (SPEC-300-001 R7) -- same
    heading regex, same "skip header/separator/short rows" rules -- but
    extracts the path column instead of validating `Approved by`. A row
    lacking a human-approved `Approved by` cell was already rejected by
    `validate_specs.py` at commit time, so any row reachable here on main is
    trusted.
    """
    match = _SCOPE_AMENDMENTS_HEADING_RE.search(spec_text)
    if not match:
        return []
    globs: list[str] = []
    for line in match.group(1).split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if re.match(r"^\|[\s:|-]*\|?$", stripped):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not any(cells):
            continue
        if cells[0] == "Date":
            continue
        if len(cells) < 5 or not cells[1]:
            continue
        globs.append(cells[1])
    return globs


def _scope_amendments_cover_block_reason(block_reason: str, spec_text: str) -> bool:
    """True only if every offending path in `block_reason` has an amendment.

    Fails closed: an unparsable `block_reason` (no `path (reason_code)`
    entries found at all) never reports coverage, since there is nothing to
    confirm was actually approved.
    """
    offenders = [m.group(1).strip() for m in _SCOPE_BLOCK_REASON_ENTRY_RE.finditer(block_reason)]
    if not offenders:
        return False
    globs = _scope_amendment_globs(spec_text)
    if not globs:
        return False
    return all(any(scope_guard._glob_match(g, path) for g in globs) for path in offenders)


class UnblockError(ValueError):
    """A closed gate or invalid attempt contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalized_blocked_since(value: object) -> str:
    """Return the stable text identity used for a blocker timestamp.

    PyYAML resolves unquoted ISO timestamps to ``datetime`` while quoted values
    remain strings.  The controller must treat those equivalent spellings as the
    same blocker so packets are JSON-serializable and can round-trip through
    ``finalize``.
    """
    if isinstance(value, datetime):
        instant = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


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


# SPEC-351 R1/R2: extract AC IDs cited as *failing* independent verification
# from an attempt's free-text `reason` / `verification.command_result`. Both
# fields are hand-written prose (see knowledge/attempts/*SPEC-235*, e.g.
# "verdict fail on AC1, AC2, AC5, AC10, AC11 with AC13 unverifiable"), so the
# extraction is deliberately narrow: an AC-ID list must begin immediately
# (modulo an "on"/"for"/":" connector) after a "fail"/"failed"/"fails" token --
# not merely appear anywhere in the same comma-delimited run-on sentence.
# BUG (found in independent verification, fixed pre-merge): the original
# `[^.:]*` clause pattern had no requirement that the captured AC IDs
# immediately follow the fail token, so free text listing an unrelated AC
# later in the same clause -- e.g. "AC5 failed, AC6 now passes" -- misattributed
# the failure to AC6 (the passing AC) instead of AC5 (the actually-failing one)
# or picked up both. The tightened pattern only matches a comma/"and"-joined
# run of AC-ID tokens starting right after the fail token (plus its optional
# connector), so a clause that doesn't lead with an AC-ID list there extracts
# nothing rather than misattributing -- still with any "with ... unverifiable"
# aside stripped first, so a still-unverifiable AC (SPEC-235's "AC13
# unverifiable") is never miscounted as a repeat.
_FAILURE_CLAUSE_RE = re.compile(
    r"fail(?:ed|s)?\b\s*(?:(?:on|for)\s+|:\s*)?"
    r"((?:AC[1-9][0-9]*(?:\s*,\s*|\s+and\s+)?)+)",
    re.IGNORECASE,
)
_UNVERIFIABLE_ASIDE_RE = re.compile(r"\bwith\b.*?\bunverifiable\b", re.IGNORECASE)
_AC_ID_RE = re.compile(r"\bAC[1-9][0-9]*\b")

# BUG (found in independent re-verification, fixed pre-merge): the clause
# pattern above still misattributed when an "and"-joined (not comma-joined)
# AC-ID immediately precedes a positive verdict for THAT SAME AC in the same
# clause -- e.g. "failed AC5 and AC6 now passes" -- because "and AC6" is a
# legitimate list continuation (also needed for "fails for AC3 and AC4") and
# the clause pattern has no way to tell the two shapes apart from the fail
# token alone. Fixed with a second, independent pass: pair each individual
# AC-ID occurrence in the full text with the text immediately following it
# (up to the next AC-ID token or a sentence break) and veto that specific
# AC-ID -- not the whole clause -- if that gap states a positive outcome for
# it. This is symmetric with an "and"-joined *failure* list, e.g. "failed AC5
# and AC6" with no trailing veto still cites both.
_AC_WITH_TRAILING_RE = re.compile(
    r"\bAC([1-9][0-9]*)\b((?:(?!\bAC[1-9][0-9]*\b)[^.:])*)", re.IGNORECASE
)
_POSITIVE_VERB_RE = re.compile(
    r"\b(?:now\s+)?(?:passes|passing|pass\b|resolved|repaired|"
    r"is\s+fine|remains\s+fine|is\s+ok(?:ay)?|is\s+clear)",
    re.IGNORECASE,
)


def _positive_veto_ac_ids(text: str) -> set[str]:
    vetoed: set[str] = set()
    for match in _AC_WITH_TRAILING_RE.finditer(text):
        if _POSITIVE_VERB_RE.search(match.group(2)):
            vetoed.add(f"AC{match.group(1)}")
    return vetoed


def _failure_cited_ac_ids(text: object) -> set[str]:
    if not isinstance(text, str) or not text:
        return set()
    ac_ids: set[str] = set()
    for clause in _FAILURE_CLAUSE_RE.findall(text):
        clause = _UNVERIFIABLE_ASIDE_RE.sub("", clause)
        ac_ids.update(_AC_ID_RE.findall(clause))
    ac_ids -= _positive_veto_ac_ids(text)
    return ac_ids


def _repeated_failed_ac_ids(attempts: list[Mapping[str, Any]]) -> list[str]:
    """Return, sorted, the AC IDs cited as failed on 2+ separate attempts.

    Only ``outcome: failed`` attempts count -- a ``succeeded`` attempt's
    "AC1-AC9 pass" summary must never contribute to a repeat count.
    """
    counts: dict[str, int] = {}
    for attempt in attempts:
        if attempt.get("outcome") != "failed":
            continue
        verification = attempt.get("verification")
        cited = _failure_cited_ac_ids(attempt.get("reason"))
        if isinstance(verification, Mapping):
            cited |= _failure_cited_ac_ids(verification.get("command_result"))
        for ac_id in cited:
            counts[ac_id] = counts.get(ac_id, 0) + 1
    return sorted(ac_id for ac_id, count in counts.items() if count >= 2)


def _lineage_attempts(root: Path, fm: Mapping[str, Any], own_attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pool a spec's own attempts with its declared parent's (SPEC-351 R2).

    Lineage is resolved from the frontmatter ``parent`` field only (e.g.
    SPEC-235-001's ``parent: SPEC-235``) -- never inferred from the
    ``SPEC-NNN-MMM`` ID shape alone.
    """
    lineage = list(own_attempts)
    parent_id = fm.get("parent")
    if isinstance(parent_id, str) and parent_id.strip():
        lineage += _load_attempts(root, parent_id.strip())
    return lineage


def prepare(spec_file: Path, project_root: Path, run_id: str, *, retry_override: bool = False,
            allow_escalation: bool = False) -> dict[str, Any]:
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
    blocked_since = _normalized_blocked_since(fm["blocked_since"])
    fingerprint = hashlib.sha256(json.dumps({
        "spec_id": fm["id"], "class": blocker_class, "reason": fm["block_reason"],
        "since": blocked_since, "evidence": evidence_ref, "sha256": evidence_hash,
    }, sort_keys=True).encode()).hexdigest()
    prior = _load_attempts(project_root, str(fm["id"]))
    if not retry_override and any(a.get("fingerprint") == fingerprint and a.get("automatic") for a in prior):
        raise UnblockError("automatic attempt already recorded for unchanged blocker fingerprint")
    if blocker_class == SCOPE_VIOLATION_CLASS:
        # R8: never eligible on class membership alone -- only once every
        # offending path named in `block_reason` is covered by a `## Scope
        # Amendments` row on main (a human decision), can rung 1 run.
        eligibility = (
            "eligible"
            if _scope_amendments_cover_block_reason(str(fm["block_reason"]), parsed.body)
            else "skipped"
        )
    else:
        eligibility = "eligible" if blocker_class in SAFE_CLASSES else "skipped"
    # SPEC-351 R2/R3/R5: a spec/AC combination that has already failed
    # independent verification 2+ times (counting the declared parent's
    # attempts too) is routed to AC review instead of another blind
    # recovery attempt -- but only where a worker would otherwise have been
    # eligible to run. This never widens a "skipped" (human-required)
    # packet, so SKIP_CLASSES/uncovered scope_violation behavior is
    # unchanged, and a spec/AC pair that has not repeated sees no change.
    repeated_ac_ids = _repeated_failed_ac_ids(_lineage_attempts(project_root, fm, prior))
    if repeated_ac_ids and eligibility == "eligible":
        eligibility = AC_REVIEW_ELIGIBILITY
    # SPEC-350 R3: `unknown_critical_failure` (and any future MANUAL_TRIAGE_CLASSES
    # member) is never safe to auto-retry, so it always lands on `eligibility:
    # "skipped"` above like SKIP_CLASSES -- but unlike an ordinary skip it is not
    # a dead end. `triage_required` and `eligibility_detail` are additive fields:
    # `eligibility` itself is read for equality elsewhere (`record_attempt`,
    # `prepare`'s own `allow_escalation` check, `unblock_ladder.drive_to_done`),
    # so this never overwrites a repeated-AC "eligible-for-ac-review" value --
    # manual-triage classes are never in SAFE_CLASSES, so they can't reach that
    # branch above in the first place.
    triage_required = blocker_class in MANUAL_TRIAGE_CLASSES
    eligibility_detail = (
        f"{eligibility} (human triage required)" if triage_required else eligibility
    )
    packet = {
        "schema_version": 1, "packet_id": f"{run_id}:{fm['id']}:{fingerprint[:12]}",
        "run_id": run_id, "spec_id": fm["id"], "spec_path": str(spec_file.relative_to(project_root)),
        "source_blocked_since": blocked_since, "blocker_class": blocker_class,
        "metric_blocker_class": LIFECYCLE_TO_METRIC_BLOCKER[blocker_class],
        "block_reason": str(fm["block_reason"]),
        "blocker_scope": fm["blocker_scope"], "fingerprint": fingerprint,
        "evidence": [{"path": evidence_ref, "sha256": evidence_hash}], "prior_attempts": prior,
        "eligibility": eligibility, "eligibility_detail": eligibility_detail,
        "triage_required": triage_required, "repeated_ac_ids": repeated_ac_ids,
        "bounded_task": str(fm["unblock_condition"]),
        "guardrails": ["no scope expansion", "preserve original blocker evidence", "verify pinned evidence"],
        "verification_gate": "linked before/after evidence and explicit command result",
        "retry_override": bool(retry_override),
    }
    if allow_escalation and eligibility == "skipped":
        packet["escalate"] = True
    return packet


def triage(spec_file: Path, project_root: Path, run_id: str = "triage") -> dict[str, Any]:
    """Read-only manual-triage packet for a blocker class with no automated path.

    Distinct from the automated rung-1 recovery ladder (`SAFE_CLASSES`) and from
    the deliberately-permanent `SKIP_CLASSES`: a class in `MANUAL_TRIAGE_CLASSES`
    (currently just ``unknown_critical_failure``) is never auto-retried, but it
    must not silently accumulate in `skipped` forever either (SPEC-350 R2). This
    reuses `prepare()`'s validation and pinned-evidence packet unchanged --
    `record_attempt`/`finalize` remain the only mutation paths -- and adds the
    explicit next action a human/coordinator should take.
    """
    packet = prepare(spec_file, project_root, run_id)
    if not packet["triage_required"]:
        raise UnblockError(
            f"triage is scoped to {sorted(MANUAL_TRIAGE_CLASSES)}; "
            f"blocker_class {packet['blocker_class']!r} uses prepare()'s ordinary "
            "eligibility path"
        )
    packet["next_action"] = (
        "human triage required: review blocker_evidence and block_reason below, "
        "then record an explicit decision -- either record_attempt(outcome="
        "\"skipped\", reason=...) to keep it blocked with a documented rationale, "
        "or, if a human-verified fix exists, an operator-resolved "
        "record_attempt(outcome=\"succeeded\", automatic=False, "
        "authorization={...}) per SPEC-276."
    )
    return packet


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


def _validate_authorization(authorization: Mapping[str, Any] | None) -> dict[str, Any]:
    """Require a non-empty human authorization record for an operator-resolved success."""
    if not isinstance(authorization, Mapping):
        raise UnblockError("operator-resolved success requires an authorization record")
    authorized_by = str(authorization.get("authorized_by", "")).strip()
    statement = str(authorization.get("statement", "")).strip()
    if not authorized_by or not statement:
        raise UnblockError("authorization requires non-empty authorized_by and statement")
    return {"authorized_by": authorized_by, "statement": statement}


def record_attempt(packet: Mapping[str, Any], project_root: Path, *, outcome: str,
                   intervention: str, verification: Mapping[str, Any],
                   causal: Mapping[str, Any], automatic: bool = True,
                   reason: str = "", authorization: Mapping[str, Any] | None = None) -> Path:
    """Persist one immutable, validated attempt artifact and return its path."""
    if outcome not in OUTCOMES:
        raise UnblockError("unknown attempt outcome")
    authorization_record: dict[str, Any] = {}
    if packet.get("eligibility") == "skipped" and outcome != "skipped":
        # The controller never dispatches or self-certifies an unsafe/external class: an
        # automatic attempt is refused unconditionally. A human operator recording a
        # non-automatic, evidence-backed success with an explicit authorization record is
        # the one narrow exception (SPEC-276) -- it does not widen automatic dispatch.
        if automatic or outcome != "succeeded":
            raise UnblockError("unsafe/external blocker must be recorded as skipped")
        authorization_record = _validate_authorization(authorization)
    if packet.get("eligibility") == AC_REVIEW_ELIGIBILITY and automatic and outcome != "skipped":
        # SPEC-351 R3: never dispatch a third blind automatic recovery attempt on a
        # spec/AC combination that already failed independent verification 2+ times --
        # the controller must record this as skipped (routing to AC review) instead.
        raise UnblockError("repeated same-AC failure requires AC review, not another automatic attempt")
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
        "causal": dict(causal), "authorization": authorization_record,
        # SPEC-351 R4: durably record the repeat-failure detection outcome using the
        # same immutable attempt-artifact mechanism as every other unblock_spec.py
        # result, so a later attempt (or a human) can see "this AC has failed
        # verification twice before" without re-reading every prior attempt by hand.
        "eligibility": packet.get("eligibility"),
        "repeated_ac_ids": list(packet.get("repeated_ac_ids", [])),
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
        if fm.get("status") not in {"blocked", "ready"} or _normalized_blocked_since(fm.get("blocked_since")) != packet.get("source_blocked_since"):
            raise UnblockError("spec blocker changed; prepare again")
        fm["status"] = "ready"
        # SPEC-355: relocate the resolved blocker's fields into this history
        # entry rather than leaving them live at the top level -- a spec that
        # has moved past `blocked` must never again read as though it still
        # is. The reason/evidence/etc. are preserved (not deleted) so a later
        # reader or knowledge-base pass can still find "how this was fixed".
        resolved_blocker = {
            key: fm.pop(key)
            for key in RESOLVED_BLOCKER_FIELDS
            if key in fm
        }
        history_entry: dict[str, Any] = {"attempt": attempt["attempt_id"], "at": _now()}
        if resolved_blocker:
            history_entry["resolved_blocker"] = resolved_blocker
        fm.setdefault("unblock_history", []).append(history_entry)
        return fm
    current = parse_spec_file(spec_path).frontmatter
    if current.get("status") != "blocked" or _normalized_blocked_since(current.get("blocked_since")) != packet.get("source_blocked_since"):
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
    parser.add_argument("operation", choices=("prepare", "triage"))
    parser.add_argument("spec_file", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--allow-escalation", action="store_true")
    ns = parser.parse_args()
    if ns.operation == "triage":
        print(json.dumps(triage(ns.spec_file, ns.root, ns.run_id), indent=2))
    else:
        print(json.dumps(prepare(
            ns.spec_file, ns.root, ns.run_id, allow_escalation=ns.allow_escalation,
        ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
