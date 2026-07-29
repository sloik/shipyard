#!/usr/bin/env python3
"""
SPEC-028 research synthesis gate helpers.

This module implements the conditional Step 9.7 gate for research/analysis
specs that feed direct code dependents. It is intentionally file-based and
deterministic so tests can exercise it with synthetic fixtures only.
"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml


SUPPORTED_RESEARCH_DOMAINS = {"research", "analysis"}
_FORMAT_BY_SUFFIX = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".csv": "csv",
}


class SynthesisGateError(RuntimeError):
    """Raised when Step 9.7 triggers but interface validation fails."""

    def __init__(self, result: Dict[str, Any]):
        self.result = result
        missing = []
        for spec_id, details in result.get("validation_details", {}).items():
            for item in details.get("missing_expectations", []):
                missing.append(f"{spec_id}: {item}")
        summary = "; ".join(missing) or "interface validation failed"
        super().__init__(summary)


@dataclass(frozen=True)
class SpecDocument:
    path: Path
    frontmatter: Dict[str, Any]
    body: str

    @property
    def spec_id(self) -> str:
        return str(self.frontmatter.get("id", self.path.stem))


def _iso8601_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        try:
            Path(tmp_path).unlink()
        except FileNotFoundError:
            pass


def load_spec_document(spec_path: Path) -> SpecDocument:
    text = spec_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{spec_path} is missing YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{spec_path} has malformed YAML frontmatter")
    frontmatter = yaml.safe_load(parts[1]) or {}
    if not isinstance(frontmatter, dict):
        raise ValueError(f"{spec_path} frontmatter is not a mapping")
    return SpecDocument(path=spec_path, frontmatter=frontmatter, body=parts[2].lstrip())


def resolve_domain(frontmatter: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> str:
    config = config or {}
    stacks = config.get("stacks") if isinstance(config.get("stacks"), dict) else {}
    stack_name = frontmatter.get("stack")
    stack_profile = stacks.get(stack_name, {}) if stack_name in stacks else {}
    if not isinstance(stack_profile, dict):
        stack_profile = {}
    runner = config.get("runner") if isinstance(config.get("runner"), dict) else {}

    raw = (
        frontmatter.get("effective_domain")
        or frontmatter.get("domain")
        or stack_profile.get("domain")
        or runner.get("domain")
        or "code"
    )
    value = str(raw).strip().lower()
    return value or "code"


def find_direct_code_dependents(
    current_spec_id: str,
    specs_dir: Path,
    config: Optional[Dict[str, Any]] = None,
) -> List[SpecDocument]:
    dependents: List[SpecDocument] = []
    for spec_path in sorted(specs_dir.glob("*.md")):
        document = load_spec_document(spec_path)
        if document.spec_id == current_spec_id:
            continue
        after = document.frontmatter.get("after") or []
        if not isinstance(after, list):
            continue
        if current_spec_id not in [str(item).strip() for item in after]:
            continue
        if resolve_domain(document.frontmatter, config) == "code":
            dependents.append(document)
    return dependents


def _detect_output_format(output_path: Path, frontmatter: Dict[str, Any]) -> str:
    explicit = str(frontmatter.get("output_type") or "").strip().lower()
    if explicit:
        return explicit
    return _FORMAT_BY_SUFFIX.get(output_path.suffix.lower(), "markdown")


def _normalize_path(path: str) -> str:
    return str(Path(path)).replace("\\", "/")


def _load_output(output_path: Path, output_format: str) -> Tuple[Any, Dict[str, Any]]:
    raw_text = output_path.read_text(encoding="utf-8")
    metadata: Dict[str, Any] = {"raw_text": raw_text}

    if output_format == "json":
        parsed = json.loads(raw_text)
        metadata["keys"] = set(_collect_keys(parsed))
        return parsed, metadata
    if output_format == "yaml":
        parsed = yaml.safe_load(raw_text)
        metadata["keys"] = set(_collect_keys(parsed))
        return parsed, metadata
    if output_format == "csv":
        rows = list(csv.DictReader(raw_text.splitlines()))
        fieldnames = list(rows[0].keys()) if rows else []
        metadata["keys"] = set(fieldnames)
        metadata["rows"] = rows
        return rows, metadata

    headings = []
    for line in raw_text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*$", line)
        if match:
            headings.append(match.group(1).strip().lower())
    metadata["headings"] = headings
    metadata["keys"] = set(headings)
    return raw_text, metadata


def _collect_keys(value: Any, prefix: str = "") -> List[str]:
    keys: List[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_str = str(key)
            full_key = f"{prefix}.{key_str}" if prefix else key_str
            keys.append(key_str.lower())
            keys.append(full_key.lower())
            keys.extend(_collect_keys(nested, full_key))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_collect_keys(item, prefix))
    return keys


def _extract_expected_interfaces(
    dependent: SpecDocument,
    current_output_location: str,
) -> List[str]:
    expectations: List[str] = []
    body = dependent.body

    required_inputs = dependent.frontmatter.get("required_inputs") or []
    if isinstance(required_inputs, list):
        normalized_current = _normalize_path(current_output_location)
        for item in required_inputs:
            if _normalize_path(str(item)) == normalized_current:
                expectations.append("__required_input__")
                break

    patterns = [
        r"`([^`]{1,40})`\s+(?:field|section|header|key)",
        r"`([^`]{1,40})`",
        r'"([^"]{1,40})"\s+(?:field|section|header|key)',
        r"'([^']{1,40})'\s+(?:field|section|header|key)",
        r"(?:field|section|header|key)\s+(?:named|called)?\s*`([^`]{1,40})`",
        r"(?:contains|include|includes|needs|expects)\s+(?:a|an|the)?\s*([A-Za-z0-9_-]{3,40})\s+(?:field|section|header|key)",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, body, flags=re.IGNORECASE):
            token = str(match).strip().strip(".,:; ").lower()
            if token and token not in expectations:
                expectations.append(token)

    lower_body = body.lower()
    for token in ("recommendation", "benchmarks", "decision", "summary", "constraints"):
        if token in lower_body and token not in expectations:
            expectations.append(token)

    return expectations


def _has_interface_token(output_format: str, output_meta: Dict[str, Any], token: str) -> bool:
    if token == "__required_input__":
        return True

    token = token.lower()
    keys = output_meta.get("keys", set())
    if token in keys:
        return True

    if output_format == "markdown":
        headings = output_meta.get("headings", [])
        if any(token in heading for heading in headings):
            return True

    raw_text = str(output_meta.get("raw_text", "")).lower()
    return token in raw_text


def _sentences_from_text(text: str) -> List[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return [part.strip() for part in parts if len(part.strip()) > 20]


def _extract_key_findings(output_format: str, parsed_output: Any, output_meta: Dict[str, Any]) -> List[str]:
    findings: List[str] = []

    def add_candidate(text: str) -> None:
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 12:
            return
        if text and text not in findings:
            findings.append(text.rstrip(".") + ".")

    if output_format in {"json", "yaml"}:
        if isinstance(parsed_output, dict):
            ordered_keys = ("recommendation", "decision", "summary", "key_findings", "constraints", "anti_patterns")
            for key in ordered_keys:
                if key not in parsed_output:
                    continue
                value = parsed_output[key]
                if isinstance(value, list):
                    for item in value:
                        add_candidate(str(item))
                else:
                    add_candidate(f"{key.replace('_', ' ').title()}: {value}")
            for key, value in parsed_output.items():
                if len(findings) >= 7:
                    break
                if isinstance(value, (str, int, float)):
                    add_candidate(f"{key.replace('_', ' ').title()}: {value}")
    elif output_format == "csv":
        rows = output_meta.get("rows", [])
        headers = sorted(output_meta.get("keys", set()))
        if headers:
            add_candidate("CSV output exposes fields: " + ", ".join(headers[:6]))
        for row in rows[:3]:
            if isinstance(row, dict):
                rendered = ", ".join(f"{key}={value}" for key, value in row.items())
                add_candidate(rendered)
    else:
        raw_text = str(output_meta.get("raw_text", ""))
        for heading in output_meta.get("headings", [])[:3]:
            add_candidate(f"Section present: {heading}.")
        for sentence in _sentences_from_text(raw_text):
            add_candidate(sentence)
            if len(findings) >= 7:
                break

    if len(findings) < 3:
        raw_text = str(output_meta.get("raw_text", ""))
        for sentence in _sentences_from_text(raw_text):
            add_candidate(sentence)
            if len(findings) >= 3:
                break

    return findings[:7]


def _derive_confidence(interface_validation: str, findings: Sequence[str], dependent_count: int) -> str:
    if interface_validation == "failed":
        return "low"
    if len(findings) >= 4 and dependent_count >= 1:
        return "high"
    return "medium"


def _build_pattern_text(
    spec_id: str,
    domain: str,
    output_location: str,
    findings: Sequence[str],
    validation_details: Dict[str, Any],
) -> str:
    decision = findings[0] if findings else "Decision was not confidently extracted from the artifact."
    constraints = list(findings[1:3])
    if not constraints:
        constraints = ["Respect the downstream interface documented in the dependent specs."]

    anti_patterns: List[str] = []
    for spec_name, details in validation_details.items():
        for missing in details.get("missing_expectations", []):
            anti_patterns.append(f"Avoid shipping output that omits `{missing}` required by {spec_name}.")
    if not anti_patterns:
        anti_patterns.append("Avoid forcing downstream code specs to parse the full artifact ad hoc.")

    lines = [
        "---",
        f"pattern: {spec_id} synthesis findings",
        f"source_spec: {spec_id}",
        f"domain: {domain}",
        f"created: {datetime.now(timezone.utc).date().isoformat()}",
        "---",
        "",
        "## Decision",
        decision,
        "",
        "## Key Constraints",
    ]
    lines.extend(f"- {item}" for item in constraints[:2])
    lines.extend([
        "",
        "## Anti-Patterns",
    ])
    lines.extend(f"- {item}" for item in anti_patterns[:2])
    lines.extend([
        "",
        "## Full Artifact",
        f"See: {output_location}",
    ])
    return "\n".join(lines[:49]) + "\n"


def _relpath(path: Path, project_root: Path) -> str:
    return path.relative_to(project_root).as_posix()


def run_synthesis_gate(
    *,
    spec_path: Path,
    specs_dir: Path,
    project_root: Path,
    config: Optional[Dict[str, Any]] = None,
    now: Optional[str] = None,
    write_artifacts: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Execute the Step 9.7 synthesis gate.

    Returns ``None`` when the gate should silently skip. Returns a metrics-like
    result payload when triggered. Raises ``SynthesisGateError`` after writing
    artifacts when interface validation fails.
    """
    started = datetime.now(timezone.utc)
    current = load_spec_document(spec_path)
    current_domain = resolve_domain(current.frontmatter, config)
    if current_domain not in SUPPORTED_RESEARCH_DOMAINS:
        return None

    output_location = current.frontmatter.get("output_artifact")
    if not output_location:
        return None

    dependents = find_direct_code_dependents(current.spec_id, specs_dir, config)
    if not dependents:
        return None

    output_path = project_root / str(output_location)
    output_format = _detect_output_format(output_path, current.frontmatter)

    validation_details: Dict[str, Any] = {}
    missing_any = False
    parse_error = None
    parsed_output: Any = None
    output_meta: Dict[str, Any] = {"raw_text": ""}

    output_exists = output_path.exists()
    output_parseable = output_exists
    if output_exists:
        try:
            parsed_output, output_meta = _load_output(output_path, output_format)
        except Exception as exc:  # pragma: no cover - exercised through tests
            output_parseable = False
            parse_error = str(exc)
    else:
        output_parseable = False

    for dependent in dependents:
        expectations = _extract_expected_interfaces(dependent, str(output_location))
        missing: List[str] = []

        if not output_exists:
            missing.append("output_artifact")
        elif not output_parseable:
            missing.append("parseable_output")

        for token in expectations:
            if token == "__required_input__":
                continue
            if not output_parseable or not _has_interface_token(output_format, output_meta, token):
                missing.append(token)

        status = "passed" if not missing else "failed"
        if missing:
            missing_any = True

        validation_details[dependent.spec_id] = {
            "status": status,
            "expects_current_output": "__required_input__" in expectations,
            "required_inputs": dependent.frontmatter.get("required_inputs", []),
            "expected_interfaces": [token for token in expectations if token != "__required_input__"],
            "missing_expectations": missing,
            "output_exists": output_exists,
            "output_parseable": output_parseable,
            "parse_error": parse_error,
        }

    findings = _extract_key_findings(output_format, parsed_output, output_meta) if output_parseable else []
    interface_validation = "failed" if missing_any else "passed"
    timestamp = now or _iso8601_now()

    handoff_path = project_root / "knowledge" / "handoffs" / f"{current.spec_id}.json"
    pattern_path = project_root / "knowledge" / "patterns" / f"{current.spec_id}-findings.md"

    handoff_payload = {
        "spec_id": current.spec_id,
        "domain": current_domain,
        "output_location": str(output_location),
        "output_format": output_format,
        "key_findings": findings[:7],
        "confidence": _derive_confidence(interface_validation, findings, len(dependents)),
        "dependent_specs": [doc.spec_id for doc in dependents],
        "interface_validation": interface_validation,
        "validation_details": validation_details,
        "timestamp": timestamp,
    }

    pattern_text = _build_pattern_text(
        current.spec_id,
        current_domain,
        str(output_location),
        findings,
        validation_details,
    )

    if write_artifacts:
        _atomic_write_text(handoff_path, json.dumps(handoff_payload, indent=2) + "\n")
        _atomic_write_text(pattern_path, pattern_text)

    elapsed = round((datetime.now(timezone.utc) - started).total_seconds(), 3)
    result = {
        "triggered": True,
        "dependent_specs": [doc.spec_id for doc in dependents],
        "interface_validation": interface_validation,
        "handoff_artifact_path": _relpath(handoff_path, project_root),
        "knowledge_pattern_path": _relpath(pattern_path, project_root),
        "duration_s": elapsed,
        "validation_details": validation_details,
        "blocking_issue": (
            "Missing downstream expectations: "
            + ", ".join(
                f"{spec_id} -> {', '.join(details['missing_expectations'])}"
                for spec_id, details in validation_details.items()
                if details["missing_expectations"]
            )
            if missing_any
            else None
        ),
    }

    if interface_validation == "failed":
        raise SynthesisGateError(result)

    return result
