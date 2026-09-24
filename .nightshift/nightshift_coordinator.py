#!/usr/bin/env python3
"""
Nightshift Phase 1 Coordinator — /nightshift run implementation

Orchestrates the delegation of specs to implementation agents, manages context
pointers, handles gap reports, validates post-merge, and records coordinator
metrics. This is the authoritative entry point for spec execution when Argo
invokes /nightshift run.

Key responsibilities:
1. Pre-flight checks (spec readiness, git state, config validity)
2. Context pointer assembly (DevKB, .argo/, Cortex pointers, knowledge/)
3. Implementation agent brief generation
4. Agent delegation (via Agent tool)
5. Outcome handling (success → post-merge validation, gap → report, failure → log)
6. Coordinator-level metrics recording

Exit codes:
  0 — All specs completed (success or documented gap)
  1 — Pre-flight check failed
  2 — Implementation agent failed (not gap report)
  3 — Post-merge validation failed
"""

import json
import re
import sys
import hashlib
import time
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Optional, Tuple
import subprocess
import yaml

from parallel_executor import (
    BoundedWorktreeDispatcher,
    ReleaseSurfaceLease,
    SerializedIntegrationQueue,
    TrackedTerminalFrontmatterProjector,
    WorktreeHandle,
    parallel_worker_limit,
)
from integration_broker import (
    DurableIntegrationReceiptAdapter,
    IntegrationBroker,
    IntegrationBrokerFeedbackAdapter,
)
import deployment_tiers
from spec_artifacts import reports_root_for_spec_path
from spec_frontmatter import parse_spec_file
from status_store import StatusStore
from worktree_janitor import run_startup_janitor
from verifier_feedback import (
    FeedbackRuntimeAdapter,
    FeedbackState,
    FeedbackValidationError,
    reconcile_feedback,
    validate_verifier_verdict,
)
import managed_payload_provenance
from verification_report import candidate_revision_digest, validate_dispatch_identity

try:
    from preflight import run_install_admission
except Exception:  # pragma: no cover - deployed install may be incomplete
    run_install_admission = None  # type: ignore[assignment]

try:
    from jsonschema import ValidationError as JsonSchemaValidationError
    from jsonschema import validate as jsonschema_validate
except ImportError:
    JsonSchemaValidationError = None
    jsonschema_validate = None

try:
    import yaml
except ImportError:
    print("Error: PyYAML required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


class CoordinatorError(Exception):
    """Raised when coordinator encounters unrecoverable error."""
    pass


class SpecReadyError(Exception):
    """Raised when a spec is not ready to run."""
    pass


class GitError(Exception):
    """Raised when git operations fail."""
    pass


class SpecContractError(CoordinatorError):
    """Raised when a spec's required input or output artifact contract fails."""

    def __init__(self, message: str, *, status: str, error_type: str):
        super().__init__(message)
        self.status = status
        self.error_type = error_type


class ValidationError(CoordinatorError):
    """Raised when post-merge or cross-stack integration validation fails."""


class ManagedPayloadIntegrityError(CoordinatorError):
    """Raised when the admitted control-plane payload cannot be accepted."""


class RunTokenCeilingExceeded(CoordinatorError):
    """A run spent more tokens than its configured refusal ceiling."""


DEFAULT_RUN_TOKEN_CEILING = 90_000_000
_TOKEN_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def run_token_ceiling(config: Dict[str, Any]) -> int:
    """Read a positive per-run ceiling, retaining the measured default on bad input."""
    value = config.get("run_token_ceiling", DEFAULT_RUN_TOKEN_CEILING)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return DEFAULT_RUN_TOKEN_CEILING


def observed_token_spend(agent_result: Dict[str, Any]) -> int:
    """Sum provider-reported token fields without inspecting prompt content."""
    usage = agent_result.get("tokens_used", 0)
    if isinstance(usage, dict):
        return sum(max(0, int(usage.get(field, 0) or 0)) for field in _TOKEN_USAGE_FIELDS)
    try:
        return max(0, int(usage))
    except (TypeError, ValueError):
        return 0


class ExactSubstepCache:
    """Exact input-hash cache for deterministic, idempotent coordinator sub-steps."""

    NEVER_CACHE_LABELS = {
        'gating_test',
        'gating_tests',
        'test',
        'tests',
        'build',
        'validation',
        'post_merge_validation',
        'integration_gate',
    }

    def __init__(self, max_entries: int = 128):
        self.max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[str, Any] = OrderedDict()
        self.hits = 0
        self.misses = 0
        self.bypasses = 0

    @staticmethod
    def input_hash(inputs: Any) -> str:
        payload = json.dumps(inputs, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def is_cacheable(cls, label: str, *, volatile: bool = False, cacheable: bool = True) -> bool:
        if volatile or not cacheable:
            return False
        normalized = label.strip().lower().replace(" ", "_").replace("-", "_")
        return normalized not in cls.NEVER_CACHE_LABELS and not normalized.endswith("_test_run")

    def get_or_compute(
        self,
        label: str,
        inputs: Any,
        compute: Callable[[], Any],
        *,
        volatile: bool = False,
        cacheable: bool = True,
    ) -> Any:
        """Return cached result only when the full input hash and label match exactly."""
        if not self.is_cacheable(label, volatile=volatile, cacheable=cacheable):
            self.bypasses += 1
            return compute()

        key = f"{label}:{self.input_hash(inputs)}"
        if key in self._entries:
            self.hits += 1
            self._entries.move_to_end(key)
            return self._entries[key]

        self.misses += 1
        result = compute()
        self._entries[key] = result
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return result


def iso8601_now() -> str:
    """Return current timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def normalize_command(command: Any) -> Optional[str]:
    """Normalize config command values to executable strings."""
    if command is None:
        return None
    if not isinstance(command, str):
        command = str(command)
    command = command.strip()
    return command or None


def normalize_relative_path(path_value: Optional[str]) -> str:
    """Normalize project-relative paths for stack-root comparisons."""
    if path_value is None:
        return ""
    return str(path_value).replace("\\", "/").strip().strip("/")


def path_matches_root(path_value: str, root_value: Optional[str]) -> bool:
    """Return True when a relative file path falls under the given stack root."""
    root = normalize_relative_path(root_value or ".")
    path = normalize_relative_path(path_value)
    if root in ("", "."):
        return True
    return path == root or path.startswith(f"{root}/")


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load a mapping YAML stream, merging documents in source order.

    Nightshift's shipped ``config.yaml`` uses ``---`` section separators. This
    helper remains safe for ordinary single-document YAML and preserves the
    existing CoordinatorError behavior for malformed input.
    """
    try:
        with open(path) as f:
            data: Dict[str, Any] = {}
            for document in yaml.safe_load_all(f):
                if isinstance(document, dict):
                    data.update(document)
        return data
    except yaml.YAMLError as e:
        raise CoordinatorError(f"YAML parse error in {path}: {e}")
    except FileNotFoundError:
        raise CoordinatorError(f"File not found: {path}")


def save_yaml(data: Dict[str, Any], path: Path) -> None:
    """Save dict as YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def git_is_clean(project_root: Path) -> bool:
    """Check if git tree is clean (no uncommitted changes)."""
    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0 and not result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def git_get_branch() -> Optional[str]:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def read_spec_frontmatter(spec_file: Path) -> Tuple[Dict[str, Any], str]:
    """
    Read spec file and extract frontmatter + status.
    Returns: (frontmatter_dict, status_value)
    Raises: CoordinatorError if spec is malformed
    """
    try:
        with open(spec_file) as f:
            content = f.read()
    except FileNotFoundError:
        raise CoordinatorError(f"Spec file not found: {spec_file}")

    # Extract YAML frontmatter
    if not content.startswith('---'):
        raise CoordinatorError(f"Spec {spec_file} has no frontmatter")

    parts = content.split('---', 2)
    if len(parts) < 3:
        raise CoordinatorError(f"Spec {spec_file} malformed frontmatter")

    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        raise CoordinatorError(f"YAML parse error in {spec_file}: {e}")

    if not isinstance(frontmatter, dict):
        raise CoordinatorError(f"Spec {spec_file} frontmatter is not a dict")

    status = frontmatter.get('status', 'unknown')
    return frontmatter, status


def extract_required_inputs(frontmatter: Dict[str, Any]) -> List[str]:
    """Return required input paths from top-level or nested context frontmatter."""
    values: List[str] = []

    top_level = frontmatter.get('required_inputs')
    if isinstance(top_level, list):
        values.extend(item for item in top_level if isinstance(item, str) and item.strip())

    context = frontmatter.get('context')
    if isinstance(context, dict):
        nested = context.get('required_inputs')
        if isinstance(nested, list):
            values.extend(item for item in nested if isinstance(item, str) and item.strip())

    seen = set()
    deduped: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _load_schema_document(path: Path) -> Any:
    """Load a JSON or YAML document from disk."""
    suffix = path.suffix.lower()
    text = path.read_text(encoding='utf-8')
    if suffix == '.json':
        return json.loads(text)
    return yaml.safe_load(text)


def update_spec_status(
    spec_file: Path,
    *,
    status: str,
    message: str,
    error_type: Optional[str] = None,
) -> None:
    """Persist a status transition and failure context back to the spec frontmatter."""
    from spec_frontmatter import write_spec_frontmatter

    def mutate(frontmatter: Dict[str, Any]) -> Dict[str, Any]:
        frontmatter['status'] = status
        frontmatter['blocked_reason' if status == 'blocked' else 'failure_reason'] = message
        if status != 'blocked':
            frontmatter.pop('blocked_reason', None)
        if status != 'failed':
            frontmatter.pop('failure_reason', None)
        if error_type:
            frontmatter['error_type'] = error_type
        else:
            frontmatter.pop('error_type', None)
        return frontmatter

    write_spec_frontmatter(spec_file, mutate)


def set_spec_status(spec_file: Path, status: str) -> None:
    """Persist a bare status transition without failure metadata."""
    from spec_frontmatter import write_spec_frontmatter

    def mutate(frontmatter: Dict[str, Any]) -> Dict[str, Any]:
        frontmatter['status'] = status
        frontmatter.pop('blocked_reason', None)
        frontmatter.pop('failure_reason', None)
        frontmatter.pop('error_type', None)
        return frontmatter

    write_spec_frontmatter(spec_file, mutate)


def verify_required_inputs(project_root: Path, frontmatter: Dict[str, Any]) -> List[Path]:
    """Ensure required input files exist before a spec launches."""
    required_inputs = extract_required_inputs(frontmatter)
    resolved: List[Path] = []

    for rel_path in required_inputs:
        path = project_root / rel_path
        if not path.exists():
            raise SpecContractError(
                f"required_inputs file not found: '{rel_path}'",
                status='blocked',
                error_type='required_inputs_missing',
            )
        resolved.append(path)

    return resolved


def load_required_input_context(project_root: Path, frontmatter: Dict[str, Any]) -> List[Dict[str, str]]:
    """Load required input file contents for injection into the implementation brief."""
    payloads: List[Dict[str, str]] = []
    for path in verify_required_inputs(project_root, frontmatter):
        payloads.append(
            {
                'path': str(path.relative_to(project_root)),
                'content': path.read_text(encoding='utf-8'),
            }
        )
    return payloads


def verify_output_artifact(project_root: Path, frontmatter: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Verify a declared output artifact exists and optionally matches its schema."""
    rel_artifact = frontmatter.get('output_artifact')
    if not rel_artifact:
        return None

    artifact_path = project_root / rel_artifact
    if not artifact_path.exists():
        raise SpecContractError(
            f"output_artifact declared at '{rel_artifact}' but file was not produced",
            status='failed',
            error_type='output_artifact_missing',
        )

    result: Dict[str, Any] = {
        'output_artifact': rel_artifact,
        'exists': True,
    }

    rel_schema = frontmatter.get('output_schema')
    if not rel_schema:
        return result

    artifact_suffix = artifact_path.suffix.lower()
    if artifact_suffix not in {'.json', '.yaml', '.yml'}:
        result['schema_validation'] = 'skipped_unsupported_format'
        return result

    if jsonschema_validate is None:
        raise CoordinatorError(
            "jsonschema is required to validate output_schema for JSON/YAML artifacts. "
            "Install it with: pip install jsonschema"
        )

    schema_path = project_root / rel_schema
    schema = _load_schema_document(schema_path)
    payload = _load_schema_document(artifact_path)

    try:
        jsonschema_validate(instance=payload, schema=schema)
    except JsonSchemaValidationError as exc:
        raise SpecContractError(
            f"output_artifact schema validation failed for '{rel_artifact}': {exc.message}",
            status='failed',
            error_type='output_artifact_schema_mismatch',
        ) from exc

    result['schema_validation'] = 'passed'
    result['output_schema'] = rel_schema
    return result


def validate_spec_readiness(spec_file: Path, spec_id: str) -> None:
    """
    Validate that a spec is ready to run.
    Raises SpecReadyError if not ready.
    """
    frontmatter, status = read_spec_frontmatter(spec_file)

    # Status must be 'ready'
    if status != 'ready':
        raise SpecReadyError(f"Spec {spec_id} status is '{status}', not 'ready'")

    # Verify required frontmatter fields
    required = ['id', 'priority', 'layer', 'type', 'status', 'created']
    for field in required:
        if field not in frontmatter:
            raise SpecReadyError(f"Spec {spec_id} missing frontmatter field: {field}")

    # WARNING (non-blocking): check template_version
    template_version = frontmatter.get('template_version')
    if template_version != 2:
        print(f"WARNING: Spec {spec_id} does not have template_version: 2 "
              f"(found: {template_version}). Consider migrating to spec template v2.")


# SPEC-373: directory-scoped context folder names, preferred name first.
CONTEXT_FOLDER_NAMES = ('.agent-context', '.argo')


class ContextPointerAssembler:
    """Builds context pointer list for implementation agent."""

    def __init__(self, project_root: Path, config: Dict[str, Any], spec: Dict[str, Any], argo_home: Path):
        self.project_root = project_root
        self.config = config
        self.spec = spec
        self.argo_home = argo_home

    def assemble(self) -> Dict[str, Any]:
        """Assemble full context pointer list."""
        return {
            'devkb': self._devkb_pointers(),
            'argo_folders': self._argo_folder_pointers(),
            'cortex': self._cortex_pointers(),
            'knowledge': self._knowledge_pointers(),
            'project_files': self._project_file_pointers(),
            'required_inputs': self._required_input_payloads(),
        }

    def _devkb_pointers(self) -> List[str]:
        """Suggest DevKB files based on project language and spec domain."""
        pointers = []
        language = self.config.get('project', {}).get('language', '').lower()

        # Language-based DevKB files
        lang_map = {
            'python': 'python.md',
            'swift': 'swift.md',
            'typescript': 'typescript.md',
            'javascript': 'javascript.md',
            'rust': 'rust.md',
            'go': 'go.md',
        }

        if language in lang_map:
            pointers.append(f"Argo Home/DevKB/{lang_map[language]}")

        # Always include common files
        pointers.extend([
            'Argo Home/DevKB/architecture.md',
            'Argo Home/DevKB/git.md',
        ])

        # Check if project uses Xcode/Swift
        if any((self.project_root / f).exists() for f in ['Package.swift', '*.xcodeproj']):
            pointers.append('Argo Home/DevKB/xcode.md')

        # Add tooling-specific files if applicable
        if any((self.project_root / f).exists() for f in ['.nightshift/hooks/pre-commit', 'Makefile']):
            pointers.append('Argo Home/DevKB/shell.md')

        return list(dict.fromkeys(pointers))  # Remove duplicates, preserve order

    def _argo_folder_pointers(self) -> List[str]:
        """Suggest context folders to check (project root + spec target dirs).

        SPEC-373: both `.agent-context/` and the legacy `.argo/` are recognized
        while installations migrate; in one directory the new name comes first.
        """
        pointers = []

        def add_context_folders(directory: Path) -> None:
            for name in CONTEXT_FOLDER_NAMES:
                folder = directory / name
                if folder.exists():
                    pointers.append(str(folder.relative_to(self.project_root)))

        # Always: project root context folders
        add_context_folders(self.project_root)

        # Target directories from spec context
        target_files = self.spec.get('context', {}).get('target_files', [])
        for target in target_files:
            target_path = self.project_root / target
            add_context_folders(target_path.parent)

        return list(dict.fromkeys(pointers))

    def _cortex_pointers(self) -> Dict[str, Any]:
        """Suggest Cortex tags to query and lookback window."""
        spec_type = self.spec.get('type', 'feature')
        language = self.config.get('project', {}).get('language', '').lower()

        tags = [language, spec_type]
        if 'tech_stack' in self.spec:
            tags.extend(self.spec.get('tech_stack', []))

        return {
            'tags': list(dict.fromkeys(tags)),
            'last_sessions': 3,
        }

    def _knowledge_pointers(self) -> List[str]:
        """Point to .nightshift/knowledge/ directory."""
        knowledge_dir = self.project_root / '.nightshift' / 'knowledge'
        if knowledge_dir.exists():
            return [str(knowledge_dir.relative_to(self.project_root))]
        return []

    def _project_file_pointers(self) -> List[str]:
        """Point to project-level docs and config."""
        pointers = []

        # Project's .claude/CLAUDE.md if it exists
        claude_md = self.project_root / '.claude' / 'CLAUDE.md'
        if claude_md.exists():
            pointers.append(str(claude_md.relative_to(self.project_root)))

        # config.yaml
        if (self.project_root / 'config.yaml').exists():
            pointers.append('config.yaml')

        return pointers

    def _required_input_payloads(self) -> List[Dict[str, str]]:
        """Load required input artifacts into context so the implementation agent can read them."""
        return load_required_input_context(self.project_root, self.spec)


class CoordinatorMetrics:
    """Records coordinator-level metrics per run."""

    def __init__(self, metrics_dir: Path):
        self.metrics_dir = metrics_dir
        self.metrics_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = f"run-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}"
        self.started_at = iso8601_now()
        self.data = {
            'run_id': self.run_id,
            'started_at': self.started_at,
            'completed_at': None,
            'coordinator_model': None,
            'specs_queued': 0,
            'specs_completed': 0,
            'specs_failed': 0,
            'specs_gapped': 0,
            'specs_skipped': 0,
            'post_merge_validations': [],
            'integration_gates': [],
            'warnings': [],
            'artifact_verifications': [],
            'cascade_blocks': [],
            'coordinator_overhead_s': 0,
            'total_wall_time_s': 0,
        }

    def save(self) -> Path:
        """Save metrics to .nightshift/metrics/coordinator/"""
        run_dir = self.metrics_dir / 'coordinator'
        run_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
        metrics_file = run_dir / f"{timestamp}_run.yaml"
        save_yaml(self.data, metrics_file)
        return metrics_file

    def record_completion(self, wall_time_s: float, overhead_s: float):
        """Mark run complete with timing."""
        self.data['completed_at'] = iso8601_now()
        self.data['total_wall_time_s'] = int(wall_time_s)
        self.data['coordinator_overhead_s'] = int(overhead_s)


class GapReportGenerator:
    """Generates structured gap reports when implementation agent stops."""

    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir

    def create(
        self,
        spec_id: str,
        spec_file: str,
        gap_type: str,
        phase_stopped: int,
        research_attempts: int,
        summary: str,
        what_tried: List[str],
        what_would_unblock: List[str],
        partial_work: Optional[Dict[str, str]] = None,
    ) -> Path:
        """
        Create and save a gap report.
        gap_type: spec_gap | context_gap | domain_gap | tooling_gap
        """
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        report_file = self.reports_dir / f"GAP-{spec_id}-{timestamp.replace(':', '')}.md"

        markdown = self._generate_markdown(
            spec_id, spec_file, gap_type, phase_stopped, research_attempts,
            summary, what_tried, what_would_unblock, partial_work
        )

        with open(report_file, 'w') as f:
            f.write(markdown)

        # Also save as YAML for metrics
        yaml_file = self.reports_dir / f"GAP-{spec_id}-{timestamp.replace(':', '')}.yaml"
        yaml_data = {
            'spec_id': spec_id,
            'spec_file': spec_file,
            'timestamp': timestamp,
            'gap_type': gap_type,
            'phase_stopped': phase_stopped,
            'research_attempts': research_attempts,
            'time_before_stop_s': 0,  # Would be filled by implementation agent
            'tokens_before_stop': 0,
            'summary': summary,
            'what_tried': what_tried,
            'what_would_unblock': what_would_unblock,
            'partial_work': partial_work or {},
        }
        save_yaml(yaml_data, yaml_file)

        return report_file

    def _generate_markdown(
        self, spec_id, spec_file, gap_type, phase, attempts,
        summary, tried, unblock, partial
    ) -> str:
        """Generate markdown gap report."""
        markdown = f"""---
spec_id: {spec_id}
spec_file: {spec_file}
timestamp: {iso8601_now()}
gap_type: {gap_type}
phase_stopped: {phase}
research_attempts: {attempts}
---

# Gap Report: {spec_id}

## What I was trying to do

{summary}

## What's missing or unclear

{summary}

## What I tried

"""
        for attempt in tried:
            markdown += f"- {attempt}\n"

        markdown += "\n## What would unblock this\n\n"
        for suggestion in unblock:
            markdown += f"- {suggestion}\n"

        if partial:
            markdown += f"\n## Partial work (if any)\n\n"
            if partial.get('branch'):
                markdown += f"Branch: {partial['branch']}\n"
            if partial.get('commit'):
                markdown += f"Commit: {partial['commit']}\n"
            if partial.get('description'):
                markdown += f"\n{partial['description']}\n"

        return markdown


class IntegrationFailureReportGenerator:
    """Writes cross-stack integration failure reports for main specs."""

    def __init__(self, reports_dir: Path):
        self.reports_dir = reports_dir

    def create(
        self,
        *,
        main_spec_id: str,
        child_results: List[Dict[str, Any]],
        validation_output: str,
        related_stacks: List[str],
    ) -> Path:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y-%m-%dT%H%M%SZ')
        report_path = self.reports_dir / f"integration-failure-{main_spec_id}-{timestamp}.md"

        lines = [
            f"# Integration Failure: {main_spec_id}",
            "",
            f"- Main spec: `{main_spec_id}`",
            f"- Generated: `{iso8601_now()}`",
            f"- Related stacks checked: {', '.join(related_stacks) if related_stacks else 'none'}",
            "",
            "## Children Merged",
            "",
        ]

        for index, child in enumerate(child_results, start=1):
            changed_files = child.get('files_changed') or []
            lines.append(
                f"{index}. `{child['spec_id']}`"
                f" (stack: `{child.get('stack') or 'default'}`, branch: `{child.get('branch') or 'unknown'}`)"
            )
            if changed_files:
                for rel_path in changed_files:
                    lines.append(f"   - {rel_path}")
            else:
                lines.append("   - (no changed files reported)")

        lines.extend(
            [
                "",
                "## Validation Output",
                "",
                "```text",
                validation_output.rstrip() or "(no output)",
                "```",
                "",
            ]
        )

        report_path.write_text("\n".join(lines), encoding='utf-8')
        return report_path


class PostMergeValidator:
    """Validates that post-merge main branch still passes tests."""

    def __init__(self, project_root: Path, config: Dict[str, Any]):
        self.project_root = project_root
        self.config = config

    def _stack_profile(self, frontmatter: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Resolve a stack profile for the given spec frontmatter, if any."""
        if not frontmatter:
            return None
        stack_name = frontmatter.get('stack')
        if not stack_name:
            return None
        stacks = self.config.get('stacks')
        if not isinstance(stacks, dict):
            return None
        profile = stacks.get(stack_name)
        return profile if isinstance(profile, dict) else None

    def _test_timeout(self, commands: Dict[str, Any]) -> int:
        """Resolve the configured test timeout."""
        timeout = commands.get('test_timeout_s', self.config.get('commands', {}).get('test_timeout_s', 300))
        try:
            timeout_value = int(timeout)
        except (TypeError, ValueError):
            timeout_value = 300
        return 300 if timeout_value <= 0 else timeout_value

    def _run_command(self, command: Optional[str], *, label: str, timeout: int) -> Tuple[bool, str]:
        """Run one validation command and capture combined output."""
        normalized = normalize_command(command)
        if not normalized:
            return True, f"{label} skipped (not configured)"

        try:
            result = subprocess.run(
                normalized,
                shell=True,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"{label} timed out ({timeout}s)"
        except Exception as exc:  # pragma: no cover - defensive wrapper
            return False, f"{label} error: {exc}"

        combined_output = "\n".join(
            chunk for chunk in [result.stdout.strip(), result.stderr.strip()] if chunk
        ).strip()
        if result.returncode != 0:
            failure_output = combined_output or "(no output)"
            return False, f"{label} failed:\n{failure_output}"

        success_output = combined_output or "(no output)"
        return True, f"{label} passed:\n{success_output}"

    def validate(self, frontmatter: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Run post-merge build + test for one spec using stack-aware commands when present."""
        commands = self.config.get('commands', {})
        stack_profile = self._stack_profile(frontmatter)
        if stack_profile and isinstance(stack_profile.get('commands'), dict):
            commands = stack_profile['commands']

        build_cmd = normalize_command(commands.get('build'))
        test_cmd = normalize_command(commands.get('test'))
        timeout = self._test_timeout(commands)

        metadata: Dict[str, Any] = {
            'stack': frontmatter.get('stack') if frontmatter else None,
            'build_command': build_cmd,
            'test_command': test_cmd,
        }

        if not build_cmd and not test_cmd:
            metadata['skipped'] = True
            return True, None, metadata

        outputs: List[str] = []

        if build_cmd:
            passed, output = self._run_command(build_cmd, label="Build", timeout=timeout)
            outputs.append(output)
            if not passed:
                metadata['output'] = "\n\n".join(outputs)
                return False, metadata['output'], metadata

        if test_cmd:
            passed, output = self._run_command(test_cmd, label="Tests", timeout=timeout)
            outputs.append(output)
            if not passed:
                metadata['output'] = "\n\n".join(outputs)
                return False, metadata['output'], metadata

        metadata['output'] = "\n\n".join(outputs) if outputs else None
        return True, None, metadata

    def validate_integration(
        self,
        *,
        main_spec_id: str,
        related_stack_names: List[str],
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """Run the cross-stack integration gate for a main spec."""
        commands = self.config.get('commands', {})
        build_cmd = normalize_command(commands.get('build'))
        test_cmd = normalize_command(commands.get('test'))
        timeout = self._test_timeout(commands)

        metadata: Dict[str, Any] = {
            'spec_id': main_spec_id,
            'build_command': build_cmd,
            'test_command': test_cmd,
            'related_stacks': related_stack_names,
            'related_stack_tests': [],
        }

        if not test_cmd:
            metadata['integration_gate'] = 'skipped'
            metadata['warning'] = "No project-wide test suite configured -- integration gate skipped"
            return True, None, metadata

        outputs: List[str] = []

        if build_cmd:
            passed, output = self._run_command(build_cmd, label="Project-wide build", timeout=timeout)
            outputs.append(output)
            if not passed:
                metadata['output'] = "\n\n".join(outputs)
                metadata['integration_gate'] = 'failed'
                return False, metadata['output'], metadata

        passed, output = self._run_command(test_cmd, label="Project-wide tests", timeout=timeout)
        outputs.append(output)
        if not passed:
            metadata['output'] = "\n\n".join(outputs)
            metadata['integration_gate'] = 'failed'
            return False, metadata['output'], metadata

        stacks = self.config.get('stacks', {})
        for stack_name in related_stack_names:
            profile = stacks.get(stack_name, {}) if isinstance(stacks, dict) else {}
            stack_commands = profile.get('commands', {}) if isinstance(profile, dict) else {}
            stack_test_cmd = normalize_command(stack_commands.get('test'))
            if not stack_test_cmd:
                metadata['related_stack_tests'].append(
                    {'stack': stack_name, 'status': 'skipped', 'command': None}
                )
                continue

            passed, output = self._run_command(
                stack_test_cmd,
                label=f"Related stack tests [{stack_name}]",
                timeout=self._test_timeout(stack_commands),
            )
            outputs.append(output)
            entry = {
                'stack': stack_name,
                'status': 'passed' if passed else 'failed',
                'command': stack_test_cmd,
            }
            metadata['related_stack_tests'].append(entry)
            if not passed:
                metadata['output'] = "\n\n".join(outputs)
                metadata['integration_gate'] = 'failed'
                return False, metadata['output'], metadata

        metadata['output'] = "\n\n".join(outputs)
        metadata['integration_gate'] = 'passed'
        return True, None, metadata


class Coordinator:
    """Main coordinator orchestrator."""

    def __init__(
        self,
        project_root: Path,
        spec_files: List[Path],
        argo_home: Path,
        config: Optional[Dict[str, Any]] = None,
        completion_evidence_provider: Optional[Callable[[WorktreeHandle], Dict[str, Any]]] = None,
        authoring_provider: Optional[managed_payload_provenance.AuthoringProvider] = None,
        integrity_install: Optional[Path] = None,
    ):
        self.project_root = project_root
        self.spec_files = spec_files
        self.argo_home = argo_home
        self.config = config or self._load_config()
        self.metrics = CoordinatorMetrics(project_root / '.nightshift' / 'metrics')
        self.gap_reporter = GapReportGenerator(project_root / '.nightshift' / 'reports')
        self.integration_reporter = IntegrationFailureReportGenerator(project_root / 'reports' / '_wip')
        self.validator = PostMergeValidator(project_root, self.config)
        self._integrity_receipts: Dict[str, Dict[str, Any]] = {}
        self._shared_admission: Dict[str, Any] | None = None
        self._shared_integrity_failed = False
        # Parent-only seam. Worker results are never consulted for completion
        # acceptance; an unwired provider is an explicit fail-closed state.
        self._completion_evidence_provider = completion_evidence_provider
        self._authoring_provider = authoring_provider
        self._integrity_install = integrity_install

    def _install_root(self) -> Path:
        if getattr(self, "_integrity_install", None) is not None:
            return Path(self._integrity_install).resolve()
        installed = self.project_root / ".nightshift"
        return installed if installed.is_dir() else Path(__file__).resolve().parent

    def _admit_managed_payload(self, spec_id: str) -> Dict[str, Any]:
        if run_install_admission is None:
            raise ManagedPayloadIntegrityError(
                "validate_install.py is unavailable; installation admission cannot run."
            )
        admission = run_install_admission(
            spec_id, install_root=self._install_root(), invocation_kind="coordinator",
            run_id=self.metrics.run_id,
        )
        if not admission.get("ok"):
            raise ManagedPayloadIntegrityError(
                admission.get("reason") or "Managed-payload admission is indeterminate."
            )
        if not admission.get("integrity_receipt_path") or not admission.get("integrity_receipt_sha256"):
            raise ManagedPayloadIntegrityError("Managed-payload admission produced no integrity receipt.")
        self._integrity_receipts[spec_id] = admission
        return admission

    def _worker_install_root(self, handle: WorktreeHandle) -> Path:
        if getattr(self, "_integrity_install", None) is not None:
            relative = self._install_root().relative_to(self.project_root.resolve())
            return handle.worktree_path / relative
        installed = handle.worktree_path / ".nightshift"
        return installed if installed.is_dir() else Path(__file__).resolve().parent

    def _accept_managed_payload(self, spec_id: str) -> Dict[str, Any]:
        admission = self._integrity_receipts.get(spec_id)
        if admission is None:
            raise ManagedPayloadIntegrityError("Managed-payload integrity receipt is unavailable.")
        result = managed_payload_provenance.verify_terminal_integrity(
            self._install_root(),
            spec_id=spec_id,
            receipt_ref=str(admission["integrity_receipt_path"]),
            receipt_sha256=str(admission["integrity_receipt_sha256"]),
            run_id=str(admission.get("integrity_run_id") or self.metrics.run_id),
            **({"authoring_provider": self._authoring_provider}
               if getattr(self, "_authoring_provider", None) is not None else {}),
        )
        if not result.ok:
            raise ManagedPayloadIntegrityError(
                f"Managed-payload result acceptance denied ({result.reason_code}); preserve the divergent install and route the fix through canonical release."
            )
        return result.to_dict()

    def _load_config(self) -> Dict[str, Any]:
        """Load config.yaml from project."""
        config_file = self.project_root / '.nightshift' / 'config.yaml'
        if not config_file.exists():
            raise CoordinatorError(f"Config not found: {config_file}")
        return load_yaml(config_file)

    def parallel_dispatch_enabled(self) -> bool:
        """Whether this coordinator was explicitly configured for concurrency."""
        return parallel_worker_limit(self.config) is not None

    def build_parallel_dispatcher(self, *, start_worker, poll_worker) -> BoundedWorktreeDispatcher:
        """Create the opt-in dispatcher while retaining coordinator lifecycle ownership.

        The harness supplies the worker hooks; it never receives scheduling or
        durable-status authority.  Callers that omit a valid worker limit keep
        the established sequential ``run()`` path.
        """
        if not self.parallel_dispatch_enabled():
            raise CoordinatorError("parallel dispatch is disabled or invalid; using sequential mode")
        specs_dir = self.project_root / "specs"
        if not specs_dir.exists():
            specs_dir = self.project_root / ".nightshift" / "specs"
        repo_root = Path(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"], cwd=self.project_root,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        )
        main_branch = str((self.config.get("git") or {}).get("main_branch", "main"))
        store = StatusStore.for_specs_dir(specs_dir)
        selected_spec_ids = {
            str(read_spec_frontmatter(spec_file)[0].get("id"))
            for spec_file in self.spec_files
        }

        def admit_worker(spec_id, handle, _worker_run_id):
            if self._shared_integrity_failed:
                return {"ok": False, "admission": "deny", "reason": "shared managed payload integrity is untrusted"}
            install = self._worker_install_root(handle)
            return run_install_admission(
                spec_id, install_root=install, invocation_kind="coordinator",
                run_id=_worker_run_id,
            )

        return BoundedWorktreeDispatcher(
            repo_root=repo_root,
            project_root=self.project_root,
            specs_dir=specs_dir,
            config=self.config,
            status_store=store,
            start_worker=start_worker,
            poll_worker=poll_worker,
            janitor=lambda: run_startup_janitor(
                repo_root, self.project_root, main_branch=main_branch, status_store=store,
            ),
            admit_worker=admit_worker,
            dispatch_guard=lambda: not self._shared_integrity_failed,
            selected_spec_ids=selected_spec_ids,
        )

    def _execute_parallel_worker(
        self, spec_id: str, handle: WorktreeHandle, _worker_run_id: str,
    ) -> Dict[str, Any]:
        """Execute one isolated worker without granting integration authority."""
        source = next(
            (
                path for path in self.spec_files
                if read_spec_frontmatter(path)[0].get("id") == spec_id
            ),
            None,
        )
        if source is None:
            raise CoordinatorError(f"parallel worker was not selected by this coordinator: {spec_id}")
        try:
            relative = source.resolve().relative_to(self.project_root.resolve())
            worker_spec = handle.worktree_path / relative
        except ValueError:
            worker_spec = source
        frontmatter, _ = read_spec_frontmatter(worker_spec)
        verify_required_inputs(handle.worktree_path, frontmatter)
        context = ContextPointerAssembler(
            handle.worktree_path, self.config, frontmatter, self.argo_home,
        ).assemble()
        result = self._delegate_spec(
            spec_id, worker_spec,
            self._generate_agent_brief(spec_id, worker_spec, context),
        )
        self._enforce_run_token_ceiling(spec_id, worker_spec, result)
        return result

    def _start_parallel_worker(
        self, spec_id: str, handle: WorktreeHandle, worker_run_id: str,
    ) -> Future:
        """Return an in-flight future owned by this coordinator's bounded pool."""
        pool = getattr(self, '_parallel_worker_pool', None)
        if pool is None:
            raise CoordinatorError("parallel worker pool is unavailable")
        return pool.submit(self._execute_parallel_worker, spec_id, handle, worker_run_id)

    @staticmethod
    def _poll_parallel_worker(worker: object) -> Optional[Dict[str, Any]]:
        """Return a completed worker result without granting it parent-side effects."""
        if not isinstance(worker, Future):
            return {"status": "failed", "reason": "invalid parallel worker handle"}
        if not worker.done():
            return None
        try:
            result = worker.result()
        except Exception as exc:  # worker failures become coordinator-owned terminal evidence
            return {
                "status": "failed",
                "reason": f"parallel worker raised {type(exc).__name__}: {exc}",
            }
        if not isinstance(result, dict):
            return {"status": "failed", "reason": "parallel worker returned a non-mapping result"}
        return result

    def _terminalize_parallel_blocked(
        self,
        status_store: StatusStore, *, spec_id: str, run_id: str | None,
        reason: str, payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Persist one immutable blocked choice, then project it to lifecycle."""
        if not run_id:
            raise ValueError("terminal run_id is required")
        current = status_store.get_state(spec_id)
        if (
            current is not None
            and current.get('status') in {'done', 'blocked'}
            and current.get('run_id') != run_id
        ):
            return False
        decision = status_store.record_terminal_decision(
            spec_id, run_id, 'blocked', source='coordinator', reason=reason,
            payload=payload or {},
        )
        current = status_store.get_state(spec_id)
        already_projected = (
            current is not None
            and current.get('status') == 'blocked'
            and current.get('run_id') == run_id
            and (current.get('payload') or {}).get('terminal_decision_id')
                == decision['decision_id']
        )
        if not already_projected:
            status_store.update_state(
                spec_id, 'blocked', run_id=run_id, source='coordinator',
                note=reason, payload={
                    **(payload or {}),
                    'terminal_decision_id': decision['decision_id'],
                },
            )
        spec_path = next((
            path for path in self.spec_files
            if read_spec_frontmatter(path)[0].get('id') == spec_id
        ), None)
        if spec_path is None:
            raise ValueError(f"canonical spec path missing for {spec_id}")
        handle = WorktreeHandle(
            spec_id, self.project_root, "", self.project_root, self.project_root,
            terminal_run_id=run_id, canonical_spec_path=spec_path,
        )
        TrackedTerminalFrontmatterProjector(
            self.project_root, status_store,
        ).project(handle, decision)
        return not already_projected

    @staticmethod
    def _recover_persisted_terminal_decisions(
        status_store: StatusStore, spec_ids: set[str], *,
        terminal_projector: Any = None,
        spec_paths: Optional[Dict[str, Path]] = None,
    ) -> Dict[str, str]:
        """Project interrupted choices under their original logical run IDs."""
        recovered: Dict[str, str] = {}
        for spec_id in sorted(spec_ids):
            current = status_store.get_state(spec_id)
            if current is None:
                continue
            run_id = current.get('run_id')
            if not isinstance(run_id, str) or not run_id:
                continue
            decision = status_store.get_terminal_decision(spec_id, run_id)
            if decision is None:
                continue
            current_terminal = current.get('status') in {'done', 'blocked'}
            if current_terminal:
                if (
                    current.get('status') != decision.get('decision')
                    or (current.get('payload') or {}).get('terminal_decision_id')
                        != decision.get('decision_id')
                ):
                    raise StatusStoreError(
                        f"durable terminal status conflicts with immutable decision for {spec_id}"
                    )
            else:
                status_store.update_state(
                    spec_id, decision['decision'], run_id=run_id,
                    source='coordinator_recovery',
                    note=decision.get('reason') or 'recovered immutable terminal decision',
                    payload={
                        **(decision.get('payload') or {}),
                        'terminal_decision_id': decision['decision_id'],
                        'recovered_projection': True,
                    },
                )
            if terminal_projector is not None:
                spec_path = (spec_paths or {}).get(spec_id)
                if spec_path is None:
                    raise ValueError(f"canonical spec path missing for {spec_id}")
                handle = WorktreeHandle(
                    spec_id, Path(spec_path).parent, "", Path(spec_path).parent,
                    Path(spec_path).parent, terminal_run_id=run_id,
                    canonical_spec_path=spec_path,
                )
                terminal_projector.project(handle, decision)
            recovered[spec_id] = str(decision['decision'])
        return recovered

    @staticmethod
    def _completion_artifact_bytes(
        handle: WorktreeHandle, revision: str, descriptor: Any,
    ) -> tuple[bytes, str]:
        """Read one hash-bound candidate artifact from the immutable revision."""
        if not isinstance(descriptor, dict):
            raise ValueError("artifact descriptor is missing")
        path = descriptor.get('path')
        expected_sha = descriptor.get('sha256')
        pure = PurePosixPath(path) if isinstance(path, str) else PurePosixPath('..')
        if not path or pure.is_absolute() or '..' in pure.parts:
            raise ValueError("artifact path is not a safe candidate-relative path")
        result = subprocess.run(
            ['git', 'show', f'{revision}:{pure.as_posix()}'],
            cwd=handle.worktree_path, capture_output=True,
        )
        if result.returncode != 0 or not result.stdout:
            raise ValueError(f"candidate artifact is missing or empty: {path}")
        observed_sha = hashlib.sha256(result.stdout).hexdigest()
        if expected_sha != observed_sha:
            raise ValueError(f"candidate artifact hash mismatch: {path}")
        return result.stdout, pure.as_posix()

    def _decide_parallel_completion_evidence(self, handle: WorktreeHandle) -> Dict[str, Any]:
        """Validate a parent-owned receipt; worker evidence claims are ignored."""
        provider = self._completion_evidence_provider
        if provider is None:
            return {
                'ok': False, 'outcome': 'indeterminate',
                'reason_code': 'NS-COMP-EVIDENCE-PROVIDER-MISSING',
            }
        try:
            receipt = provider(handle)
        except Exception as exc:
            return {
                'ok': False, 'outcome': 'indeterminate',
                'reason_code': 'NS-COMP-EVIDENCE-PROVIDER-FAILED',
                'detail': f'{type(exc).__name__}: {exc}',
            }
        try:
            if not isinstance(receipt, dict) or receipt.get('schema_version') != '1.0.0':
                raise ValueError('completion receipt schema is invalid')
            if receipt.get('spec_id') != handle.spec_id:
                raise ValueError('completion receipt spec_id mismatch')
            if not handle.integrity_run_id or receipt.get('run_id') != handle.integrity_run_id:
                raise ValueError('completion receipt run_id mismatch')

            head = subprocess.run(
                ['git', 'rev-parse', 'HEAD^{commit}'], cwd=handle.worktree_path,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            branch = subprocess.run(
                ['git', 'rev-parse', f'{handle.branch_name}^{{commit}}'],
                cwd=handle.worktree_path, capture_output=True, text=True, check=True,
            ).stdout.strip()
            revision = receipt.get('candidate_revision')
            if revision != head or revision != branch:
                raise ValueError('completion receipt candidate revision is stale or mismatched')
            main_branch = str((self.config.get('git') or {}).get('main_branch', 'main'))
            main_revision = subprocess.run(
                ['git', 'rev-parse', f'{main_branch}^{{commit}}'],
                cwd=handle.worktree_path, capture_output=True, text=True, check=True,
            ).stdout.strip()
            if receipt.get('main_revision') != main_revision:
                raise ValueError('completion receipt main revision is stale or mismatched')
            dirty = subprocess.run(
                ['git', 'status', '--porcelain'], cwd=handle.worktree_path,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            if dirty:
                raise ValueError('candidate worktree changed after its immutable revision')
            observed_files = sorted(filter(None, subprocess.run(
                ['git', 'diff', '--name-only', f'{main_revision}...{revision}'],
                cwd=handle.worktree_path, capture_output=True, text=True, check=True,
            ).stdout.splitlines()))
            if not observed_files or receipt.get('changed_files') != observed_files:
                raise ValueError('completion receipt changed-file observation mismatch')

            artifacts = receipt.get('artifacts')
            if not isinstance(artifacts, dict):
                raise ValueError('completion receipt artifacts are missing')
            report_bytes, report_path = self._completion_artifact_bytes(
                handle, revision, artifacts.get('report'),
            )
            tests_bytes, tests_path = self._completion_artifact_bytes(
                handle, revision, artifacts.get('tests'),
            )
            checklist_bytes, checklist_path = self._completion_artifact_bytes(
                handle, revision, artifacts.get('ac_checklist'),
            )
            tests = json.loads(tests_bytes)
            checklist = json.loads(checklist_bytes)
            if not isinstance(tests, dict) or tests.get('status') not in {'pass', 'fail'}:
                raise ValueError('test evidence is structurally invalid')
            total = tests.get('tests_total')
            passed = tests.get('tests_passed')
            commands = tests.get('commands')
            if (
                isinstance(total, bool) or not isinstance(total, int) or total < 0
                or isinstance(passed, bool) or not isinstance(passed, int) or passed < 0
                or passed > total
                or not isinstance(commands, list) or not commands
                or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get('command'), str)
                    or not item['command'].strip()
                    or isinstance(item.get('exit_code'), bool)
                    or not isinstance(item.get('exit_code'), int)
                    for item in commands
                )
            ):
                raise ValueError('test counts or command evidence are invalid')
            if not isinstance(checklist, dict) or not isinstance(checklist.get('items'), list):
                raise ValueError('AC checklist is structurally invalid')
            ac_items = checklist['items']
            source = next((
                path for path in self.spec_files
                if read_spec_frontmatter(path)[0].get('id') == handle.spec_id
            ), None)
            if source is None:
                raise ValueError('selected spec is unavailable for AC coverage')
            source_text = source.read_text(encoding='utf-8')
            ac_section = source_text.partition('## Acceptance Criteria')[2].partition('\n## ')[0]
            expected_ac_ids = sorted({
                f'AC{number}' for number in re.findall(
                    r'\bAC(\d+)\s*(?:\([^\n)]*\))?\s*:', ac_section,
                )
            })
            reported_ac_ids = [
                item.get('ac_id') for item in ac_items if isinstance(item, dict)
            ]
            if (
                not expected_ac_ids
                or len(reported_ac_ids) != len(ac_items)
                or len(reported_ac_ids) != len(set(reported_ac_ids))
                or set(reported_ac_ids) != set(expected_ac_ids)
                or any(
                    not isinstance(item.get('passes'), bool)
                    or not isinstance(item.get('evidence'), str)
                    or not item['evidence'].strip()
                    for item in ac_items if isinstance(item, dict)
                )
            ):
                raise ValueError('AC checklist does not exactly cover the selected spec')

            verifier_descriptor = artifacts.get('verifier')
            if not isinstance(verifier_descriptor, dict):
                raise ValueError('verifier artifact descriptor is missing')
            verifier_path = verifier_descriptor.get('path')
            if not isinstance(verifier_path, str):
                raise ValueError('verifier artifact path is invalid')
            verifier_file = (self.project_root / verifier_path).resolve()
            evidence_root = (self.project_root / '.nightshift' / 'completion-evidence').resolve()
            if verifier_file.parent != evidence_root or not verifier_file.is_file():
                raise ValueError('verifier artifact is outside the parent-owned evidence root')
            verifier_bytes = verifier_file.read_bytes()
            if hashlib.sha256(verifier_bytes).hexdigest() != verifier_descriptor.get('sha256'):
                raise ValueError('verifier artifact hash mismatch')
            verdict = json.loads(verifier_bytes)
            candidate_digest = candidate_revision_digest(revision)
            if (
                receipt.get('candidate_revision_digest') != candidate_digest
                or verdict.get('candidate_revision_digest') != candidate_digest
            ):
                raise ValueError('verifier identity is not bound to the candidate revision')
            validate_verifier_verdict(
                verdict,
                spec_id=handle.spec_id,
                implementation_head_digest=str(receipt.get('implementation_head_digest', '')),
                verifier_head_commit=str(receipt.get('verifier_head_commit', '')),
                expected_ac_ids=expected_ac_ids,
                verifier_id=str(receipt.get('verifier_id', '')),
                implementer_ids=receipt.get('implementer_ids') or (),
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError,
                subprocess.CalledProcessError, FeedbackValidationError) as exc:
            return {
                'ok': False, 'outcome': 'indeterminate',
                'reason_code': 'NS-COMP-EVIDENCE-RECEIPT-INVALID',
                'detail': str(exc),
            }

        failed = []
        if tests.get('status') != 'pass' or total <= 0 or passed != total \
                or any(item['exit_code'] != 0 for item in commands):
            failed.append('tests_passed')
        if not checklist.get('all_pass') or any(not item.get('passes') for item in ac_items):
            failed.append('acs_covered')
        if verdict.get('verdict') != 'pass' or any(
            item.get('status') != 'pass' for item in verdict.get('acs') or ()
        ):
            failed.append('verifier')
        if failed:
            return {
                'ok': False, 'outcome': 'rejected',
                'reason_code': 'NS-COMP-EVIDENCE-REJECTED',
                'failed': sorted(failed),
                'candidate_revision': revision,
            }
        return {
            'ok': True, 'outcome': 'accepted',
            'reason_code': 'NS-COMP-EVIDENCE-ACCEPTED',
            'candidate_revision': revision,
            'changed_files': observed_files,
            'artifacts': {
                'report': report_path, 'tests': tests_path,
                'ac_checklist': checklist_path, 'verifier': verifier_path,
            },
        }

    @staticmethod
    def _completion_evidence_recovery_payload(
        handle: WorktreeHandle, decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Retain the branch and exact recovery inputs for a denied decision."""
        return {
            'completion_evidence_decision': decision,
            'worker_outcome': handle.outcome or {},
            'branch_name': handle.branch_name,
            'worktree_path': str(handle.worktree_path),
            'integrity_receipt_path': handle.integrity_receipt_path,
            'integrity_receipt_sha256': handle.integrity_receipt_sha256,
            'integrity_run_id': handle.integrity_run_id,
        }

    def _run_parallel_specs(self, start_time: datetime) -> int:
        """Run the selected specs through one dispatcher and one integration queue."""
        dispatcher = self.build_parallel_dispatcher(
            start_worker=self._start_parallel_worker,
            poll_worker=self._poll_parallel_worker,
        )
        integration_queue = self.build_integration_queue()
        selected_ids = {
            str(read_spec_frontmatter(spec_file)[0].get('id'))
            for spec_file in self.spec_files
        }
        accepted_ids: set[str] = set()
        failed_ids: set[str] = set()
        integration_failed = False
        selected_spec_paths = {
            str(read_spec_frontmatter(path)[0].get('id')): path
            for path in self.spec_files
            if str(read_spec_frontmatter(path)[0].get('id')) in selected_ids
        }
        recovered = self._recover_persisted_terminal_decisions(
            dispatcher.status_store, selected_ids,
            terminal_projector=getattr(
                integration_queue, 'terminal_frontmatter_projector', None,
            ),
            spec_paths=selected_spec_paths,
        )
        self.metrics.data.setdefault('parallel_integrations', []).extend(
            {
                'spec_id': spec_id,
                'decision': 'accepted' if terminal_value == 'done' else 'reverted',
                'reason': 'immutable_terminal_projection_recovered_at_startup',
                'validation_output': '',
            }
            for spec_id, terminal_value in sorted(recovered.items())
        )
        for spec_id, terminal_value in recovered.items():
            if terminal_value != 'done':
                continue
            state = dispatcher.status_store.get_state(spec_id)
            run_id = state.get('run_id') if state is not None else None
            decision = (
                dispatcher.status_store.get_terminal_decision(spec_id, run_id)
                if isinstance(run_id, str) and run_id else None
            )
            if decision is None:
                raise ValueError(
                    f"recovered done decision missing for {spec_id}/{run_id}"
                )
            integration_queue.restore_accepted_terminal_decision(spec_id, decision)
        accepted_ids.update(
            spec_id for spec_id, decision in recovered.items() if decision == 'done'
        )
        failed_ids.update(
            spec_id for spec_id, decision in recovered.items() if decision == 'blocked'
        )
        integration_failed = any(decision == 'blocked' for decision in recovered.values())
        worker_limit = parallel_worker_limit(self.config)
        assert worker_limit is not None

        self._parallel_worker_pool = ThreadPoolExecutor(
            max_workers=worker_limit, thread_name_prefix='nightshift-worker',
        )
        try:
            while True:
                try:
                    launched = dispatcher.advance()
                except Exception as exc:
                    integration_failed = True
                    for spec_id in selected_ids:
                        if self._terminalize_parallel_blocked(
                            dispatcher.status_store, spec_id=spec_id, run_id=self.metrics.run_id,
                            reason=f"parallel dispatch failed: {type(exc).__name__}: {exc}",
                        ):
                            failed_ids.add(spec_id)
                    break
                self.metrics.data['specs_queued'] += len(launched)

                for failure in dispatcher.drain_failed():
                    spec_id = str(failure['spec_id'])
                    reason = str(failure.get('reason') or 'parallel worker failed')
                    if self._terminalize_parallel_blocked(
                        dispatcher.status_store, spec_id=spec_id,
                        run_id=failure.get('run_id'), reason=reason,
                        payload=failure.get('outcome'),
                    ):
                        failed_ids.add(spec_id)

                completed = dispatcher.drain_completed()
                if completed:
                    evidence_accepted: List[WorktreeHandle] = []
                    for handle in completed:
                        decision = self._decide_parallel_completion_evidence(handle)
                        handle.completion_evidence_acceptance = decision
                        self.metrics.data.setdefault('completion_evidence_decisions', []).append({
                            'spec_id': handle.spec_id,
                            **decision,
                        })
                        if decision['ok']:
                            handle.verified_revision = decision['candidate_revision']
                            evidence_accepted.append(handle)
                            continue
                        integration_failed = True
                        if self._terminalize_parallel_blocked(
                            dispatcher.status_store, spec_id=handle.spec_id,
                            run_id=handle.terminal_run_id or handle.integrity_run_id,
                            reason=(
                                f"completion evidence {decision['outcome']}: "
                                f"{decision['reason_code']}"
                            ),
                            payload=self._completion_evidence_recovery_payload(handle, decision),
                        ):
                            failed_ids.add(handle.spec_id)
                    for handle in sorted(evidence_accepted, key=lambda item: item.spec_id):
                        try:
                            result = integration_queue.integrate([handle])
                        except Exception as exc:
                            recovered = integration_queue.recover_terminal_projection(handle)
                            if recovered == 'done':
                                accepted_ids.add(handle.spec_id)
                                self.metrics.data.setdefault('parallel_integrations', []).append({
                                    'spec_id': handle.spec_id,
                                    'decision': 'accepted',
                                    'reason': 'immutable_terminal_projection_recovered',
                                    'validation_output': '',
                                })
                                continue
                            if recovered == 'blocked':
                                integration_failed = True
                                failed_ids.add(handle.spec_id)
                                self.metrics.data.setdefault('parallel_integrations', []).append({
                                    'spec_id': handle.spec_id,
                                    'decision': 'reverted',
                                    'reason': 'immutable_terminal_projection_recovered',
                                    'validation_output': '',
                                })
                                continue
                            integration_failed = True
                            if self._terminalize_parallel_blocked(
                                dispatcher.status_store, spec_id=handle.spec_id,
                                run_id=handle.terminal_run_id or handle.integrity_run_id,
                                reason=f"serialized integration failed: {type(exc).__name__}: {exc}",
                                payload=handle.outcome,
                            ):
                                failed_ids.add(handle.spec_id)
                            continue
                        accepted_ids.update(result.accepted)
                        failed_ids.update(result.held)
                        failed_ids.update(result.reverted)
                        integration_failed = integration_failed or bool(result.held or result.reverted)
                        decisions = {decision.spec_id: decision for decision in result.decisions}
                        for spec_id in result.held:
                            decision = decisions.get(spec_id)
                            reason = decision.reason if decision else 'serialized integration held'
                            self._terminalize_parallel_blocked(
                                dispatcher.status_store, spec_id=spec_id,
                                run_id=handle.terminal_run_id or handle.integrity_run_id,
                                reason=f"serialized integration held: {reason}",
                                payload={
                                    'integration_decision': vars(decision)
                                    if decision is not None else None,
                                },
                            )
                        self.metrics.data.setdefault('parallel_integrations', []).extend(
                            {
                                'spec_id': decision.spec_id,
                                'decision': decision.outcome,
                                'reason': decision.reason,
                                'validation_output': decision.validation_output,
                            }
                            for decision in result.decisions
                        )
                if not dispatcher.active and not launched and not completed:
                    break
                if dispatcher.active and not launched and not completed:
                    delay = float(
                        (self.config.get('parallel_admission') or {}).get('poll_interval_s', 1.0)
                    )
                    time.sleep(max(0.01, min(delay, 5.0)))
        finally:
            self._parallel_worker_pool.shutdown(wait=True)
            self._parallel_worker_pool = None

        for spec_id in selected_ids:
            current = dispatcher.status_store.get_state(spec_id)
            if current is None or current.get('status') not in {'done', 'blocked'}:
                if self._terminalize_parallel_blocked(
                    dispatcher.status_store, spec_id=spec_id, run_id=self.metrics.run_id,
                    reason='parallel run ended without a terminal integration outcome',
                ):
                    failed_ids.add(spec_id)

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        self.metrics.data['specs_completed'] += len(accepted_ids)
        self.metrics.data['specs_failed'] += len(failed_ids)
        self.metrics.record_completion(elapsed, 30)
        self.metrics.save()
        if integration_failed:
            return 3
        return 2 if failed_ids else 0

    def build_integration_queue(self, *, request_repair=None, dependency_graph=None) -> SerializedIntegrationQueue:
        """Create the sole main-branch integration owner for parallel workers.

        This is intentionally separate from dispatch: worker hooks can report a
        completed branch, but only the coordinator's queue merges and validates
        it against the current main checkout.
        """
        repo_root = Path(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"], cwd=self.project_root,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        )
        specs_dir = self.project_root / "specs"
        if not specs_dir.exists():
            specs_dir = self.project_root / ".nightshift" / "specs"
        main_branch = str((self.config.get("git") or {}).get("main_branch", "main"))
        attempts = int((self.config.get("parallel_integration") or {}).get("max_repair_attempts", 1))
        protected_surfaces = (self.config.get("parallel_integration") or {}).get("protected_release_surfaces", [])

        def validate(handle):
            passed, error, metadata = self.validator.validate()
            output = error or metadata.get("output") or "main validation passed"
            return passed, output

        def terminal_gate(handle):
            # First prove the coordinator/shared control plane is still the
            # admitted one.  A failure stops every integration decision.
            if self._shared_admission is None:
                self._shared_admission = run_install_admission(
                    None, install_root=self._install_root(), invocation_kind="coordinator",
                    run_id=f"{self.metrics.run_id}-shared",
                )
            shared = self._shared_admission
            if not shared.get("ok"):
                self._shared_integrity_failed = True
                return {"ok": False, "outcome": "indeterminate", "reason_code": "NS-MPI-SHARED-ADMISSION", "scope": "shared"}
            shared_result = managed_payload_provenance.verify_terminal_integrity(
                self._install_root(),
                spec_id="unselected",
                receipt_ref=str(shared.get("integrity_receipt_path")),
                receipt_sha256=str(shared.get("integrity_receipt_sha256")),
                run_id=str(shared.get("integrity_run_id") or f"{self.metrics.run_id}-shared"),
            )
            if not shared_result.ok:
                self._shared_integrity_failed = True
                return {**shared_result.to_dict(), "scope": "shared"}
            install = self._worker_install_root(handle)
            if not handle.integrity_receipt_path or not handle.integrity_receipt_sha256:
                return {"ok": False, "outcome": "indeterminate", "reason_code": "NS-MPI-RECEIPT-MISSING", "scope": "worker"}
            worker_result = managed_payload_provenance.verify_terminal_integrity(
                install,
                spec_id=handle.spec_id,
                receipt_ref=handle.integrity_receipt_path,
                receipt_sha256=handle.integrity_receipt_sha256,
                run_id=handle.integrity_run_id,
                **({"authoring_provider": self._authoring_provider}
                   if getattr(self, "_authoring_provider", None) is not None else {}),
            ).to_dict()
            return {**worker_result, "scope": "worker"}

        status_store = StatusStore.for_specs_dir(specs_dir)

        def authorization_gate(handle, candidate_sha, head_drift):
            # SPEC-294 R3/R6: the only place config/frontmatter is read for
            # this gate -- the queue itself stays policy-agnostic (mirrors
            # request_repair's injected-callable shape). Reads happen fresh
            # per call rather than being cached on the handle, so an edited
            # deploy_environment: or config.yaml is honored on the very next
            # merge attempt without a coordinator restart.
            deploy_environment = None
            spec_path = specs_dir / f"{handle.spec_id}.md"
            if spec_path.is_file():
                try:
                    deploy_environment = parse_spec_file(spec_path).frontmatter.get(
                        "deploy_environment"
                    )
                except Exception:
                    deploy_environment = None
            return deployment_tiers.check_candidate_authorization(
                reports_root_for_spec_path(spec_path), handle.spec_id,
                cfg=self.config, deploy_environment=deploy_environment,
                candidate_sha=candidate_sha, head_drift=head_drift,
            )

        return SerializedIntegrationQueue(
            repo_root=repo_root,
            main_branch=main_branch,
            validate_main=validate,
            request_repair=request_repair,
            status_store=status_store,
            dependency_graph=dependency_graph,
            max_repair_attempts=attempts,
            protected_surfaces=protected_surfaces,
            terminal_gate=terminal_gate,
            evidence_path=self.project_root / "reports" / "_wip" / f"integration-queue-{self.metrics.run_id}.json",
            release_surface_lease=ReleaseSurfaceLease(self.project_root),
            terminal_frontmatter_projector=TrackedTerminalFrontmatterProjector(
                repo_root, status_store,
            ),
            authorization_gate=authorization_gate,
        )

    def build_integration_broker(self, *, request_repair=None, dependency_graph=None) -> IntegrationBroker:
        """Return the only parent-facing integration entry point for this run."""
        return IntegrationBroker(self.build_integration_queue(
            request_repair=request_repair, dependency_graph=dependency_graph,
        ))

    def reconcile_verifier_feedback(
        self, adapter: FeedbackRuntimeAdapter, initial_state: FeedbackState, *,
        parent_key: bytes, events=None, packet_inputs=None,
        integration_handles: Dict[str, WorktreeHandle] | None = None,
        integration_broker: IntegrationBroker | None = None,
    ) -> FeedbackState:
        """Execute SPEC-235/235-001 through the existing parent authority.

        The reducer owns policy and the supplied adapter owns only durable state,
        normalized polling, and keyed effect execution. Implementer-blocked
        diagnosis remains a source-specific admission inside that same reducer;
        it does not create another scheduler or lifecycle owner. Integration effects must
        still enter :meth:`build_integration_broker`; this method does not expose
        merge or lifecycle authority to a worker or verifier.
        """
        receipt_namespace = hashlib.sha256(
            f"{initial_state.run_id}:{initial_state.spec_id}".encode("utf-8")
        ).hexdigest()
        durable_adapter = DurableIntegrationReceiptAdapter(
            adapter,
            store_root=(
                self.project_root / "reports" / "_wip"
                / "integration-receipts" / receipt_namespace
            ),
        )
        brokered_adapter = IntegrationBrokerFeedbackAdapter(
            durable_adapter,
            broker_factory=(
                (lambda: integration_broker)
                if integration_broker is not None
                else self.build_integration_broker
            ),
            handles=integration_handles or {},
        )
        return reconcile_feedback(
            brokered_adapter, initial_state, parent_key=parent_key,
            events=events, packet_inputs=packet_inputs,
        )

    def initialize_verifier_feedback_state(
        self, *, run_id: str, spec_id: str, candidate_revision: str,
        dispatch_plan: Dict[str, Any], containment_evidence: Dict[str, Any],
        expected_ac_ids: Tuple[str, ...], original_authority: Tuple[str, ...],
        candidate_branch: str = "", candidate_worktree_ref: str = "",
        implementer_ids: Tuple[str, ...] = (),
    ) -> FeedbackState:
        """Pin the private candidate revision to its public verifier identity.

        Only the coordinator receives ``candidate_revision``.  The returned
        durable state uses its opaque implementation digest for reducer/event
        binding while retaining the exact revision solely for parent Git
        comparisons during a possible remediation transition.
        """
        identity = validate_dispatch_identity(
            dispatch_plan=dispatch_plan,
            containment_evidence=containment_evidence,
            verdict={
                "spec_id": spec_id,
                "identity_schema_version": dispatch_plan.get(
                    "identity_schema_version"
                ),
                "head_commit": dispatch_plan.get("head_commit"),
                "implementation_head_digest": dispatch_plan.get(
                    "implementation_head_digest"
                ),
            },
            spec_id=spec_id,
            run_id=run_id,
            candidate_revision=candidate_revision,
        )
        return FeedbackState(
            run_id=run_id,
            spec_id=spec_id,
            implementation_head_digest=identity["implementation_head_digest"],
            expected_ac_ids=expected_ac_ids,
            original_authority=original_authority,
            candidate_branch=candidate_branch,
            candidate_worktree_ref=candidate_worktree_ref,
            implementer_ids=implementer_ids,
            candidate_revision=candidate_revision,
            verifier_head_commit=str(dispatch_plan["head_commit"]),
            containment_binding_digest=identity["containment_binding_digest"],
        )

    def preflight(self) -> None:
        """Validate pre-flight checks. Raise on failure."""
        install_root = self.project_root / ".nightshift"
        if not install_root.is_dir():
            install_root = Path(__file__).resolve().parent
        if run_install_admission is None:
            raise CoordinatorError(
                "validate_install.py is unavailable; installation admission cannot run."
            )
        admission = run_install_admission(
            None, install_root=install_root, invocation_kind="coordinator"
        )
        if not admission.get("ok"):
            raise CoordinatorError(
                admission.get("reason")
                or f"Installation admission gate result: {admission.get('admission', 'indeterminate')}."
            )
        self._shared_admission = admission

        # Check git is clean
        if not git_is_clean(self.project_root):
            raise CoordinatorError("Git tree not clean. Commit or stash changes before running coordinator.")

        # Check all specs are ready
        for spec_file in self.spec_files:
            if not spec_file.exists():
                raise CoordinatorError(f"Spec file not found: {spec_file}")

            frontmatter, status = read_spec_frontmatter(spec_file)
            spec_id = frontmatter.get('id', 'UNKNOWN')

            try:
                validate_spec_readiness(spec_file, spec_id)
            except SpecReadyError as e:
                raise CoordinatorError(f"Spec {spec_id} not ready: {e}")

            if frontmatter.get('type') == 'main':
                for child_spec_id in frontmatter.get('implementation_order') or frontmatter.get('children') or []:
                    child_spec_file = self._child_spec_path(spec_file, child_spec_id)
                    if not child_spec_file.exists():
                        raise CoordinatorError(f"Child spec file not found for {child_spec_id}: {child_spec_file}")
                    try:
                        validate_spec_readiness(child_spec_file, child_spec_id)
                    except SpecReadyError as e:
                        raise CoordinatorError(f"Child spec {child_spec_id} not ready: {e}")

        if 'commands' not in self.config or not isinstance(self.config.get('commands'), dict):
            raise CoordinatorError("Config must define a commands mapping")

    def run(self) -> int:
        """
        Execute coordinator flow. Return exit code.
        0 = success, 1 = preflight failed, 2 = impl agent failed, 3 = validation failed
        """
        try:
            self.preflight()
        except CoordinatorError as e:
            print(f"PREFLIGHT FAILED: {e}", file=sys.stderr)
            return 1

        start_time = datetime.now(timezone.utc)

        if self.parallel_dispatch_enabled():
            return self._run_parallel_specs(start_time)

        # Process each spec
        for spec_file in self.spec_files:
            frontmatter, _ = read_spec_frontmatter(spec_file)
            spec_id = frontmatter.get('id', 'UNKNOWN')

            try:
                self._run_spec(spec_id, spec_file, frontmatter)
                self.metrics.data['specs_completed'] += 1
            except ValidationError as e:
                self.metrics.data['specs_failed'] += 1
                print(f"SPEC {spec_id} FAILED VALIDATION: {e}", file=sys.stderr)
                return 3
            except Exception as e:
                self.metrics.data['specs_failed'] += 1
                print(f"SPEC {spec_id} FAILED: {e}", file=sys.stderr)
                return 2

        # Record metrics
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        self.metrics.record_completion(elapsed, 30)  # Assume 30s coordinator overhead
        metrics_file = self.metrics.save()

        print(f"Coordinator complete. Metrics: {metrics_file}")
        return 0

    def _warn(self, message: str) -> None:
        """Record and emit a coordinator warning."""
        self.metrics.data.setdefault('warnings', []).append(message)
        print(f"WARNING: {message}", file=sys.stderr)

    def _delegate_spec(
        self,
        spec_id: str,
        spec_file: Path,
        brief: str,
    ) -> Dict[str, Any]:
        """Placeholder implementation-agent delegation hook.

        Completion acceptance never comes from this worker-facing result. The
        distinct parent evidence provider remains unwired by default.
        """
        print(f"\n=== SPEC {spec_id} ===")
        print(f"Spec file: {spec_file}")
        print(f"Brief preview (first 500 chars):\n{brief[:500]}...\n")
        return {
            'status': 'success',
            'spec_id': spec_id,
            'commit_hash': 'abc123deadbeef',
            'branch': f'spec-{spec_id}',
            'files_changed': [],
        }

    def _child_spec_path(self, parent_file: Path, child_spec_id: str) -> Path:
        """Resolve a child spec file relative to the parent spec directory.

        Real Nightshift spec files are usually named ``SPEC-123-slug.md`` rather
        than exactly ``SPEC-123.md``. Prefer an exact match, then fall back to a
        prefix glob so ``implementation_order: [SPEC-123]`` still resolves.
        """
        exact = parent_file.parent / f"{child_spec_id}.md"
        if exact.exists():
            return exact

        matches = sorted(parent_file.parent.glob(f"{child_spec_id}*.md"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise CoordinatorError(
                f"Multiple child spec files match {child_spec_id}: "
                + ", ".join(str(path.name) for path in matches)
            )
        return exact

    def _detect_related_stacks(self, child_results: List[Dict[str, Any]]) -> List[str]:
        """Detect additional stacks affected by shared-file changes."""
        stacks = self.config.get('stacks')
        if not isinstance(stacks, dict):
            return []

        related: set[str] = set()
        for child in child_results:
            child_stack = child.get('stack')
            if not child_stack or child_stack not in stacks:
                continue
            child_root = stacks[child_stack].get('root', '.')
            for rel_path in child.get('files_changed') or []:
                if path_matches_root(rel_path, child_root):
                    continue
                for stack_name, profile in stacks.items():
                    if stack_name == child_stack:
                        continue
                    if path_matches_root(rel_path, profile.get('root', '.')):
                        related.add(stack_name)
        return sorted(related)

    def _run_main_spec(self, spec_id: str, spec_file: Path, frontmatter: Dict[str, Any]) -> None:
        """Process a container spec by executing its children, then the integration gate."""
        child_ids = frontmatter.get('implementation_order') or frontmatter.get('children') or []
        if not child_ids:
            raise CoordinatorError(f"Main spec {spec_id} has no children to execute")

        set_spec_status(spec_file, 'in_progress')
        child_results: List[Dict[str, Any]] = []

        for child_spec_id in child_ids:
            child_spec_file = self._child_spec_path(spec_file, child_spec_id)
            if not child_spec_file.exists():
                raise CoordinatorError(f"Child spec file not found for {child_spec_id}: {child_spec_file}")

            child_frontmatter, _ = read_spec_frontmatter(child_spec_file)
            result = self._run_spec(child_spec_id, child_spec_file, child_frontmatter)
            child_results.append(result)

        # Result acceptance owns the fresh post-work comparison.  It runs
        # before integration validation or lifecycle terminalization.
        self._accept_managed_payload(spec_id)
        related_stacks = self._detect_related_stacks(child_results)
        passed, error, metadata = self.validator.validate_integration(
            main_spec_id=spec_id,
            related_stack_names=related_stacks,
        )

        if metadata.get('warning'):
            self._warn(metadata['warning'])

        gate_entry = {
            'spec_id': spec_id,
            'integration_gate': metadata.get('integration_gate'),
            'related_stacks': related_stacks,
            'children': [
                {
                    'spec_id': child['spec_id'],
                    'stack': child.get('stack'),
                    'files_changed': child.get('files_changed', []),
                }
                for child in child_results
            ],
        }

        if passed:
            set_spec_status(spec_file, 'done')
            self.metrics.data['integration_gates'].append(gate_entry)
            return

        report_path = self.integration_reporter.create(
            main_spec_id=spec_id,
            child_results=child_results,
            validation_output=error or metadata.get('output') or "(no output)",
            related_stacks=related_stacks,
        )
        gate_entry['report_path'] = str(report_path)
        gate_entry['failure_output'] = error
        self.metrics.data['integration_gates'].append(gate_entry)
        raise ValidationError(f"Cross-stack integration gate failed for {spec_id}: {error}")

    def _run_spec(self, spec_id: str, spec_file: Path, frontmatter: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a single spec through its lifecycle.
        1. Assemble context pointers
        2. Generate brief
        3. Delegate to implementation agent
        4. Handle outcome
        5. Post-merge validation if needed
        """
        self.metrics.data['specs_queued'] += 1

        # Keep the exact admission receipt for this selected spec.  A later
        # admission would bless changed bytes and is not a terminal check.
        self._admit_managed_payload(spec_id)

        if frontmatter.get('type') == 'main':
            self._run_main_spec(spec_id, spec_file, frontmatter)
            return {
                'status': 'success',
                'spec_id': spec_id,
                'stack': None,
                'files_changed': [],
            }

        try:
            verify_required_inputs(self.project_root, frontmatter)
        except SpecContractError as exc:
            update_spec_status(spec_file, status=exc.status, message=str(exc), error_type=exc.error_type)
            raise

        # Step 1: Assemble context pointers
        assembler = ContextPointerAssembler(
            self.project_root, self.config, frontmatter, self.argo_home
        )
        context_pointers = assembler.assemble()

        # Step 2: Generate brief for implementation agent
        brief = self._generate_agent_brief(spec_id, spec_file, context_pointers)

        # Step 3: Delegate to implementation agent
        agent_result = self._delegate_spec(spec_id, spec_file, brief)
        self._enforce_run_token_ceiling(spec_id, spec_file, agent_result)

        # Step 5: Post-merge validation
        if agent_result['status'] == 'success':
            acceptance = self._accept_managed_payload(spec_id)
            self.metrics.data.setdefault('managed_payload_acceptance', []).append({
                'spec_id': spec_id,
                'outcome': acceptance['outcome'],
                'reason_code': acceptance['reason_code'],
                'artifact_path': acceptance['artifact_path'],
                'artifact_sha256': acceptance['artifact_sha256'],
            })
            try:
                verification = verify_output_artifact(self.project_root, frontmatter)
            except SpecContractError as exc:
                update_spec_status(spec_file, status=exc.status, message=str(exc), error_type=exc.error_type)
                raise
            if verification is not None:
                self.metrics.data.setdefault('artifact_verifications', []).append(
                    {
                        'spec_id': spec_id,
                        **verification,
                    }
                )
            passed, error, validation_meta = self.validator.validate(frontmatter)
            if not passed:
                self.metrics.data['post_merge_validations'].append({
                    'spec_id': spec_id,
                    'developer_said_done': True,
                    'main_green_after_merge': False,
                    'failure_output': error,
                    'stack': validation_meta.get('stack'),
                    'build_command': validation_meta.get('build_command'),
                    'test_command': validation_meta.get('test_command'),
                })
                raise ValidationError(f"Post-merge validation failed for {spec_id}: {error}")
            else:
                self.metrics.data['post_merge_validations'].append({
                    'spec_id': spec_id,
                    'developer_said_done': True,
                    'main_green_after_merge': True,
                    'stack': validation_meta.get('stack'),
                    'build_command': validation_meta.get('build_command'),
                    'test_command': validation_meta.get('test_command'),
                    'skipped': validation_meta.get('skipped', False),
                })
            set_spec_status(spec_file, 'done')
            return {
                'status': 'success',
                'spec_id': spec_id,
                'stack': frontmatter.get('stack'),
                'branch': agent_result.get('branch'),
                'commit_hash': agent_result.get('commit_hash'),
                'files_changed': list(agent_result.get('files_changed') or []),
            }

        raise CoordinatorError(f"Implementation agent did not complete {spec_id}: {agent_result['status']}")

    def _enforce_run_token_ceiling(
        self, spec_id: str, spec_file: Path, agent_result: Dict[str, Any]
    ) -> None:
        """Refuse a breached run, retaining its reported partial work verbatim.

        This is intentionally a post-observation refusal: it records provider
        usage and stops the coordinator. It never changes a request or history
        in an attempt to continue below the ceiling.
        """
        ceiling = run_token_ceiling(self.config)
        observed = observed_token_spend(agent_result)
        if observed <= ceiling:
            return

        reason = f"run_token_ceiling {ceiling} breached: observed spend {observed}"
        partial_work = dict(agent_result)
        partial_work["description"] = reason
        gap_report = self.gap_reporter.create(
            spec_id=spec_id,
            spec_file=str(spec_file),
            gap_type="token_ceiling",
            phase_stopped=3,
            research_attempts=0,
            summary=reason,
            what_tried=["Accepted provider-reported token usage without modifying the run context."],
            what_would_unblock=["Raise run_token_ceiling after reviewing historical usage and this breach report."],
            partial_work=partial_work,
        )
        self._record_run_spend_ceiling_breach(spec_id, ceiling, observed, gap_report)
        update_spec_status(
            spec_file,
            status="blocked",
            message=reason,
            error_type="run_token_ceiling_exceeded",
        )
        raise RunTokenCeilingExceeded(f"{reason}; report: {gap_report}")

    def _record_run_spend_ceiling_breach(
        self, spec_id: str, ceiling: int, observed: int, gap_report: Path
    ) -> Path:
        """Append the refusal event to the human-facing per-day run report."""
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        report_path = self.project_root / "reports" / f"{date}-nightshift-report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        if not report_path.exists():
            report_path.write_text(f"# Nightshift Report — {date}\n\n**Outcome:** blocked\n", encoding="utf-8")
        with report_path.open("a", encoding="utf-8") as report:
            report.write(
                f"\n## Run Spend Ceiling Breach\n\n"
                f"- Spec: {spec_id}\n"
                f"- Ceiling: {ceiling}\n"
                f"- Observed spend: {observed}\n"
                f"- Partial work: {gap_report}\n"
            )
        return report_path

    def _generate_agent_brief(
        self, spec_id: str, spec_file: Path, context_pointers: Dict[str, Any]
    ) -> str:
        """Generate the brief for implementation agent."""
        brief = f"""# Nightshift Implementation Spec: {spec_id}

You have been delegated this spec by the Nightshift Coordinator.

## Your Task

Implement the spec at: {spec_file}

Follow the LOOP.md protocol exactly. Your goal is to:
1. Read and understand the spec
2. Plan implementation with tests
3. Write tests that match acceptance criteria
4. Implement the code
5. Run static analysis and reviews
6. Validate against acceptance criteria
7. Commit and report results

## Context to Read

Before starting, read these pointers:

### DevKB Files (technology lessons)
"""
        for devkb_file in context_pointers.get('devkb', []):
            brief += f"- {devkb_file}\n"

        brief += "\n### Project context folders (.agent-context/, .argo/)\n"
        for argo_folder in context_pointers.get('argo_folders', []):
            brief += f"- {argo_folder}\n"

        brief += "\n### Cortex Tags to Query\n"
        cortex = context_pointers.get('cortex', {})
        brief += f"Tags: {', '.join(cortex.get('tags', []))}\n"
        brief += f"Last {cortex.get('last_sessions', 3)} sessions\n"

        brief += "\n### Knowledge Files\n"
        for knowledge_file in context_pointers.get('knowledge', []):
            brief += f"- {knowledge_file}\n"

        brief += "\n### Project Files\n"
        for project_file in context_pointers.get('project_files', []):
            brief += f"- {project_file}\n"

        required_inputs = context_pointers.get('required_inputs', [])
        if required_inputs:
            brief += "\n### Required Inputs (load these into working context)\n"
            for payload in required_inputs:
                brief += f"\n## Required Input: {payload['path']}\n\n"
                brief += "```text\n"
                brief += payload['content'].rstrip()
                brief += "\n```\n"

        brief += f"""

## Important Constraints

- **Read LOOP.md first** — it is the authoritative spec execution protocol
- **Do not guess** — if you hit an information gap, spawn a research subagent
- **Circuit breaker** — if you spawn 3+ research subagents on the same gap, STOP
- **Gap reports** — if you must stop, produce a structured gap report at:
  .nightshift/reports/GAP-{spec_id}-{{TIMESTAMP}}.md
- **No implementation without a spec** — the coordinator enforces this

## Success Criteria

When done:
1. All acceptance criteria are met and tested
2. Code passes lint, type check, and build
3. Tests pass and coverage is adequate
4. Git branch is clean (all changes committed)
5. Metrics YAML is complete and valid

Report your outcome to the coordinator.
"""
        return brief


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <project_root> <spec_file> [<spec_file> ...]", file=sys.stderr)
        print(f"       {sys.argv[0]} <project_root> --all", file=sys.stderr)
        sys.exit(1)

    project_root = Path(sys.argv[1])
    argo_home = Path.home() / 'Dropbox' / 'Argo'

    # Determine which specs to run
    if len(sys.argv) > 2 and sys.argv[2] == '--all':
        # Run all ready specs
        specs_dir = project_root / '.nightshift' / 'specs'
        if not specs_dir.exists():
            print("ERROR: .nightshift/specs/ not found", file=sys.stderr)
            sys.exit(1)
        spec_files = sorted(specs_dir.glob('SPEC-*.md'))
    else:
        # Run specified specs
        spec_files = [Path(s) for s in sys.argv[2:]]

    if not spec_files:
        print("ERROR: No specs to run", file=sys.stderr)
        sys.exit(1)

    # Run coordinator
    try:
        coordinator = Coordinator(project_root, spec_files, argo_home)
        exit_code = coordinator.run()
        sys.exit(exit_code)
    except CoordinatorError as e:
        print(f"COORDINATOR ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
