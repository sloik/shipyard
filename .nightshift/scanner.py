"""Secret/PII scanner and commit escalation gate for Nightshift.

The public entry point is :func:`scan_diff`, which returns structured findings
and escalation decisions without requiring git. The CLI wraps it for hooks.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_DIFF_RISK_THRESHOLD = 500
DEFAULT_TOKEN_COST_THRESHOLD = 8_000
DEFAULT_SIGNOFF_ENV = "NIGHTSHIFT_ESCALATION_SIGNOFF"


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
class ScanReport:
    findings: list[Finding]
    escalations: list[Escalation]
    added_lines: int
    token_cost: int

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
        "phone",
        re.compile(r"\b(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b"),
    ),
    (
        "home_address",
        re.compile(
            r"\b\d{1,6}\s+[A-Za-z0-9.' -]+"
            r"\s+(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Lane|Ln\.?|Drive|Dr\.?|"
            r"Boulevard|Blvd\.?|Court|Ct\.?|Way|Place|Pl\.?)\b",
            re.IGNORECASE,
        ),
    ),
]

CANONICAL_RUN_ID_PATTERN = re.compile(r"\brun-\d{4}-\d{2}-\d{2}-\d{6}\b")


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

    return ScannerConfig(
        diff_risk_threshold=_int_value(values.get("diff_risk_threshold"), DEFAULT_DIFF_RISK_THRESHOLD),
        token_cost_threshold=_int_value(values.get("token_cost_threshold"), DEFAULT_TOKEN_COST_THRESHOLD),
        signoff_env=values.get("escalation_signoff_env") or DEFAULT_SIGNOFF_ENV,
    )


def scan_diff(
    diff_text: str,
    *,
    config: ScannerConfig | None = None,
    environ: dict[str, str] | None = None,
) -> ScanReport:
    """Scan added diff lines for secrets/PII and threshold-triggered escalation."""
    cfg = config or ScannerConfig()
    env = environ if environ is not None else dict(os.environ)
    added = list(_added_lines(diff_text))
    findings: list[Finding] = []

    for location, text in added:
        findings.extend(_scan_line(text, location))

    added_text = "\n".join(text for _, text in added)
    token_cost = _estimate_tokens(added_text)
    escalations = _escalations(len(added), token_cost, cfg, env)
    return ScanReport(findings, escalations, len(added), token_cost)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan a git diff for secrets, PII, and escalation thresholds.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--staged", action="store_true", help="scan git diff --cached")
    source.add_argument("--diff-file", type=Path, help="scan a saved diff file")
    parser.add_argument("--config", type=Path, default=Path(".nightshift/config.yaml"))
    args = parser.parse_args(argv)

    diff_text = _staged_diff() if args.staged else args.diff_file.read_text(encoding="utf-8")
    report = scan_diff(diff_text, config=load_config(args.config))
    _print_report(report)
    return 1 if report.blocked or report.needs_escalation else 0


def _int_value(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _added_lines(diff_text: str) -> Iterable[tuple[str, str]]:
    current_file = "<diff>"
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:]
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            new_line = int(match.group(1)) if match else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            location = f"{current_file}:{new_line}" if new_line else current_file
            yield location, raw[1:]
            new_line += 1
            continue
        if raw.startswith("-") and not raw.startswith("---"):
            continue
        if new_line:
            new_line += 1


def _scan_line(text: str, location: str) -> list[Finding]:
    findings: list[Finding] = []
    for matched_class, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(Finding("secret", location, matched_class))
    for matched_class, pattern in PII_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0)
            if matched_class == "credit_card" and _canonical_run_id_context(text, match):
                continue
            if _valid_pii(matched_class, value):
                findings.append(Finding("pii", location, matched_class))
    return findings


def _canonical_run_id_context(text: str, match: re.Match[str]) -> bool:
    """Return whether a numeric candidate is the timestamp portion of a canonical run ID."""
    start = match.start() - len("run-")
    return start >= 0 and CANONICAL_RUN_ID_PATTERN.fullmatch(text[start : match.end()]) is not None


def _valid_pii(matched_class: str, value: str) -> bool:
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
        ["git", "diff", "--cached", "--unified=0", "--no-ext-diff"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _print_report(report: ScanReport) -> None:
    if not report.blocked and not report.needs_escalation:
        return
    if report.findings:
        print("[nightshift scanner] Secret/PII finding(s) detected; commit rejected.", file=sys.stderr)
        for finding in report.findings:
            print(
                f"  - {finding.type}: {finding.matched_class} at {finding.location}",
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
