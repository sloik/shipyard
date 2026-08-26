"""Coordinator-owned boundary for serial Nightshift parent integration.

Workers hand this object completed branches and privacy-safe release intents;
they never receive the main checkout or a merge capability.  Keeping the small
wrapper separate makes the ownership boundary explicit for harness adapters.
"""

from __future__ import annotations

from typing import Iterable, List

from parallel_executor import IntegrationQueueResult, SerializedIntegrationQueue, WorktreeHandle


class IntegrationBroker:
    """The sole coordinator-facing entry point for worker integration."""

    def __init__(self, queue: SerializedIntegrationQueue) -> None:
        self._queue = queue

    def dispatch(self, handle: WorktreeHandle) -> List[str]:
        """Reserve the worker's declared surfaces; return conflicting owners."""
        return self._queue.reserve(handle)

    def integrate_completed(self, handles: Iterable[WorktreeHandle]) -> IntegrationQueueResult:
        """Serialize terminal integration through the owned queue."""
        return self._queue.integrate(handles)

    def terminalize(self, spec_id: str) -> None:
        """Release a hold after the coordinator has recorded its terminal state."""
        self._queue.release(spec_id)
