#!/usr/bin/env python3
"""SPEC-060: Conflict-check a suggested follow-up spec before autocreation.

Usage:
    check_followup_spec.py --suggestion-title TITLE --specs-dir PATH
                           [--artifact PATH] [--domain DOMAIN] [--layer INT]
                           [--parent-id SPEC-ID] [--similarity-threshold FLOAT]

Exit codes:
    0  No mechanical conflict found. JSON on stdout: {status, proposed_id, notes, nfr_texts}
    1  Conflict detected.           JSON on stdout: {status, conflicts, notes, nfr_texts}

The script never rejects on NFR grounds alone — it returns nfr_texts so the
calling agent can perform semantic judgment.

ID generation priority:
  1. --parent-id SPEC-ID  →  SPEC-ID-NNN  (parent-scoped, collision-safe)
  2. --domain DOMAIN       →  project prefix + NNN  (inferred from existing specs)
  3. neither               →  project prefix + NNN  (inferred from existing specs)

The returned proposed_id is always verified unique against existing spec IDs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Extract YAML frontmatter from a markdown file. Returns {} on failure."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}


def _load_specs(specs_dir: Path) -> list[dict[str, Any]]:
    """Load frontmatter + body for all spec .md files (excluding templates)."""
    specs = []
    for path in sorted(specs_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        fm = _parse_frontmatter(text)
        if fm.get("id"):
            fm["_path"] = str(path)
            fm["_body"] = text
            specs.append(fm)
    return specs


# ---------------------------------------------------------------------------
# Title tokenisation & Jaccard similarity
# ---------------------------------------------------------------------------

_STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this", "are", "its",
    "not", "via", "can", "use", "has", "have", "will", "add", "new",
    "fix", "bug", "spec", "impl", "into", "when", "also", "more",
}


def _tokenise(title: str) -> set[str]:
    """Lower-case words >= 4 chars, minus stop words."""
    words = re.findall(r"[a-zA-Z]+", title.lower())
    return {w for w in words if len(w) >= 4 and w not in _STOP_WORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _extract_title(body: str) -> str:
    """Extract first H1 title from markdown body."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


_BODY_SECTION_KEYWORDS = ("requirement", "acceptance", "criteria")


def _section_tokens(body: str) -> set[str]:
    """Tokenise the Requirements + Acceptance Criteria prose of a spec.

    Two specs can have differing titles but identical requirement/AC bodies — the
    verbatim-duplicate failure mode (SPEC-055 == SPEC-048). Comparing this prose
    catches duplicates that a title-only check misses. Collects every line under
    a `##`/`###` header whose text mentions requirements or acceptance criteria,
    up to the next header of the same-or-higher level.
    """
    lines = body.splitlines()
    collected: list[str] = []
    capturing = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            capturing = any(kw in heading for kw in _BODY_SECTION_KEYWORDS)
            continue
        if capturing:
            collected.append(stripped)
    return _tokenise(" ".join(collected))


# ---------------------------------------------------------------------------
# Proposed ID generation
# ---------------------------------------------------------------------------

# Project-specific domain-to-prefix map (Fartownik defaults).
# Projects may configure this via config.yaml in future; for now the
# inferred-prefix fallback makes this map optional.
_DOMAIN_PREFIX_MAP = {
    "ds": "FART-DS-",
    "ui": "FART-SCR-",
    "net": "FART-NET-",
    "be": "FART-BE-",
    "watch": "FART-WATCH-",
    "arch": "FART-ARCH-",
    "test": "FART-TEST-",
    "infra": "FART-INFRA-",
    "align": "FART-ALIGN-",
    "nav": "FART-NAV-",
    "misc": "FART-MISC-",
}


def _infer_project_prefix(specs: list[dict[str, Any]]) -> str:
    """Infer the dominant spec ID prefix for this project from existing IDs.

    Looks at all non-NFR, non-sub-spec IDs (those without a dash-separated
    numeric suffix after a dash-digit sequence) and returns the most common
    prefix (everything before the trailing -NNN). Falls back to 'SPEC-' when
    no pattern is clear.
    """
    prefix_counts: Counter[str] = Counter()
    for s in specs:
        sid = str(s.get("id", ""))
        if not sid or sid.startswith("NFR-"):
            continue
        # Match: everything before the last -NNN (3+ digit terminal segment)
        m = re.match(r"^(.*?)-(\d{3,})(?:-[a-z].+)?$", sid)
        if m:
            prefix_counts[m.group(1) + "-"] += 1
    if prefix_counts:
        return prefix_counts.most_common(1)[0][0]
    return "SPEC-"


def _proposed_id(
    domain: str | None,
    specs: list[dict[str, Any]],
    parent_id: str | None = None,
) -> str:
    """Generate a proposed spec ID that is guaranteed unique among existing IDs.

    Priority:
      1. parent_id provided → PARENT-NNN (parent-scoped, collision-safe across
         follow-up streams from different parents)
      2. domain in _DOMAIN_PREFIX_MAP → domain-prefix + NNN
      3. fallback → infer project prefix from existing IDs + NNN

    In all cases the returned ID is verified against the in-memory ID set; if
    the candidate already exists the counter is incremented until unique.
    """
    existing_ids = {str(s.get("id", "")) for s in specs}

    if parent_id:
        # Parent-scoped: find existing PARENT-NNN children (exactly 3 digits)
        prefix = f"{parent_id}-"
        child_nums: list[int] = []
        for sid in existing_ids:
            if sid.startswith(prefix):
                suffix = sid[len(prefix):]
                m = re.match(r"^(\d{3})(?:-|$)", suffix)
                if m:
                    child_nums.append(int(m.group(1)))
        next_n = (max(child_nums) + 1) if child_nums else 1
    else:
        # Domain-prefix or inferred-prefix
        mapped = _DOMAIN_PREFIX_MAP.get((domain or "").lower())
        if mapped:
            prefix = mapped
        else:
            prefix = _infer_project_prefix(specs)
        domain_nums: list[int] = []
        for s in specs:
            sid = str(s.get("id", ""))
            if sid.startswith(prefix):
                suffix = sid[len(prefix):]
                m = re.match(r"(\d+)", suffix)
                if m:
                    domain_nums.append(int(m.group(1)))
        next_n = (max(domain_nums) + 1) if domain_nums else 1

    # Build candidate and ensure uniqueness
    candidate = f"{prefix}{next_n:03d}"
    while candidate in existing_ids:
        next_n += 1
        candidate = f"{prefix}{next_n:03d}"

    return candidate


# ---------------------------------------------------------------------------
# NFR extraction
# ---------------------------------------------------------------------------

def _relevant_nfr_texts(specs: list[dict[str, Any]]) -> list[str]:
    """Return full body text of all active NFRs.

    All active NFR bodies are returned unconditionally so the calling agent can
    perform semantic judgment across the full active constraint set. Retired NFRs
    are excluded — they no longer apply.
    """
    results: list[str] = []
    for s in specs:
        sid = str(s.get("id", ""))
        is_nfr = sid.startswith("NFR-") or str(s.get("type", "")).lower() == "nfr"
        if not is_nfr:
            continue
        if str(s.get("status", "")).lower() == "retired":
            continue
        results.append(s["_body"])
    return results


# ---------------------------------------------------------------------------
# Main conflict check
# ---------------------------------------------------------------------------

def check(
    suggestion_title: str,
    specs_dir: Path,
    artifact: str | None,
    domain: str | None,
    layer: int | None,
    threshold: float,
    parent_id: str | None = None,
    suggestion_body: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Run all checks. Returns (exit_code, result_dict)."""
    specs = _load_specs(specs_dir)
    suggestion_tokens = _tokenise(suggestion_title)
    conflicts: list[dict[str, str]] = []
    notes: list[str] = []

    # (a) Title similarity against existing spec titles
    for s in specs:
        existing_title = _extract_title(s.get("_body", ""))
        combined = str(s.get("id", "")) + " " + existing_title
        sim = _jaccard(suggestion_tokens, _tokenise(combined))
        if sim >= threshold:
            conflicts.append({
                "type": "title_similarity",
                "spec_id": str(s.get("id", "")),
                "spec_status": str(s.get("status", "")),
                "detail": (
                    f"'{s.get('id')}' ({s.get('status', '')}) has Jaccard similarity "
                    f"{sim:.2f} >= threshold {threshold} — title: '{existing_title}'"
                ),
            })

    # (e) Requirement/AC body similarity — closes the inline-gate gap (audit R6).
    # The whole-corpus scan_all() compared bodies, but the per-suggestion gate only
    # compared titles, so a verbatim-duplicate suggestion that shared few title tokens
    # (the SPEC-055 == SPEC-048 leak) slipped through at creation. When the caller passes
    # the proposed requirement/AC prose via --suggestion-body, compare it against each
    # existing spec's Requirements+AC sections. Header-agnostic on the suggestion side
    # (tokenise the whole provided prose) since the spec body does not exist yet.
    if suggestion_body:
        suggestion_section_tokens = _tokenise(suggestion_body)
        for s in specs:
            body_sim = _jaccard(suggestion_section_tokens, _section_tokens(s.get("_body", "")))
            if body_sim >= threshold:
                conflicts.append({
                    "type": "body_similarity",
                    "spec_id": str(s.get("id", "")),
                    "spec_status": str(s.get("status", "")),
                    "detail": (
                        f"'{s.get('id')}' ({s.get('status', '')}) has requirement/AC body "
                        f"Jaccard similarity {body_sim:.2f} >= threshold {threshold} — "
                        "the proposed requirements duplicate an existing spec"
                    ),
                })

    # (b) output_artifact exact match — only for ready/in_progress specs
    if artifact:
        for s in specs:
            existing_artifact = str(s.get("output_artifact", ""))
            if not existing_artifact or existing_artifact != artifact:
                continue
            status = str(s.get("status", ""))
            if status in ("ready", "in_progress"):
                conflicts.append({
                    "type": "output_artifact_clash",
                    "spec_id": str(s.get("id", "")),
                    "spec_status": status,
                    "detail": (
                        f"'{s.get('id')}' (status: {status}) already targets "
                        f"output_artifact '{artifact}'"
                    ),
                })

    # (c) Domain+layer cluster — informational, not a conflict
    if domain is not None and layer is not None:
        cluster_ids = [
            str(s.get("id", ""))
            for s in specs
            if str(s.get("domain", "")).lower() == domain.lower()
            and s.get("layer") == layer
        ]
        if cluster_ids:
            notes.append(
                f"Domain '{domain}' layer {layer} already has "
                f"{len(cluster_ids)} spec(s): {', '.join(cluster_ids[:10])}"
                + (" (truncated)" if len(cluster_ids) > 10 else "")
            )

    # (d) NFR extraction — all active NFRs returned for agent semantic judgment, never a conflict signal
    nfr_texts = _relevant_nfr_texts(specs)
    if nfr_texts:
        notes.append(
            f"{len(nfr_texts)} NFR file(s) surfaced for semantic review — "
            "check nfr_texts before creating the spec"
        )

    if conflicts:
        return 1, {
            "status": "conflict",
            "conflicts": conflicts,
            "nfr_texts": nfr_texts,
            "notes": notes,
        }

    proposed_id = _proposed_id(domain, specs, parent_id=parent_id)
    return 0, {
        "status": "clean",
        "proposed_id": proposed_id,
        "nfr_texts": nfr_texts,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Whole-corpus duplicate scan (SPEC-069 — close the duplicate-spec leak)
# ---------------------------------------------------------------------------

def scan_all(specs_dir: Path, threshold: float) -> tuple[int, dict[str, Any]]:
    """Compare every spec pair for near-duplication, by title AND requirement/AC body.

    The per-suggestion `check()` only runs when a follow-up is generated through the
    kickoff flow. Duplicates that enter another way (hand-authored drafts, bulk
    promotion, batch generation before either spec hits disk) never pass through it —
    which is exactly how SPEC-055 shipped as a verbatim duplicate of SPEC-048. This
    scan is invoked over the whole corpus (e.g. by `/nightshift status` / `validate`)
    so duplicates are caught regardless of how they were created.

    Returns (exit_code, result). Exit 1 if any duplicate pair is found.
    """
    specs = _load_specs(specs_dir)
    duplicates: list[dict[str, Any]] = []
    for i in range(len(specs)):
        for j in range(i + 1, len(specs)):
            a, b = specs[i], specs[j]
            # Sub-specs of the same parent are expected to be related; only flag
            # them when the body itself is near-identical, not merely similar.
            title_sim = _jaccard(
                _tokenise(_extract_title(a["_body"])),
                _tokenise(_extract_title(b["_body"])),
            )
            body_sim = _jaccard(_section_tokens(a["_body"]), _section_tokens(b["_body"]))
            if title_sim >= threshold or body_sim >= threshold:
                duplicates.append({
                    "spec_a": str(a.get("id", "")),
                    "status_a": str(a.get("status", "")),
                    "spec_b": str(b.get("id", "")),
                    "status_b": str(b.get("status", "")),
                    "title_similarity": round(title_sim, 2),
                    "body_similarity": round(body_sim, 2),
                    "detail": (
                        f"{a.get('id')} ({a.get('status', '')}) and "
                        f"{b.get('id')} ({b.get('status', '')}) overlap "
                        f"(title {title_sim:.2f}, body {body_sim:.2f} >= {threshold})"
                    ),
                })
    if duplicates:
        return 1, {"status": "duplicates_found", "duplicates": duplicates, "scanned": len(specs)}
    return 0, {"status": "clean", "duplicates": [], "scanned": len(specs)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Check a suggested follow-up spec for conflicts before autocreation. "
            "Exit 0: no mechanical conflict. Exit 1: conflict detected. "
            "JSON result on stdout in both cases."
        )
    )
    parser.add_argument(
        "--suggestion-title", default=None,
        help="Human-readable title of the suggested follow-up spec (required unless --scan-all)",
    )
    parser.add_argument(
        "--scan-all", action="store_true",
        help=(
            "Scan the whole specs dir for near-duplicate pairs (title + requirement/AC "
            "body) instead of checking one suggestion. Exit 1 if duplicates are found."
        ),
    )
    parser.add_argument(
        "--specs-dir", required=True, type=Path,
        help="Path to the .nightshift/specs/ directory",
    )
    parser.add_argument(
        "--artifact", default=None,
        help="Expected output_artifact path (relative to project root)",
    )
    parser.add_argument(
        "--domain", default=None,
        help="Spec domain (e.g. ds, ui, net, be, watch, test)",
    )
    parser.add_argument(
        "--layer", default=None, type=int,
        help="Spec layer (0=foundation, 1=infra, 2=feature, 3=polish)",
    )
    parser.add_argument(
        "--similarity-threshold", default=0.4, type=float,
        help="Jaccard similarity threshold for title conflict detection (default: 0.4)",
    )
    parser.add_argument(
        "--parent-id", default=None,
        help=(
            "Parent spec ID for parent-scoped ID generation (e.g. SPEC-004). "
            "When set, proposed_id will be PARENT-NNN instead of domain-prefix-NNN. "
            "Recommended for follow-up specs that belong under an existing parent."
        ),
    )
    parser.add_argument(
        "--suggestion-body", default=None,
        help=(
            "Proposed requirement/AC prose for the follow-up (audit R6). When provided, "
            "the inline gate also flags body-text duplication against existing specs — "
            "catching verbatim duplicates that share few title tokens (the SPEC-055==048 leak)."
        ),
    )
    args = parser.parse_args()

    specs_dir = args.specs_dir
    if not specs_dir.exists():
        print(json.dumps({
            "status": "error",
            "detail": f"specs-dir not found: {specs_dir}",
        }))
        sys.exit(2)

    if args.scan_all:
        exit_code, result = scan_all(specs_dir, args.similarity_threshold)
        print(json.dumps(result, indent=2))
        sys.exit(exit_code)

    if not args.suggestion_title:
        print(json.dumps({
            "status": "error",
            "detail": "--suggestion-title is required unless --scan-all is set",
        }))
        sys.exit(2)

    exit_code, result = check(
        suggestion_title=args.suggestion_title,
        specs_dir=specs_dir,
        artifact=args.artifact,
        domain=args.domain,
        layer=args.layer,
        threshold=args.similarity_threshold,
        parent_id=args.parent_id,
        suggestion_body=args.suggestion_body,
    )
    print(json.dumps(result, indent=2))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
