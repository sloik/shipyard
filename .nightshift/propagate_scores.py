#!/usr/bin/env python3
"""
Pattern Effectiveness Score Propagation for Nightshift

Reads metrics YAML files and propagates citation data back into pattern files.
Updates Effectiveness Tracking sections with counters (Cited, Helpful, Neutral, Harmful).

Usage:
    python3 propagate_scores.py <metrics_file_or_dir> --patterns-dir <patterns_dir>
    python3 propagate_scores.py metrics/2026-03-29_001_SPEC-001.yaml --patterns-dir knowledge/patterns
    python3 propagate_scores.py metrics/ --patterns-dir knowledge/patterns

Idempotency:
    Uses .propagated marker file to track processed metrics files.
    Running the script twice on the same file won't double-count citations.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


class PatternTracker:
    """Tracks processed metrics files to ensure idempotency."""

    def __init__(self, state_file=None):
        """
        Initialize tracker.

        Args:
            state_file: Path to store processed file hashes. Defaults to .propagated in cwd.
        """
        if state_file is None:
            state_file = Path.cwd() / ".propagated"
        self.state_file = Path(state_file)
        self.processed = set()
        self._load_state()

    def _load_state(self):
        """Load state from disk."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self.processed = set(data.get("processed", []))
            except Exception:
                # If state file is corrupted, start fresh
                self.processed = set()

    def save_state(self):
        """Save state to disk."""
        data = {"processed": sorted(list(self.processed))}
        self.state_file.write_text(json.dumps(data, indent=2))

    def is_processed(self, file_path):
        """Check if file was already processed."""
        return str(Path(file_path).resolve()) in self.processed

    def mark_processed(self, file_path):
        """Mark file as processed."""
        self.processed.add(str(Path(file_path).resolve()))


class PatternPropagator:
    """Updates pattern files with effectiveness counters from metrics."""

    def __init__(self, patterns_dir):
        """
        Initialize propagator.

        Args:
            patterns_dir: Path to knowledge/patterns directory
        """
        self.patterns_dir = Path(patterns_dir)

    def update_pattern(self, pattern_name, effectiveness, last_cited):
        """
        Update a pattern's Effectiveness Tracking section.

        Args:
            pattern_name: Name of the pattern (filename without .md)
            effectiveness: "helpful", "neutral", or "harmful"
            last_cited: Date string (YYYY-MM-DD)

        Returns:
            True if successful, False if pattern not found
        """
        pattern_file = self.patterns_dir / f"{pattern_name}.md"

        if not pattern_file.exists():
            print(
                f"Warning: Pattern file not found: {pattern_file}",
                file=sys.stderr
            )
            return False

        content = pattern_file.read_text()

        # Look for existing Effectiveness Tracking section
        tracking_match = re.search(
            r"## Effectiveness Tracking\n((?:[^\n#]*\n)*)",
            content
        )

        if tracking_match:
            # Update existing section
            tracking_block = tracking_match.group(0)
            updated_block = self._increment_tracking(
                tracking_block,
                effectiveness,
                last_cited
            )
            content = content.replace(tracking_block, updated_block)
        else:
            # Create new section at end
            new_section = self._create_tracking_section(effectiveness, last_cited)
            content = content.rstrip() + "\n\n" + new_section

        pattern_file.write_text(content)
        return True

    def _increment_tracking(self, tracking_block, effectiveness, last_cited):
        """Increment effectiveness counters in tracking block."""
        lines = tracking_block.split("\n")
        updated_lines = []

        for line in lines:
            if line.startswith("- Last cited:"):
                updated_lines.append(f"- Last cited: {last_cited}")
            elif line.startswith("- Cited:"):
                count = self._extract_count(line)
                updated_lines.append(f"- Cited: {count + 1}")
            elif line.startswith("- Helpful:"):
                count = self._extract_count(line)
                if effectiveness == "helpful":
                    count += 1
                updated_lines.append(f"- Helpful: {count}")
            elif line.startswith("- Neutral:"):
                count = self._extract_count(line)
                if effectiveness == "neutral":
                    count += 1
                updated_lines.append(f"- Neutral: {count}")
            elif line.startswith("- Harmful:"):
                count = self._extract_count(line)
                if effectiveness == "harmful":
                    count += 1
                updated_lines.append(f"- Harmful: {count}")
            else:
                updated_lines.append(line)

        return "\n".join(updated_lines)

    def _create_tracking_section(self, effectiveness, last_cited):
        """Create a new Effectiveness Tracking section."""
        helpful = 1 if effectiveness == "helpful" else 0
        neutral = 1 if effectiveness == "neutral" else 0
        harmful = 1 if effectiveness == "harmful" else 0

        section = (
            "## Effectiveness Tracking\n"
            f"- Last cited: {last_cited}\n"
            "- Cited: 1\n"
            f"- Helpful: {helpful}\n"
            f"- Neutral: {neutral}\n"
            f"- Harmful: {harmful}\n"
        )
        return section

    @staticmethod
    def _extract_count(line):
        """Extract numeric count from tracking line."""
        match = re.search(r":\s*(\d+)", line)
        if match:
            return int(match.group(1))
        return 0


class PatternHealthReporter:
    """Generates pattern health report."""

    def __init__(self, patterns_dir):
        """
        Initialize reporter.

        Args:
            patterns_dir: Path to knowledge/patterns directory
        """
        self.patterns_dir = Path(patterns_dir)

    def generate_report(self):
        """
        Generate pattern health report.

        Returns:
            Markdown string with pattern health analysis
        """
        patterns = self._scan_patterns()

        # Sort by citation count (descending)
        patterns_by_cited = sorted(
            patterns.values(),
            key=lambda p: p["cited"],
            reverse=True
        )

        # Identify problematic patterns
        high_harmful = [
            p for p in patterns.values()
            if p["cited"] > 0 and p["harmful_rate"] > 0.3
        ]

        stale = [p for p in patterns.values() if p["cited"] == 0]

        # Build report
        report = "# Pattern Health Report\n\n"
        report += f"Generated: {datetime.now().isoformat()}\n\n"

        report += f"## Summary\n"
        report += f"- Total patterns: {len(patterns)}\n"
        report += f"- Never cited: {len(stale)}\n"
        report += f"- High harmful rate (>30%): {len(high_harmful)}\n"
        report += f"- Average cited count: {self._avg_cited(patterns):.1f}\n\n"

        report += "## Most Cited Patterns\n\n"
        for pattern in patterns_by_cited[:10]:
            if pattern["cited"] > 0:
                report += f"### {pattern['name']}\n"
                report += f"- Cited: {pattern['cited']}\n"
                report += f"- Helpful: {pattern['helpful']} ({pattern['helpful_rate']:.0%})\n"
                report += f"- Neutral: {pattern['neutral']}\n"
                report += f"- Harmful: {pattern['harmful']} ({pattern['harmful_rate']:.0%})\n"
                report += f"- Last cited: {pattern['last_cited']}\n\n"

        if high_harmful:
            report += "## High-Risk Patterns (>30% Harmful)\n\n"
            for pattern in high_harmful:
                report += f"### {pattern['name']}\n"
                report += f"- Harmful rate: {pattern['harmful_rate']:.0%}\n"
                report += f"- Citations: {pattern['cited']}\n"
                report += f"- Harmful: {pattern['harmful']}/{pattern['cited']}\n\n"

        if stale:
            report += "## Never-Cited Patterns (Stale)\n\n"
            for pattern in sorted(stale, key=lambda p: p['name']):
                report += f"- {pattern['name']}\n"
            report += "\n"

        report += "## Best Practices (100% Helpful)\n\n"
        perfect = [p for p in patterns.values() if p["cited"] > 0 and p["harmful"] == 0 and p["neutral"] == 0]
        for pattern in sorted(perfect, key=lambda p: p["cited"], reverse=True):
            report += f"- {pattern['name']} (Cited: {pattern['cited']})\n"

        return report

    def _scan_patterns(self):
        """Scan pattern directory and extract tracking data."""
        patterns = {}

        for pattern_file in sorted(self.patterns_dir.glob("*.md")):
            if pattern_file.name == "_TEMPLATE.md":
                continue

            pattern_name = pattern_file.stem
            content = pattern_file.read_text()

            # Extract tracking data
            tracking_match = re.search(
                r"## Effectiveness Tracking\n((?:[^\n#]*\n)*)",
                content
            )

            if tracking_match:
                data = self._parse_tracking_section(tracking_match.group(0))
                data["name"] = pattern_name
                patterns[pattern_name] = data
            else:
                patterns[pattern_name] = {
                    "name": pattern_name,
                    "cited": 0,
                    "helpful": 0,
                    "neutral": 0,
                    "harmful": 0,
                    "last_cited": "never",
                    "helpful_rate": 0.0,
                    "harmful_rate": 0.0,
                }

        return patterns

    @staticmethod
    def _parse_tracking_section(section):
        """Parse Effectiveness Tracking section."""
        data = {
            "cited": 0,
            "helpful": 0,
            "neutral": 0,
            "harmful": 0,
            "last_cited": "unknown",
        }

        for line in section.split("\n"):
            if line.startswith("- Last cited:"):
                data["last_cited"] = line.split(": ", 1)[1].strip()
            elif line.startswith("- Cited:"):
                data["cited"] = int(line.split(": ", 1)[1].strip())
            elif line.startswith("- Helpful:"):
                data["helpful"] = int(line.split(": ", 1)[1].strip())
            elif line.startswith("- Neutral:"):
                data["neutral"] = int(line.split(": ", 1)[1].strip())
            elif line.startswith("- Harmful:"):
                data["harmful"] = int(line.split(": ", 1)[1].strip())

        # Calculate rates
        if data["cited"] > 0:
            data["helpful_rate"] = data["helpful"] / data["cited"]
            data["harmful_rate"] = data["harmful"] / data["cited"]
        else:
            data["helpful_rate"] = 0.0
            data["harmful_rate"] = 0.0

        return data

    @staticmethod
    def _avg_cited(patterns):
        """Calculate average citation count."""
        if not patterns:
            return 0.0
        return sum(p["cited"] for p in patterns.values()) / len(patterns)


def process_metrics_file(metrics_path, patterns_dir, tracker):
    """
    Process a single metrics file and propagate scores.

    Args:
        metrics_path: Path to metrics YAML file
        patterns_dir: Path to patterns directory
        tracker: PatternTracker instance

    Returns:
        Tuple of (success: bool, message: str)
    """
    metrics_path = Path(metrics_path)

    # Check if already processed
    if tracker.is_processed(str(metrics_path)):
        return True, f"Skipped (already processed): {metrics_path.name}"

    # Read metrics file
    try:
        with open(metrics_path) as f:
            metrics = yaml.safe_load(f)
    except Exception as e:
        return False, f"Error reading metrics file: {e}"

    # Only process completed specs
    if metrics.get("status") != "completed":
        return True, f"Skipped (status={metrics.get('status')}): {metrics_path.name}"

    # Extract citations
    knowledge = metrics.get("knowledge", {})
    citations = knowledge.get("citations", [])

    if not citations:
        tracker.mark_processed(str(metrics_path))
        return True, f"No citations: {metrics_path.name}"

    # Get today's date
    today = datetime.now().strftime("%Y-%m-%d")

    # Update patterns
    propagator = PatternPropagator(patterns_dir)
    for citation in citations:
        pattern_name = citation.get("pattern")
        effectiveness = citation.get("effectiveness", "neutral")

        if not pattern_name:
            print(f"Warning: Citation missing 'pattern' field", file=sys.stderr)
            continue

        propagator.update_pattern(pattern_name, effectiveness, today)

    tracker.mark_processed(str(metrics_path))
    return True, f"Processed {len(citations)} citation(s): {metrics_path.name}"


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Propagate pattern effectiveness scores from metrics YAML"
    )
    parser.add_argument(
        "metrics",
        help="Metrics file or directory containing metrics files"
    )
    parser.add_argument(
        "--patterns-dir",
        required=True,
        help="Path to knowledge/patterns directory"
    )
    parser.add_argument(
        "--report",
        help="Output path for pattern health report (default: reports/pattern-health.md)"
    )
    parser.add_argument(
        "--state-file",
        help="Path to state file for idempotency tracking (default: .propagated)"
    )

    args = parser.parse_args()

    metrics_path = Path(args.metrics)
    patterns_dir = Path(args.patterns_dir)

    if not patterns_dir.exists():
        print(f"Error: Patterns directory not found: {patterns_dir}", file=sys.stderr)
        sys.exit(1)

    # Initialize tracker
    tracker = PatternTracker(state_file=args.state_file)

    # Process metrics
    if metrics_path.is_file():
        success, msg = process_metrics_file(metrics_path, patterns_dir, tracker)
        print(msg)
        if not success:
            sys.exit(1)
    elif metrics_path.is_dir():
        results = []
        for yaml_file in sorted(metrics_path.glob("*.yaml")) + sorted(metrics_path.glob("*.yml")):
            success, msg = process_metrics_file(yaml_file, patterns_dir, tracker)
            results.append((success, msg))
            print(msg)

        if not all(success for success, _ in results):
            sys.exit(1)
    else:
        print(f"Error: Not a file or directory: {metrics_path}", file=sys.stderr)
        sys.exit(1)

    # Save tracker state
    tracker.save_state()

    # Generate report
    reporter = PatternHealthReporter(patterns_dir)
    report = reporter.generate_report()

    # Determine output path
    if args.report:
        report_path = Path(args.report)
    else:
        report_path = Path("reports") / "pattern-health.md"

    # Ensure directory exists
    report_path.parent.mkdir(parents=True, exist_ok=True)

    # Write report
    report_path.write_text(report)
    print(f"\nPattern health report: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
