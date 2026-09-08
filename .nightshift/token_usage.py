#!/usr/bin/env python3
"""SPEC-298 — privacy-safe token-usage telemetry, aggregation, reporting,
and evidence-gated forecasting.

This module is the single adapter boundary for structured provider usage
metadata (already-parsed dicts such as ``{"prompt_tokens": 123, ...}``
returned by ``llm_client.py`` providers or carried on
``nightshift_coordinator._TOKEN_USAGE_FIELDS``-shaped payloads). It never
scrapes transcripts, never monkey-patches an SDK, and never makes a network
call. Everything downstream (aggregation, reports, forecasts, quota
projection) works only from the closed, versioned event schema this module
defines.

Privacy boundary (R1): an accepted event stores only run/spec identifiers,
a timestamp, provider/harness/model identifiers, role/phase, an attempt
ordinal, numeric token/request/cost/duration fields, and a closed
measurement state. No prompts, responses, tool arguments, paths,
credentials, raw provider payloads, or account/quota identifiers.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

TOKEN_EVENT_SCHEMA_VERSION = 1

# R2: closed measurement-state vocabulary.
TOKEN_MEASUREMENT_STATES = frozenset({"measured", "partial", "unavailable", "rejected"})

# Harnesses this adapter can normalize already-structured usage metadata
# for. Anything else emits a single ``unavailable`` observation and never
# has its ``raw_usage`` payload inspected.
SUPPORTED_HARNESSES = frozenset({"openai_compatible", "anthropic_api"})

# R1: role vocabulary reused from loop_events.FEEDBACK_ROLES so token events
# stay in the same closed, already-reviewed vocabulary as other actor events.
TOKEN_ROLES = frozenset({
    "implementer", "diagnostician", "repairer", "verifier", "remediator", "parent",
})

# The exact, closed set of fields a persisted token-usage event may carry.
TOKEN_EVENT_FIELDS = frozenset({
    "schema_version", "run_id", "spec_id", "ts", "provider", "harness", "model",
    "role", "phase", "attempt_ordinal", "input_tokens", "output_tokens",
    "reasoning_tokens", "cached_tokens", "request_count", "cost", "currency",
    "duration_s", "measurement_state",
})

# R2/AC1: named rejection reasons. Every rejection must map onto one of
# these -- never a generic catch-all -- so failure tests can assert on the
# exact privacy/consistency violation that was caught.
REJECTION_REASONS = frozenset({
    "empty_or_invalid_input",
    "unsupported_usage_field",
    "credential_shaped_key",
    "transcript_like_payload",
    "absolute_path_field",
    "negative_token_count",
    "non_numeric_token_count",
    "inconsistent_total",
})

# Canonical token dimension -> accepted provider-field aliases. Any key in
# a raw_usage payload that is not one of these aliases is, by definition,
# not structured usage metadata this adapter is allowed to normalize.
_FIELD_ALIASES: Dict[str, tuple] = {
    "input_tokens": ("input_tokens", "prompt_tokens"),
    "output_tokens": ("output_tokens", "completion_tokens"),
    "reasoning_tokens": ("reasoning_tokens",),
    "cached_tokens": ("cached_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"),
}
_TOTAL_ALIASES = ("total_tokens",)
_ALL_KNOWN_ALIASES = frozenset(
    alias for aliases in _FIELD_ALIASES.values() for alias in aliases
) | frozenset(_TOTAL_ALIASES)

_CREDENTIAL_KEY_RE = re.compile(
    r"(api[_-]?key|secret|password|passwd|credential|authorization|auth[_-]?token|bearer)",
    re.IGNORECASE,
)
_TRANSCRIPT_KEYS = frozenset({
    "prompt", "response", "text", "content", "messages", "transcript",
    "completion", "conversation", "raw", "raw_response", "output_text",
})


class TokenUsageRejected(ValueError):
    """Raised internally to short-circuit normalization with a named reason."""

    def __init__(self, reason: str):
        assert reason in REJECTION_REASONS, f"unregistered rejection reason: {reason}"
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class TokenUsageResult:
    """Outcome of :func:`normalize_provider_usage`.

    ``event`` is populated only when ``accepted`` is True. A rejected input
    is never persisted (R2); ``reason`` is one of REJECTION_REASONS.
    """

    accepted: bool
    event: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


def _looks_like_absolute_path(value: str) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return value.startswith("/") or value.startswith("~") or bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _validate_raw_usage(raw_usage: Dict[str, Any]) -> Dict[str, Optional[int]]:
    """Validate and extract known token dimensions from raw_usage.

    Raises TokenUsageRejected with a specific reason on any privacy or
    consistency violation. Returns a dict of canonical dimension -> int
    (only for dimensions that were present).
    """
    for key, value in raw_usage.items():
        if key in _ALL_KNOWN_ALIASES:
            continue
        if _CREDENTIAL_KEY_RE.search(key):
            raise TokenUsageRejected("credential_shaped_key")
        if key in _TRANSCRIPT_KEYS or (isinstance(value, str) and len(value) > 32):
            raise TokenUsageRejected("transcript_like_payload")
        if isinstance(value, str) and _looks_like_absolute_path(value):
            raise TokenUsageRejected("absolute_path_field")
        raise TokenUsageRejected("unsupported_usage_field")

    extracted: Dict[str, Optional[int]] = {}
    for canonical_key, aliases in _FIELD_ALIASES.items():
        present = [a for a in aliases if a in raw_usage]
        if not present:
            extracted[canonical_key] = None
            continue
        raw_value = raw_usage[present[0]]
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise TokenUsageRejected("non_numeric_token_count")
        if isinstance(raw_value, float) and not raw_value.is_integer():
            raise TokenUsageRejected("non_numeric_token_count")
        int_value = int(raw_value)
        if int_value < 0:
            raise TokenUsageRejected("negative_token_count")
        extracted[canonical_key] = int_value

    total_alias = next((a for a in _TOTAL_ALIASES if a in raw_usage), None)
    if total_alias is not None:
        total_value = raw_usage[total_alias]
        if isinstance(total_value, bool) or not isinstance(total_value, (int, float)):
            raise TokenUsageRejected("non_numeric_token_count")
        total_value = int(total_value)
        if total_value < 0:
            raise TokenUsageRejected("negative_token_count")
        # R4: never sum token classes whose provider semantics overlap.
        # `reasoning_tokens` and `cached_tokens` are commonly subsets of
        # `output_tokens`/`input_tokens` respectively (OpenAI- and
        # Anthropic-shaped usage alike), so only input+output are checked
        # against a provider-reported total -- and only when both are
        # themselves present, since a total covering fields this adapter
        # never received cannot be verified.
        if extracted["input_tokens"] is not None and extracted["output_tokens"] is not None:
            base_sum = extracted["input_tokens"] + extracted["output_tokens"]
            if total_value != base_sum:
                raise TokenUsageRejected("inconsistent_total")

    return extracted


def _safe_str(value: Any, max_len: int = 128) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > max_len:
        raise TokenUsageRejected("unsupported_usage_field")
    return value


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_provider_usage(
    *,
    run_id: str,
    spec_id: str,
    harness: str,
    provider: str,
    model: str,
    role: str,
    phase: str,
    attempt_ordinal: int,
    raw_usage: Optional[Dict[str, Any]],
    requested_dimensions: Sequence[str] = ("input_tokens", "output_tokens"),
    duration_s: Optional[float] = None,
    request_count: Optional[int] = None,
    cost: Optional[float] = None,
    currency: Optional[str] = None,
    ts: Optional[str] = None,
) -> TokenUsageResult:
    """The single narrow adapter boundary (R3).

    Accepts already-structured provider usage metadata (a plain dict of
    numeric fields, exactly what llm_client.py providers already parse out
    of a JSON response) and normalizes it into the closed R1 event shape.
    Never reads a transcript, never calls out to a provider.
    """
    if role not in TOKEN_ROLES:
        return TokenUsageResult(False, reason="unsupported_usage_field")
    from loop_events import PHASE_IDS
    if phase not in PHASE_IDS:
        return TokenUsageResult(False, reason="unsupported_usage_field")
    if not isinstance(attempt_ordinal, int) or isinstance(attempt_ordinal, bool) or attempt_ordinal < 1:
        return TokenUsageResult(False, reason="unsupported_usage_field")

    try:
        provider_s = _safe_str(provider)
        harness_s = _safe_str(harness)
        model_s = _safe_str(model, max_len=256)
        currency_s = _safe_str(currency, max_len=8) if currency is not None else None
    except TokenUsageRejected as exc:
        return TokenUsageResult(False, reason=exc.reason)

    if duration_s is not None and (not isinstance(duration_s, (int, float)) or duration_s < 0):
        return TokenUsageResult(False, reason="negative_token_count")
    if request_count is not None and (
        not isinstance(request_count, int) or isinstance(request_count, bool) or request_count < 0
    ):
        return TokenUsageResult(False, reason="negative_token_count")
    if cost is not None and (not isinstance(cost, (int, float)) or cost < 0):
        return TokenUsageResult(False, reason="negative_token_count")

    base = dict(
        schema_version=TOKEN_EVENT_SCHEMA_VERSION,
        run_id=run_id, spec_id=spec_id, ts=ts or _iso_utc_now(),
        provider=provider_s, harness=harness_s, model=model_s,
        role=role, phase=phase, attempt_ordinal=attempt_ordinal,
        request_count=request_count, cost=cost, currency=currency_s,
        duration_s=duration_s,
    )

    if harness not in SUPPORTED_HARNESSES:
        # R3: unsupported harness -> one unavailable observation, never a
        # rejection, and raw_usage (if any was even passed) is never read.
        event = {
            **base,
            "input_tokens": None, "output_tokens": None,
            "reasoning_tokens": None, "cached_tokens": None,
            "measurement_state": "unavailable",
        }
        return TokenUsageResult(True, event=event)

    if not raw_usage:
        event = {
            **base,
            "input_tokens": None, "output_tokens": None,
            "reasoning_tokens": None, "cached_tokens": None,
            "measurement_state": "unavailable",
        }
        return TokenUsageResult(True, event=event)

    if not isinstance(raw_usage, dict):
        return TokenUsageResult(False, reason="empty_or_invalid_input")

    try:
        extracted = _validate_raw_usage(raw_usage)
    except TokenUsageRejected as exc:
        return TokenUsageResult(False, reason=exc.reason)

    present = {dim for dim in requested_dimensions if extracted.get(dim) is not None}
    if present == set(requested_dimensions):
        state = "measured"
    elif present:
        state = "partial"
    else:
        state = "unavailable"

    event = {
        **base,
        "input_tokens": extracted["input_tokens"],
        "output_tokens": extracted["output_tokens"],
        "reasoning_tokens": extracted["reasoning_tokens"],
        "cached_tokens": extracted["cached_tokens"],
        "measurement_state": state,
    }
    return TokenUsageResult(True, event=event)


# ---------------------------------------------------------------------------
# R4: deterministic per-run aggregation
# ---------------------------------------------------------------------------

_COMPONENT_FIELDS = ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens")


def derive_token_measurements(events: Iterable[Dict[str, Any]], run_id: str, spec_id: str) -> Dict[str, Any]:
    """Aggregate accepted token_usage events for one run/spec deterministically.

    Iterates the already-persisted event stream exactly once; since a
    rejected input is never persisted, and each accepted event is written
    exactly once by its caller, straight summation cannot double-count.
    Token classes with overlapping provider semantics are never summed
    into one another -- each stays a separate labeled total.
    """
    totals: Dict[str, int] = {f: 0 for f in _COMPONENT_FIELDS}
    have_component = {f: False for f in _COMPONENT_FIELDS}
    request_count_total = 0
    have_request_count = False
    cost_total = 0.0
    have_cost = False
    currencies: set = set()
    duration_total = 0.0
    have_duration = False
    state_counts = {s: 0 for s in ("measured", "partial", "unavailable")}
    by_phase: Dict[str, Dict[str, Any]] = {}
    by_phase_have: Dict[str, Dict[str, bool]] = {}
    event_count = 0

    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("event") != "token_usage":
            continue
        if ev.get("run_id") != run_id or ev.get("spec_id") != spec_id:
            continue
        state = ev.get("measurement_state")
        if state not in ("measured", "partial", "unavailable"):
            continue
        event_count += 1
        state_counts[state] += 1

        phase = ev.get("phase") or "unknown"
        bucket = by_phase.setdefault(phase, {
            **{f: 0 for f in _COMPONENT_FIELDS},
            "event_count": 0,
            "measurement_state_counts": {s: 0 for s in ("measured", "partial", "unavailable")},
        })
        bucket_have = by_phase_have.setdefault(phase, {f: False for f in _COMPONENT_FIELDS})
        bucket["event_count"] += 1
        bucket["measurement_state_counts"][state] += 1

        for f in _COMPONENT_FIELDS:
            v = ev.get(f)
            # DevKB python.md:87 -- absence must not render as zero. A
            # component this event never measured (None) must not make the
            # aggregate look like it measured a genuine 0 for that component.
            if isinstance(v, int) and not isinstance(v, bool):
                totals[f] += v
                have_component[f] = True
                bucket[f] += v
                bucket_have[f] = True

        rc = ev.get("request_count")
        if isinstance(rc, int) and not isinstance(rc, bool):
            request_count_total += rc
            have_request_count = True

        cost = ev.get("cost")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            cost_total += cost
            have_cost = True
            currency = ev.get("currency")
            if currency:
                currencies.add(currency)

        dur = ev.get("duration_s")
        if isinstance(dur, (int, float)) and not isinstance(dur, bool):
            duration_total += dur
            have_duration = True

    if event_count == 0:
        return {
            "event_count": 0,
            "measurement_state": "unavailable",
            "measurement_state_counts": {s: 0 for s in ("measured", "partial", "unavailable")},
            "input_tokens": None, "output_tokens": None,
            "reasoning_tokens": None, "cached_tokens": None,
            "request_count": None, "cost": None, "currency": None,
            "duration_s": None, "by_phase": {},
        }

    overall_state = (
        "measured" if state_counts["measured"] and not state_counts["partial"] and not state_counts["unavailable"]
        else "partial" if (state_counts["measured"] or state_counts["partial"])
        else "unavailable"
    )

    for phase, bucket in by_phase.items():
        bucket_have = by_phase_have[phase]
        for f in _COMPONENT_FIELDS:
            if not bucket_have[f]:
                bucket[f] = None

    return {
        "event_count": event_count,
        "measurement_state": overall_state,
        "measurement_state_counts": state_counts,
        "input_tokens": totals["input_tokens"] if have_component["input_tokens"] else None,
        "output_tokens": totals["output_tokens"] if have_component["output_tokens"] else None,
        "reasoning_tokens": totals["reasoning_tokens"] if have_component["reasoning_tokens"] else None,
        "cached_tokens": totals["cached_tokens"] if have_component["cached_tokens"] else None,
        "request_count": request_count_total if have_request_count else None,
        "cost": round(cost_total, 6) if have_cost else None,
        "currency": (currencies.pop() if len(currencies) == 1 else ("mixed" if len(currencies) > 1 else None)),
        "duration_s": round(duration_total, 3) if have_duration else None,
        "by_phase": by_phase,
    }


def apply_token_measurements(metrics: Dict[str, Any], aggregate: Dict[str, Any]) -> None:
    """Project an aggregate onto a metrics row as an optional-additive field.

    Mirrors SPEC-196's `apply_phase_measurements` shape: legacy rows that
    never call this remain valid with token telemetry simply absent, which
    downstream analysis treats as unavailable rather than zero.
    """
    metrics["token_usage"] = aggregate


# ---------------------------------------------------------------------------
# R5: read-only cohort report
# ---------------------------------------------------------------------------

REPORT_GROUP_DIMENSIONS = ("model", "harness", "spec_type", "complexity_band", "outcome", "phase")


def _percentile(sorted_values: List[float], pct: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    d0 = sorted_values[f] * (c - k)
    d1 = sorted_values[c] * (k - f)
    return d0 + d1


def _total_from_components(input_tokens: Optional[int], output_tokens: Optional[int]) -> Optional[int]:
    if input_tokens is None or output_tokens is None:
        return None
    return input_tokens + output_tokens


def _run_total_tokens(row: Dict[str, Any]) -> Optional[int]:
    tu = row.get("token_usage")
    if not tu or tu.get("measurement_state") == "unavailable":
        return None
    return _total_from_components(tu.get("input_tokens"), tu.get("output_tokens"))


def build_token_report(rows: List[Dict[str, Any]], group_by: Sequence[str] = REPORT_GROUP_DIMENSIONS) -> Dict[str, Any]:
    """R5: group observed runs by declared strata without a hiding average.

    ``rows`` are enriched metrics dicts each carrying model/harness/
    spec_type/complexity_band/outcome and an optional ``token_usage``
    aggregate (as produced by :func:`derive_token_measurements`). Every
    group is reported separately; no cross-stratum aggregate value is
    emitted. When grouping by ``phase``, each row contributes its
    phase-scoped totals from ``token_usage.by_phase`` -- never the
    run-level total repeated under every phase it touched.
    """
    groups: Dict[tuple, Dict[str, Any]] = {}
    group_by_phase = "phase" in group_by
    for row in rows:
        run_tu = row.get("token_usage") or {}
        phases = run_tu.get("by_phase") or {}
        # A row with no phase-scoped token data (e.g. token telemetry
        # entirely unavailable for that run) still needs exactly one
        # group membership; its phase dimension is reported as None
        # (unavailable), never an internal sentinel string.
        iter_phases = phases if (group_by_phase and phases) else {None: None}
        for phase_name, phase_bucket in iter_phases.items():
            if group_by_phase:
                key = tuple(row.get(dim) if dim != "phase" else phase_name for dim in group_by)
            else:
                key = tuple(row.get(dim) for dim in group_by)
            g = groups.setdefault(key, {
                "key": dict(zip(group_by, key)),
                "sample_size": 0,
                "completed": 0,
                "totals": [],
                "durations": [],
                "state_counts": {"measured": 0, "partial": 0, "unavailable": 0, "rejected": 0},
            })
            g["sample_size"] += 1
            if row.get("outcome") == "completed" or row.get("status") == "completed":
                g["completed"] += 1

            if group_by_phase and phase_bucket is not None:
                total = _total_from_components(phase_bucket.get("input_tokens"), phase_bucket.get("output_tokens"))
                state_counts = phase_bucket.get("measurement_state_counts") or {}
                state = max(state_counts, key=state_counts.get) if state_counts else "unavailable"
            else:
                total = _run_total_tokens(row)
                state = run_tu.get("measurement_state", "unavailable")

            if total is not None:
                g["totals"].append(total)
            duration = run_tu.get("duration_s")
            if duration is not None:
                g["durations"].append(duration)
            g["state_counts"][state] = g["state_counts"].get(state, 0) + 1

    result_groups = []
    for g in groups.values():
        totals_sorted = sorted(g["totals"])
        durations_sorted = sorted(g["durations"])
        result_groups.append({
            "group": g["key"],
            "sample_size": g["sample_size"],
            "completion_rate": round(g["completed"] / g["sample_size"], 4) if g["sample_size"] else None,
            "token_total_median": statistics.median(totals_sorted) if totals_sorted else None,
            "token_total_p10": _percentile(totals_sorted, 0.10),
            "token_total_p90": _percentile(totals_sorted, 0.90),
            "duration_s_median": statistics.median(durations_sorted) if durations_sorted else None,
            "measurement_state_counts": g["state_counts"],
        })
    return {"schema_version": TOKEN_EVENT_SCHEMA_VERSION, "groups": result_groups}


# ---------------------------------------------------------------------------
# R6-R8: evidence-gated forecast and advisory efficiency comparison
# ---------------------------------------------------------------------------

MIN_COHORT_SAMPLES = 10
MIN_PER_ROUTE_SAMPLES = 3
MAX_UNAVAILABLE_RATIO = 0.30


def derive_cohort(
    rows: List[Dict[str, Any]], *, model_or_tier: str, harness: str, spec_type: str, complexity_band: str,
) -> List[Dict[str, Any]]:
    """R6: transparent, deterministic cohort membership rule."""
    return [
        row for row in rows
        if row.get("model") == model_or_tier
        and row.get("harness") == harness
        and row.get("spec_type") == spec_type
        and row.get("complexity_band") == complexity_band
    ]


@dataclass
class ForecastResult:
    status: str  # "forecast" | "insufficient_evidence"
    failed_gates: List[str] = field(default_factory=list)
    cohort_size: int = 0
    estimate_denominator: int = 0
    exclusions: List[str] = field(default_factory=list)
    point_estimate: Optional[float] = None
    interval_low: Optional[float] = None
    interval_high: Optional[float] = None
    assumptions: List[str] = field(default_factory=list)
    source_row_ids: List[str] = field(default_factory=list)
    generated_at: str = ""
    completion_rate: Optional[float] = None
    duration_interval_low: Optional[float] = None
    duration_interval_high: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "failed_gates": self.failed_gates,
            "cohort_size": self.cohort_size,
            "estimate_denominator": self.estimate_denominator,
            "exclusions": self.exclusions,
            "point_estimate": self.point_estimate,
            "interval_low": self.interval_low,
            "interval_high": self.interval_high,
            "assumptions": self.assumptions,
            "source_row_ids": self.source_row_ids,
            "generated_at": self.generated_at,
            "completion_rate": self.completion_rate,
            "duration_interval_low": self.duration_interval_low,
            "duration_interval_high": self.duration_interval_high,
        }


def forecast_spec(
    cohort: List[Dict[str, Any]], *, compared_routes: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> ForecastResult:
    """R6/R7: deterministic median + empirical-interval baseline with abstention.

    ``cohort`` is the compatible-run cohort from :func:`derive_cohort`.
    ``compared_routes`` (optional) maps a model/tier label to its own
    sub-cohort, used only for the >=3-per-route gate when the caller
    intends a routing comparison.
    """
    now = _iso_utc_now()
    completed = [
        r for r in cohort
        if (r.get("token_usage") or {}).get("measurement_state") in ("measured", "partial")
    ]
    failed_gates: List[str] = []

    if len(completed) < MIN_COHORT_SAMPLES:
        failed_gates.append(f"min_cohort_samples: have {len(completed)}, need {MIN_COHORT_SAMPLES}")

    unavailable_or_rejected = [
        r for r in cohort
        if (r.get("token_usage") or {}).get("measurement_state") in ("unavailable", "rejected", None)
    ]
    ratio = len(unavailable_or_rejected) / len(cohort) if cohort else 1.0
    if ratio > MAX_UNAVAILABLE_RATIO:
        failed_gates.append(f"max_unavailable_ratio: have {ratio:.2f}, limit {MAX_UNAVAILABLE_RATIO}")

    if compared_routes:
        for label, sub_cohort in compared_routes.items():
            sub_completed = [
                r for r in sub_cohort
                if (r.get("token_usage") or {}).get("measurement_state") in ("measured", "partial")
            ]
            if len(sub_completed) < MIN_PER_ROUTE_SAMPLES:
                failed_gates.append(
                    f"min_per_route_samples[{label}]: have {len(sub_completed)}, need {MIN_PER_ROUTE_SAMPLES}"
                )

    if failed_gates:
        return ForecastResult(
            status="insufficient_evidence", failed_gates=failed_gates,
            cohort_size=len(cohort), estimate_denominator=0,
            generated_at=now,
        )

    # AC6: partial rows missing a required total component (input or
    # output) are excluded from the total-token estimate but remain
    # visible in coverage diagnostics via cohort_size vs estimate_denominator.
    usable = []
    exclusions = []
    for r in completed:
        total = _run_total_tokens(r)
        if total is None:
            exclusions.append(r.get("metrics_row_id", "unknown"))
        else:
            usable.append((r.get("metrics_row_id", "unknown"), total))

    if not usable:
        return ForecastResult(
            status="insufficient_evidence",
            failed_gates=["estimate_denominator: 0 usable total-token observations"],
            cohort_size=len(cohort), estimate_denominator=0, exclusions=exclusions,
            generated_at=now,
        )

    values = sorted(v for _, v in usable)
    point = statistics.median(values)
    low = _percentile(values, 0.10)
    high = _percentile(values, 0.90)

    # R8/AC7: carry completion rate and a duration interval alongside the
    # token interval so an efficiency comparison can name the full
    # trade-off, not token cost alone.
    completed_count = sum(
        1 for r in cohort if r.get("outcome") == "completed" or r.get("status") == "completed"
    )
    completion_rate = round(completed_count / len(cohort), 4) if cohort else None
    durations = sorted(
        d for r in cohort
        if (d := (r.get("token_usage") or {}).get("duration_s")) is not None
    )
    duration_low = _percentile(durations, 0.10)
    duration_high = _percentile(durations, 0.90)

    return ForecastResult(
        status="forecast",
        cohort_size=len(cohort),
        estimate_denominator=len(usable),
        exclusions=exclusions,
        point_estimate=point,
        interval_low=low,
        interval_high=high,
        assumptions=[
            "deterministic robust baseline: median plus empirical 10th/90th percentile interval",
            "cohort membership requires exact model/harness/spec_type/complexity_band match",
            "partial observations missing a required total-token component are excluded from the estimate",
        ],
        source_row_ids=[rid for rid, _ in usable],
        generated_at=now,
        completion_rate=completion_rate,
        duration_interval_low=duration_low,
        duration_interval_high=duration_high,
    )


EFFICIENCY_VOCABULARY = frozenset({"no_recommendation", "candidate_more_efficient", "candidate_less_efficient"})


def compare_model_efficiency(
    route_a: Dict[str, Any], route_b: Dict[str, Any], forecast_a: ForecastResult, forecast_b: ForecastResult,
) -> Dict[str, Any]:
    """R8: advisory-only comparison. Never mutates routing/config."""
    if forecast_a.status != "forecast" or forecast_b.status != "forecast":
        return {"conclusion": "no_recommendation", "reason": "one or both routes lack a gated forecast"}

    if forecast_a.estimate_denominator < MIN_PER_ROUTE_SAMPLES or forecast_b.estimate_denominator < MIN_PER_ROUTE_SAMPLES:
        return {"conclusion": "no_recommendation", "reason": "underpowered route sample"}

    if forecast_a.point_estimate is None or forecast_b.point_estimate is None:
        return {"conclusion": "no_recommendation", "reason": "missing point estimate"}

    if forecast_a.point_estimate == forecast_b.point_estimate:
        conclusion = "no_recommendation"
    elif forecast_a.point_estimate < forecast_b.point_estimate:
        conclusion = "candidate_more_efficient"
    else:
        conclusion = "candidate_less_efficient"

    return {
        "conclusion": conclusion,
        "route_a": route_a,
        "route_b": route_b,
        "token_interval_a": [forecast_a.interval_low, forecast_a.interval_high],
        "token_interval_b": [forecast_b.interval_low, forecast_b.interval_high],
        "duration_interval_a": [forecast_a.duration_interval_low, forecast_a.duration_interval_high],
        "duration_interval_b": [forecast_b.duration_interval_low, forecast_b.duration_interval_high],
        "completion_rate_a": forecast_a.completion_rate,
        "completion_rate_b": forecast_b.completion_rate,
        "sample_size_a": forecast_a.estimate_denominator,
        "sample_size_b": forecast_b.estimate_denominator,
        "trade_off": (
            "lower measured/partial median token total for route_a"
            if conclusion == "candidate_more_efficient"
            else "lower measured/partial median token total for route_b"
            if conclusion == "candidate_less_efficient"
            else "no material difference in the deterministic baseline"
        ),
    }


# ---------------------------------------------------------------------------
# R9: weekly-quota projection (result state only, never the quota value)
# ---------------------------------------------------------------------------

QUOTA_PROJECTION_STATES = frozenset({"likely_fits", "uncertain", "likely_exceeds", "quota_unknown"})


def project_quota(
    *, remaining_amount: Optional[float], reset_boundary: Optional[str], forecast: ForecastResult,
) -> str:
    """R9/AC8: tri-state (or quota_unknown) result. The caller must never
    persist ``remaining_amount``/``reset_boundary`` themselves; this
    function returns only the categorical result string.
    """
    if remaining_amount is None or reset_boundary is None:
        return "quota_unknown"
    if not isinstance(remaining_amount, (int, float)) or isinstance(remaining_amount, bool) or remaining_amount < 0:
        return "quota_unknown"
    if forecast.status != "forecast" or forecast.interval_low is None or forecast.interval_high is None:
        return "quota_unknown"

    if remaining_amount >= forecast.interval_high:
        return "likely_fits"
    if remaining_amount < forecast.interval_low:
        return "likely_exceeds"
    return "uncertain"


# ---------------------------------------------------------------------------
# CLI (R6/R9): evidence-gated forecast for one selected draft/ready spec.
# ---------------------------------------------------------------------------

def _load_enriched_rows(metrics_dir: "Path", specs_dir: "Path | None") -> List[Dict[str, Any]]:
    from analyze_metrics import enrich_rows_for_token_report, load_metrics_files

    metrics = load_metrics_files(str(metrics_dir))
    return enrich_rows_for_token_report(metrics, specs_dir)


def main(argv=None) -> int:
    import argparse
    import json as _json
    from pathlib import Path as _Path

    parser = argparse.ArgumentParser(
        description="SPEC-298 evidence-gated token forecast / quota projection (read-only)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    fc = sub.add_parser("forecast", help="Evidence-gated forecast for one draft/ready spec")
    fc.add_argument("metrics_dir")
    fc.add_argument("--specs-dir", default=None)
    fc.add_argument("--model", required=True)
    fc.add_argument("--harness", required=True)
    fc.add_argument("--spec-type", required=True)
    fc.add_argument("--complexity-band", required=True)
    fc.add_argument(
        "--quota-remaining", type=float, default=None,
        help="Authorized numeric remaining quota amount (R9). Never persisted.",
    )
    fc.add_argument(
        "--quota-reset", default=None,
        help="Authorized quota reset boundary label (R9). Never persisted.",
    )

    args = parser.parse_args(argv)
    specs_dir = _Path(args.specs_dir) if args.specs_dir else None
    rows = _load_enriched_rows(_Path(args.metrics_dir), specs_dir)

    if args.command == "forecast":
        cohort = derive_cohort(
            rows, model_or_tier=args.model, harness=args.harness,
            spec_type=args.spec_type, complexity_band=args.complexity_band,
        )
        result = forecast_spec(cohort)
        output = result.to_dict()
        # R9/AC8: the quota result state crosses the boundary; the
        # remaining amount and reset boundary supplied on argv never do.
        output["quota_projection"] = project_quota(
            remaining_amount=args.quota_remaining, reset_boundary=args.quota_reset, forecast=result,
        )
        print(_json.dumps(output, indent=2, default=str))
        return 0

    return 2


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
