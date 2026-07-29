#!/usr/bin/env python3
"""
SPEC-042 retry loop — wires the outcome router (SPEC-034) into the LOOP.md
Step 7 -> Step 11 retry cycle.

Responsibility split:

  * ``outcome_router``    — **pure** policy evaluation. Given an ``Outcome`` and
                            a policy table, returns a ``RoutingDecision``.
  * ``retry_loop``        — **effectful** driver. Runs an attempt, consults the
                            circuit breaker and router, sleeps for backoff,
                            emits structured events, and re-invokes the
                            attempt until a terminal action is returned.
  * ``LOOP.md Step 11``   — prose describing the retry flow; the actual
                            control flow is implemented here so it can be
                            unit-tested.

Events emitted to ``events_logger.emit`` (duck-typed; may be ``None``):

  * ``circuit_breaker_checked``  — before every attempt, with ``tripped`` bool.
  * ``handler_outcome_received`` — after each attempt completes; carries
                                    ``handler_status`` / ``router_outcome``.
  * ``retry_decided``            — whenever the router returns a retryable
                                    action. Fields: ``outcome``,
                                    ``retry_count``, ``max_retries``,
                                    ``backoff_seconds``, ``action``.
  * ``retry_backoff_start``      — before sleeping.
  * ``retry_backoff_end``        — after sleeping.
  * ``spec_aborted``             — terminal ABORT/BLOCK; carries
                                    ``final_outcome`` and ``total_retries``.
  * ``spec_escalated``           — terminal ESCALATE; carries ``final_outcome``
                                    and ``total_retries``.

A ``RetryLoopResult`` is returned describing why the loop exited. It does NOT
raise — terminal failures are signalled via ``result.terminal_action``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from outcome_router import (
    Outcome,
    OutcomePolicy,
    RoutingAction,
    RoutingDecision,
    check_circuit_breaker,
    handler_outcome_to_router_outcome,
    route_outcome,
)

# SPEC-046 — prior_attempts enforcement gate. Imported lazily-safe (pure
# module, no side effects) so this file keeps working when the helper is
# absent in forks / partial deployments.
try:
    from spec_frontmatter import (
        DEFAULT_MAX_PRIOR_ATTEMPTS,
        FrontmatterError,
        append_prior_attempt,
        parse_spec_file,
        tracking_enabled,
    )
except ImportError:  # pragma: no cover — defensive
    DEFAULT_MAX_PRIOR_ATTEMPTS = 10
    FrontmatterError = ValueError  # type: ignore[assignment,misc]
    append_prior_attempt = None  # type: ignore[assignment]
    parse_spec_file = None  # type: ignore[assignment]

    def tracking_enabled(_frontmatter: Dict[str, Any]) -> bool:  # type: ignore[no-redef]
        return True


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass
class RetryLoopResult:
    """Outcome of :func:`execute_with_retry`.

    ``terminal_action`` is always one of ``NEXT``, ``ABORT``, ``BLOCK``, or
    ``ESCALATE``. Retryable actions never leak out — the loop keeps running
    until one of these is reached (or ``max_total_attempts`` is hit, which
    forces an ABORT with ``exhausted=True``).
    """

    terminal_action: RoutingAction
    final_outcome: Outcome
    attempts: int                          # number of attempts actually run
    retry_count: int = 0                   # attempts beyond the first
    decisions: list = field(default_factory=list)  # list[RoutingDecision]
    handler_outcomes: list = field(default_factory=list)  # list[Outcome-dataclass or similar]
    exhausted: bool = False


# ---------------------------------------------------------------------------
# Public driver
# ---------------------------------------------------------------------------


def execute_with_retry(
    attempt_fn: Callable[[int, Dict[str, Any]], Any],
    policies: Dict[Outcome, OutcomePolicy],
    *,
    circuit_breaker: Any = None,
    events_logger: Any = None,
    spec_id: Optional[str] = None,
    max_total_attempts: int = 16,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
    attempt_context: Optional[Dict[str, Any]] = None,
    spec_file: Optional[Path] = None,
    session_id: Optional[str] = None,
    prior_attempts_recorder: Optional[
        Callable[[Path, Dict[str, Any]], Dict[str, Any]]
    ] = None,
    max_prior_attempts: int = DEFAULT_MAX_PRIOR_ATTEMPTS,
) -> RetryLoopResult:
    """Run ``attempt_fn`` under outcome-router policies until a terminal action.

    Parameters
    ----------
    attempt_fn:
        Callable invoked once per attempt. Signature
        ``(attempt_index: int, context: dict) -> handler_outcome``.
        ``handler_outcome`` should be a ``handler_registry.Outcome`` dataclass
        (or any object with a ``status`` attribute). The dict ``context`` is
        seeded from ``attempt_context`` and mutated between attempts to carry
        forward retry state (see ``RoutingDecision.context``).
    policies:
        Active policy table produced by ``outcome_router.load_policies``.
    circuit_breaker:
        Optional circuit-breaker instance with ``.is_triggered()``. R6 —
        ``check_circuit_breaker`` runs BEFORE every attempt / route call.
    events_logger:
        Optional duck-typed emitter (``.emit(event_type, spec_id=?, **fields)``).
    spec_id:
        Optional spec identifier, forwarded to every event for traceability.
    max_total_attempts:
        Defensive safety net. If the policy table over-configures retries
        the loop still terminates. Default 16.
    sleep_fn / time_fn:
        Injection points for tests — override so AC3's "≥4s" assertion uses
        a fast fake clock while the production path uses ``time.sleep``.
    attempt_context:
        Initial failure context carried into the first attempt. Each retry
        merges ``RoutingDecision.context`` back into this dict.
    spec_file:
        Optional path to the spec file. When supplied (and
        ``prior_attempts_tracking`` is not disabled in the spec's frontmatter),
        the SPEC-046 retry precondition gate fires before each RETRY / REPLAN /
        SUMMARIZE_AND_RETRY jump: the prior attempt is appended to the spec's
        ``prior_attempts:`` list. If the write fails the retry is converted to
        ``ABORT`` with a ``prior_attempts_write_failed`` event — retries from
        here are blocked until the spec can be parsed.
    session_id:
        Optional session identifier recorded on each ``prior_attempts`` entry.
    prior_attempts_recorder:
        Injection seam for tests. Defaults to
        :func:`spec_frontmatter.append_prior_attempt`. Callable signature is
        ``(spec_file, entry) -> result_dict`` (mirror of the production helper).
    max_prior_attempts:
        Maximum entries to keep in the spec's frontmatter before rotating to
        the sibling archive file. Defaults to ``DEFAULT_MAX_PRIOR_ATTEMPTS`` (10).

    Returns
    -------
    RetryLoopResult
    """
    context: Dict[str, Any] = dict(attempt_context or {})

    decisions: list = []
    handler_outcomes: list = []
    retry_count = 0
    last_router_outcome: Outcome = Outcome.FATAL

    for attempt in range(max_total_attempts):
        # ------------------------------------------------------------------
        # R6: circuit breaker first. If tripped BEFORE we even run an
        # attempt, short-circuit to ABORT — no handler invocation, no
        # policy lookup, no retry_decided event.
        # ------------------------------------------------------------------
        tripped = check_circuit_breaker(circuit_breaker)
        _emit(
            events_logger,
            "circuit_breaker_checked",
            spec_id,
            attempt=attempt,
            tripped=tripped,
        )
        if tripped:
            result = RetryLoopResult(
                terminal_action=RoutingAction.ABORT,
                final_outcome=last_router_outcome,
                attempts=attempt,
                retry_count=retry_count,
                decisions=decisions,
                handler_outcomes=handler_outcomes,
                exhausted=False,
            )
            _emit(
                events_logger,
                "spec_aborted",
                spec_id,
                reason="circuit_breaker_tripped",
                final_outcome=last_router_outcome.value,
                total_retries=retry_count,
            )
            return result

        # ------------------------------------------------------------------
        # Run the attempt.
        # ------------------------------------------------------------------
        handler_outcome = attempt_fn(attempt, context)
        handler_outcomes.append(handler_outcome)

        router_outcome = handler_outcome_to_router_outcome(handler_outcome)
        last_router_outcome = router_outcome
        _emit(
            events_logger,
            "handler_outcome_received",
            spec_id,
            attempt=attempt,
            handler_status=getattr(handler_outcome, "status", None),
            next_action=getattr(handler_outcome, "next_action", None),
            router_outcome=router_outcome.value,
        )

        # ------------------------------------------------------------------
        # Ask the router what to do next.
        # ------------------------------------------------------------------
        decision: RoutingDecision = route_outcome(
            outcome=router_outcome,
            policies=policies,
            attempt=retry_count,
            failure_context=context,
            circuit_breaker=circuit_breaker,  # router also does its own check
            event_log=events_logger,
        )
        decisions.append(decision)

        # Merge decision.context back into our context so the next attempt
        # sees the latest failure details.
        if decision.context:
            context.update(decision.context)

        action = decision.action

        # ------------------------------------------------------------------
        # Terminal actions.
        # ------------------------------------------------------------------
        if action == RoutingAction.NEXT:
            return RetryLoopResult(
                terminal_action=action,
                final_outcome=router_outcome,
                attempts=attempt + 1,
                retry_count=retry_count,
                decisions=decisions,
                handler_outcomes=handler_outcomes,
                exhausted=False,
            )
        if action in (RoutingAction.ABORT, RoutingAction.BLOCK):
            _emit(
                events_logger,
                "spec_aborted",
                spec_id,
                reason=(
                    "circuit_breaker_tripped"
                    if action == RoutingAction.BLOCK
                    else "policy_abort"
                ),
                final_outcome=router_outcome.value,
                total_retries=retry_count,
                exhausted=decision.exhausted,
            )
            return RetryLoopResult(
                terminal_action=action,
                final_outcome=router_outcome,
                attempts=attempt + 1,
                retry_count=retry_count,
                decisions=decisions,
                handler_outcomes=handler_outcomes,
                exhausted=decision.exhausted,
            )
        if action == RoutingAction.ESCALATE:
            _emit(
                events_logger,
                "spec_escalated",
                spec_id,
                final_outcome=router_outcome.value,
                total_retries=retry_count,
            )
            return RetryLoopResult(
                terminal_action=action,
                final_outcome=router_outcome,
                attempts=attempt + 1,
                retry_count=retry_count,
                decisions=decisions,
                handler_outcomes=handler_outcomes,
                exhausted=False,
            )

        # ------------------------------------------------------------------
        # Retryable actions: RETRY, REPLAN, SUMMARIZE_AND_RETRY.
        # Before we can jump back to Step 7, SPEC-046 requires the prior
        # attempt to be recorded on the spec's frontmatter. If the gate
        # fails (parse error, disk error) we CONVERT the action to ABORT so
        # the loop never retries without an audit trail.
        # ------------------------------------------------------------------
        gate_result = _run_prior_attempts_gate(
            spec_file=spec_file,
            handler_outcome=handler_outcome,
            router_outcome=router_outcome,
            attempt_index=attempt,
            retry_count=retry_count,
            session_id=session_id,
            spec_id=spec_id,
            events_logger=events_logger,
            recorder=prior_attempts_recorder,
            max_entries=max_prior_attempts,
        )
        if gate_result == "failed":
            # Convert this retry to ABORT. Fall through to the ABORT handler
            # by running the same emission path as a policy-driven abort.
            _emit(
                events_logger,
                "spec_aborted",
                spec_id,
                reason="prior_attempts_write_failed",
                final_outcome=router_outcome.value,
                total_retries=retry_count,
                exhausted=False,
            )
            return RetryLoopResult(
                terminal_action=RoutingAction.ABORT,
                final_outcome=router_outcome,
                attempts=attempt + 1,
                retry_count=retry_count,
                decisions=decisions,
                handler_outcomes=handler_outcomes,
                exhausted=False,
            )

        policy = policies.get(router_outcome)
        max_retries = (
            policy.retry_policy.max_retries
            if policy is not None and policy.retry_policy is not None
            else 0
        )
        _emit(
            events_logger,
            "retry_decided",
            spec_id,
            outcome=router_outcome.value,
            retry_count=retry_count,
            max_retries=max_retries,
            backoff_seconds=decision.wait_seconds,
            action=action.value,
        )

        if decision.wait_seconds > 0:
            started_at = time_fn()
            _emit(
                events_logger,
                "retry_backoff_start",
                spec_id,
                attempt=attempt,
                backoff_seconds=decision.wait_seconds,
            )
            sleep_fn(decision.wait_seconds)
            elapsed = time_fn() - started_at
            _emit(
                events_logger,
                "retry_backoff_end",
                spec_id,
                attempt=attempt,
                backoff_seconds=decision.wait_seconds,
                elapsed_seconds=elapsed,
            )

        retry_count += 1

    # ----------------------------------------------------------------------
    # Safety net: ran out of attempts without a terminal action. Abort.
    # ----------------------------------------------------------------------
    _emit(
        events_logger,
        "spec_aborted",
        spec_id,
        reason="max_total_attempts_exceeded",
        final_outcome=last_router_outcome.value,
        total_retries=retry_count,
        exhausted=True,
    )
    return RetryLoopResult(
        terminal_action=RoutingAction.ABORT,
        final_outcome=last_router_outcome,
        attempts=max_total_attempts,
        retry_count=retry_count,
        decisions=decisions,
        handler_outcomes=handler_outcomes,
        exhausted=True,
    )


# ---------------------------------------------------------------------------
# SPEC-046 — prior_attempts retry precondition gate
# ---------------------------------------------------------------------------


def _derive_failure_hint(
    handler_outcome: Any,
    router_outcome: Outcome,
) -> str:
    """Turn a handler outcome into a short, deterministic failure hint.

    No LLM calls — the spec's "Out of Scope" section explicitly rules that out.
    We concatenate the router outcome, the handler status, and any error_type
    from handler metrics. The result is one line suitable for a retry agent to
    read before re-attempting the spec.
    """
    status = getattr(handler_outcome, "status", None) or "unknown"
    metrics = getattr(handler_outcome, "metrics", {}) or {}
    parts: List[str] = [f"{router_outcome.value}: {status}"]

    error_type = metrics.get("error_type") if isinstance(metrics, dict) else None
    if error_type:
        parts.append(f"error_type={error_type}")

    error_message = metrics.get("error") if isinstance(metrics, dict) else None
    if error_message and not error_type:
        # Trim the message so the hint stays a short single line.
        snippet = str(error_message).strip().splitlines()[0][:160]
        if snippet:
            parts.append(snippet)

    next_action = getattr(handler_outcome, "next_action", None)
    if next_action:
        parts.append(f"next_action={next_action}")

    return " | ".join(parts)


def _derive_events_summary(handler_outcome: Any) -> str:
    """Derive the ``events`` field for a prior_attempts entry.

    The retry loop doesn't receive the raw event stream — it only sees the
    handler's terminal ``Outcome``. We summarise that into a human-readable
    blob: status, next_action, and any artifact / metrics keys.
    """
    status = getattr(handler_outcome, "status", None) or "unknown"
    next_action = getattr(handler_outcome, "next_action", None) or ""
    artifacts = getattr(handler_outcome, "artifacts", None) or []
    metrics = getattr(handler_outcome, "metrics", {}) or {}

    fragments: List[str] = [f"status={status}"]
    if next_action:
        fragments.append(f"next_action={next_action}")
    if artifacts:
        fragments.append(f"artifacts={len(artifacts)}")
    if isinstance(metrics, dict) and metrics:
        # Keep it compact — just the keys to aid retrospection.
        fragments.append("metrics=" + ",".join(sorted(str(k) for k in metrics.keys())))

    return "; ".join(fragments)


def _run_prior_attempts_gate(
    *,
    spec_file: Optional[Path],
    handler_outcome: Any,
    router_outcome: Outcome,
    attempt_index: int,
    retry_count: int,
    session_id: Optional[str],
    spec_id: Optional[str],
    events_logger: Any,
    recorder: Optional[Callable[[Path, Dict[str, Any]], Dict[str, Any]]],
    max_entries: int,
) -> str:
    """Fire the SPEC-046 retry precondition gate.

    Returns one of:

    * ``"skipped"`` — no spec file supplied, or spec opts out via
      ``prior_attempts_tracking: false``.
    * ``"recorded"`` — prior attempt successfully appended.
    * ``"failed"``   — gate failed; caller must convert to ABORT.
    """
    if spec_file is None:
        return "skipped"

    # Opt-out check runs before any write — parse first, honour the flag, bail
    # if disabled. If parsing fails here the gate itself is considered failed
    # because we cannot confirm whether tracking is on or off.
    if parse_spec_file is None or append_prior_attempt is None:
        return "skipped"  # pragma: no cover — defensive (import failure)

    try:
        parsed = parse_spec_file(spec_file)
    except FrontmatterError as exc:
        _emit(
            events_logger,
            "prior_attempts_write_failed",
            spec_id,
            reason="frontmatter_parse_error",
            error=str(exc),
            spec_file=str(spec_file),
        )
        return "failed"

    if not tracking_enabled(parsed.frontmatter):
        return "skipped"

    entry = {
        "attempt": retry_count + 1,
        "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_id": session_id or "",
        "outcome": router_outcome.value,
        "events": _derive_events_summary(handler_outcome),
        "failure_hint": _derive_failure_hint(handler_outcome, router_outcome),
    }

    record_fn = recorder or append_prior_attempt
    try:
        if recorder is not None:
            result = recorder(spec_file, entry)
        else:
            result = record_fn(spec_file, entry, max_entries=max_entries)
    except Exception as exc:  # noqa: BLE001 — we must convert ALL errors to ABORT
        _emit(
            events_logger,
            "prior_attempts_write_failed",
            spec_id,
            reason="write_error",
            error=f"{type(exc).__name__}: {exc}",
            spec_file=str(spec_file),
        )
        return "failed"

    _emit(
        events_logger,
        "prior_attempts_recorded",
        spec_id,
        spec_file=str(spec_file),
        attempt_number=(
            result.get("attempt_number")
            if isinstance(result, dict)
            else retry_count + 1
        ),
        frontmatter_count=(
            result.get("frontmatter_count") if isinstance(result, dict) else None
        ),
        archived_count=(
            result.get("archived_count") if isinstance(result, dict) else 0
        ),
    )
    return "recorded"


# ---------------------------------------------------------------------------
# Event emission helper (duck-typed)
# ---------------------------------------------------------------------------


def _emit(events_logger: Any, event_type: str, spec_id: Optional[str], **fields: Any) -> None:
    """Best-effort event emission — no-op if logger is None or lacks .emit.

    Matches the dispatch.py contract so the retry loop never crashes over a
    logging hiccup.
    """
    if events_logger is None:
        return
    emit = getattr(events_logger, "emit", None)
    if emit is None:
        return
    try:
        emit(event_type, spec_id=spec_id, **fields)
    except Exception:
        pass
