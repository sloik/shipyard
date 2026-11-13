"""Opt-in recommendations at existing parent boundaries, never a lifecycle/cache owner.

Decision/context artifacts are the only persistence. Native receipts and supported
reuse APIs remain authoritative; this module cannot waive, run or stop a gate.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import spec_artifacts
from spec_frontmatter import parse_spec_file

SCHEMA = "1.0.0"
MEASURES = ("native_seconds", "preparation_seconds", "reasoning_seconds", "human_queue_wait_seconds", "invocations")
DISPOSITIONS = {"continue", "reuse", "propose_amendment", "recommend_replacement"}


class EconomicsError(ValueError):
    """Invalid context cannot authorize an automatic action."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EconomicsError(f"{label} must be named")
    return value


def _obligation_ids(spec_file: Path) -> list[str]:
    return re.findall(r"^\s*- \[[ xX]\] ((?:R|AC)-?\d+)\b", spec_file.read_text(), re.M)


def _number(value: Any, label: str, *, positive: bool = False, integer: bool = False) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or value < 0 or (positive and value == 0) or (integer and not isinstance(value, int))):
        raise EconomicsError(f"invalid {label}")


def load_policy(root: Path) -> dict[str, Any]:
    """Use the canonical multidocument config reader; missing feature stays legacy."""
    from nightshift_coordinator import load_yaml
    path = Path(root) / "config.yaml"
    if not path.exists():
        return {}
    policy = load_yaml(path).get("verification_economics", {})
    if not isinstance(policy, Mapping):
        raise EconomicsError("verification_economics must be a mapping")
    return dict(policy)


def _policy(policy: Mapping[str, Any]) -> None:
    if type(policy.get("enabled", False)) is not bool:
        raise EconomicsError("enabled must be boolean")
    allowed = {"enabled", "soft_duration_seconds", "soft_invocations", "soft_spend"}
    if set(policy) - allowed:
        raise EconomicsError("unknown economics policy field")
    for key in ("soft_duration_seconds", "soft_invocations"):
        if key in policy:
            _number(policy[key], key, positive=True, integer=key == "soft_invocations")
    if "soft_spend" in policy:
        spend = policy["soft_spend"]
        if not isinstance(spend, Mapping) or set(spend) != {"amount", "currency"}:
            raise EconomicsError("soft_spend requires amount and currency")
        _number(spend["amount"], "soft_spend", positive=True)
        _text(spend["currency"], "currency")


def _receipt(row: Mapping[str, Any]) -> dict[str, Any]:
    """Unknown values cannot be relabelled as zero. A zero needs measured provenance."""
    row = dict(row)
    if set(row) != {"receipt_id", "run_id", "evidence", "source", "measurements", "failures"}:
        raise EconomicsError("receipt shape mismatch")
    _text(row["receipt_id"], "receipt_id")
    _text(row["run_id"], "originating run")
    evidence = row["evidence"]
    if not isinstance(evidence, Mapping) or set(evidence) != {"path", "sha256"}:
        raise EconomicsError("receipt needs original hash reference")
    relative = Path(_text(evidence["path"], "receipt path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise EconomicsError("receipt reference must be portable")
    if not isinstance(evidence["sha256"], str) or len(evidence["sha256"]) != 64:
        raise EconomicsError("receipt digest missing")
    if not isinstance(row["failures"], list):
        raise EconomicsError("failures must be retained as a list")
    measurements = row["measurements"]
    if not isinstance(measurements, Mapping) or set(measurements) != {*MEASURES, "spend"}:
        raise EconomicsError("every measurement must be measured or explicitly unknown")
    for key, value in measurements.items():
        if not isinstance(value, Mapping) or set(value) != {"value", "unit", "scope", "availability"}:
            raise EconomicsError("measurement shape mismatch")
        _text(value["scope"], "measurement scope")
        if key != "spend" and value["unit"] != ("count" if key == "invocations" else "seconds"):
            raise EconomicsError("measurement unit mismatch")
        if value["availability"] == "unknown":
            if value["value"] is not None:
                raise EconomicsError("unknown measurement cannot become fabricated zero")
        elif value["availability"] == "measured":
            _number(value["value"], key, integer=key == "invocations")
            _text(value["unit"], "measurement unit")
        else:
            raise EconomicsError("unknown measurement availability")
    return row


def _unknown_measurements() -> dict[str, Any]:
    result = {key: {"value": None, "unit": "count" if key == "invocations" else "seconds",
                    "scope": "not measured by this receipt", "availability": "unknown"} for key in MEASURES}
    result["spend"] = {"value": None, "unit": None, "scope": "provider billing unavailable", "availability": "unknown"}
    return result


def _lineage(spec_file: Path) -> list[str]:
    """The existing parent relationship carries recovery/new-run cumulative history."""
    ids: list[str] = []
    selected = spec_file
    while True:
        fm = parse_spec_file(selected).frontmatter
        spec_id = _text(fm.get("id"), "spec ID")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", spec_id):
            raise EconomicsError("unsafe spec identity")
        if spec_id in ids:
            raise EconomicsError("cyclic spec lineage")
        ids.append(spec_id)
        parent = fm.get("parent")
        if not parent:
            return ids
        matches = [p for p in spec_file.parent.glob("*.md") if not p.name.startswith("_")
                   and parse_spec_file(p).frontmatter.get("id") == parent]
        if len(matches) != 1:
            raise EconomicsError("unresolved parent lineage")
        selected = matches[0]


def _history(reports: Path, ids: list[str]) -> list[dict[str, Any]]:
    rows = []
    for spec_id in ids:
        state, entries, _ = spec_artifacts.read_index_state(reports, spec_id)
        if state not in {"missing", "available", "empty"}:
            raise EconomicsError("artifact index cannot reset cumulative history")
        retained = {f"artifacts/{path.name}" for path in spec_artifacts.artifacts_dir(reports, spec_id).glob("verification-economics-*.json")}
        if retained - {entry.get("path") for entry in entries}:
            raise EconomicsError("retained economics artifacts missing from index; history cannot reset")
        for entry in entries:
            if entry.get("type") not in {"decision", "context"}:
                continue
            artifact = spec_artifacts.read_indexed_artifact(reports, spec_id, entry["path"])
            payload = json.loads(artifact["content"])
            record = payload.get("verification_economics")
            if record is not None:
                if record.get("schema_version") != SCHEMA or record.get("record_digest") != _digest(
                        {k: v for k, v in record.items() if k != "record_digest"}):
                    raise EconomicsError("decision schema/digest mismatch")
                rows.append(record)
    return rows


def _cumulative(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in MEASURES:
        values = [r["measurements"][key] for r in receipts]
        known = [v["value"] for v in values if v["availability"] == "measured"]
        result[key] = {"value": sum(known) if values and len(known) == len(values) else None,
                       "known_subtotal": sum(known) if known else None,
                       "unit": "count" if key == "invocations" else "seconds",
                       "scope": "deduplicated original receipts; categories remain separate"}
    currencies = {r["measurements"]["spend"]["unit"] for r in receipts
                  if r["measurements"]["spend"]["availability"] == "measured"}
    result["spend"] = {}
    for currency in sorted(currencies):
        values = [r["measurements"]["spend"] for r in receipts]
        known = [v["value"] for v in values if v["availability"] == "measured" and v["unit"] == currency]
        result["spend"][currency] = {"value": sum(known) if len(known) == len(values) else None,
                                      "known_subtotal": sum(known), "unit": currency}
    return result


def pinned_proposal(repo: Path, spec_file: Path, *, source_ref: str, command: str,
                    action: str, action_id: str, expected_new_evidence: str = "",
                    changed_boundary: str = "") -> dict[str, Any]:
    """Capture current identities through the existing input/toolchain identity API."""
    from verification_report import build_identity
    excluded = {"NIGHTSHIFT_ESCALATION_SIGNOFF", "NIGHTSHIFT_ACTIVE_SPEC", "NIGHTSHIFT_COORDINATOR_SESSION", "NIGHTSHIFT_RUN_ID"}
    env_digest = _digest({k: v for k, v in os.environ.items() if k not in excluded})
    identity = build_identity(repo, source_ref, command=command, env={"environment_digest": env_digest},
                              host=_digest(platform.node()))
    spec_text = spec_file.read_bytes()
    obligations = _obligation_ids(spec_file)
    return {"action": action, "action_id": action_id, "obligations": obligations,
            "identity": {"source": identity["inputs_digest"], "spec": hashlib.sha256(spec_text).hexdigest(),
                         "environment": {k: identity[k] for k in ("env", "toolchain", "device_policy", "host")},
                         "command": {k: identity[k] for k in ("command", "selection", "flags")}},
            "expected_new_evidence": expected_new_evidence, "changed_boundary": changed_boundary}


def import_native_receipt(root: Path, relative_path: str, *, run_id: str) -> dict[str, Any]:
    """Fold an existing suite-sample receipt, without a new native telemetry launch."""
    path = Path(root) / relative_path
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts or path.is_symlink():
        raise EconomicsError("native receipt requires a portable regular reference")
    payload = json.loads(path.read_text())
    native = payload.get("retained_native", payload)
    if native.get("kind") != "native":
        raise EconomicsError("not a supported suite-sample native receipt")
    measurements = _unknown_measurements()
    for key, value in (("native_seconds", native.get("wall_s")),
                       ("invocations", 0 if native.get("launch_denied") is True else 1)):
        if value is not None:
            measurements[key].update(value=value, availability="measured", scope="suite-sample command wall time" if key == "native_seconds" else "suite-sample observed launch")
    spend = native.get("spend")
    if isinstance(spend, Mapping) and spend.get("amount") is not None:
        measurements["spend"].update(value=spend["amount"], unit=spend.get("currency"),
                                     scope="available spend retained by original receipt", availability="measured")
    return _receipt({"receipt_id": _text(native.get("invocation_identity"), "native invocation identity"),
                     "run_id": native.get("run_id") or run_id,
                     "source": {"kind": "native"},
                     "evidence": {"path": relative_path, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                     "measurements": measurements,
                     "failures": payload.get("failure_names", []) or ([] if native.get("native_exit_code") == 0 else
                                 [{"native_exit_code": native.get("native_exit_code"), "state": payload.get("state", "unknown")}])})


def import_timing_receipt(root: Path, relative_path: str, *, run_id: str, stage: str) -> dict[str, Any]:
    """Read retained normal-boundary instrumentation, keeping nonnative categories distinct.

    Sidecars are mutable while work runs; import only a retained final snapshot. A
    later changed original fails closed rather than resetting/double-counting it.
    """
    import record_metrics
    categories = {"surface_preparation": "preparation_seconds", "coordination_gate_wait": "human_queue_wait_seconds"}
    if stage not in categories:
        raise EconomicsError("stage cannot be relabelled as reasoning/native time")
    path = Path(root) / relative_path
    payload = json.loads(path.read_text())
    validated = record_metrics.validate_timing_record("stage", {"stage": stage, "seconds": payload.get("stages", {}).get(stage)})
    measurements = _unknown_measurements()
    seconds = validated["seconds"]
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
        measurements[categories[stage]].update(value=seconds, availability="measured", scope=f"record_metrics stage {stage}; completed retained snapshot")
    return _receipt({"receipt_id": _digest({"run_id": run_id, "stage": stage, "path": relative_path}),
                     "run_id": run_id, "source": {"kind": "timing", "stage": stage},
                     "evidence": {"path": relative_path, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                     "measurements": measurements, "failures": []})


def supported_reuse(context: Mapping[str, Any], identity: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """Always ask the existing owner, including on replay; never mint reuse eligibility."""
    proof = context.get("reuse")
    if proof is None:
        return {"eligible": False, "reason": "no_supported_proof"}
    if not isinstance(proof, Mapping):
        raise EconomicsError("reuse proof must name its supported API")
    if proof.get("kind") == "ledger":
        from verification_report import reuse_decision
        current = {"inputs_digest": identity["source"], **identity["environment"], **identity["command"]}
        if proof.get("spec_digest") != identity["spec"]:
            return {"eligible": False, "reason": "contract_binding_missing_or_changed"}
        decision = reuse_decision(proof.get("record"), current, now=now)
        return {"eligible": decision["reuse"], "api": "verification_report.reuse_decision", **decision}
    if proof.get("kind") == "recovery":
        from unblock_spec import recovery_eligibility
        if proof.get("spec_digest") != identity["spec"] or proof.get("identity") != identity:
            return {"eligible": False, "reason": "recovery_boundary_mismatch"}
        decision = recovery_eligibility(proof["record"], proof["current"], now=now)
        return {"api": "unblock_spec.recovery_eligibility", **decision}
    raise EconomicsError("unsupported reuse API")


def checkpoint(root: Path, spec_file: Path, *, run_id: str, proposal: Mapping[str, Any],
               context: Mapping[str, Any] | None = None, policy: Mapping[str, Any] | None = None,
               now: datetime | None = None, controller: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Record then recommend at a stable boundary. No execution or lifecycle effect."""
    root, spec_file = Path(root).resolve(), Path(spec_file).resolve()
    policy = dict(policy) if policy is not None else load_policy(root)
    _policy(policy)
    if not policy.get("enabled", False):
        return {"status": "disabled", "launch_allowed": True, "marks_done": False}
    now = now or datetime.now(timezone.utc)
    context = dict(context or {})
    if set(context) - {"receipts", "owner_signal", "disposition", "reuse"}:
        raise EconomicsError("unsupported context (budget reset/waiver/lifecycle not permitted)")
    proposal = dict(proposal)
    if set(proposal) != {"action_id", "action", "obligations", "identity", "expected_new_evidence", "changed_boundary"}:
        raise EconomicsError("proposal shape mismatch")
    _text(proposal["action"], "proposed action")
    _text(proposal["action_id"], "stable parent action ID")
    _text(run_id, "run_id")
    if not isinstance(proposal["obligations"], list) or not proposal["obligations"]:
        raise EconomicsError("unmet obligations must be retained")
    for obligation in proposal["obligations"]:
        _text(obligation, "obligation ID")
    if not set(proposal["obligations"]).issubset(_obligation_ids(spec_file)):
        raise EconomicsError("proposal names an unknown requirement/AC obligation")
    identity = proposal["identity"]
    if not isinstance(identity, Mapping) or set(identity) != {"source", "spec", "environment", "command"}:
        raise EconomicsError("exact source/spec/environment/command identity required")
    if any(value is None or value == "" or value == {} for value in identity.values()):
        raise EconomicsError("incomplete pinned identity")
    if any(not isinstance(identity[key], str) or not re.fullmatch(r"[a-f0-9]{64}", identity[key]) for key in ("source", "spec")):
        raise EconomicsError("source/spec digest identity required")
    if not isinstance(identity["environment"], Mapping) or set(identity["environment"]) != {"env", "toolchain", "device_policy", "host"}:
        raise EconomicsError("environment identity shape mismatch")
    if not isinstance(identity["command"], Mapping) or set(identity["command"]) != {"command", "selection", "flags"}:
        raise EconomicsError("command identity shape mismatch")
    _text(identity["command"]["command"], "exact command")
    for key in ("expected_new_evidence", "changed_boundary"):
        if not isinstance(proposal[key], str):
            raise EconomicsError("evidence/boundary must be a named string")
    reports = spec_artifacts.reports_root_for_spec_path(spec_file)
    ids = _lineage(spec_file)
    history = _history(reports, ids)
    receipts: dict[str, dict[str, Any]] = {}
    for row in [r for prior in history for r in prior["receipts"]] + list(context.get("receipts", [])):
        validated = _receipt(row)
        evidence_path = root / validated["evidence"]["path"]
        if (evidence_path.is_symlink() or not evidence_path.is_file()
                or not evidence_path.resolve().is_relative_to(root)
                or hashlib.sha256(evidence_path.read_bytes()).hexdigest() != validated["evidence"]["sha256"]):
            raise EconomicsError("original receipt missing or changed; preserve history")
        source = validated["source"]
        if source == {"kind": "native"}:
            observed = import_native_receipt(root, validated["evidence"]["path"], run_id=validated["run_id"])
        elif isinstance(source, Mapping) and source.get("kind") == "timing" and set(source) == {"kind", "stage"}:
            observed = import_timing_receipt(root, validated["evidence"]["path"], run_id=validated["run_id"], stage=source["stage"])
        else:
            raise EconomicsError("unsupported measurement source")
        if observed != validated:
            raise EconomicsError("fabricated measurement or receipt identity differs from original observation")
        key = validated["receipt_id"]
        if key in receipts and receipts[key] != validated:
            raise EconomicsError("receipt identity conflict; history cannot reset")
        receipts[key] = validated
    totals = _cumulative(list(receipts.values()))
    reuse = supported_reuse(context, identity, now=now)
    reasons = []
    signal = context.get("owner_signal", "")
    if not isinstance(signal, str):
        raise EconomicsError("owner signal must be named")
    if signal.strip():
        reasons.append("owner_signal")
    repeated = any(r["proposal"]["action"] == proposal["action"] and r["proposal"]["identity"] == identity
                   and (r["run_id"] != run_id or r["proposal"]["action_id"] != proposal["action_id"]) for r in history)
    if (repeated or reuse["eligible"]) and not proposal["expected_new_evidence"].strip() and not proposal["changed_boundary"].strip():
        reasons.append("no_new_evidence")
    native = totals["native_seconds"]["known_subtotal"]
    count = totals["invocations"]["known_subtotal"]
    if "soft_duration_seconds" in policy and native is not None and native >= policy["soft_duration_seconds"]:
        reasons.append("soft_duration")
    if "soft_invocations" in policy and count is not None and count >= policy["soft_invocations"]:
        reasons.append("soft_invocations")
    if "soft_spend" in policy:
        limit = policy["soft_spend"]
        amount = totals["spend"].get(limit["currency"], {}).get("known_subtotal")
        if amount is not None and amount >= limit["amount"]:
            reasons.append("soft_spend")
    decision = {"schema_version": SCHEMA, "spec_id": ids[0], "run_id": run_id, "lineage": ids,
                "proposal": proposal, "policy": policy, "owner_signal": signal,
                "receipts": sorted(receipts.values(), key=lambda r: r["receipt_id"]),
                "cumulative": totals, "reuse": reuse, "reason_codes": reasons,
                "recommendation": "review_needed" if reasons else "continue",
                "unmet_obligations": proposal["obligations"], "marks_done": False}
    if controller is not None:
        if set(controller) != {"packet_id", "issuance_id"}:
            raise EconomicsError("controller binding requires packet and issuance")
        for value in controller.values():
            _text(value, "controller binding")
        decision["controller"] = dict(controller)
    # The recommendation is independent of disposition, and stable on identical replay.
    decision["record_digest"] = _digest(decision)
    disposition = context.get("disposition")
    applied = None
    if disposition is not None:
        if not isinstance(disposition, Mapping) or set(disposition) != {
                "decision_digest", "kind", "authorized_by", "statement", "evidence_delta", "budget"}:
            raise EconomicsError("disposition requires exact decision, owner authority and finite budget")
        if disposition["decision_digest"] != decision["record_digest"]:
            raise EconomicsError("stale disposition: pinned identity or cumulative history changed")
        kind = disposition["kind"]
        if kind not in DISPOSITIONS:
            raise EconomicsError("no disposition may skip gates or mark Done")
        actor = _text(disposition["authorized_by"], "owner authority")
        if not actor.startswith("human:"):
            raise EconomicsError("agent cost judgment cannot waive a mandatory gate")
        _text(disposition["statement"], "owner statement")
        if kind == "continue":
            delta = _text(disposition["evidence_delta"], "new evidence delta")
            if delta not in {proposal["expected_new_evidence"], proposal["changed_boundary"]}:
                raise EconomicsError("continuation must name the proposed real new evidence/boundary")
            budget = disposition["budget"]
            if not isinstance(budget, Mapping) or set(budget) != {"invocations", "duration_seconds"}:
                raise EconomicsError("continuation needs finite invocation and duration budget")
            _number(budget["invocations"], "budget invocations", positive=True, integer=True)
            _number(budget["duration_seconds"], "budget duration", positive=True)
        elif kind == "reuse" and not reuse["eligible"]:
            raise EconomicsError("reuse refused by existing API")
        applied = dict(disposition)
        previous = [r["disposition"] for r in history if "disposition" in r
                    and r["disposition"]["decision_digest"] == decision["record_digest"]]
        if any(old != applied for old in previous):
            raise EconomicsError("immutable disposition conflicts with retained owner choice")
    def persist(record: dict[str, Any], artifact_type: str) -> dict[str, str]:
        digest = record["record_digest"]
        matches = [r for r in history if r["record_digest"] == digest]
        filename = f"verification-economics-{digest}.json"
        path = spec_artifacts.artifacts_dir(reports, ids[0]) / filename
        if not matches and not path.exists():
            spec_artifacts.write_artifact(reports, ids[0], type=artifact_type, actor="parent",
                                         summary=f"Verification economics {record.get('recommendation', 'disposition')}",
                                         content={"verification_economics": record}, filename=filename)
        if not path.is_file():
            # A parent's identical decision does not replace this spec's own durable context.
            spec_artifacts.write_artifact(reports, ids[0], type=artifact_type, actor="parent",
                                         summary="Verification economics context", content={"verification_economics": record}, filename=filename)
        return {"path": str(path.relative_to(root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    reference = persist(decision, "decision")
    disposition_ref = None
    if applied is not None:
        retained = {**decision, "disposition": applied}
        retained["record_digest"] = _digest({k: v for k, v in retained.items() if k != "record_digest"})
        disposition_ref = persist(retained, "context")
    # SPEC209: advisory emission follows required immutable receipt persistence.
    # Never add observation fields to the digest-bound economics decision.
    try:
        from loop_events import observe_delivery_boundary
        observe_delivery_boundary(reports.parent, ids[0], run_id=run_id,
            action_id=proposal['action_id'], eligibility=reuse['eligible'],
            disposition='abandoned' if applied and applied['kind'] in {'recommend_replacement', 'propose_amendment'} else
                'offered' if reuse['eligible'] else 'not_offered',
            source_receipt_digest=reuse.get('record_digest'),
            demand_receipt_digest=decision['record_digest'], reason_code=reuse.get('reason'))
    except Exception:
        pass
    status = applied["kind"] if applied else decision["recommendation"]
    return {"schema_version": SCHEMA, "status": status, "launch_allowed": status == "continue",
            "decision_digest": decision["record_digest"], "decision": reference, "disposition": disposition_ref,
            "reason_codes": reasons, "unmet_obligations": proposal["obligations"],
            "cumulative": totals, "reuse": reuse, "marks_done": False}
