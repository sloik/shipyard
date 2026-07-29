#!/usr/bin/env python3
"""SPEC-053: Base fingerprints for safe source-of-truth writes."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Fingerprint:
    path: str
    sha256: str
    size_bytes: int
    mtime_ns: int
    captured_at: str
    owner: str
    purpose: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint_file(path: Path, *, owner: str, purpose: str) -> Fingerprint:
    stat = path.stat()
    return Fingerprint(
        path=str(path),
        sha256=sha256_file(path),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        captured_at=now_iso(),
        owner=owner,
        purpose=purpose,
    )


def capture_fingerprints(paths: Iterable[Path], metadata_path: Path, *, owner: str, purpose: str) -> list[Fingerprint]:
    fingerprints = [fingerprint_file(Path(path), owner=owner, purpose=purpose) for path in paths]
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
    tmp.write_text(json.dumps({"captured_at": now_iso(), "files": [asdict(fp) for fp in fingerprints]}, indent=2), encoding="utf-8")
    os.replace(tmp, metadata_path)
    return fingerprints


def load_metadata(metadata_path: Path) -> dict:
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def validate_metadata(metadata_path: Path) -> list[str]:
    errors = []
    try:
        data = load_metadata(metadata_path)
    except Exception as exc:
        return [f"cannot read fingerprint metadata: {exc}"]
    if not isinstance(data.get("files"), list):
        return ["fingerprint metadata missing files list"]
    required = {"path", "sha256", "size_bytes", "mtime_ns", "captured_at", "owner", "purpose"}
    for idx, item in enumerate(data["files"]):
        missing = required - set(item or {})
        if missing:
            errors.append(f"files[{idx}] missing keys: {', '.join(sorted(missing))}")
        elif not Path(item["path"]).exists():
            errors.append(f"files[{idx}] path missing: {item['path']}")
    return errors


def _find_entry(metadata: dict, target: Path) -> dict | None:
    resolved = str(target)
    for item in metadata.get("files", []):
        if item.get("path") == resolved:
            return item
    # tolerate absolute resolution changes
    target_abs = str(target.resolve()) if target.exists() else str(target)
    for item in metadata.get("files", []):
        try:
            if str(Path(item.get("path", "")).resolve()) == target_abs:
                return item
        except OSError:
            continue
    return None


def verify_fingerprint(metadata_path: Path, target: Path) -> tuple[bool, dict]:
    metadata = load_metadata(metadata_path)
    entry = _find_entry(metadata, target)
    if entry is None:
        return False, {
            "owner": "source_fingerprints",
            "risk": "guarded write has no captured base fingerprint",
            "evidence": str(target),
            "suggested_fix": "Capture fingerprints before attempting this source-of-truth write.",
        }
    if not target.exists():
        return False, {
            "owner": entry.get("owner", "source_fingerprints"),
            "risk": "guarded target is missing",
            "evidence": str(target),
            "suggested_fix": "Recreate the file or refresh the fingerprint metadata.",
        }
    actual = sha256_file(target)
    if actual != entry.get("sha256"):
        return False, {
            "owner": entry.get("owner", "source_fingerprints"),
            "risk": "source-of-truth changed since this run captured its base",
            "expected_hash": entry.get("sha256"),
            "actual_hash": actual,
            "evidence": str(target),
            "suggested_fix": "Re-read the live file, reconcile changes, then recapture fingerprints before writing.",
        }
    return True, {"owner": entry.get("owner"), "evidence": str(target)}


def _atomic_write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def guarded_write_text(target: Path, text: str, *, metadata_path: Path, override_reason_file: Path | None = None, report_path: Path | None = None) -> tuple[bool, dict]:
    ok, detail = verify_fingerprint(metadata_path, target)
    if not ok:
        if not override_reason_file or not override_reason_file.exists():
            return False, detail
        reason = override_reason_file.read_text(encoding="utf-8").strip()
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with report_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n## Source Fingerprint Override\n\n- File: `{target}`\n- Reason: {reason}\n")
        detail = {**detail, "override_reason": reason}
    _atomic_write_text(target, text)
    return True, detail


def guarded_transform_text(target: Path, transform: Callable[[str], str], *, metadata_path: Path, override_reason_file: Path | None = None, report_path: Path | None = None) -> tuple[bool, dict]:
    before = target.read_text(encoding="utf-8")
    return guarded_write_text(target, transform(before), metadata_path=metadata_path, override_reason_file=override_reason_file, report_path=report_path)
