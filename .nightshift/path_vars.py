#!/usr/bin/env python3
"""path_vars.py — Portable path variables for Nightshift specs and registry.

Stored Nightshift artifacts (projects-registry.json, spec prose) must not hold
absolute host paths: a path generated in a Cowork Linux VM
(``/sessions/.../mnt/Argo/Cortex/api``) is wrong when read on the owner's Mac
(``/Users/ed/Dropbox/Argo/Cortex/api``). Instead they hold *tokens* that resolve
to real paths at read time, per environment.

Three fixed anchors only (highest priority first):
  - ``{{PROJECT_ROOT}}`` — parent of the spec's nearest-enclosing ``.nightshift``
  - ``{{ARGO_HOME}}``    — Argo Home root (``session.md`` marker)
  - ``{{HOME}}``         — the user's home directory (lowest priority)

Two functions:
  - ``tokenize(abs_path, anchors) -> str`` — replace the longest matching anchor
    prefix with its ``{{NAME}}`` token. Both candidate and anchor values are
    ``os.path.realpath``-normalized before comparison (the single most
    load-bearing rule: ``/Users/ed`` (HOME) is a prefix of
    ``/Users/ed/Dropbox/Argo`` (ARGO_HOME), so naive HOME-first reproduces the
    VM-path bug — longest-anchor-wins fixes it).
  - ``resolve(text, root, *, mode) -> str`` — replace ``{{TOKEN}}`` occurrences
    with real paths. ``mode='execute'`` is fail-CLOSED (raises ``ResolutionError``
    for any unresolvable UPPER token, never empty/partial substitutes);
    ``mode='display'`` is fail-OPEN (leaves the literal token). Tokens inside
    code fences/spans are always left verbatim.

The path-token pass uses regex ``\\{\\{([A-Z][A-Z0-9_]*)\\}\\}`` and runs
separately from ``prompt_engine._render_placeholders`` (which matches ``\\w`` and
raises on unknown). Safety comes from the separate non-overlapping pass + egress
resolution, not from casing.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

# UPPER_SNAKE path/env tokens only (lower_snake prompt vars are prompt_engine's).
TOKEN_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")

# The three supported anchors, highest priority first (used by tokenize ordering
# and to recognise known tokens in resolve / the validator).
ANCHOR_NAMES = ("PROJECT_ROOT", "ARGO_HOME", "HOME")

# Marker file that identifies Argo Home during the walk-up resolution chain.
_ARGO_HOME_MARKER = "session.md"


class ResolutionError(Exception):
    """Raised in execute mode when an UPPER token cannot be resolved.

    Carries ``token`` (the bare anchor name, e.g. ``ARGO_HOME``) so callers can
    report exactly which anchor was missing without string-parsing the message.
    """

    def __init__(self, token: str, detail: str = "") -> None:
        self.token = token
        msg = f"cannot resolve path token {{{{{token}}}}}"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


# ──────────────────────────────────────────────────────────────────────
# Anchor resolution
# ──────────────────────────────────────────────────────────────────────


def _argo_home(root: Path) -> Optional[str]:
    """Resolve ARGO_HOME, worktree-safe. Returns a realpath str or None.

    Chain (R3):
      1. ``$ARGO_HOME`` if set and the directory exists.
      2. Else walk up from ``root`` for a ``session.md`` marker.
      3. Else None (caller fails closed in execute mode).

    NEVER falls back to ``DEFAULT_ROOT`` / ``Path.home()`` — that is the source
    of the VM-home bug this feature kills. The walk-up base is the explicit
    ``root`` argument (never cwd, never ``Path.home()``).
    """
    env = os.environ.get("ARGO_HOME")
    if env:
        p = Path(env)
        if p.is_dir():
            return os.path.realpath(str(p))
    cur = Path(os.path.realpath(str(root)))
    # Walk up including cur itself; stop at filesystem root.
    while True:
        if (cur / _ARGO_HOME_MARKER).is_file():
            return str(cur)
        if cur.parent == cur:
            return None
        cur = cur.parent


def _resolve_anchor(name: str, root: Path) -> Optional[str]:
    """Return the realpath-normalized absolute dir for an anchor, or None."""
    if name == "PROJECT_ROOT":
        return os.path.realpath(str(root))
    if name == "ARGO_HOME":
        return _argo_home(root)
    if name == "HOME":
        return os.path.realpath(str(Path.home()))
    return None  # unknown anchor


# ──────────────────────────────────────────────────────────────────────
# tokenize
# ──────────────────────────────────────────────────────────────────────


def _rel_under(candidate_real: str, anchor_real: str) -> Optional[str]:
    """If candidate is at or under anchor (component-boundary), return the
    POSIX relative path ('' when equal); else None. Both args realpath'd.

    Uses ``os.path.relpath`` + a ``..`` guard rather than ``str.startswith`` so
    ``/Users/ed`` does not falsely match ``/Users/edward/...``.
    """
    if candidate_real == anchor_real:
        return ""
    rel = os.path.relpath(candidate_real, anchor_real)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        return None
    return rel.replace(os.sep, "/")


def tokenize(abs_path: str, anchors: dict[str, str]) -> str:
    """Replace the longest matching anchor prefix in ``abs_path`` with its token.

    ``anchors`` maps anchor NAME -> absolute path value (e.g.
    ``{"ARGO_HOME": "/Users/ed/Dropbox/Argo", "HOME": "/Users/ed"}``). Both the
    candidate and every anchor value are ``realpath``-normalized before
    comparison. The most-specific (longest realpath'd) matching anchor wins, so
    ``/Users/ed/Dropbox/Argo/Cortex`` tokenizes against ARGO_HOME, not HOME, even
    though HOME is a prefix. If no anchor matches, the realpath'd absolute path is
    returned unchanged.
    """
    cand = os.path.realpath(abs_path)
    best_name: Optional[str] = None
    best_anchor_len = -1
    best_rel: Optional[str] = None
    for name, value in anchors.items():
        if not value:
            continue
        anchor_real = os.path.realpath(value)
        rel = _rel_under(cand, anchor_real)
        if rel is None:
            continue
        # Longest realpath'd anchor wins (most specific).
        if len(anchor_real) > best_anchor_len:
            best_anchor_len = len(anchor_real)
            best_name = name
            best_rel = rel
    if best_name is None:
        return cand
    if best_rel:
        return f"{{{{{best_name}}}}}/{best_rel}"
    return f"{{{{{best_name}}}}}"


# ──────────────────────────────────────────────────────────────────────
# Code-fence / inline-span masking (shared by resolve, migration, validator)
# ──────────────────────────────────────────────────────────────────────


def code_spans(text: str) -> list[tuple[int, int]]:
    """Return [start, end) char ranges that are inside a fenced code block
    (``` ... ``` or ~~~ ... ~~~) or an inline code span (`...`).

    Tokens inside these ranges are treated as literal and never resolved /
    migrated / flagged. This is the only literal-token escape (R11).
    """
    spans: list[tuple[int, int]] = []
    lines = text.split("\n")
    pos = 0
    fence: Optional[str] = None  # active fence marker ('```' or '~~~') or None
    fence_start = 0
    for line in lines:
        line_len = len(line)
        stripped = line.lstrip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        if fence is None:
            if is_fence:
                fence = stripped[:3]
                fence_start = pos  # include the opening fence line
        else:
            if is_fence and stripped.startswith(fence):
                spans.append((fence_start, pos + line_len))
                fence = None
        pos += line_len + 1  # +1 for the '\n'
    if fence is not None:
        # Unterminated fence: treat to end of text.
        spans.append((fence_start, len(text)))

    # Inline code spans, but only on lines NOT already inside a fenced block.
    def _in_fence(idx: int) -> bool:
        return any(s <= idx < e for s, e in spans)

    for m in re.finditer(r"`[^`\n]+`", text):
        if not _in_fence(m.start()):
            spans.append((m.start(), m.end()))
    spans.sort()
    return spans


def _in_spans(idx: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= idx < e for s, e in spans)


# ──────────────────────────────────────────────────────────────────────
# resolve
# ──────────────────────────────────────────────────────────────────────


def resolve(text: str, root: Path, *, mode: str) -> str:
    """Resolve ``{{TOKEN}}`` path tokens in ``text`` against ``root``.

    ``root`` is the explicit PROJECT_ROOT (no process-global default). ``mode``:
      - ``'execute'`` — fail-CLOSED. Resolve EVERY UPPER token first; if any is
        unresolvable (unknown anchor or unresolvable ARGO_HOME) raise
        ``ResolutionError`` BEFORE substituting any token. Never returns an
        empty- or partial-substituted string.
      - ``'display'`` — fail-OPEN. Leave any unresolvable token as its literal
        ``{{TOKEN}}``.

    Tokens inside code fences/spans are always left verbatim. Early-out when no
    ``{{`` is present (the cache stores raw token-bearing text and resolves only
    at egress, so most reads have no token).
    """
    if mode not in ("execute", "display"):
        raise ValueError(f"mode must be 'execute' or 'display', got {mode!r}")
    if "{{" not in text:
        return text

    spans = code_spans(text)

    if mode == "execute":
        # First pass: validate every resolvable token (outside code spans).
        for m in TOKEN_RE.finditer(text):
            if _in_spans(m.start(), spans):
                continue
            name = m.group(1)
            resolved = _resolve_anchor(name, root)
            if resolved is None:
                detail = (
                    "unknown anchor (expected one of "
                    f"{', '.join(ANCHOR_NAMES)})"
                    if name not in ANCHOR_NAMES
                    else "$ARGO_HOME unset and no session.md marker found"
                )
                raise ResolutionError(name, detail)

    def _sub(m: re.Match[str]) -> str:
        if _in_spans(m.start(), spans):
            return m.group(0)
        name = m.group(1)
        resolved = _resolve_anchor(name, root)
        if resolved is None:
            # display mode reaches here; execute already validated above.
            return m.group(0)
        return resolved

    return TOKEN_RE.sub(_sub, text)
