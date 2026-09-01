"""SPEC-291: typed, indexed per-spec artifacts under ``reports/<SPEC-ID>/artifacts/``.

A spec's lifecycle decisions are made on evidence that evaporates the moment
the decision is committed. This module gives the single lifecycle owner
(``status_store.transition_commit_backed`` and the promotion entrypoint in
``spec_promotion.py``) a durable place to write *why* a transition happened:
one JSON artifact file per record, indexed by a machine-readable
``artifacts/index.json`` that a later reader can recall from without the
acting session's transcript.

No new concurrent writer is introduced (NFR-001 waiver): every write here
happens synchronously, inline, from the single durable-transition choke
point that was already the sole writer of the status checkpoint and the
frontmatter.
"""
from __future__ import annotations

import argparse
import json
import re
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lifecycle import ARTIFACT_INDEX_FIELDS, ARTIFACT_TYPES, is_judgment_transition

ARTIFACTS_SUBDIR = "artifacts"
INDEX_FILENAME = "index.json"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


class ArtifactError(RuntimeError):
    """Raised when a spec artifact cannot be durably written or read."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def reports_root_for_spec_path(spec_path: Path) -> Path:
    """Return the ``reports/`` directory that is a sibling of ``spec_path``'s specs dir.

    Mirrors ``status_store.default_db_path_for_specs_dir``'s rule: the specs
    directory (``spec_path``'s parent) and ``reports/`` are siblings under the
    same project/nightshift root, whether that root is ``canonical/`` or a
    plain test fixture directory.
    """
    specs_dir = Path(spec_path).resolve().parent
    root = specs_dir.parent if specs_dir.name == "specs" else specs_dir
    return root / "reports"


def artifacts_dir(reports_root: Path, spec_id: str) -> Path:
    return Path(reports_root) / spec_id / ARTIFACTS_SUBDIR


def index_path(reports_root: Path, spec_id: str) -> Path:
    return artifacts_dir(reports_root, spec_id) / INDEX_FILENAME


def read_index(reports_root: Path, spec_id: str) -> list[dict[str, Any]]:
    """Return the artifact index entries for ``spec_id``, or ``[]`` if absent.

    Best-effort: a missing or malformed index is treated as no artifacts
    rather than raised, so read paths (board panel, kickoff brief) never
    break on an unrelated spec's absent history (R7 non-retroactivity).
    """
    path = index_path(reports_root, spec_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    return list(entries) if isinstance(entries, list) else []


def _slugify(text: str) -> str:
    slug = _SLUG_RE.sub("-", text.strip().lower()).strip("-")
    return slug or "artifact"


def write_artifact(
    reports_root: Path,
    spec_id: str,
    *,
    type: str,
    actor: str,
    summary: str,
    content: Mapping[str, Any],
    created: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Write one artifact JSON file and append its entry to the spec's index.

    Returns the index entry that was appended.
    """
    if type not in ARTIFACT_TYPES:
        raise ArtifactError(
            f"artifact type {type!r} is not on the registry: {sorted(ARTIFACT_TYPES)}"
        )
    if not isinstance(actor, str) or not actor.strip():
        raise ArtifactError("artifact actor must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ArtifactError("artifact summary must be a non-empty string")

    created_at = created or _utc_now()
    directory = artifacts_dir(reports_root, spec_id)
    directory.mkdir(parents=True, exist_ok=True)

    stamp = created_at.replace(":", "").replace("-", "")
    stem = filename or f"{stamp}-{_slugify(type)}-{_slugify(summary)[:40]}"
    if not stem.endswith(".json"):
        stem = f"{stem}.json"
    target = directory / stem
    suffix = 2
    while target.exists():
        target = directory / f"{stem[:-5]}-{suffix}.json"
        suffix += 1

    payload = {
        "kind": "spec_artifact",
        "schema_version": 1,
        "spec_id": spec_id,
        "type": type,
        "created": created_at,
        "actor": actor,
        "summary": summary,
        **dict(content),
    }
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    relative_path = f"{ARTIFACTS_SUBDIR}/{target.name}"
    entry = {
        "type": type,
        "created": created_at,
        "actor": actor,
        "summary": summary,
        "path": relative_path,
    }
    _append_index_entry(reports_root, spec_id, entry)
    return entry


def _append_index_entry(reports_root: Path, spec_id: str, entry: Mapping[str, Any]) -> None:
    path = index_path(reports_root, spec_id)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactError(f"artifact index unreadable: {path}") from exc
        entries = data.get("entries") if isinstance(data, dict) else None
        entries = list(entries) if isinstance(entries, list) else []
    else:
        entries = []
    entries.append(dict(entry))
    path.write_text(
        json.dumps({"schema_version": 1, "spec_id": spec_id, "entries": entries}, indent=2) + "\n",
        encoding="utf-8",
    )


def write_status_transition_artifact(
    reports_root: Path,
    spec_id: str,
    *,
    from_status: str,
    to_status: str,
    actor: str,
    reason: str,
    evidence: Iterable[str] = (),
    run_id: str | None = None,
    created: str | None = None,
) -> dict[str, Any]:
    """Write the R3 ``status-transition`` artifact for one durable transition."""
    if not isinstance(reason, str) or not reason.strip():
        raise ArtifactError("status-transition artifact requires a non-empty reason")
    content = {
        "from": from_status,
        "to": to_status,
        "reason": reason.strip(),
        "evidence": list(evidence),
        "run_id": run_id,
    }
    return write_artifact(
        reports_root, spec_id,
        type="status-transition", actor=actor,
        summary=f"{from_status} -> {to_status}: {reason.strip()[:120]}",
        content=content, created=created,
    )


def validate_artifact_index(
    reports_root: Path,
    spec_id: str,
    *,
    allowed_types: Collection[str] = ARTIFACT_TYPES,
    tracked_paths: Collection[str] | None = None,
    canonical_relative_prefix: str = "",
) -> list[str]:
    """Validate one spec's ``artifacts/index.json`` (R6).

    Returns an empty list when the spec has no ``artifacts/`` directory at
    all (R7: absence is never a finding). When the directory exists, checks:
    schema-conformant entries, on-registry types, every listed path exists
    (and is git-tracked when ``tracked_paths`` is supplied), and every file
    physically present under ``artifacts/`` is listed in the index (orphan
    detection).

    ``canonical_relative_prefix`` lets a caller whose ``tracked_paths`` are
    canonical-root-relative (e.g. ``reports/SPEC-1/artifacts/x.json``) supply
    that prefix so path membership can be checked correctly.
    """
    directory = artifacts_dir(reports_root, spec_id)
    if not directory.is_dir():
        return []

    errors: list[str] = []
    path = index_path(reports_root, spec_id)
    if not path.is_file():
        errors.append(f"{spec_id}: artifacts/ exists with no index.json")
        return errors

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{spec_id}: artifacts/index.json is not valid JSON: {exc}"]

    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return [f"{spec_id}: artifacts/index.json must be a mapping with an 'entries' list"]

    listed_names: set[str] = set()
    for position, entry in enumerate(data["entries"]):
        prefix = f"{spec_id}: artifacts/index.json entries[{position}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        missing = [field for field in ARTIFACT_INDEX_FIELDS if not str(entry.get(field, "")).strip()]
        if missing:
            errors.append(f"{prefix} missing required field(s): {', '.join(missing)}")
            continue
        entry_type = entry["type"]
        if entry_type not in allowed_types:
            errors.append(
                f"{prefix} has off-registry type {entry_type!r}; allowed: {sorted(allowed_types)}"
            )
        entry_path = str(entry["path"])
        if not entry_path.startswith(f"{ARTIFACTS_SUBDIR}/") or "/../" in entry_path or entry_path.startswith("/"):
            errors.append(f"{prefix} path must be a safe relative artifacts/<file> path, got {entry_path!r}")
            continue
        listed_names.add(entry_path.split("/", 1)[1])
        artifact_file = directory / entry_path.split("/", 1)[1]
        if not artifact_file.is_file():
            errors.append(f"{prefix} lists missing file: {entry_path}")
        if tracked_paths is not None:
            relative = f"{canonical_relative_prefix}reports/{spec_id}/{entry_path}"
            if relative not in tracked_paths:
                errors.append(f"{prefix} references an untracked artifact file: {entry_path}")

    for artifact_file in sorted(directory.glob("*")):
        if artifact_file.is_dir() or artifact_file.name == INDEX_FILENAME:
            continue
        if artifact_file.name not in listed_names:
            errors.append(
                f"{spec_id}: orphan artifact file not listed in index.json: "
                f"{ARTIFACTS_SUBDIR}/{artifact_file.name}"
            )

    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser(
        "record-transition",
        help=(
            "Write the status-transition artifact for a transition already "
            "applied to a spec's frontmatter by other means (e.g. SKILL.md "
            "Step 2/6's commit-backed Edit + git commit)."
        ),
    )
    record.add_argument("spec_file", type=Path)
    record.add_argument("--from", dest="from_status", required=True)
    record.add_argument("--to", dest="to_status", required=True)
    record.add_argument("--run-id", required=True)
    record.add_argument("--actor", default="coordinator")
    record.add_argument("--reason")
    record.add_argument("--evidence", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.command != "record-transition":  # pragma: no cover - argparse enforces choices
        return 1

    from spec_frontmatter import parse_spec_file

    spec_path = Path(ns.spec_file).resolve()
    spec_id = str(parse_spec_file(spec_path).frontmatter.get("id") or "")
    if not spec_id:
        print(json.dumps({"ok": False, "error": f"spec id missing from {spec_path.name}"}))
        return 1

    reason = (ns.reason or "").strip()
    if is_judgment_transition(ns.from_status, ns.to_status) and not reason:
        print(json.dumps({
            "ok": False,
            "error": (
                f"transition {ns.from_status!r} -> {ns.to_status!r} for {spec_id} is a "
                "judgment transition and requires a non-empty --reason"
            ),
        }))
        return 1
    if not reason:
        reason = f"mechanical transition to {ns.to_status!r} via run {ns.run_id}"

    try:
        entry = write_status_transition_artifact(
            reports_root_for_spec_path(spec_path), spec_id,
            from_status=ns.from_status, to_status=ns.to_status,
            actor=ns.actor, reason=reason, evidence=ns.evidence, run_id=ns.run_id,
        )
    except ArtifactError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True, "entry": entry}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
