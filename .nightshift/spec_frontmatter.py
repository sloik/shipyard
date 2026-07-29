#!/usr/bin/env python3
"""
SPEC-046 — Robust spec frontmatter read-modify-write helper.

This module parses a spec's YAML frontmatter, lets a caller mutate the parsed
data, and writes the result back while keeping the markdown body byte-for-byte
identical. It is the foundation of the retry precondition gate that records
``prior_attempts`` entries onto a spec before the loop jumps back to Step 7.

Design notes
============

* We do NOT round-trip the whole file through ``yaml.dump`` — only the
  frontmatter block between the first two ``---`` lines is re-serialised. The
  body (including trailing whitespace, emoji, and Polish diacritics) is
  preserved exactly as read from disk.
* Atomic writes: the new contents are written to a sibling temp file and
  swapped into place with ``os.replace`` so a crash mid-write cannot leave a
  half-rewritten spec.
* ``yaml.safe_dump`` is used with ``sort_keys=False`` and
  ``allow_unicode=True`` to keep ordering stable and avoid mojibake.
* Overflow of ``prior_attempts`` past the configured cap rotates the oldest
  entries to ``<spec-stem>.attempts-archive.json`` as an append-only list —
  preserving full history without bloating the spec.

Public API
----------

* :func:`parse_spec_file` — read frontmatter + body (returns both plus the raw
  frontmatter text for debugging).
* :func:`write_spec_frontmatter` — read-modify-write helper. Takes a mutator
  callable that receives the parsed dict and returns the updated dict.
* :func:`append_prior_attempt` — high-level helper the retry gate calls to
  record a single attempt entry, rotating to the archive when the cap is
  exceeded.
* :func:`load_attempts_history` — CLI helper that returns the combined list
  of frontmatter + archive attempts in chronological order.
* :func:`tracking_enabled` — returns ``False`` when the spec opts out via
  ``prior_attempts_tracking: false``.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml

try:
    from vocabulary import concept_map
except ImportError:  # portable project-copy fallback
    concept_map = None


DEFAULT_MAX_PRIOR_ATTEMPTS = 10

_FALLBACK_SPEC_STATUSES = frozenset({
    "draft",
    "planned",
    "ready",
    "in_progress",
    "blocked",
    "done",
    "superseded",
    "active",    # type: nfr specs only — constraint is in effect
    "retired",   # type: nfr specs only — constraint no longer applies
})

# The registry is canonical. The fallback keeps older copied kits importable.
try:
    _registry_statuses = (concept_map() if concept_map else {}).get("status", {}).get("values", [])
    VALID_SPEC_STATUSES: frozenset = frozenset(_registry_statuses) or _FALLBACK_SPEC_STATUSES
except Exception:
    VALID_SPEC_STATUSES = _FALLBACK_SPEC_STATUSES

NFR_FAMILY_STATUSES: frozenset = frozenset({
    "active",
    "retired",
})

# Board labels use registry-derived help instead of a second prose definition.
try:
    _status_definition = (concept_map() if concept_map else {}).get("status", {}).get("definition", "")
except Exception:
    _status_definition = ""
STATUS_SEMANTICS: dict[str, str] = {
    status: _status_definition or "Stored lifecycle state; see vocabulary-registry.yaml."
    for status in VALID_SPEC_STATUSES
}


def is_nfr_family(frontmatter: Dict[str, Any] | None) -> bool:
    """Return True for standing NFR constraints and dated NFR run specs.

    NFR-family membership is intentionally broader than ``type: nfr`` because
    dated verification runs may be ``type: task`` while still carrying an
    ``NFR-`` ID.
    """
    if not isinstance(frontmatter, dict):
        return False
    spec_id = frontmatter.get("id")
    spec_type = frontmatter.get("type")
    return (
        isinstance(spec_id, str) and spec_id.startswith("NFR-")
    ) or spec_type == "nfr"


def allowed_statuses_for_spec(frontmatter: Dict[str, Any] | None) -> frozenset:
    """Return valid lifecycle statuses for a specific spec frontmatter."""
    if is_nfr_family(frontmatter):
        return NFR_FAMILY_STATUSES
    return VALID_SPEC_STATUSES


def status_error_for_spec(frontmatter: Dict[str, Any] | None, status: str) -> str | None:
    """Return a status validation error for this spec, or None when valid."""
    if is_nfr_family(frontmatter) and status not in NFR_FAMILY_STATUSES:
        return (
            "NFR-family specs (id starts with NFR- or type is nfr) must use "
            f"status active or retired; got {status}"
        )
    if status not in VALID_SPEC_STATUSES:
        valid_sorted = sorted(VALID_SPEC_STATUSES)
        return f"invalid status {status!r} — valid values: {', '.join(valid_sorted)}"
    return None


def touches_tokens(touches: Any) -> set[str]:
    """Return scope-matchable tokens extracted from a spec's ``touches:`` list."""
    import re

    tokens: set[str] = set()
    if not isinstance(touches, list):
        return tokens
    for item in touches:
        if isinstance(item, str):
            for part in re.split(r"[/._\\-]", item.lower()):
                if len(part) > 2:
                    tokens.add(part)
    return tokens


def nfr_match_reasons(spec: Dict[str, Any], nfr: Dict[str, Any]) -> list[str]:
    """Return the canonical mechanical NFR-match reasons for ``spec``.

    Empty ``scope_tags`` is deliberately conservative and therefore matches every
    candidate.  This is the one matcher shared by the impact report and static
    reconciliation gate.
    """
    raw_tags = nfr.get("scope_tags") or []
    scope_tags = {str(tag).lower().strip() for tag in raw_tags if isinstance(tag, str)}
    if not scope_tags:
        return ["no scope_tags on NFR — conservative, all non-done specs returned"]

    reasons: list[str] = []
    domain = str(spec.get("domain") or "").lower().strip()
    if domain and domain in scope_tags:
        reasons.append(f"domain:{domain}")
    layer = spec.get("layer")
    if layer is not None and f"layer-{layer}" in scope_tags:
        reasons.append(f"layer:{layer}")
    matched = touches_tokens(spec.get("touches")) & scope_tags
    if matched:
        reasons.append(f"touches:{','.join(sorted(matched))}")
    return reasons


def nfr_binding_ids(nfr: Dict[str, Any]) -> set[str]:
    """Return an NFR's own ID plus its explicitly declared top-level parent."""
    ids = {str(nfr.get("id", "")).strip()}
    parent = nfr.get("parent")
    if isinstance(parent, str) and parent.strip():
        ids.add(parent.strip())
    return ids - {""}


def nfr_is_bound_or_waived(spec: Dict[str, Any], nfr: Dict[str, Any]) -> bool:
    """Whether a matching NFR is truthfully bound or explicitly waived."""
    accepted_ids = nfr_binding_ids(nfr)
    bindings = spec.get("nfrs") or []
    if isinstance(bindings, list) and any(str(item).strip() in accepted_ids for item in bindings):
        return True
    waivers = spec.get("nfr_waivers") or []
    return isinstance(waivers, list) and any(
        isinstance(item, dict)
        and str(item.get("id", "")).strip() in accepted_ids
        and isinstance(item.get("reason"), str)
        and bool(item["reason"].strip())
        for item in waivers
    )


# Canonical valid display states for board columns.
# Single source of truth consumed by board.py (_apply_column_override) and
# validate_specs.py (validate_config_file).
VALID_COLUMN_STATES: frozenset = frozenset({"expanded", "collapsed", "hidden"})


def check_column_override(override: object) -> list:
    """Validate a ``board_column_defaults`` override mapping.

    Returns a list of human-readable problem strings.  An empty list means
    the override is valid.  Callers should handle the absent-override case
    (``None``) before calling this function.

    The override must be a dict with optional sub-keys:

    * ``default_state`` — mapping of status-id → display state.  Each id
      must be a canonical spec status; each value must be one of
      ``expanded``, ``collapsed``, or ``hidden``.
    * ``order`` — list of all 9 canonical status ids in the desired column
      order.  Must be a full permutation (no missing, no extra, no dups).

    Extra keys are silently ignored (forward-compatibility).
    """
    problems: list = []

    if not isinstance(override, dict):
        problems.append("board_column_defaults must be a mapping")
        return problems

    # --- Validate default_state ---
    raw_states = override.get("default_state")
    if raw_states is not None:
        if not isinstance(raw_states, dict):
            problems.append("board_column_defaults.default_state must be a mapping")
        else:
            for col_id, state in raw_states.items():
                if col_id not in VALID_SPEC_STATUSES:
                    problems.append(
                        f"board_column_defaults.default_state has unknown status {col_id!r}"
                        f" (valid: {', '.join(sorted(VALID_SPEC_STATUSES))})"
                    )
                elif state not in VALID_COLUMN_STATES:
                    problems.append(
                        f"board_column_defaults.default_state[{col_id!r}] has invalid value"
                        f" {state!r} — must be one of: expanded, collapsed, hidden"
                    )

    # --- Validate order ---
    raw_order = override.get("order")
    if raw_order is not None:
        if not isinstance(raw_order, list):
            problems.append("board_column_defaults.order must be a list")
        elif set(raw_order) != set(VALID_SPEC_STATUSES) or len(raw_order) != len(VALID_SPEC_STATUSES):
            missing = sorted(set(VALID_SPEC_STATUSES) - set(raw_order))
            extra = sorted(set(raw_order) - set(VALID_SPEC_STATUSES))
            problems.append(
                "board_column_defaults.order must be a full permutation of all"
                f" {len(VALID_SPEC_STATUSES)} canonical statuses"
                f" (missing={missing}, extra={extra})"
            )

    return problems


class FrontmatterError(ValueError):
    """Raised when a spec file has malformed or missing YAML frontmatter."""


@dataclass
class ParsedSpec:
    """In-memory view of a spec file, frontmatter split from body."""

    frontmatter: Dict[str, Any]
    body: str                # everything after the closing --- (newline included)
    raw_frontmatter: str     # original frontmatter text (for debugging)
    end_delim_trailing_newline: bool  # whether the closing --- was followed by \n


# ---------------------------------------------------------------------------
# Low-level parse / write
# ---------------------------------------------------------------------------


def _split_frontmatter(content: str) -> Tuple[str, str, bool]:
    """Split raw file contents into (frontmatter_text, body, end_delim_trailing_newline).

    ``body`` begins with a leading newline when the closing ``---`` is followed
    by one in the original file; this is preserved on write so we do not
    introduce or strip trailing newlines.

    Raises :class:`FrontmatterError` if the file is missing a frontmatter
    block — callers that need a permissive mode should catch the exception.
    """
    if not content:
        raise FrontmatterError("spec file is empty")

    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("missing opening frontmatter delimiter ('---')")

    end_idx: Optional[int] = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise FrontmatterError("missing closing frontmatter delimiter ('---')")

    fm_text = "\n".join(lines[1:end_idx])
    # Everything after the closing --- line. We keep the leading newline so
    # body reconstruction is byte-exact when joined back with the delimiter.
    body_lines = lines[end_idx + 1:]
    # str.split preserves a trailing empty element when the source ended in
    # "\n"; joining body_lines with "\n" therefore keeps the original shape.
    body = "\n".join(body_lines)

    # Detect whether the closing --- line had a trailing newline in the
    # original. body_lines has at least one element (possibly empty) if the
    # source had "\n" after ---. If body_lines == [] the source ended with
    # the closing --- and no newline.
    end_delim_trailing_newline = len(body_lines) > 0

    return fm_text, body, end_delim_trailing_newline


def parse_spec_file(spec_file: Path) -> ParsedSpec:
    """Read ``spec_file`` and return its parsed frontmatter + raw body.

    Raises :class:`FrontmatterError` for malformed / missing frontmatter or
    invalid YAML.
    """
    try:
        content = spec_file.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FrontmatterError(f"spec file not found: {spec_file}") from exc

    fm_text, body, end_nl = _split_frontmatter(content)

    try:
        parsed = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"invalid YAML frontmatter: {exc}") from exc

    if not isinstance(parsed, dict):
        raise FrontmatterError("frontmatter must be a YAML mapping")

    return ParsedSpec(
        frontmatter=parsed,
        body=body,
        raw_frontmatter=fm_text,
        end_delim_trailing_newline=end_nl,
    )


def _serialise_frontmatter(data: Dict[str, Any]) -> str:
    """Serialise a frontmatter dict back to YAML text.

    ``sort_keys=False`` preserves insertion order so the output is stable for
    humans reviewing diffs. ``allow_unicode=True`` keeps Polish diacritics and
    emoji readable in the file (safe_dump would otherwise escape them).
    """
    text = yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10_000,  # prevent line-wrap of long strings (e.g., event summaries)
    )
    # yaml.safe_dump terminates with "\n" — keep that; the outer reassembly
    # adds the closing --- on the next line.
    return text


def _atomic_write(target: Path, data: str) -> None:
    """Write ``data`` to ``target`` atomically.

    The temp file lives in the same directory as ``target`` so ``os.replace``
    is guaranteed to be atomic on POSIX and modern Windows.
    """
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(directory),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def write_spec_frontmatter(
    spec_file: Path,
    mutator: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> ParsedSpec:
    """Read ``spec_file``, hand the frontmatter dict to ``mutator``, write back.

    The mutator MUST return the (possibly modified) frontmatter dict. The body
    is preserved byte-for-byte.

    Returns the updated :class:`ParsedSpec` so the caller can observe the
    post-write state without a second read.
    """
    parsed = parse_spec_file(spec_file)
    new_fm = mutator(dict(parsed.frontmatter))
    if not isinstance(new_fm, dict):
        raise FrontmatterError("mutator must return a dict")

    fm_text = _serialise_frontmatter(new_fm)

    fingerprint_metadata = os.environ.get("NIGHTSHIFT_SOURCE_FINGERPRINTS")
    if fingerprint_metadata:
        try:
            from source_fingerprints import verify_fingerprint
            ok, detail = verify_fingerprint(Path(fingerprint_metadata), spec_file)
        except Exception as exc:
            raise FrontmatterError(f"source fingerprint check failed: {exc}") from exc
        if not ok:
            raise FrontmatterError(
                "source fingerprint stale: "
                f"owner={detail.get('owner')} risk={detail.get('risk')} "
                f"evidence={detail.get('evidence')} suggested_fix={detail.get('suggested_fix')}"
            )

    # Reassemble:
    #   ---\n<fm_text>---\n<body>
    # fm_text already ends with \n.
    if parsed.end_delim_trailing_newline:
        new_content = f"---\n{fm_text}---\n{parsed.body}"
    else:
        new_content = f"---\n{fm_text}---{parsed.body}"

    _atomic_write(spec_file, new_content)

    return ParsedSpec(
        frontmatter=new_fm,
        body=parsed.body,
        raw_frontmatter=fm_text,
        end_delim_trailing_newline=parsed.end_delim_trailing_newline,
    )


# ---------------------------------------------------------------------------
# prior_attempts helpers
# ---------------------------------------------------------------------------


def tracking_enabled(frontmatter: Dict[str, Any]) -> bool:
    """Return ``True`` unless the spec has ``prior_attempts_tracking: false``.

    Default is enabled. Only an explicit ``false`` disables the gate.
    """
    flag = frontmatter.get("prior_attempts_tracking", True)
    if isinstance(flag, bool):
        return flag
    # Be forgiving of string values written by hand.
    if isinstance(flag, str):
        return flag.strip().lower() not in {"false", "no", "0", "off"}
    return True


def _archive_path(spec_file: Path) -> Path:
    """Return the sibling archive path for a spec, e.g. ``SPEC-001.attempts-archive.json``."""
    return spec_file.with_name(f"{spec_file.stem}.attempts-archive.json")


def _read_archive(archive: Path) -> List[Dict[str, Any]]:
    if not archive.exists():
        return []
    try:
        data = json.loads(archive.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def _write_archive(archive: Path, entries: List[Dict[str, Any]]) -> None:
    _atomic_write(
        archive,
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
    )


def append_prior_attempt(
    spec_file: Path,
    entry: Dict[str, Any],
    *,
    max_entries: int = DEFAULT_MAX_PRIOR_ATTEMPTS,
) -> Dict[str, Any]:
    """Append ``entry`` to the spec's ``prior_attempts`` list.

    Returns a dict describing what happened::

        {
            "appended": True,
            "frontmatter_count": <int>,
            "archived_count": <int>,  # entries rotated to the archive this call
            "attempt_number": <int>,  # 1-indexed attempt number just recorded
        }

    When the list exceeds ``max_entries``, the oldest entries are rotated to
    ``<spec>.attempts-archive.json`` (newest ``max_entries`` remain in the
    spec). Archive writes happen BEFORE the spec rewrite so a crash can never
    leave attempts in neither file.

    Raises :class:`FrontmatterError` on parse failure — the caller is expected
    to convert that into a ``prior_attempts_write_failed`` event.
    """
    parsed = parse_spec_file(spec_file)

    existing = parsed.frontmatter.get("prior_attempts") or []
    if not isinstance(existing, list):
        # Corrupt field — normalise to list so the loop can still proceed.
        existing = []

    # Attempt number is 1-indexed and counts EVERY attempt ever recorded
    # (including any already rotated to the archive).
    archive = _archive_path(spec_file)
    archived_so_far = len(_read_archive(archive))
    next_attempt_number = archived_so_far + len(existing) + 1

    new_entry = dict(entry)
    new_entry.setdefault("attempt", next_attempt_number)

    combined = list(existing) + [new_entry]

    archived_this_call = 0
    if len(combined) > max_entries:
        overflow = combined[:-max_entries]
        combined = combined[-max_entries:]
        archived_this_call = len(overflow)
        current_archive = _read_archive(archive)
        current_archive.extend(overflow)
        _write_archive(archive, current_archive)

    def _mutate(fm: Dict[str, Any]) -> Dict[str, Any]:
        fm["prior_attempts"] = combined
        return fm

    write_spec_frontmatter(spec_file, _mutate)

    return {
        "appended": True,
        "frontmatter_count": len(combined),
        "archived_count": archived_this_call,
        "attempt_number": new_entry["attempt"],
    }


def load_attempts_history(spec_file: Path) -> List[Dict[str, Any]]:
    """Return the full attempt history for ``spec_file`` in order (oldest first).

    Combines the archive (older entries) with the in-spec ``prior_attempts``
    (newest entries). Missing files yield empty lists — callers get a usable
    response even for specs that never retried.
    """
    archived: List[Dict[str, Any]] = _read_archive(_archive_path(spec_file))
    try:
        parsed = parse_spec_file(spec_file)
    except FrontmatterError:
        return archived

    in_spec = parsed.frontmatter.get("prior_attempts") or []
    if not isinstance(in_spec, list):
        in_spec = []

    return archived + [entry for entry in in_spec if isinstance(entry, dict)]
