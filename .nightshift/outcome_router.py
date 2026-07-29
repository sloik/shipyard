#!/usr/bin/env python3
"""
Retry & outcome routing for Nightshift specs (SPEC-034).

Typed outcome vocabulary, configurable routing policies, retry backoff
computation, and integration points with goal gates and the circuit breaker.

The router is pure evaluation logic -- it computes what to do but does not
execute it.  The caller reads the RoutingDecision and acts accordingly.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Optional integration imports
# ---------------------------------------------------------------------------

try:
    from goal_gate import GateResult
except ImportError:  # pragma: no cover - standalone usage
    GateResult = Any  # type: ignore[misc,assignment]

try:
    from loop_events import RunEventLog
except ImportError:  # pragma: no cover - standalone usage
    RunEventLog = Any  # type: ignore[misc,assignment]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Outcome(enum.Enum):
    """Vocabulary of step outcomes."""

    SUCCESS = "SUCCESS"
    TEST_FAIL = "TEST_FAIL"
    BUILD_FAIL = "BUILD_FAIL"
    TIMEOUT = "TIMEOUT"
    CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    FATAL = "FATAL"


class RoutingAction(enum.Enum):
    """Actions the router can prescribe."""

    NEXT = "NEXT"
    RETRY = "RETRY"
    REPLAN = "REPLAN"
    SUMMARIZE_AND_RETRY = "SUMMARIZE_AND_RETRY"
    ABORT = "ABORT"
    BLOCK = "BLOCK"
    # SPEC-042: terminal "mark for human review" action. Like ABORT, it stops
    # the retry loop, but carries the semantic "this needs human attention"
    # rather than "give up".
    ESCALATE = "ESCALATE"


_RETRYABLE_ACTIONS = {
    RoutingAction.RETRY,
    RoutingAction.REPLAN,
    RoutingAction.SUMMARIZE_AND_RETRY,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RetryPolicy:
    """Controls retry timing."""

    max_retries: int = 3
    backoff_type: str = "exponential"  # "none" | "linear" | "exponential"
    backoff_base_s: float = 5.0
    max_backoff_s: float = 120.0

    def __post_init__(self) -> None:
        if self.backoff_type not in ("none", "linear", "exponential"):
            raise ValueError(
                f"backoff_type must be 'none', 'linear', or 'exponential', "
                f"got {self.backoff_type!r}"
            )

    def compute_delay(self, attempt: int) -> float:
        """Return the delay in seconds for the given 0-indexed attempt."""
        if self.backoff_type == "none":
            return 0.0
        if self.backoff_type == "linear":
            return self.backoff_base_s * (attempt + 1)
        # exponential
        return min(self.backoff_base_s * (2 ** attempt), self.max_backoff_s)


@dataclass
class OutcomePolicy:
    """Maps an outcome to a routing action and retry policy."""

    outcome: Outcome
    action: RoutingAction
    retry_policy: Optional[RetryPolicy] = None

    def __post_init__(self) -> None:
        if self.action in _RETRYABLE_ACTIONS and self.retry_policy is None:
            raise ValueError(
                f"action {self.action.value} requires a retry_policy, but None was given"
            )


@dataclass
class RoutingDecision:
    """Output of the router."""

    action: RoutingAction
    wait_seconds: float = 0.0
    context: Dict[str, Any] = field(default_factory=dict)
    retries_remaining: int = 0
    exhausted: bool = False


# ---------------------------------------------------------------------------
# Default policies
# ---------------------------------------------------------------------------

DEFAULT_POLICIES: Dict[Outcome, OutcomePolicy] = {
    Outcome.SUCCESS: OutcomePolicy(
        outcome=Outcome.SUCCESS,
        action=RoutingAction.NEXT,
    ),
    Outcome.TEST_FAIL: OutcomePolicy(
        outcome=Outcome.TEST_FAIL,
        action=RoutingAction.REPLAN,
        retry_policy=RetryPolicy(
            max_retries=2, backoff_type="exponential",
            backoff_base_s=5.0, max_backoff_s=60.0,
        ),
    ),
    Outcome.BUILD_FAIL: OutcomePolicy(
        outcome=Outcome.BUILD_FAIL,
        action=RoutingAction.RETRY,
        retry_policy=RetryPolicy(
            max_retries=3, backoff_type="exponential",
            backoff_base_s=5.0, max_backoff_s=60.0,
        ),
    ),
    Outcome.TIMEOUT: OutcomePolicy(
        outcome=Outcome.TIMEOUT,
        action=RoutingAction.RETRY,
        retry_policy=RetryPolicy(max_retries=1, backoff_type="none"),
    ),
    Outcome.CONTEXT_OVERFLOW: OutcomePolicy(
        outcome=Outcome.CONTEXT_OVERFLOW,
        action=RoutingAction.SUMMARIZE_AND_RETRY,
        retry_policy=RetryPolicy(max_retries=1, backoff_type="none"),
    ),
    Outcome.REVIEW_REJECTED: OutcomePolicy(
        outcome=Outcome.REVIEW_REJECTED,
        action=RoutingAction.REPLAN,
        retry_policy=RetryPolicy(
            max_retries=2, backoff_type="linear",
            backoff_base_s=5.0, max_backoff_s=30.0,
        ),
    ),
    Outcome.FATAL: OutcomePolicy(
        outcome=Outcome.FATAL,
        action=RoutingAction.ABORT,
    ),
}


# ---------------------------------------------------------------------------
# Circuit breaker integration
# ---------------------------------------------------------------------------


def check_circuit_breaker(breaker: object) -> bool:
    """Return True if the breaker exists and is triggered."""
    if breaker is None:
        return False
    return breaker.is_triggered()  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Goal gate integration
# ---------------------------------------------------------------------------


def gate_result_to_outcome(gate_result: Any) -> Outcome:
    """Map a GateResult to an Outcome by inspecting condition and action.

    Mapping rules:
    - on_fail == "block" -> FATAL
    - on_fail == "skip"  -> SUCCESS
    - condition contains "tests_pass" or "test_" -> TEST_FAIL
    - condition contains "build_clean" -> BUILD_FAIL
    - condition contains "review_approved" -> REVIEW_REJECTED
    - default -> BUILD_FAIL
    """
    action = getattr(gate_result, "action", None) or ""
    condition = getattr(gate_result, "condition", "") or ""

    if action == "block":
        return Outcome.FATAL
    if action == "skip":
        return Outcome.SUCCESS

    if "tests_pass" in condition or "test_" in condition:
        return Outcome.TEST_FAIL
    if "build_clean" in condition:
        return Outcome.BUILD_FAIL
    if "review_approved" in condition:
        return Outcome.REVIEW_REJECTED

    return Outcome.BUILD_FAIL


# ---------------------------------------------------------------------------
# Handler-registry integration (SPEC-042)
# ---------------------------------------------------------------------------

# Mapping of handler ``Outcome.status`` strings (see SPEC-033 / SPEC-041
# ``handler_registry.Outcome``) to the router's own ``Outcome`` enum. Values
# outside this table fall through to ``Outcome.FATAL`` (typical policy default
# ABORT). Handlers may signal a more specific failure mode via ``next_action``;
# when set to a value matching an ``Outcome`` name, it overrides the status
# mapping (e.g. ``next_action="TEST_FAIL"``).
_HANDLER_STATUS_TO_OUTCOME: Dict[str, Outcome] = {
    "success": Outcome.SUCCESS,
    "failure": Outcome.TEST_FAIL,
    "failed": Outcome.TEST_FAIL,
    "blocked": Outcome.FATAL,
    "skipped": Outcome.SUCCESS,
    "build_fail": Outcome.BUILD_FAIL,
    "build_failed": Outcome.BUILD_FAIL,
    "timeout": Outcome.TIMEOUT,
    "context_overflow": Outcome.CONTEXT_OVERFLOW,
    "review_rejected": Outcome.REVIEW_REJECTED,
    "fatal": Outcome.FATAL,
}


def handler_outcome_to_router_outcome(handler_outcome: Any) -> Outcome:
    """Map a handler-registry ``Outcome`` dataclass to a router ``Outcome`` enum.

    The handler-registry ``Outcome`` (SPEC-033 / SPEC-041) uses a free-form
    ``status`` string (``"success"``, ``"failure"``, ``"blocked"``, ...) plus
    an optional ``next_action`` hint. SPEC-042 needs a router-side
    ``Outcome`` enum value to pass to ``route_outcome()``.

    Mapping rules (in priority order):
      1. ``handler_outcome is None`` -> ``Outcome.FATAL`` (defensive default).
      2. ``next_action`` naming an ``Outcome`` (e.g. ``"TEST_FAIL"``) wins.
      3. ``status`` looked up in ``_HANDLER_STATUS_TO_OUTCOME`` (case-insensitive).
      4. Unknown status -> ``Outcome.FATAL``. The caller's policy decides
         how to treat an unrecognised outcome; by default
         ``route_outcome`` routes unmatched outcomes to ``ABORT``.
    """
    if handler_outcome is None:
        return Outcome.FATAL

    # 2. next_action override — explicit signal from a smarter handler.
    next_action = getattr(handler_outcome, "next_action", None)
    if isinstance(next_action, str):
        key = next_action.strip().upper()
        if key in _OUTCOME_NAMES:
            return _OUTCOME_NAMES[key]

    # 3. status string lookup.
    status = getattr(handler_outcome, "status", None)
    if isinstance(status, str):
        return _HANDLER_STATUS_TO_OUTCOME.get(status.lower(), Outcome.FATAL)

    # 4. anything else -> FATAL.
    return Outcome.FATAL


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------

_ACTION_NAMES = {a.value.lower(): a for a in RoutingAction}
_OUTCOME_NAMES = {o.value: o for o in Outcome}


def _parse_retry_block(raw: Optional[Dict[str, Any]]) -> Optional[RetryPolicy]:
    """Parse a retry: {...} block from YAML config into a RetryPolicy."""
    if raw is None:
        return None
    return RetryPolicy(
        max_retries=int(raw.get("max_retries", 3)),
        backoff_type=str(raw.get("backoff", raw.get("backoff_type", "exponential"))),
        backoff_base_s=float(raw.get("base_s", raw.get("backoff_base_s", 5.0))),
        max_backoff_s=float(raw.get("max_s", raw.get("max_backoff_s", 120.0))),
    )


def _parse_policy_entry(raw: Dict[str, Any]) -> OutcomePolicy:
    """Parse a single policy entry dict into an OutcomePolicy."""
    outcome_str = str(raw["outcome"]).upper()
    if outcome_str not in _OUTCOME_NAMES:
        raise ValueError(f"unknown outcome {outcome_str!r}")
    outcome = _OUTCOME_NAMES[outcome_str]

    action_str = str(raw["action"]).lower()
    if action_str not in _ACTION_NAMES:
        raise ValueError(f"unknown action {action_str!r}")
    action = _ACTION_NAMES[action_str]

    retry_policy = _parse_retry_block(raw.get("retry"))

    return OutcomePolicy(outcome=outcome, action=action, retry_policy=retry_policy)


def load_policies(
    spec_frontmatter: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[Outcome, OutcomePolicy]:
    """Load outcome routing policies from spec or config.

    Spec-level replaces config entirely (not merge).  If the spec defines
    any ``outcome_routing``, config defaults are ignored.  If neither is
    present, built-in DEFAULT_POLICIES are returned.
    """
    raw_entries: Optional[List[Dict[str, Any]]] = None

    # Spec frontmatter: accept either key (SPEC-034 canonical, SPEC-042 alias).
    if "outcome_routing" in spec_frontmatter:
        raw_entries = spec_frontmatter["outcome_routing"]
    elif "outcomes" in spec_frontmatter:
        raw_entries = spec_frontmatter["outcomes"]
    else:
        # Config: ``outcome_routing:`` (SPEC-034) or ``outcomes:`` (SPEC-042).
        # If both are present, SPEC-034 wins (stable key). Each is a mapping
        # with a ``defaults:`` list of entries.
        routing_config = config.get("outcome_routing")
        if not isinstance(routing_config, dict):
            routing_config = config.get("outcomes")
        if isinstance(routing_config, dict):
            raw_entries = routing_config.get("defaults")

    if not raw_entries:
        return dict(DEFAULT_POLICIES)

    policies: Dict[Outcome, OutcomePolicy] = {}
    for entry in raw_entries:
        policy = _parse_policy_entry(entry)
        policies[policy.outcome] = policy
    return policies


# ---------------------------------------------------------------------------
# Core routing function
# ---------------------------------------------------------------------------


def route_outcome(
    outcome: Outcome,
    policies: Dict[Outcome, OutcomePolicy],
    attempt: int,
    failure_context: Dict[str, Any],
    circuit_breaker: object = None,
    event_log: object = None,
) -> RoutingDecision:
    """Route a step outcome to a recovery action.

    Parameters
    ----------
    outcome:
        What happened.
    policies:
        The active policy set (from ``load_policies``).
    attempt:
        Current attempt number (0-indexed).
    failure_context:
        Error details to preserve for the next attempt.
    circuit_breaker:
        Optional circuit breaker instance.  If triggered, returns BLOCK.
    event_log:
        Optional ``RunEventLog`` instance.  If provided, emits an
        ``outcome_routed`` event.
    """
    # 1. Circuit breaker check first
    if check_circuit_breaker(circuit_breaker):
        decision = RoutingDecision(action=RoutingAction.BLOCK, context=failure_context)
        _emit_event(event_log, outcome, decision, attempt)
        return decision

    # 2. Look up matching policy; no match -> ABORT
    policy = policies.get(outcome)
    if policy is None:
        decision = RoutingDecision(
            action=RoutingAction.ABORT, context=failure_context,
        )
        _emit_event(event_log, outcome, decision, attempt)
        return decision

    # 3. Non-retryable actions (NEXT, ABORT, BLOCK) -> return immediately
    if policy.action not in _RETRYABLE_ACTIONS:
        decision = RoutingDecision(
            action=policy.action,
            wait_seconds=0.0,
            context=failure_context,
        )
        _emit_event(event_log, outcome, decision, attempt)
        return decision

    # 4. Retryable action: check exhaustion
    retry_policy = policy.retry_policy
    assert retry_policy is not None  # ensured by OutcomePolicy.__post_init__

    if attempt >= retry_policy.max_retries:
        decision = RoutingDecision(
            action=RoutingAction.ABORT,
            context=failure_context,
            exhausted=True,
        )
        _emit_event(event_log, outcome, decision, attempt)
        return decision

    # 5. Compute delay and build decision
    wait_seconds = retry_policy.compute_delay(attempt)
    retries_remaining = retry_policy.max_retries - attempt - 1

    decision = RoutingDecision(
        action=policy.action,
        wait_seconds=wait_seconds,
        context=failure_context,
        retries_remaining=retries_remaining,
    )

    # 6. Emit event
    _emit_event(event_log, outcome, decision, attempt)

    return decision


# ---------------------------------------------------------------------------
# Event emission helper
# ---------------------------------------------------------------------------


def _emit_event(
    event_log: object,
    outcome: Outcome,
    decision: RoutingDecision,
    attempt: int,
) -> None:
    """Emit an outcome_routed event if an event log is available."""
    if event_log is None:
        return
    event_log.emit(  # type: ignore[union-attr]
        "outcome_routed",
        outcome=outcome.value,
        action=decision.action.value,
        attempt=attempt,
        wait_seconds=decision.wait_seconds,
        retries_remaining=decision.retries_remaining,
        exhausted=decision.exhausted,
    )
