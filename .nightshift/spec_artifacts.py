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
import base64
import errno
import json
import os
import re
import stat
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lifecycle
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


# SPEC-360 R2/R4/R5: index diagnostics and the bounded, index-bound content reader used by the
# board. The reader treats every artifact as untrusted display data: it resolves only an exact
# key present in the owning spec's own index, checks realpath containment on the file it
# actually opens, and decides size and type before any content is returned.
TEXT_PREVIEW_LIMIT_BYTES = 1024 * 1024
RASTER_PREVIEW_LIMIT_BYTES = 10 * 1024 * 1024
_TEXT_PREVIEW_MEDIA = {
    ".json": "application/json", ".jsonl": "application/x-ndjson", ".md": "text/markdown",
    ".txt": "text/plain", ".log": "text/plain", ".py": "text/x-python",
}
_RASTER_PREVIEW_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
_INDEX_STATE_NAMES = {"absent": "missing", "malformed": "invalid", "unavailable": "unavailable"}


class ArtifactReadError(Exception):
    """A rejected artifact read: an HTTP status, a closed error code and a content-free message."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def read_index_state(reports_root: Path, spec_id: str) -> tuple[str, list[dict[str, Any]], str]:
    """Return ``(state, entries, detail)`` distinguishing every index condition.

    ``state`` is ``missing`` (no index file), ``invalid`` (not a well-formed index of this
    spec), ``unavailable`` (an I/O error, not absence), ``empty`` (valid, no entries) or
    ``available``. ``entries`` is ``[]`` unless the index is valid; ``detail`` never carries a
    host path. ``read_index`` keeps its lenient ``[]`` contract for its other callers.
    """
    status, entries, detail = _read_index_strict(reports_root, spec_id)
    if status == "ok":
        return ("available" if entries else "empty"), entries, ""
    return _INDEX_STATE_NAMES[status], [], detail


def _raster_signature_matches(media_type: str, head: bytes) -> bool:
    if media_type == "image/png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return head.startswith(b"\xff\xd8\xff")
    return media_type == "image/webp" and head[:4] == b"RIFF" and head[8:12] == b"WEBP"


_OUTSIDE_MESSAGE = "the artifact resolves outside this spec's artifact directory"
_NOT_FOUND_MESSAGE = "no such artifact is indexed for this spec"
_UNREADABLE_MESSAGE = "the artifact could not be read"


def _open_at(parent: int, name: str, flags: int) -> int:
    """Open one path component below ``parent`` without following a symlink, or raise a typed refusal."""
    try:
        return os.open(name, flags | getattr(os, "O_CLOEXEC", 0), dir_fd=parent)
    except OSError as exc:
        try:
            linked = stat.S_ISLNK(os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode)
        except OSError:
            linked = False
        if linked or exc.errno == errno.ELOOP:
            raise ArtifactReadError(400, "invalid_path", _OUTSIDE_MESSAGE) from None
        if isinstance(exc, (FileNotFoundError, NotADirectoryError)):
            raise ArtifactReadError(404, "artifact_not_found", _NOT_FOUND_MESSAGE) from None
        raise ArtifactReadError(503, "artifact_unavailable", _UNREADABLE_MESSAGE) from None


def _open_regular_file(reports_root: Path, spec_id: str, members: list[str]) -> int:
    """Open ``<reports root>/<spec id>/artifacts/<members>`` and return the descriptor of a regular file.

    The path is walked one component at a time from the reports root, each step ``O_NOFOLLOW``
    relative to the previous directory descriptor, so a symlink at any component below the reports
    root (the spec directory, ``artifacts``, a subdirectory or the file) is refused and can never
    redefine where the spec's artifact directory is. The reports root itself is the trust anchor.
    Anything that is not a regular file (directory, FIFO, device, socket) is refused without being
    opened, and the final open is ``O_NONBLOCK`` so a FIFO swapped in mid-request cannot block.
    Every descriptor opened here is closed on every path; only the returned one is the caller's.
    """
    names = [spec_id, ARTIFACTS_SUBDIR, *members]
    try:
        parent = os.open(reports_root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        raise ArtifactReadError(503, "artifact_unavailable", _UNREADABLE_MESSAGE) from None
    try:
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        for name in names[:-1]:
            child = _open_at(parent, name, directory_flags)
            os.close(parent)
            parent = child
        try:
            info = os.stat(names[-1], dir_fd=parent, follow_symlinks=False)
        except (FileNotFoundError, NotADirectoryError):
            raise ArtifactReadError(404, "artifact_not_found", _NOT_FOUND_MESSAGE) from None
        except OSError:
            raise ArtifactReadError(503, "artifact_unavailable", _UNREADABLE_MESSAGE) from None
        if stat.S_ISLNK(info.st_mode):
            raise ArtifactReadError(400, "invalid_path", _OUTSIDE_MESSAGE)
        if not stat.S_ISREG(info.st_mode):
            raise ArtifactReadError(404, "artifact_not_found", _NOT_FOUND_MESSAGE)
        fd = _open_at(parent, names[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                      | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0))
    finally:
        os.close(parent)
    try:
        regular = stat.S_ISREG(os.fstat(fd).st_mode)  # the entry could have been swapped after the check above
    except OSError:
        os.close(fd)
        raise ArtifactReadError(503, "artifact_unavailable", _UNREADABLE_MESSAGE) from None
    if not regular:
        os.close(fd)
        raise ArtifactReadError(404, "artifact_not_found", _NOT_FOUND_MESSAGE)
    return fd


def read_indexed_artifact(reports_root: Path, spec_id: str, key: Any) -> dict[str, Any]:
    """Read one indexed artifact for the board, or raise ``ArtifactReadError``.

    ``key`` must be an exact index key ``artifacts/<relative-member>`` of *this* spec. The spec's
    ``artifacts`` directory must be the real directory ``<reports root>/<spec id>/artifacts``: a
    symlink anywhere between the reports root and the file is refused, not followed.
    """
    prefix = f"{ARTIFACTS_SUBDIR}/"
    if (not isinstance(key, str) or not key.startswith(prefix) or "\x00" in key or len(key) > 1024
            or not lifecycle.is_safe_relative_posix_path(key)):
        raise ArtifactReadError(400, "invalid_path", "path must be an exact artifact index key such as artifacts/<file>")
    if (not isinstance(spec_id, str) or spec_id in ("", ".", "..") or "/" in spec_id or "\x00" in spec_id
            or os.path.islink(Path(reports_root) / spec_id) or os.path.islink(artifacts_dir(reports_root, spec_id))):
        # Refused before the index is read, so a linked target's index cannot be probed either.
        raise ArtifactReadError(400, "invalid_path", _OUTSIDE_MESSAGE)
    state, entries, _ = read_index_state(reports_root, spec_id)
    if state == "missing":
        raise ArtifactReadError(404, "index_missing", "this spec has no artifact index")
    if state == "invalid":
        raise ArtifactReadError(409, "index_invalid", "this spec's artifact index is not valid")
    if state == "unavailable":
        raise ArtifactReadError(503, "artifact_unavailable", "the artifact index could not be read")
    entry = next((item for item in entries if item.get("path") == key), None)
    if entry is None:
        raise ArtifactReadError(404, "artifact_not_found", _NOT_FOUND_MESSAGE)
    fd = _open_regular_file(reports_root, spec_id, key[len(prefix):].split("/"))
    try:
        handle = os.fdopen(fd, "rb")
    except OSError:
        os.close(fd)  # fdopen does not take ownership of the descriptor when it fails
        raise ArtifactReadError(503, "artifact_unavailable", _UNREADABLE_MESSAGE) from None
    try:
        with handle:
            info = os.fstat(handle.fileno())
            suffix = os.path.splitext(key)[1].lower()
            media_type = _TEXT_PREVIEW_MEDIA.get(suffix)
            raster = False
            if media_type is None:
                media_type = _RASTER_PREVIEW_MEDIA.get(suffix)
                raster = media_type is not None
            if media_type is None:
                raise ArtifactReadError(415, "preview_unsupported", "this artifact type has no safe preview")
            limit = RASTER_PREVIEW_LIMIT_BYTES if raster else TEXT_PREVIEW_LIMIT_BYTES
            if info.st_size > limit:
                raise ArtifactReadError(413, "artifact_too_large", f"artifact exceeds the {limit // (1024 * 1024)} MiB preview limit")
            data = handle.read(limit + 1)
    except ArtifactReadError:
        raise
    except OSError:
        raise ArtifactReadError(503, "artifact_unavailable", _UNREADABLE_MESSAGE) from None
    if len(data) > limit:  # the file grew after the size check
        raise ArtifactReadError(413, "artifact_too_large", f"artifact exceeds the {limit // (1024 * 1024)} MiB preview limit")
    if raster:
        if not _raster_signature_matches(media_type, data[:12]):
            raise ArtifactReadError(415, "preview_unsupported", "the file content does not match its image type")
        content, encoding = base64.b64encode(data).decode("ascii"), "base64"
    else:
        try:
            content, encoding = data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            raise ArtifactReadError(415, "preview_unsupported", "the artifact is not valid UTF-8 text") from None
    return {
        "spec_id": spec_id, "path": key, "type": entry.get("type"), "summary": entry.get("summary"),
        "media_type": media_type, "encoding": encoding, "content": content, "size_bytes": len(data),
    }


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
    if _symlinked_index_component(reports_root, spec_id):
        # SPEC-370 R2: refuse before any directory is created or any byte is written -- a
        # symlinked spec dir, artifacts dir or index file is never a supported write target.
        raise ArtifactError(
            f"refusing to write artifact for {spec_id}: its artifacts location is not a "
            "supported layout (a symlinked path component)"
        )
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
    spec_path: Path | None = None,
    expected_status: str | None = None,
    reconsider_when: str | None = None,
    state_rationale_evidence: Iterable[Mapping[str, Any]] = (),
    provenance: str = "authored",
) -> dict[str, Any]:
    """Write the R3 ``status-transition`` artifact for one durable transition.

    SPEC-357 R2: when ``spec_path`` is given, the artifact additionally
    carries an additive ``state_rationale`` snapshot, and the spec's
    ``## State rationale`` section is upserted with ``record`` pointing at
    this exact artifact -- through :func:`capture_state_rationale`, the one
    shared routine every mutation boundary calls. Omitting ``spec_path``
    (a caller with no addressable file) skips capture entirely.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise ArtifactError("status-transition artifact requires a non-empty reason")
    content = {
        "from": from_status,
        "to": to_status,
        "reason": reason.strip(),
        "evidence": list(evidence),
        "run_id": run_id,
    }
    summary = f"{from_status} -> {to_status}: {reason.strip()[:120]}"
    if spec_path is not None:
        captured = capture_state_rationale(
            reports_root, spec_id, Path(spec_path),
            artifact_type="status-transition", actor=actor, summary=summary,
            artifact_content=content, status=to_status, reason=reason,
            reconsider_when=reconsider_when, evidence=state_rationale_evidence,
            provenance=provenance, created=created, expected_status=expected_status,
        )
        if captured["unchanged"]:
            for item in reversed(read_index(reports_root, spec_id)):
                if item.get("path") == captured["record"]:
                    return item
            raise ArtifactError(
                f"state rationale record {captured['record']!r} does not resolve "
                f"in the artifact index for {spec_id}"
            )
        return captured["artifact"]
    return write_artifact(
        reports_root, spec_id,
        type="status-transition", actor=actor,
        summary=summary, content=content, created=created,
    )


def capture_state_rationale(
    reports_root: Path,
    spec_id: str,
    spec_path: Path,
    *,
    artifact_type: str,
    actor: str,
    summary: str,
    artifact_content: Mapping[str, Any],
    status: str,
    reason: str,
    reconsider_when: str | None = None,
    evidence: Iterable[Mapping[str, Any]] = (),
    provenance: str = "authored",
    created: str | None = None,
    expected_status: str | None = None,
    expected_record: str | None = None,
) -> dict[str, Any]:
    """SPEC-357 R3: the single shared state-rationale capture routine.

    Writes one typed artifact carrying an additive ``state_rationale``
    snapshot, then upserts the spec's ``## State rationale`` section with
    ``record`` set to that artifact's indexed path -- artifact first, since
    the section's ``record`` names it (R2). Returns
    ``{"unchanged": bool, "record": str, "artifact": dict | None}``;
    ``artifact`` is ``None`` only when ``unchanged`` is ``True``.

    Idempotent: repeating an identical already-applied capture (same
    six-field snapshot, section's ``record`` already set) is a no-op that
    returns the existing record rather than writing duplicate history.
    ``expected_status``/``expected_record`` name what the caller believes is
    currently true; a mismatch is refused as a stale/competing revision
    rather than silently overwritten (R3).

    A caller that omits ``reconsider_when`` for a ``draft``/``planned``/
    ``blocked`` status (SPEC-358 owns *enforcing* that it be supplied; this
    spec owns capture only) is not refused outright -- refusing would break
    every pre-existing caller of a boundary this spec did not get to update
    everywhere at once (e.g. the board UI, which does not yet send it). The
    plain artifact is still written with no ``state_rationale`` key and the
    section is left untouched, so a reader honestly sees ``legacy_missing``
    (R5) rather than a knowingly schema-invalid declaration with
    ``reconsider_when: null``. Any *other* validation failure (a malformed
    evidence locator, wrong schema_version, ...) is a genuine caller bug and
    is still refused before any write (see ``mapping_errors`` below).
    """
    from spec_frontmatter import parse_spec_file

    reason = reason.strip() if isinstance(reason, str) else ""
    mapping: dict[str, Any] = {
        "schema_version": lifecycle.STATE_RATIONALE_SCHEMA_VERSION,
        "status": status,
        "reason": reason,
        "reconsider_when": reconsider_when,
        "evidence": [dict(item) for item in evidence],
        "provenance": provenance,
        "record": None,
    }
    mapping_errors = lifecycle.validate_state_rationale_mapping(mapping)
    missing_trigger_only = mapping_errors == [
        "reconsider_when is required (non-empty) when status is draft/planned/blocked"
    ]
    if mapping_errors and not missing_trigger_only:
        raise ArtifactError("state rationale is invalid: " + "; ".join(mapping_errors))

    spec_path = Path(spec_path)
    parsed = parse_spec_file(spec_path)
    current_section = lifecycle.parse_state_rationale(parsed.body)
    current_status = str(parsed.frontmatter.get("status") or "")
    current_record = current_section.get("record") if current_section else None

    if expected_status is not None and current_status != expected_status:
        raise ArtifactError(
            f"state rationale capture refused for {spec_id}: expected status "
            f"{expected_status!r}, found {current_status!r} (stale revision)"
        )
    if expected_record is not None and current_record != expected_record:
        raise ArtifactError(
            f"state rationale capture refused for {spec_id}: expected record "
            f"{expected_record!r}, found {current_record!r} (stale revision)"
        )
    if missing_trigger_only:
        entry = write_artifact(
            reports_root, spec_id, type=artifact_type, actor=actor, summary=summary,
            content=dict(artifact_content), created=created,
        )
        return {"unchanged": False, "record": None, "artifact": entry, "skipped": True}
    if (
        current_section is not None and current_record
        and lifecycle.state_rationale_snapshots_equal(current_section, mapping)
    ):
        return {"unchanged": True, "record": current_record, "artifact": None}

    entry = write_artifact(
        reports_root, spec_id, type=artifact_type, actor=actor, summary=summary,
        content={**dict(artifact_content), "state_rationale": lifecycle.state_rationale_snapshot(mapping)},
        created=created,
    )
    mapping["record"] = entry["path"]
    _write_state_rationale_section(spec_path, parsed, mapping)
    return {"unchanged": False, "record": entry["path"], "artifact": entry}


def _write_state_rationale_section(spec_path: Path, parsed: Any, mapping: Mapping[str, Any]) -> None:
    """Rewrite ``spec_path`` with ``mapping`` upserted into its body section.

    Reuses ``spec_frontmatter``'s low-level serialiser/atomic-write helpers
    read-only rather than adding a second public frontmatter writer -- this
    module owns no frontmatter field, only the body section.
    """
    from spec_frontmatter import _atomic_write, _serialise_frontmatter

    new_body = lifecycle.upsert_state_rationale_section(parsed.body, mapping)
    fm_text = _serialise_frontmatter(parsed.frontmatter)
    new_content = (
        f"---\n{fm_text}---\n{new_body}" if parsed.end_delim_trailing_newline
        else f"---\n{fm_text}---{new_body}"
    )
    _atomic_write(spec_path, new_content)


def record_authoring_decision(
    spec_path: Path,
    *,
    status: str,
    reason: str,
    actor: str,
    reconsider_when: str | None = None,
    evidence: Iterable[Mapping[str, Any]] = (),
    provenance: str = "authored",
    findings: Iterable[str] = (),
) -> dict[str, Any]:
    """SPEC-357 R2/R3: the authoring / reason-only-revision capture boundary.

    Initial creation of a draft/planned spec -- or any later change to its
    declaration with no accompanying lifecycle-status transition -- reuses
    the existing ``decision`` artifact type/shape rather than inventing a
    synthetic status transition to explain it.
    """
    from spec_frontmatter import parse_spec_file

    spec_path = Path(spec_path)
    spec_id = str(parse_spec_file(spec_path).frontmatter.get("id") or "")
    if not spec_id:
        raise ArtifactError(f"spec id missing from {spec_path.name}")
    decision = lifecycle.decision_record(
        trigger="state_rationale_authoring", current_state=status, candidates=[status],
        reason=reason, findings=list(findings), resolution=reason, rationale=reason,
        authority=actor,
    )
    return capture_state_rationale(
        reports_root_for_spec_path(spec_path), spec_id, spec_path,
        artifact_type="decision", actor=actor,
        summary=f"state rationale authored: {status} -- {reason.strip()[:100]}",
        artifact_content={"decision": decision},
        status=status, reason=reason, reconsider_when=reconsider_when,
        evidence=evidence, provenance=provenance,
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


# ---------------------------------------------------------------------------
# SPEC-359 R4/R5/R6: read-only resolution of a spec's current rationale record
# and of its persisted-versus-working provenance.
#
# Nothing here writes, stages, commits or promotes. The record is selected by
# the EXACT path the spec's own ``## State rationale`` section names -- never by
# newest timestamp, commit subject or matching title -- and every failure mode
# is a distinct quality rather than a raised error, so one spec's corrupt index
# affects that spec only.
# ---------------------------------------------------------------------------

_RECORD_TYPES = frozenset({"decision", "status-transition"})
_HISTORY_CANDIDATES = 5


def parse_rationale_section(body: str) -> tuple[str, Any]:
    """Parse ``body`` once: ``("absent"|"present"|"malformed", section-or-error-text)``."""
    try:
        section = lifecycle.parse_state_rationale(body)
    except lifecycle.StateRationaleError as exc:
        return "malformed", str(exc)
    return ("absent", None) if section is None else ("present", section)


def rationale_stamp(reports_root: Path, spec_id: str, record: str | None) -> tuple:
    """Stat-only stamp of the files a spec's rationale resolution reads (R6)."""
    stamps = []
    paths = [index_path(reports_root, spec_id)]
    if isinstance(record, str) and record.startswith(f"{ARTIFACTS_SUBDIR}/"):
        paths.append(Path(reports_root) / spec_id / record)
    for path in paths:
        try:
            stat = path.stat()
            stamps.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            stamps.append(None)
    return tuple(stamps)


def _symlinked_index_component(reports_root: Path, spec_id: str) -> bool:
    """SPEC-370 R1/R2: is the spec dir, its ``artifacts`` dir, or the index file itself a symlink?

    Mirrors ``read_indexed_artifact``'s caller-level guard (SPEC-368): the reports root is the
    trust anchor, so a symlink at any component between it and the index file redefines nothing
    and is refused rather than followed. Existence is not implied either way -- a component that
    does not exist at all is simply not a symlink.
    """
    spec_dir = Path(reports_root) / spec_id
    directory = artifacts_dir(reports_root, spec_id)
    path = index_path(reports_root, spec_id)
    return os.path.islink(spec_dir) or os.path.islink(directory) or os.path.islink(path)


def _read_index_strict(reports_root: Path, spec_id: str) -> tuple[str, list[dict[str, Any]], str]:
    """Return ``(status, entries, detail)``; status is ok, absent, unavailable or malformed."""
    path = index_path(reports_root, spec_id)
    if _symlinked_index_component(reports_root, spec_id):
        # Refused before the index is read, so a relocated target's entries are never disclosed
        # (matches read_indexed_artifact's reader-level refusal for the same layout).
        return "unavailable", [], "artifacts/index.json is not reachable: a symlinked path component"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "absent", [], "artifacts/index.json does not exist"
    except (OSError, UnicodeDecodeError) as exc:
        return "unavailable", [], f"artifacts/index.json cannot be read: {type(exc).__name__}"
    try:
        data = json.loads(text)
    except ValueError as exc:
        return "malformed", [], f"artifacts/index.json is not valid JSON: {exc}"
    entries = data.get("entries") if isinstance(data, dict) else None
    if (not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries)
            or data.get("spec_id") not in (None, spec_id)):
        return "malformed", [], "artifacts/index.json must be a mapping of this spec with an 'entries' list of mappings"
    return "ok", entries, ""


def _historical_context(frontmatter: Mapping[str, Any], reports_root: Path, spec_id: str) -> dict[str, Any] | None:
    """Candidate history for a spec with no rationale section -- never asserted current (R4)."""
    status, entries, _ = _read_index_strict(reports_root, spec_id)
    candidates = [
        item for item in entries
        if item.get("type") in _RECORD_TYPES and isinstance(item.get("path"), str)
        and lifecycle.is_safe_relative_posix_path(item["path"])
    ][-_HISTORY_CANDIDATES:]
    facts: list[str] = []
    if candidates:
        facts.append(f"{len(candidates)} candidate artifact(s), in index order (none is claimed to be the current decision)")
    gap = frontmatter.get("promotion_gap")
    if isinstance(gap, Mapping) and gap:
        facts.append("promotion_gap: " + "; ".join(
            f"{key}={str(gap[key])[:120]}" for key in ("reason", "upstream", "resolution") if gap.get(key)))
    if frontmatter.get("block_reason") or frontmatter.get("blocker_class"):
        facts.append(
            f"blocker fields: class {frontmatter.get('blocker_class')}, reason "
            f"{str(frontmatter.get('block_reason') or '')[:160]}")
    if not facts:
        return None
    return {
        "reason": "; ".join(facts),
        "evidence": [{"kind": "artifact", "spec": spec_id, "path": item["path"]} for item in candidates],
    }


def resolve_state_rationale(
    frontmatter: Mapping[str, Any],
    parsed: tuple[str, Any],
    reports_root: Path,
) -> dict[str, Any] | None:
    """SPEC-359 R4: resolve the exact current rationale record, without writing.

    Returns ``None`` for an excluded family (main/questions/NFR) with no
    optional declaration, else ``{quality, provenance, reason, reconsider_when,
    record, evidence, diagnostics}``. ``quality`` is one of ``recorded``,
    ``reconstructed``, ``legacy_missing``, ``stale``, ``malformed`` or
    ``unavailable`` -- ``recorded`` means the section and its record agree, not
    that the content is true or committed.
    """
    spec_id = str(frontmatter.get("id") or "")
    kind, data = parsed
    diagnostics: list[dict[str, Any]] = []
    if not spec_id or "/" in spec_id or spec_id in (".", ".."):
        # The id names a directory under reports/; an unsafe one is never joined into a path.
        return {"quality": "unavailable", "provenance": None, "reason": None, "reconsider_when": None,
                "record": None, "evidence": [],
                "diagnostics": [{"code": "rationale_index_unavailable",
                                 "reason": "the spec id is not a safe artifact owner name", "evidence": []}]}

    def out(quality: str, section: Mapping[str, Any] | None = None) -> dict[str, Any]:
        section = section or {}
        evidence = section.get("evidence") if isinstance(section.get("evidence"), list) else []
        return {
            "quality": quality,
            "provenance": section.get("provenance") if section.get("provenance") in lifecycle.STATE_RATIONALE_PROVENANCES else None,
            "reason": section.get("reason") if isinstance(section.get("reason"), str) else None,
            "reconsider_when": section.get("reconsider_when") if isinstance(section.get("reconsider_when"), str) else None,
            "record": section.get("record") if isinstance(section.get("record"), str) else None,
            "evidence": [dict(item) for item in evidence if isinstance(item, Mapping)],
            "diagnostics": diagnostics,
        }

    def note(code: str, reason: str, evidence: list[dict[str, Any]] | None = None) -> None:
        diagnostics.append({"code": code, "reason": reason[:1000], "evidence": evidence or []})

    if kind == "absent":
        if not lifecycle.requires_state_rationale(frontmatter):
            return None
        note("rationale_legacy_missing",
             "no '## State rationale' section exists: the original decision is not recorded, and the "
             "generic status-mapping reason does not establish it")
        history = _historical_context(frontmatter, reports_root, spec_id)
        if history:
            note("rationale_historical_context",
                 "historical context only, not asserted to be the current decision: " + history["reason"],
                 history["evidence"])
        return out("legacy_missing")
    if kind == "malformed":
        note("rationale_malformed", str(data))
        return out("malformed")

    section: Mapping[str, Any] = data
    errors = lifecycle.validate_state_rationale_mapping(section)
    if type(section.get("schema_version")) is not int:
        errors.append("schema_version must be an integer")
    if errors:
        note("rationale_malformed", "; ".join(errors[:5]))
        return out("malformed")
    if lifecycle.evidence_quality_label(frontmatter, section) == "stale":
        note("rationale_stale",
             f"the section records status {section.get('status')!r} but the spec's status is "
             f"{frontmatter.get('status')!r}; the record describes an earlier decision")
        return out("stale", section)
    record = section.get("record")
    if not record:
        note("rationale_record_not_declared",
             "the section names no record artifact, so the decision provenance cannot be inspected")
        return out("unavailable", section)

    locator = [{"kind": "artifact", "spec": spec_id, "path": record}]
    status, entries, detail = _read_index_strict(reports_root, spec_id)
    if status in ("absent", "unavailable"):
        note("rationale_index_unavailable", detail, locator)
        return out("unavailable", section)
    if status == "malformed":
        note("rationale_index_malformed", detail, locator)
        return out("malformed", section)
    matching = [item for item in entries if item.get("path") == record]
    if len(matching) > 1:
        note("rationale_index_malformed", "the selected record has duplicate index entries", locator)
        return out("malformed", section)
    if not matching:
        note("rationale_record_not_indexed",
             f"the section's record {record!r} is not listed in the artifact index; "
             "no other entry is substituted", locator)
        return out("unavailable", section)
    if matching[0].get("type") not in _RECORD_TYPES:
        note("rationale_record_wrong_type",
             f"the indexed type {matching[0].get('type')!r} is not a decision or status-transition", locator)
        return out("malformed", section)
    root = Path(reports_root).resolve() / spec_id / ARTIFACTS_SUBDIR
    artifact = (root / record.split("/", 1)[1]).resolve()
    if root != artifact.parent and root not in artifact.parents:
        note("rationale_record_path_escape", "the record path resolves outside the spec's artifacts directory", locator)
        return out("malformed", section)
    try:
        content = json.loads(artifact.read_text(encoding="utf-8"))
    except FileNotFoundError:
        note("rationale_record_unavailable", "the record file does not exist", locator)
        return out("unavailable", section)
    except (OSError, UnicodeDecodeError) as exc:
        note("rationale_record_unavailable", f"the record file cannot be read: {type(exc).__name__}", locator)
        return out("unavailable", section)
    except ValueError as exc:
        note("rationale_record_malformed", f"the record file is not valid JSON: {exc}", locator)
        return out("malformed", section)
    if (not isinstance(content, dict) or content.get("kind") != "spec_artifact"
            or content.get("spec_id") != spec_id or content.get("type") != matching[0].get("type")):
        note("rationale_record_malformed",
             "the record's identity (kind, owner or type) does not match its index entry", locator)
        return out("malformed", section)
    snapshot = content.get("state_rationale")
    if not isinstance(snapshot, dict):
        note("rationale_snapshot_mismatch", "the record carries no rationale snapshot", locator)
        return out("stale", section)
    if not lifecycle.state_rationale_snapshots_equal(section, snapshot):
        note("rationale_snapshot_mismatch",
             "the record's rationale snapshot differs from the current section", locator)
        return out("stale", section)
    if content.get("type") == "status-transition" and content.get("to") != section.get("status"):
        note("rationale_snapshot_mismatch",
             f"the record's transition target {content.get('to')!r} differs from the section status "
             f"{section.get('status')!r}", locator)
        return out("stale", section)
    return out("reconstructed" if section.get("provenance") == "reconstructed" else "recorded", section)


class PersistenceSnapshot:
    """One batched, read-only Git/index snapshot for a project (SPEC-359 R5/R6).

    Built with at most two Git processes for the whole project regardless of
    how many specs it has: one ``status`` over the project's spec and artifact
    globs, and -- only when some spec differs from HEAD -- one ``cat-file
    --batch`` for those specs' committed frontmatter. Labels are per
    project-relative path and never spawn a process. ``--no-optional-locks``
    keeps the read from touching the index.
    """

    def __init__(self, project_root: Path, *, policy: str = "commit-backed",
                 repo_root: Path | None = None, entries: dict[str, str] | None = None,
                 ignored_dirs: Iterable[str] = (), head_status: dict[str, str | None] | None = None,
                 error: str | None = None, processes: int = 0) -> None:
        self.project_root = Path(project_root)
        self.policy = policy
        self.repo_root = repo_root
        self.entries = entries or {}
        self.ignored_dirs = tuple(ignored_dirs)
        self.head_status = head_status or {}
        self.error = error
        self.processes = processes
        self._prefix = ""
        if repo_root is not None:
            try:
                rel = self.project_root.relative_to(repo_root).as_posix()
                self._prefix = "" if rel == "." else rel + "/"
            except ValueError:
                self.repo_root = None

    @property
    def available(self) -> bool:
        return self.policy == "private-local" or (self.repo_root is not None and self.error is None)

    def _git_path(self, relative: str) -> str:
        return self._prefix + relative

    def label(self, relative: str) -> str:
        """committed, staged, working_tree_only, private_local or unknown for one project-relative path."""
        if self.policy == "private-local":
            return "private_local"
        if self.repo_root is None or self.error is not None:
            return "unknown"
        git_path = self._git_path(relative)
        if not (self.project_root / relative).exists():
            return "unknown"
        code = self.entries.get(git_path)
        if code is None:
            if any(git_path.startswith(prefix) for prefix in self.ignored_dirs):
                return "private_local"
            return "committed"
        if code == "!!":
            return "private_local"
        if code == "??":
            return "working_tree_only"
        index, worktree = code[0], code[1]
        if worktree != " ":
            return "working_tree_only"
        return "staged" if index != " " else "committed"

    def partially_staged(self, relatives: Iterable[str]) -> list[str]:
        """Paths staged AND further modified in the working tree (index holds older bytes)."""
        found = []
        for relative in relatives:
            code = self.entries.get(self._git_path(relative))
            if code and code[0] not in (" ", "?", "!") and code[1] not in (" ", "?", "!"):
                found.append(relative)
        return found

    def committed_status(self, relative: str, working_status: str) -> str | None:
        """HEAD's lifecycle status for a spec file, or None when it is not committed."""
        if self.policy == "private-local" or self.repo_root is None or self.error is not None:
            return None
        git_path = self._git_path(relative)
        code = self.entries.get(git_path)
        if code is None:
            return working_status if self.label(relative) == "committed" else None
        if code in ("??", "!!"):
            return None
        return self.head_status.get(git_path)


def _read_state_policy(project_root: Path) -> str:
    config = Path(project_root) / "config.yaml"
    try:
        import yaml
        merged: dict[str, Any] = {}
        for document in yaml.safe_load_all(config.read_text(encoding="utf-8")):
            if isinstance(document, dict):
                merged.update(document)
    except Exception:  # a missing or broken config never breaks a read
        return "commit-backed"
    section = merged.get("nightshift_state")
    return "private-local" if isinstance(section, dict) and section.get("policy") == "private-local" else "commit-backed"


def _find_git_root(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _frontmatter_status(text: str) -> str | None:
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    for line in parts[1].splitlines():
        if line.startswith("status:"):
            return line.split(":", 1)[1].strip().strip("'\"") or None
    return None


_MAX_HEAD_LOOKUPS = 200


def collect_persistence_snapshot(specs_dir: Path, *, timeout: float = 20.0) -> PersistenceSnapshot:
    """Build the project's persistence snapshot (see :class:`PersistenceSnapshot`)."""
    import subprocess

    specs_dir = Path(specs_dir).resolve()
    project_root = specs_dir.parent if specs_dir.name == "specs" else specs_dir
    if _read_state_policy(project_root) == "private-local":
        return PersistenceSnapshot(project_root, policy="private-local")
    repo_root = _find_git_root(project_root)
    if repo_root is None:
        return PersistenceSnapshot(project_root)
    snapshot = PersistenceSnapshot(project_root, repo_root=repo_root)
    prefix = snapshot._prefix
    specs_rel = specs_dir.relative_to(project_root).as_posix() if specs_dir != project_root else "."
    spec_glob = "*.md" if specs_rel == "." else f"{specs_rel}/*.md"
    pathspecs = [f":(glob){prefix}{spec_glob}", f":(glob){prefix}reports/*/artifacts/*"]
    try:
        completed = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(repo_root), "status", "--porcelain=v1", "-z",
             "--no-renames", "--ignored=matching", "-uall", "--", *pathspecs],
            capture_output=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return PersistenceSnapshot(project_root, repo_root=repo_root, error=f"git status failed: {type(exc).__name__}",
                                   processes=1)
    if completed.returncode != 0:
        return PersistenceSnapshot(project_root, repo_root=repo_root,
                                   error="git status failed: " + _decode(completed.stderr).strip()[:200], processes=1)
    entries: dict[str, str] = {}
    ignored_dirs: list[str] = []
    for item in _decode(completed.stdout).split("\0"):
        if len(item) < 4:
            continue
        code, path = item[:2], item[3:]
        if code == "!!" and path.endswith("/"):
            ignored_dirs.append(path)
        entries[path] = code
    processes = 1
    changed = [
        path for path, code in entries.items()
        if code not in ("??", "!!") and path.startswith(prefix) and path.endswith(".md")
        and "/artifacts/" not in path
    ][:_MAX_HEAD_LOOKUPS]
    head_status: dict[str, str | None] = {}
    if changed:
        processes = 2
        try:
            batch = subprocess.run(
                ["git", "--no-optional-locks", "-C", str(repo_root), "cat-file", "--batch"],
                input="".join(f"HEAD:{path}\n" for path in changed).encode("utf-8"),
                capture_output=True, timeout=timeout, check=False,
            )
            data, position = batch.stdout, 0
            for path in changed:
                newline = data.find(b"\n", position)
                if newline < 0:
                    break
                header = _decode(data[position:newline]).split()
                position = newline + 1
                if len(header) == 3 and header[1] == "blob" and header[2].isdigit():
                    size = int(header[2])
                    head_status[path] = _frontmatter_status(_decode(data[position:position + size]))
                    position += size + 1
                else:
                    head_status[path] = None
        except (OSError, subprocess.SubprocessError, ValueError):
            head_status = {}
    snapshot.entries, snapshot.ignored_dirs = entries, tuple(ignored_dirs)
    snapshot.head_status, snapshot.processes = head_status, processes
    return snapshot


def persistence_stamp(specs_dir: Path) -> tuple:
    """Stat-only stamp of the Git state and policy the snapshot depends on (R6).

    The signature it feeds must never spawn a process, so this reads only the
    index, HEAD, the current branch ref, packed-refs and ``config.yaml``.
    """
    specs_dir = Path(specs_dir)
    project_root = specs_dir.parent if specs_dir.name == "specs" else specs_dir

    def stat(path: Path) -> tuple | None:
        try:
            info = path.stat()
            return (info.st_mtime_ns, info.st_size)
        except OSError:
            return None

    stamps: list[tuple | None] = [stat(project_root / "config.yaml")]
    repo_root = _find_git_root(project_root)
    if repo_root is None:
        return tuple(stamps)
    git_dir = repo_root / ".git"
    common = git_dir
    try:
        if git_dir.is_file():
            pointer = git_dir.read_text(encoding="utf-8").strip()
            if pointer.startswith("gitdir:"):
                git_dir = (repo_root / pointer.split(":", 1)[1].strip()).resolve()
                common_file = git_dir / "commondir"
                common = (git_dir / common_file.read_text(encoding="utf-8").strip()).resolve() \
                    if common_file.is_file() else git_dir
        head_text = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return tuple(stamps)
    stamps += [stat(git_dir / "index"), stat(git_dir / "HEAD"), stat(common / "packed-refs")]
    if head_text.startswith("ref:"):
        stamps.append(stat(common / head_text.split(":", 1)[1].strip()))
    return tuple(stamps)


def project_config_path(specs_dir: Path) -> Path:
    """The project's ``config.yaml`` beside its specs directory (the board reads the same file)."""
    specs_dir = Path(specs_dir)
    return (specs_dir.parent if specs_dir.name == "specs" else specs_dir) / "config.yaml"


def explanation_layout(specs_dir: Path) -> tuple[Path, str]:
    """``(reports_root, specs_prefix)`` for a specs directory: where its artifacts live and the
    project-relative prefix of its spec files. Shared by the board and the CLI."""
    specs_dir = Path(specs_dir)
    reports_root = reports_root_for_spec_path(specs_dir / "placeholder.md")
    try:
        relative = specs_dir.resolve().relative_to(reports_root.parent).as_posix()
    except ValueError:
        relative = "."
    return reports_root, "" if relative == "." else relative + "/"


HEARTBEAT_MAX_BYTES = 8192
_HEARTBEAT_STATES = frozenset({"worker-started", "worker-done", "worker-blocked", "parent-seeded"})
_HEARTBEAT_TIMESTAMP_KEYS = frozenset({"time", "timestamp_utc", "timestamp"})
_HEARTBEAT_REASONS = {
    "heartbeat_absent": "no heartbeat file exists for this spec",
    "heartbeat_unreadable": "the heartbeat file is not a readable regular file",
    "heartbeat_oversized": f"the heartbeat file is larger than {HEARTBEAT_MAX_BYTES} bytes",
    "heartbeat_unparsable": "the heartbeat file does not parse as a heartbeat",
    "heartbeat_no_timestamp": "the heartbeat file declares no timestamp",
}


class _HeartbeatProblem(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _heartbeat_unknown(spec_id: str, code: str) -> dict[str, Any]:
    reason = _HEARTBEAT_REASONS[code]
    return {"result": "unknown", "text": f"unknown ({reason})", "diagnostic": lifecycle._diagnostic(
        code, f"heartbeat liveness is unknown: {reason}",
        [{"kind": "file", "path": f"reports/_wip/orchestrator-progress-{spec_id}.md"}])}


def _read_heartbeat_bytes(reports_root: Path, name: str) -> bytes:
    """One bounded read of ``<reports root>/_wip/<name>``; nothing below the reports root is followed."""
    cloexec = getattr(os, "O_CLOEXEC", 0)
    directory = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | cloexec
    try:
        root = os.open(reports_root, directory)
    except (FileNotFoundError, NotADirectoryError):
        raise _HeartbeatProblem("heartbeat_absent") from None
    except OSError:
        raise _HeartbeatProblem("heartbeat_unreadable") from None
    fd = wip = None
    try:
        try:
            wip = os.open("_wip", directory | getattr(os, "O_NOFOLLOW", 0), dir_fd=root)
            info = os.stat(name, dir_fd=wip, follow_symlinks=False)
        except (FileNotFoundError, NotADirectoryError):
            raise _HeartbeatProblem("heartbeat_absent") from None
        except OSError:
            raise _HeartbeatProblem("heartbeat_unreadable") from None
        if not stat.S_ISREG(info.st_mode):
            raise _HeartbeatProblem("heartbeat_unreadable")
        if info.st_size > HEARTBEAT_MAX_BYTES:
            raise _HeartbeatProblem("heartbeat_oversized")
        try:
            fd = os.open(name, os.O_RDONLY | cloexec | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOCTTY", 0), dir_fd=wip)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise _HeartbeatProblem("heartbeat_unreadable")
            data = b""
            while len(data) <= HEARTBEAT_MAX_BYTES:  # bounded even if the file grows after the stat
                chunk = os.read(fd, HEARTBEAT_MAX_BYTES + 1 - len(data))
                if not chunk:
                    break
                data += chunk
        except OSError:
            raise _HeartbeatProblem("heartbeat_unreadable") from None
        if len(data) > HEARTBEAT_MAX_BYTES:
            raise _HeartbeatProblem("heartbeat_oversized")
        return data
    finally:
        for descriptor in (fd, wip, root):
            if descriptor is not None:
                os.close(descriptor)


def read_heartbeat_evidence(reports_root: Path, spec_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """SPEC-366: what an in-progress spec's own heartbeat file says, as the classifier's result.

    Reads at most one file, ``<reports root>/_wip/orchestrator-progress-<spec id>.md`` (the name
    ``scope_guard`` defines), and hands the declared ``heartbeat_state``, ``phase``,
    ``expected_duration_min`` and an age computed from its declared timestamp to the existing
    ``liveness_classifier.classify_heartbeat``. File mtime, commits and branch movement are never
    inputs. Returns ``{"result", "text", "diagnostic"}``; ``text`` is built only from the
    classifier result, the declared state (a closed set) and the age, so free text (phase, blockers,
    evidence) can never reach an explanation or a static export. Anything unusable is ``unknown``
    with a typed diagnostic.
    """
    spec_id = str(spec_id)
    if not spec_id or spec_id.startswith(".") or "/" in spec_id or "\\" in spec_id or "\x00" in spec_id:
        return _heartbeat_unknown(spec_id, "heartbeat_absent")
    try:
        data = _read_heartbeat_bytes(Path(reports_root), f"orchestrator-progress-{spec_id}.md")
        try:
            lines = data.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            raise _HeartbeatProblem("heartbeat_unparsable") from None
        fields: dict[str, str] = {}
        stamp = None
        for index, line in enumerate(lines):
            key, separator, value = line.partition(":")
            key, value = key.strip(), value.strip().strip("'\"")
            if index == 0 and (not separator or key != "heartbeat_state"):
                raise _HeartbeatProblem("heartbeat_unparsable")
            if separator:
                fields.setdefault(key, value)
                if key in _HEARTBEAT_TIMESTAMP_KEYS and stamp is None:
                    stamp = value
        state = fields.get("heartbeat_state")
        if state not in _HEARTBEAT_STATES:
            raise _HeartbeatProblem("heartbeat_unparsable")
        if stamp is None:
            raise _HeartbeatProblem("heartbeat_no_timestamp")
        declared = lifecycle._parse_declared_time(stamp)
        if declared is None:
            raise _HeartbeatProblem("heartbeat_unparsable")
    except _HeartbeatProblem as problem:
        return _heartbeat_unknown(spec_id, problem.code)
    import liveness_classifier  # the existing heartbeat-only classifier, reused unchanged (SPEC-225)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = max(0.0, (current - declared).total_seconds() / 60)  # a timestamp ahead of the clock is age 0
    entry: dict[str, Any] = {"heartbeat_state": state, "age_min": age}
    if fields.get("phase"):
        entry["phase"] = fields["phase"]
    try:
        expected = float(fields["expected_duration_min"])
        if expected >= 0 and expected != float("inf"):
            entry["expected_duration_min"] = expected
    except (KeyError, ValueError):
        pass
    result = str(liveness_classifier.classify_heartbeat(entry))
    return {"result": result, "diagnostic": None,
            "text": f"{result} ({state}, {int(age)} min since its declared timestamp)"}


_UNRESOLVED = object()


def compose_run_state_explanation(
    item: Mapping[str, Any],
    *,
    file_frontmatter: Mapping[str, Any],
    rationale_parsed: tuple[str, Any],
    mtime: float,
    path: Path,
    durable_state: Mapping[str, Any] | None,
    admission: Any,
    hold: Mapping[str, Any] | None,
    admission_specs: Mapping[str, Mapping[str, Any]] | None,
    dependency_errors: Mapping[str, str] | None,
    parallel_decision: Mapping[str, Any] | None,
    qualified: Mapping[str, Any] | None,
    snapshot: PersistenceSnapshot,
    reports_root: Path,
    specs_prefix: str = "",
    rationale: Any = _UNRESOLVED,
    now: Any = None,
    heartbeat_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """SPEC-359 R1: the ONE per-spec composition the board and the CLI both call.

    ``item`` carries the effective status and is what admission was derived
    from; ``file_frontmatter`` is the file's own frontmatter (the rationale
    section binds to *its* status). Everything else is a result some producer
    already computed for the same snapshot. ``rationale`` may be supplied by a
    caller that memoizes its resolution; otherwise it is resolved here.
    Read-only: no write, staging, status change or Git process (the snapshot
    was collected once by the caller). ``heartbeat_evidence`` (SPEC-366, from
    ``read_heartbeat_evidence``) is quoted for an in-progress spec only.
    """
    import status_store

    spec_id = str(item.get("id") or "")
    file_status = str(file_frontmatter.get("status", "draft"))
    view = status_store.effective_status_view(file_status, dict(durable_state) if durable_state else None,
                                              mtime, path)
    view["effective"] = str(item.get("status", view["effective"]))
    if snapshot.policy == "private-local" and view["source"] == "frontmatter":
        view["source"] = "private_local"
    if rationale is _UNRESOLVED:
        rationale = resolve_state_rationale(file_frontmatter, rationale_parsed, reports_root)
    record = rationale.get("record") if rationale else None
    if record and not lifecycle.is_safe_relative_posix_path(record):
        record = None
    spec_rel = f"{specs_prefix}{Path(path).name}"
    record_rel = f"reports/{spec_id}/{record}" if record else None
    index_rel = f"reports/{spec_id}/{ARTIFACTS_SUBDIR}/{INDEX_FILENAME}" if record else None
    persistence = {
        "spec": snapshot.label(spec_rel),
        "record": snapshot.label(record_rel) if record_rel else "not_applicable",
        "index": snapshot.label(index_rel) if index_rel else "not_applicable",
    }
    view["committed"] = snapshot.committed_status(spec_rel, file_status)
    in_progress = item.get("status") == "in_progress"
    run_evidence: dict[str, Any] = {"checkpoint": dict(durable_state)} if durable_state and in_progress else {}
    if heartbeat_evidence is not None and in_progress:
        run_evidence["heartbeat"] = heartbeat_evidence["text"]
    explanation = lifecycle.run_state_explanation(
        item, admission=admission, specs=admission_specs, dependency_errors=dependency_errors,
        authorization_hold=hold, parallel_decision=parallel_decision, qualified=qualified,
        lifecycle_view=view, rationale=rationale, persistence=persistence,
        persistence_notes={"partially_staged": snapshot.partially_staged(
            [rel for rel in (spec_rel, record_rel, index_rel) if rel])},
        run_evidence=run_evidence or None,
        legacy_run_state=item.get("run_state"), now=now,
    )
    diagnostic = (heartbeat_evidence or {}).get("diagnostic") if in_progress else None
    if diagnostic:
        explanation["diagnostics"] = ([dict(diagnostic)] + explanation["diagnostics"])[: lifecycle._LIST_BOUND * 2]
        if not (durable_state and durable_state.get("status")):
            for context in explanation["gates"]:  # only unknown evidence: the gate must not read as a pass
                if context.get("code") == "execution_context":
                    context["result"] = "unknown"
    return explanation


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
    record.add_argument(
        "--reconsider-when",
        help=(
            "SPEC-357 R1: required (non-empty) when --to is draft/planned/blocked -- "
            "the concrete completion condition, decision, date, or review trigger."
        ),
    )
    record.add_argument(
        "--state-evidence", action="append", default=[], dest="state_evidence",
        metavar="JSON",
        help='One typed evidence locator as JSON, e.g. \'{"kind": "file", "path": "..."}\'.',
    )
    record.add_argument("--provenance", default="authored", choices=("authored", "reconstructed"))

    author = sub.add_parser(
        "author-decision",
        help=(
            "SPEC-357 R3: record the state-rationale decision for a freshly "
            "authored spec (or a reason-only revision), reusing the existing "
            "`decision` artifact type rather than a synthetic transition."
        ),
    )
    author.add_argument("spec_file", type=Path)
    author.add_argument("--status", required=True)
    author.add_argument("--reason", required=True)
    author.add_argument("--actor", default="coordinator")
    author.add_argument("--reconsider-when")
    author.add_argument("--state-evidence", action="append", default=[], dest="state_evidence")
    author.add_argument("--provenance", default="authored", choices=("authored", "reconstructed"))
    author.add_argument("--finding", action="append", default=[])
    return parser


def _parse_state_evidence(raw_entries: list[str]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for raw in raw_entries:
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ArtifactError(f"--state-evidence is not valid JSON: {raw!r}") from exc
        if not isinstance(entry, dict):
            raise ArtifactError(f"--state-evidence must decode to a JSON object: {raw!r}")
        parsed.append(entry)
    return parsed


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)

    from spec_frontmatter import parse_spec_file

    if ns.command == "author-decision":
        spec_path = Path(ns.spec_file).resolve()
        try:
            state_evidence = _parse_state_evidence(ns.state_evidence)
            result = record_authoring_decision(
                spec_path, status=ns.status, reason=ns.reason, actor=ns.actor,
                reconsider_when=ns.reconsider_when, evidence=state_evidence,
                provenance=ns.provenance, findings=ns.finding,
            )
        except ArtifactError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}))
            return 1
        print(json.dumps({"ok": True, **result}, indent=2, default=str))
        return 0

    if ns.command != "record-transition":  # pragma: no cover - argparse enforces choices
        return 1

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
        state_evidence = _parse_state_evidence(ns.state_evidence)
        entry = write_status_transition_artifact(
            reports_root_for_spec_path(spec_path), spec_id,
            from_status=ns.from_status, to_status=ns.to_status,
            actor=ns.actor, reason=reason, evidence=ns.evidence, run_id=ns.run_id,
            spec_path=spec_path, reconsider_when=ns.reconsider_when,
            state_rationale_evidence=state_evidence, provenance=ns.provenance,
        )
    except ArtifactError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps({"ok": True, "entry": entry}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
