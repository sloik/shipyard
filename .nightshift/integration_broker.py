"""Coordinator-owned boundary for serial Nightshift parent integration.

Workers hand this object completed branches and privacy-safe release intents;
they never receive the main checkout or a merge capability.  Keeping the small
wrapper separate makes the ownership boundary explicit for harness adapters.
"""

from __future__ import annotations

import hashlib
import json
import fcntl
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterable, List, Mapping, Optional

from parallel_executor import IntegrationQueueResult, SerializedIntegrationQueue, WorktreeHandle
from verifier_feedback import (
    FeedbackEffect,
    FeedbackRuntimeAdapter,
    FeedbackState,
    NormalizedFeedbackEvent,
)


class IntegrationBroker:
    """The sole coordinator-facing entry point for worker integration."""

    def __init__(self, queue: SerializedIntegrationQueue) -> None:
        self._queue = queue

    def dispatch(self, handle: WorktreeHandle) -> List[str]:
        """Reserve the worker's declared surfaces; return conflicting owners."""
        return self._queue.reserve(handle)

    def integrate_completed(
        self,
        handles: Iterable[WorktreeHandle],
        *,
        verified_revisions: Optional[Mapping[str, str]] = None,
        operation_key: str | None = None,
        operation_digest: str | None = None,
    ) -> IntegrationQueueResult:
        """Serialize verified terminal integration and fresh-main checks through the owned queue.

        Recovery diagnosticians and repairers never receive this broker; only
        the coordinator may rejoin a repaired SPEC-235-001 candidate here.  Its
        parent-private revision binding crosses this broker boundary explicitly;
        the queue then rejects a mutable branch whose tip no longer equals it.
        """
        materialized = list(handles)
        if verified_revisions is not None:
            for handle in materialized:
                if handle.spec_id in verified_revisions:
                    handle.verified_revision = verified_revisions[handle.spec_id]
        if operation_key is None and operation_digest is None:
            return self._queue.integrate(materialized)
        return self._queue.integrate(
            materialized, operation_key=operation_key,
            operation_digest=operation_digest,
        )

    def terminalize(self, spec_id: str) -> None:
        """Release a hold after the coordinator has recorded its terminal state."""
        self._queue.release(spec_id)


class DurableIntegrationReceiptAdapter:
    """Add an atomic, process-recreatable receipt store to a runtime adapter."""

    def __init__(self, delegate: FeedbackRuntimeAdapter, *, store_root: Path) -> None:
        self._delegate = delegate
        self._store_root = Path(store_root)

    def load_state(self, run_id: str) -> FeedbackState | None:
        return self._delegate.load_state(run_id)

    def save_state(self, state: FeedbackState) -> None:
        self._delegate.save_state(state)

    def poll_events(self, run_id: str) -> Iterable[NormalizedFeedbackEvent]:
        return self._delegate.poll_events(run_id)

    def execute_effect(
        self, effect: FeedbackEffect, *, idempotency_key: str
    ) -> NormalizedFeedbackEvent | None:
        return self._delegate.execute_effect(effect, idempotency_key=idempotency_key)

    def _paths(self, idempotency_key: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self._store_root / f"{digest}.json", self._store_root / f"{digest}.lock"

    @staticmethod
    def _read(path: Path) -> Mapping[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("durable integration receipt is unreadable") from exc
        if not isinstance(value, dict):
            raise ValueError("durable integration receipt is invalid")
        return value

    def load_integration_receipt(
        self, idempotency_key: str
    ) -> Mapping[str, Any] | None:
        path, lock_path = self._paths(idempotency_key)
        self._store_root.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            return self._read(path)

    def compare_and_set_integration_receipt(
        self, idempotency_key: str, *, expected_phase: str | None,
        receipt: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        path, lock_path = self._paths(idempotency_key)
        self._store_root.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            current = self._read(path)
            current_phase = current.get("phase") if current else None
            if current_phase != expected_phase:
                if current is None:
                    raise ValueError("durable integration receipt CAS mismatch")
                return current
            body = json.dumps(
                dict(receipt), sort_keys=True, separators=(",", ":")
            ).encode("utf-8") + b"\n"
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=self._store_root
            )
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
                directory = os.open(self._store_root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            stored = self._read(path)
            assert stored is not None
            return stored


class IntegrationBrokerFeedbackAdapter:
    """Production composition from reducer effects to exact-object integration.

    The delegate retains durable state/event ownership.  This adapter alone
    translates the reducer's coordinator-owned enqueue effect into a broker
    call and returns the exact applied Git object as an integration result.
    """

    def __init__(
        self,
        delegate: FeedbackRuntimeAdapter,
        *,
        broker_factory: Callable[[], IntegrationBroker],
        handles: Mapping[str, WorktreeHandle],
    ) -> None:
        self._delegate = delegate
        self._broker_factory = broker_factory
        self._handles = dict(handles)

    def load_state(self, run_id: str) -> FeedbackState | None:
        return self._delegate.load_state(run_id)

    def save_state(self, state: FeedbackState) -> None:
        self._delegate.save_state(state)

    def poll_events(self, run_id: str) -> Iterable[NormalizedFeedbackEvent]:
        return self._delegate.poll_events(run_id)

    def execute_effect(
        self, effect: FeedbackEffect, *, idempotency_key: str
    ) -> NormalizedFeedbackEvent | None:
        if effect.kind != "enqueue_integration_broker":
            return self._delegate.execute_effect(
                effect, idempotency_key=idempotency_key
            )
        payload = effect.payload
        spec_id = payload.get("spec_id")
        revision = payload.get("candidate_revision")
        revision_kind = payload.get("revision_kind")
        remediated_revision = payload.get("remediated_candidate_revision")
        if revision_kind not in {"candidate", "remediated"}:
            raise ValueError("integration effect lacks revision kind")
        if revision_kind == "remediated" and remediated_revision != revision:
            raise ValueError("remediated candidate revision binding mismatch")
        if (
            not isinstance(spec_id, str)
            or not isinstance(revision, str)
            or len(revision) != 40
            or any(ch not in "0123456789abcdef" for ch in revision)
            or spec_id not in self._handles
        ):
            raise ValueError("integration effect lacks exact candidate revision binding")

        load_receipt = getattr(self._delegate, "load_integration_receipt", None)
        store_receipt = getattr(
            self._delegate, "compare_and_set_integration_receipt", None
        )
        if not callable(load_receipt) or not callable(store_receipt):
            raise ValueError("durable integration receipt store is unavailable")
        payload_bytes = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        payload_digest = hashlib.sha256(payload_bytes).hexdigest()
        effect_digest = hashlib.sha256(
            json.dumps(
                {
                    "key": effect.key,
                    "kind": effect.kind,
                    "payload_digest": payload_digest,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        def validate_receipt(receipt: Mapping[str, Any]) -> None:
            if (
                receipt.get("idempotency_key") != idempotency_key
                or receipt.get("effect_digest") != effect_digest
                or receipt.get("payload_digest") != payload_digest
                or receipt.get("candidate_revision") != revision
            ):
                raise ValueError("divergent integration idempotency-key reuse")

        receipt = load_receipt(idempotency_key)
        if receipt is None:
            receipt = store_receipt(
                idempotency_key,
                expected_phase=None,
                receipt={
                    "schema_version": 1,
                    "phase": "prepared",
                    "idempotency_key": idempotency_key,
                    "effect_digest": effect_digest,
                    "payload_digest": payload_digest,
                    "spec_id": spec_id,
                    "candidate_revision": revision,
                },
            )
        validate_receipt(receipt)
        if receipt.get("phase") == "terminal":
            return _event_from_receipt(receipt)
        if receipt.get("phase") != "prepared":
            raise ValueError("invalid durable integration receipt phase")

        result = self._broker_factory().integrate_completed(
            [self._handles[spec_id]],
            verified_revisions={spec_id: revision},
            operation_key=idempotency_key,
            operation_digest=effect_digest,
        )
        decision = next(
            (item for item in result.decisions if item.spec_id == spec_id), None
        )
        accepted = spec_id in result.accepted
        applied_revision = decision.applied_revision if decision and accepted else None

        # SPEC-294 R3/Q5: a hold for pending deployment authorization is not
        # a terminal adapter failure -- it is an expected, resumable wait.
        # Leaving the receipt at "prepared" (rather than CAS-ing it to
        # "terminal") is what lets a later execute_effect call -- after a
        # human authorization artifact lands -- re-enter integrate_completed
        # and actually merge, keyed by the same run_id/idempotency_key
        # (DurableIntegrationReceiptAdapter). CAS-ing this to terminal here
        # would permanently lock the candidate out of ever merging.
        if (
            decision is not None
            and decision.outcome == "held"
            and decision.overlap_kind == "authorization_required"
        ):
            return NormalizedFeedbackEvent(
                key="integration-result:"
                + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24],
                kind="integration_result",
                role="parent",
                outcome="stalled",
                head=str(payload.get("head") or ""),
                applied_revision=None,
                reason="external_authority",
                next_action="provide_external_input",
            )

        outcome = "completed" if accepted and applied_revision == revision else "failed"
        event = NormalizedFeedbackEvent(
            key="integration-result:"
            + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24],
            kind="integration_result",
            role="parent",
            outcome=outcome,
            head=str(payload.get("head") or ""),
            applied_revision=applied_revision,
            reason=("ordinary_progress" if outcome == "completed" else "adapter_failure"),
            next_action=("continue" if outcome == "completed" else "inspect_adapter"),
        )
        stored = store_receipt(
            idempotency_key,
            expected_phase="prepared",
            receipt={
                **dict(receipt),
                "phase": "terminal",
                "result_event": asdict(event),
                "applied_revision": applied_revision,
                "broker_outcome": {
                    "accepted": list(result.accepted),
                    "held": list(result.held),
                    "reverted": list(result.reverted),
                    "decision_outcome": decision.outcome if decision else "missing",
                    "decision_reason": decision.reason if decision else "missing",
                },
            },
        )
        validate_receipt(stored)
        if stored.get("phase") != "terminal":
            raise ValueError("integration receipt did not reach terminal phase")
        return _event_from_receipt(stored)


def _event_from_receipt(receipt: Mapping[str, Any]) -> NormalizedFeedbackEvent:
    record = receipt.get("result_event")
    if not isinstance(record, Mapping):
        raise ValueError("terminal integration receipt lacks result event")
    return NormalizedFeedbackEvent(**dict(record))
