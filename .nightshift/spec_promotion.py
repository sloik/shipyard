#!/usr/bin/env python3
"""SPEC-291 R4: the canonical entrypoint for a ``draft``/``planned`` -> ``ready`` promotion.

Promotion edits have historically happened as a manual frontmatter edit (a
``promotion_gap.resolved: true`` set by hand) plus a commit like ``chore:
resolve SPEC-276 promotion gap and promote draft -> ready``. That trail
carries no reason and no record of the validation an agent performed. This
module gives that flow a single canonical entrypoint that:

- reuses ``promotion_gap_error``/``promotion_transition_error`` rather than
  reimplementing the gap-resolution gate (Out of Scope: this spec never
  changes *whether* a promotion is allowed, only *why* it durably records
  one);
- resolves a declared ``promotion_gap`` in its own frontmatter write (status
  unchanged) before the status transition, because
  ``write_spec_frontmatter``'s refusal gate reads the pre-mutation
  frontmatter -- a promotion attempted in the same write as its own gap
  resolution would still see the unresolved gap and refuse;
- delegates the actual ``draft``/``planned`` -> ``ready`` transition to
  ``StatusStore.transition_commit_backed``, which writes the durable
  checkpoint, the ``status-transition`` artifact, and the frontmatter, in
  that order;
- additionally persists the validation knowledge behind the promotion --
  the resolved gap's resolution rationale, and any agent-gathered findings
  or evidence -- as ``decision``/``context``/``validation-evidence``
  artifacts (R4), so a later reader reconstructs what was decided, why, and
  on what evidence from the artifact index alone.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import lifecycle
import spec_artifacts
from spec_frontmatter import (
    parse_spec_file,
    promotion_gap_error,
    promotion_transition_error,
    write_spec_frontmatter,
)
from status_store import StatusStore


class PromotionError(RuntimeError):
    """Raised when a promotion cannot be durably performed."""


def promote_to_ready(
    spec_path: Path,
    *,
    reason: str,
    run_id: str,
    status_store: StatusStore,
    actor: str = "coordinator",
    target_status: str = "ready",
    gap_resolution: Mapping[str, Any] | None = None,
    resolution_rationale: str | None = None,
    findings: Iterable[str] = (),
    evidence: Iterable[str] = (),
) -> dict[str, Any]:
    """Promote one spec from ``draft``/``planned`` to ``ready`` (or ``planned``).

    ``gap_resolution`` merges into the spec's existing ``promotion_gap``
    mapping (e.g. ``{"resolved": True}`` or ``{"waived_reason": "..."}``) when
    a declared gap is currently unresolved. Supplying it without a declared
    gap, or without ``resolution_rationale``, is refused -- gap resolution
    must itself be evidenced.

    Returns ``{"checkpoint": ..., "artifacts": [...]}`` -- the durable status
    checkpoint and every artifact entry this call wrote.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise PromotionError("promotion requires a non-empty reason")

    path = Path(spec_path).resolve()
    parsed = parse_spec_file(path)
    fm = parsed.frontmatter
    spec_id = str(fm.get("id") or "")
    if not spec_id:
        raise PromotionError(f"spec id missing from {path.name}")
    current_status = str(fm.get("status") or "")
    if current_status not in {"draft", "planned"}:
        raise PromotionError(
            f"promotion refused: {spec_id} status is {current_status!r}, "
            "not draft or planned"
        )

    declared_gap = fm.get("promotion_gap")
    gap_kind = declared_gap.get("kind") if isinstance(declared_gap, Mapping) else None
    unresolved = declared_gap is not None and promotion_gap_error(
        fm, specs_dir=path.parent
    ) is not None

    if unresolved:
        if gap_resolution is None:
            raise PromotionError(
                f"promotion refused: {spec_id} has an unresolved promotion_gap "
                f"{gap_kind!r}; supply gap_resolution"
            )
        if not isinstance(resolution_rationale, str) or not resolution_rationale.strip():
            raise PromotionError(
                "resolving a promotion_gap requires a non-empty resolution_rationale"
            )

        def _resolve_gap(current: dict[str, Any]) -> dict[str, Any]:
            gap = dict(current.get("promotion_gap") or {})
            gap.update(gap_resolution)
            return {**current, "promotion_gap": gap}

        parsed = write_spec_frontmatter(path, _resolve_gap)
        fm = parsed.frontmatter

    refusal = promotion_transition_error(fm, target_status, specs_dir=path.parent)
    if refusal:
        raise PromotionError(refusal)

    checkpoint = status_store.transition_commit_backed(
        path, target_status, run_id=run_id, source="promotion",
        reason=reason, actor=actor,
    )

    reports_root = spec_artifacts.reports_root_for_spec_path(path)
    written: list[dict[str, Any]] = []

    if unresolved:
        decision = lifecycle.decision_record(
            trigger=f"promotion_gap:{gap_kind}",
            current_state=current_status,
            candidates=[target_status],
            reason=str(declared_gap.get("reason", "")) if isinstance(declared_gap, Mapping) else "",
            findings=list(findings),
            resolution=str(resolution_rationale),
            rationale=str(resolution_rationale),
            authority=actor,
        )
        written.append(spec_artifacts.write_artifact(
            reports_root, spec_id, type="decision", actor=actor,
            summary=f"resolved promotion_gap {gap_kind}: {str(resolution_rationale)[:100]}",
            content={"decision": decision, "gap_resolution": dict(gap_resolution or {})},
        ))

    findings = list(findings)
    if findings:
        written.append(spec_artifacts.write_artifact(
            reports_root, spec_id, type="context", actor=actor,
            summary=f"{len(findings)} finding(s) gathered for promotion to {target_status}",
            content={"findings": findings},
        ))

    evidence = list(evidence)
    if evidence:
        written.append(spec_artifacts.write_artifact(
            reports_root, spec_id, type="validation-evidence", actor=actor,
            summary=f"validation performed for promotion to {target_status}",
            content={"evidence": evidence},
        ))

    return {"checkpoint": checkpoint, "artifacts": written}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_file", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--actor", default="coordinator")
    parser.add_argument("--target-status", default="ready", choices=("ready", "planned"))
    parser.add_argument("--gap-resolved", action="store_true")
    parser.add_argument("--gap-waived-reason")
    parser.add_argument("--resolution-rationale")
    parser.add_argument("--finding", action="append", default=[])
    parser.add_argument("--evidence", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    gap_resolution: dict[str, Any] | None = None
    if ns.gap_resolved:
        gap_resolution = {"resolved": True}
    elif ns.gap_waived_reason:
        gap_resolution = {"waived_reason": ns.gap_waived_reason}

    store = StatusStore.for_specs_dir(ns.spec_file.resolve().parent)
    try:
        result = promote_to_ready(
            ns.spec_file, reason=ns.reason, run_id=ns.run_id, status_store=store,
            actor=ns.actor, target_status=ns.target_status,
            gap_resolution=gap_resolution, resolution_rationale=ns.resolution_rationale,
            findings=ns.finding, evidence=ns.evidence,
        )
    except PromotionError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"ok": True, **result}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
