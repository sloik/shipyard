#!/usr/bin/env python3
"""migrate_paths.py — One-shot prose migration to portable path tokens (SPEC-071 R10).

Rewrites absolute host paths in human-authored spec PROSE (and frontmatter) to
``{{ANCHOR}}``-relative tokens via the shared ``path_vars`` tokenizer. Prose is
the only valid one-shot target: the registry regenerates every sync (so it is
tokenized at generation time, R5), while prose is never regenerated.

Safety properties (R10):
  - **Dry-run by default**; ``--apply`` is required to write.
  - **Idempotent**: text already inside ``{{...}}`` is skipped, so
    ``migrate(migrate(x)) == migrate(x)``.
  - **Anchored to known absolute roots only** (ARGO_HOME, HOME) — never a generic
    ``/segment`` regex, so ``/api/v1/...`` route docs are untouched.
  - **Skips fenced + inline code** (the literal-token escape).
  - Emits a **triage report** of every absolute path that matched only HOME (or
    no anchor). ``--apply`` REFUSES ``{{HOME}}``-only matches unless
    ``--include-home`` (a VM-home file may not exist at the Mac home).
  - **Aborts when invoked from a linked git worktree** (detected via
    ``git rev-parse --git-dir``) so worktree-local prose isn't rewritten in a way
    that conflicts on merge.
  - Produces a **reversible manifest** (``--manifest PATH``) recording each
    before/after substitution.

Usage:
  python3 migrate_paths.py <dir-or-file> [--apply] [--include-home]
                           [--argo-home PATH] [--manifest PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_CANONICAL_DIR = Path(__file__).resolve().parent
if str(_CANONICAL_DIR) not in sys.path:
    sys.path.insert(0, str(_CANONICAL_DIR))

import path_vars  # noqa: E402


class WorktreeAbort(RuntimeError):
    """Raised when migration is invoked from a linked git worktree."""


# Match an absolute path beginning at one of the known leak/home roots. We
# anchor on the realpath'd ARGO_HOME and HOME prefixes (resolved at runtime), so
# we never touch a generic ``/segment`` like ``/api/v1/...``.
_PATH_CHARS = r"[^\s\"'`)\]<>]"


def _abs_path_re(prefixes: list[str]) -> re.Pattern:
    alts = "|".join(re.escape(p) for p in sorted(prefixes, key=len, reverse=True))
    return re.compile(rf"(?:{alts}){_PATH_CHARS}*")


def is_linked_worktree(path: Path) -> bool:
    """True if ``path`` is inside a linked git worktree (not the main checkout).

    A linked worktree's ``git rev-parse --git-dir`` points at
    ``<main>/.git/worktrees/<name>`` rather than a plain ``.git`` directory.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=str(path if path.is_dir() else path.parent),
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False  # not a git repo / git unavailable — don't block
    return "/worktrees/" in out.replace(os.sep, "/")


def migrate_text(text: str, anchors: dict[str, str]) -> tuple[str, list[dict]]:
    """Return (migrated_text, substitutions).

    Each substitution: {before, after, anchor, home_only, start}. A match whose
    tokenization yields ``{{HOME}}`` (or no anchor) is reported but its
    ``home_only`` flag lets the caller gate whether to apply it.

    Idempotent: paths already inside a ``{{...}}`` token, or inside code
    fences/spans, are left untouched.
    """
    if not anchors:
        return text, []
    spans = path_vars.code_spans(text)
    # Also treat existing token bodies as protected, so we never rewrite a path
    # that is already (partly) tokenized -> idempotency.
    token_spans = [(m.start(), m.end()) for m in path_vars.TOKEN_RE.finditer(text)]
    protected = spans + token_spans

    def _protected(idx: int) -> bool:
        return any(s <= idx < e for s, e in protected)

    # Match paths as written in prose: include BOTH the raw anchor value and its
    # realpath, since prose may use the symlinked form (macOS /tmp vs
    # /private/tmp). tokenize() realpath-normalizes both sides for the actual
    # token decision, so a raw-prefix match still resolves correctly.
    prefixes = []
    for v in anchors.values():
        if not v:
            continue
        prefixes.append(v)
        rp = os.path.realpath(v)
        if rp != v:
            prefixes.append(rp)
    pattern = _abs_path_re(prefixes)
    subs: list[dict] = []

    # Build replacement plan first (non-overlapping, left to right).
    matches = []
    for m in pattern.finditer(text):
        if _protected(m.start()):
            continue
        before = m.group(0)
        end = m.end()
        # Trailing sentence punctuation is prose, not part of the path.
        while before and before[-1] in ".,;:":
            before = before[:-1]
            end -= 1
        if not before:
            continue
        after = path_vars.tokenize(before, anchors)
        if after == before:
            continue  # no anchor matched (e.g. realpath drift) — skip
        home_only = after.startswith("{{HOME}}")
        matches.append((m.start(), end, before, after, home_only))

    if not matches:
        return text, []

    out = []
    last = 0
    for start, end, before, after, home_only in matches:
        out.append(text[last:start])
        out.append(after)
        last = end
        subs.append({
            "before": before, "after": after,
            "anchor": after.split("/", 1)[0].strip("{}"),
            "home_only": home_only, "start": start,
        })
    out.append(text[last:])
    return "".join(out), subs


def _apply_subs(text: str, anchors: dict[str, str], include_home: bool) -> tuple[str, list[dict], list[dict]]:
    """Return (new_text, applied, skipped_home_only).

    When ``include_home`` is False, ``{{HOME}}``-only substitutions are reported
    in ``skipped_home_only`` and NOT applied.
    """
    if include_home:
        new_text, subs = migrate_text(text, anchors)
        return new_text, subs, []

    # Re-run with HOME removed so home-only paths are never rewritten, then
    # separately compute what was skipped (for the triage report).
    anchors_no_home = {k: v for k, v in anchors.items() if k != "HOME"}
    new_text, applied = migrate_text(text, anchors_no_home)
    _, all_subs = migrate_text(text, anchors)
    applied_keys = {(s["before"], s["start"]) for s in applied}
    skipped = [s for s in all_subs if s["home_only"] and (s["before"], s["start"]) not in applied_keys]
    return new_text, applied, skipped


def _resolve_anchors(argo_home: Path | None, home: Path | None = None) -> dict[str, str]:
    home = str(home) if home is not None else str(Path.home())
    if argo_home is not None:
        ah = str(argo_home)
    else:
        env = os.environ.get("ARGO_HOME")
        ah = env if env else None
        if ah is None:
            # Walk up from cwd for a session.md marker.
            cur = Path(os.path.realpath(os.getcwd()))
            while True:
                if (cur / "session.md").is_file():
                    ah = str(cur)
                    break
                if cur.parent == cur:
                    break
                cur = cur.parent
    anchors = {}
    if ah:
        anchors["ARGO_HOME"] = ah
    anchors["HOME"] = home
    return anchors


def _iter_targets(target: Path):
    if target.is_dir():
        for p in sorted(target.glob("*.md")):
            if not p.name.startswith("_"):
                yield p
    elif target.is_file():
        yield target


def run(target: Path, *, apply: bool, include_home: bool,
        argo_home: Path | None, manifest: Path | None,
        home: Path | None = None) -> dict:
    """Execute the migration. Returns a summary dict (also used by tests)."""
    if is_linked_worktree(target):
        raise WorktreeAbort(
            f"refusing to migrate from a linked git worktree: {target}. "
            "Run the prose migration on the main checkout only (R10/R12)."
        )

    anchors = _resolve_anchors(argo_home, home)
    manifest_entries: list[dict] = []
    triage: list[dict] = []
    changed_files = 0
    total_applied = 0

    for path in _iter_targets(target):
        text = path.read_text(encoding="utf-8")
        new_text, applied, skipped = _apply_subs(text, anchors, include_home)
        if skipped:
            for s in skipped:
                triage.append({"file": str(path), **s})
        if not applied or new_text == text:
            continue
        changed_files += 1
        total_applied += len(applied)
        # Per-file before/after diff (printed).
        print(f"\n=== {path} ({len(applied)} substitution(s)) ===")
        for s in applied:
            print(f"  - {s['before']}")
            print(f"  + {s['after']}")
        manifest_entries.append({
            "file": str(path),
            "substitutions": applied,
        })
        if apply:
            path.write_text(new_text, encoding="utf-8")

    if triage:
        print("\n--- TRIAGE: {{HOME}}-only / no-anchor matches "
              f"({'applied' if include_home else 'NOT applied — use --include-home'}) ---")
        for t in triage:
            print(f"  {t['file']}: {t['before']} -> {t['after']}")

    if manifest is not None and manifest_entries:
        manifest.write_text(json.dumps({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "applied": apply,
            "include_home": include_home,
            "files": manifest_entries,
        }, indent=2) + "\n", encoding="utf-8")

    mode = "APPLIED" if apply else "DRY-RUN (no files written; pass --apply)"
    print(f"\n{mode}: {total_applied} substitution(s) across {changed_files} file(s); "
          f"{len(triage)} home-only match(es).")
    return {
        "applied": apply,
        "changed_files": changed_files,
        "total_applied": total_applied,
        "triage": triage,
        "manifest_entries": manifest_entries,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="SPEC-071 one-shot prose path migration")
    ap.add_argument("target", type=Path, help="spec directory or single .md file")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--include-home", action="store_true",
                    help="also apply {{HOME}}-only matches (off by default)")
    ap.add_argument("--argo-home", type=Path, default=None,
                    help="explicit ARGO_HOME anchor (default: $ARGO_HOME or session.md walk-up)")
    ap.add_argument("--manifest", type=Path, default=None,
                    help="write a reversible before/after manifest JSON to this path")
    args = ap.parse_args()
    try:
        run(args.target, apply=args.apply, include_home=args.include_home,
            argo_home=args.argo_home, manifest=args.manifest)
    except WorktreeAbort as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
