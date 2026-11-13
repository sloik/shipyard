"""SPEC-416: the one shared spec-ID grammar, parser, code validator and minter.

New spec IDs have the form ``{KIND}-{CODE}-{NNN}(-{NNN})*`` where ``CODE`` is
``[{FAMILY}-]{PROJECT}``: one or two letter-only segments, each 2-6 uppercase
ASCII letters.  Parsing is unambiguous because code segments are letters-only
and number segments are digits-only: ``CODE`` is every letter segment between
``KIND`` and the first numeric segment (``SPEC-CTX-CORE-052`` is kind ``SPEC``,
code ``CTX-CORE``, number ``052``).

Existing ("legacy") IDs are never renamed.  ``parse_id`` therefore has a
lenient mode that recognises every historical shape (``SPEC-111``,
``SPEC-390-002-001``, ``BUG-018``, ``SPEC-QUESTIONS-001``, ``SPEC-ARGO-121``)
and a strict mode that implements the R1 grammar for new IDs.  Every kit
consumer that parses or matches an ID imports this module rather than keeping
a private regex.
"""

from __future__ import annotations

import re
import json
import os
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

# The R1 grammar, written once for docs and tests to grep.
GRAMMAR = "{KIND}-{CODE}-{NNN}(-{NNN})*"

# The closed id_kind vocabulary (distinct from the frontmatter ``type:``).
ID_KINDS: tuple[str, ...] = ("SPEC", "BUG", "NFR", "QUESTIONS")

# New-ID pairing between id kind and frontmatter ``type:`` (R2, fully strict).
_KIND_TO_TYPE = {"BUG": "bugfix", "NFR": "nfr", "QUESTIONS": "questions"}

_KINDS_ALT = "|".join(ID_KINDS)
_CODE_SEGMENT = r"[A-Z]{2,6}"
_CODE_SEGMENT_RE = re.compile(rf"^{_CODE_SEGMENT}$")

STRICT_ID_RE = re.compile(
    rf"^(?P<kind>{_KINDS_ALT})-(?P<code>{_CODE_SEGMENT}(?:-{_CODE_SEGMENT})?)-(?P<number>\d{{3,}}(?:-\d+)*)$"
)
# The same R1 grammar as a JavaScript regular expression source (board JS reads it).
STRICT_ID_JS_PATTERN = (
    rf"^({_KINDS_ALT})-({_CODE_SEGMENT}(?:-{_CODE_SEGMENT})?)-\d{{3,}}(?:-\d+)*$"
)
# Every historical shape: a letters-only kind, uppercase alphanumeric segments,
# then the first numeric segment and any (alphanumeric) child segments.
LEGACY_ID_RE = re.compile(
    r"^(?P<kind>[A-Z]+)-(?P<code>(?:[A-Z][A-Z0-9]*-)*)(?P<number>\d+(?:-[A-Za-z0-9]+)*)$"
)

# Free-text token (reports, run directories): kinds SPEC/BUG/QUESTIONS/NFR, any
# hyphenated uppercase prefix, then greedy numeric children.  The lookahead
# keeps a following kind word from being swallowed as a prefix segment.
TOKEN_PATTERN = (
    # "SPEC-QUESTIONS-NNN" is the legacy questions shape; it is matched explicitly
    # because QUESTIONS is also a kind word the lookahead below refuses as a prefix.
    r"(?:SPEC-QUESTIONS-\d+(?:-\d+)*"
    rf"|(?:{_KINDS_ALT})-(?:(?!(?:{_KINDS_ALT})-)[A-Z][A-Z0-9]*-)*\d+(?:-\d+)*)"
)
TOKEN_RE = re.compile(TOKEN_PATTERN)

# Commit-subject IDs (``[ID] ...`` and ``chore: mark ID done|blocked``).
COMMIT_ID_PATTERN = rf"(?:{_KINDS_ALT})-(?:[A-Z0-9]+-)*\d+"
# The same ID as a POSIX ERE group, kept verbatim in ``hooks/commit-msg``
# (bash cannot import this module; a test pins the hook text to this value).
COMMIT_ID_ERE = rf"({_KINDS_ALT})-([A-Z0-9]+-)*[0-9]+"

# Filenames: a spec/NFR/questions home file, and a bug spec home file.
_FILENAME_ID = r"(?:[A-Z][A-Z0-9]*-)*\d+"
SPEC_FILENAME_RE = re.compile(r"^(?:SPEC-.+|NFR-.+|QUESTIONS-.+|.+-QUESTIONS-.+)\.md$")
BUG_FILENAME_RE = re.compile(rf"^BUG-{_FILENAME_ID}(?:-.+)?\.md$")
_STEM_ID_RE = re.compile(rf"^((?:{_KINDS_ALT}|EVAL|FART)-(?:[A-Z][A-Z0-9]*-)*\d+(?:-\d+)*)")


@dataclass(frozen=True)
class ParsedId:
    kind: str
    code: str
    number: str
    strict: bool

    @property
    def parts(self) -> tuple[str, str, str]:
        return (self.kind, self.code, self.number)


def parse_id(spec_id: object, *, strict: bool = False) -> ParsedId | None:
    """Split ``spec_id`` into kind, code and number; ``None`` when unrecognised.

    ``strict=True`` accepts only the R1 grammar.  The default accepts every
    historical form too (``ParsedId.strict`` says which matched).
    """
    if not isinstance(spec_id, str):
        return None
    match = STRICT_ID_RE.match(spec_id)
    if match:
        return ParsedId(match["kind"], match["code"], match["number"], True)
    if strict:
        return None
    match = LEGACY_ID_RE.match(spec_id)
    if match:
        return ParsedId(match["kind"], match["code"].rstrip("-"), match["number"], False)
    return None


def split_id(spec_id: str) -> tuple[str, str, str] | None:
    parsed = parse_id(spec_id)
    return parsed.parts if parsed else None


def is_recognised_id(spec_id: object) -> bool:
    return parse_id(spec_id) is not None


def find_tokens(text: str) -> list[str]:
    """Every spec-ID token in free text (legacy and R1 shapes)."""
    return TOKEN_RE.findall(text)


def id_from_stem(stem: str) -> str | None:
    """The leading ID of a spec file stem (``SPEC-NS-KIT-002-slug`` -> ``SPEC-NS-KIT-002``)."""
    match = _STEM_ID_RE.match(stem)
    return match.group(1) if match else None


def is_spec_filename(name: str) -> bool:
    return bool(SPEC_FILENAME_RE.match(name))


def is_bug_spec_filename(name: str) -> bool:
    return bool(BUG_FILENAME_RE.match(name))


# ---------------------------------------------------------------------------
# R2: id kind <-> frontmatter type
# ---------------------------------------------------------------------------

def expected_type_for_kind(kind: str) -> str | None:
    """The one ``type:`` a kind demands, or ``None`` for ``SPEC`` (every other type)."""
    return _KIND_TO_TYPE.get(kind)


def kind_type_mismatch(spec_id: str, spec_type: object) -> str | None:
    """Return a message when a new ID's kind and ``type:`` disagree (R2), else ``None``."""
    parsed = parse_id(spec_id)
    if parsed is None or parsed.kind not in ID_KINDS:
        return None
    declared = str(spec_type or "").strip().lower()
    required = expected_type_for_kind(parsed.kind)
    if required is not None:
        if declared != required:
            return (
                f"spec_id_kind_type: id {spec_id} has kind {parsed.kind}, which requires "
                f"type: {required}, but the spec declares type: {declared or '(none)'}"
            )
        return None
    if declared in set(_KIND_TO_TYPE.values()):
        want = next(kind for kind, value in _KIND_TO_TYPE.items() if value == declared)
        return (
            f"spec_id_kind_type: id {spec_id} has kind SPEC, but type: {declared} "
            f"requires kind {want}"
        )
    return None


# ---------------------------------------------------------------------------
# R3: project codes
# ---------------------------------------------------------------------------

# The locked initial table (SPEC-416 Gap Protocol, 2026-10-03), keyed by the
# registry project name.  A project missing here fails registry generation.
PROJECT_CODES: Mapping[str, str] = {
    "API": "CTX-API",
    "CORE": "CTX-CORE",
    "MCP": "CTX-MCP",
    "TOOLS": "CTX-TOOLS",
    "FARTOWNIK": "FART-APP",
    "BE": "FART-BE",
    "NIGHTSHIFT": "NS-CTL",
    "NIGHTSHIFT-CANONICAL": "NS-KIT",
    "INWESTOMAT": "INWEST-HUB",
    "INVESTING-MCP": "INWEST-MCP",
    "AGENT-CHAT-MCP": "ACHAT",
    "ARGO": "ARGO",
    "BENCHMARKS": "BENCH",
    "COJEZDZI": "COJEZD",
    "FORECASTS": "FCAST",
    "SUPERFORECASTING": "SFCAST",
    "FOCUS": "FOCUS",
    "GRAPHIFY": "GRAPHY",
    "HEAR-ME-SAY": "HEARME",
    "LMAC-RUN-MCP": "LMACRN",
    "LMSTUDIO-MCP": "LMSTUD",
    "SHIPYARD": "SHIPYD",
    "XLSX-TOOLKIT": "XLSXTK",
    # Owner-authority additions (2026-10-05) for projects registered after the table was locked.
    "CRAFTJOBQUOTE": "CJQ",
    "GAMENIGHTLEDGER": "GNL",
    "WORKSHOPFRACTIONSHEET": "WFS",
    "CLOUDSYNCKIT": "CSK",  # Owner-authority addition, SPEC-NS-KIT-248 (2026-10-22).
}


def code_shape_error(code: object) -> str | None:
    """Why ``code`` is not an R1 code, or ``None`` when it is well-formed."""
    if not isinstance(code, str) or not code:
        return "code is missing"
    segments = code.split("-")
    if len(segments) > 2:
        return f"code {code!r} has {len(segments)} segments; at most 2 (FAMILY-PROJECT) are allowed"
    for segment in segments:
        if not _CODE_SEGMENT_RE.match(segment):
            return (
                f"code {code!r} segment {segment!r} must be 2-6 uppercase ASCII letters "
                "(no digits, no empty or hyphen-only segments)"
            )
    return None


def code_status(code: object) -> str:
    """``ok`` | ``missing`` | ``malformed`` for one project's registered code."""
    if not isinstance(code, str) or not code:
        return "missing"
    return "malformed" if code_shape_error(code) else "ok"


def project_for_spec_id(spec_id: object, projects: Sequence[Mapping[str, object]]) -> Mapping[str, object] | None:
    """Owner of an R1 ID by its project code, or ``None`` (legacy IDs fall back to prefixes)."""
    parsed = parse_id(spec_id, strict=True)
    if parsed is None:
        return None
    matches = [project for project in projects if project.get("code") == parsed.code]
    return matches[0] if len(matches) == 1 else None


def validate_project_codes(projects: Sequence[Mapping[str, object]]) -> list[str]:
    """Fail-closed registry check (R3); every message names the project."""
    errors: list[str] = []
    seen: dict[str, str] = {}
    for project in projects:
        name = str(project.get("name") or "?")
        code = project.get("code")
        problem = code_shape_error(code)
        if problem:
            errors.append(f"project {name}: {problem}")
            continue
        assert isinstance(code, str)
        if code in seen:
            errors.append(f"project {name}: duplicate code {code!r} (also used by project {seen[code]})")
        else:
            seen[code] = name
    families = {code.split("-")[0]: seen_name for code, seen_name in seen.items() if "-" in code}
    for code, name in seen.items():
        if "-" not in code and code in families:
            errors.append(
                f"project {name}: code {code!r} is also the family stem of project {families[code]}'s "
                "code; a family stem is never a standalone project code"
            )
    return errors


# ---------------------------------------------------------------------------
# R6: minting
# ---------------------------------------------------------------------------

def mint_id(kind: str, code: str, used_ids: Iterable[str]) -> str:
    """Next ``{kind}-{code}-NNN`` whose number is unused under ``code`` anywhere in ``used_ids``.

    ``used_ids`` is every ID known locally plus every ID in the fleet, so the
    result is never present in any registered project.
    """
    if kind not in ID_KINDS:
        raise ValueError(f"unknown id kind {kind!r}; expected one of {', '.join(ID_KINDS)}")
    problem = code_shape_error(code)
    if problem:
        raise ValueError(problem)
    ids = {str(value) for value in used_ids}
    numbers: set[int] = set()
    for other in ids:
        parsed = parse_id(other)
        if parsed and parsed.code == code:
            numbers.add(int(parsed.number.split("-")[0]))
    number = (max(numbers) + 1) if numbers else 1
    candidate = f"{kind}-{code}-{number:03d}"
    while candidate in ids or number in numbers:
        number += 1
        candidate = f"{kind}-{code}-{number:03d}"
    return candidate


# BUG-NS-KIT-246: commit hooks need only registry identity and one frozen list,
# never a scan of fleet specs or a network lookup.
def commit_project_legacy_ids(install: Path, project_root: Path) -> tuple[str | None, set[str], str | None]:
    """Return registered code, frozen membership and an optional one-line warning.

    Unknown/unregistered projects retain grammar-only validation. Linked worktrees
    resolve through their primary checkout, preserving the checkout subdirectory.
    """
    install, project_root = install.resolve(), project_root.resolve()
    registry = install / "projects-registry.json"
    if not registry.is_file():
        registry = install / ".nightshift" / "projects-registry.json"
    try:
        payload = json.loads(registry.read_text(encoding="utf-8"))
        rows = payload["projects"]
        if not isinstance(rows, list):
            return None, set(), None
    except (OSError, ValueError, KeyError, TypeError):
        return None, set(), None
    roots = {project_root}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir", "--show-prefix"],
            cwd=project_root, text=True, capture_output=True, timeout=5,
        )
        lines = result.stdout.splitlines()
        if result.returncode == 0 and lines:
            roots.add((Path(lines[0]).parent / (lines[1] if len(lines) > 1 else "")).resolve())
    except (OSError, subprocess.TimeoutExpired):
        pass
    codes = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            continue
        registered = Path(os.path.expandvars(os.path.expanduser(row["path"].replace("{{HOME}}", str(Path.home()))))).resolve()
        if registered in roots and code_shape_error(row.get("code")) is None:
            codes.add(row["code"])
    if len(codes) != 1:
        return None, set(), None
    code = codes.pop()
    path = install / "spec-id-legacy" / f"{code}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ids = data["ids"]
        if not isinstance(ids, list) or not all(isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+", item) for item in ids):
            raise ValueError("ids must contain only alphanumeric legacy ID tokens")
        if data.get("project_code", code) != code:
            raise ValueError("project code does not match registered owner")
        return code, set(ids), None
    except (OSError, ValueError, KeyError, TypeError):
        return code, set(), f"[nightshift commit-msg] WARNING: unreadable legacy ID list {path}; grammar only"


def commit_id_ere(install: Path, project_root: Path) -> str:
    """POSIX ERE union of the unchanged grammar and exact local legacy tokens."""
    _code, ids, warning = commit_project_legacy_ids(install, project_root)
    if warning:
        print(warning, file=sys.stderr)
    # Frozen tokens allow historical letter suffixes too; no token can contain ERE syntax.
    return "(" + "|".join([COMMIT_ID_ERE, *sorted(ids)]) + ")" if ids else COMMIT_ID_ERE


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Offline commit-hook ID membership")
    parser.add_argument("--commit-id-ere", action="store_true", required=True)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    print(commit_id_ere(args.install, args.project_root))
