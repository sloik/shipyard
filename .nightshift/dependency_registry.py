"""Exact, filesystem-backed dependency resolution across Nightshift projects.

The registry is discovery metadata, not an ownership oracle.  Ownership comes
only from finding an exact ``id:`` in a physical spec file under a registered
project path.  This keeps admission deterministic when boards are stopped and
prevents prefix guesses from silently selecting the wrong project.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml


@dataclass(frozen=True)
class ProjectRef:
    name: str
    path: Path
    port: int | None = None


@dataclass(frozen=True)
class SpecRecord:
    spec_id: str
    status: str
    frontmatter: Mapping[str, Any]
    spec_path: Path
    project: ProjectRef

    def public_frontmatter(self) -> dict[str, Any]:
        item = dict(self.frontmatter)
        item.update({
            "id": self.spec_id,
            "status": self.status,
            "_external_project": self.project.name,
            "_external_project_path": str(self.project.path),
            "_external_spec_path": str(self.spec_path),
            "_external_port": self.project.port,
        })
        return item


@dataclass(frozen=True)
class DependencyResolution:
    resolved: Mapping[str, SpecRecord] = field(default_factory=dict)
    errors: Mapping[str, str] = field(default_factory=dict)
    registry_error: str | None = None

    def combined_specs(self, local_specs: Mapping[str, Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
        combined: dict[str, Mapping[str, Any]] = dict(local_specs)
        for spec_id, record in self.resolved.items():
            combined[spec_id] = record.public_frontmatter()
        return combined


def _expand_path(raw_path: str) -> Path:
    home = Path.home()
    argo_home = Path(os.environ.get("ARGO_HOME", home / "Dropbox" / "Argo"))
    expanded = raw_path.replace("{{HOME}}", str(home)).replace("{{ARGO_HOME}}", str(argo_home))
    return Path(os.path.expandvars(os.path.expanduser(expanded))).resolve()


def specs_dir_for_project(project_path: Path) -> Path | None:
    """Return a registered project's standard or flat specs directory."""
    candidates = (
        project_path / ".nightshift" / "specs",
        project_path / "specs",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def _parse_spec(path: Path) -> tuple[str, str, dict[str, Any]] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(frontmatter, dict) or not frontmatter.get("id"):
        return None
    spec_id = str(frontmatter["id"])
    status = str(frontmatter.get("status") or "unknown").lower()
    return spec_id, status, frontmatter


class DependencyRegistryResolver:
    """Resolve exact dependency IDs with a short structural cache."""

    def __init__(
        self,
        specs_dir: Path,
        *,
        registry_path: Path | None = None,
        cache_seconds: float = 5.0,
    ) -> None:
        self.specs_dir = Path(specs_dir).resolve()
        self.registry_path = Path(registry_path).resolve() if registry_path else self.specs_dir.parent / "projects-registry.json"
        self.cache_seconds = max(0.0, cache_seconds)
        self._loaded_at = 0.0
        self._records: dict[str, list[SpecRecord]] = {}
        self._registry_error: str | None = None

    def invalidate(self) -> None:
        self._loaded_at = 0.0

    def resolve(
        self,
        dependency_ids: Iterable[str],
        *,
        local_specs: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> DependencyResolution:
        local_specs = local_specs or {}
        self._refresh_if_stale()
        resolved: dict[str, SpecRecord] = {}
        errors: dict[str, str] = {}
        for spec_id in sorted({str(value) for value in dependency_ids if value}):
            owners = self._records.get(spec_id, [])
            if len(owners) == 1:
                record = owners[0]
                local = local_specs.get(spec_id)
                if local is not None and record.spec_path.parent == self.specs_dir:
                    record = SpecRecord(
                        record.spec_id,
                        str(local.get("status") or record.status).lower(),
                        dict(local),
                        record.spec_path,
                        record.project,
                    )
                resolved[spec_id] = record
            elif len(owners) > 1:
                locations = ", ".join(sorted(str(item.spec_path) for item in owners))
                errors[spec_id] = f"ambiguous dependency {spec_id}: found in {locations}"
            else:
                suffix = f"; registry unavailable: {self._registry_error}" if self._registry_error else ""
                errors[spec_id] = f"unresolved dependency {spec_id}{suffix}"
        return DependencyResolution(resolved, errors, self._registry_error)

    def _refresh_if_stale(self) -> None:
        if self._loaded_at and time.monotonic() - self._loaded_at < self.cache_seconds:
            return
        records: dict[str, list[SpecRecord]] = {}
        projects, registry_error = self._load_projects()
        current = next((project for project in projects if specs_dir_for_project(project.path) == self.specs_dir), None)
        if current is None:
            root = self.specs_dir.parent.parent if self.specs_dir.parent.name == ".nightshift" else self.specs_dir.parent
            current = ProjectRef(root.name.upper(), root)
        scan_targets: list[tuple[ProjectRef, Path]] = [(current, self.specs_dir)]
        scan_targets.extend(
            (project, project_specs)
            for project in projects
            if (project_specs := specs_dir_for_project(project.path)) is not None
        )

        seen_paths: set[Path] = set()
        for project, project_specs in scan_targets:
            for spec_path in sorted(project_specs.glob("*.md")):
                resolved_path = spec_path.resolve()
                if resolved_path in seen_paths:
                    continue
                seen_paths.add(resolved_path)
                parsed = _parse_spec(spec_path)
                if parsed is None:
                    continue
                spec_id, status, frontmatter = parsed
                record = SpecRecord(spec_id, status, frontmatter, resolved_path, project)
                records.setdefault(spec_id, []).append(record)

        self._records = records
        self._registry_error = registry_error
        self._loaded_at = time.monotonic()

    def _load_projects(self) -> tuple[list[ProjectRef], str | None]:
        if not self.registry_path.is_file():
            return [], None
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [], str(exc)
        rows = payload.get("projects") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return [], "projects must be a list"
        projects: list[ProjectRef] = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                continue
            port = row.get("port")
            projects.append(ProjectRef(
                str(row.get("name") or Path(row["path"]).name).upper(),
                _expand_path(row["path"]),
                port if isinstance(port, int) else None,
            ))
        return projects, None
