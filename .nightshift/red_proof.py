#!/usr/bin/env python3
"""Record and mechanically re-assert durable pre-fix red-test evidence.

A red proof belongs to the exact test bytes that were executed against a named
baseline.  Later, post-fix integration must not recreate the old implementation.
It can only confirm that the committed evidence still names the same test bytes
and exact failures, then identify the result honestly as inherited evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = "1.0.0"
STATUS_REASSERTED = "reasserted"
STATUS_NOT_RE_DERIVABLE = "not_re_derivable"


class RedProofError(ValueError):
    """The requested proof artifact is malformed or unsafe to create."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _contained_file(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise RedProofError("test_file must be a non-empty repository-relative path")
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate == root or root not in candidate.parents:
        raise RedProofError("test_file escapes the repository root")
    if not candidate.is_file():
        raise RedProofError(f"test_file does not exist: {relative}")
    return candidate


def _non_empty_strings(values: Sequence[str], field: str) -> list[str]:
    normalized = [value.strip() for value in values]
    if not normalized or any(not value for value in normalized):
        raise RedProofError(f"{field} must contain one or more non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise RedProofError(f"{field} must not contain duplicates")
    return sorted(normalized)


def build_proof(
    *, root: Path, spec_id: str, baseline_revision: str,
    test_file: str, failing_test_names: Sequence[str],
) -> dict[str, Any]:
    """Build the canonical artifact payload from one observed red run."""
    spec_id = spec_id.strip()
    baseline_revision = baseline_revision.strip()
    if not spec_id:
        raise RedProofError("spec_id must be non-empty")
    if not baseline_revision:
        raise RedProofError("baseline_revision must be non-empty")
    test_path = _contained_file(root, test_file)
    failures = _non_empty_strings(failing_test_names, "failing_test_names")
    return {
        "schema_version": SCHEMA_VERSION,
        "spec_id": spec_id,
        "baseline_revision": baseline_revision,
        "test_file": {
            "path": Path(test_file).as_posix(),
            "sha256": _sha256(test_path),
        },
        "failing_test_names": failures,
        "observed_failure_count": len(failures),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def record_proof(
    *, root: Path, artifact: Path, spec_id: str, baseline_revision: str,
    test_file: str, failing_test_names: Sequence[str],
) -> dict[str, Any]:
    payload = build_proof(
        root=root,
        spec_id=spec_id,
        baseline_revision=baseline_revision,
        test_file=test_file,
        failing_test_names=failing_test_names,
    )
    _atomic_write_json(artifact, payload)
    return payload


def load_proof(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RedProofError(f"red-proof artifact is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise RedProofError("red-proof artifact must be a JSON object")
    required = {
        "schema_version", "spec_id", "baseline_revision", "test_file",
        "failing_test_names", "observed_failure_count",
    }
    if set(payload) != required:
        raise RedProofError("red-proof artifact has an unexpected field set")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise RedProofError("unsupported red-proof schema_version")
    for field in ("spec_id", "baseline_revision"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise RedProofError(f"{field} must be a non-empty string")
    test_file = payload["test_file"]
    if not isinstance(test_file, dict) or set(test_file) != {"path", "sha256"}:
        raise RedProofError("test_file must contain exactly path and sha256")
    if not isinstance(test_file["path"], str) or not test_file["path"]:
        raise RedProofError("test_file.path must be non-empty")
    digest = test_file["sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise RedProofError("test_file.sha256 must be a lowercase SHA-256")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise RedProofError("test_file.sha256 must be a lowercase SHA-256") from exc
    if digest != digest.lower():
        raise RedProofError("test_file.sha256 must be a lowercase SHA-256")
    failures = payload["failing_test_names"]
    if not isinstance(failures, list) or not all(isinstance(item, str) for item in failures):
        raise RedProofError("failing_test_names must be a JSON string array")
    checked = _non_empty_strings(failures, "failing_test_names")
    if checked != failures:
        raise RedProofError("failing_test_names must be unique and sorted")
    if payload["observed_failure_count"] != len(failures):
        raise RedProofError("observed_failure_count does not match failing_test_names")
    return payload


def reassert_proof(
    *, root: Path, artifact: Path, result_path: Path | None = None,
) -> dict[str, Any]:
    """Re-assert artifact identity without executing or reconstructing old code.

    A changed/missing test is an honest evidence result, not a controller error,
    so it returns ``not_re_derivable`` rather than raising.
    """
    proof = load_proof(artifact)
    base = {
        "schema_version": SCHEMA_VERSION,
        "spec_id": proof["spec_id"],
        "baseline_revision": proof["baseline_revision"],
        "failing_test_names": proof["failing_test_names"],
        "red_execution_performed": False,
        "code_reverted": False,
    }
    try:
        test_path = _contained_file(root, proof["test_file"]["path"])
    except RedProofError as exc:
        result = {
            **base,
            "status": STATUS_NOT_RE_DERIVABLE,
            "evidence_mode": "unavailable",
            "reason": str(exc),
        }
        if result_path is not None:
            _atomic_write_json(result_path, result)
        return result
    observed = _sha256(test_path)
    expected = proof["test_file"]["sha256"]
    if observed != expected:
        result = {
            **base,
            "status": STATUS_NOT_RE_DERIVABLE,
            "evidence_mode": "unavailable",
            "reason": "test_file_content_hash_changed",
            "expected_test_file_sha256": expected,
            "observed_test_file_sha256": observed,
        }
        if result_path is not None:
            _atomic_write_json(result_path, result)
        return result
    result = {
        **base,
        "status": STATUS_REASSERTED,
        "evidence_mode": "inherited_committed_artifact",
        "reason": "current_test_file_matches_recorded_red_proof",
        "test_file": proof["test_file"],
    }
    if result_path is not None:
        _atomic_write_json(result_path, result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record")
    record.add_argument("--root", type=Path, default=Path.cwd())
    record.add_argument("--artifact", type=Path, required=True)
    record.add_argument("--spec-id", required=True)
    record.add_argument("--baseline-revision", required=True)
    record.add_argument("--test-file", required=True)
    record.add_argument("--failing-test", action="append", required=True)
    reassert = subparsers.add_parser("reassert")
    reassert.add_argument("--root", type=Path, default=Path.cwd())
    reassert.add_argument("--artifact", type=Path, required=True)
    reassert.add_argument("--result", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "record":
            result = record_proof(
                root=args.root,
                artifact=args.artifact,
                spec_id=args.spec_id,
                baseline_revision=args.baseline_revision,
                test_file=args.test_file,
                failing_test_names=args.failing_test,
            )
        else:
            result = reassert_proof(
                root=args.root, artifact=args.artifact, result_path=args.result,
            )
    except RedProofError as exc:
        print(json.dumps({"status": "invalid_artifact", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
