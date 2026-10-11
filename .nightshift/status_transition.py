"""FastAPI-free status-write gate shared by ``board.py`` and ``board_ctl.py`` (SPEC-417-003).

``board.py`` calls ``gate_status_write`` from its single durable-writer path and
``board_ctl.py transition`` calls the same function with the board down, so a
refusal is the same text and leaves the same transfer-refusal record either way.
Nothing here imports FastAPI; PyYAML is the only third-party module.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

import lifecycle
from spec_frontmatter import (
    allowed_statuses_for_spec,
    promotion_transition_error,
    status_error_for_spec,
    VALID_SPEC_STATUSES,
)

# SPEC-290: the frontmatter field that persists a status-transfer refusal so it
# survives past the toast that first reported it.
TRANSFER_REFUSAL_FIELD = "transfer_refusal"
_TRANSFER_REFUSAL_MAX_LEN = 300


def sanitize_transfer_refusal_text(text: str) -> str:
    """Collapse to one line and cap length so the value is a safe YAML scalar."""
    collapsed = " ".join(str(text).split())
    if len(collapsed) > _TRANSFER_REFUSAL_MAX_LEN:
        collapsed = collapsed[: _TRANSFER_REFUSAL_MAX_LEN - 1].rstrip() + "…"
    return collapsed


def render_scalar_field_line(key: str, value: str) -> str:
    """Render ``key: value`` as one safely-quoted YAML mapping line."""
    dumped = yaml.safe_dump({key: value}, default_flow_style=False, allow_unicode=True)
    return dumped.rstrip("\n")


def upsert_or_remove_field_line(fm_block: str, key: str, rendered_line: str | None) -> str:
    """Upsert or delete a single top-level ``key: ...`` line, else no-op.

    Every other line (order, list style, date quoting) is preserved byte-for-byte.
    """
    lines = fm_block.split("\n")
    prefix = f"{key}:"
    out: list[str] = []
    found = False
    for line in lines:
        if line.startswith(prefix):
            found = True
            if rendered_line is not None:
                out.append(rendered_line)
            continue
        out.append(line)
    if not found and rendered_line is not None:
        if out and out[-1] == "":
            out.insert(len(out) - 1, rendered_line)
        else:
            out.append(rendered_line)
    return "\n".join(out)


def write_scalar_field(path: Path, key: str, value: str | None) -> bool:
    """Upsert (``value`` given) or remove (``None``) one top-level scalar field.

    Returns whether the file changed; leaves every other line byte-for-byte unchanged.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"malformed frontmatter in {path}")
    fm_block, body_block = parts[1], parts[2]
    rendered = None if value is None else render_scalar_field_line(key, value)
    new_fm = upsert_or_remove_field_line(fm_block, key, rendered)
    if new_fm == fm_block:
        return False
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text("---" + new_fm + "---" + body_block, encoding="utf-8")
    os.replace(tmp, path)
    return True


def record_transfer_refusal_on_file(path: Path, reason: str) -> None:
    """Best-effort: an advisory record must never turn a refusal into a crash."""
    text = sanitize_transfer_refusal_text(reason)
    if not text:
        return
    try:
        write_scalar_field(path, TRANSFER_REFUSAL_FIELD, text)
    except (OSError, ValueError):
        pass


def clear_transfer_refusal_on_file(path: Path) -> None:
    try:
        write_scalar_field(path, TRANSFER_REFUSAL_FIELD, None)
    except (OSError, ValueError):
        pass


class CompletionValidationError(ValueError):
    """Blocking release findings with their separate advisory diagnostics."""

    def __init__(self, errors: list[str], warnings: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors
        self.warnings = warnings


def gate_status_write(
    frontmatter: Mapping[str, Any], status: str, *, reason: str | None, specs_dir: Path,
    canonical_dir: Path, record_refusal: Callable[[str], None] | None = None, warnings: list[str] | None = None,
) -> str:
    """Run the board's write gates in the board's order; return the reason text to record.

    Raises ``ValueError`` with the refusal text (after calling ``record_refusal``
    for every refusal except an unknown status, which the board never recorded).
    A missing reason on a non-judgment transition yields the mechanical default.
    Optional ``warnings`` collects advisory release diagnostics for the caller.
    """
    def refuse(message: str) -> None:
        if record_refusal is not None:
            record_refusal(message)
        raise ValueError(message)

    if status not in VALID_SPEC_STATUSES:
        raise ValueError(f"invalid status: {status}")
    if status not in allowed_statuses_for_spec(dict(frontmatter)):
        refuse(status_error_for_spec(dict(frontmatter), status) or f"invalid status: {status}")
    refusal = promotion_transition_error(frontmatter, status, specs_dir=specs_dir)
    if refusal:
        refuse(refusal)
    if status == "done":
        # BUG-337: release-manifest.json is canonical-only release bookkeeping, never
        # distributed to installs; an install with no manifest skips this check.
        import release_handoff
        manifest_path = Path(canonical_dir) / "release-manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                if record_refusal is not None:
                    record_refusal(str(exc))
                raise ValueError(f"release handoff validation unavailable: {exc}") from exc
            from validate_specs import split_findings
            errors, advisory = split_findings(
                release_handoff.validate_spec_handoff(dict(frontmatter), Path(canonical_dir), manifest)
            )
            if warnings is not None:
                warnings.extend(advisory)
            if errors:
                message = "; ".join(errors)
                if record_refusal is not None:
                    record_refusal(message)
                raise CompletionValidationError(errors, advisory)
    if status == "done":
        # BUG-NS-KIT-127 R2: referenced files outside the done commit must already be in git.
        spec_id = str(frontmatter.get("id") or "")
        matches = sorted(Path(specs_dir).glob(f"{spec_id}-*.md")) or sorted(Path(specs_dir).glob(f"{spec_id}.md"))
        if spec_id and matches:
            import spec_artifacts
            try:
                outside = spec_artifacts.untracked_references(matches[0])["outside"]
            except Exception:  # advisory lookup must not turn a done flip into a crash
                outside = []
            if outside:
                refuse(
                    "done refused: referenced files are neither tracked nor staged: "
                    + ", ".join(outside)
                    + " (commit them before the done commit; see spec_artifacts.py untracked-refs)"
                )
    current_status = str(frontmatter.get("status") or "")
    reason_text = reason.strip() if isinstance(reason, str) else ""
    if lifecycle.is_judgment_transition(current_status, status) and not reason_text:
        refuse(f"status transition {current_status} -> {status} requires a non-empty reason")
    return reason_text or f"mechanical board transition to {status}"
