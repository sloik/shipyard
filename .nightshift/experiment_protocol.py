#!/usr/bin/env python3
"""Closed contracts for prospective, event-backed Nightshift experiments.

Tracked descriptors contain only safe experiment definitions. Raw observations
belong to the explicitly enrolled private observability store and are validated
against the descriptor's per-event payload schema before persistence.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import yaml


SCHEMA_VERSION = 1
EXPERIMENT_STATES = frozenset(
    {"registered", "collecting", "review_due", "resolved", "retired"}
)
CONCLUSIONS = frozenset(
    {"supported", "not_supported", "inconclusive", "invalidated"}
)
SAMPLE_STATES = frozenset(
    {
        "no_samples",
        "insufficient_samples",
        "sampled",
        "censored",
        "incomplete",
        "instrumentation_gap",
        "invalidated",
    }
)
OUTCOME_CLASSES = frozenset({"adoption", "effectiveness", "reliability"})
EVIDENCE_CLASSES = frozenset({"passive", "controlled", "randomized"})
SOURCE_CLASSES = frozenset({"passive", "controlled"})
EVENT_OUTCOMES = frozenset(
    {"eligible", "succeeded", "failed", "refused", "interrupted", "unknown"}
)
ANALYZERS = frozenset({"event-chain-rate-v1"})
PRIVACY_CLASSES = frozenset({"private-local"})
REVIEW_TRIGGERS = frozenset({"first_of_minimum_or_deadline"})
PAYLOAD_TYPES = frozenset(
    {"boolean", "integer", "nonnegative_integer", "number", "digest", "identifier"}
)
CORRELATION_KEYS = frozenset(
    {
        "subject_digest",
        "package_digest",
        "inventory_digest",
        "plan_digest",
        "approval_digest",
        "admission_digest",
        "run_digest",
        "job_digest",
        "state_digest",
    }
)
DESCRIPTOR_FIELDS = frozenset(
    {
        "schema_version",
        "experiment_id",
        "source_spec_id",
        "owner",
        "hypothesis_revision",
        "event_contract",
        "analyzer",
        "outcome_class",
        "observation",
        "privacy",
        "event_schemas",
        "hypotheses",
        "guardrails",
        "invalidating_assumptions",
    }
)
OBSERVATION_FIELDS = frozenset(
    {
        "start_release_fingerprint",
        "started_at",
        "minimum_eligible_observations",
        "maximum_window_days",
        "review_trigger",
    }
)
HYPOTHESIS_FIELDS = frozenset(
    {
        "id",
        "live_execution_ids",
        "claim",
        "counterevidence",
        "eligible_events",
        "required_chain",
        "denominator_event",
        "numerator_event",
        "unit_of_analysis",
        "deduplication_keys",
        "evidence_class",
        "exclusions",
        "supported_at_or_above",
        "not_supported_below",
        "no_sample_behavior",
        "consequences",
    }
)
CONSEQUENCE_FIELDS = frozenset({"supported", "not_supported", "inconclusive"})
EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "experiment_id",
        "hypothesis_revision",
        "project_id",
        "sequence",
        "previous_event_hash",
        "event_hash",
        "operation_id",
        "event_name",
        "producer",
        "release_fingerprint",
        "source_class",
        "occurred_at",
        "idempotency_key",
        "correlations",
        "outcome",
        "payload",
    }
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_EXPERIMENT_ID = re.compile(r"^EXP-[A-Z0-9][A-Z0-9-]{2,95}$")
_HYPOTHESIS_ID = re.compile(r"^H[1-9][0-9]*$")
_LIVE_EXECUTION_ID = re.compile(r"^LE[1-9][0-9]*$")
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_URL = re.compile(r"(?:https?://|ssh://|git@)", re.I)
_SECRET = re.compile(r"(?:api[_-]?key|secret|password|token|authorization|bearer)\s*[:=]", re.I)
_ABSOLUTE_PATH = re.compile(r"(?:^|\s)(?:/[^\s]+|[A-Za-z]:[\\/][^\s]+)")


class ExperimentProtocolError(ValueError):
    """A descriptor or observation violated the closed experiment contract."""


def canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _iso8601(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ExperimentProtocolError(f"{field} must be an ISO-8601 string")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExperimentProtocolError(f"{field} must be ISO-8601") from exc


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ExperimentProtocolError(f"{field} must be a controlled identifier")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ExperimentProtocolError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _nonempty_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExperimentProtocolError(f"{field} must be non-empty text")
    if "\n" in value or len(value) > 600:
        raise ExperimentProtocolError(f"{field} must be bounded single-line text")
    if _URL.search(value) or _SECRET.search(value) or _ABSOLUTE_PATH.search(value):
        raise ExperimentProtocolError(f"{field} contains a forbidden path, URL, or secret-shaped value")
    return value.strip()


def _closed(mapping: Any, fields: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(mapping, Mapping):
        raise ExperimentProtocolError(f"{label} must be a mapping")
    unknown = sorted(set(mapping) - fields)
    if unknown:
        raise ExperimentProtocolError(f"{label} has unknown fields: {', '.join(unknown)}")
    return mapping


def _safe_relative(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExperimentProtocolError(f"{field} must be a safe relative reference")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "://" in value:
        raise ExperimentProtocolError(f"{field} must be a safe relative reference")
    return path.as_posix()


def descriptor_revision(descriptor: Mapping[str, Any]) -> str:
    material = dict(descriptor)
    material.pop("hypothesis_revision", None)
    return _sha(material)


def validate_descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
    descriptor = dict(_closed(value, DESCRIPTOR_FIELDS, "experiment descriptor"))
    missing = sorted(DESCRIPTOR_FIELDS - set(descriptor))
    if missing:
        raise ExperimentProtocolError(
            "experiment descriptor missing fields: " + ", ".join(missing)
        )
    if descriptor["schema_version"] != SCHEMA_VERSION:
        raise ExperimentProtocolError(f"schema_version must be {SCHEMA_VERSION}")
    if not isinstance(descriptor["experiment_id"], str) or not _EXPERIMENT_ID.fullmatch(
        descriptor["experiment_id"]
    ):
        raise ExperimentProtocolError("experiment_id must match EXP-<UPPER-ID>")
    _identifier(descriptor["source_spec_id"], "source_spec_id")
    _identifier(descriptor["owner"], "owner")
    _identifier(descriptor["event_contract"], "event_contract")
    if descriptor["analyzer"] not in ANALYZERS:
        raise ExperimentProtocolError("analyzer is not supported")
    if descriptor["outcome_class"] not in OUTCOME_CLASSES:
        raise ExperimentProtocolError("outcome_class is not permitted post-close")
    if descriptor["privacy"] not in PRIVACY_CLASSES:
        raise ExperimentProtocolError("privacy must be private-local")

    observation = _closed(descriptor["observation"], OBSERVATION_FIELDS, "observation")
    if set(observation) != OBSERVATION_FIELDS:
        raise ExperimentProtocolError("observation contract is incomplete")
    _digest(observation["start_release_fingerprint"], "start_release_fingerprint")
    _iso8601(observation["started_at"], "started_at")
    minimum = observation["minimum_eligible_observations"]
    window = observation["maximum_window_days"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ExperimentProtocolError("minimum_eligible_observations must be a positive integer")
    if isinstance(window, bool) or not isinstance(window, int) or not 1 <= window <= 3660:
        raise ExperimentProtocolError("maximum_window_days must be between 1 and 3660")
    if observation["review_trigger"] not in REVIEW_TRIGGERS:
        raise ExperimentProtocolError("review_trigger is not supported")

    event_schemas = descriptor["event_schemas"]
    if not isinstance(event_schemas, Mapping) or not event_schemas:
        raise ExperimentProtocolError("event_schemas must be a non-empty mapping")
    for event_name, schema in event_schemas.items():
        if not isinstance(event_name, str) or not _EVENT_NAME.fullmatch(event_name):
            raise ExperimentProtocolError("event_schemas contains an invalid event name")
        if not isinstance(schema, Mapping):
            raise ExperimentProtocolError(f"event schema {event_name} must be a mapping")
        for field, field_type in schema.items():
            _identifier(field, f"event schema {event_name} field")
            if field_type not in PAYLOAD_TYPES:
                raise ExperimentProtocolError(
                    f"event schema {event_name}.{field} has unsupported type"
                )

    hypotheses = descriptor["hypotheses"]
    if not isinstance(hypotheses, list) or not hypotheses:
        raise ExperimentProtocolError("hypotheses must be a non-empty list")
    seen_hypotheses: set[str] = set()
    seen_live_items: set[str] = set()
    for index, raw in enumerate(hypotheses):
        hypothesis = _closed(raw, HYPOTHESIS_FIELDS, f"hypotheses[{index}]")
        if set(hypothesis) != HYPOTHESIS_FIELDS:
            raise ExperimentProtocolError(f"hypotheses[{index}] contract is incomplete")
        hypothesis_id = hypothesis["id"]
        if not isinstance(hypothesis_id, str) or not _HYPOTHESIS_ID.fullmatch(hypothesis_id):
            raise ExperimentProtocolError(f"hypotheses[{index}].id must match H<number>")
        if hypothesis_id in seen_hypotheses:
            raise ExperimentProtocolError("hypothesis IDs must be unique")
        seen_hypotheses.add(hypothesis_id)
        live_ids = hypothesis["live_execution_ids"]
        if not isinstance(live_ids, list) or not live_ids:
            raise ExperimentProtocolError("live_execution_ids must be a non-empty list")
        for live_id in live_ids:
            if not isinstance(live_id, str) or not _LIVE_EXECUTION_ID.fullmatch(live_id):
                raise ExperimentProtocolError("live_execution_ids must match LE<number>")
            if live_id in seen_live_items:
                raise ExperimentProtocolError("live execution IDs may map only once")
            seen_live_items.add(live_id)
        _nonempty_text(hypothesis["claim"], "claim")
        _nonempty_text(hypothesis["counterevidence"], "counterevidence")
        for field in ("eligible_events", "required_chain"):
            events = hypothesis[field]
            if not isinstance(events, list) or not events or any(
                event not in event_schemas for event in events
            ):
                raise ExperimentProtocolError(f"{field} must reference declared event schemas")
        for field in ("denominator_event", "numerator_event"):
            if hypothesis[field] not in event_schemas:
                raise ExperimentProtocolError(f"{field} must reference a declared event schema")
        _identifier(hypothesis["unit_of_analysis"], "unit_of_analysis")
        keys = hypothesis["deduplication_keys"]
        if not isinstance(keys, list) or not keys or any(key not in CORRELATION_KEYS for key in keys):
            raise ExperimentProtocolError("deduplication_keys are not allowlisted")
        if hypothesis["evidence_class"] not in EVIDENCE_CLASSES:
            raise ExperimentProtocolError("evidence_class is invalid")
        exclusions = hypothesis["exclusions"]
        if not isinstance(exclusions, list) or any(
            not isinstance(item, str) or not _IDENTIFIER.fullmatch(item) for item in exclusions
        ):
            raise ExperimentProtocolError("exclusions must be controlled identifiers")
        supported = hypothesis["supported_at_or_above"]
        unsupported = hypothesis["not_supported_below"]
        if isinstance(supported, bool) or not isinstance(supported, (int, float)):
            raise ExperimentProtocolError("supported_at_or_above must be numeric")
        if isinstance(unsupported, bool) or not isinstance(unsupported, (int, float)):
            raise ExperimentProtocolError("not_supported_below must be numeric")
        if not 0 <= unsupported <= supported <= 1:
            raise ExperimentProtocolError("decision thresholds must satisfy 0 <= below <= above <= 1")
        if hypothesis["no_sample_behavior"] != "no_samples":
            raise ExperimentProtocolError("no_sample_behavior must be no_samples")
        consequences = _closed(
            hypothesis["consequences"], CONSEQUENCE_FIELDS, "consequences"
        )
        if set(consequences) != CONSEQUENCE_FIELDS:
            raise ExperimentProtocolError("consequences contract is incomplete")
        for name, consequence in consequences.items():
            _identifier(consequence, f"consequences.{name}")

    for field in ("guardrails", "invalidating_assumptions"):
        items = descriptor[field]
        if not isinstance(items, list) or not items:
            raise ExperimentProtocolError(f"{field} must be a non-empty list")
        for item in items:
            _identifier(item, field)

    expected_revision = descriptor_revision(descriptor)
    _digest(descriptor["hypothesis_revision"], "hypothesis_revision")
    if descriptor["hypothesis_revision"] != expected_revision:
        raise ExperimentProtocolError("hypothesis_revision does not match descriptor content")
    return descriptor


def load_descriptor(path: Path) -> dict[str, Any]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ExperimentProtocolError("descriptor must be a regular file")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ExperimentProtocolError("descriptor is not valid YAML") from exc
    if not isinstance(value, Mapping):
        raise ExperimentProtocolError("descriptor must contain a mapping")
    return validate_descriptor(value)


def event_hash(event: Mapping[str, Any]) -> str:
    material = dict(event)
    material.pop("event_hash", None)
    return _sha(material)


def _validate_payload_value(value: Any, field_type: str, field: str) -> None:
    if field_type == "boolean" and not isinstance(value, bool):
        raise ExperimentProtocolError(f"payload.{field} must be boolean")
    if field_type == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        raise ExperimentProtocolError(f"payload.{field} must be integer")
    if field_type == "nonnegative_integer" and (
        isinstance(value, bool) or not isinstance(value, int) or value < 0
    ):
        raise ExperimentProtocolError(f"payload.{field} must be a non-negative integer")
    if field_type == "number" and (
        isinstance(value, bool) or not isinstance(value, (int, float))
    ):
        raise ExperimentProtocolError(f"payload.{field} must be numeric")
    if field_type == "digest":
        _digest(value, f"payload.{field}")
    if field_type == "identifier":
        _identifier(value, f"payload.{field}")


def validate_event(value: Mapping[str, Any], descriptor: Mapping[str, Any]) -> dict[str, Any]:
    descriptor = validate_descriptor(descriptor)
    event = dict(_closed(value, EVENT_FIELDS, "experiment event"))
    if set(event) != EVENT_FIELDS:
        raise ExperimentProtocolError("experiment event contract is incomplete")
    if event["schema_version"] != SCHEMA_VERSION:
        raise ExperimentProtocolError(f"event schema_version must be {SCHEMA_VERSION}")
    try:
        uuid.UUID(str(event["event_id"]))
        uuid.UUID(str(event["project_id"]))
        uuid.UUID(str(event["operation_id"]))
    except ValueError as exc:
        raise ExperimentProtocolError("event, project, and operation IDs must be UUIDs") from exc
    if event["experiment_id"] != descriptor["experiment_id"]:
        raise ExperimentProtocolError("event experiment_id does not match descriptor")
    if event["hypothesis_revision"] != descriptor["hypothesis_revision"]:
        raise ExperimentProtocolError("event hypothesis_revision does not match descriptor")
    if isinstance(event["sequence"], bool) or not isinstance(event["sequence"], int) or event["sequence"] < 1:
        raise ExperimentProtocolError("sequence must be a positive integer")
    if event["previous_event_hash"] is not None:
        _digest(event["previous_event_hash"], "previous_event_hash")
    _digest(event["event_hash"], "event_hash")
    _identifier(event["producer"], "producer")
    _digest(event["release_fingerprint"], "release_fingerprint")
    _digest(event["idempotency_key"], "idempotency_key")
    if event["source_class"] not in SOURCE_CLASSES:
        raise ExperimentProtocolError("source_class is invalid")
    if event["outcome"] not in EVENT_OUTCOMES:
        raise ExperimentProtocolError("outcome is invalid")
    _iso8601(event["occurred_at"], "occurred_at")
    event_name = event["event_name"]
    schema = descriptor["event_schemas"].get(event_name)
    if schema is None:
        raise ExperimentProtocolError("event_name is not declared by descriptor")
    correlations = event["correlations"]
    if not isinstance(correlations, Mapping) or not correlations:
        raise ExperimentProtocolError("correlations must be a non-empty mapping")
    if set(correlations) - CORRELATION_KEYS:
        raise ExperimentProtocolError("correlations contains unapproved keys")
    for key, digest_value in correlations.items():
        _digest(digest_value, f"correlations.{key}")
    payload = event["payload"]
    if not isinstance(payload, Mapping) or set(payload) != set(schema):
        raise ExperimentProtocolError("payload fields must exactly match the event schema")
    for field, field_type in schema.items():
        _validate_payload_value(payload[field], field_type, field)
    if event_hash(event) != event["event_hash"]:
        raise ExperimentProtocolError("event_hash does not match canonical event content")
    return event


def build_event(
    descriptor: Mapping[str, Any],
    *,
    event_id: str,
    project_id: str,
    sequence: int,
    previous_event_hash: str | None,
    operation_id: str,
    event_name: str,
    producer: str,
    release_fingerprint: str,
    source_class: str,
    occurred_at: str,
    idempotency_key: str,
    correlations: Mapping[str, str],
    outcome: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    descriptor = validate_descriptor(descriptor)
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "experiment_id": descriptor["experiment_id"],
        "hypothesis_revision": descriptor["hypothesis_revision"],
        "project_id": project_id,
        "sequence": sequence,
        "previous_event_hash": previous_event_hash,
        "event_hash": "",
        "operation_id": operation_id,
        "event_name": event_name,
        "producer": producer,
        "release_fingerprint": release_fingerprint,
        "source_class": source_class,
        "occurred_at": occurred_at,
        "idempotency_key": idempotency_key,
        "correlations": dict(correlations),
        "outcome": outcome,
        "payload": dict(payload),
    }
    event["event_hash"] = event_hash(event)
    return validate_event(event, descriptor)


def descriptor_reference(path: str) -> str:
    """Validate and normalize a tracked descriptor reference."""
    return _safe_relative(path, "descriptor")
