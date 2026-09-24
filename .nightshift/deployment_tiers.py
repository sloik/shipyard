"""SPEC-294: deployment-environment autonomy tiers.

An optional, per-project ``deployment:`` block in ``config.yaml`` names
environments and, for each, whether a completed spec's candidate merges
automatically (``auto_merge``) or must wait for a durable human
authorization record (``authorize``).  This is a distinct axis from
``runner.tiers`` (model capability per spec) -- this module never selects a
model, only a merge policy.

Zero-behavior-change contract (R2): when the ``deployment:`` key is absent
from config entirely, ``resolve_deployment_policy`` returns ``(None, [])``
and every caller must treat that as "use today's ``git.merge_on_pass``
path, unchanged" -- never as an unresolvable/malformed case.

Fail-closed contract (R5): once the ``deployment:`` key is present, any
parse ambiguity -- an unknown key, a malformed environment, an unresolvable
``deploy_environment`` -- resolves to ``"authorize"`` (the most
restrictive tier), never silently to ``"auto_merge"``, and is always
accompanied by at least one named finding string.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import spec_artifacts

ON_COMPLETION_VALUES = frozenset({"auto_merge", "authorize"})
_KNOWN_BLOCK_KEYS = frozenset({"environments", "default_environment"})
_KNOWN_ENV_KEYS = frozenset({"on_completion"})

# SPEC-294 R4: the decision-artifact subtype this module writes/reads under
# the SPEC-291 "decision" artifact type. Distinguishes an authorization
# record from any other decision artifact sharing that spec's index.
AUTHORIZATION_DECISION_KIND = "deployment_authorization"

# R4: "The broker refuses an authorization whose actor field identifies an
# agent." No project-wide human/agent identity registry exists yet, so this
# is a conservative, documented heuristic over the actor string itself --
# not a claim of verified human identity. Any actor string containing one
# of these (case-insensitive) substrings is treated as an agent identifier
# and refused; a bare empty/blank actor is refused for the same reason
# ``spec_artifacts.write_artifact`` already refuses it (fail closed).
_AGENT_ACTOR_MARKERS = (
    "coordinator", "agent", "claude", "worker", "executor", "bot",
    "nightshift", "session_", "assistant", "ai ",
)


def is_agent_actor(actor: str) -> bool:
    """Return whether ``actor`` looks like an agent/automation identity."""
    normalized = str(actor or "").strip().lower()
    if not normalized:
        return True
    return any(marker in normalized for marker in _AGENT_ACTOR_MARKERS)


@dataclass(frozen=True)
class AuthorizationStatus:
    """Result of checking whether a candidate SHA is authorized to merge."""

    required: bool
    authorized: bool
    reason: str
    on_completion: str | None = None


def resolve_deployment_policy(
    cfg: Mapping[str, Any], deploy_environment: str | None
) -> tuple[str | None, list[str]]:
    """Resolve one candidate's merge policy from a project config.

    Returns ``(on_completion, findings)``:

    - ``(None, [])`` -- no ``deployment:`` block at all; R2 zero-behavior-
      change applies and the caller must fall back to
      ``git.merge_on_pass``.
    - ``("auto_merge" | "authorize", findings)`` -- a resolvable block;
      ``findings`` is empty on a fully valid, resolvable block.
    - ``("authorize", findings)`` with a non-empty ``findings`` -- fail-
      closed (R5): the block or the requested environment could not be
      resolved cleanly, so the most restrictive tier is returned along
      with a named diagnostic for each problem found.
    """
    if not isinstance(cfg, Mapping) or "deployment" not in cfg:
        return None, []

    block = cfg.get("deployment")
    findings: list[str] = []

    if not isinstance(block, Mapping):
        return "authorize", ["deployment: block must be a mapping"]

    for key in block:
        if key not in _KNOWN_BLOCK_KEYS:
            findings.append(f"deployment: unknown key {key!r}")

    environments = block.get("environments")
    default_environment = block.get("default_environment")

    if not isinstance(environments, Mapping) or not environments:
        findings.append("deployment.environments must be a non-empty mapping")
        return "authorize", findings

    resolved_envs: dict[str, str] = {}
    for name, env_spec in environments.items():
        if not isinstance(env_spec, Mapping):
            findings.append(f"deployment.environments.{name!r} must be a mapping")
            continue
        for key in env_spec:
            if key not in _KNOWN_ENV_KEYS:
                findings.append(
                    f"deployment.environments.{name!r} has unknown key {key!r}"
                )
        on_completion = env_spec.get("on_completion")
        if on_completion not in ON_COMPLETION_VALUES:
            findings.append(
                f"deployment.environments.{name!r}.on_completion has unknown "
                f"value {on_completion!r} -- expected one of: "
                f"{', '.join(sorted(ON_COMPLETION_VALUES))}"
            )
            continue
        resolved_envs[name] = on_completion

    if default_environment is not None and default_environment not in environments:
        findings.append(
            f"deployment.default_environment {default_environment!r} is not a "
            "declared environment"
        )

    # Any structural problem already found makes this block unresolvable;
    # do not attempt per-candidate resolution against a broken block.
    if findings:
        return "authorize", findings

    target = deploy_environment or default_environment
    if target is None:
        return "authorize", [
            "deployment: no deploy_environment given and no default_environment set"
        ]
    if target not in resolved_envs:
        return "authorize", [
            f"deploy_environment {target!r} is not a declared environment"
        ]
    return resolved_envs[target], []


def deployment_block_findings(cfg: Mapping[str, Any]) -> list[str]:
    """Return config-level findings for the ``deployment:`` block, if present.

    Used by ``validate_config_file`` (AC1/AC5): resolves with no specific
    ``deploy_environment`` so every declared environment and the block shape
    itself are checked once per project, independent of any one spec.
    """
    _, findings = resolve_deployment_policy(cfg, None)
    return findings


class AuthorizationRefused(RuntimeError):
    """Raised when a proposed authorization record cannot be accepted (R4)."""


def record_authorization(
    reports_root: Path, spec_id: str, *, actor: str, sha: str, environment: str,
) -> dict[str, Any]:
    """Durably record a human authorization of ``sha`` (R4).

    The coordinator is the sole caller/committer (SPEC-QUESTIONS-004 Q2):
    this only wraps ``spec_artifacts.write_artifact`` with the
    ``deployment_authorization`` decision-artifact shape; it never stages or
    commits anything itself. Raises ``AuthorizationRefused`` for an
    agent-identified actor or a malformed SHA, before any artifact is
    written.
    """
    if is_agent_actor(actor):
        raise AuthorizationRefused(
            f"authorization actor {actor!r} identifies an agent, not a human"
        )
    if not isinstance(sha, str) or len(sha) != 40 or any(
        ch not in "0123456789abcdef" for ch in sha.lower()
    ):
        raise AuthorizationRefused(f"authorization sha {sha!r} is not a full commit SHA")
    return spec_artifacts.write_artifact(
        reports_root, spec_id, type="decision", actor=actor,
        summary=f"authorized merge to {environment!r} at {sha[:12]}",
        content={
            "decision_kind": AUTHORIZATION_DECISION_KIND,
            "authorized_sha": sha,
            "environment": environment,
        },
    )


def find_authorization(
    reports_root: Path, spec_id: str, candidate_sha: str,
) -> tuple[bool, str]:
    """Return whether a non-agent-actor authorization covers ``candidate_sha``.

    R4: authorization binds to the exact SHA it names; any newer commit on
    the candidate branch is a different SHA and is never covered by an
    older record, so this alone gives Scenario 5 (a repair commit
    re-engages the hold) for free -- callers just re-check with the fresh
    SHA on every loop iteration.
    """
    entry = find_authorization_entry(reports_root, spec_id, candidate_sha)
    if entry is not None:
        return True, f"authorized by {entry.get('actor', '')} at {entry.get('created', '?')}"
    return False, "no authorization artifact covers this candidate SHA"


def find_authorization_entry(
    reports_root: Path, spec_id: str, candidate_sha: str,
) -> Mapping[str, Any] | None:
    """The index entry of the non-agent authorization covering ``candidate_sha``, if any.

    The lookup ``find_authorization`` has always done, exposed so a read-only
    projection (SPEC-359) can cite the exact record instead of a sentence.
    """
    entries = spec_artifacts.read_index(reports_root, spec_id)
    for entry in reversed(entries):
        if entry.get("type") != "decision":
            continue
        path = Path(reports_root) / spec_id / str(entry.get("path", ""))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("decision_kind") != AUTHORIZATION_DECISION_KIND:
            continue
        # Fail-closed read (the index is a derived/rebuildable file; the
        # artifact payload is the durable source of truth): both must agree
        # on a human actor, not just the index projection.
        index_actor = str(entry.get("actor", ""))
        payload_actor = str(data.get("actor", ""))
        if is_agent_actor(index_actor) or is_agent_actor(payload_actor):
            continue
        if data.get("authorized_sha") == candidate_sha:
            return entry
    return None


def pending_authorization_hold(
    reports_wip_dir: Path, spec_id: str,
) -> tuple[bool, str, str]:
    """Best-effort read of the queue's own evidence for a live board/report view.

    R3: "awaiting_authorization is a derived hold state ... surfaced on the
    board and in the run report." The integration queue already durably
    writes every decision (including a hold) to
    ``reports/_wip/integration-queue-<run_id>.json`` via
    ``write_integration_queue_result`` -- this reads that existing evidence
    rather than adding a second persistence path. It is read-only and
    non-authoritative: the merge gate itself is enforced only by
    ``check_candidate_authorization`` at merge time.

    Returns ``(held, reason, candidate_sha)``. SPEC-294-001-001 R2: the
    third element surfaces the queue's own persisted ``candidate_sha``
    (R1) -- the actual SHA checked against the merge gate, not the
    coordinator's ``HEAD`` -- so a board caller can prefill an
    authorization control without asking the operator to transcribe it
    from elsewhere. Empty string when not held or when older evidence
    predates R1's ``candidate_sha`` field.
    """
    detail = pending_authorization_hold_detail(reports_wip_dir, spec_id)
    return bool(detail["held"]), str(detail["reason"]), str(detail["candidate_sha"])


def pending_authorization_hold_detail(reports_wip_dir: Path, spec_id: str) -> dict[str, Any]:
    """``pending_authorization_hold`` with the queue evidence's own references (SPEC-359 R2).

    The same read, the same decision: which queue file, run, candidate SHA and
    environment the hold names (when the queue recorded them), and -- for a
    held candidate -- the authorization record that now covers it, if one does.
    ``checked`` distinguishes "no hold found" from "could not read the evidence".
    """
    directory = Path(reports_wip_dir)
    none = {"held": False, "reason": "", "candidate_sha": "", "checked": directory.is_dir()}
    if not directory.is_dir():
        return none
    candidates = sorted(
        directory.glob("integration-queue-*.json"),
        key=lambda path: path.stat().st_mtime, reverse=True,
    )
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        decisions = data.get("decisions") if isinstance(data, dict) else None
        if not isinstance(decisions, list):
            continue
        for decision in reversed(decisions):
            if not isinstance(decision, dict) or decision.get("spec_id") != spec_id:
                continue
            if (
                decision.get("outcome") == "held"
                and decision.get("overlap_kind") == "authorization_required"
            ):
                sha = str(decision.get("candidate_sha") or "")
                detail: dict[str, Any] = {
                    "held": True,
                    "reason": str(decision.get("reason") or "awaiting deployment authorization"),
                    "candidate_sha": sha,
                    "checked": True,
                    "queue_file": f"reports/_wip/{path.name}",
                }
                environment = decision.get("deploy_environment") or decision.get("environment")
                if environment:
                    detail["environment"] = str(environment)
                if isinstance(data.get("run_id"), str):
                    detail["run_id"] = data["run_id"]
                if sha:
                    entry = find_authorization_entry(directory.parent, spec_id, sha)
                    if entry is not None and isinstance(entry.get("path"), str):
                        detail["authorization_record"] = entry["path"]
                return detail
            return none
    return none


def check_candidate_authorization(
    reports_root: Path, spec_id: str, *, cfg: Mapping[str, Any],
    deploy_environment: str | None, candidate_sha: str, head_drift: bool = False,
) -> AuthorizationStatus:
    """The single per-candidate check the integration queue gate calls.

    Combines policy resolution (R1/R2/R5) with the authorization-artifact
    lookup (R4) and the drift-invalidation rule (R3/Q3): a validation that
    ran before ``head_drift`` became true is stale, so a pending
    authorization is never honored against it even if the SHA still
    happens to match (drift means the *validation*, not just the merge
    target, is out of date).
    """
    on_completion, findings = resolve_deployment_policy(cfg, deploy_environment)
    if on_completion is None:
        return AuthorizationStatus(False, True, "no deployment: block; unchanged merge_on_pass path", None)
    if on_completion == "auto_merge" and not findings:
        return AuthorizationStatus(False, True, "resolved to auto_merge", on_completion)
    # Either explicitly "authorize", or fail-closed to "authorize" with
    # findings (R5) -- both paths require a durable authorization record.
    if head_drift:
        return AuthorizationStatus(
            True, False,
            "prior fresh-main validation is stale (head drifted); re-validate before honoring authorization",
            on_completion,
        )
    authorized, reason = find_authorization(reports_root, spec_id, candidate_sha)
    if findings:
        reason = "; ".join(findings) + " -- fail-closed to authorize; " + reason
    return AuthorizationStatus(True, authorized, reason, on_completion)
