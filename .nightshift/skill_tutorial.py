"""Render the read-only Nightshift command tutorial from SKILL.md's registry."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import Any


REGISTRY_FENCE = "<!-- nightshift-commands-registry -->"
REGISTRY_PATTERN = re.compile(
    rf"{re.escape(REGISTRY_FENCE)}\s*```yaml\n(.*?)\n```",
    re.DOTALL,
)
LIFECYCLE = "draft → ready → in_progress → done | blocked"


def _scalar(value: str) -> Any:
    """Parse the small, deliberately constrained YAML subset used by the registry."""
    value = value.strip()
    if value == "[]":
        return []
    if value.startswith("[") and value.endswith("]"):
        return [item.strip().strip('"') for item in value[1:-1].split(",") if item.strip()]
    return value.strip('"')


def _parse_registry_yaml(text: str) -> dict[str, list[dict[str, Any]]]:
    """Parse the registry without adding a runtime dependency to a help command.

    The fenced registry intentionally permits only ``commands``, list rows, and
    scalar/list field values.  Rejecting broader YAML keeps this parser honest.
    """
    commands: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line == "commands:":
            continue
        row = re.fullmatch(r"  - ([a-z_]+): (.+)", line)
        field = re.fullmatch(r"    ([a-z_]+): (.+)", line)
        if row:
            current = {row.group(1): _scalar(row.group(2))}
            commands.append(current)
        elif field and current is not None:
            current[field.group(1)] = _scalar(field.group(2))
        elif line.strip():
            raise ValueError("commands registry uses unsupported YAML syntax")
    return {"commands": commands}


def load_registry(skill_path: Path) -> list[dict[str, Any]]:
    """Load and validate the sole machine-readable commands registry."""
    match = REGISTRY_PATTERN.search(skill_path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError("SKILL.md is missing the nightshift commands registry")
    parsed = _parse_registry_yaml(match.group(1))
    commands = parsed.get("commands") if isinstance(parsed, dict) else None
    if not isinstance(commands, list) or not commands:
        raise ValueError("commands registry must contain a non-empty commands list")
    required = {"name", "one_liner", "options", "when_to_use", "side_effects", "not_when", "asks", "example"}
    names: set[str] = set()
    for entry in commands:
        if not isinstance(entry, dict) or required - set(entry):
            raise ValueError("each commands registry row must include tutorial fields")
        name = entry["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z-]+", name) or name in names:
            raise ValueError("commands registry names must be unique lowercase command names")
        if not isinstance(entry["options"], list) or not all(isinstance(option, str) for option in entry["options"]):
            raise ValueError(f"commands registry options must be a list for {name}")
        names.add(name)
    return commands


def validate_registry_consistency(skill_path: Path) -> None:
    """Raise when the registry and documented command headings diverge."""
    registry_names = {entry["name"] for entry in load_registry(skill_path)}
    headings = set(
        re.findall(
            r"^## `/nightshift ([a-z-]+)(?: [^`]*)?`",
            skill_path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )
    if registry_names != headings:
        missing = sorted(headings - registry_names)
        extra = sorted(registry_names - headings)
        raise ValueError(f"command registry drift: missing={missing}; extra={extra}")


def invocation(command: str, harness: str) -> str:
    prefix = "$nightshift" if harness == "codex" else "/nightshift"
    return f"{prefix} {command}".rstrip()


def _options(entry: dict[str, Any]) -> str:
    options = entry["options"]
    return ", ".join(options) if options else "none"


def render_overview(commands: list[dict[str, Any]], harness: str) -> str:
    lines = [
        "Nightshift is a spec-first development loop: it turns an approved spec into tested, reviewed, traceable work while keeping lifecycle and release evidence explicit.",
        "",
        f"Lifecycle: {LIFECYCLE}",
        "",
        "Commands",
        "| Command | Use it when… | Options |",
        "| --- | --- | --- |",
    ]
    for entry in commands:
        lines.append(
            f"| `{invocation(entry['name'], harness)}` | {entry['one_liner']} | {_options(entry)} |"
        )
    lines.extend(
        [
            "",
            "Available commands",
            *(
                f"{invocation(entry['name'], harness)} — {entry['one_liner']}"
                for entry in commands
            ),
            "",
            "Decision tree",
            f"- New project → `{invocation('init', harness)}`",
            f"- Existing code → `{invocation('retrofit', harness)}`",
            f"- Want work done → `{invocation('spec', harness)}` then `{invocation('kickoff', harness)}`",
            f"- Run blocked → `{invocation('unblock <spec-id>', harness)}`",
            f"- Want done anyway → `{invocation('unblock <spec-id> --to-done', harness)}`",
            f"- Specs and code drifted → `{invocation('sync', harness)}`",
            f"- Something looks broken → `{invocation('doctor', harness)}` / `{invocation('validate', harness)}`",
        ]
    )
    return "\n".join(lines) + "\n"


def render_command(entry: dict[str, Any], harness: str) -> str:
    command = entry["name"]
    return "\n".join(
        [
            f"{invocation(command, harness)} — {entry['one_liner']}",
            "",
            f"Purpose: {entry['when_to_use']}",
            f"Do not use it when: {entry['not_when']}",
            f"Options: {_options(entry)}",
            f"Changes: {entry['side_effects']}",
            f"It will ask: {entry['asks']}",
            f"Worked example: {entry['example']}",
            "",
        ]
    )


def render_tutorial(skill_path: Path, command: str | None, harness: str) -> str:
    commands = load_registry(skill_path)
    if command in {None, ""}:
        return render_overview(commands, harness)
    selected = "tutorial" if command == "help" else command
    for entry in commands:
        if entry["name"] == selected:
            return render_command(entry, harness)
    raise ValueError(f"unknown Nightshift tutorial command: {command}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", help="optional Nightshift command name")
    parser.add_argument("--harness", choices=("claude", "codex", "other"), default="other")
    parser.add_argument(
        "--skill",
        type=Path,
        default=Path(__file__).parent / "Skills" / "nightshift" / "SKILL.md",
        help="SKILL.md containing the registry (read only)",
    )
    args = parser.parse_args(argv)
    try:
        print(render_tutorial(args.skill, args.command, args.harness), end="")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
