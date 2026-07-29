"""Registry-backed Nightshift vocabulary exports and deterministic coherence audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import yaml

ROOT = Path(__file__).parent
REGISTRY_PATH = ROOT / "vocabulary-registry.yaml"

def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("concepts"), list):
        raise ValueError(f"invalid vocabulary registry: {path}")
    keys = [item.get("key") for item in data["concepts"] if isinstance(item, dict)]
    if len(keys) != len(set(keys)) or any(not isinstance(key, str) or not key for key in keys):
        raise ValueError("registry concepts need unique non-empty keys")
    for concept in data["concepts"]:
        missing = {"key", "label", "short_help", "definition", "applicability", "values"} - set(concept)
        if missing:
            raise ValueError(f"registry concept {concept.get('key')!r} missing {sorted(missing)}")
    return data

def concept_map(registry: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    registry = registry or load_registry()
    return {item["key"]: item for item in registry["concepts"]}

def export_json(registry: dict[str, Any] | None = None) -> str:
    registry = registry or load_registry()
    return json.dumps({"schema_version": 1, "registry_version": registry["version"], "concepts": registry["concepts"]}, indent=2, sort_keys=True) + "\n"

def export_markdown(registry: dict[str, Any] | None = None) -> str:
    registry = registry or load_registry()
    rows = ["# Nightshift Spec Vocabulary", "", "**Canonical source:** `vocabulary-registry.yaml` (version %s)." % registry["version"], "", "This generated entry point is checked by `vocabulary.py audit`; consumer-specific examples may add context but must not redefine these terms.", "", "| Key | Label | Short help | Allowed values |", "|---|---|---|---|"]
    for item in registry["concepts"]:
        values = ", ".join(str(value) for value in item["values"]) or "—"
        rows.append(f"| `{item['key']}` | {item['label']} | {item['short_help']} | {values} |")
    rows.extend(["", "## Registry-derived definitions", ""])
    for item in registry["concepts"]:
        rows.extend([f"### {item['label']}", "", item["definition"], ""])
    return "\n".join(rows)

def write_exports(directory: Path = ROOT) -> tuple[Path, Path]:
    registry = load_registry(directory / "vocabulary-registry.yaml")
    json_path, markdown_path = directory / "vocabulary.json", directory / "VOCABULARY.md"
    json_path.write_text(export_json(registry), encoding="utf-8")
    markdown_path.write_text(export_markdown(registry), encoding="utf-8")
    return json_path, markdown_path

def audit(directory: Path = ROOT) -> list[dict[str, str]]:
    registry = load_registry(directory / "vocabulary-registry.yaml")
    concepts = concept_map(registry)
    issues: list[dict[str, str]] = []
    expected = export_markdown(registry)
    vocab = directory / "VOCABULARY.md"
    if not vocab.exists() or vocab.read_text(encoding="utf-8") != expected:
        issues.append({"term": "VOCABULARY.md", "consumer": "documentation", "source": str(vocab), "location": "generated export", "expected": "registry-derived Markdown", "observed": "missing or stale export"})
    for consumer in registry.get("consumers", []):
        path = directory / consumer["path"]
        if not path.exists():
            issues.append({"term": consumer["name"], "consumer": consumer["name"], "source": str(path), "location": "file", "expected": "registered consumer exists", "observed": "missing"})
            continue
        source = path.read_text(encoding="utf-8")
        for key in consumer.get("bindings", []):
            if key not in concepts:
                issues.append({"term": key, "consumer": consumer["name"], "source": str(path), "location": "registry binding", "expected": "registered concept", "observed": "missing registry entry"})
    return issues

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("export", "audit"))
    parser.add_argument("--directory", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.command == "export":
        json_path, markdown_path = write_exports(args.directory)
        print(json.dumps({"json": str(json_path), "markdown": str(markdown_path)}))
        return 0
    issues = audit(args.directory)
    print(json.dumps({"ok": not issues, "issues": issues}, indent=2))
    return 0 if not issues else 1

if __name__ == "__main__":
    raise SystemExit(main())
