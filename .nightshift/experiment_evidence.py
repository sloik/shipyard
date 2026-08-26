#!/usr/bin/env python3
"""Private capture and deterministic projections for real-use experiments."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

from experiment_protocol import (
    ExperimentProtocolError,
    canonical,
    build_event,
    event_hash,
    load_descriptor,
    validate_descriptor,
    validate_event,
)
from observability_store import (
    ObservabilityStoreError,
    StoreContext,
    enroll,
    read_artifacts,
    write_or_outbox,
)


class ExperimentEvidenceError(RuntimeError):
    """Experiment evidence is incomplete, corrupt, or ambiguous."""


class ExperimentObserver:
    """Closed producer used by domain authorities at real workflow boundaries."""

    def __init__(
        self,
        context: StoreContext,
        descriptor: Mapping[str, Any],
        *,
        producer: str,
        release_fingerprint: str,
    ):
        self.context = context
        self.descriptor = validate_descriptor(descriptor)
        self.producer = producer
        self.release_fingerprint = release_fingerprint

    def emit(
        self,
        event_name: str,
        *,
        operation_id: str,
        correlations: Mapping[str, str],
        outcome: str,
        payload: Mapping[str, Any],
        source_class: str = "passive",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        current = load_events(self.context, self.descriptor)
        stable = canonical({
            "experiment_id": self.descriptor["experiment_id"],
            "operation_id": operation_id,
            "event_name": event_name,
            "correlations": dict(correlations),
            "outcome": outcome,
            "payload": dict(payload),
        })
        idempotency_key = hashlib.sha256(stable).hexdigest()
        prior = next((item for item in current if item["idempotency_key"] == idempotency_key), None)
        if prior is not None:
            return {"status": "idempotent", "event_hash": prior["event_hash"]}
        sequence = len(current) + 1
        previous = current[-1]["event_hash"] if current else None
        event_id = str(uuid.uuid5(uuid.UUID(self.context.project_id), idempotency_key))
        event = build_event(
            self.descriptor,
            event_id=event_id,
            project_id=self.context.project_id,
            sequence=sequence,
            previous_event_hash=previous,
            operation_id=operation_id,
            event_name=event_name,
            producer=self.producer,
            release_fingerprint=self.release_fingerprint,
            source_class=source_class,
            occurred_at=occurred_at or datetime.now(UTC).isoformat(),
            idempotency_key=idempotency_key,
            correlations=correlations,
            outcome=outcome,
            payload=payload,
        )
        return append_event(self.context, self.descriptor, event)


@contextmanager
def _stream_lock(context: StoreContext, experiment_id: str):
    lock_dir = (
        context.root
        / "nightshift-observability"
        / "projects"
        / context.project_id
        / "locks"
    )
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{experiment_id}.lock"
    if lock_path.is_symlink():
        raise ExperimentEvidenceError("experiment lock may not be a symlink")
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _events(records: Iterable[Mapping[str, Any]], descriptor: Mapping[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for record in records:
        payload = record.get("payload", {})
        event = payload.get("experiment_event") if isinstance(payload, Mapping) else None
        if not isinstance(event, Mapping):
            raise ExperimentEvidenceError("experiment artifact has no closed event payload")
        if event.get("experiment_id") != descriptor["experiment_id"]:
            continue
        try:
            selected.append(validate_event(event, descriptor))
        except ExperimentProtocolError as exc:
            raise ExperimentEvidenceError(str(exc)) from exc
    selected.sort(key=lambda item: (item["project_id"], item["sequence"]))
    previous_by_project: dict[str, str | None] = {}
    sequence_by_project: dict[str, int] = {}
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for item in selected:
        project_id = item["project_id"]
        expected = sequence_by_project.get(project_id, 0) + 1
        if item["sequence"] != expected:
            raise ExperimentEvidenceError("experiment event sequence contains a gap or fork")
        if item["previous_event_hash"] != previous_by_project.get(project_id):
            raise ExperimentEvidenceError("experiment event hash chain is broken")
        if item["event_id"] in seen_ids or item["idempotency_key"] in seen_keys:
            raise ExperimentEvidenceError("experiment event stream contains a duplicate identity")
        seen_ids.add(item["event_id"])
        seen_keys.add(item["idempotency_key"])
        sequence_by_project[project_id] = expected
        previous_by_project[project_id] = item["event_hash"]
    return selected


def load_events(context: StoreContext, descriptor: Mapping[str, Any]) -> list[dict[str, Any]]:
    descriptor = validate_descriptor(descriptor)
    return _events(read_artifacts(context, kind="experiment_event"), descriptor)


def append_event(
    context: StoreContext,
    descriptor: Mapping[str, Any],
    event: Mapping[str, Any],
) -> dict[str, Any]:
    """Append one prebuilt event after verifying exact stream continuity.

    Transport outages return ``awaiting_sync``. Contract, privacy, duplicate,
    and integrity failures remain hard failures and cannot become evidence.
    """
    descriptor = validate_descriptor(descriptor)
    candidate = validate_event(event, descriptor)
    if candidate["project_id"] != context.project_id:
        raise ExperimentEvidenceError("event project_id does not match private enrollment")
    with _stream_lock(context, descriptor["experiment_id"]):
        current = load_events(context, descriptor)
        for existing in current:
            if existing["event_id"] == candidate["event_id"]:
                if canonical(existing) == canonical(candidate):
                    return {"status": "idempotent", "event_hash": existing["event_hash"]}
                # Let the immutable object store write the divergent candidate so
                # its existing quarantine authority records the conflict.
                try:
                    write_or_outbox(
                        context,
                        kind="experiment_event",
                        artifact_id=candidate["event_id"],
                        run_sequence=candidate["sequence"],
                        producer=candidate["producer"],
                        payload={"experiment_event": candidate},
                    )
                except ObservabilityStoreError as exc:
                    raise ExperimentEvidenceError(str(exc)) from exc
                raise ExperimentEvidenceError("divergent duplicate event was not quarantined")
            if existing["idempotency_key"] == candidate["idempotency_key"]:
                raise ExperimentEvidenceError("idempotency key has divergent content")
        expected_sequence = len(current) + 1
        expected_previous = current[-1]["event_hash"] if current else None
        if candidate["sequence"] != expected_sequence:
            raise ExperimentEvidenceError("event sequence is not the next stream sequence")
        if candidate["previous_event_hash"] != expected_previous:
            raise ExperimentEvidenceError("event previous hash does not match stream head")
        try:
            receipt = write_or_outbox(
                context,
                kind="experiment_event",
                artifact_id=candidate["event_id"],
                run_sequence=candidate["sequence"],
                producer=candidate["producer"],
                payload={"experiment_event": candidate},
            )
        except ObservabilityStoreError as exc:
            raise ExperimentEvidenceError(str(exc)) from exc
        return {**receipt, "event_hash": candidate["event_hash"]}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _dedup_key(event: Mapping[str, Any], keys: list[str]) -> tuple[str, ...] | None:
    correlations = event["correlations"]
    if any(key not in correlations for key in keys):
        return None
    return tuple(correlations[key] for key in keys)


def analyze_experiment(
    descriptor: Mapping[str, Any],
    events: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Derive a privacy-safe projection; absence is never interpreted as success."""
    descriptor = validate_descriptor(descriptor)
    checked = _events(
        ({"payload": {"experiment_event": event}} for event in events), descriptor
    )
    observation = descriptor["observation"]
    started_at = _parse_time(observation["started_at"])
    deadline = started_at + timedelta(days=observation["maximum_window_days"])
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    producer_events = [
        event
        for event in checked
        if event["release_fingerprint"] == observation["start_release_fingerprint"]
        and _parse_time(event["occurred_at"]) >= started_at
    ]
    invalidated_count = len(checked) - len(producer_events)
    results: list[dict[str, Any]] = []
    total_eligible = total_numerator = total_censored = total_incomplete = 0
    any_gap = invalidated_count > 0
    conclusions: list[str] = []
    scopes: set[str] = set()
    for hypothesis in descriptor["hypotheses"]:
        units: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
        gap_count = 0
        for event in producer_events:
            if event["event_name"] not in hypothesis["eligible_events"]:
                continue
            key = _dedup_key(event, hypothesis["deduplication_keys"])
            if key is None:
                gap_count += 1
                continue
            units.setdefault(key, []).append(event)
        eligible = numerator = censored = incomplete = 0
        controlled = False
        project_ids: set[str] = set()
        for unit_events in units.values():
            names = [event["event_name"] for event in unit_events]
            if hypothesis["denominator_event"] not in names:
                continue
            eligible += 1
            project_ids.update(event["project_id"] for event in unit_events)
            controlled = controlled or any(event["source_class"] == "controlled" for event in unit_events)
            cursor = 0
            complete = True
            for required in hypothesis["required_chain"]:
                try:
                    cursor = names.index(required, cursor) + 1
                except ValueError:
                    complete = False
                    break
            if complete:
                if any(
                    event["event_name"] == hypothesis["numerator_event"]
                    and event["outcome"] == "succeeded"
                    for event in unit_events
                ):
                    numerator += 1
            elif current_time >= deadline:
                censored += 1
            else:
                incomplete += 1
        total_eligible += eligible
        total_numerator += numerator
        total_censored += censored
        total_incomplete += incomplete
        any_gap = any_gap or gap_count > 0
        value = numerator / eligible if eligible else None
        minimum = observation["minimum_eligible_observations"]
        conclusion: str | None = None
        if invalidated_count:
            sample_state = "invalidated"
            conclusion = "invalidated" if current_time >= deadline else None
        elif gap_count:
            sample_state = "instrumentation_gap"
        elif eligible == 0:
            sample_state = "no_samples"
        elif censored:
            sample_state = "censored"
        elif incomplete:
            sample_state = "incomplete"
        elif eligible < minimum:
            sample_state = "insufficient_samples"
        else:
            sample_state = "sampled"
            if hypothesis["evidence_class"] != "passive" and not controlled:
                conclusion = "inconclusive"
            elif value is not None and value >= hypothesis["supported_at_or_above"]:
                conclusion = "supported"
            elif value is not None and value < hypothesis["not_supported_below"]:
                conclusion = "not_supported"
            else:
                conclusion = "inconclusive"
        if conclusion:
            conclusions.append(conclusion)
        if len(project_ids) > 1:
            scope = "cross_project"
        elif eligible > 1:
            scope = "repeated_single_project"
        elif eligible == 1:
            scope = "single_observation"
        else:
            scope = "none"
        scopes.add(scope)
        results.append(
            {
                "hypothesis_id": hypothesis["id"],
                "eligible": eligible,
                "numerator": numerator,
                "denominator": eligible,
                "value": value,
                "sample_state": sample_state,
                "censored": censored,
                "incomplete": incomplete,
                "instrumentation_gaps": gap_count,
                "evidence_scope": scope,
                "conclusion": conclusion,
            }
        )
    minimum = observation["minimum_eligible_observations"]
    review_due = current_time >= deadline or total_eligible >= minimum
    if checked and not review_due:
        state = "collecting"
    elif review_due:
        terminal = all(item["conclusion"] is not None for item in results)
        state = "resolved" if terminal else "review_due"
    else:
        state = "registered"
    overall: str | None = None
    if state == "resolved":
        if "invalidated" in conclusions:
            overall = "invalidated"
        elif "not_supported" in conclusions:
            overall = "not_supported"
        elif conclusions and all(item == "supported" for item in conclusions):
            overall = "supported"
        else:
            overall = "inconclusive"
    first = min((_parse_time(item["occurred_at"]) for item in producer_events), default=None)
    return {
        "schema_version": 1,
        "experiment_id": descriptor["experiment_id"],
        "source_spec_id": descriptor["source_spec_id"],
        "hypothesis_revision": descriptor["hypothesis_revision"],
        "state": state,
        "review_trigger": observation["review_trigger"],
        "sample_state": (
            "invalidated" if invalidated_count else
            "instrumentation_gap" if any_gap else
            "no_samples" if total_eligible == 0 else
            "censored" if total_censored else
            "incomplete" if total_incomplete else
            "insufficient_samples" if total_eligible < minimum else "sampled"
        ),
        "eligible": total_eligible,
        "numerator": total_numerator,
        "denominator": total_eligible,
        "value": total_numerator / total_eligible if total_eligible else None,
        "invalidated_events": invalidated_count,
        "censored": total_censored,
        "incomplete": total_incomplete,
        "evidence_scope": "cross_project" if "cross_project" in scopes else (
            "repeated_single_project" if "repeated_single_project" in scopes else
            "single_observation" if "single_observation" in scopes else "none"
        ),
        "conclusion": overall,
        "window": {"started_at": observation["started_at"], "deadline": deadline.isoformat()},
        "time_to_first_evidence_s": (
            int((first - started_at).total_seconds()) if first is not None else None
        ),
        "hypotheses": results,
        "evidence_hashes": [item["event_hash"] for item in checked],
    }


def write_projection(path: Path, projections: Iterable[Mapping[str, Any]]) -> None:
    """Atomically replace a non-authoritative, reproducible public-safe view."""
    path = Path(path)
    data = canonical({"schema_version": 1, "experiments": sorted(
        (dict(item) for item in projections), key=lambda item: item["experiment_id"]
    )}) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".experiment-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def seal_result(
    context: StoreContext,
    descriptor: Mapping[str, Any],
    projection: Mapping[str, Any],
    *,
    result_id: str,
    producer: str,
) -> dict[str, Any]:
    descriptor = validate_descriptor(descriptor)
    if projection.get("state") != "resolved":
        raise ExperimentEvidenceError("only a resolved projection can be sealed")
    return write_or_outbox(
        context,
        kind="experiment_result",
        artifact_id=result_id,
        run_sequence=len(projection.get("evidence_hashes", [])),
        producer=producer,
        payload={"experiment_result": dict(projection)},
    )


def experiment_metrics(projections: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build allowlisted aggregate metrics with explicit sample denominators."""
    rows = [dict(item) for item in projections]
    total = len(rows)
    review_due = sum(item.get("state") == "review_due" for item in rows)
    resolved = sum(item.get("state") == "resolved" for item in rows)
    no_samples = sum(item.get("sample_state") == "no_samples" for item in rows)
    gaps = sum(item.get("sample_state") == "instrumentation_gap" for item in rows)
    with_evidence = sum(int(item.get("eligible", 0)) > 0 for item in rows)
    linked = sum(bool(item.get("remediation_linked")) for item in rows)
    impactful = sum(item.get("conclusion") in {"not_supported", "invalidated"} for item in rows)

    def rate(numerator: int, denominator: int) -> dict[str, Any]:
        return {
            "numerator": numerator,
            "eligible_denominator": denominator,
            "value": numerator / denominator if denominator else None,
            "sample_state": "sampled" if denominator else "no_samples",
        }

    conclusions = {name: sum(item.get("conclusion") == name for item in rows) for name in (
        "supported", "not_supported", "inconclusive", "invalidated"
    )}
    states = {name: sum(item.get("state") == name for item in rows) for name in (
        "registered", "collecting", "review_due", "resolved", "retired"
    )}
    return {
        "schema_version": 1,
        "registered_experiments": total,
        "states": states,
        "conclusions": conclusions,
        "rates": {
            "instrumentation_coverage_rate": rate(with_evidence, total),
            "no_sample_experiment_rate": rate(no_samples, review_due),
            "review_completion_rate": rate(resolved, review_due + resolved),
            "instrumentation_gap_rate": rate(gaps, total),
            "remediation_creation_rate": rate(linked, impactful),
        },
        "time_to_first_evidence_s": [
            item["time_to_first_evidence_s"] for item in rows
            if isinstance(item.get("time_to_first_evidence_s"), int)
        ],
    }


def route_impactful_conclusion(
    root: Path,
    projection: Mapping[str, Any],
    *,
    evidence_ref: str,
    child_spec_id: str,
    specs_dir: Path,
    recorded_at: str,
) -> tuple[dict[str, Any], bool]:
    """Route one unsupported/invalidated result through SPEC-236's authority."""
    if projection.get("state") != "resolved" or projection.get("conclusion") not in {
        "not_supported", "invalidated"
    }:
        raise ExperimentEvidenceError("only impactful resolved conclusions create remediation")
    from followup_decisions import seal_official_decision

    return seal_official_decision(
        root,
        run_id=str(projection["experiment_id"]),
        source_spec_id=str(projection["source_spec_id"]),
        terminal_resolution="post_release",
        discovery_phase="post_release",
        classification={
            "cause_class": "implementation_defect",
            "detail_reason": "regression_in_landed_work",
            "planned_at_source_authoring": False,
        },
        evidence_ref=evidence_ref,
        outcome="created",
        child_spec_id=child_spec_id,
        specs_dir=specs_dir,
        recorded_at=recorded_at,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or project real-use experiments")
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate")
    validate.add_argument("descriptor", type=Path)
    status = subcommands.add_parser("status")
    status.add_argument("descriptor", type=Path)
    status.add_argument("--config", type=Path, required=True)
    status.add_argument("--repo", type=Path, required=True)
    status.add_argument("--output", type=Path)
    status.add_argument("--now")
    args = parser.parse_args(argv)
    try:
        descriptor = load_descriptor(args.descriptor)
        if args.command == "validate":
            print(json.dumps({
                "experiment_id": descriptor["experiment_id"],
                "hypothesis_revision": descriptor["hypothesis_revision"],
                "status": "valid",
            }, sort_keys=True))
            return 0
        context = enroll(args.config, args.repo)
        now = _parse_time(args.now) if args.now else None
        projection = analyze_experiment(descriptor, load_events(context, descriptor), now=now)
        if args.output:
            write_projection(args.output, [projection])
        display = {key: projection[key] for key in (
            "experiment_id", "source_spec_id", "hypothesis_revision", "state",
            "review_trigger", "sample_state", "eligible", "evidence_scope", "conclusion",
        )}
        print(json.dumps(display, sort_keys=True))
        return 0
    except (ExperimentProtocolError, ExperimentEvidenceError, ObservabilityStoreError, OSError) as exc:
        print(json.dumps({"status": "invalid", "reason": type(exc).__name__}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
