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
import re
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional


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
    children: List[str] = field(default_factory=list)
    implementation_order: List[str] = field(default_factory=list)


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
            children=data.get("children", []),
            implementation_order=data.get("implementation_order", []),
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
        visited = set()
        rec_stack = set()
        cycles = []

        def dfs(node: str, path: List[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            if node in graph:
                for neighbor in sorted(graph[node]):
                    if neighbor not in visited:
                        dfs(neighbor, path[:])
                    elif neighbor in rec_stack:
                        # Found a cycle
                        cycle_start_idx = path.index(neighbor)
                        cycle = path[cycle_start_idx:] + [neighbor]
                        # Only add if not already found
                        if cycle not in cycles:
                            cycles.append(cycle)

            rec_stack.remove(node)

        # Start DFS from all unvisited nodes
        for node in sorted(graph.keys()):
            if node not in visited:
                dfs(node, [])

        return cycles

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
                if not nfr_file.exists():
                    if debug:
                        print(f"  Warning: NFR file {nfr_id}.md not found", file=sys.stderr)
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

    # Write execution plan
    if args.debug:
        print("\nWriting execution-plan.json...")

    plan_file = specs_dir / "execution-plan.json"
    try:
        with open(plan_file, "w") as f:
            f.write(plan.to_json())
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


def main():
    """Parse arguments and dispatch to plan or validate."""
    parser = argparse.ArgumentParser(
        description="Nightshift DAG — Offline Dependency Graph & Execution Plan Builder"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Compute and write execution plan")
    plan_parser.add_argument("spec_id", help="Main spec ID (e.g., SPEC-004)")
    plan_parser.add_argument("--debug", action="store_true", help="Verbose output")
    plan_parser.add_argument("--specs-dir", default=None, help="Path to specs directory")

    validate_parser = subparsers.add_parser(
        "validate", help="Check consistency only (no file written)"
    )
    validate_parser.add_argument("spec_id", help="Main spec ID")
    validate_parser.add_argument("--debug", action="store_true", help="Verbose output")
    validate_parser.add_argument("--specs-dir", default=None, help="Path to specs directory")

    args = parser.parse_args()

    if args.command == "plan":
        exit_code = plan(args)
    elif args.command == "validate":
        exit_code = validate(args)
    else:
        parser.print_help()
        exit_code = 2

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
