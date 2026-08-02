#!/usr/bin/env python3
"""
Nightshift DAG — Offline Dependency Graph & Execution Plan Builder

A lightweight CLI tool that reads Nightshift spec YAML frontmatter, builds a DAG,
detects cycles, validates implementation_order, and writes execution-plan.json.

Exit codes:
  0: Clean plan (no cycles, no order conflicts)
  1: Plan written but with issues (cycles, order conflicts)
  2: Fatal error (missing spec, malformed YAML, I/O error)
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional

import yaml

CANONICAL_DIR = Path(__file__).resolve().parent
if str(CANONICAL_DIR) not in sys.path:
    sys.path.insert(0, str(CANONICAL_DIR))

from model_stylesheet import resolve_model
from dependency_registry import DependencyRegistryResolver
from parallel_executor import (
    AdmissionSpec,
    plan_dynamic_admission,
    plan_parallel_execution,
    write_admission_plan,
    ParallelLayer,
)
from spec_frontmatter import VALID_SPEC_STATUSES

_STOP_WORDS = frozenset({
    "the", "a", "an", "to", "in", "for", "and", "or", "with",
    "of", "is", "on", "at", "by", "from", "as", "it", "be",
    "that", "this",
})

_BUGFIX_KEYWORDS = {"fix", "crash", "bug", "broken", "error", "fail", "regression"}
_REFACTOR_KEYWORDS = {"refactor", "restructure", "reorganize", "clean up", "simplify", "extract", "decouple"}


class Color(Enum):
    """Tri-color DFS state."""

    WHITE = 0
    GRAY = 1
    BLACK = 2


def _canonicalize_cycle(cycle: List[str]) -> Tuple[str, ...]:
    """Rotate a cycle so it starts at its lexicographically smallest node."""
    if len(cycle) < 2:
        return tuple(cycle)

    body = cycle[:-1]
    if not body:
        return tuple(cycle)

    min_node = min(body)
    min_index = body.index(min_node)
    rotated = body[min_index:] + body[:min_index]
    return tuple(rotated + [rotated[0]])


def detect_cycles_in_graph(
    graph: Dict[str, Set[str]],
    *,
    color: Optional[Dict[str, Color]] = None,
) -> List[List[str]]:
    """
    Detect all cycles in a dependency graph using tri-color DFS.

    Args:
        graph: Dict mapping node ID to Set of its dependencies.
        color: Optional externally supplied color map, used by tests that
            instrument DFS state transitions.

    Returns:
        List of cycle chains (each chain includes start node twice).
    """
    all_nodes = set(graph.keys())
    for neighbors in graph.values():
        all_nodes.update(neighbors)

    if color is None:
        color = {}

    for node in all_nodes:
        if node not in color:
            color[node] = Color.WHITE

    cycles: List[List[str]] = []
    seen_cycles: Set[Tuple[str, ...]] = set()

    def dfs(node: str, path: List[str]) -> None:
        color[node] = Color.GRAY
        path.append(node)

        for neighbor in sorted(graph.get(node, set())):
            if neighbor not in color:
                color[neighbor] = Color.WHITE
            neighbor_color = color[neighbor]
            if neighbor_color == Color.WHITE:
                dfs(neighbor, path[:])
            elif neighbor_color == Color.GRAY:
                cycle_start_idx = path.index(neighbor)
                cycle = path[cycle_start_idx:] + [neighbor]
                canonical_cycle = _canonicalize_cycle(cycle)
                if canonical_cycle not in seen_cycles:
                    seen_cycles.add(canonical_cycle)
                    cycles.append(list(canonical_cycle))

        color[node] = Color.BLACK

    for node in sorted(all_nodes):
        if color[node] == Color.WHITE:
            dfs(node, [])

    return cycles


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class SpecFrontmatter:
    """Parsed YAML frontmatter from a spec file."""
    id: str
    parent: Optional[str] = None
    after: List[str] = field(default_factory=list)
    nfrs: List[str] = field(default_factory=list)
    type: str = "feature"  # main, feature, bugfix, refactor, chore, nfr, eval
    status: str = "draft"
    priority: int = 1
    children: List[str] = field(default_factory=list)
    implementation_order: List[str] = field(default_factory=list)
    # New fields for multi-stack support (SPEC-023)
    stack: Optional[str] = None
    domain: Optional[str] = None
    output_artifact: Optional[str] = None
    output_type: Optional[str] = None
    output_schema: Optional[str] = None
    required_inputs: List[str] = field(default_factory=list)
    provides: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    touches: List[str] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    """Represents the computed execution plan."""
    computed_at: str
    source_spec: str
    execution_order: List[str]
    cycles: List[List[str]]
    blocked: List[str]
    nfr_injections: Dict[str, List[str]]

    def to_json(self) -> str:
        """Serialize to JSON with 2-space indentation."""
        data = asdict(self)
        return json.dumps(data, indent=2)


class OrderConflictBox:
    """Renders an ASCII box showing order conflicts with correction."""

    @staticmethod
    def render(parent_id: str, declared: List[str], computed: List[str]) -> str:
        """
        Generate an ASCII box showing the conflict and ready-to-paste correction.

        Args:
            parent_id: The parent spec ID (e.g., "SPEC-004")
            declared: Order declared in parent's implementation_order
            computed: Order computed by topological sort

        Returns:
            Multi-line string with ASCII box and correction details.
        """
        box_width = 64
        top_line = "╔" + "═" * (box_width - 2) + "╗"
        bottom_line = "╚" + "═" * (box_width - 2) + "╝"

        lines = [
            top_line,
            "║  " + "⚠  ORDER CONFLICT — plan auto-corrected".ljust(box_width - 4) + "║",
            bottom_line,
            "",
            "  Declared in " + parent_id + ":    " + " → ".join(declared),
            "  Computed (topo sort):    " + " → ".join(computed),
        ]

        # Identify which specs moved
        lines.append("")
        for i, spec_id in enumerate(computed):
            if i < len(declared) and spec_id == declared[i]:
                continue
            # This spec moved. Find where it was in declared.
            if spec_id in declared:
                old_pos = declared.index(spec_id)
                if old_pos < i:
                    lines.append(f"  {spec_id} moved earlier — after: [] (no deps)")
                else:
                    # Find what it now depends on
                    deps = _find_dependencies_for_spec(
                        spec_id, computed[:i], parent_id
                    )
                    lines.append(
                        f"  {spec_id} moved later  — after: {deps}"
                    )

        lines.append("")
        lines.append("  execution-plan.json reflects the CORRECTED order.")
        lines.append("  Update your spec:")
        lines.append("")
        lines.append("    implementation_order:")
        for spec_id in computed:
            lines.append(f"      - {spec_id}")
        lines.append("")
        lines.append(bottom_line)

        return "\n".join(lines)


def _find_dependencies_for_spec(
    spec_id: str, earlier_specs: List[str], parent_id: str
) -> List[str]:
    """Find the dependencies of a spec based on specs that come before it."""
    # For now, return the last spec in the earlier list as a heuristic
    if earlier_specs:
        return [earlier_specs[-1]]
    return []


# ============================================================================
# DAG Builder
# ============================================================================

class DAGBuilder:
    """Builds a directed acyclic graph from Nightshift spec frontmatter."""

    def __init__(self, specs_dir: Path):
        self.specs_dir = specs_dir
        self.specs: Dict[str, SpecFrontmatter] = {}
        self.local_spec_ids: Set[str] = set()
        self.dependency_resolution = None

    def load_specs(self) -> Dict[str, SpecFrontmatter]:
        """
        Load all spec files from specs_dir and parse their frontmatter.

        Returns:
            Dict mapping spec ID to SpecFrontmatter.

        Raises:
            ValueError: If YAML frontmatter is malformed.
        """
        self.specs = {}
        for spec_file in self.specs_dir.glob("*.md"):
            try:
                frontmatter = self._parse_frontmatter(spec_file)
                if frontmatter:
                    self.specs[frontmatter.id] = frontmatter
            except ValueError as e:
                raise ValueError(f"Error parsing {spec_file.name}: {e}")
        self.local_spec_ids = set(self.specs)
        local_specs = {
            spec_id: {"id": spec_id, "status": spec.status}
            for spec_id, spec in self.specs.items()
        }
        dependency_ids = {
            dependency
            for spec in self.specs.values()
            for dependency in spec.after
        }
        self.dependency_resolution = DependencyRegistryResolver(self.specs_dir).resolve(
            dependency_ids,
            local_specs=local_specs,
        )
        if self.dependency_resolution.errors:
            raise ValueError("; ".join(self.dependency_resolution.errors.values()))
        for spec_id, record in self.dependency_resolution.resolved.items():
            if spec_id in self.specs:
                continue
            self.specs[spec_id] = SpecFrontmatter(
                id=spec_id,
                status=record.status,
                type=str(record.frontmatter.get("type") or "external"),
                priority=int(record.frontmatter.get("priority") or 1),
            )
        return self.specs

    def _parse_frontmatter(self, filepath: Path) -> Optional[SpecFrontmatter]:
        """
        Parse YAML frontmatter from a spec file (between --- delimiters).

        Returns:
            SpecFrontmatter if successful, None if file has no frontmatter.

        Raises:
            ValueError: If YAML is malformed.
        """
        with open(filepath, "r") as f:
            content = f.read()

        # Extract frontmatter between first two --- lines
        lines = content.split("\n")
        if not lines or lines[0].strip() != "---":
            return None

        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break

        if end_idx is None:
            return None

        yaml_lines = lines[1:end_idx]
        yaml_text = "\n".join(yaml_lines)

        # Parse YAML using regex (no external dependencies)
        return self._parse_yaml_text(yaml_text)

    def _parse_yaml_text(self, yaml_text: str) -> SpecFrontmatter:
        """Parse YAML text and return SpecFrontmatter."""
        data = self._regex_parse_yaml(yaml_text)

        # Extract and validate required fields
        spec_id = data.get("id")
        if not spec_id:
            raise ValueError("Missing required field: id")

        return SpecFrontmatter(
            id=spec_id,
            parent=data.get("parent"),
            after=data.get("after", []),
            nfrs=data.get("nfrs", []),
            type=data.get("type", "feature"),
            status=data.get("status", "draft"),
            priority=int(data.get("priority", 1)),
            children=data.get("children", []),
            implementation_order=data.get("implementation_order", []),
            stack=data.get("stack"),
            domain=data.get("domain"),
            output_artifact=data.get("output_artifact"),
            output_type=data.get("output_type"),
            output_schema=data.get("output_schema"),
            required_inputs=data.get("required_inputs", []),
            provides=data.get("provides", []),
            requires=data.get("requires", []),
            touches=data.get("touches", []),
        )

    @staticmethod
    def _regex_parse_yaml(yaml_text: str) -> Dict:
        """Parse YAML using regex (no external dependencies)."""
        data = {}

        # Parse id
        match = re.search(r'^\s*id:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            data["id"] = match.group(1).strip()

        # Parse parent
        match = re.search(r'^\s*parent:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            data["parent"] = match.group(1).strip()

        # Parse type
        match = re.search(r'^\s*type:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            data["type"] = match.group(1).strip()

        # Parse status
        match = re.search(r'^\s*status:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            data["status"] = match.group(1).strip()

        # Parse layer
        match = re.search(r'^\s*layer:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            data["layer"] = match.group(1).strip()

        # Parse priority (numeric; malformed values fail at frontmatter construction).
        match = re.search(r'^\s*priority:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            data["priority"] = match.group(1).strip()

        # Parse created
        match = re.search(r'^\s*created:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            data["created"] = match.group(1).strip()

        # Parse after (list - try multiline first)
        match = re.search(
            r'^\s*after:\s*\n((?:^\s+-\s+.+$\n?)*)',
            yaml_text,
            re.MULTILINE
        )
        if match and match.group(1).strip():
            items_text = match.group(1)
            items = re.findall(r'^\s+-\s+(.+)$', items_text, re.MULTILINE)
            data["after"] = [item.strip() for item in items]
        else:
            # Try inline list
            match = re.search(r'^\s*after:\s*\[(.+?)\]', yaml_text, re.MULTILINE)
            if match:
                items = match.group(1).split(",")
                data["after"] = [item.strip() for item in items if item.strip()]

        # Parse nfrs (list - try multiline first)
        match = re.search(
            r'^\s*nfrs:\s*\n((?:^\s+-\s+.+$\n?)*)',
            yaml_text,
            re.MULTILINE
        )
        if match and match.group(1).strip():
            items_text = match.group(1)
            items = re.findall(r'^\s+-\s+(.+)$', items_text, re.MULTILINE)
            data["nfrs"] = [item.strip() for item in items]
        else:
            # Try inline list
            match = re.search(r'^\s*nfrs:\s*\[(.+?)\]', yaml_text, re.MULTILINE)
            if match:
                items = match.group(1).split(",")
                data["nfrs"] = [item.strip() for item in items if item.strip()]
            else:
                # Try empty list
                match = re.search(r'^\s*nfrs:\s*\[\]', yaml_text, re.MULTILINE)
                if match:
                    data["nfrs"] = []

        # Parse children (list - try multiline first)
        match = re.search(
            r'^\s*children:\s*\n((?:^\s+-\s+.+$\n?)*)',
            yaml_text,
            re.MULTILINE
        )
        if match and match.group(1).strip():
            items_text = match.group(1)
            items = re.findall(r'^\s+-\s+(.+)$', items_text, re.MULTILINE)
            data["children"] = [item.strip() for item in items]
        else:
            # Try inline list
            match = re.search(r'^\s*children:\s*\[(.+?)\]', yaml_text, re.MULTILINE)
            if match:
                items = match.group(1).split(",")
                data["children"] = [item.strip() for item in items if item.strip()]
            else:
                match = re.search(r'^\s*children:\s*\[\]', yaml_text, re.MULTILINE)
                if match:
                    data["children"] = []

        # Parse stack (scalar)
        match = re.search(r'^\s*stack:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            val = match.group(1).strip()
            if val:
                data["stack"] = val

        # Parse domain (scalar)
        match = re.search(r'^\s*domain:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            val = match.group(1).strip()
            if val:
                data["domain"] = val

        # Parse output_artifact (scalar)
        match = re.search(r'^\s*output_artifact:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            val = match.group(1).strip().strip('"').strip("'")
            if val:
                data["output_artifact"] = val

        # Parse output_type (scalar)
        match = re.search(r'^\s*output_type:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            val = match.group(1).strip()
            if val:
                data["output_type"] = val

        # Parse output_schema (scalar)
        match = re.search(r'^\s*output_schema:\s*(.+)$', yaml_text, re.MULTILINE)
        if match:
            val = match.group(1).strip().strip('"').strip("'")
            if val:
                data["output_schema"] = val

        # Parse context.required_inputs (nested list under context:)
        match = re.search(
            r'^\s*context:\s*\n(?:\s+\w+:.*\n)*?\s+required_inputs:\s*\n((?:^\s+-\s+.+$\n?)*)',
            yaml_text,
            re.MULTILINE
        )
        if match and match.group(1).strip():
            items_text = match.group(1)
            items = re.findall(r'^\s+-\s+(.+)$', items_text, re.MULTILINE)
            data["required_inputs"] = [item.strip().strip('"').strip("'") for item in items]
        else:
            # Try inline list under context
            match = re.search(
                r'^\s*context:\s*\n\s+required_inputs:\s*\[(.+?)\]',
                yaml_text,
                re.MULTILINE
            )
            if match:
                items = match.group(1).split(",")
                data["required_inputs"] = [item.strip().strip('"').strip("'") for item in items if item.strip()]


        # Parse OpenSpec-transfer stacking metadata lists (SPEC-054)
        for list_name in ("provides", "requires", "touches"):
            match = re.search(
                rf'^\s*{list_name}:\s*\n((?:^\s+-\s+.+$\n?)*)',
                yaml_text,
                re.MULTILINE,
            )
            if match and match.group(1).strip():
                items_text = match.group(1)
                items = re.findall(r'^\s+-\s+(.+)$', items_text, re.MULTILINE)
                data[list_name] = [item.strip().strip('"').strip("'") for item in items]
            else:
                match = re.search(rf'^\s*{list_name}:\s*\[(.*?)\]', yaml_text, re.MULTILINE)
                if match:
                    items = match.group(1).split(",")
                    data[list_name] = [item.strip().strip('"').strip("'") for item in items if item.strip()]

        # Parse implementation_order (list - try multiline first)
        match = re.search(
            r'^\s*implementation_order:\s*\n((?:^\s+-\s+.+$\n?)+)',
            yaml_text,
            re.MULTILINE
        )
        if match:
            items_text = match.group(1)
            items = re.findall(r'^\s+-\s+(.+)$', items_text, re.MULTILINE)
            data["implementation_order"] = [item.strip() for item in items]
        else:
            # Try inline list
            match = re.search(
                r'^\s*implementation_order:\s*\[(.+?)\]',
                yaml_text,
                re.MULTILINE
            )
            if match:
                items = match.group(1).split(",")
                data["implementation_order"] = [
                    item.strip() for item in items if item.strip()
                ]

        return data

    def build_graph(
        self, main_spec_id: str
    ) -> Dict[str, Set[str]]:
        """
        Build dependency graph starting from main_spec_id.

        Only includes specs that are children of main_spec_id or depended
        on transitively. Main specs and NFR specs are included for graph
        construction but filtered out later.

        Args:
            main_spec_id: The root spec ID (e.g., "SPEC-004")

        Returns:
            Dict mapping spec ID to Set of its dependencies.

        Raises:
            ValueError: If main spec not found.
        """
        if main_spec_id not in self.specs:
            raise ValueError(f"Main spec {main_spec_id} not found")

        # Find all specs transitively reachable from main_spec_id
        reachable = self._find_reachable_specs(main_spec_id)

        # Build graph for reachable specs
        graph = {}
        for spec_id in reachable:
            spec = self.specs[spec_id]
            dependencies = set(spec.after)
            graph[spec_id] = dependencies

        return graph

    def _find_reachable_specs(self, spec_id: str) -> Set[str]:
        """Find all specs reachable from a given spec (children + after deps)."""
        visited = set()
        stack = [spec_id]

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)

            if current not in self.specs:
                continue

            spec = self.specs[current]
            # Add children
            for child in spec.children:
                if child not in visited:
                    stack.append(child)
            # Add after dependencies
            for dep in spec.after:
                if dep not in visited:
                    stack.append(dep)

        return visited

    def topological_sort(self, graph: Dict[str, Set[str]]) -> List[str]:
        """
        Compute topological sort of the graph using Kahn's algorithm.

        Deterministic: alphabetical tie-breaking.

        Args:
            graph: Dict mapping spec ID to Set of its dependencies (things that must come BEFORE it).

        Returns:
            List of spec IDs in topological order.
        """
        # Initialize in-degree: count how many dependencies each node has
        # in_degree[node] = len(graph[node]) = how many things must come before node
        in_degree = {node: len(graph[node]) for node in graph}

        # Kahn's algorithm with alphabetical tie-breaking
        # Start with nodes that have no dependencies
        queue = sorted([node for node in in_degree if in_degree[node] == 0])
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)

            # For each node that depends on the one we just processed
            for other_node in graph:
                if node in graph[other_node]:
                    # Decrease its in-degree (one of its dependencies is now processed)
                    in_degree[other_node] -= 1
                    if in_degree[other_node] == 0:
                        # It's now ready to process (all its dependencies are done)
                        queue.append(other_node)
                        queue.sort()

        return result

    def detect_cycles(self, graph: Dict[str, Set[str]]) -> List[List[str]]:
        """
        Detect all cycles using DFS.

        Args:
            graph: Dict mapping spec ID to Set of its dependencies.

        Returns:
            List of cycle chains (each chain includes start node twice).
        """
        return detect_cycles_in_graph(graph)

    def check_order(
        self, parent: SpecFrontmatter, computed: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if parent's implementation_order matches computed topo sort (for children only).

        Args:
            parent: The parent spec frontmatter.
            computed: The computed topological sort.

        Returns:
            (is_consistent, correction_yaml) tuple.
        """
        declared = parent.implementation_order

        # Filter computed order to only include parent's children and executable specs
        parent_child_ids = set(parent.children)
        executable_computed = [
            spec_id for spec_id in computed
            if spec_id in parent_child_ids
            and spec_id in self.specs
            and self.specs[spec_id].type not in ("main", "nfr")
        ]

        # Filter declared to only include executable specs
        executable_declared = [
            spec_id for spec_id in declared
            if spec_id in parent_child_ids
            and spec_id in self.specs
            and self.specs[spec_id].type not in ("main", "nfr")
        ]

        is_consistent = executable_declared == executable_computed

        correction = None
        if not is_consistent:
            correction = OrderConflictBox.render(
                parent.id, executable_declared, executable_computed
            )

        return is_consistent, correction

    def build_nfr_map(
        self, specs: Dict[str, SpecFrontmatter], debug: bool = False
    ) -> Dict[str, List[str]]:
        """
        Build NFR injection map: spec ID -> list of NFR IDs.

        Args:
            specs: Dict of spec ID -> SpecFrontmatter.
            debug: If True, log warnings for missing NFR files.

        Returns:
            Dict mapping spec ID to list of NFR IDs.
        """
        nfr_map = {}
        for spec_id, spec in specs.items():
            nfr_map[spec_id] = []
            for nfr_id in spec.nfrs:
                nfr_file = self.specs_dir / f"{nfr_id}.md"
                template_named_files = list(self.specs_dir.glob(f"{nfr_id}-*.md"))
                if not nfr_file.exists() and not template_named_files:
                    if debug:
                        print(
                            f"  Warning: NFR file {nfr_id}.md or {nfr_id}-*.md not found",
                            file=sys.stderr,
                        )
                else:
                    nfr_map[spec_id].append(nfr_id)

        return nfr_map


# ============================================================================
# Main CLI
# ============================================================================

def resolve_specs_dir(specs_dir_arg: Optional[str]) -> Path:
    """
    Resolve the specs directory.

    If specs_dir_arg is provided, use it. Otherwise, walk up from the
    script's directory looking for a directory containing 'specs/'.

    Raises:
        ValueError: If specs directory cannot be resolved.
    """
    if specs_dir_arg:
        specs_path = Path(specs_dir_arg).resolve()
        if specs_path.is_dir():
            return specs_path
        raise ValueError(f"--specs-dir {specs_dir_arg} is not a directory")

    # Walk up from script directory
    script_dir = Path(__file__).parent
    current = script_dir

    while current != current.parent:
        candidate = current / "specs"
        if candidate.is_dir():
            return candidate
        current = current.parent

    raise ValueError("Could not locate specs/ directory")


def _extract_frontmatter_and_body(spec_file: Path) -> Tuple[str, str]:
    """Return YAML frontmatter text and markdown body from a spec file."""
    content = spec_file.read_text()
    lines = content.split("\n")

    if not lines or lines[0].strip() != "---":
        raise ValueError("missing YAML frontmatter")

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        raise ValueError("missing closing frontmatter delimiter")

    return "\n".join(lines[1:end_idx]), "\n".join(lines[end_idx + 1:])


def _load_spec_ids(specs_dir: Path) -> Set[str]:
    """Load all spec IDs present in the target specs directory."""
    builder = DAGBuilder(specs_dir)
    spec_ids = set()

    for spec_file in specs_dir.glob("*.md"):
        try:
            yaml_text, _ = _extract_frontmatter_and_body(spec_file)
        except ValueError:
            continue

        spec_id = builder._regex_parse_yaml(yaml_text).get("id")
        if spec_id:
            spec_ids.add(spec_id)

    return spec_ids


def _validate_spec_file(spec_path: Path) -> List[str]:
    """
    Validate a single spec file and return a list of violation strings.

    Returns an empty list if the spec is valid.
    """
    violations: List[str] = []

    if not spec_path.is_file():
        violations.append(f"INVALID: spec file not found {spec_path}")
        return violations

    try:
        yaml_text, body = _extract_frontmatter_and_body(spec_path)
    except ValueError as e:
        violations.append(f"INVALID: {e}")
        return violations

    builder = DAGBuilder(spec_path.parent)
    data = builder._regex_parse_yaml(yaml_text)

    for field_name in ("id", "status", "layer", "type", "created"):
        value = data.get(field_name)
        if value is None or str(value).strip() == "":
            violations.append(f"INVALID: missing field {field_name} in frontmatter")

    status = data.get("status", "")
    if status and status not in VALID_SPEC_STATUSES:
        violations.append(
            "INVALID: invalid status "
            f"{status} (expected one of: {', '.join(sorted(VALID_SPEC_STATUSES))})"
        )

    available_spec_ids = _load_spec_ids(spec_path.parent)
    for field_name in ("after", "nfrs"):
        for ref in data.get(field_name, []):
            if ref not in available_spec_ids:
                violations.append(
                    f"INVALID: {field_name} reference {ref} not found in specs/"
                )

    if "## Requirements" not in body:
        violations.append("INVALID: missing section Requirements")
    if "## Acceptance Criteria" not in body:
        violations.append("INVALID: missing section Acceptance Criteria")

    return violations


def validate_spec(args) -> int:
    """
    Execute the 'validate-spec' command for a single spec file.

    Returns exit code (0 or 1).
    """
    spec_file = Path(args.spec_file).resolve()
    violations = _validate_spec_file(spec_file)

    if violations:
        for violation in violations:
            print(violation)
        return 1

    print(f"VALID: {spec_file}")
    return 0


def resolve_model_command(args) -> int:
    """Execute the 'resolve-model' command for a single spec file."""
    spec_file = Path(args.spec_file).resolve()
    config_file = Path(args.config).resolve()

    try:
        yaml_text, _ = _extract_frontmatter_and_body(spec_file)
        spec_frontmatter = DAGBuilder(spec_file.parent)._regex_parse_yaml(yaml_text)
        config_data = yaml.safe_load(config_file.read_text()) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return 1

    stylesheet = config_data.get("model_stylesheet") or {}
    print(json.dumps(resolve_model(spec_frontmatter, stylesheet)))
    return 0


def admission(args) -> int:
    """Write a current-frontier admission plan from durable spec state."""
    specs_dir = Path(args.specs_dir) if args.specs_dir else CANONICAL_DIR / "specs"
    builder = DAGBuilder(specs_dir)
    try:
        specs = builder.load_specs()
    except (OSError, ValueError) as exc:
        print(f"Error loading specs: {exc}", file=sys.stderr)
        return 2

    configured = {}
    config_path = getattr(args, "config", None)
    if config_path:
        try:
            for document in yaml.safe_load_all(Path(config_path).read_text()):
                if isinstance(document, dict):
                    configured.update(document.get("parallel_admission") or {})
        except (OSError, yaml.YAMLError) as exc:
            print(f"Error reading admission config: {exc}", file=sys.stderr)
            return 2

    worker_limit = args.worker_limit if args.worker_limit is not None else configured.get("worker_limit", 1)
    missing_touches_policy = (
        args.missing_touches_policy
        if args.missing_touches_policy is not None
        else configured.get("missing_touches_policy", "exclusive")
    )
    runnable_specs = [
        AdmissionSpec(
            spec_id=spec.id,
            status=spec.status,
            after=tuple(spec.after),
            touches=tuple(spec.touches),
            priority=spec.priority,
        )
        for spec_id in sorted(builder.local_spec_ids)
        for spec in [specs[spec_id]]
        if spec.type not in ("main", "nfr")
    ]
    resolution = builder.dependency_resolution
    plan = plan_dynamic_admission(
        runnable_specs,
        worker_limit,
        missing_touches_policy=missing_touches_policy,
        dependency_statuses={
            spec_id: record.status
            for spec_id, record in (resolution.resolved if resolution else {}).items()
            if spec_id not in builder.local_spec_ids
        },
        dependency_errors=resolution.errors if resolution else {},
    )
    json_path, markdown_path = write_admission_plan(plan, specs_dir)
    print(f"admission plan written: {json_path}")
    print(f"review plan written: {markdown_path}")
    return 0


def detect_runtime_cycles(args) -> int:
    """
    Execute the 'detect-runtime-cycles' command using retry edges from events.jsonl.

    Returns exit code (0 or 1).
    """
    events_file = Path(args.events).resolve()

    if not events_file.exists():
        print("no events log found — runtime cycle detection skipped")
        return 0

    graph: Dict[str, Set[str]] = {}

    with open(events_file, "r") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                event = json.loads(line)
            except json.JSONDecodeError as e:
                print(
                    f"warning: skipping malformed events line {line_number}: {e}",
                    file=sys.stderr,
                )
                continue

            if event.get("event") != "spec_retry":
                continue

            source = event.get("source")
            target = event.get("target")
            if not isinstance(source, str) or not isinstance(target, str):
                continue

            graph.setdefault(source, set()).add(target)
            graph.setdefault(target, set())

    cycles = detect_cycles_in_graph(graph)

    if cycles:
        for cycle in cycles:
            print(" → ".join(cycle))
        return 1

    print("no runtime cycles detected")
    return 0


def plan(args) -> int:
    """
    Execute the 'plan' command.

    Returns exit code (0, 1, or 2).
    """
    try:
        specs_dir = resolve_specs_dir(args.specs_dir)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    builder = DAGBuilder(specs_dir)

    # Load specs
    try:
        specs = builder.load_specs()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    # Check that main spec exists
    if args.spec_id not in specs:
        print(
            f"Error: Main spec {args.spec_id} not found",
            file=sys.stderr
        )
        return 2

    main_spec = specs[args.spec_id]

    if args.debug:
        print("[1/5] Scanning specs...")
        for spec_id in sorted(specs.keys()):
            spec = specs[spec_id]
            children_str = (
                "[" + ", ".join(spec.children) + "]"
                if spec.children else "[]"
            )
            after_str = (
                "[" + ", ".join(spec.after) + "]"
                if spec.after else "[]"
            )
            parent_str = f"parent={spec.parent}" if spec.parent else ""
            print(
                f"  {spec_id:<15} type={spec.type:<8} "
                f"status={spec.status:<8} {parent_str} after={after_str}"
            )

    # Build graph
    try:
        graph = builder.build_graph(args.spec_id)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if args.debug:
        print("\n[2/5] Building dependency graph...")
        for spec_id in sorted(graph.keys()):
            deps = graph[spec_id]
            if deps:
                deps_str = ", ".join(sorted(deps))
                print(f"  {spec_id:<15} ← {deps_str}")
            else:
                print(f"  {spec_id:<15} ← (root)")

    # Topological sort
    topo_order = builder.topological_sort(graph)

    # Check order consistency
    order_consistent, conflict_box = builder.check_order(main_spec, topo_order)

    if args.debug:
        print("\n[3/5] Checking implementation_order consistency...")
        declared = main_spec.implementation_order
        print(f"  {args.spec_id} declares: {declared}")
        print(f"  Topological sort:  {topo_order}  {'✓ consistent' if order_consistent else '✗ CONFLICT'}")

    # Detect cycles
    cycles = builder.detect_cycles(graph)

    if args.debug:
        print("\n[4/5] Cycle detection...")
        if not cycles:
            print("  No cycles found  ✓")
        else:
            for cycle in cycles:
                cycle_str = " → ".join(cycle)
                print(f"  Cycle: {cycle_str}")

    # Build NFR map
    nfr_map = builder.build_nfr_map(specs, debug=args.debug)

    if args.debug:
        print("\n[5/5] Building NFR injection map...")
        for spec_id in sorted(nfr_map.keys()):
            nfrs = nfr_map[spec_id]
            nfr_str = "[" + ", ".join(nfrs) + "]" if nfrs else "[]"
            print(f"  {spec_id:<15} → {nfr_str}")

    # Filter execution order: exclude main and nfr specs
    executable_order = [
        spec_id for spec_id in topo_order
        if spec_id in specs and specs[spec_id].type not in ("main", "nfr")
    ]

    # Identify blocked specs (in cycles)
    blocked = set()
    for cycle in cycles:
        blocked.update(cycle[:-1])  # Exclude the repeated start node

    blocked = sorted(list(blocked))

    # Build execution plan
    plan = ExecutionPlan(
        computed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source_spec=args.spec_id,
        execution_order=executable_order,
        cycles=cycles,
        blocked=blocked,
        nfr_injections=nfr_map,
    )

    # Compute parallel layers if requested
    parallel_data = None
    if getattr(args, "parallel", False):
        layers = plan_parallel_execution(graph, executable_order)
        parallel_data = [asdict(layer) for layer in layers]

    # Write execution plan
    if args.debug:
        print("\nWriting execution-plan.json...")

    plan_file = specs_dir / "execution-plan.json"
    try:
        plan_dict = json.loads(plan.to_json())
        if parallel_data is not None:
            plan_dict["parallel_layers"] = parallel_data
        with open(plan_file, "w") as f:
            json.dump(plan_dict, f, indent=2)
    except IOError as e:
        print(f"Error writing {plan_file}: {e}", file=sys.stderr)
        return 2

    # Print output
    if conflict_box:
        print(conflict_box)

    if not args.debug and not cycles:
        num_specs = len(executable_order)
        print(f"✓ execution-plan.json written  [{num_specs} specs · 0 cycles]")
    elif not args.debug:
        num_specs = len(executable_order)
        num_cycles = len(cycles)
        num_blocked = len(blocked)
        cycle_str = " → ".join(cycles[0]) if cycles else ""
        print(f"✗ Cycle detected: {cycle_str}")
        print(f"  Blocked specs excluded: {', '.join(blocked)}")
        print(f"  execution-plan.json written  [{num_specs} specs · {num_cycles} cycle blocked]")
    elif args.debug:
        num_specs = len(executable_order)
        num_cycles = len(cycles)
        num_nfr_injections = sum(1 for nfrs in nfr_map.values() if nfrs)
        print(
            f"✓ Done  [{num_specs} specs · {num_cycles} cycles · "
            f"{num_nfr_injections} NFR injection]"
        )

    # Determine exit code
    if cycles or not order_consistent:
        return 1
    return 0


def validate(args) -> int:
    """
    Execute the 'validate' command (same as plan but no file written).

    Returns exit code (0, 1, or 2).
    """
    try:
        specs_dir = resolve_specs_dir(args.specs_dir)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    builder = DAGBuilder(specs_dir)

    # Load specs
    try:
        specs = builder.load_specs()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    # Check that main spec exists
    if args.spec_id not in specs:
        print(
            f"Error: Main spec {args.spec_id} not found",
            file=sys.stderr
        )
        return 2

    main_spec = specs[args.spec_id]

    if args.debug:
        print(f"[1/5] Scanning specs...")
        for spec_id in sorted(specs.keys()):
            spec = specs[spec_id]
            parent_str = f"parent={spec.parent}" if spec.parent else ""
            print(f"  {spec_id:<15} type={spec.type:<8} {parent_str}")

    # Build graph
    try:
        graph = builder.build_graph(args.spec_id)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    if args.debug:
        print("\n[2/5] Building dependency graph...")
        for spec_id in sorted(graph.keys()):
            deps = graph[spec_id]
            if deps:
                print(f"  {spec_id:<15} ← {', '.join(sorted(deps))}")

    # Topological sort
    topo_order = builder.topological_sort(graph)

    # Check order
    order_consistent, conflict_box = builder.check_order(main_spec, topo_order)

    if args.debug:
        print("\n[3/5] Checking implementation_order consistency...")
        print(f"  Declared: {main_spec.implementation_order}")
        print(f"  Computed: {topo_order}")

    # Detect cycles
    cycles = builder.detect_cycles(graph)

    if args.debug:
        print("\n[4/5] Cycle detection...")
        if cycles:
            for cycle in cycles:
                print(f"  Cycle: {' → '.join(cycle)}")
        else:
            print("  No cycles found  ✓")

    # Build NFR map
    nfr_map = builder.build_nfr_map(specs, debug=args.debug)

    if args.debug:
        print("\n[5/5] Building NFR injection map...")
        for spec_id in sorted(nfr_map.keys()):
            print(f"  {spec_id:<15} → {nfr_map[spec_id]}")

    # Print validation results
    if conflict_box:
        print(conflict_box)

    if cycles:
        print("Cycles detected:")
        for cycle in cycles:
            print(f"  {' → '.join(cycle)}")
        return 1

    if not order_consistent:
        return 1

    if not args.debug:
        print(f"✓ Validation passed for {args.spec_id}")

    return 0



# ============================================================================
# SPEC-054: stacking metadata graph/next helpers
# ============================================================================

def _spec_sort_key(spec: SpecFrontmatter) -> tuple:
    def _int_or_999(value):
        try:
            return int(str(value).lstrip("P"))
        except Exception:
            return 999
    return (_int_or_999(getattr(spec, "priority", 999)), _int_or_999(getattr(spec, "layer", 999)), spec.id)


def build_stack_metadata(specs: Dict[str, SpecFrontmatter]) -> dict:
    providers: Dict[str, List[str]] = {}
    for spec in specs.values():
        for marker in spec.provides:
            providers.setdefault(marker, []).append(spec.id)

    warnings: List[dict] = []
    for spec in specs.values():
        for req in spec.requires:
            if req not in providers:
                warnings.append({
                    "type": "unmatched_requires",
                    "spec_id": spec.id,
                    "marker": req,
                    "message": f"{spec.id} requires {req}, but no spec provides it",
                })
        if spec.parent and spec.parent not in specs:
            warnings.append({
                "type": "missing_parent",
                "spec_id": spec.id,
                "parent": spec.parent,
                "message": f"{spec.id} references missing parent {spec.parent}",
            })

    active = [s for s in specs.values() if s.status in {"ready", "in_progress"}]
    for i, left in enumerate(active):
        for right in active[i + 1:]:
            overlap = sorted(set(left.touches) & set(right.touches))
            for marker in overlap:
                warnings.append({
                    "type": "touch_overlap",
                    "spec_ids": [left.id, right.id],
                    "marker": marker,
                    "message": f"{left.id} and {right.id} both touch {marker}",
                })

    unlocks: Dict[str, List[str]] = {sid: [] for sid in specs}
    for spec in specs.values():
        for dep in spec.after:
            if dep in unlocks:
                unlocks[dep].append(spec.id)

    return {
        "providers": {k: sorted(v) for k, v in providers.items()},
        "warnings": warnings,
        "unlocks": {k: sorted(v) for k, v in unlocks.items()},
    }


def graph_command(args) -> int:
    try:
        specs_dir = resolve_specs_dir(args.specs_dir)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    specs = DAGBuilder(specs_dir).load_specs()
    graph = {sid: set(spec.after) for sid, spec in specs.items()}
    cycles = detect_cycles_in_graph(graph)
    metadata = build_stack_metadata(specs)
    payload = {
        "specs": [
            {
                "id": spec.id,
                "status": spec.status,
                "after": spec.after,
                "parent": spec.parent,
                "provides": spec.provides,
                "requires": spec.requires,
                "touches": spec.touches,
                "unlocks": metadata["unlocks"].get(spec.id, []),
            }
            for spec in sorted(specs.values(), key=lambda s: s.id)
        ],
        "cycles": cycles,
        "warnings": metadata["warnings"],
    }
    if args.json_output:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for spec in payload["specs"]:
            print(f"{spec['id']} [{spec['status']}] after={spec['after']} unlocks={spec['unlocks']}")
        for warning in payload["warnings"]:
            print(f"WARNING {warning['type']}: {warning['message']}")
    return 1 if cycles else 0


def next_command(args) -> int:
    try:
        specs_dir = resolve_specs_dir(args.specs_dir)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    builder = DAGBuilder(specs_dir)
    try:
        specs = builder.load_specs()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    metadata = build_stack_metadata(specs)
    ready = []
    for spec_id in sorted(builder.local_spec_ids):
        spec = specs[spec_id]
        if spec.status != "ready":
            continue
        unmet = [dep for dep in spec.after if dep not in specs or specs[dep].status != "done"]
        if unmet:
            continue
        warnings = [w for w in metadata["warnings"] if w.get("spec_id") == spec.id or spec.id in w.get("spec_ids", [])]
        ready.append({
            "id": spec.id,
            "status": spec.status,
            "after": spec.after,
            "provides": spec.provides,
            "requires": spec.requires,
            "touches": spec.touches,
            "unlocks": metadata["unlocks"].get(spec.id, []),
            "warnings": warnings,
        })
    ready.sort(key=lambda item: _spec_sort_key(specs[item["id"]]))
    payload = {"ready": ready, "warnings": metadata["warnings"]}
    if args.json_output:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for item in ready:
            print(f"{item['id']} ready warnings={len(item['warnings'])}")
    return 0

# ============================================================================
# SPEC-035: ingest subcommand
# ============================================================================

def _detect_spec_type(description: str) -> str:
    """Detect spec type from description using keyword heuristics.

    First keyword match by position wins.
    """
    desc_lower = description.lower()
    # Build a list of (position, type) for all keyword matches
    matches: List[Tuple[int, str]] = []
    for kw in _BUGFIX_KEYWORDS:
        pos = desc_lower.find(kw)
        if pos >= 0:
            matches.append((pos, "bugfix"))
    for kw in _REFACTOR_KEYWORDS:
        pos = desc_lower.find(kw)
        if pos >= 0:
            matches.append((pos, "refactor"))
    if not matches:
        return "feature"
    matches.sort(key=lambda x: x[0])
    return matches[0][1]


def _generate_slug(description: str) -> str:
    """Generate a URL-safe slug from a description, truncated at word boundary."""
    slug = re.sub(r'[^a-z0-9]+', '-', description.lower()).strip('-')
    if len(slug) <= 50:
        return slug
    # Truncate at word boundary (last hyphen before or at pos 50)
    truncated = slug[:50]
    last_hyphen = truncated.rfind('-')
    if last_hyphen > 0:
        return truncated[:last_hyphen]
    return truncated


def _find_target_files(project_dir: Path, description: str) -> List[str]:
    """Scan project tree (3 levels deep) for files matching significant words."""
    words = set(re.findall(r'[a-z]+', description.lower())) - _STOP_WORDS
    # Filter to words >= 3 chars for meaningful matching
    words = {w for w in words if len(w) >= 3}
    if not words:
        return []

    matches: List[str] = []
    for depth, (dirpath, dirnames, filenames) in enumerate(os.walk(project_dir)):
        if depth >= 3:
            dirnames.clear()
            continue
        # Skip hidden dirs and common non-source dirs
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in ('node_modules', '__pycache__', 'venv', '.git')]
        for fname in filenames:
            if fname.startswith('.'):
                continue
            fname_lower = fname.lower()
            for word in words:
                if word in fname_lower:
                    rel = os.path.relpath(os.path.join(dirpath, fname), project_dir)
                    matches.append(rel)
                    break
            if len(matches) >= 10:
                break
        if len(matches) >= 10:
            break

    return sorted(matches[:10])


def ingest(args) -> int:
    """Generate a spec file from a natural language description.

    Returns exit code (0 or 1).
    """
    description = args.description

    # Resolve specs dir
    if args.specs_dir:
        specs_dir = Path(args.specs_dir).resolve()
    else:
        try:
            specs_dir = resolve_specs_dir(None)
        except ValueError:
            specs_dir = Path.cwd() / "specs"

    if not specs_dir.is_dir():
        specs_dir.mkdir(parents=True, exist_ok=True)

    # Auto-assign ID: scan for SPEC-NNN filenames
    max_id = 0
    for f in specs_dir.iterdir():
        m = re.match(r'SPEC-(\d+)', f.name)
        if m:
            num = int(m.group(1))
            if num > max_id:
                max_id = num
    next_id = max_id + 1

    # Generate slug
    slug = _generate_slug(description)

    # Detect type
    detected_type = _detect_spec_type(description)

    # Today's date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Auto-detect target files
    project_dir = specs_dir.parent
    target_files = _find_target_files(project_dir, description)
    target_files_str = ""
    if target_files:
        target_files_str = "\n".join(f"- `{f}`" for f in target_files)
    else:
        target_files_str = "- (none detected — fill in manually)"

    # Build spec content
    spec_id = f"SPEC-{next_id:03d}"
    filename = f"{spec_id}-{slug}.md"
    spec_path = specs_dir / filename

    content = f"""---
id: {spec_id}
priority: 3
layer: 1
type: {detected_type}
status: draft
after: []
prior_attempts: []
created: {today}
template_version: 1
---

## Problem

{description}

## Requirements

- TODO: define requirements

## Acceptance Criteria

- [ ] TODO: define acceptance criteria

## Context

**Auto-detected target files:**
{target_files_str}

## Implementation Notes

- TODO: add implementation notes

## Out of Scope

- TODO: define what is out of scope
"""

    spec_path.write_text(content)

    # Post-generation validation
    violations = _validate_spec_file(spec_path)
    if violations:
        print(f"Created: {spec_path}")
        print("Validation warnings:")
        for v in violations:
            print(f"  {v}")
        return 0
    else:
        print(f"Created: {spec_path}")
        print(f"VALID: {spec_path}")
        return 0


# ============================================================================
# SPEC-036: status subcommand
# ============================================================================

try:
    from loop_events import load_events, tail_events, STEP_NAMES
except ImportError:
    # Inline fallback: define minimal versions if loop_events is unavailable
    def load_events(events_file: Path) -> List[Dict]:
        events: List[Dict] = []
        try:
            with open(events_file, "r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        if isinstance(event, dict):
                            events.append(event)
                    except json.JSONDecodeError:
                        continue
        except (FileNotFoundError, OSError):
            pass
        return events

    def tail_events(events_file: Path, last_n: int = 20) -> List[Dict]:
        return load_events(events_file)[-last_n:]

    STEP_NAMES = {
        1: "preflight", 2: "task_selection", 3: "context_loading",
        4: "test_planning", 5: "test_writing", 6: "plan_review",
        7: "implementation", 8: "validation", 9: "completion_verification",
        10: "post_review", 11: "circuit_breaker", 12: "commit_changelog",
        13: "metrics_logging", 14: "report_generation", 15: "post_run",
        16: "loop_exit",
    }


def _discover_runs(nightshift_dir: Path) -> List[Path]:
    """Find run-* directories sorted newest-first."""
    runs_dir = nightshift_dir / "runs"
    if not runs_dir.is_dir():
        return []
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("run-")]
    return sorted(run_dirs, key=lambda d: d.name, reverse=True)


def _derive_run_state(events: List[Dict]) -> str:
    """Derive run state from events list."""
    if not events:
        return "unknown"

    event_types = {e.get("event") for e in events}

    if "loop_ended" in event_types:
        return "completed"

    # Check if loop was started but never ended
    if "loop_started" in event_types:
        # Check for interruption signals
        if "error" in event_types or "circuit_breaker_tripped" in event_types:
            return "interrupted"
        return "in_progress"

    # Has some events but no clear start/end
    if events:
        return "in_progress"

    return "unknown"


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration.

    45 -> "45s"
    90 -> "1m 30s"
    3661 -> "1h 1m 1s"
    """
    seconds = int(seconds)
    if seconds < 0:
        seconds = 0

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)


def _format_event_line(event: Dict) -> str:
    """Format a single event as a human-readable line.

    [HH:MM:SS] step_name -- event_type: details
    """
    ts = event.get("ts", "")
    # Extract time portion from ISO timestamp
    time_str = "??:??:??"
    if ts:
        try:
            # Handle both Z and +00:00 suffixes
            ts_clean = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_clean)
            time_str = dt.strftime("%H:%M:%S")
        except (ValueError, AttributeError):
            pass

    event_type = event.get("event", "unknown")

    # Build step name from step number if available
    step = event.get("step")
    step_name = ""
    if isinstance(step, int) and step in STEP_NAMES:
        step_name = STEP_NAMES[step]
    elif isinstance(step, str):
        step_name = step

    # Build details from remaining interesting fields
    detail_keys = {"message", "spec_id", "reason", "details", "result"}
    details = []
    for k in detail_keys:
        v = event.get(k)
        if v is not None:
            details.append(str(v))
    detail_str = ", ".join(details) if details else ""

    if step_name and detail_str:
        return f"[{time_str}] {step_name} -- {event_type}: {detail_str}"
    elif step_name:
        return f"[{time_str}] {step_name} -- {event_type}"
    elif detail_str:
        return f"[{time_str}] {event_type}: {detail_str}"
    else:
        return f"[{time_str}] {event_type}"


def _build_run_summary(run_dir: Path) -> Dict:
    """Read events from a run directory and compute summary."""
    events_file = run_dir / "events.jsonl"
    events = load_events(events_file)

    run_id = run_dir.name
    state = _derive_run_state(events)

    # Extract spec_id from events
    spec_id = None
    for e in events:
        sid = e.get("spec_id")
        if sid:
            spec_id = sid
            break

    # Extract spec title from events (loop_started often has it)
    spec_title = None
    for e in events:
        if e.get("event") == "loop_started":
            spec_title = e.get("spec_title") or e.get("title")
            if not spec_id:
                spec_id = e.get("spec_id")
            break

    # Compute elapsed time
    elapsed = 0.0
    first_ts = None
    last_ts = None
    for e in events:
        ts = e.get("ts", "")
        if ts:
            try:
                ts_clean = ts.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_clean)
                if first_ts is None or dt < first_ts:
                    first_ts = dt
                if last_ts is None or dt > last_ts:
                    last_ts = dt
            except (ValueError, AttributeError):
                continue
    if first_ts and last_ts:
        elapsed = (last_ts - first_ts).total_seconds()

    # Current/last step
    current_step = None
    current_step_name = None
    step_elapsed = 0.0
    total_steps = len(STEP_NAMES)
    for e in reversed(events):
        step = e.get("step")
        if isinstance(step, int):
            current_step = step
            current_step_name = STEP_NAMES.get(step, f"step-{step}")
            # Compute step elapsed
            step_ts = e.get("ts", "")
            if step_ts and last_ts:
                try:
                    ts_clean = step_ts.replace("Z", "+00:00")
                    step_dt = datetime.fromisoformat(ts_clean)
                    step_elapsed = (last_ts - step_dt).total_seconds()
                except (ValueError, AttributeError):
                    pass
            break

    # Last event
    last_event = events[-1] if events else None

    return {
        "run_id": run_id,
        "state": state,
        "spec_id": spec_id,
        "spec_title": spec_title,
        "elapsed": elapsed,
        "elapsed_formatted": _format_duration(elapsed),
        "current_step": current_step,
        "current_step_name": current_step_name,
        "step_elapsed": step_elapsed,
        "step_elapsed_formatted": _format_duration(step_elapsed),
        "total_steps": total_steps,
        "event_count": len(events),
        "last_event": _format_event_line(last_event) if last_event else None,
    }


def _print_run_summary(summary: Dict) -> None:
    """Print a formatted run summary."""
    run_id = summary["run_id"]
    state = summary["state"]
    spec_id = summary.get("spec_id") or "unknown"
    spec_title = summary.get("spec_title")
    elapsed_fmt = summary["elapsed_formatted"]
    current_step = summary.get("current_step")
    current_step_name = summary.get("current_step_name")
    step_elapsed_fmt = summary.get("step_elapsed_formatted", "")
    total_steps = summary.get("total_steps", 16)
    last_event = summary.get("last_event")

    spec_str = spec_id
    if spec_title:
        spec_str = f"{spec_id} ({spec_title})"

    print(f"Run:      {run_id}")
    print(f"State:    {state}")
    print(f"Spec:     {spec_str}")
    if current_step is not None:
        print(f"Step:     {current_step}/{total_steps} — {current_step_name} ({step_elapsed_fmt})")
    print(f"Elapsed:  {elapsed_fmt}")
    if last_event:
        print(f"Last:     {last_event}")


def status_command(args) -> int:
    """Show run status and observability.

    Returns exit code (0).
    """
    nightshift_dir = Path(args.nightshift_dir).resolve()
    json_output = getattr(args, 'json_output', False)
    follow_mode = getattr(args, 'follow', False)
    run_id = getattr(args, 'run_id', None)
    history_mode = getattr(args, 'history', False)

    runs = _discover_runs(nightshift_dir)

    # No runs at all
    if not runs:
        if json_output:
            print(json.dumps({"message": "No runs found", "runs": []}))
        else:
            print("No runs found in", nightshift_dir / "runs")
            print("Run a Nightshift loop first to generate run data.")
        return 0

    # --history mode
    if history_mode:
        summaries = [_build_run_summary(r) for r in runs]
        if json_output:
            print(json.dumps(summaries, indent=2))
        else:
            # Table format
            print(f"{'Run ID':<30} {'State':<14} {'Spec':<12} {'Elapsed':<10}")
            print("-" * 66)
            for s in summaries:
                print(f"{s['run_id']:<30} {s['state']:<14} {s.get('spec_id') or '-':<12} {s['elapsed_formatted']:<10}")
        return 0

    # --run <id> mode
    if run_id:
        # Find matching run
        match = None
        for r in runs:
            if r.name == run_id:
                match = r
                break
        if not match:
            if json_output:
                print(json.dumps({"error": f"Run {run_id} not found"}))
            else:
                print(f"Run {run_id} not found.")
            return 1

        summary = _build_run_summary(match)
        if json_output:
            print(json.dumps(summary, indent=2))
        else:
            _print_run_summary(summary)
        return 0

    # --follow mode
    if follow_mode:
        latest_run = runs[0]
        events_file = latest_run / "events.jsonl"
        seen_count = 0
        idle_start = time.time()
        max_idle = 60.0

        # First, print any existing events
        existing = load_events(events_file)
        for ev in existing:
            if json_output:
                print(json.dumps(ev))
            else:
                print(_format_event_line(ev))
        seen_count = len(existing)

        # Check if already completed
        if existing:
            state = _derive_run_state(existing)
            if state == "completed":
                return 0

        # Poll for new events
        while True:
            current = load_events(events_file)
            if len(current) > seen_count:
                for ev in current[seen_count:]:
                    if json_output:
                        print(json.dumps(ev))
                    else:
                        print(_format_event_line(ev))
                seen_count = len(current)
                idle_start = time.time()

                # Check for loop_ended
                state = _derive_run_state(current)
                if state == "completed":
                    return 0

            # Check idle timeout
            if time.time() - idle_start > max_idle:
                if not json_output:
                    print("(idle timeout — 60s with no new events)")
                return 0

            time.sleep(0.5)

    # Default: show most recent run summary
    latest_run = runs[0]
    summary = _build_run_summary(latest_run)
    if json_output:
        print(json.dumps(summary, indent=2))
    else:
        _print_run_summary(summary)

    return 0


def _resolve_history_db_dir(arg_value: Optional[str]) -> Optional[Path]:
    """Map the --db-dir CLI arg to an execution_history db_dir override."""
    if arg_value is None:
        return None
    return Path(arg_value).expanduser().resolve()


def _split_project_filter(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Heuristic for --project: if the value looks like a filesystem path
    (contains '/') return it as the path filter; otherwise treat it as a
    project name filter. Returns (name, path) with one side set.
    """
    if value is None:
        return None, None
    if "/" in value or value.startswith("~"):
        return None, str(Path(value).expanduser())
    return value, None


def history_command(args) -> int:
    """Implement `nightshift-dag history` (list recent runs)."""
    try:
        from execution_history import query_runs, SchemaVersionError
    except ImportError as exc:  # pragma: no cover — canonical on sys.path
        print(f"error: could not import execution_history: {exc}", file=sys.stderr)
        return 2

    db_dir = _resolve_history_db_dir(getattr(args, "db_dir", None))
    name_filter, path_filter = _split_project_filter(args.project)

    # query_runs filters by name exactly; path-form filters are applied after.
    try:
        rows = query_runs(
            project=name_filter,
            since=args.since,
            status=args.status,
            limit=max(1, int(args.limit)) if args.limit else 50,
            db_dir=db_dir,
        )
    except SchemaVersionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summaries = [r.to_dict() for r in rows]

    if path_filter is not None:
        # Post-filter by nightshift_dir (which is derived from project root)
        # — query_runs doesn't expose that column in RunSummary, so fetch
        # the raw column via a secondary lookup. Small, pragmatic.
        from execution_history import _get_connection  # noqa: PLC0415
        conn = _get_connection(db_dir)
        try:
            keep_ids = set()
            placeholders = ",".join("?" * len(summaries)) or "''"
            if summaries:
                ids = [s["run_id"] for s in summaries]
                cur = conn.execute(
                    f"SELECT run_id FROM runs WHERE nightshift_dir LIKE ? "
                    f"AND run_id IN ({placeholders})",
                    [f"%{path_filter}%"] + ids,
                )
                keep_ids = {r[0] for r in cur.fetchall()}
            summaries = [s for s in summaries if s["run_id"] in keep_ids]
        finally:
            conn.close()

    if args.table:
        _print_history_table(summaries)
    else:
        print(json.dumps(summaries, indent=2))
    return 0


def history_failures_command(args) -> int:
    """Implement `nightshift-dag history failures` (grouped by error_type)."""
    try:
        from execution_history import query_failures, SchemaVersionError
    except ImportError as exc:  # pragma: no cover
        print(f"error: could not import execution_history: {exc}", file=sys.stderr)
        return 2

    db_dir = _resolve_history_db_dir(getattr(args, "db_dir", None))
    name_filter, _path_filter = _split_project_filter(args.project)

    try:
        rows = query_failures(
            project=name_filter,
            limit=max(1, int(args.limit)) if args.limit else 200,
            db_dir=db_dir,
        )
    except SchemaVersionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rows_dicts = [r.to_dict() for r in rows]

    # Optional pre-filter
    if getattr(args, "error_type", None):
        rows_dicts = [r for r in rows_dicts if r.get("error_type") == args.error_type]

    # Group by error_type
    buckets: Dict[str, Dict[str, object]] = {}
    for r in rows_dicts:
        et = r.get("error_type") or "unclassified"
        bucket = buckets.setdefault(et, {"error_type": et, "count": 0, "examples": []})
        bucket["count"] = int(bucket["count"]) + 1
        examples = bucket["examples"]
        assert isinstance(examples, list)
        if len(examples) < 5:
            examples.append({
                "spec_id": r.get("spec_id"),
                "run_id": r.get("run_id"),
                "project": r.get("project"),
                "status": r.get("status"),
                "completed_at": r.get("completed_at"),
            })

    grouped = sorted(
        buckets.values(), key=lambda b: int(b["count"]), reverse=True  # type: ignore[arg-type]
    )

    if args.table:
        if not grouped:
            print("(no failures recorded)")
        else:
            print(f"{'error_type':<30} {'count':>6}")
            print("-" * 37)
            for b in grouped:
                print(f"{str(b['error_type']):<30} {int(b['count']):>6}")  # type: ignore[arg-type]
    else:
        print(json.dumps(grouped, indent=2))
    return 0


def _print_history_table(summaries: List[Dict]) -> None:
    """Compact human-readable table for `history --table`."""
    if not summaries:
        print("(no runs recorded)")
        return
    print(
        f"{'run_id':<34} {'project':<20} {'start_time':<22} "
        f"{'outcome':<10} {'specs':>8}"
    )
    print("-" * 100)
    for s in summaries:
        specs = f"{s.get('specs_completed', 0)}/{s.get('specs_attempted', 0)}"
        print(
            f"{str(s.get('run_id', ''))[:33]:<34} "
            f"{str(s.get('project', ''))[:19]:<20} "
            f"{str(s.get('start_time', ''))[:21]:<22} "
            f"{str(s.get('outcome', ''))[:9]:<10} "
            f"{specs:>8}"
        )


def dispatch_spec_command(args) -> int:
    """Execute the 'dispatch-spec' command (SPEC-041).

    Resolves the given spec's ``effective_domain`` and routes it through the
    handler registry. Prints the ``Outcome`` (augmented with dispatch
    metadata) as JSON on stdout.

    Exit code:
        0 — handler executed and returned an ``Outcome`` with status
            ``success`` or ``skipped``.
        1 — spec not found, load error, or ``Outcome.status`` indicates
            failure / blocked.
    """
    from handler_registry import HandlerContext, create_default_registry, load_custom_handlers
    from dispatch import dispatch_spec as _dispatch_spec
    from loop_events import open_run_log

    try:
        specs_dir = resolve_specs_dir(args.specs_dir)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Locate the spec file by ID. Use yaml.safe_load so the full frontmatter
    # (including ``effective_domain`` / ``domain`` / custom fields) is
    # available to the dispatcher — the regex parser only exposes known keys.
    spec_file: Optional[Path] = None
    spec_frontmatter: Dict = {}
    for candidate in specs_dir.glob("*.md"):
        try:
            yaml_text, _ = _extract_frontmatter_and_body(candidate)
        except ValueError:
            continue
        try:
            data = yaml.safe_load(yaml_text) or {}
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and data.get("id") == args.spec_id:
            spec_file = candidate
            spec_frontmatter = data
            break

    if spec_file is None:
        print(
            f"Error: spec {args.spec_id} not found under {specs_dir}",
            file=sys.stderr,
        )
        return 1

    # Optional config load (for custom handlers + runner.domain fallback).
    config: Dict = {}
    if args.config:
        try:
            config = yaml.safe_load(Path(args.config).read_text()) or {}
        except (OSError, yaml.YAMLError) as exc:
            print(f"Error: cannot read config {args.config}: {exc}", file=sys.stderr)
            return 1

    # Build a per-invocation event log so CLI callers still get events.jsonl
    # for inspection (used by test_ac6).
    nightshift_dir = Path(args.nightshift_dir).resolve()
    run_log = open_run_log(nightshift_dir)

    registry = create_default_registry()
    if config.get("handlers"):
        try:
            load_custom_handlers(registry, config)
        except Exception as exc:  # noqa: BLE001 — CLI wrapper mirrors LOOP preflight
            run_log.emit(
                "custom_handler_load_failed",
                spec_id=args.spec_id,
                error=str(exc),
            )

    ctx = HandlerContext(
        project_root=specs_dir.parent,
        spec_path=spec_file,
        events_logger=run_log,
        config=config,
        checkpoint_dir=nightshift_dir / "checkpoints",
    )

    outcome = _dispatch_spec(spec_frontmatter, registry, ctx, config=config)

    # Re-resolve the effective domain for the reporting payload; the event
    # log already has the authoritative record.
    from dispatch import resolve_effective_domain

    resolution = resolve_effective_domain(spec_frontmatter, config)
    # If fallback happened, the domain in the handler_selected event is "code",
    # not the unresolved string — read it back from the log.
    selected_events = [
        e for e in run_log.read_all() if e.get("event") == "handler_selected"
    ]
    effective_domain = (
        selected_events[-1]["effective_domain"] if selected_events else resolution.domain
    )
    handler_class_name = (
        selected_events[-1]["handler_class_name"] if selected_events else ""
    )

    payload = {
        "spec_id": args.spec_id,
        "effective_domain": effective_domain,
        "handler_class_name": handler_class_name,
        "status": outcome.status,
        "artifacts": list(outcome.artifacts),
        "metrics": dict(outcome.metrics),
        "next_action": outcome.next_action,
        "run_id": run_log.run_id,
        "events_file": str(run_log.events_file),
    }
    print(json.dumps(payload, indent=2))

    return 0 if outcome.status in {"success", "skipped"} else 1


# ---------------------------------------------------------------------------
# SPEC-046 — `attempts SPEC-ID` CLI subcommand
# ---------------------------------------------------------------------------


def _find_spec_file_by_id(spec_id: str, specs_dir: Optional[str]) -> Optional[Path]:
    """Locate a spec file given its ID.

    Search order:
      1. Explicit ``--specs-dir`` when provided.
      2. The canonical ``specs/`` dir next to this script.
      3. ``plans/specs/`` in the project root (two levels up from canonical).
      4. ``eval-specs/`` in the project root (SPEC-046 R4 — opt-out specs).
    """
    candidates: List[Path] = []
    if specs_dir:
        candidates.append(Path(specs_dir))

    script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir / "specs")

    project_root = script_dir.parent
    candidates.append(project_root / "plans" / "specs")
    candidates.append(project_root / "eval-specs")

    # Walk up to three levels for external projects that use this script.
    cwd = Path.cwd()
    for depth in range(3):
        base = cwd if depth == 0 else cwd.parents[depth - 1]
        candidates.append(base / "plans" / "specs")
        candidates.append(base / ".nightshift" / "specs")

    seen: set = set()
    for directory in candidates:
        if not directory.is_dir():
            continue
        resolved = directory.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        for candidate in sorted(directory.glob("*.md")):
            try:
                fm_text, _ = _extract_frontmatter_and_body(candidate)
            except ValueError:
                continue
            # Fast path — id appears as a frontmatter line.
            import re as _re
            match = _re.search(r"(?m)^id:\s*([^\s#]+)", fm_text)
            if match and match.group(1).strip() == spec_id:
                return candidate

    return None


def attempts_command(args) -> int:
    """Print the full prior_attempts history for a spec (SPEC-046 R5)."""
    # Late import so test suites that don't touch this subcommand don't pay
    # the yaml cost twice. spec_frontmatter already imports yaml.
    from spec_frontmatter import load_attempts_history

    spec_file: Optional[Path]
    if args.spec_file:
        spec_file = Path(args.spec_file)
        if not spec_file.exists():
            print(f"spec file not found: {spec_file}", file=sys.stderr)
            return 2
    else:
        spec_file = _find_spec_file_by_id(args.spec_id, args.specs_dir)
        if spec_file is None:
            print(f"could not locate spec {args.spec_id}", file=sys.stderr)
            return 2

    entries = load_attempts_history(spec_file)

    if args.json_output:
        print(json.dumps(
            {"spec_id": args.spec_id, "spec_file": str(spec_file), "attempts": entries},
            indent=2,
            ensure_ascii=False,
        ))
        return 0

    print(f"Prior attempts for {args.spec_id} ({spec_file})")
    print("=" * 72)
    if not entries:
        print("(no attempts recorded)")
        return 0

    # Format:  # | date | outcome | failure_hint
    header = f"{'#':>3}  {'date':<25}  {'outcome':<18}  failure_hint"
    print(header)
    print("-" * len(header))
    for entry in entries:
        attempt = str(entry.get("attempt", "?"))
        date = str(entry.get("date", ""))[:25]
        outcome = str(entry.get("outcome", ""))[:18]
        hint = str(entry.get("failure_hint", ""))
        print(f"{attempt:>3}  {date:<25}  {outcome:<18}  {hint}")
    print()
    print(f"Total: {len(entries)} attempt(s)")
    return 0


def main():
    """Parse arguments and dispatch to CLI subcommands."""
    parser = argparse.ArgumentParser(
        description="Nightshift DAG — Offline Dependency Graph & Execution Plan Builder"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Compute and write execution plan")
    plan_parser.add_argument("spec_id", help="Main spec ID (e.g., SPEC-004)")
    plan_parser.add_argument("--debug", action="store_true", help="Verbose output")
    plan_parser.add_argument("--specs-dir", default=None, help="Path to specs directory")
    plan_parser.add_argument("--parallel", action="store_true", help="Include parallel execution layers in plan")

    admission_parser = subparsers.add_parser(
        "admission", help="Compute and persist the current dynamic admission frontier"
    )
    admission_parser.add_argument("--specs-dir", default=None, help="Path to specs directory")
    admission_parser.add_argument("--worker-limit", type=int, default=None, help="Maximum concurrent workers")
    admission_parser.add_argument("--config", default=None, help="Optional config.yaml supplying parallel_admission defaults")
    admission_parser.add_argument(
        "--missing-touches-policy",
        choices=("exclusive", "allow"),
        default=None,
        help="How missing or coarse touches declarations affect parallel admission",
    )

    validate_parser = subparsers.add_parser(
        "validate", help="Check consistency only (no file written)"
    )
    validate_parser.add_argument("spec_id", help="Main spec ID")
    validate_parser.add_argument("--debug", action="store_true", help="Verbose output")
    validate_parser.add_argument("--specs-dir", default=None, help="Path to specs directory")

    validate_spec_parser = subparsers.add_parser(
        "validate-spec", help="Validate a single spec file for loop readiness"
    )
    validate_spec_parser.add_argument("spec_file", help="Path to the spec file")

    graph_parser = subparsers.add_parser("graph", help="Show full spec graph with stacking metadata (SPEC-054)")
    graph_parser.add_argument("--specs-dir", default=None, help="Path to specs directory")
    graph_parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON")

    next_parser = subparsers.add_parser("next", help="Suggest unblocked ready specs (SPEC-054)")
    next_parser.add_argument("--specs-dir", default=None, help="Path to specs directory")
    next_parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON")

    resolve_model_parser = subparsers.add_parser(
        "resolve-model", help="Resolve a spec's model selection from config"
    )
    resolve_model_parser.add_argument("spec_file", help="Path to the spec file")
    resolve_model_parser.add_argument(
        "--config", required=True, help="Path to config.yaml"
    )

    runtime_cycles_parser = subparsers.add_parser(
        "detect-runtime-cycles",
        help="Detect retry-loop cycles from Nightshift events.jsonl",
    )
    runtime_cycles_parser.add_argument(
        "--events", required=True, help="Path to events.jsonl"
    )

    ingest_parser = subparsers.add_parser("ingest", help="Generate a spec from a description")
    ingest_parser.add_argument("description", help="Natural language spec description")
    ingest_parser.add_argument("--specs-dir", default=None, help="Path to specs directory")

    # --- dispatch-spec — SPEC-041 handler registry dispatch ---
    dispatch_parser = subparsers.add_parser(
        "dispatch-spec",
        help="Dispatch a spec through the handler registry and print the Outcome (SPEC-041)",
    )
    dispatch_parser.add_argument("spec_id", help="Spec ID (e.g., SPEC-TEST-001)")
    dispatch_parser.add_argument(
        "--specs-dir",
        default=None,
        help="Path to specs directory (auto-resolved if omitted)",
    )
    dispatch_parser.add_argument(
        "--config",
        default=None,
        help="Optional path to config.yaml for custom handler loading",
    )
    dispatch_parser.add_argument(
        "--nightshift-dir",
        default=".nightshift",
        help="Nightshift state directory (events.jsonl lives here)",
    )

    status_parser = subparsers.add_parser("status", help="Show run status and observability")
    status_parser.add_argument("--follow", action="store_true", help="Tail live events")
    status_parser.add_argument("--run", dest="run_id", help="Show specific run")
    status_parser.add_argument("--history", action="store_true", help="List recent runs")
    status_parser.add_argument("--json", action="store_true", dest="json_output", help="JSON output")
    status_parser.add_argument("--nightshift-dir", default=".nightshift", help="Nightshift directory")

    # --- history — cross-project run history DB (SPEC-040) ---
    history_parser = subparsers.add_parser(
        "history",
        help="Query the cross-project execution history DB (~/.nightshift/history.db)",
    )
    history_parser.add_argument(
        "--project",
        default=None,
        help="Filter by project name or project/nightshift path "
        "(heuristic: value containing '/' is treated as a path)",
    )
    history_parser.add_argument(
        "--status",
        default=None,
        help="Filter by run outcome (e.g. 'completed', 'failed', 'blocked')",
    )
    history_parser.add_argument(
        "--since",
        default=None,
        help="Only runs with start_time >= SINCE (ISO 8601)",
    )
    history_parser.add_argument(
        "--limit", type=int, default=50, help="Maximum rows returned (default 50)"
    )
    history_parser.add_argument(
        "--table", action="store_true", help="Human-readable tabular output (default is JSON)"
    )
    history_parser.add_argument(
        "--db-dir",
        default=None,
        help="Override history DB directory (defaults to ~/.nightshift)",
    )
    history_subparsers = history_parser.add_subparsers(dest="history_subcommand")

    failures_parser = history_subparsers.add_parser(
        "failures",
        help="Aggregate non-completed spec results grouped by error_type",
    )
    failures_parser.add_argument(
        "--project",
        default=None,
        help="Filter by project name or path (heuristic)",
    )
    failures_parser.add_argument(
        "--error-type",
        default=None,
        help="Filter to a specific error_type before grouping",
    )
    failures_parser.add_argument(
        "--limit", type=int, default=200, help="Row sample cap before grouping (default 200)"
    )
    failures_parser.add_argument(
        "--table", action="store_true", help="Human-readable tabular output (default is JSON)"
    )
    failures_parser.add_argument(
        "--db-dir",
        default=None,
        help="Override history DB directory (defaults to ~/.nightshift)",
    )

    # --- attempts — print a spec's prior_attempts history (SPEC-046) ---
    attempts_parser = subparsers.add_parser(
        "attempts",
        help="Show a spec's prior_attempts history (frontmatter + archive)",
    )
    attempts_parser.add_argument("spec_id", help="Spec ID (e.g., SPEC-046)")
    attempts_parser.add_argument(
        "--spec-file",
        dest="spec_file",
        default=None,
        help="Explicit spec file path (bypasses ID lookup)",
    )
    attempts_parser.add_argument(
        "--specs-dir",
        default=None,
        help="Override specs directory for the ID lookup",
    )
    attempts_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit JSON instead of a human table",
    )

    args = parser.parse_args()

    if args.command == "plan":
        exit_code = plan(args)
    elif args.command == "admission":
        exit_code = admission(args)
    elif args.command == "validate":
        exit_code = validate(args)
    elif args.command == "validate-spec":
        exit_code = validate_spec(args)
    elif args.command == "graph":
        exit_code = graph_command(args)
    elif args.command == "next":
        exit_code = next_command(args)
    elif args.command == "resolve-model":
        exit_code = resolve_model_command(args)
    elif args.command == "detect-runtime-cycles":
        exit_code = detect_runtime_cycles(args)
    elif args.command == "ingest":
        exit_code = ingest(args)
    elif args.command == "dispatch-spec":
        exit_code = dispatch_spec_command(args)
    elif args.command == "status":
        exit_code = status_command(args)
    elif args.command == "history":
        if getattr(args, "history_subcommand", None) == "failures":
            exit_code = history_failures_command(args)
        else:
            exit_code = history_command(args)
    elif args.command == "attempts":
        exit_code = attempts_command(args)
    else:
        parser.print_help()
        exit_code = 2

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
