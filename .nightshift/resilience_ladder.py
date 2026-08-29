"""Bounded, keyed class-specific recovery decisions for SPEC-266.

This module never dispatches workers, writes lifecycle state, or merges.  The
parent controller supplies the evidence callbacks and executes the returned
effect exactly once per ``run_id/class/rung`` key.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


FAILURE_CLASSES = frozenset({"verifier_fail", "premise_dispute", "evidence_gap", "transport_stall"})


@dataclass(frozen=True)
class ResilienceDecision:
    failure_class: str
    rung: int
    action: str
    terminal: str | None
    evidence_refs: tuple[str, ...] = ()

    @property
    def effect_key(self) -> str:
        return f"{self.failure_class}/{self.rung}"


def decide_verifier_fail(
    previous_failed: Iterable[str], current_failed: Iterable[str], *, max_rounds: int = 2
) -> ResilienceDecision:
    """Permit a second remediation only after measurable AC-set shrinkage."""
    previous, current = set(previous_failed), set(current_failed)
    rung = 2
    if not current:
        return ResilienceDecision("verifier_fail", rung, "continue", "done")
    if max_rounds >= rung and current < previous:
        return ResilienceDecision("verifier_fail", rung, "dispatch_remediation", None)
    return ResilienceDecision("verifier_fail", rung, "terminal_blocked", "blocked")


def decide_premise_dispute(
    disputed_ac: str, *, covered_by: str | None, runtime_gate: str | None,
    amendment: str | None, reviewer: str, enabled: bool = True,
) -> ResilienceDecision:
    """Route coverage/runtime evidence through the independent amendment gate."""
    refs = tuple(item for item in (covered_by, runtime_gate, amendment) if item)
    if not enabled:
        return ResilienceDecision("premise_dispute", 1, "terminal_blocked", "blocked", refs)
    if covered_by and reviewer == "approve":
        return ResilienceDecision("premise_dispute", 1, "rerun_gate", None, refs)
    if runtime_gate and reviewer == "approve":
        return ResilienceDecision("premise_dispute", 2, "rerun_gate", None, refs)
    if reviewer == "approve" and amendment:
        return ResilienceDecision("premise_dispute", 3, "rerun_gate", None, refs)
    # A rejected premise amendment leaves a genuine evidence gap; retain the
    # original dispute identity while making that terminal classification
    # explicit for the blocked report.
    return ResilienceDecision("premise_dispute", 3, "terminal_blocked", "blocked", (*refs, "evidence_gap"))


def decide_evidence_gap(*, artifact_found: bool, passes_used: int, max_passes: int = 1) -> ResilienceDecision:
    if artifact_found:
        return ResilienceDecision("evidence_gap", passes_used, "rerun_gate", None)
    if passes_used < max_passes:
        return ResilienceDecision("evidence_gap", passes_used + 1, "collect_evidence", None)
    return ResilienceDecision("evidence_gap", max_passes, "terminal_blocked", "blocked")


def decide_transport_stall(
    failures: Iterable[tuple[str, str]], *, max_rebinds: int = 2
) -> ResilienceDecision:
    """A changed tool or fresh worker earns one bounded extra rebind."""
    observed = list(failures)
    rung = len(observed)
    if not observed:
        return ResilienceDecision("transport_stall", 0, "continue", None)
    if rung == 1:
        return ResilienceDecision("transport_stall", 1, "rebind", None)
    previous, current = observed[-2], observed[-1]
    changed = previous[0] != current[0] or previous[1] != current[1]
    if changed and rung <= max_rebinds:
        return ResilienceDecision("transport_stall", rung, "rebind", None)
    return ResilienceDecision("transport_stall", rung, "terminal_blocked", "blocked")


def keyed_effect_key(run_id: str, decision: ResilienceDecision) -> str:
    """Return the durable allowance identity for exactly one run/class/rung."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("resilience effects require a non-empty run id")
    return f"{run_id}:{decision.effect_key}"


def consume_keyed_effect(
    effects: Mapping[str, object], decision: ResilienceDecision, *, run_id: str | None = None,
) -> bool:
    """True only when this run has not already consumed the rung's budget.

    ``run_id`` is optional only for the pure decision helpers retained for
    backwards-compatible unit use. The retry driver always supplies it.
    """
    key = keyed_effect_key(run_id, decision) if run_id is not None else decision.effect_key
    return key not in effects


def scan_ac_coverage(specs_dir: Path, ac_text: str) -> tuple[str, ...]:
    """Return done/in-progress specs that contain the disputed AC verbatim.

    This intentionally performs no inference: a partial phrase, semantic
    similarity, or a draft spec is not coverage evidence.
    """
    if not ac_text.strip():
        return ()
    matches: list[str] = []
    for path in sorted(Path(specs_dir).glob("SPEC-*.md")):
        text = path.read_text(encoding="utf-8")
        status = re.search(r"^status:\s*(done|in_progress)\s*$", text, re.MULTILINE)
        spec_id = re.search(r"^id:\s*(SPEC-[A-Za-z0-9-]+)\s*$", text, re.MULTILINE)
        if status and spec_id and ac_text in text:
            matches.append(spec_id.group(1))
    return tuple(matches)


def decide_from_parent_context(
    _outcome: Any, context: Mapping[str, Any],
) -> ResilienceDecision | None:
    """Translate a parent-classified terminal outcome into one bounded rung.

    Classification and all side-effecting work remain parent-owned. This helper
    merely consumes the parent-provided evidence and returns the next recorded
    allowance. A missing or malformed class deliberately returns ``None`` so
    the normal terminal route remains fail-closed.
    """
    failure_class = context.get("resilience_failure_class")
    try:
        if failure_class == "verifier_fail":
            return decide_verifier_fail(
                context.get("previous_failed_acs", ()), context.get("failed_acs", ()),
                max_rounds=int(context.get("resilience_max_rounds", 2)),
            )
        if failure_class == "premise_dispute":
            ac_text = context.get("disputed_ac")
            if not isinstance(ac_text, str) or not ac_text.strip():
                return None
            covered_by = context.get("covered_by")
            specs_dir = context.get("specs_dir")
            if not covered_by and isinstance(specs_dir, (str, Path)):
                coverage = scan_ac_coverage(Path(specs_dir), ac_text)
                covered_by = coverage[0] if coverage else None
            return decide_premise_dispute(
                ac_text,
                covered_by=covered_by if isinstance(covered_by, str) else None,
                runtime_gate=context.get("runtime_gate") if isinstance(context.get("runtime_gate"), str) else None,
                amendment=context.get("amendment") if isinstance(context.get("amendment"), str) else None,
                reviewer=str(context.get("reviewer", "veto")),
                enabled=bool(context.get("resilience_premise_enabled", True)),
            )
        if failure_class == "evidence_gap":
            return decide_evidence_gap(
                artifact_found=bool(context.get("artifact_found", False)),
                passes_used=int(context.get("evidence_passes_used", 0)),
                max_passes=int(context.get("resilience_max_passes", 1)),
            )
        if failure_class == "transport_stall":
            raw_failures = context.get("transport_failures", ())
            if not isinstance(raw_failures, Iterable) or isinstance(raw_failures, (str, bytes)):
                return None
            failures = list(raw_failures)
            if not all(
                isinstance(item, tuple) and len(item) == 2 and all(isinstance(part, str) for part in item)
                for item in failures
            ):
                return None
            return decide_transport_stall(
                failures, max_rebinds=int(context.get("resilience_max_rebinds", 2)),
            )
    except (OSError, TypeError, ValueError):
        # Invalid parent evidence is never a reason to renew a ladder.
        return None
    return None
