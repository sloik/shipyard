#!/usr/bin/env python3
"""Evidence-backed, deterministic unblock controller (SPEC-185).

The controller deliberately packages and records an unblock attempt; it never
selects remediation or dispatches a worker.  All evidence references are
project-relative and SHA-256 pinned so a packet cannot be reused after its
blocker evidence changes.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, NamedTuple

import yaml

import scope_guard
import managed_payload_provenance as mpi
from lifecycle import BLOCKER_CLASSES, MANUAL_TRIAGE_CLASSES, transition_allowed, validate_blocked
from loop_events import open_run_log
from spec_frontmatter import is_nfr_family, parse_spec_file, write_spec_frontmatter
from status_store import StatusStore, default_db_path_for_specs_dir, read_durable_states_readonly

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
    "invalid_run_abandonment",
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
# (guides/run-7.md "Step 6 evidence gate — check 6"), one entry per offending path:
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


RETRY_CLOSED = "automatic attempt already recorded for unchanged blocker fingerprint"
FINALIZE_ONLY = ("a succeeded outcome is already recorded for this blocker fingerprint; "
                 "only finalize is permitted")
NEW_RUN_REQUIRED = ("this run already recorded an outcome on this blocker fingerprint; "
                    "retry_override requires a new run identity")
NOT_ISSUED = "packet was not durably issued for this run and blocker fingerprint"
SUPERSEDED = "packet was superseded by a later durable issuance on this blocker fingerprint"
OTHER_FINGERPRINT = "packet was issued for another blocker fingerprint"
NO_OWN_OUTCOME = "finalize requires an outcome recorded by this packet"
# Named fail-closed reasons for a durable ledger entry whose attempt evidence is not intact.
ATTEMPT_EVIDENCE_MISSING = "NS-UNBLOCK-ATTEMPT-EVIDENCE-MISSING: ledger-recorded attempt evidence is missing"
ATTEMPT_EVIDENCE_UNSAFE = ("NS-UNBLOCK-ATTEMPT-EVIDENCE-UNSAFE: ledger-recorded attempt evidence is not a safe "
                           "single-link local file")
ATTEMPT_EVIDENCE_MISMATCH = ("NS-UNBLOCK-ATTEMPT-EVIDENCE-MISMATCH: ledger-recorded attempt evidence does not "
                             "match its durable digest")
ATTEMPT_LEDGER_ORPHANED = ("NS-UNBLOCK-ATTEMPT-LEDGER-ORPHANED: ledger-recorded attempt is not bound to a durable "
                           "packet issuance on its blocker fingerprint")
ATTEMPT_PHASES = ("prepare", "record", "finalize")
ISSUANCE_SOURCE = "invalid-run-abandonment-packet"
ATTEMPT_LEDGER_SOURCE = "invalid-run-abandonment-attempt"


class Decision(NamedTuple):
    allow: bool
    reason: str


def automatic_attempt_decision(ledger, fingerprint: str, packet: Mapping[str, Any], run_id: str,
                               retry_override: bool, phase: str, *, issuance: Mapping[str, Any],
                               in_flight: str | None = None) -> Decision:
    """Automatic recovery attempts are keyed by the current blocker fingerprint. This rule governs
    every automatic attempt, administrative and ordinary alike. Retry state is the durable
    status-store ledger alone: durably issued packets and recorded attempt outcomes with their
    digests, on both routes. An attempt file is evidence bound to its ledger digest. A ledger
    entry whose file is missing, unsafe, corrupted, digest-mismatched or not bound to a durable
    issuance fails closed with a named reason: it never reopens the
    fingerprint, never counts as no outcome and never permits a further automatic attempt. A
    file without a ledger entry is not an outcome. Any completed outcome (failed, skipped or
    succeeded) recorded in the ledger on the current fingerprint by any run closes that
    fingerprint to further automatic attempts; after a succeeded outcome only finalize is
    permitted. `retry_override` (human) is the only way to open a closed fingerprint. The sole
    exemption is a crash replay: the same run, on the same fingerprint, presenting the same
    durably issued packet, with no outcome yet recorded in the ledger for that packet; it may
    record exactly one outcome. A succeeded-but-unfinalized run may finalize idempotently and
    may not record again; an ordinary run whose own automatic succeeded attempt is on file may
    re-prepare finalize-only (the same packet, which can only finalize). A packet is bound to the run and fingerprint for which prepare durably
    issued it; a packet copied to another run, issued for another fingerprint, or superseded is
    refused at record_attempt.

    This is the single implementation of that rule. Administrative ``prepare``,
    ``record_attempt`` and the packet revalidation that runs before every administrative
    mutation call it directly; the ordinary ``prepare``, ``record_attempt`` and ``finalize``
    call it through ``_ordinary_decision``. Nothing else decides whether an automatic attempt
    may proceed.

    ``ledger`` is every durable attempt-ledger entry of the spec as ``_attempt_ledger``
    returns it: the recorded ``attempt_id``, ``packet_id``, ``run_id``, ``fingerprint`` and
    ``outcome``, plus ``integrity`` (empty when the bound evidence file is intact, otherwise the
    named fail-closed reason). ``in_flight`` is the attempt id the current ``record_attempt``
    call itself is writing, passed only by the revalidation that runs between that call's own
    writes; its entry is integrity-checked like any other but is not counted as a prior
    outcome there. The entry check of ``record_attempt`` passes none, so a completed outcome
    is never recorded again.
    ``packet`` is the presented packet (at prepare: the packet about to be issued). ``phase``
    is one of ``prepare``, ``record`` or ``finalize``. ``issuance`` is
    ``{"record": <durable issuance of packet["issuance_id"]> | None, "latest_issuance_id": ...}``;
    after prepare the override is honoured only as that durable issuance recorded it.
    """
    if phase not in ATTEMPT_PHASES:
        raise ValueError(f"unknown attempt phase {phase!r}")
    on_fingerprint = [entry for entry in ledger if entry.get("fingerprint") == fingerprint]
    for entry in ledger:
        # Integrity precedes every other outcome: an entry that cannot be bound to its
        # fingerprint (orphaned) or whose evidence is not intact fails closed.
        if entry.get("integrity") and (entry in on_fingerprint or entry.get("integrity") == ATTEMPT_LEDGER_ORPHANED):
            return Decision(False, str(entry["integrity"]))
    packet_id = str(packet.get("packet_id", ""))
    own_ids = {f"{packet_id}-{outcome}" for outcome in OUTCOMES}
    on_fingerprint = [entry for entry in on_fingerprint if entry.get("attempt_id") != in_flight]
    own = [entry for entry in on_fingerprint if entry.get("attempt_id") in own_ids]
    issued = issuance.get("record")
    override = bool(retry_override) if phase == "prepare" else bool(
        isinstance(issued, Mapping) and issued.get("retry_override") is True)
    if any(entry.get("outcome") == "succeeded" for entry in on_fingerprint):
        own_succeeded = any(entry.get("outcome") == "succeeded" for entry in own)
        if not own_succeeded or phase == "record" or (phase == "prepare" and retry_override):
            return Decision(False, FINALIZE_ONLY)
    elif on_fingerprint:
        if phase == "prepare":
            if not retry_override:
                return Decision(False, RETRY_CLOSED)
            if own:
                return Decision(False, NEW_RUN_REQUIRED)
        elif phase == "record" and (own or not override):
            return Decision(False, RETRY_CLOSED)
    if phase == "finalize" and not own:
        return Decision(False, NO_OWN_OUTCOME)
    if phase != "prepare":
        if packet.get("fingerprint") != fingerprint:
            return Decision(False, OTHER_FINGERPRINT)
        if (not isinstance(issued, Mapping) or issued.get("issuance_id") != packet.get("issuance_id")
                or issued.get("packet_id") != packet_id or issued.get("run_id") != run_id
                or packet.get("run_id") != run_id or issued.get("fingerprint") != fingerprint
                or issued.get("retry_override") is not bool(packet.get("retry_override"))
                or issued.get("invalid_run_abandonment") != packet.get("invalid_run_abandonment")):
            return Decision(False, NOT_ISSUED)
        if issuance.get("latest_issuance_id") != packet.get("issuance_id"):
            return Decision(False, SUPERSEDED)
    return Decision(True, "")


UNBOUND_ADMINISTRATIVE_PACKET = ("packet claims administrative recovery but is not bound to a durable "
                                 "administrative abandonment decision")
ADMINISTRATIVE_BLOCKER_NEEDS_ADMINISTRATIVE_PACKET = (
    "an administrative abandonment blocker is recovered only with its durably issued administrative packet")
REPEATED_AC_FAILURE = "repeated same-AC failure requires AC review, not another automatic attempt"
ADMINISTRATIVE_PACKET_KEYS = ("invalid_run_abandonment",)


def _is_administrative_packet(packet: Mapping[str, Any]) -> bool:
    """Route by the presented packet only; the administrative guard then verifies it durably.

    Administrative ``prepare`` stamps ``invalid_run_abandonment`` into the packet it durably
    issues. A packet carrying that key takes the administrative path, where the guard binds it
    to the durable decision and issuance ledger (a forged marker is refused). Ordinary
    ``prepare`` also stamps an ``issuance_id`` (SPEC-NS-KIT-109), so that key no longer routes:
    any packet without ``invalid_run_abandonment`` goes to the ordinary controller, which
    refuses an administrative blocker.
    """
    return any(key in packet for key in ADMINISTRATIVE_PACKET_KEYS)


def _is_administrative_blocker(spec_path: Path, frontmatter: Mapping[str, Any], spec_id: str) -> bool:
    """Read-only: the live blocker is an administrative abandonment (frontmatter or durable state)."""
    if frontmatter.get("invalid_run_abandonment") is not None:
        return True
    latest = read_durable_states_readonly(default_db_path_for_specs_dir(spec_path.parent), [spec_id]).get(spec_id)
    return bool(latest and latest.get("source") == "invalid-run-abandonment")


class _Route(NamedTuple):
    """The status-store row families of one controller route; the mechanism is shared."""
    name: str
    issuance_prefix: str
    issuance_source: str
    ledger_source: str
    intent_source: str
    attempt_prefix: str
    intent_prefix: str


ADMIN_ROUTE = _Route("administrative", "administrative-issuance-", ISSUANCE_SOURCE, ATTEMPT_LEDGER_SOURCE,
                     "invalid-run-abandonment-attempt-intent", "administrative-attempt-",
                     "administrative-attempt-intent-")
ORDINARY_ROUTE = _Route("ordinary", "ordinary-issuance-", "ordinary-unblock-packet", "ordinary-unblock-attempt",
                        "ordinary-unblock-attempt-intent", "ordinary-attempt-", "ordinary-attempt-intent-")
ATTEMPT_INTENT_SOURCE = ADMIN_ROUTE.intent_source
ADOPTION_SOURCE = "ordinary-unblock-adoption"
ADOPTION_KEY = "ordinary-legacy-adoption"


def _issuance_key(fingerprint: str, sequence: int, route: _Route = ADMIN_ROUTE) -> str:
    return f"{route.issuance_prefix}{fingerprint}-{sequence}"


def _issuances(store: StatusStore, spec_id: str, fingerprint: str, route: _Route = ADMIN_ROUTE) -> list[dict[str, Any]]:
    """Every durable packet issuance on this fingerprint, in issuance order."""
    issued, sequence = [], 1
    while True:
        row = store.get_terminal_decision(spec_id, _issuance_key(fingerprint, sequence, route))
        if row is None:
            return issued
        payload = row.get("payload") or {}
        if (row.get("source") != route.issuance_source
                or payload.get("issuance_id") != _issuance_key(fingerprint, sequence, route)
                or payload.get("fingerprint") != fingerprint):
            raise UnblockError("durable packet issuance ledger is inconsistent")
        issued.append(payload)
        sequence += 1


def _latest_issuance(store: StatusStore, spec_id: str, fingerprint: str,
                     route: _Route = ADMIN_ROUTE) -> tuple[dict[str, Any] | None, int]:
    """Return (latest durable issuance on this fingerprint, next sequence number)."""
    issued = _issuances(store, spec_id, fingerprint, route)
    return (issued[-1] if issued else None), len(issued) + 1


def _attempt_key(attempt_id: str, route: _Route = ADMIN_ROUTE) -> str:
    return route.attempt_prefix + hashlib.sha256(attempt_id.encode()).hexdigest()


def _administrative_attempt_key(attempt_id: str) -> str:
    return _attempt_key(attempt_id, ADMIN_ROUTE)


def _intent_key(attempt_id: str, route: _Route = ADMIN_ROUTE) -> str:
    """Ledger key of the durable write intent (stamp + digest) recorded before the attempt file.

    An intent is not an outcome; it only lets a crash replay of the same attempt rebuild the
    identical bytes from the ledger.
    """
    return route.intent_prefix + hashlib.sha256(attempt_id.encode()).hexdigest()


def _administrative_intent_key(attempt_id: str) -> str:
    return _intent_key(attempt_id, ADMIN_ROUTE)


def _attempt_ledger_payload(root: Path, target: Path, attempt: Mapping[str, Any], packet_id: str,
                            digest: str, route: _Route = ADMIN_ROUTE) -> dict[str, Any]:
    """The durable ledger record of one attempt outcome and its evidence digest."""
    payload = {"attempt_id": attempt["attempt_id"], "packet_id": packet_id, "run_id": attempt["run_id"],
               "fingerprint": attempt["fingerprint"], "outcome": attempt["outcome"],
               "attempt_path": str(target.relative_to(root)), "attempt_sha256": digest}
    if route.name == "administrative":
        payload["invalid_run_abandonment"] = attempt["invalid_run_abandonment"]
    else:
        payload["automatic"] = bool(attempt.get("automatic"))
    return payload


def _links_below(root: Path, path: Path) -> bool:
    """A symlink at or under the project root on the way to `path` (the root itself may be a link)."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(root.joinpath(*parts[:depth]).is_symlink() for depth in range(1, len(parts) + 1))


def _attempt_evidence_integrity(root: Path, recorded: Mapping[str, Any]) -> str:
    """Empty when the ledger-bound attempt file is intact; otherwise the named reason."""
    path = root / str(recorded.get("attempt_path"))
    if ".." in Path(str(recorded.get("attempt_path"))).parts or _links_below(root, path):
        return ATTEMPT_EVIDENCE_UNSAFE
    if not path.exists():
        return ATTEMPT_EVIDENCE_MISSING
    if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > mpi.MAX_ACCEPTANCE_BYTES:
        return ATTEMPT_EVIDENCE_UNSAFE
    if _hash(path) != recorded.get("attempt_sha256"):
        return ATTEMPT_EVIDENCE_MISMATCH
    try:
        attempt = parse_spec_file(path).frontmatter
    except Exception:
        return ATTEMPT_EVIDENCE_MISMATCH
    keys = ("attempt_id", "run_id", "fingerprint", "outcome", "invalid_run_abandonment")
    if any(attempt.get(key) != recorded.get(key) for key in keys):
        return ATTEMPT_EVIDENCE_MISMATCH
    if "automatic" in recorded and bool(attempt.get("automatic")) is not recorded["automatic"]:
        return ATTEMPT_EVIDENCE_MISMATCH
    return ""


def _attempt_ledger(root: Path, store: StatusStore, spec_id: str, route: _Route = ADMIN_ROUTE) -> list[dict[str, Any]]:
    """The durable attempt ledger of `spec_id` on one route -- the only retry state.

    Each entry carries the recorded outcome facts and ``integrity``: empty when its evidence
    file is intact and bound, otherwise the named fail-closed reason. Attempt files are never
    enumerated here; a file without a ledger entry is not an outcome. An ordinary entry adopted
    from a pre-ledger install (``legacy_adopted``) has no issuance and stands as its own; its
    file keeps whatever name it was recorded under.
    """
    entries = []
    issued_packets: dict[str, set[str]] = {}
    for row in store.list_terminal_decisions(spec_id, source=route.ledger_source):
        recorded = dict(row.get("payload") or {})
        attempt_id, fingerprint = recorded.get("attempt_id"), recorded.get("fingerprint")
        legacy = route.name == "ordinary" and recorded.get("legacy_adopted") is True
        orphaned = (not isinstance(attempt_id, str) or row.get("run_id") != _attempt_key(str(attempt_id), route)
                    or recorded.get("outcome") not in OUTCOMES)
        if not orphaned and legacy:
            orphaned = not isinstance(recorded.get("attempt_path"), str)
        elif not orphaned:
            orphaned = (not isinstance(fingerprint, str)
                        or attempt_id != f"{recorded.get('packet_id')}-{recorded.get('outcome')}"
                        or recorded.get("attempt_path")
                        != str((_attempts_dir(root) / f"{attempt_id.replace(':', '_')}.md").relative_to(root)))
        if not orphaned and not legacy:
            if fingerprint not in issued_packets:
                issued_packets[fingerprint] = {str(item.get("packet_id"))
                                               for item in _issuances(store, spec_id, fingerprint, route)}
            orphaned = recorded.get("packet_id") not in issued_packets[fingerprint]
        recorded["integrity"] = ATTEMPT_LEDGER_ORPHANED if orphaned else _attempt_evidence_integrity(root, recorded)
        entries.append(recorded)
    return entries


def _issuance_view(store: StatusStore, packet: Mapping[str, Any], fingerprint: str,
                   route: _Route = ADMIN_ROUTE) -> dict[str, Any]:
    """The durable issuance facts `automatic_attempt_decision` binds a presented packet to."""
    spec_id = str(packet.get("spec_id", ""))
    latest, _ = _latest_issuance(store, spec_id, fingerprint, route)
    issuance_id = packet.get("issuance_id")
    record = None
    if isinstance(issuance_id, str) and issuance_id.startswith(route.issuance_prefix):
        row = store.get_terminal_decision(spec_id, issuance_id)
        if row is not None and row.get("source") == route.issuance_source:
            record = row.get("payload")
    return {"record": record, "latest_issuance_id": (latest or {}).get("issuance_id")}


def _emit_integrity(root: Path, packet: Mapping[str, Any], reason: str, ledger, route: str) -> None:
    """SPEC-NS-KIT-109 R7: tell installs' run logs which ledger entry failed its integrity check."""
    run_id = str(packet.get("run_id", ""))
    if reason.startswith("NS-UNBLOCK-ATTEMPT-") and mpi.SAFE_ID.fullmatch(run_id):
        failed = next((e.get("attempt_id") for e in ledger if e.get("integrity") == reason), None)
        open_run_log(root, run_id).emit("unblock_ledger_integrity_failed", packet.get("spec_id"),
                                        reason=reason.split(":")[0], attempt_id=failed, route=route)


def _administrative_decision(root: Path, store: StatusStore, packet: Mapping[str, Any], fingerprint: str,
                             phase: str, *, retry_override: bool | None = None,
                             in_flight: str | None = None) -> Decision:
    """Apply `automatic_attempt_decision` to the durable ledger and issuance facts."""
    ledger = _attempt_ledger(Path(root), store, str(packet.get("spec_id", "")))
    decision = automatic_attempt_decision(
        ledger, fingerprint, packet, str(packet.get("run_id", "")),
        bool(packet.get("retry_override")) if retry_override is None else retry_override, phase,
        issuance=_issuance_view(store, packet, fingerprint), in_flight=in_flight)
    if not decision.allow:
        _emit_integrity(Path(root), packet, decision.reason, ledger, "administrative")
    return decision


def _own_automatic_success(attempts, packet_id: str, fingerprint: str) -> str | None:
    """The attempt id of this packet's own automatic `succeeded` attempt on the fingerprint."""
    attempt_id = f"{packet_id}-succeeded"
    return attempt_id if any(
        a.get("attempt_id") == attempt_id and a.get("automatic") and a.get("fingerprint") == fingerprint
        and a.get("outcome") == "succeeded" for a in attempts) else None


_REASON_NAMES = {value: name for name, value in (
    ("RETRY_CLOSED", RETRY_CLOSED), ("FINALIZE_ONLY", FINALIZE_ONLY), ("NEW_RUN_REQUIRED", NEW_RUN_REQUIRED),
    ("NOT_ISSUED", NOT_ISSUED), ("SUPERSEDED", SUPERSEDED), ("OTHER_FINGERPRINT", OTHER_FINGERPRINT),
    ("NO_OWN_OUTCOME", NO_OWN_OUTCOME),
    ("ADMINISTRATIVE_BLOCKER_NEEDS_ADMINISTRATIVE_PACKET", ADMINISTRATIVE_BLOCKER_NEEDS_ADMINISTRATIVE_PACKET),
    ("REPEATED_AC_FAILURE", REPEATED_AC_FAILURE),
    ("ATTEMPT_EVIDENCE_MISSING", ATTEMPT_EVIDENCE_MISSING), ("ATTEMPT_EVIDENCE_UNSAFE", ATTEMPT_EVIDENCE_UNSAFE),
    ("ATTEMPT_EVIDENCE_MISMATCH", ATTEMPT_EVIDENCE_MISMATCH), ("ATTEMPT_LEDGER_ORPHANED", ATTEMPT_LEDGER_ORPHANED))}


def _emit_refusal(root: Path, packet: Mapping[str, Any], phase: str, reason: str, **extra: Any) -> None:
    """BUG-NS-KIT-109 R4: tell installs' run logs which named reason refused an ordinary attempt."""
    run_id = str(packet.get("run_id", ""))
    if mpi.SAFE_ID.fullmatch(run_id):
        open_run_log(root, run_id).emit("unblock_decision_refused", packet.get("spec_id"), phase=phase,
                                        reason=_REASON_NAMES.get(reason, "OTHER"), detail=reason,
                                        route="ordinary", issuance_id=packet.get("issuance_id"), **extra)


def _ordinary_decision(root: Path, store: StatusStore, packet: Mapping[str, Any], fingerprint: str, phase: str,
                       *, in_flight: str | None = None) -> Decision:
    """Apply `automatic_attempt_decision` to the ordinary durable ledger and issuance facts.

    A non-automatic (human-authorized) outcome is not an automatic attempt and never closes a
    fingerprint; it stays in the ledger as evidence only.
    """
    packet_id = str(packet.get("packet_id", ""))
    full = _attempt_ledger(root, store, str(packet.get("spec_id", "")), ORDINARY_ROUTE)
    ledger = [entry for entry in full
              if entry.get("automatic") or str(entry.get("attempt_id", "")).startswith(packet_id + "-")]
    # A succeeded-but-unfinalized run re-prepares finalize-only: nothing is reopened, so the
    # override is moot there and the shared rule is applied without it.
    finalize_only = phase == "prepare" and _own_automatic_success(ledger, packet_id, fingerprint) is not None
    decision = automatic_attempt_decision(
        ledger, fingerprint, packet, str(packet.get("run_id", "")),
        bool(packet.get("retry_override")) and not finalize_only, phase,
        issuance=_issuance_view(store, packet, fingerprint, ORDINARY_ROUTE), in_flight=in_flight)
    if (decision.allow and phase == "prepare" and not packet.get("retry_override") and not finalize_only
            and any(entry.get("fingerprint") == fingerprint for entry in ledger)):
        # The ordinary controller never re-prepares: its caller finalizes the packet it holds.
        decision = Decision(False, RETRY_CLOSED)
    if not decision.allow:
        _emit_refusal(root, packet, phase, decision.reason)
        _emit_integrity(root, packet, decision.reason, ledger, "ordinary")
    return decision


def _issue_packet(store: StatusStore, packet: dict[str, Any], *, finalize_only: bool,
                  route: _Route = ADMIN_ROUTE, mint_unissued: bool = False) -> dict[str, Any]:
    """Durably issue `packet` (or reuse its current issuance); caller holds the controller lock.

    ``mint_unissued`` lets a finalize-only packet whose own success was adopted from a
    pre-ledger install (no issuance exists) receive one.
    """
    spec_id, fingerprint = str(packet["spec_id"]), str(packet["fingerprint"])
    latest, sequence = _latest_issuance(store, spec_id, fingerprint, route)
    if latest and latest.get("packet_id") == packet["packet_id"] and (
            finalize_only or latest.get("retry_override") is bool(packet["retry_override"])):
        return latest
    if finalize_only and not mint_unissued:
        raise UnblockError(NOT_ISSUED)
    payload = {"issuance_id": _issuance_key(fingerprint, sequence, route), "sequence": sequence,
               "packet_id": packet["packet_id"], "run_id": packet["run_id"], "fingerprint": fingerprint,
               "retry_override": bool(packet["retry_override"])}
    if route.name == "administrative":
        payload["invalid_run_abandonment"] = packet["invalid_run_abandonment"]
    row = store.record_terminal_decision(spec_id, payload["issuance_id"], "blocked",
                                         source=route.issuance_source, payload=payload)
    if row.get("source") != route.issuance_source or row.get("payload") != payload:
        raise UnblockError("contradictory durable packet issuance")
    return payload


def _install_root(root: Path) -> Path:
    """Resolve a caller's ``--root`` / ``project_root`` to the install directory (BUG-NS-KIT-142).

    Either spelling is accepted: the install directory itself (it has ``specs/``) or a project
    root that holds ``.nightshift/specs``. A directory with ``specs/`` wins, so a tree that has
    both (this repository's ``canonical/`` next to ``.nightshift/``) resolves to itself. Anything
    else raises before any file or directory is created.
    """
    root = Path(root)
    if (root / "specs").is_dir():
        return root
    if (root / ".nightshift" / "specs").is_dir():
        return root / ".nightshift"
    raise UnblockError(f"NS-UNBLOCK-ROOT-NOT-INSTALL: neither {root / 'specs'} nor "
                       f"{root / '.nightshift' / 'specs'} exists; pass the project root or the install directory")


@contextmanager
def _administrative_lock(root: Path):
    """Serialize this bounded parent controller, including identical replay."""
    directory = mpi._safe_artifact_root(root, mpi.ABANDONMENT_DIR)
    fd = os.open(directory / ".controller.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _decision_pointer(decision: Mapping[str, Any]) -> dict[str, str]:
    return {key: str(decision[key]) for key in ("artifact_path", "artifact_sha256", "invocation_id")}


def _administrative_pointer(root: Path, spec_id: str, fm: Mapping[str, Any],
                            packet: Mapping[str, Any] | None = None) -> dict[str, str] | None:
    offered = (packet or {}).get("invalid_run_abandonment") or fm.get("invalid_run_abandonment")
    latest = read_durable_states_readonly(default_db_path_for_specs_dir(root / "specs"), [spec_id]).get(spec_id)
    if offered is None and (not latest or latest.get("source") != "invalid-run-abandonment"):
        return None
    store = StatusStore.for_specs_dir(root / "specs")
    run_id = str(latest["run_id"]) if offered is None else f"abandonment-{offered.get('invocation_id', '')}" if isinstance(offered, dict) else ""
    terminal = store.get_terminal_decision(spec_id, run_id)
    if (not terminal or terminal.get("decision") != "blocked"
            or terminal.get("source") != "invalid-run-abandonment"):
        raise UnblockError("administrative blocker requires its original durable parent decision")
    pointer = (terminal.get("payload") or {}).get("invalid_run_abandonment")
    if not isinstance(pointer, dict) or (offered is not None and offered != pointer):
        raise UnblockError("administrative blocker identity changed")
    return pointer


def _revalidate_administrative(root: Path, spec_id: str, pointer: Mapping[str, str], provider) -> dict[str, Any]:
    if provider is None:
        raise UnblockError("administrative recovery requires the external parent abandonment provider")
    try:
        decision = mpi.verify_invalid_run_abandonment(root, spec_id=spec_id, abandonment_provider=provider)
        if _decision_pointer(decision) != dict(pointer):
            raise UnblockError("administrative packet no longer binds the immutable decision")
        path = root / decision["artifact_path"]
        if path.is_symlink() or _hash(path) != decision["artifact_sha256"]:
            raise UnblockError("administrative decision changed")
        return decision
    except mpi.MetadataError as exc:
        failures = mpi._quarantine_abandonment_rejection(root, spec_id, provider)
        raise UnblockError(mpi._with_quarantine_failures(str(exc), failures)) from exc


def abandon_invalid_run(spec_file: Path, project_root: Path, *, abandonment_provider) -> dict[str, Any]:
    """Parent-only rejected-old-run -> administrative blocked; never ready/accept.

    ``project_root`` may be the project root or the installed controller workspace (normally
    ``.nightshift``), exactly as for prepare/record_attempt/finalize; state is kept under the
    install directory.
    """
    root, spec_file = _install_root(Path(project_root)).resolve(), Path(spec_file).resolve()
    fm = parse_spec_file(spec_file).frontmatter
    spec_id = str(fm.get("id", ""))
    try:
        decision = mpi.verify_invalid_run_abandonment(root, spec_id=spec_id, abandonment_provider=abandonment_provider)
    except mpi.MetadataError as exc:
        failures = mpi._quarantine_abandonment_rejection(root, spec_id, abandonment_provider)
        if failures:
            raise mpi.MetadataError(mpi._with_quarantine_failures(str(exc), failures)) from exc
        raise
    if mpi._git_root(root) / decision["spec_path"] != spec_file or is_nfr_family(fm):
        raise UnblockError("administrative authority does not own this selected spec")
    with _administrative_lock(root):
        # Inside the same critical section as every administrative write below, so a
        # blocker written concurrently cannot be overwritten (no check-then-act gap).
        live_fm = parse_spec_file(spec_file).frontmatter
        live = live_fm.get("status") == "blocked" and any(live_fm.get(key) for key in ("block_reason", "blocker_class"))
        if live and live_fm.get("invalid_run_abandonment") != _decision_pointer(decision):
            retained = {item["path"] for item in decision["retained_evidence"].values()}
            if str(live_fm.get("blocker_evidence", "")) not in retained:
                raise UnblockError("spec is already blocked for an unrelated reason; a human must resolve that blocker first")
        decision = mpi.record_invalid_run_abandonment(root, spec_id=spec_id, abandonment_provider=abandonment_provider)
        pointer = _decision_pointer(decision)
        guard = lambda: _revalidate_administrative(root, spec_id, pointer, abandonment_provider)
        store = StatusStore.for_specs_dir(spec_file.parent)
        run_id = f"abandonment-{decision['invocation_id']}"
        payload = {"invalid_run_abandonment": pointer, "candidate_commit": decision["candidate_commit"],
                   "candidate_tree": decision["candidate_tree"], "acceptance_authorized": False,
                   "merge_authorized": False, "cleanup_authorized": False}
        previous = store.get_terminal_decision(spec_id, run_id)
        if previous and (previous.get("payload") != payload or previous.get("source") != "invalid-run-abandonment"):
            raise UnblockError("contradictory durable administrative ownership")
        current = parse_spec_file(spec_file).frontmatter
        if current.get("status") == "ready":
            state = store.get_state(spec_id)
            matched = False
            if previous and state and state.get("status") == "ready" and state.get("source") == "coordinator-unblock":
                for entry in current.get("unblock_history", []):
                    if not isinstance(entry, dict) or entry.get("resolved_blocker", {}).get("invalid_run_abandonment") != pointer:
                        continue
                    attempt_id = entry.get("attempt", "")
                    if not isinstance(attempt_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", attempt_id):
                        continue
                    path = _attempts_dir(root) / f"{attempt_id.replace(':', '_')}.md"
                    if state.get("note") != f"unblock attempt {attempt_id}" or not attempt_id.endswith("-succeeded"):
                        continue
                    # Bind to the durable parent digest recorded at attempt creation, never
                    # to fields copied back out of the attempt artifact itself.
                    durable = store.get_terminal_decision(spec_id, _administrative_attempt_key(attempt_id))
                    recorded = (durable or {}).get("payload") or {}
                    if (not durable or durable.get("source") != ATTEMPT_LEDGER_SOURCE
                            or recorded.get("invalid_run_abandonment") != pointer
                            or recorded.get("packet_id") != attempt_id.removesuffix("-succeeded")
                            or recorded.get("attempt_path") != str(path.relative_to(root))
                            or path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1
                            or _hash(path) != recorded.get("attempt_sha256")):
                        continue
                    attempt = parse_spec_file(path).frontmatter
                    if attempt.get("run_id") != state.get("run_id") or attempt.get("outcome") != "succeeded":
                        continue
                    matched = True
                    break
            if not matched:
                raise UnblockError("arbitrary ready reset cannot resolve an invalid old run")
            guard()
            return {**decision, "projection_status": "ready"}
        if current.get("status") not in {"in_progress", "blocked"}:
            raise UnblockError("invalid old run must remain nonaccepted and recoverable")
        guard()
        terminal = store.record_terminal_decision(spec_id, run_id, "blocked", source="invalid-run-abandonment",
            reason=mpi.REASON_INVALID_RUN_ABANDONED, payload=payload)
        guard()
        state = store.get_state(spec_id)
        if not state or state.get("run_id") != run_id or state.get("source") != "invalid-run-abandonment":
            store.transition_commit_backed(spec_file, "blocked", run_id=run_id, source="invalid-run-abandonment",
                reason="Invalid old run rejected administratively; controller verification required",
                evidence=[pointer["artifact_path"]], before_administrative_write=guard,
                extra_payload={"terminal_decision_id": terminal["decision_id"]})
        elif current.get("status") != "blocked":
            # A crash after durable blocked persistence is projected outward;
            # this never creates a second checkpoint or terminal decision.
            store.transition_commit_backed(spec_file, "blocked", run_id=run_id, source="invalid-run-abandonment",
                reason="Invalid old run rejected administratively; controller verification required",
                evidence=[pointer["artifact_path"]], before_administrative_write=guard,
                extra_payload={"terminal_decision_id": terminal["decision_id"]})
        guard()
        administrative = {"blocker_class": "evidence_unavailable",
            "block_reason": mpi.REASON_INVALID_RUN_ABANDONED, "blocked_since": terminal["created_at"],
            "unblock_condition": "Revalidate externally authorized rejected-run evidence through the existing controller",
            "blocker_scope": "in_scope", "blocker_evidence": pointer["artifact_path"],
            "invalid_run_abandonment": pointer}
        def blocked(value):
            updated = {**value, "status": "blocked", **administrative}
            # A related prior blocker (about this same rejected run) is moved to history,
            # never silently overwritten. Idempotent: once projected, nothing differs.
            prior = {key: value[key] for key in RESOLVED_BLOCKER_FIELDS if key in value}
            def same(key):
                if key == "blocked_since":
                    return _normalized_blocked_since(prior[key]) == _normalized_blocked_since(administrative[key])
                return prior[key] == administrative[key]
            if prior and not all(same(key) for key in prior):
                updated["unblock_history"] = [*value.get("unblock_history", []), {
                    "superseded_blocker": prior, "at": terminal["created_at"],
                    "by": "invalid-run-abandonment"}]
            return updated
        expected = blocked(parse_spec_file(spec_file).frontmatter)
        if parse_spec_file(spec_file).frontmatter != expected:
            write_spec_frontmatter(spec_file, blocked)
        return {**decision, "projection_status": "blocked"}


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


def _lineage_attempts(root: Path, fm: Mapping[str, Any], own_attempts: list[dict[str, Any]],
                      loader=None) -> list[dict[str, Any]]:
    """Pool a spec's own attempts with its declared parent's (SPEC-351 R2).

    Lineage is resolved from the frontmatter ``parent`` field only (e.g.
    SPEC-235-001's ``parent: SPEC-235``) -- never inferred from the
    ``SPEC-NNN-MMM`` ID shape alone. ``loader(spec_id)`` returns a spec's attempts: the
    controller passes the durable ledger's view; the default scans attempt files.
    """
    lineage = list(own_attempts)
    parent_id = fm.get("parent")
    if isinstance(parent_id, str) and parent_id.strip():
        lineage += loader(parent_id.strip()) if loader else _load_attempts(root, parent_id.strip())
    return lineage


def _prior_attempts(root: Path, store: StatusStore, spec_id: str) -> list[dict[str, Any]]:
    """The spec's ledgered attempts (both routes); the file is read only through its ledger entry.

    An entry whose file is not intact counts as a ``failed`` attempt (fail closed) and carries the
    named ``integrity`` reason; it cites no acceptance criterion because its bytes are not trusted.
    """
    attempts: list[dict[str, Any]] = []
    for route in (ORDINARY_ROUTE, ADMIN_ROUTE):
        for entry in _attempt_ledger(root, store, spec_id, route):
            parsed: dict[str, Any] | None = None
            if not entry["integrity"]:
                try:
                    parsed = dict(parse_spec_file(root / str(entry["attempt_path"])).frontmatter)
                except Exception:
                    entry["integrity"] = ATTEMPT_EVIDENCE_MISMATCH
            attempts.append(parsed if parsed is not None else {
                "attempt_id": entry.get("attempt_id"), "fingerprint": entry.get("fingerprint"),
                "outcome": "failed", "reason": "", "integrity": entry["integrity"]})
    return attempts


def adopt_legacy_attempts(root: Path, store: StatusStore, spec_id: str, *, run_id: str | None = None,
                          dry_run: bool = False) -> dict[str, Any]:
    """SPEC-NS-KIT-109 R5: ledger the pre-ledger attempt files of `spec_id`, once per spec.

    Every parseable ``unblock_attempt`` file of the spec with no ledger entry gets one entry
    carrying its current digest and ``legacy_adopted: true`` (no issuance; the entry stands as
    its own). The first adoption is recorded in the store, so a file that appears later is
    never adopted: it has no ledger entry and is not an outcome. Unparsable files named for the
    spec are reported and ignored (``_load_attempts`` already ignored them). Idempotent; the
    caller holds the controller lock.
    """
    root = Path(root)
    if store.get_terminal_decision(spec_id, ADOPTION_KEY) is not None:
        return {"spec_id": spec_id, "adopted": [], "skipped": [], "already_adopted": True}
    adopted: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    token = re.compile(rf"(?<![A-Za-z0-9-]){re.escape(spec_id)}(?![A-Za-z0-9])(?!-\d)")
    directory = _attempts_dir(root)
    for path in sorted(directory.glob("*.md")) if directory.is_dir() else []:
        try:
            if path.is_symlink() or path.stat().st_nlink != 1 or path.stat().st_size > mpi.MAX_ACCEPTANCE_BYTES:
                raise ValueError("unsafe attempt file")
            parsed = dict(parse_spec_file(path).frontmatter)
        except Exception:
            if token.search(path.name):
                skipped.append(path.name)
            continue
        if (parsed.get("kind") != "unblock_attempt" or parsed.get("spec_id") != spec_id
                or "invalid_run_abandonment" in parsed):
            continue  # not this spec's attempt; administrative attempts are ledgered by their own route
        outcome, attempt_id = parsed.get("outcome"), parsed.get("attempt_id")
        if outcome not in OUTCOMES or not isinstance(attempt_id, str) or not attempt_id or attempt_id in seen:
            skipped.append(path.name)
            continue
        seen.add(attempt_id)
        key = _attempt_key(attempt_id, ORDINARY_ROUTE)
        existing = store.get_terminal_decision(spec_id, key)
        if existing is not None:
            if (existing.get("payload") or {}).get("legacy_adopted") is True:
                adopted.append(path.name)  # a crash replay of this same adoption
            continue
        adopted.append(path.name)
        if dry_run:
            continue
        suffix = f"-{outcome}"
        run, fingerprint = parsed.get("run_id"), parsed.get("fingerprint")
        store.record_terminal_decision(spec_id, key, "blocked", source=ORDINARY_ROUTE.ledger_source, payload={
            "attempt_id": attempt_id, "packet_id": attempt_id[:-len(suffix)] if attempt_id.endswith(suffix) else attempt_id,
            "run_id": run if isinstance(run, str) else None,
            "fingerprint": fingerprint if isinstance(fingerprint, str) else None, "outcome": outcome,
            "attempt_path": str(path.relative_to(root)), "attempt_sha256": _hash(path),
            "automatic": bool(parsed.get("automatic")), "legacy_adopted": True})
    if not dry_run:
        store.record_terminal_decision(spec_id, ADOPTION_KEY, "blocked", source=ADOPTION_SOURCE,
                                       payload={"adopted": len(adopted), "skipped": skipped, "at": _now()})
        if (adopted or skipped) and isinstance(run_id, str) and mpi.SAFE_ID.fullmatch(run_id):
            open_run_log(root, run_id).emit("unblock_legacy_attempts_adopted", spec_id,
                                            count=len(adopted), skipped=skipped)
    return {"spec_id": spec_id, "adopted": adopted, "skipped": skipped, "already_adopted": False}


def _prepare(spec_file: Path, project_root: Path, run_id: str, *, retry_override: bool = False,
             allow_escalation: bool = False, _resume: bool = False) -> dict[str, Any]:
    """Validate a blocked spec and derive its pinned packet.

    The ordinary controller (``_resume`` false; the caller holds the controller lock) adopts the
    spec's pre-ledger attempt files once and applies `automatic_attempt_decision` over its durable
    ledger here; durable issuance is the caller's. Administrative recovery (``_resume`` true)
    derives the packet only and mutates nothing; its ledger decision is made by the caller.
    """
    spec_file, project_root = Path(spec_file), Path(project_root)
    project_root = project_root.resolve()
    if not spec_file.is_absolute():
        spec_file = project_root / spec_file
    spec_file = spec_file.resolve()
    parsed = parse_spec_file(spec_file)
    fm = parsed.frontmatter
    if is_nfr_family(fm) or str(fm.get("id", "")).startswith("EVAL-"):
        raise UnblockError("NFR-family and eval fixtures cannot be unblocked")
    if fm.get("status") != "blocked" and not (_resume and fm.get("status") == "ready"):
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
    store = StatusStore.for_specs_dir(spec_file.parent)
    if not _resume:
        # SPEC-NS-KIT-109 R5: ledger the pre-ledger attempt files of this spec and its parent, once.
        parent_id = fm.get("parent")
        for adopted_id in (str(fm["id"]), *([parent_id.strip()] if isinstance(parent_id, str) and parent_id.strip() else [])):
            adopt_legacy_attempts(project_root, store, adopted_id, run_id=run_id)
        decision = _ordinary_decision(project_root, store, {
            "spec_id": fm["id"], "packet_id": f"{run_id}:{fm['id']}:{fingerprint[:12]}", "run_id": run_id,
            "fingerprint": fingerprint, "retry_override": bool(retry_override)}, fingerprint, "prepare")
        if not decision.allow:
            raise UnblockError(decision.reason)
    prior = _prior_attempts(project_root, store, str(fm["id"]))
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
    lineage = _lineage_attempts(project_root, fm, prior, loader=lambda spec_id: _prior_attempts(project_root, store, spec_id))
    repeated_ac_ids = _repeated_failed_ac_ids(lineage)
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
    if any(item.get("integrity") for item in lineage):
        packet["integrity_failures"] = [{"attempt_id": item.get("attempt_id"), "reason": str(item["integrity"]).split(":")[0]}
                                        for item in lineage if item.get("integrity")]
    if not _resume and _own_automatic_success(prior, str(packet["packet_id"]), fingerprint):
        # BUG-NS-KIT-109: the decision above admitted this run only to finalize its own success.
        packet["retry_override"], packet["finalize_only"] = False, True
    return packet


def triage(spec_file: Path, project_root: Path, run_id: str = "triage") -> dict[str, Any]:
    """Manual-triage packet for a blocker class with no automated path (it durably issues like `prepare`).

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


def _record_attempt(packet: Mapping[str, Any], project_root: Path, *, outcome: str,
                   intervention: str, verification: Mapping[str, Any],
                   causal: Mapping[str, Any], automatic: bool = True,
                   reason: str = "", authorization: Mapping[str, Any] | None = None,
                   _guard=None, _administrative: bool = False) -> Path:
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
        raise UnblockError(REPEATED_AC_FAILURE)
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
    route = ADMIN_ROUTE if _administrative else ORDINARY_ROUTE
    fingerprint = str(packet.get("fingerprint", ""))
    if _administrative and not automatic:
        # Administrative recovery is only ever an automatic controller attempt; the human
        # route onto a closed fingerprint is `retry_override`, never a manual flag.
        raise UnblockError("administrative recovery attempts are automatic; a human uses retry_override")
    if _administrative:
        store = StatusStore.for_specs_dir((root / str(packet["spec_path"])).parent)
    else:
        spec_file = _relative(root, str(packet.get("spec_path", "")))
        store = StatusStore.for_specs_dir(spec_file.parent)
        current: dict[str, Any] | None = None
        if spec_file.is_file():
            try:
                current = dict(parse_spec_file(spec_file).frontmatter)
            except Exception:
                current = {}  # unparsable spec: the durable store still answers the blocker kind
        if current is not None and _is_administrative_blocker(spec_file, current, str(packet.get("spec_id", ""))):
            # BUG-NS-KIT-110 R1: the route is chosen by the presented packet, so a stripped copy
            # lands here; refuse it as `_finalize` does, before any write.
            _emit_refusal(root, packet, "record", ADMINISTRATIVE_BLOCKER_NEEDS_ADMINISTRATIVE_PACKET)
            raise UnblockError(ADMINISTRATIVE_BLOCKER_NEEDS_ADMINISTRATIVE_PACKET)
        if store.get_terminal_decision(str(packet["spec_id"]), _attempt_key(attempt_id, route)) is not None:
            raise UnblockError("attempt artifact already exists and is immutable")
        if automatic:
            decision = _ordinary_decision(root, store, packet, fingerprint, "record")
            if not decision.allow:
                raise UnblockError(decision.reason)
        if current is not None and automatic and outcome != "skipped" and packet.get("eligibility") == "eligible":
            # BUG-NS-KIT-110 R2 / SPEC-NS-KIT-109 R4: the SPEC-351 gate is re-evaluated against the
            # ledgered attempts now, not the packet pinned at prepare (this attempt is not ledgered yet).
            repeated = _repeated_failed_ac_ids(_lineage_attempts(
                root, current, _prior_attempts(root, store, str(packet.get("spec_id", ""))),
                loader=lambda spec_id: _prior_attempts(root, store, spec_id)))
            if repeated:
                _emit_refusal(root, packet, "record", REPEATED_AC_FAILURE, repeated_ac_ids=repeated)
                raise UnblockError(f"{REPEATED_AC_FAILURE} ({', '.join(repeated)})")
    if _administrative:
        decision = _administrative_decision(root, store, packet, fingerprint, "record")
        if not decision.allow:
            raise UnblockError(decision.reason)
    # Ledger only: attempt files are never consulted to decide anything here.
    for other in (OUTCOMES - {outcome}) if automatic else ():
        other_id = f"{packet['packet_id']}-{other}"
        if (store.get_terminal_decision(str(packet["spec_id"]), _attempt_key(other_id, route))
                or store.get_terminal_decision(str(packet["spec_id"]), _intent_key(other_id, route))):
            raise UnblockError("this recovery run already recorded a different completed outcome")
    intent_row = store.get_terminal_decision(str(packet["spec_id"]), _intent_key(attempt_id, route))
    if intent_row is not None and intent_row.get("source") != route.intent_source:
        raise UnblockError(ATTEMPT_LEDGER_ORPHANED)
    if (target.exists() or target.is_symlink()) and intent_row is None:
        # A pre-existing file at this path with no ledger entry is not an outcome and is
        # never read; only a ledgered crash replay may complete its own write.
        raise UnblockError(ATTEMPT_LEDGER_ORPHANED)
    if _administrative and parse_spec_file(root / str(packet["spec_path"])).frontmatter.get("status") == "ready" and not target.exists():
        raise UnblockError("resolved administrative recovery cannot record a new attempt")
    data = {
        "kind": "unblock_attempt", "schema_version": 1, "attempt_id": attempt_id,
        "run_id": packet["run_id"], "spec_id": packet["spec_id"],
        "created_at": (intent_row.get("payload") or {}).get("created_at") if intent_row else _now(),
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
    if _administrative:
        data["invalid_run_abandonment"] = packet["invalid_run_abandonment"]
    else:
        def _guard() -> None:
            # The same decision, same phase, between the writes; the in-flight outcome is not yet an outcome.
            between = _ordinary_decision(root, store, packet, fingerprint, "record", in_flight=attempt_id)
            if not between.allow:
                raise UnblockError(between.reason)
    body = "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True) + "---\n\n# Unblock attempt\n"
    _guard()
    # Durable write intent (stamp + digest) precedes the file, so a crash replay is
    # ledgered: it rebuilds identical bytes from the ledger, never from the file.
    intent = {**_attempt_ledger_payload(root, target, data, str(packet["packet_id"]),
                                        hashlib.sha256(body.encode("utf-8")).hexdigest(), route),
              "created_at": data["created_at"]}
    if intent_row is not None and intent_row.get("payload") != intent:
        raise UnblockError("contradictory immutable administrative attempt")
    recorded_intent = store.record_terminal_decision(
        str(packet["spec_id"]), _intent_key(attempt_id, route), "blocked",
        source=route.intent_source, payload=intent)
    if recorded_intent.get("source") != route.intent_source or recorded_intent.get("payload") != intent:
        raise UnblockError("contradictory immutable administrative attempt")
    mpi._safe_artifact_root(root, Path("knowledge/attempts"))
    _guard()
    try:
        expected_digest, replay = mpi._atomic_write_new(target, body.encode("utf-8"), limit=mpi.MAX_ACCEPTANCE_BYTES)
    except FileExistsError as exc:
        raise UnblockError("contradictory immutable administrative attempt") from exc
    _guard()
    identity = _attempt_key(attempt_id, route)
    payload = _attempt_ledger_payload(root, target, data, str(packet["packet_id"]), expected_digest, route)
    existing = store.get_terminal_decision(str(packet["spec_id"]), identity)
    if existing and (existing.get("source") != route.ledger_source or existing.get("payload") != payload):
        raise UnblockError("immutable administrative attempt digest changed")
    _guard()
    if (_links_below(root, target) or not target.is_file() or target.stat().st_nlink != 1
            or target.stat().st_size > mpi.MAX_ACCEPTANCE_BYTES or _hash(target) != expected_digest):
        raise UnblockError("administrative attempt changed before its original digest was recorded")
    store.record_terminal_decision(str(packet["spec_id"]), identity, "blocked",
        source=route.ledger_source, payload=payload)
    if replay and (_administrative or existing):
        return target
    _guard()
    open_run_log(root, str(packet["run_id"])).emit(
        "unblock_attempt_recorded", packet["spec_id"], attempt_id=attempt_id, outcome=outcome,
        route=route.name, issuance_id=packet.get("issuance_id"))
    return target


def _finalize(packet: Mapping[str, Any], attempt_path: Path, project_root: Path, *, _guard=None, _administrative: bool = False) -> str:
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
    if not _administrative:
        if _is_administrative_blocker(spec_path, parse_spec_file(spec_path).frontmatter, str(packet.get("spec_id", ""))):
            # An administrative blocker is never moved to ready by a non-administrative packet (R4);
            # refused before any ledger question, as `record_attempt` refuses it before writing.
            raise UnblockError(ADMINISTRATIVE_BLOCKER_NEEDS_ADMINISTRATIVE_PACKET)
        store = StatusStore.for_specs_dir(spec_path.parent)
        _validate_ordinary_attempt(root, store, packet, attempt_path)
        if attempt.get("automatic"):
            decision = _ordinary_decision(root, store, packet, str(packet.get("fingerprint", "")), "finalize")
            if not decision.allow:
                raise UnblockError(decision.reason)
        _validate_ordinary_attempt(root, store, packet, attempt_path, bound=True)
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
    if not _administrative:
        # Ordinary controller: an administrative blocker
        # is never moved to ready by a non-administrative packet (R4).
        if current.get("status") == "ready" and any(
                isinstance(entry, dict) and entry.get("attempt") == attempt["attempt_id"]
                for entry in current.get("unblock_history", [])):
            return "ready"  # BUG-NS-KIT-109: an identical second finalize is a no-op
        if current.get("status") != "blocked" or _normalized_blocked_since(current.get("blocked_since")) != packet.get("source_blocked_since"):
            raise UnblockError("spec blocker changed; prepare again")
        if _is_administrative_blocker(spec_path, current, str(packet.get("spec_id", ""))):
            raise UnblockError(ADMINISTRATIVE_BLOCKER_NEEDS_ADMINISTRATIVE_PACKET)
        try:
            StatusStore.for_specs_dir(spec_path.parent).transition_commit_backed(
                spec_path, "ready", run_id=str(packet["run_id"]), source="coordinator-unblock",
                note=f"unblock attempt {attempt['attempt_id']}",
            )
        except Exception as exc:
            raise UnblockError(f"durable unblock transition failed: {exc}") from exc
        write_spec_frontmatter(spec_path, mutate)
        open_run_log(root, str(packet["run_id"])).emit("spec_unblocked", packet["spec_id"], attempt_id=attempt["attempt_id"], transition="blocked->ready",
                                                       route="ordinary", issuance_id=packet.get("issuance_id"))
        return "ready"
    store = StatusStore.for_specs_dir(spec_path.parent)
    state = store.get_state(str(packet["spec_id"]))
    projected = bool(state and state.get("status") == "ready" and state.get("run_id") == packet["run_id"]
                     and state.get("source") == "coordinator-unblock")
    if attempt.get("invalid_run_abandonment") != packet["invalid_run_abandonment"]:
        raise UnblockError("attempt does not bind the administrative decision")
    _guard()
    if current.get("status") == "ready" and projected and any(
        isinstance(entry, dict) and entry.get("attempt") == attempt["attempt_id"]
        and entry.get("resolved_blocker", {}).get("invalid_run_abandonment") == packet["invalid_run_abandonment"]
        for entry in current.get("unblock_history", [])):
        return "ready"
    if (current.get("status") != "blocked" and not (projected and current.get("status") == "ready")) or _normalized_blocked_since(current.get("blocked_since")) != packet.get("source_blocked_since"):
        raise UnblockError("spec blocker changed; prepare again")
    try:
        if not projected or current.get("status") == "blocked":
            store.transition_commit_backed(
                spec_path, "ready", run_id=str(packet["run_id"]), source="coordinator-unblock",
                note=f"unblock attempt {attempt['attempt_id']}", before_administrative_write=_guard,
            )
    except Exception as exc:
        raise UnblockError(f"durable unblock transition failed: {exc}") from exc
    _guard()
    write_spec_frontmatter(spec_path, mutate)
    _guard()
    open_run_log(root, str(packet["run_id"])).emit("spec_unblocked", packet["spec_id"], attempt_id=attempt["attempt_id"], transition="blocked->ready",
                                                   route="administrative", issuance_id=packet.get("issuance_id"))
    return "ready"


def _validate_ordinary_attempt(root: Path, store: StatusStore, packet: Mapping[str, Any], attempt_path: Path,
                               *, bound: bool = False) -> None:
    """SPEC-NS-KIT-109 R3: finalize accepts only an attempt bound to its ledger entry and issuance.

    A file at the attempt path with no ledger entry is not an outcome (orphaned); an entry whose
    file is not intact fails with its named reason. Called twice around the retry decision:
    first for those two checks (``bound`` false), then to require that the entry belongs to this
    packet's durable issuance (``bound`` true).
    """
    path = Path(attempt_path).absolute()
    if path.is_symlink():
        raise UnblockError("attempt must be a safe immutable local artifact")
    attempt_id = parse_spec_file(path).frontmatter.get("attempt_id")
    row = store.get_terminal_decision(str(packet["spec_id"]), _attempt_key(attempt_id, ORDINARY_ROUTE)) \
        if isinstance(attempt_id, str) else None
    recorded = (row or {}).get("payload") or {}
    if (row is None or row.get("source") != ORDINARY_ROUTE.ledger_source
            or path.resolve() != (root / str(recorded.get("attempt_path"))).resolve()):
        _emit_integrity(root, packet, ATTEMPT_LEDGER_ORPHANED, [{"attempt_id": attempt_id, "integrity": ATTEMPT_LEDGER_ORPHANED}], "ordinary")
        raise UnblockError(ATTEMPT_LEDGER_ORPHANED)
    reason = _attempt_evidence_integrity(root, recorded)
    if reason:
        _emit_integrity(root, packet, reason, [{"attempt_id": attempt_id, "integrity": reason}], "ordinary")
        raise UnblockError(reason)
    if not bound:
        return  # stage one: the entry exists and its file is intact; the retry rule decides next
    if any(recorded.get(key) != packet.get(key) for key in ("packet_id", "fingerprint", "run_id")):
        raise UnblockError("attempt does not belong to packet")
    issued = _issuance_view(store, packet, str(packet.get("fingerprint", "")), ORDINARY_ROUTE)["record"]
    if (not isinstance(issued, Mapping) or issued.get("packet_id") != packet.get("packet_id")
            or issued.get("run_id") != packet.get("run_id")):
        raise UnblockError(NOT_ISSUED)


def _validate_administrative_attempt(root: Path, packet: Mapping[str, Any], attempt_path: Path) -> None:
    path = Path(attempt_path).absolute()
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents) or path.stat().st_nlink != 1:
        raise UnblockError("administrative attempt must be a safe immutable local artifact")
    attempt = parse_spec_file(path).frontmatter
    outcome = attempt.get("outcome")
    expected_id = f"{packet['packet_id']}-{outcome}"
    expected_path = _attempts_dir(root) / f"{expected_id.replace(':', '_')}.md"
    if path != expected_path or outcome not in OUTCOMES or path.stat().st_size > mpi.MAX_ACCEPTANCE_BYTES:
        raise UnblockError("administrative attempt was not recorded at its supported local path")
    for key in ("run_id", "spec_id", "source_blocked_since", "fingerprint", "blocker_class", "metric_blocker_class", "evidence", "eligibility", "invalid_run_abandonment"):
        if attempt.get(key) != packet.get(key):
            raise UnblockError("administrative attempt identity does not match its pinned packet")
    if attempt.get("attempt_id") != expected_id or attempt.get("kind") != "unblock_attempt" or attempt.get("schema_version") != 1:
        raise UnblockError("invalid administrative attempt artifact")
    if not isinstance(attempt.get("causal"), Mapping) or not isinstance(attempt.get("verification"), Mapping):
        raise UnblockError("invalid administrative causal or verification contract")
    _validate_causal(str(outcome), attempt["causal"], attempt["verification"])
    store = StatusStore.for_specs_dir((root / str(packet["spec_path"])).parent)
    terminal = store.get_terminal_decision(str(packet["spec_id"]), _administrative_attempt_key(expected_id))
    payload = _attempt_ledger_payload(root, path, attempt, str(packet["packet_id"]), _hash(path))
    if not terminal or terminal.get("decision") != "blocked" or terminal.get("source") != ATTEMPT_LEDGER_SOURCE or terminal.get("payload") != payload:
        raise UnblockError("administrative attempt lacks its original durable parent digest")


@contextmanager
def _recovery_guard(spec_file: Path, root: Path, packet, provider, phase: str = "prepare",
                    in_flight: str | None = None):
    root = Path(root).resolve()
    spec_file = Path(spec_file).resolve()
    fm = parse_spec_file(spec_file).frontmatter
    pointer = _administrative_pointer(root, str(fm.get("id", "")), fm, packet)
    if pointer is None:
        yield None, None
        return
    if packet is not None and (packet.get("invalid_run_abandonment") != pointer
                               or packet.get("spec_id") != fm.get("id")):
        raise UnblockError("controller packet lost administrative ownership")
    def guard():
        result = _revalidate_administrative(root, str(fm["id"]), pointer, provider)
        if packet is not None:
            run_id = packet.get("run_id")
            fingerprint = packet.get("fingerprint")
            if (not isinstance(run_id, str) or not mpi.SAFE_ID.fullmatch(run_id)
                    or not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
                    or packet.get("packet_id") != f"{run_id}:{fm['id']}:{fingerprint[:12]}"
                    or packet.get("spec_path") != str(spec_file.relative_to(root))):
                raise UnblockError("administrative controller packet identity changed")
            current = parse_spec_file(spec_file).frontmatter
            fingerprint_now = fingerprint
            if current.get("blocked_since") is not None:
                expected = _prepare(spec_file, root, run_id, retry_override=bool(packet.get("retry_override")),
                                    _resume=True)
                for key in ("schema_version", "packet_id", "run_id", "spec_id", "spec_path", "source_blocked_since",
                            "blocker_class", "metric_blocker_class", "block_reason", "blocker_scope",
                            "fingerprint", "evidence", "eligibility", "bounded_task", "retry_override"):
                    if packet.get(key) != expected.get(key):
                        raise UnblockError("administrative controller packet changed from pinned evidence")
                fingerprint_now = expected["fingerprint"]
            # Revalidation never bypasses the retry rule: the same decision, same phase.
            decision = _administrative_decision(root, StatusStore.for_specs_dir(spec_file.parent), packet,
                                                fingerprint_now, phase, in_flight=in_flight)
            if not decision.allow:
                raise UnblockError(decision.reason)
        return result
    guard()
    with _administrative_lock(root):
        guard()
        yield pointer, guard


def _prepare_ordinary(selected: Path, root: Path, run_id: str, *, retry_override: bool,
                      allow_escalation: bool) -> dict[str, Any]:
    """Ordinary prepare: adoption, the shared decision and durable issuance in one critical section."""
    with _administrative_lock(root):
        packet = _prepare(selected, root, run_id, retry_override=retry_override,
                          allow_escalation=allow_escalation, _resume=False)
        store = StatusStore.for_specs_dir(selected.resolve().parent)
        finalize_only = bool(packet.get("finalize_only"))
        own_id = f"{packet['packet_id']}-succeeded"
        legacy_own = finalize_only and any(
            entry.get("attempt_id") == own_id and entry.get("legacy_adopted") is True
            for entry in _attempt_ledger(root, store, str(packet["spec_id"]), ORDINARY_ROUTE))
        issued = _issue_packet(store, packet, finalize_only=finalize_only, route=ORDINARY_ROUTE,
                               mint_unissued=legacy_own)
        packet["issuance_id"] = issued["issuance_id"]
        packet["retry_override"] = issued["retry_override"]
        if finalize_only:
            open_run_log(root, run_id).emit("unblock_prepare_finalize_only", packet["spec_id"],
                                            attempt_id=own_id, route="ordinary", issuance_id=packet["issuance_id"])
        return packet


def prepare(spec_file: Path, project_root: Path, run_id: str, *, retry_override: bool = False,
            allow_escalation: bool = False, abandonment_provider=None) -> dict[str, Any]:
    given = Path(project_root).resolve()
    root = _install_root(given).resolve()
    selected = Path(spec_file)
    if not selected.is_absolute():
        # A path relative to the project root the caller named (e.g. `.nightshift/specs/X.md`) is
        # honoured when it is not a file under the install itself.
        selected = given / selected if root != given and not (root / selected).exists() and (given / selected).exists() else root / selected
    with _recovery_guard(selected, root, None, abandonment_provider) as (pointer, guard):
        if pointer is None:
            return _prepare_ordinary(selected, root, run_id, retry_override=retry_override,
                                     allow_escalation=allow_escalation)
        if not isinstance(run_id, str) or not mpi.SAFE_ID.fullmatch(run_id):
            raise UnblockError("invalid administrative recovery run identity")
        if parse_spec_file(selected).frontmatter.get("status") == "ready":
            state = StatusStore.for_specs_dir(selected.parent).get_state(str(parse_spec_file(selected).frontmatter["id"]))
            if not state or state.get("status") != "ready" or state.get("source") != "coordinator-unblock" or state.get("run_id") != run_id:
                raise UnblockError("arbitrary ready reset cannot resume controller recovery")
        packet = _prepare(selected, root, run_id, retry_override=retry_override,
                          allow_escalation=allow_escalation, _resume=True)
        store = StatusStore.for_specs_dir(selected.resolve().parent)
        decision = _administrative_decision(root, store, packet, str(packet["fingerprint"]), "prepare",
                                            retry_override=retry_override)
        if not decision.allow:
            raise UnblockError(decision.reason)
        guard()
        packet["invalid_run_abandonment"] = pointer
        own_ids = {f"{packet['packet_id']}-{outcome}" for outcome in OUTCOMES}
        finalize_only = any(entry.get("attempt_id") in own_ids
                            for entry in _attempt_ledger(root, store, str(packet["spec_id"])))
        issued = _issue_packet(store, packet, finalize_only=finalize_only)
        packet["issuance_id"] = issued["issuance_id"]
        packet["retry_override"] = issued["retry_override"]
        guard()
        return packet


def record_attempt(packet: Mapping[str, Any], project_root: Path, *, outcome: str,
                   intervention: str, verification: Mapping[str, Any], causal: Mapping[str, Any],
                   automatic: bool = True, reason: str = "", authorization: Mapping[str, Any] | None = None,
                   abandonment_provider=None) -> Path:
    if not _is_administrative_packet(packet):
        # Ordinary controller, under the same controller lock as ordinary prepare and finalize;
        # the caller's own project_root spelling is kept (the returned path is built from it).
        project_root = _install_root(Path(project_root))
        with _administrative_lock(project_root):
            return _record_attempt(packet, project_root, outcome=outcome, intervention=intervention,
                verification=verification, causal=causal, automatic=automatic, reason=reason,
                authorization=authorization)
    root = _install_root(Path(project_root)).resolve()
    in_flight = f"{packet.get('packet_id', '')}-{outcome}"
    with _recovery_guard(_relative(root, str(packet["spec_path"])), root, packet, abandonment_provider,
                         "record", in_flight) as (pointer, guard):
        if pointer is None:
            raise UnblockError(UNBOUND_ADMINISTRATIVE_PACKET)
        return _record_attempt(packet, root, outcome=outcome, intervention=intervention,
            verification=verification, causal=causal, automatic=automatic, reason=reason,
            authorization=authorization, _guard=guard, _administrative=True)


def finalize(packet: Mapping[str, Any], attempt_path: Path, project_root: Path, *, abandonment_provider=None) -> str:
    if not _is_administrative_packet(packet):
        # Ordinary controller: its only addition to the SPEC-185 transition refuses to move an
        # administrative blocker to ready with a non-administrative packet.
        project_root = _install_root(Path(project_root))
        with _administrative_lock(project_root):
            return _finalize(packet, attempt_path, project_root)
    root = _install_root(Path(project_root)).resolve()
    with _recovery_guard(_relative(root, str(packet["spec_path"])), root, packet, abandonment_provider,
                         "finalize") as (pointer, guard):
        if pointer is None:
            raise UnblockError(UNBOUND_ADMINISTRATIVE_PACKET)
        def guarded_attempt():
            guard()
            _validate_administrative_attempt(root, packet, attempt_path)
        guarded_attempt()
        return _finalize(packet, attempt_path, root, _guard=guarded_attempt, _administrative=True)


# --------------------------------------------------------------------------- SPEC-NS-KIT-002-006
# Evidence-bound recovery/resume. A persisted, immutable record of the stages that
# already completed for ONE candidate; `recovery_eligibility` names the first stage
# whose own check fails. It never marks Done and never waives a gate: scope, terminal
# integrity, serial integration and fresh-main validation are always executed anew.

RECOVERY_STAGES = ("worker", "reviewer", "verifier", "integration")
REUSABLE_STAGES = ("worker", "reviewer", "verifier")  # integration/fresh-main are never reused
PROTECTED_STAGES = ("worker", "verifier", "integration")  # product/safety/scope, independent, fresh-main
RECEIPT_MAX_AGE = timedelta(hours=24)
KNOWN_OWNERSHIP = ("none_running", "confirmed_stopped")
ALWAYS_EXECUTED = ("scope", "terminal_integrity", "serial_integration", "fresh_main")


def _vr():
    import verification_report
    return verification_report


def _cdigest(value: Any) -> str:
    vr = _vr()
    return vr.sha256_hex(vr.canonical_json(value))


def _iso(value: Any) -> datetime | None:
    return _vr()._parse_iso(value)


def make_stage_receipt(stage: str, *, run_id: str, issued_at: str, expires_at: str,
                       evidence: list[Mapping[str, str]], identity: Mapping[str, Any],
                       independent: bool = False, contaminated: bool = False) -> dict[str, Any]:
    """One stage's original receipt; ``receipt_digest`` makes later edits detectable."""
    if stage not in REUSABLE_STAGES:
        raise UnblockError(f"stage {stage!r} has no reusable receipt")
    receipt = {"stage": stage, "run_id": run_id, "issued_at": issued_at, "expires_at": expires_at,
               "evidence": [dict(item) for item in evidence], "evidence_digest": _cdigest(list(evidence)),
               "identity_digest": _vr().identity_digest(identity),
               "independent": bool(independent), "contaminated": bool(contaminated)}
    receipt["receipt_digest"] = _cdigest(receipt)
    return receipt


def make_recovery_record(spec_id: str, run_id: str, *, candidate_sha: str, candidate_tree: str,
                         identity: Mapping[str, Any], receipts: list[Mapping[str, Any]],
                         owner_run: str, process_state: str, created_at: str | None = None,
                         required_stages: tuple[str, ...] = ("worker", "verifier")) -> dict[str, Any]:
    by_stage = {r["stage"]: dict(r) for r in receipts}
    done = [s for s in RECOVERY_STAGES if s in by_stage]
    record = {"kind": "recovery_record", "schema_version": 1, "spec_id": spec_id, "run_id": run_id,
              "created_at": created_at or _now(),
              "candidate": {"sha": candidate_sha, "tree": candidate_tree},
              "identity": dict(identity), "identity_digest": _vr().identity_digest(identity),
              "ownership": {"owner_run": owner_run, "process_state": process_state},
              "required_stages": list(required_stages), "last_completed_stage": done[-1] if done else None,
              "stages": by_stage}
    record["record_digest"] = _cdigest(record)
    return record


def _recovery_dir(root: Path, spec_id: str) -> Path:
    return Path(root) / "reports" / spec_id / "recovery"


def _write_new(path: Path, data: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    except FileExistsError as exc:
        raise UnblockError("recovery artifacts are immutable; use a new run id") from exc
    return path


def persist_recovery_record(root: Path, record: Mapping[str, Any]) -> Path:
    return _write_new(_recovery_dir(root, str(record["spec_id"])) / f"{record['run_id']}-record.json", record)


def _stage_problem(receipt: Any, stage: str, record: Mapping[str, Any], current: Mapping[str, Any],
                   now: datetime) -> tuple[str, str] | None:
    """Return (code, reason) when this stage's own check fails, else None."""
    if not isinstance(receipt, Mapping):
        return "missing_receipt", f"no {stage} receipt was recorded"
    if receipt.get("receipt_digest") != _cdigest({k: v for k, v in receipt.items() if k != "receipt_digest"}):
        return "untrusted_receipt", f"{stage} receipt does not match its own digest"
    if receipt.get("stage") != stage:
        return "untrusted_receipt", f"{stage} receipt is for another stage"
    if receipt.get("identity_digest") != record.get("identity_digest"):
        return "identity_changed", f"{stage} receipt is bound to another identity"
    issued, expires = _iso(receipt.get("issued_at")), _iso(receipt.get("expires_at"))
    if issued is None or expires is None:
        return "untrusted_receipt", f"{stage} receipt has no valid issuance/expiry"
    if expires <= now:
        return "expired_original", f"{stage} receipt reached its original expiry"
    if issued + RECEIPT_MAX_AGE <= now:
        return "exceeds_24h", f"{stage} receipt is older than 24 hours from original issuance"
    if receipt.get("contaminated"):
        return "substantive_contamination", f"{stage} evidence carries substantive contamination"
    if stage == "verifier" and not receipt.get("independent"):
        return "not_independent", "verifier receipt is not an independently accepted verdict"
    digests = current.get("evidence_digests") or {}
    if digests.get(stage) != receipt.get("evidence_digest"):
        return "evidence_changed", f"{stage} evidence digest differs from the original receipt"
    return None


def recovery_eligibility(record: Mapping[str, Any], current: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """First invalidated or unperformed stage with a reason; reuse never extends or refreshes.

    ``current`` carries candidate_sha, candidate_tree, identity and evidence_digests
    (per stage, recomputed from the evidence files now).
    """
    def refuse(code: str, reason: str, stage: str = RECOVERY_STAGES[0]) -> dict[str, Any]:
        return {"eligible": False, "resume_stage": stage, "invalidated_stage": stage, "code": code,
                "reason": reason, "reused": [], "to_execute": list(RECOVERY_STAGES),
                "always_executed": list(ALWAYS_EXECUTED), "marks_done": False}

    if record.get("kind") != "recovery_record" or record.get("record_digest") != _cdigest(
            {k: v for k, v in record.items() if k != "record_digest"}):
        return refuse("untrusted_record", "recovery record does not match its digest")
    if (record.get("ownership") or {}).get("process_state") not in KNOWN_OWNERSHIP:
        return refuse("unknown_ownership", "process ownership is unknown; confirm none are running, then run a new worker stage")
    cand = record.get("candidate") or {}
    if current.get("candidate_sha") != cand.get("sha") or current.get("candidate_tree") != cand.get("tree"):
        return refuse("candidate_changed", "candidate SHA/tree differs from the recorded candidate")
    cur_id, rec_id = current.get("identity") or {}, record.get("identity") or {}
    if _vr().identity_digest(cur_id) != record.get("identity_digest"):
        changed = sorted(k for k in set(cur_id) | set(rec_id) if cur_id.get(k) != rec_id.get(k))
        return refuse("identity_changed", "identity component changed: " + (", ".join(changed) or "digest"))
    stages = record.get("stages") or {}
    needed = set(record.get("required_stages") or ()) | set(stages)
    reused: list[str] = []
    for stage in REUSABLE_STAGES:
        if stage not in needed:
            continue
        problem = _stage_problem(stages.get(stage), stage, record, current, now)
        if problem:
            code, reason = problem
            return {**refuse(code, reason, stage), "reused": reused,
                    "to_execute": [s for s in RECOVERY_STAGES if s not in reused]}
        reused.append(stage)
    return {"eligible": True, "resume_stage": "integration", "invalidated_stage": None, "code": "reusable",
            "reason": "all required stages valid for the unchanged candidate", "reused": reused,
            "to_execute": ["integration"], "always_executed": list(ALWAYS_EXECUTED), "marks_done": False}


def fast_path_decision(eligibility: Mapping[str, Any]) -> dict[str, Any]:
    """R1/R2: dispatch the verifier directly only on a reused worker proof; else ordinary kickoff."""
    if "worker" in eligibility.get("reused", ()) and eligibility.get("resume_stage") != "worker":
        return {"fast_path": True, "dispatch": eligibility["resume_stage"], "worker_run": False}
    return {"fast_path": False, "dispatch": "ordinary_kickoff", "worker_run": True,
            "reason": eligibility.get("reason", "")}


def fast_path_trailers(decision: Mapping[str, Any], eligibility: Mapping[str, Any],
                       executed: tuple[str, ...] = ()) -> list[str]:
    """Extra terminal-commit trailers; the ordinary Nightshift-Evidence-* trailers are unchanged."""
    if not decision.get("fast_path"):
        return []
    return ["Nightshift-Recovery-Fast-Path: reused=" + ",".join(eligibility.get("reused", ()))
            + ";executed=" + ",".join(executed or eligibility.get("to_execute", ()))]


def resume_recovery(root: Path, record_path: Path, current: Mapping[str, Any], *, run_id: str,
                    now: datetime | None = None, operator: bool = False,
                    authorization: Mapping[str, Any] | None = None, propose_stage: str | None = None,
                    human_action: str = "") -> dict[str, Any]:
    """Evaluate (never execute) a recovery resume and persist a separate, immutable resume record.

    The original record and its receipts are read-only. The operator route needs an explicit
    authorization; a proposal that skips a protected gate is refused, and a permitted skip is
    recorded as an exception, never as an ordinary pass.
    """
    root = _install_root(Path(root))
    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    eligibility = recovery_eligibility(record, current, now=now or datetime.now(timezone.utc))
    auth: dict[str, Any] = {}
    exception = False
    if operator:
        auth = _validate_authorization(authorization)
        if (record.get("ownership") or {}).get("process_state") not in KNOWN_OWNERSHIP:
            raise UnblockError("operator recovery with unknown process ownership fails closed")
        if propose_stage is not None:
            if propose_stage not in RECOVERY_STAGES:
                raise UnblockError("unknown proposed stage")
            order = RECOVERY_STAGES.index
            skipped = RECOVERY_STAGES[order(eligibility["resume_stage"]):order(propose_stage)]
            if any(s in PROTECTED_STAGES for s in skipped):
                raise UnblockError("operator recovery cannot skip a product, safety, scope, independent-verification or fresh-main gate")
            exception = bool(skipped)
    elif propose_stage is not None:
        raise UnblockError("a proposed stage requires the operator mode")
    stage = propose_stage if exception else eligibility["resume_stage"]
    decision = fast_path_decision(eligibility)
    result = {
        "kind": "recovery_resume", "schema_version": 1, "spec_id": record["spec_id"], "run_id": run_id,
        "record_digest": record["record_digest"], "mode": "operator" if operator else "parent",
        "authorization": auth, "proposed_stage": propose_stage or eligibility["resume_stage"],
        "resume_stage": stage, "eligibility": eligibility, "fast_path": decision,
        "attempt_result": "authorized_exception" if exception else ("resume_reused" if eligibility["eligible"] else "resume_refused"),
        "exception": exception, "reused_stages": list(eligibility["reused"]),
        "executed_stages": [], "to_execute": list(eligibility["to_execute"]), "always_executed": list(ALWAYS_EXECUTED),
        "causal_confidence": "not_established", "evidence_refs": [
            {"path": item.get("path"), "sha256": item.get("sha256")}
            for r in (record.get("stages") or {}).values() for item in r.get("evidence", [])],
        "human_action_needed": human_action or ("" if eligibility["eligible"] else eligibility["reason"]),
        "marks_done": False, "created_at": _now()}
    path = _write_new(_recovery_dir(root, str(record["spec_id"])) / f"{run_id}-resume.json", result)
    open_run_log(root, run_id).emit("recovery_resume", record["spec_id"], resume_stage=stage,
                                    reused=",".join(result["reused_stages"]), fast_path=decision["fast_path"],
                                    mode=result["mode"], exception=exception)
    return {**result, "path": str(path)}


def _current_from_args(root: Path, record: Mapping[str, Any], candidate: str, identity_file: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        import subprocess
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else ""
    digests: dict[str, str] = {}
    for stage, receipt in (record.get("stages") or {}).items():
        files = []
        for item in receipt.get("evidence", []):
            try:
                files.append({"path": item["path"], "sha256": _hash(_relative(root, str(item["path"])))})
            except (OSError, UnblockError, KeyError):
                files.append({"path": item.get("path"), "sha256": "missing"})
        digests[stage] = _cdigest(files)
    return {"candidate_sha": git("rev-parse", candidate), "candidate_tree": git("rev-parse", f"{candidate}^{{tree}}"),
            "identity": json.loads(Path(identity_file).read_text(encoding="utf-8")), "evidence_digests": digests}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "triage", "resume", "adopt-legacy-attempts"))
    parser.add_argument("spec_file", type=Path, nargs="?")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--spec", help="adopt-legacy-attempts: the spec id whose attempt files are adopted")
    parser.add_argument("--dry-run", action="store_true", help="adopt-legacy-attempts: report only")
    parser.add_argument("--allow-escalation", action="store_true")
    parser.add_argument("--record", type=Path, help="resume: persisted recovery record")
    parser.add_argument("--candidate", default="HEAD", help="resume: candidate ref to bind")
    parser.add_argument("--identity-file", type=Path, help="resume: current full identity JSON")
    parser.add_argument("--operator", action="store_true", help="resume: direct/operator recovery")
    parser.add_argument("--authorized-by", default="")
    parser.add_argument("--statement", default="")
    parser.add_argument("--propose-stage", choices=RECOVERY_STAGES)
    ns = parser.parse_args()
    if ns.operation == "adopt-legacy-attempts":
        if not ns.spec:
            parser.error("adopt-legacy-attempts requires --spec")
        root = _install_root(ns.root).resolve()
        store = StatusStore.for_specs_dir(root / "specs")
        with _administrative_lock(root):
            print(json.dumps(adopt_legacy_attempts(root, store, ns.spec, run_id=ns.run_id or "adopt-legacy-attempts",
                                                   dry_run=ns.dry_run), indent=2))
        return 0
    if not ns.spec_file or not ns.run_id:
        parser.error("this operation requires spec_file and --run-id")
    if ns.operation == "resume":
        if not ns.record or not ns.identity_file:
            parser.error("resume requires --record and --identity-file")
        record = json.loads(ns.record.read_text(encoding="utf-8"))
        out = resume_recovery(
            ns.root, ns.record, _current_from_args(ns.root, record, ns.candidate, ns.identity_file),
            run_id=ns.run_id, operator=ns.operator, propose_stage=ns.propose_stage,
            authorization={"authorized_by": ns.authorized_by, "statement": ns.statement} if ns.operator else None)
        print(json.dumps(out, indent=2))
    elif ns.operation == "triage":
        print(json.dumps(triage(ns.spec_file, ns.root, ns.run_id), indent=2))
    else:
        print(json.dumps(prepare(
            ns.spec_file, ns.root, ns.run_id, allow_escalation=ns.allow_escalation,
        ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
