"""Durable, harness-agnostic completion reconciliation for kickoff parents.

SPEC-234 deliberately keeps harness calls behind :class:`KickoffRuntimeAdapter`.
The persisted ``KickoffResolutionState`` is authoritative; a heartbeat is only an
observation that can cause a parent to call :func:`reconcile` again.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Protocol


class ResolutionPhase(str, Enum):
    WORKER_RUNNING = "worker_running"
    WORKER_COMPLETED = "worker_completed"
    VERIFIER_DISPATCHING = "verifier_dispatching"
    VERIFIER_DISPATCHED = "verifier_dispatched"
    CONTROLLER_RESOLUTION_REQUIRED = "controller_resolution_required"


_TERMINAL_PHASES = frozenset({
    ResolutionPhase.VERIFIER_DISPATCHED,
    ResolutionPhase.CONTROLLER_RESOLUTION_REQUIRED,
})


@dataclass(frozen=True)
class CompletionDelivery:
    """Normalized completion from either a callback or a polling adapter."""

    key: str
    source: str


@dataclass(frozen=True)
class KickoffResolutionState:
    """JSON-safe durable state, advanced only through monotonic phases."""

    run_id: str
    phase: ResolutionPhase = ResolutionPhase.WORKER_RUNNING
    completion_key: str | None = None
    verifier_dispatch_key: str | None = None
    poll_attempts: int = 0
    controller_reason: str | None = None

    def as_record(self) -> dict[str, object]:
        return asdict(self)


class KickoffRuntimeAdapter(Protocol):
    """The small portability boundary a kickoff parent must provide.

    ``save_state`` must durably replace the state before returning.  The
    dispatcher must treat ``idempotency_key`` as a stable exactly-once key: a
    retry after a crash may call it again, but it may launch at most one
    independent verifier.  ``poll_worker_completion`` is a bounded fallback;
    it returns ``None`` when no completion is observable yet.
    """

    def load_state(self, run_id: str) -> KickoffResolutionState | None: ...

    def save_state(self, state: KickoffResolutionState) -> None: ...

    def poll_worker_completion(self, run_id: str) -> CompletionDelivery | None: ...

    def dispatch_verifier(self, run_id: str, *, idempotency_key: str) -> None: ...

    def schedule_reconciliation(self, run_id: str) -> None: ...


def _persist(adapter: KickoffRuntimeAdapter, state: KickoffResolutionState) -> KickoffResolutionState:
    adapter.save_state(state)
    return state


def _dispatch_key(run_id: str, completion_key: str) -> str:
    return f"verifier:{run_id}:{completion_key}"


def reconcile(
    run_id: str,
    adapter: KickoffRuntimeAdapter,
    *,
    completion: CompletionDelivery | None = None,
    max_poll_attempts: int = 1,
) -> KickoffResolutionState:
    """Persist and resolve completion before a parent can return idle/status.

    A parent calls this for callbacks, status requests, terminal heartbeats, and
    scheduled polling.  Calling it after a crash is safe: persisted
    ``VERIFIER_DISPATCHING`` reuses the same dispatch key.  Launch errors become
    a controller-owned terminal route; this reducer never runs a verifier.
    """

    if max_poll_attempts < 0:
        raise ValueError("max_poll_attempts must be non-negative")
    state = adapter.load_state(run_id) or KickoffResolutionState(run_id=run_id)

    if state.phase in _TERMINAL_PHASES:
        return state

    if completion is None and state.phase is ResolutionPhase.WORKER_RUNNING:
        if state.poll_attempts >= max_poll_attempts:
            adapter.schedule_reconciliation(run_id)
            return state
        completion = adapter.poll_worker_completion(run_id)
        state = _persist(
            adapter,
            KickoffResolutionState(
                **{**state.as_record(), "poll_attempts": state.poll_attempts + 1}
            ),
        )
        if completion is None:
            adapter.schedule_reconciliation(run_id)
            return state

    if completion is not None and state.phase is ResolutionPhase.WORKER_RUNNING:
        if not completion.key:
            raise ValueError("completion delivery requires a stable idempotency key")
        state = _persist(
            adapter,
            KickoffResolutionState(
                run_id=run_id,
                phase=ResolutionPhase.WORKER_COMPLETED,
                completion_key=completion.key,
                poll_attempts=state.poll_attempts,
            ),
        )

    if state.phase is ResolutionPhase.WORKER_COMPLETED:
        assert state.completion_key  # guaranteed by the transition above
        state = _persist(
            adapter,
            KickoffResolutionState(
                **{
                    **state.as_record(),
                    "phase": ResolutionPhase.VERIFIER_DISPATCHING,
                    "verifier_dispatch_key": _dispatch_key(run_id, state.completion_key),
                }
            ),
        )

    if state.phase is ResolutionPhase.VERIFIER_DISPATCHING:
        assert state.verifier_dispatch_key
        try:
            adapter.dispatch_verifier(run_id, idempotency_key=state.verifier_dispatch_key)
        except Exception:
            # Deliberately retain no harness exception text in durable state.
            # The parent records sanitized evidence then enters its existing
            # controller-backed unblock/terminal-resolution protocol.
            return _persist(
                adapter,
                KickoffResolutionState(
                    **{
                        **state.as_record(),
                        "phase": ResolutionPhase.CONTROLLER_RESOLUTION_REQUIRED,
                        "controller_reason": "verifier_launch_failed",
                    }
                ),
            )
        return _persist(
            adapter,
            KickoffResolutionState(
                **{**state.as_record(), "phase": ResolutionPhase.VERIFIER_DISPATCHED}
            ),
        )

    return state
