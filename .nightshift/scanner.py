"""Secret/PII scanner and commit escalation gate for Nightshift.

The public entry point is :func:`scan_diff`, which returns structured findings
and escalation decisions without requiring git. The CLI wraps it for hooks.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Iterable


DEFAULT_DIFF_RISK_THRESHOLD = 500
DEFAULT_TOKEN_COST_THRESHOLD = 8_000
DEFAULT_SIGNOFF_ENV = "NIGHTSHIFT_ESCALATION_SIGNOFF"

# BUG-013: a location whose file could not be determined says so, rather than
# inheriting the name of whatever file happened to parse last.
UNKNOWN_PATH = "<unknown path>"

# SPEC-192: an acknowledgement may never outlive review by more than this.
MAX_ACKNOWLEDGEMENT_DAYS = 365
MIN_ACKNOWLEDGEMENT_REASON = 10

# SPEC-093 R3: Cortex screens external ingestion through a synthetic diff whose "file" is
# not a repository path at all. It can never be a fixture path, so it is named here rather
# than left to the anchor rules to refuse by accident.
CORTEX_EXTERNAL_LOCATION = "cortex-ingested-external"

# SPEC-197: the kit's own detector fixtures. A finding is excluded only where BOTH a
# kit-owned anchor and the digest of the exact matched value agree; neither generalises
# alone. The anchors ship with this file (canonical-owned, no project surface); the digests
# live beside the tests, which `nightshift-sync.py` never delivers to a project install - so
# an install finds no registry and excludes nothing.
FIXTURE_REGISTRY_RELPATH = "tests/fixture_digests.txt"
FIXTURE_PATH_ANCHORS = ("tests/test_scanner.py",)
_FIXTURE_ANCHOR_BASENAME = re.compile(r"^test_[A-Za-z0-9_]+\.py$")

# Project-owned Nightshift state is outside the canonical managed-payload
# contract.  This closed fallback is consulted only when the release marker is
# unreadable, so config/spec/report work remains possible while every unknown
# payload-shaped path fails closed.  ``board-reads.json`` is the deployed
# board's own write-state, which SPEC-229's KIT.CLOSURE invariant already
# excludes from the payload; naming it here keeps the fallback's classification
# identical to the marker-readable one (SPEC-241).
PROJECT_OWNED_NIGHTSHIFT_EXACT = frozenset(
    {"config.yaml", "projects-registry.json", "STOP", ".gitignore", "board-reads.json"}
)
PROJECT_OWNED_NIGHTSHIFT_PREFIXES = (
    "specs/",
    "metrics/",
    "reports/",
    "knowledge/",
    "runs/",
    "checkpoints/",
    "scenarios/",
    "prompts/",
    ".migrations/",
)

PROTOCOL_ARCHIVE_PREFIX = ".argo/protocol-archive/"
# SPEC-373: the context folder is being renamed `.argo/` -> `.agent-context/`
# installation by installation, so both root-anchored archive prefixes are
# recognized. Verification below is identical for both.
PROTOCOL_ARCHIVE_PREFIXES = (".agent-context/protocol-archive/", PROTOCOL_ARCHIVE_PREFIX)


INSTALL_MARKER = ".nightshift/"


def staged_install_prefixes(paths: Iterable[str]) -> list[str]:
    """Return every managed install prefix represented in *paths*.

    A repository may carry more than one install — Argo Home has both
    ``.nightshift/`` and ``Skills/focus/.nightshift/`` — and a whole-kit release
    stages payload into all of them at once. Recognizing only a root-level
    install left the other install's payload unexempted, so a release's own
    verified bytes counted toward the diff-size escalation.
    """
    prefixes = set()
    for path in paths:
        index = path.find(INSTALL_MARKER)
        if index != -1:
            prefixes.add(path[: index + len(INSTALL_MARKER)])
    return sorted(prefixes)


def _potential_managed_stage(path: str, prefix: str = INSTALL_MARKER) -> bool:
    if not path.startswith(prefix):
        return False
    relative = path[len(prefix) :]
    try:
        from release import is_ignored_python_cache_path
    except ImportError:
        # The narrow Cortex scanner copy intentionally ships without the full
        # Nightshift release graph. Keep identical fallback semantics there.
        candidate = PurePosixPath(relative.replace("\\", "/"))
        is_cache = "__pycache__" in candidate.parts or candidate.suffix in {
            ".pyc",
            ".pyo",
        }
    else:
        is_cache = is_ignored_python_cache_path(relative)
    if is_cache:
        return False
    return relative not in PROJECT_OWNED_NIGHTSHIFT_EXACT and not relative.startswith(
        PROJECT_OWNED_NIGHTSHIFT_PREFIXES
    )


def verified_archive_snapshot_paths(staged_paths: Iterable[str]) -> frozenset[str]:
    """Return staged archive paths whose index blob is reachable from history.

    Archive filenames and contents are both untrusted.  The only exemption proof is
    that the *complete staged blob* is already reachable from a repository ref;
    an altered byte produces a distinct object and remains subject to escalation.
    This intentionally runs only for staged Git input, not ``--diff-file`` where
    no index blob is available to prove the complete snapshot body.
    """
    candidates = sorted(path for path in staged_paths if path.startswith(PROTOCOL_ARCHIVE_PREFIXES))
    if not candidates:
        return frozenset()

    history = subprocess.run(
        ["git", "rev-list", "--objects", "--all"], capture_output=True, check=False
    )
    if history.returncode:
        return frozenset()
    reachable = {line.split(b" ", 1)[0] for line in history.stdout.splitlines()}

    verified: set[str] = set()
    for path in candidates:
        index_blob = subprocess.run(
            ["git", "rev-parse", f":{path}"], capture_output=True, check=False
        )
        blob = index_blob.stdout.strip()
        if index_blob.returncode or not blob or blob not in reachable:
            continue
        is_blob = subprocess.run(
            ["git", "cat-file", "-e", f"{blob.decode('ascii')}^{{blob}}"], check=False
        )
        if is_blob.returncode == 0:
            verified.add(path)
    return frozenset(verified)


@dataclass(frozen=True)
class Finding:
    type: str
    location: str
    matched_class: str


@dataclass(frozen=True)
class Escalation:
    kind: str
    value: int
    threshold: int
    signoff_env: str


@dataclass(frozen=True)
class Acknowledgement:
    """One reviewed PII value, accepted by digest until it expires (SPEC-192)."""

    matched_class: str
    sha256: str
    reason: str
    expires: date


@dataclass(frozen=True)
class AcknowledgedFinding:
    """A finding that did not block because a human accepted this exact value."""

    finding: Finding
    reason: str
    expires: date


@dataclass(frozen=True)
class FixtureRegistry:
    """The kit's own detector fixtures, as digests plus the paths they may appear at.

    Both halves are positive requirements (SPEC-197 R3). An empty registry - the state of
    every project install, which never receives `tests/` - excludes nothing and is not an
    error.
    """

    digests: frozenset[str] = frozenset()
    anchors: tuple[str, ...] = ()
    discarded: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScanReport:
    findings: list[Finding]
    escalations: list[Escalation]
    added_lines: int
    token_cost: int
    acknowledged: list[AcknowledgedFinding] = field(default_factory=list)
    discarded_acknowledgements: list[str] = field(default_factory=list)
    excluded: list[Finding] = field(default_factory=list)
    discarded_fixtures: list[str] = field(default_factory=list)
    managed_files_skipped: int = 0
    managed_files_exempted: int = 0
    managed_added_lines_exempted: int = 0
    archive_files_exempted: int = 0
    archive_added_lines_exempted: int = 0

    @property
    def blocked(self) -> bool:
        return bool(self.findings)

    @property
    def needs_escalation(self) -> bool:
        return bool(self.escalations)


@dataclass(frozen=True)
class ScannerConfig:
    diff_risk_threshold: int = DEFAULT_DIFF_RISK_THRESHOLD
    token_cost_threshold: int = DEFAULT_TOKEN_COST_THRESHOLD
    signoff_env: str = DEFAULT_SIGNOFF_ENV
    pii_acknowledgements: tuple[Acknowledgement, ...] = ()
    discarded_acknowledgements: tuple[str, ...] = ()


SECRET_PATTERNS = [
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b", re.IGNORECASE)),
    (
        "api_key",
        re.compile(
            r"\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\b"
            r"\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{16,}[\"']?",
            re.IGNORECASE,
        ),
    ),
]

PII_PATTERNS = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    (
        # SPEC-183: a bare undelimited digit run is an identifier, not a phone number.
        # Require real phone shape - parentheses, or a separator between each group, or
        # an explicit country code. Undelimited runs are still caught, but only beside a
        # phone-context keyword (see _phone_context_ok). Without this, every 10-digit id
        # matched: SEC CIKs, Unix mtimes, DB tuples, 3,532 broker transaction ids in one CSV.
        "phone",
        re.compile(
            r"(?<![\d.])"
            r"(?:\+\d{1,3}[\s.-]?)?"           # optional country code, must be explicit
            r"(?:\(\d{3}\)\s*|\d{3}[\s.-])"    # area code: parenthesised, or separator after
            r"\d{3}[\s.-]\d{4}"                # exchange + line, separator required
            r"(?![\d.])"
        ),
    ),
    (
        # SPEC-183: bound the gap between street number and street type. The previous
        # pattern used an unbounded [A-Za-z0-9.' -]+ run, so ANY digit earlier on a line
        # matched ANY later street-ish word - "10 million cars on the road", a line of
        # Python ending "... 1 for st in scored", a journal citation. A real address has
        # at most a few tokens between number and type. Bare lowercase "st"/"dr"/"way"
        # are ordinary English words, so unabbreviated types must be capitalised.
        #
        # SPEC-192: street names are proper nouns, so every token in the gap must start
        # capitalised or numeric too. Without this, a date followed by a capitalised
        # publication name reads as an address - the gap swallowed the lowercase word
        # between them. Prose of that shape recurs constantly in a news corpus, so it is
        # ruled out here rather than acknowledged one line at a time. The cost is recall
        # on lowercase-connector addresses ("... de la ... Avenue"), accepted knowingly.
        "home_address",
        re.compile(
            r"\b\d{1,6}(?:-\d{1,6})?\s+"
            r"(?:[A-Z0-9][A-Za-z0-9.'-]*\s+){0,3}"
            r"(?:Street|Avenue|Road|Lane|Drive|Boulevard|Court|Way|Place"
            r"|St\.|Ave\.?|Rd\.|Ln\.|Dr\.|Blvd\.?|Ct\.|Pl\.)"
            r"(?![A-Za-z])"
        ),
    ),
]

# SPEC-183: bare, undelimited digit runs only count as phone numbers when an explicit
# phone-context keyword precedes them. Keeps recall on a keyword followed by ten digits
# without treating every identifier in a research corpus as PII.
# (Deliberately no literal example here — the rule correctly flags one, and this file
#  is itself scanned. The worked examples live in tests/test_scanner.py.)
PHONE_CONTEXT_PATTERN = re.compile(
    r"\b(?:phone|tel|telephone|mobile|cell|fax|whatsapp|call|contact|reach)\b"
    r"(?:[\s:#,]+[A-Za-z]{1,6}\.?){0,3}"  # bounded filler: "call me at", "reach him on"
    r"[\s:#]*$",
    re.IGNORECASE,
)
BARE_PHONE_PATTERN = re.compile(r"(?<![\d.])\+?1?\s?(\d{10})(?![\d.])")

CANONICAL_RUN_ID_PATTERN = re.compile(r"\brun-\d{4}-\d{2}-\d{2}-\d{6}\b")

# SPEC-198: RFC 2606 §2 reserves these top-level domains and RFC 6761 restates them as
# special-use names that resolvers must refuse to resolve. No mail exchanger for them can
# exist, so an address under one cannot receive mail and cannot identify a person.
RESERVED_EMAIL_TLDS = frozenset({"test", "example", "invalid", "localhost"})

# SPEC-198: RFC 2606 §3 reserves these second-level names for the same purpose.
# Deliberately not here: ".local" is mDNS, and ".internal" is ICANN's private-use name -
# a private network's own mail can be delivered there, so both stay PII.
RESERVED_EMAIL_DOMAINS = frozenset({"example.com", "example.net", "example.org"})

# BUG-013: matched against whole, unprefixed lines only. Every content line in a unified
# diff carries a prefix character, so content can never satisfy this.
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_C_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, "\\": 92, '"': 34}

PII_CLASSES = frozenset(name for name, _ in PII_PATTERNS) | {"phone"}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def load_config(path: Path) -> ScannerConfig:
    """Load the small git escalation surface without requiring PyYAML."""
    if not path.is_file():
        return ScannerConfig()

    values: dict[str, str] = {}
    in_git = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if re.match(r"^git:\s*$", line):
            in_git = True
            continue
        if line and not line.startswith((" ", "\t")):
            in_git = False
        if not in_git:
            continue
        match = re.match(r"^\s+([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$", line)
        if match:
            key, value = match.groups()
            values[key] = value.strip("\"'")

    acknowledgements, discarded = load_pii_acknowledgements(path)
    return ScannerConfig(
        diff_risk_threshold=_int_value(values.get("diff_risk_threshold"), DEFAULT_DIFF_RISK_THRESHOLD),
        token_cost_threshold=_int_value(values.get("token_cost_threshold"), DEFAULT_TOKEN_COST_THRESHOLD),
        signoff_env=values.get("escalation_signoff_env") or DEFAULT_SIGNOFF_ENV,
        pii_acknowledgements=tuple(acknowledgements),
        discarded_acknowledgements=tuple(discarded),
    )


def scan_diff(
    diff_text: str,
    *,
    config: ScannerConfig | None = None,
    environ: dict[str, str] | None = None,
    today: date | None = None,
    fixtures: FixtureRegistry | None = None,
    managed_paths: Iterable[str] = (),
    archive_paths: Iterable[str] = (),
) -> ScanReport:
    """Scan added diff lines for secrets/PII and threshold-triggered escalation."""
    cfg = config or ScannerConfig()
    env = environ if environ is not None else dict(os.environ)
    now = today or date.today()
    registry = load_fixture_registry() if fixtures is None else fixtures
    added = list(_added_lines(diff_text))
    managed = frozenset(managed_paths)
    archive = frozenset(archive_paths)
    skipped_paths = {_location_path(location) for location, _ in added} & managed
    findings: list[Finding] = []
    acknowledged: list[AcknowledgedFinding] = []
    excluded: list[Finding] = []

    for location, text in added:
        for finding, digest in _scan_line(text, location):
            # SPEC-213: a release manifest is the single authority for canonical
            # payload ownership. Managed documentation still passes through the
            # secret scanner; only its PII findings are exempt, so a leaked key
            # can never hide behind release ownership.
            if finding.type == "pii" and _location_path(location) in managed:
                continue
            # SPEC-197: a kit fixture is decided before, and independently of, review.
            # Neither mechanism can accept what the other refuses (R12).
            if _is_kit_fixture(finding, digest, registry):
                excluded.append(finding)
                continue
            accepted = _acknowledgement_for(finding, digest, cfg.pii_acknowledgements, now)
            if accepted is None:
                findings.append(finding)
            else:
                acknowledged.append(AcknowledgedFinding(finding, accepted.reason, accepted.expires))

    # SPEC-214: managed paths reach this function only after the staged-install
    # provenance gate has proven their bytes against the release manifest. Their
    # size therefore says nothing about authored change risk. Keep scanning their
    # content for secrets, but exclude their added lines from the human-review
    # thresholds. A changed payload never enters ``managed`` because provenance
    # rejects it before this call, so it remains fully counted.
    escalation_added = [
        (location, text)
        for location, text in added
        if _location_path(location) not in managed | archive
    ]
    managed_exempted_lines = sum(1 for location, _ in added if _location_path(location) in managed)
    archive_exempted_lines = sum(1 for location, _ in added if _location_path(location) in archive)
    added_text = "\n".join(text for _, text in escalation_added)
    token_cost = _estimate_tokens(added_text)
    escalations = _escalations(len(escalation_added), token_cost, cfg, env)
    return ScanReport(
        findings,
        escalations,
        len(escalation_added),
        token_cost,
        acknowledged,
        list(cfg.discarded_acknowledgements),
        excluded,
        list(registry.discarded),
        len(skipped_paths),
        len(skipped_paths),
        managed_exempted_lines,
        len(archive),
        archive_exempted_lines,
    )


def value_digest(value: str) -> str:
    """Return the stable reference for a matched value (SPEC-192).

    The digest, never the value, is what an acknowledgement records: a config file
    holding literal PII would be PII in a tracked file, and adding one would trip the
    gate it exists to satisfy.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_fixture_registry(
    path: Path | None = None, *, anchors: Iterable[str] = FIXTURE_PATH_ANCHORS
) -> FixtureRegistry:
    """Read the kit's fixture digests, discarding anything it cannot fully validate.

    SPEC-197 R6. Every gate is a positive requirement, so there is no parse path from bad
    input to a wider gate: a malformed digest or an over-broad anchor is dropped and every
    finding it would have covered still blocks. A missing registry is the normal state of a
    project install and is not an error - it simply excludes nothing.
    """
    discarded: list[str] = []
    accepted_anchors: list[str] = []
    for anchor in anchors:
        problem = _fixture_anchor_problem(anchor)
        if problem:
            discarded.append(f"anchor {anchor!r}: {problem}")
        else:
            accepted_anchors.append(anchor)

    registry_path = _default_registry_path() if path is None else path
    digests: set[str] = set()
    if registry_path.is_file():
        for index, raw in enumerate(registry_path.read_text(encoding="utf-8").splitlines(), start=1):
            entry = raw.split("#", 1)[0].strip().lower()  # strip inline comments FIRST
            if not entry:
                continue
            if not _SHA256_PATTERN.match(entry):
                discarded.append(f"entry {index}: digest must be 64 hex characters")
                continue
            digests.add(entry)

    return FixtureRegistry(frozenset(digests), tuple(accepted_anchors), tuple(discarded))


def _default_registry_path() -> Path:
    """Locate the registry beside this module.

    That is what makes the mechanism inert outside canonical. `nightshift-sync.py`
    propagates `scanner.py` but no `tests/` entry at all, so an install's
    `.nightshift/scanner.py` looks for a sibling `tests/` that was never delivered.
    """
    return Path(__file__).resolve().parent / FIXTURE_REGISTRY_RELPATH


def _fixture_anchor_problem(anchor: str) -> str:
    """Return why an anchor is unusable, or "" if it is safe.

    SPEC-197 R7. An anchor is matched as a path *suffix*, because the same logical file is
    at a different repository-relative path in canonical, in Argo Home and in an install.
    A suffix is exactly the over-broad shape to fear, so the anchor itself is confined to a
    test file directly inside a `tests/` directory - which no source file, spec, corpus file
    or config file can satisfy.
    """
    if not isinstance(anchor, str) or not anchor or anchor != anchor.strip():
        return "must be a non-empty path with no surrounding whitespace"
    if anchor.startswith("/"):
        return "must be repository-relative, not absolute"
    if "\\" in anchor:
        return "must use forward slashes"
    if any(char in anchor for char in "*?[]"):
        return "must not contain glob metacharacters"
    parts = anchor.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return "must not contain empty, '.' or '..' segments"
    if len(parts) < 2 or parts[-2] != "tests":
        return "must name a file directly inside a tests/ directory"
    if not _FIXTURE_ANCHOR_BASENAME.match(parts[-1]):
        return "must name a test_*.py file"
    return ""


def _is_kit_fixture(finding: Finding, digest: str, registry: FixtureRegistry) -> bool:
    """Return whether this exact value, at this exact kind of path, is a kit fixture.

    Both conditions are required (SPEC-197 R3). The digest alone would let a fixture value
    copied into `scanner.py`, a spec, `CHANGELOG.md` or a commit message escape the gate,
    which is the SPEC-183 convention this mechanism exists to enforce mechanically. The path
    alone would let any repository create a file at the anchor suffix and drop a live
    credential into it.
    """
    if digest not in registry.digests:
        return False
    path = _location_path(finding.location)
    # R9/R10: a location that names no repository file is never a fixture path, whatever
    # anchors are configured.
    if path in {UNKNOWN_PATH, CORTEX_EXTERNAL_LOCATION}:
        return False
    return any(path == anchor or path.endswith(f"/{anchor}") for anchor in registry.anchors)


def _location_path(location: str) -> str:
    """Strip the trailing line number from a location, leaving the path it named."""
    head, separator, tail = location.rpartition(":")
    return head if separator and tail.isdigit() else location


def _acknowledgement_for(
    finding: Finding,
    digest: str,
    acknowledgements: Iterable[Acknowledgement],
    today: date,
) -> Acknowledgement | None:
    """Return the acknowledgement accepting this finding, if a valid one exists.

    Secrets are never acknowledgeable. Expiry is re-checked here as well as at load, so
    a config assembled in code cannot bypass the decay rule.
    """
    if finding.type != "pii":
        return None
    for entry in acknowledgements:
        if entry.sha256 == digest and entry.matched_class == finding.matched_class and entry.expires >= today:
            return entry
    return None


def load_pii_acknowledgements(
    path: Path, *, today: date | None = None
) -> tuple[list[Acknowledgement], list[str]]:
    """Read git.pii_acknowledgements (SPEC-192) as (accepted, discarded-with-reason).

    Every field is a positive requirement, so any record this cannot fully validate is
    dropped and its finding keeps blocking. There is no parse path from malformed input
    to a wider gate.
    """
    if not path.is_file():
        return [], []

    now = today or date.today()
    accepted: list[Acknowledgement] = []
    discarded: list[str] = []
    for index, record in enumerate(_acknowledgement_records(path), start=1):
        entry, problem = _validate_acknowledgement(record, now)
        if entry is not None:
            accepted.append(entry)
        else:
            discarded.append(f"entry {index}: {problem}")
    return accepted, discarded


def _acknowledgement_records(path: Path) -> list[dict[str, str]]:
    """Collect the raw key/value records under git.pii_acknowledgements."""
    records: list[dict[str, str]] = []
    in_git = False
    list_indent: int | None = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()  # strip inline comments FIRST
        if not line.strip():
            continue
        if re.match(r"^git:\s*$", line):
            in_git, list_indent = True, None
            continue
        if not line.startswith((" ", "\t")):
            in_git, list_indent = False, None
            continue
        if not in_git:
            continue

        indent = len(line) - len(line.lstrip())
        if re.match(r"^\s+pii_acknowledgements:\s*$", line):
            list_indent = indent
            continue
        if list_indent is None:
            continue
        if indent <= list_indent:
            list_indent = None  # a sibling git key ends the list
            continue

        item = re.match(r"^\s*-\s*([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$", line)
        if item:
            records.append({item.group(1): item.group(2).strip("\"'")})
            continue
        field_match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*(.*?)\s*$", line)
        if field_match and records:
            records[-1][field_match.group(1)] = field_match.group(2).strip("\"'")
    return records


def _validate_acknowledgement(
    record: dict[str, str], today: date
) -> tuple[Acknowledgement | None, str]:
    digest = record.get("sha256", "").strip().lower()
    if not _SHA256_PATTERN.match(digest):
        return None, "sha256 must be 64 hex characters"

    matched_class = record.get("class", "").strip()
    if matched_class not in PII_CLASSES:
        return None, f"class must be one of {', '.join(sorted(PII_CLASSES))}"

    reason = record.get("reason", "").strip()
    if len(reason) < MIN_ACKNOWLEDGEMENT_REASON:
        return None, f"reason must be at least {MIN_ACKNOWLEDGEMENT_REASON} characters"

    raw_expiry = record.get("expires", "").strip()
    try:
        expires = date.fromisoformat(raw_expiry)
    except ValueError:
        return None, "expires must be a YYYY-MM-DD date"
    if expires < today:
        return None, f"expired on {expires.isoformat()}"
    if expires > today + timedelta(days=MAX_ACKNOWLEDGEMENT_DAYS):
        return None, f"expires more than {MAX_ACKNOWLEDGEMENT_DAYS} days ahead"

    return Acknowledgement(matched_class, digest, reason, expires), ""


def load_unprefixed_paths(path: Path) -> list[str]:
    """Read git.unprefixed_paths (SPEC-183) using the same rules as load_config.

    Shares one config reader with the rest of the kit deliberately: a second,
    hand-rolled parser in the commit-msg hook silently swallowed an inline comment
    and produced a garbage prefix, which is the failure mode DevKB warns about.
    """
    if not path.is_file():
        return []

    paths: list[str] = []
    in_git = False
    in_list = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()  # strip inline comments FIRST
        if not line.strip():
            continue
        if re.match(r"^git:\s*$", line):
            in_git, in_list = True, False
            continue
        if not line.startswith((" ", "\t")):
            in_git, in_list = False, False
            continue
        if not in_git:
            continue
        if re.match(r"^\s+unprefixed_paths:\s*$", line):
            in_list = True
            continue
        item = re.match(r"^\s+-\s*(.+?)\s*$", line)
        if in_list and item:
            value = item.group(1).strip().strip("\"'")
            if value:
                paths.append(value)
            continue
        in_list = False
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan a git diff for secrets, PII, and escalation thresholds.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--staged", action="store_true", help="scan git diff --cached")
    source.add_argument("--diff-file", type=Path, help="scan a saved diff file")
    source.add_argument(
        "--unprefixed-paths",
        action="store_true",
        help="print git.unprefixed_paths, one per line (used by hooks/commit-msg)",
    )
    parser.add_argument("--config", type=Path, default=Path(".nightshift/config.yaml"))
    parser.add_argument(
        "--acknowledge-template",
        action="store_true",
        help="print a fill-in acknowledgement stanza for each blocking PII finding",
    )
    args = parser.parse_args(argv)

    if args.unprefixed_paths:
        for entry in load_unprefixed_paths(args.config):
            print(entry)
        return 0

    managed_payload_blocked = False
    staged_nightshift_paths: list[str] = []
    staged_paths: list[str] = []
    managed_paths: frozenset[str] = frozenset()
    archive_paths: frozenset[str] = frozenset()
    if args.staged:
        staged_names = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "-z"],
            capture_output=True,
            check=False,
        )
        if staged_names.returncode == 0:
            staged_paths = [
                path.decode("utf-8", errors="surrogateescape")
                for path in staged_names.stdout.split(b"\0")
                if path
            ]
            staged_nightshift_paths = [path for path in staged_paths if INSTALL_MARKER in path]
            archive_paths = verified_archive_snapshot_paths(staged_paths)

    install_prefixes = [
        prefix
        for prefix in staged_install_prefixes(staged_nightshift_paths)
        if any(_potential_managed_stage(path, prefix) for path in staged_nightshift_paths)
    ]
    if install_prefixes:
        # Import only on the installed hook path.  ``scan_diff`` is also used as
        # a standalone library by Cortex, whose intentionally narrow copy does
        # not own the Nightshift release/provenance helper graph.
        from managed_payload_provenance import (
            MetadataError,
            format_guidance,
            guard_staged_install,
            managed_payload_paths,
            retained_manifest,
            sync_receipt_index,
        )

        exempt: set[str] = set()
        for prefix in install_prefixes:
            install = Path(prefix.rstrip("/"))
            try:
                managed_rows = guard_staged_install(install)
            except MetadataError as exc:
                # With no trustworthy manifest, fail closed only for the staged
                # Nightshift surface.  An application-only commit never enters this
                # branch, so damaged metadata cannot freeze unrelated development.
                print(f"[nightshift scanner] Managed payload metadata error: {exc}", file=sys.stderr)
                print(format_guidance(), file=sys.stderr)
                managed_payload_blocked = True
                continue
            if managed_rows:
                print("[nightshift scanner] Managed payload edit rejected.", file=sys.stderr)
                print(format_guidance(managed_rows), file=sys.stderr)
                managed_payload_blocked = True
                continue
            # Preserve the repository-relative spelling emitted by git
            # diff. The provenance module owns the release-relative list.
            # BUG-339-001: ``guard_staged_install`` admits a ``nightshift-sync.py``
            # delivery vouched for by ``sync-manifest.json`` even when the install
            # has no ``release-marker.json``. Build the exemption set from the same
            # two sources the guard used: the marker's retained manifest plus the
            # receipt. A missing/unreadable marker is tolerated at this call only,
            # and only when a receipt vouches for something; otherwise it stays a
            # ``MetadataError`` exactly as before.
            synced_paths = frozenset(sync_receipt_index(install))
            try:
                released_paths = managed_payload_paths(retained_manifest(install))
            except MetadataError:
                if not synced_paths:
                    raise
                released_paths = frozenset()
            exempt.update(f"{prefix}{path}" for path in released_paths | synced_paths)
        managed_paths = frozenset(exempt)

    diff_text = _staged_diff() if args.staged else args.diff_file.read_text(encoding="utf-8")
    report = scan_diff(
        diff_text,
        config=load_config(args.config),
        managed_paths=managed_paths,
        archive_paths=archive_paths,
    )
    if args.acknowledge_template:
        _print_acknowledge_template(diff_text, report)
        # The exit code is the gate. Printing a stanza accepts nothing, so this path must
        # never report success on a diff the scan would reject - otherwise wiring the flag
        # into a hook would wedge that hook permanently open.
        return 1 if managed_payload_blocked or report.blocked or report.needs_escalation else 0
    _print_report(report)
    return 1 if managed_payload_blocked or report.blocked or report.needs_escalation else 0


def _int_value(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _added_lines(diff_text: str) -> Iterable[tuple[str, str]]:
    """Yield ``(location, text)`` for every added line in a git unified diff.

    BUG-013. Every content line in a unified diff carries a one-character prefix, so a
    line with no prefix is always structure and a prefixed line is always content. The
    single ambiguity is that git's own file headers begin with ``+++``/``---`` as well,
    and that ambiguity exists only between ``diff --git`` and the file's first hunk.
    Recognising those headers *only* in that window is what makes content unable to
    impersonate structure - and structure unable to swallow content.
    """
    current_file: str | None = None
    new_line = 0
    in_hunk = False
    named = False

    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            current_file, new_line, in_hunk, named = None, 0, False, False
            continue

        hunk = _HUNK_HEADER.match(raw)
        if hunk:
            new_line = int(hunk.group(1))
            in_hunk = True
            continue

        if not in_hunk:
            # Header window. git emits exactly one "+++" per file, so the first one
            # names the file and any later one is content wearing a header's clothes.
            if raw.startswith("+++ ") and not named:
                current_file = _header_path(raw[4:])
                named = True
                continue
            if raw.startswith("+"):
                # A synthetic diff with a file header and no hunk header. Cortex builds
                # exactly this shape to screen external ingestion through SPEC-093's
                # reusable entry point, so the body is an implicit hunk - anything else
                # scans nothing at all and the gate silently passes everything.
                in_hunk, new_line = True, 1
                yield _location(current_file, new_line), raw[1:]
                new_line += 1
            continue

        if raw.startswith("+"):
            yield _location(current_file, new_line), raw[1:]
            new_line += 1
            continue
        if raw.startswith("-"):
            # A removed line occupies no line in the new file.
            continue
        if raw.startswith("\\"):
            # "\ No newline at end of file" annotates the previous line.
            continue
        new_line += 1


def _location(current_file: str | None, new_line: int) -> str:
    path = UNKNOWN_PATH if current_file is None else current_file
    return f"{path}:{new_line}" if new_line else path


def _header_path(body: str) -> str | None:
    """Return the new-side path from a ``+++`` header, or None if it names no file.

    git renders a path with non-ASCII bytes, an embedded quote, or a control character
    in C-quoted form, and appends a tab after a path containing whitespace. Both are
    decoration added by the diff format, and neither is part of the filename.
    """
    if body.startswith('"'):
        end = _closing_quote(body)
        if end is None:
            return None
        path = _decode_c_quoted(body[1:end])
    else:
        path = body.split("\t", 1)[0]

    if path == "/dev/null":
        return None
    # _staged_diff pins --dst-prefix, so only "b/" is ever stripped. Guessing at other
    # prefixes would mangle a repository with a top-level directory of that name, and an
    # unknown-path marker is a better answer than a confidently wrong one.
    return path[2:] if path.startswith("b/") else path


def _closing_quote(value: str) -> int | None:
    idx = 1
    while idx < len(value):
        if value[idx] == "\\":
            idx += 2
            continue
        if value[idx] == '"':
            return idx
        idx += 1
    return None


def _decode_c_quoted(value: str) -> str:
    """Decode git's C-style quoting back to the real path."""
    out = bytearray()
    idx = 0
    while idx < len(value):
        char = value[idx]
        if char != "\\":
            out.extend(char.encode("utf-8"))
            idx += 1
            continue
        idx += 1
        if idx >= len(value):
            break
        escape = value[idx]
        if escape in _C_ESCAPES:
            out.append(_C_ESCAPES[escape])
            idx += 1
        elif escape in "01234567":
            octal = ""
            while len(octal) < 3 and idx < len(value) and value[idx] in "01234567":
                octal += value[idx]
                idx += 1
            out.append(int(octal, 8) & 0xFF)
        else:
            out.extend(escape.encode("utf-8"))
            idx += 1
    return out.decode("utf-8", errors="replace")


def _scan_line(text: str, location: str) -> list[tuple[Finding, str]]:
    """Return each finding paired with the digest of the exact value that matched.

    SPEC-192 needs the digest to decide whether a human has already accepted this value,
    so it is produced where the match is, not reconstructed later from the line.

    SPEC-287: the two context helpers below are given a per-line scan position instead of
    re-reading the whole prefix for every match. Both used to slice `text[: match.start()]`,
    so one line cost O(matches x line length) - a clean 4x per doubling of the input, and
    an extrapolated ~57 minutes on one real 29 MB single-line file. Each helper now reads
    only the text between the previous candidate and this one. Those windows are disjoint,
    so a whole line costs one pass. No pattern and no detection rule changed.
    """
    findings: list[tuple[Finding, str]] = []
    for matched_class, pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append((Finding("secret", location, matched_class), value_digest(match.group(0))))
    for matched_class, pattern in PII_PATTERNS:
        # SPEC-287: one memo per pattern, never shared. A second entry of the same class
        # would restart at the top of the line, and a memo carried over from the previous
        # entry would then be asked about a match behind its own scan position.
        url_path = _UrlPathContext(text)
        for match in pattern.finditer(text):
            value = match.group(0)
            if matched_class == "credit_card" and _canonical_run_id_context(text, match):
                continue
            # SPEC-183: a long digit run inside a URL path is a resource id, not a card.
            # A 19-digit tweet id happened to pass Luhn and blocked a commit.
            if matched_class == "credit_card" and url_path.holds(match):
                continue
            if _valid_pii(matched_class, value):
                findings.append((Finding("pii", location, matched_class), value_digest(value)))
    # SPEC-183: undelimited 10-digit runs are only PII beside a phone-context keyword.
    scanned_to = 0
    for match in BARE_PHONE_PATTERN.finditer(text):
        if _phone_context_ok(text, match, scanned_to) and _valid_pii("phone", match.group(1)):
            findings.append((Finding("pii", location, "phone"), value_digest(match.group(0))))
        scanned_to = match.end()
    return findings


def _phone_context_ok(text: str, match: re.Match[str], floor: int = 0) -> bool:
    """Return whether an undelimited digit run is introduced by a phone keyword.

    `floor` is where the previous `BARE_PHONE_PATTERN` match on this line ended, or 0 for
    the first one. SPEC-287: starting the search there instead of at the top of the line
    is not a narrowing of what counts as phone context, and the proof is that
    `PHONE_CONTEXT_PATTERN` cannot match a digit anywhere. Every alternative in it is
    letters and every quantified class is whitespace, ":", "#", "," or "."; the previous
    match ends on ten digits; so no match of this pattern can end at `match.start()` and
    also reach back across `floor`. The pattern is untouched - its separator runs are
    still unbounded, so a keyword thousands of separator characters ahead of the digits is
    still found, which `tests/test_scanner.py` pins.

    `search(text, floor, start)` rather than a slice, deliberately. `pos` only restricts
    where a match may begin: `\\b` and lookbehind still read the real text before `floor`,
    exactly as they would in `text[: start]`, and `endpos` makes `$` behave as it does at
    the end of that slice, trailing-newline rule included. Same answer, no copy.
    """
    return PHONE_CONTEXT_PATTERN.search(text, floor, match.start()) is not None


# SPEC-183/SPEC-287: a URL path segment ends at the first of these going backwards.
_URL_TOKEN_DELIMITERS = (" ", "\t", "(", '"')
_NON_SLASH = re.compile(r"[^/]")


class _UrlPathContext:
    """Streaming form of the "is this number inside a URL path" test (SPEC-287).

    The rule is SPEC-183's and is unchanged: read back to the nearest space, tab, "(" or
    double quote, and answer yes when the token that follows contains "://", starts with
    "/", or holds a "/" that is not part of its trailing run of slashes.

    What changed is that the token is no longer rebuilt per candidate. It used to be
    `text[: match.start()]` sliced, four times rfind-ed, then sliced again, once for every
    candidate on the line, which is O(candidates x line length). Candidates arrive in
    `finditer` order, so each call now reads only `text[previous candidate : this one]`.
    Those windows are disjoint, so the line costs one pass.

    The state is the token's start, where its first "/" is, whether any non-"/" follows
    that first "/", and whether "://" appears in it. Those four answers decide the rule,
    and each is monotone while the token start holds still - a token only ever grows to
    the right - so a window can be folded in rather than the token re-read. When a
    delimiter does turn up in the window the token start moves, and everything is
    recomputed from it; that recomputation is bounded by the same window.
    """

    __slots__ = ("_text", "_scanned_to", "_start", "_first_slash", "_slash_then_other", "_scheme")

    def __init__(self, text: str) -> None:
        self._text = text
        self._scanned_to = -1  # nothing read yet, and distinct from "read up to index 0"
        self._start = 0
        self._first_slash = -1
        self._slash_then_other = False
        self._scheme = False

    def holds(self, match: re.Match[str]) -> bool:
        """Return whether the candidate at `match` sits inside a URL path segment."""
        end = match.start()
        if self._scanned_to < 0:
            self._restart(self._last_delimiter(0, end), end)
        else:
            boundary = self._last_delimiter(self._scanned_to, end)
            if boundary < 0:
                self._extend(end)
            else:
                self._restart(boundary, end)
        self._scanned_to = end
        return self._scheme or self._first_slash == self._start or self._slash_then_other

    def _last_delimiter(self, low: int, high: int) -> int:
        text = self._text
        return max(text.rfind(delimiter, low, high) for delimiter in _URL_TOKEN_DELIMITERS)

    def _restart(self, boundary: int, end: int) -> None:
        """Recompute every flag for the token `text[boundary + 1 : end]`."""
        text = self._text
        self._start = boundary + 1
        self._first_slash = text.find("/", self._start, end)
        self._scheme = text.find("://", self._start, end) >= 0
        self._slash_then_other = (
            self._first_slash >= 0
            and _NON_SLASH.search(text, self._first_slash + 1, end) is not None
        )

    def _extend(self, end: int) -> None:
        """Fold `text[self._scanned_to : end]` in. The token start does not move."""
        text = self._text
        window = self._scanned_to
        if not self._scheme:
            # "://" can straddle the window edge, so re-read the two characters before it.
            self._scheme = text.find("://", max(self._start, window - 2), end) >= 0
        had_slash = self._first_slash >= 0
        if not had_slash:
            self._first_slash = text.find("/", window, end)
        if not self._slash_then_other and self._first_slash >= 0:
            # Only "/" has followed the first slash so far, so one non-"/" settles it -
            # anywhere in this window, or anywhere after the slash if the slash is new.
            self._slash_then_other = (
                _NON_SLASH.search(text, window if had_slash else self._first_slash + 1, end)
                is not None
            )


def _url_path_context(text: str, match: re.Match[str]) -> bool:
    """Return whether a numeric candidate sits inside a URL path segment.

    Single-shot form, for a caller holding one match and no line state. `_scan_line` uses
    `_UrlPathContext` directly instead: repeated single-shot calls down one line are the
    quadratic SPEC-287 removed.
    """
    return _UrlPathContext(text).holds(match)


def _canonical_run_id_context(text: str, match: re.Match[str]) -> bool:
    """Return whether a numeric candidate is the timestamp portion of a canonical run ID."""
    start = match.start() - len("run-")
    return start >= 0 and CANONICAL_RUN_ID_PATTERN.fullmatch(text[start : match.end()]) is not None


def _reserved_documentation_domain(value: str) -> bool:
    """Return whether an address sits on a name reserved for documentation (SPEC-198).

    Subdomains count. `mail.example.com` is reserved by the same rule as its parent, and a
    gate that cleared the parent while flagging the child would send the next reader looking
    for a distinction the RFCs do not draw.
    """
    domain = value.rpartition("@")[2].rstrip(".").lower()
    if not domain:
        return False
    if domain.rpartition(".")[2] in RESERVED_EMAIL_TLDS:
        return True
    return any(
        domain == reserved or domain.endswith(f".{reserved}")
        for reserved in RESERVED_EMAIL_DOMAINS
    )


def _valid_pii(matched_class: str, value: str) -> bool:
    if matched_class == "email":
        # SPEC-198: a reserved documentation domain cannot receive mail, so an address
        # there is a false positive - and every git identity fixture in the kit's own
        # test tree is one.
        return not _reserved_documentation_domain(value)
    if matched_class == "ssn":
        area, group, serial = value.split("-")
        return area not in {"000", "666"} and int(area) < 900 and group != "00" and serial != "0000"
    if matched_class == "credit_card":
        digits = re.sub(r"\D", "", value)
        return 13 <= len(digits) <= 19 and _luhn_valid(digits)
    if matched_class == "phone":
        digits = re.sub(r"\D", "", value)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return len(digits) == 10 and len(set(digits)) > 1
    return True


def _luhn_valid(digits: str) -> bool:
    total = 0
    parity = len(digits) % 2
    for idx, char in enumerate(digits):
        digit = int(char)
        if idx % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def _escalations(
    added_lines: int,
    token_cost: int,
    config: ScannerConfig,
    environ: dict[str, str],
) -> list[Escalation]:
    if environ.get(config.signoff_env):
        return []

    escalations: list[Escalation] = []
    if config.diff_risk_threshold and added_lines > config.diff_risk_threshold:
        escalations.append(Escalation("diff_risk", added_lines, config.diff_risk_threshold, config.signoff_env))
    if config.token_cost_threshold and token_cost > config.token_cost_threshold:
        escalations.append(Escalation("token_cost", token_cost, config.token_cost_threshold, config.signoff_env))
    return escalations


def _staged_diff() -> str:
    result = subprocess.run(
        # BUG-013: pin the prefixes and the colouring. diff.noprefix, diff.mnemonicPrefix
        # and color.ui are all repository-local settings that would otherwise change the
        # shape of the headers this parser reads.
        [
            "git",
            "diff",
            "--cached",
            "--unified=0",
            "--no-ext-diff",
            "--no-color",
            "--src-prefix=a/",
            "--dst-prefix=b/",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _print_acknowledge_template(diff_text: str, report: ScanReport) -> None:
    """Print a stanza per blocking PII finding, for a human to complete.

    SPEC-192: locations and digests only, never the matched value - printing the value
    would put PII on the terminal and into whatever the reviewer pastes. `expires` and
    `reason` are left empty on purpose, so an unedited paste is an invalid entry that
    still blocks. Accepting a finding has to cost a sentence and a date.
    """
    blocking = set(report.findings)
    seen: set[str] = set()
    stanzas: list[str] = []
    for location, text in _added_lines(diff_text):
        for finding, digest in _scan_line(text, location):
            if finding.type != "pii" or finding not in blocking or digest in seen:
                continue
            seen.add(digest)
            stanzas.append(
                f"    # {finding.location} - {finding.matched_class}\n"
                f'    - sha256: "{digest}"\n'
                f"      class: {finding.matched_class}\n"
                f"      expires:      # REQUIRED YYYY-MM-DD, at most "
                f"{MAX_ACKNOWLEDGEMENT_DAYS} days ahead\n"
                f'      reason: ""    # REQUIRED, >= {MIN_ACKNOWLEDGEMENT_REASON} '
                f"characters: what you reviewed and why it is safe"
            )

    if not stanzas:
        print("[nightshift scanner] No blocking PII findings to acknowledge.")
        return

    print("# Paste under `git:` in .nightshift/config.yaml, then fill in every field.")
    print("# An unedited stanza is invalid and the finding keeps blocking.")
    print("  pii_acknowledgements:")
    print("\n".join(stanzas))


def _print_report(report: ScanReport) -> None:
    if report.managed_files_exempted:
        print(
            "[nightshift scanner] "
            f"Exempted {report.managed_files_exempted} verified managed payload "
            f"file(s) and {report.managed_added_lines_exempted} added line(s) from "
            "escalation; release-manifest hashes matched.",
            file=sys.stderr,
        )
    if report.archive_files_exempted:
        print(
            "[nightshift scanner] "
            f"Exempted {report.archive_files_exempted} history-verified protocol archive "
            f"snapshot file(s) and {report.archive_added_lines_exempted} added line(s) from escalation.",
            file=sys.stderr,
        )
    if report.managed_files_skipped:
        print(
            f"[nightshift scanner] {report.managed_files_skipped} managed files skipped for PII scanning.",
            file=sys.stderr,
        )
    for problem in report.discarded_acknowledgements:
        print(
            f"[nightshift scanner] Ignoring invalid PII acknowledgement - {problem}",
            file=sys.stderr,
        )
    for problem in report.discarded_fixtures:
        print(
            f"[nightshift scanner] Ignoring invalid fixture registry entry - {problem}",
            file=sys.stderr,
        )
    # SPEC-197 R8: excluded, not silenced. A fixture that has quietly become something else
    # stays visible on every commit, and a reviewer can see how much of a file the gate is
    # not blocking on.
    for finding in report.excluded:
        print(
            f"[nightshift scanner] [kit fixture] {finding.type}: "
            f"{finding.matched_class} at {finding.location}",
            file=sys.stderr,
        )
    for accepted in report.acknowledged:
        print(
            f"[nightshift scanner] [acknowledged] {accepted.finding.matched_class} at "
            f"{accepted.finding.location} — expires {accepted.expires.isoformat()}; "
            f"{accepted.reason}",
            file=sys.stderr,
        )
    if not report.blocked and not report.needs_escalation:
        return
    if report.findings:
        print("[nightshift scanner] Secret/PII finding(s) detected; commit rejected.", file=sys.stderr)
        for finding in report.findings:
            print(
                f"  - {finding.type}: {finding.matched_class} at {finding.location}",
                file=sys.stderr,
            )
        if any(finding.type == "pii" for finding in report.findings):
            print(
                "  Reviewed and safe? Run the same command with --acknowledge-template "
                "and accept that one value. Do not reach for --no-verify: it skips the "
                "secret scan, spec validation, lint and the spec-ID check as well.",
                file=sys.stderr,
            )
    if report.escalations:
        print("[nightshift scanner] Escalation threshold exceeded; explicit sign-off required.", file=sys.stderr)
        for escalation in report.escalations:
            print(
                f"  - {escalation.kind}: {escalation.value} > {escalation.threshold}; "
                f"set {escalation.signoff_env}=1 after Lukasz sign-off",
                file=sys.stderr,
            )


if __name__ == "__main__":
    raise SystemExit(main())
