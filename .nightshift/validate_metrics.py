#!/usr/bin/env python3
"""
Metrics YAML Schema Validator for Nightshift

Validates per-spec YAML metrics files against the Nightshift metrics schema
(defined in LOOP.md step 13 and metrics/_SCHEMA.md).

Exit codes:
  0 — All validated files pass
  1 — One or more files have validation errors

Output: Structured JSON to stdout with per-file results
"""

import json
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


def parse_iso8601(timestamp_str):
    """Parse ISO 8601 timestamp. Returns datetime or None if invalid."""
    if not isinstance(timestamp_str, str):
        return None

    # Try various ISO 8601 formats
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(timestamp_str.replace("+00:00", "Z"), fmt)
        except ValueError:
            continue

    return None


def validate_root_fields(data):
    """Validate root-level required fields."""
    errors = []

    # Required root fields with type checks
    required_fields = {
        "task_id": str,
        "spec_file": str,
        "started_at": str,
        "completed_at": str,
        "status": str,
        "loop_version": str,
        "model": str,
        "harness": str,
        "review_mode": str,
    }

    for field, expected_type in required_fields.items():
        if field not in data:
            errors.append(f"Missing required root field: {field}")
        elif not isinstance(data[field], expected_type):
            errors.append(f"Field '{field}' must be {expected_type.__name__}, got {type(data[field]).__name__}")

    return errors


def validate_timestamps(data):
    """Validate ISO 8601 timestamps and time ordering."""
    errors = []

    started = data.get("started_at")
    completed = data.get("completed_at")

    # Parse and validate started_at
    if started:
        started_dt = parse_iso8601(started)
        if started_dt is None:
            errors.append(f"Invalid timestamp format for 'started_at': {started}")

    # Parse and validate completed_at
    if completed:
        completed_dt = parse_iso8601(completed)
        if completed_dt is None:
            errors.append(f"Invalid timestamp format for 'completed_at': {completed}")

    # Check ordering: completed_at >= started_at
    if started and completed:
        started_dt = parse_iso8601(started)
        completed_dt = parse_iso8601(completed)
        if started_dt and completed_dt and completed_dt < started_dt:
            errors.append(f"completed_at ({completed}) must be >= started_at ({started})")

    return errors


def validate_phases(data):
    """Validate phases section with all required phase subsections."""
    errors = []

    if "phases" not in data:
        errors.append("Missing required section: phases")
        return errors

    phases = data["phases"]
    if not isinstance(phases, dict):
        errors.append("'phases' must be a dictionary")
        return errors

    # Required phase names
    required_phases = [
        "execution_mode",
        "preflight",
        "context_load",
        "test_planning",
        "test_writing",
        "implementation",
        "review",
        "validation",
        "completion_verification",
    ]

    for phase_name in required_phases:
        if phase_name not in phases:
            errors.append(f"Missing required phase: {phase_name}")

    # Validate execution_mode is a string
    if "execution_mode" in phases:
        if not isinstance(phases["execution_mode"], str):
            errors.append("'phases.execution_mode' must be a string")

    # Validate preflight phase fields
    if "preflight" in phases:
        preflight = phases["preflight"]
        if isinstance(preflight, dict):
            for field in ["clean_tree", "initial_tests_pass"]:
                if field in preflight and not isinstance(preflight[field], bool):
                    errors.append(f"'phases.preflight.{field}' must be boolean")
            if "duration_s" in preflight and not isinstance(preflight["duration_s"], (int, float)):
                errors.append("'phases.preflight.duration_s' must be numeric")
            elif "duration_s" in preflight and preflight["duration_s"] < 0:
                errors.append("'phases.preflight.duration_s' cannot be negative")

    # Validate context_load phase fields
    if "context_load" in phases:
        context_load = phases["context_load"]
        if isinstance(context_load, dict):
            for field in ["files_read", "knowledge_entries_used"]:
                if field in context_load and not isinstance(context_load[field], int):
                    errors.append(f"'phases.context_load.{field}' must be integer")
                elif field in context_load and context_load[field] < 0:
                    errors.append(f"'phases.context_load.{field}' cannot be negative")
            if "duration_s" in context_load and not isinstance(context_load["duration_s"], (int, float)):
                errors.append("'phases.context_load.duration_s' must be numeric")
            elif "duration_s" in context_load and context_load["duration_s"] < 0:
                errors.append("'phases.context_load.duration_s' cannot be negative")

    # Validate test_planning phase fields
    if "test_planning" in phases:
        test_planning = phases["test_planning"]
        if isinstance(test_planning, dict):
            if "duration_s" in test_planning and not isinstance(test_planning["duration_s"], (int, float)):
                errors.append("'phases.test_planning.duration_s' must be numeric")
            elif "duration_s" in test_planning and test_planning["duration_s"] < 0:
                errors.append("'phases.test_planning.duration_s' cannot be negative")

    # Validate test_writing phase fields
    if "test_writing" in phases:
        test_writing = phases["test_writing"]
        if isinstance(test_writing, dict):
            for field in ["tests_written", "tests_failing"]:
                if field in test_writing and not isinstance(test_writing[field], int):
                    errors.append(f"'phases.test_writing.{field}' must be integer")
                elif field in test_writing and test_writing[field] < 0:
                    errors.append(f"'phases.test_writing.{field}' cannot be negative")
            if "duration_s" in test_writing and not isinstance(test_writing["duration_s"], (int, float)):
                errors.append("'phases.test_writing.duration_s' must be numeric")
            elif "duration_s" in test_writing and test_writing["duration_s"] < 0:
                errors.append("'phases.test_writing.duration_s' cannot be negative")

    # Validate implementation phase fields
    if "implementation" in phases:
        impl = phases["implementation"]
        if isinstance(impl, dict):
            for field in ["files_created", "files_modified", "lines_added", "lines_removed"]:
                if field in impl and not isinstance(impl[field], int):
                    errors.append(f"'phases.implementation.{field}' must be integer")
                elif field in impl and impl[field] < 0:
                    errors.append(f"'phases.implementation.{field}' cannot be negative")
            if "duration_s" in impl and not isinstance(impl["duration_s"], (int, float)):
                errors.append("'phases.implementation.duration_s' must be numeric")
            elif "duration_s" in impl and impl["duration_s"] < 0:
                errors.append("'phases.implementation.duration_s' cannot be negative")

    # Validate review phase fields
    if "review" in phases:
        review = phases["review"]
        if isinstance(review, dict):
            if "cycles" in review and not isinstance(review["cycles"], int):
                errors.append("'phases.review.cycles' must be integer")
            elif "cycles" in review and review["cycles"] < 0:
                errors.append("'phases.review.cycles' cannot be negative")
            if "issues_found" in review:
                issues = review["issues_found"]
                if not isinstance(issues, list):
                    errors.append("'phases.review.issues_found' must be a list")
                else:
                    for i, issue in enumerate(issues):
                        if isinstance(issue, dict):
                            for field in ["persona", "severity", "description"]:
                                if field not in issue:
                                    errors.append(f"'phases.review.issues_found[{i}]' missing '{field}'")
                            if "resolved" in issue and not isinstance(issue["resolved"], bool):
                                errors.append(f"'phases.review.issues_found[{i}].resolved' must be boolean")

    # Validate validation phase fields
    if "validation" in phases:
        validation = phases["validation"]
        if isinstance(validation, dict):
            if "build_pass" in validation and not isinstance(validation["build_pass"], bool):
                errors.append("'phases.validation.build_pass' must be boolean")
            if "build_errors" in validation and not isinstance(validation["build_errors"], int):
                errors.append("'phases.validation.build_errors' must be integer")
            elif "build_errors" in validation and validation["build_errors"] < 0:
                errors.append("'phases.validation.build_errors' cannot be negative")
            if "test_pass_rate" in validation:
                rate = validation["test_pass_rate"]
                if not isinstance(rate, (int, float)):
                    errors.append("'phases.validation.test_pass_rate' must be numeric (0.0-1.0)")
                elif not (0.0 <= rate <= 1.0):
                    errors.append(f"'phases.validation.test_pass_rate' must be in range [0.0, 1.0], got {rate}")
            for field in ["tests_total", "tests_passed", "lint_errors", "type_errors"]:
                if field in validation and not isinstance(validation[field], int):
                    errors.append(f"'phases.validation.{field}' must be integer")
                elif field in validation and validation[field] < 0:
                    errors.append(f"'phases.validation.{field}' cannot be negative")
            if "duration_s" in validation and not isinstance(validation["duration_s"], (int, float)):
                errors.append("'phases.validation.duration_s' must be numeric")
            elif "duration_s" in validation and validation["duration_s"] < 0:
                errors.append("'phases.validation.duration_s' cannot be negative")

    # Validate completion_verification phase fields
    if "completion_verification" in phases:
        comp_verify = phases["completion_verification"]
        if isinstance(comp_verify, dict):
            for field in ["acceptance_criteria_met", "no_regression"]:
                if field in comp_verify and not isinstance(comp_verify[field], bool):
                    errors.append(f"'phases.completion_verification.{field}' must be boolean")

    # Validate synthesis_gate phase fields (SPEC-028, optional)
    if "synthesis_gate" in phases:
        synthesis_gate = phases["synthesis_gate"]
        if isinstance(synthesis_gate, dict):
            if "triggered" in synthesis_gate and not isinstance(synthesis_gate["triggered"], bool):
                errors.append("'phases.synthesis_gate.triggered' must be boolean")
            if "dependent_specs" in synthesis_gate:
                dependent_specs = synthesis_gate["dependent_specs"]
                if not isinstance(dependent_specs, list) or not all(isinstance(item, str) for item in dependent_specs):
                    errors.append("'phases.synthesis_gate.dependent_specs' must be a list of strings")
            if "interface_validation" in synthesis_gate:
                status = synthesis_gate["interface_validation"]
                if status not in {"passed", "failed"}:
                    errors.append("'phases.synthesis_gate.interface_validation' must be 'passed' or 'failed'")
            for field in ("handoff_artifact_path", "knowledge_pattern_path"):
                if field in synthesis_gate and not isinstance(synthesis_gate[field], str):
                    errors.append(f"'phases.synthesis_gate.{field}' must be a string")
            if "duration_s" in synthesis_gate and not isinstance(synthesis_gate["duration_s"], (int, float)):
                errors.append("'phases.synthesis_gate.duration_s' must be numeric")
            elif "duration_s" in synthesis_gate and synthesis_gate["duration_s"] < 0:
                errors.append("'phases.synthesis_gate.duration_s' cannot be negative")

    return errors


def validate_satisfaction(data):
    """Validate satisfaction section."""
    errors = []

    if "satisfaction" not in data:
        errors.append("Missing required section: satisfaction")
        return errors

    satisfaction = data["satisfaction"]
    if not isinstance(satisfaction, dict):
        errors.append("'satisfaction' must be a dictionary")
        return errors

    # Validate overall_score
    if "overall_score" not in satisfaction:
        errors.append("Missing required field: satisfaction.overall_score")
    else:
        score = satisfaction["overall_score"]
        if not isinstance(score, (int, float)):
            errors.append("'satisfaction.overall_score' must be numeric")
        elif not (0.0 <= score <= 1.0):
            errors.append(f"'satisfaction.overall_score' must be in range [0.0, 1.0], got {score}")

    # Validate classification
    if "classification" not in satisfaction:
        errors.append("Missing required field: satisfaction.classification")
    else:
        classification = satisfaction["classification"]
        if classification not in ["high", "medium", "low"]:
            errors.append(f"'satisfaction.classification' must be one of [high, medium, low], got {classification}")

    # Validate dimensions
    if "dimensions" not in satisfaction:
        errors.append("Missing required section: satisfaction.dimensions")
    else:
        dimensions = satisfaction["dimensions"]
        if not isinstance(dimensions, dict):
            errors.append("'satisfaction.dimensions' must be a dictionary")
        else:
            required_dims = ["tests", "lint", "type_check", "build", "completion_verification", "review"]
            for dim in required_dims:
                if dim not in dimensions:
                    errors.append(f"Missing required dimension: satisfaction.dimensions.{dim}")
                else:
                    dim_data = dimensions[dim]
                    if isinstance(dim_data, dict):
                        if "score" not in dim_data:
                            errors.append(f"Missing 'score' in satisfaction.dimensions.{dim}")
                        else:
                            dim_score = dim_data["score"]
                            if not isinstance(dim_score, (int, float)):
                                errors.append(f"'satisfaction.dimensions.{dim}.score' must be numeric")
                            elif not (0.0 <= dim_score <= 1.0):
                                errors.append(f"'satisfaction.dimensions.{dim}.score' must be in range [0.0, 1.0], got {dim_score}")
                        if "weight" not in dim_data:
                            errors.append(f"Missing 'weight' in satisfaction.dimensions.{dim}")
                        else:
                            weight = dim_data["weight"]
                            if not isinstance(weight, (int, float)):
                                errors.append(f"'satisfaction.dimensions.{dim}.weight' must be numeric")
                            elif weight < 0:
                                errors.append(f"'satisfaction.dimensions.{dim}.weight' cannot be negative")

    return errors


def validate_commit(data):
    """Validate commit section."""
    errors = []

    if "commit" not in data:
        errors.append("Missing required section: commit")
        return errors

    commit = data["commit"]
    if not isinstance(commit, dict):
        errors.append("'commit' must be a dictionary")
        return errors

    for field in ["hash", "message"]:
        if field not in commit:
            errors.append(f"Missing required field: commit.{field}")
        elif not isinstance(commit[field], str):
            errors.append(f"'commit.{field}' must be a string")

    return errors


def validate_knowledge(data):
    """Validate knowledge section (required when status=completed)."""
    errors = []
    status = data.get("status")

    if status == "completed":
        if "knowledge" not in data:
            errors.append("Missing required section 'knowledge' when status=completed")
            return errors

        knowledge = data["knowledge"]
        if not isinstance(knowledge, dict):
            errors.append("'knowledge' must be a dictionary")
            return errors

        required_fields = ["pattern_written", "patterns_injected", "patterns_cited", "citation_rate"]
        for field in required_fields:
            if field not in knowledge:
                errors.append(f"Missing required field: knowledge.{field}")
            else:
                val = knowledge[field]
                if field == "citation_rate":
                    if not isinstance(val, (int, float)):
                        errors.append(f"'knowledge.{field}' must be numeric")
                    elif not (0.0 <= val <= 1.0):
                        errors.append(f"'knowledge.{field}' must be in range [0.0, 1.0], got {val}")
                else:
                    if not isinstance(val, int):
                        errors.append(f"'knowledge.{field}' must be integer")
                    elif val < 0:
                        errors.append(f"'knowledge.{field}' cannot be negative")

    return errors


def validate_failure(data):
    """Validate failure section (required when status != completed)."""
    errors = []
    status = data.get("status")

    if status and status != "completed":
        if "failure" not in data:
            errors.append(f"Missing required section 'failure' when status={status}")
            return errors

        failure = data["failure"]
        if not isinstance(failure, dict):
            errors.append("'failure' must be a dictionary")
            return errors

        required_fields = ["phase", "error_type", "description", "root_cause", "suggestion"]
        for field in required_fields:
            if field not in failure:
                errors.append(f"Missing required field: failure.{field}")
            elif not isinstance(failure[field], str):
                errors.append(f"'failure.{field}' must be a string")

    return errors


def validate_status_enum(data):
    """Validate status enum values."""
    errors = []
    status = data.get("status")

    # Backward compatibility: accept historical "fail" alias as "failed".
    if status == "fail":
        data["raw_status"] = "fail"
        data["status"] = "failed"
        status = "failed"

    valid_statuses = ["completed", "failed", "blocked", "discarded", "partial"]
    if status not in valid_statuses:
        errors.append(f"'status' must be one of {valid_statuses}, got {status}")

    return errors


def validate_resolution(data):
    """Validate the optional parent-authoritative kickoff resolution section."""
    if "resolution" not in data:
        return []
    resolution = data["resolution"]
    if not isinstance(resolution, dict):
        return ["'resolution' must be a dictionary"]

    errors = []
    required = {
        "run_id": str,
        "stage": str,
        "attempt": int,
        "prior_outcome": str,
        "final_outcome": str,
        "evidence_gate": dict,
        "blocker_class": str,
        "blocker_scope": str,
        "unblock_attempts": int,
        "unblock_limit": int,
        "automatic_unblock_succeeded": bool,
        "later_session_required": bool,
        "resolution_latency_s": (int, float),
    }
    for field, expected_type in required.items():
        if field not in resolution:
            errors.append(f"Missing required resolution field: {field}")
            continue
        value = resolution[field]
        if expected_type in (int, (int, float)) and isinstance(value, bool):
            errors.append(f"'resolution.{field}' must be numeric")
        elif not isinstance(value, expected_type):
            expected_name = (
                "numeric" if expected_type == (int, float) else expected_type.__name__
            )
            errors.append(f"'resolution.{field}' must be {expected_name}")

    enums = {
        "stage": {"kickoff_gate", "recovery"},
        "prior_outcome": {"none", "done", "blocked"},
        "final_outcome": {"done", "blocked"},
        "blocker_class": {
            "none",
            "implementation",
            "test_infrastructure",
            "fixture_drift",
            "baseline_regression",
            "external_input",
            "evidence_gap",
            "unknown",
        },
        "blocker_scope": {"none", "in_scope", "out_of_scope", "mixed", "unknown"},
    }
    for field, allowed in enums.items():
        value = resolution.get(field)
        if isinstance(value, str) and value not in allowed:
            errors.append(
                f"'resolution.{field}' must be one of {sorted(allowed)}, got {value}"
            )

    for field in ("attempt", "unblock_attempts", "unblock_limit"):
        value = resolution.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value < 0:
            errors.append(f"'resolution.{field}' cannot be negative")
    if resolution.get("attempt") == 0:
        errors.append("'resolution.attempt' must be at least 1")
    attempts = resolution.get("unblock_attempts")
    limit = resolution.get("unblock_limit")
    if (
        isinstance(attempts, int)
        and not isinstance(attempts, bool)
        and isinstance(limit, int)
        and not isinstance(limit, bool)
        and attempts > limit
    ):
        errors.append("'resolution.unblock_attempts' cannot exceed unblock_limit")
    latency = resolution.get("resolution_latency_s")
    if (
        isinstance(latency, (int, float))
        and not isinstance(latency, bool)
        and latency < 0
    ):
        errors.append("'resolution.resolution_latency_s' cannot be negative")

    gate = resolution.get("evidence_gate")
    if isinstance(gate, dict):
        for field in ("report_exists", "tests_passed", "code_changed", "acs_covered"):
            if field not in gate:
                errors.append(f"Missing required resolution.evidence_gate field: {field}")
            elif gate[field] not in {"pass", "fail", "unknown"}:
                errors.append(
                    f"'resolution.evidence_gate.{field}' must be pass, fail, or unknown"
                )
    return errors


def validate_file(file_path):
    """
    Validate a single metrics YAML file.

    Args:
        file_path: Path to the YAML file

    Returns:
        List of error strings (empty if valid)
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return [f"File not found: {file_path}"]

    if not file_path.suffix.lower() in [".yaml", ".yml"]:
        return [f"File must be YAML (.yaml or .yml), got {file_path.suffix}"]

    try:
        with open(file_path, "r") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [f"YAML parsing error: {e}"]
    except Exception as e:
        return [f"Error reading file: {e}"]

    if data is None:
        return ["File is empty or contains only whitespace"]

    if not isinstance(data, dict):
        return ["File must contain a YAML dictionary at the root level"]

    return validate_metrics_data(data)


def validate_metrics_data(data):
    """Validate an in-memory metrics document."""
    if data is None:
        return ["File is empty or contains only whitespace"]

    if not isinstance(data, dict):
        return ["File must contain a YAML dictionary at the root level"]

    errors = []
    errors.extend(validate_root_fields(data))
    errors.extend(validate_status_enum(data))
    errors.extend(validate_timestamps(data))
    errors.extend(validate_phases(data))
    errors.extend(validate_satisfaction(data))
    errors.extend(validate_commit(data))
    errors.extend(validate_knowledge(data))
    errors.extend(validate_failure(data))
    errors.extend(validate_resolution(data))
    return errors


def validate_directory(directory_path):
    """
    Validate all .yaml/.yml files in a directory.

    Args:
        directory_path: Path to directory containing YAML files

    Returns:
        Dictionary mapping filename -> list of errors
    """
    dir_path = Path(directory_path)

    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {dir_path}")

    results = {}

    # Find all YAML files
    yaml_files = list(dir_path.glob("*.yaml")) + list(dir_path.glob("*.yml"))

    for yaml_file in sorted(yaml_files):
        results[yaml_file.name] = validate_file(yaml_file)

    return results


def main():
    """CLI entry point.

    Usage:
        python3 validate_metrics.py <file_or_directory>
        python3 validate_metrics.py <directory> --fidelity [--events-file PATH] [--format json|markdown]

    ``--fidelity`` runs the plausibility checks from metrics_fidelity.py
    (SPEC-047). Those are warnings, not errors — they never flip exit
    code and never alter the schema-validation output.
    """
    argv = sys.argv[1:]
    if not argv:
        print(
            "Usage: python3 validate_metrics.py <file_or_directory> "
            "[--fidelity [--events-file PATH] [--format json|markdown]]",
            file=sys.stderr,
        )
        sys.exit(1)

    # Pull off the --fidelity flag and its siblings; everything else stays
    # positional so existing call-sites are undisturbed.
    fidelity_mode = False
    events_file: "Path | None" = None
    ranges_path: "Path | None" = None
    fmt = "json"
    positional: list = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--fidelity":
            fidelity_mode = True
        elif arg == "--events-file" and i + 1 < len(argv):
            events_file = Path(argv[i + 1])
            i += 1
        elif arg == "--ranges" and i + 1 < len(argv):
            ranges_path = Path(argv[i + 1])
            i += 1
        elif arg == "--format" and i + 1 < len(argv):
            fmt = argv[i + 1]
            i += 1
        else:
            positional.append(arg)
        i += 1

    if not positional:
        print("Usage: python3 validate_metrics.py <file_or_directory> [--fidelity ...]", file=sys.stderr)
        sys.exit(1)
    path = Path(positional[0])

    if fidelity_mode:
        # SPEC-047: plausibility warnings only. Import lazily so consumers
        # of validate_metrics that never opt in don't pay the cost.
        from metrics_fidelity import check_run_fidelity, render_markdown

        if not path.is_dir():
            print(
                json.dumps({"error": "--fidelity requires a metrics directory"}),
                file=sys.stderr,
            )
            sys.exit(1)
        result = check_run_fidelity(
            path,
            events_file=events_file,
            ranges_path=ranges_path,
        )
        if fmt == "markdown":
            sys.stdout.write(render_markdown(result))
        else:
            json.dump(result.to_dict(), sys.stdout, indent=2, ensure_ascii=False)
            sys.stdout.write("\n")
        sys.exit(0)

    if path.is_dir():
        # Batch mode: validate directory
        try:
            results = validate_directory(path)
        except ValueError as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

        has_errors = any(errors for errors in results.values())

        output = {
            "validated_files": len(results),
            "files_with_errors": sum(1 for errors in results.values() if errors),
            "results": results,
        }

        print(json.dumps(output, indent=2))
        sys.exit(1 if has_errors else 0)

    else:
        # Single file mode
        errors = validate_file(path)

        output = {
            "file": path.name,
            "valid": len(errors) == 0,
            "errors": errors,
        }

        print(json.dumps(output, indent=2))
        sys.exit(0 if len(errors) == 0 else 1)


if __name__ == "__main__":
    main()
