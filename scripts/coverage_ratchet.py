#!/usr/bin/env python3
"""Collect deterministic Go coverage and enforce Shipyard's checked-in floor."""

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.STDOUT)


def percentage(profile: pathlib.Path) -> float:
    line = run("go", "tool", "cover", f"-func={profile}").splitlines()[-1]
    return float(line.split()[-1].rstrip("%"))


def load(path: pathlib.Path) -> dict:
    with path.open() as source:
        return json.load(source)


def collect(report_path: pathlib.Path, profile_path: pathlib.Path, exclusions_path: pathlib.Path) -> dict:
    exclusions = {item["package"] for item in load(exclusions_path)["exclusions"]}
    packages = [package for package in run("go", "list", "./...").splitlines() if package not in exclusions]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="shipyard-coverage-") as temp:
        temp_path = pathlib.Path(temp)
        profiles = []
        for index, package in enumerate(packages):
            profile = temp_path / f"{index}.out"
            run("go", "test", "-count=1", f"-coverprofile={profile}", package)
            profiles.append(profile)
        with profile_path.open("w") as merged:
            merged.write("mode: set\n")
            for profile in profiles:
                merged.writelines(profile.read_text().splitlines(keepends=True)[1:])
        report = {
            "total": percentage(profile_path),
            "packages": {package: percentage(profile) for package, profile in zip(packages, profiles)},
        }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def changed_go_packages(base_ref: str, exclusions: set[str]) -> set[str]:
    try:
        changed = run("git", "diff", "--name-only", f"{base_ref}...HEAD", "--", "*.go").splitlines()
    except subprocess.CalledProcessError:
        return set()
    packages = set()
    for filename in changed:
        package_dir = pathlib.Path(filename).parent
        if package_dir == pathlib.Path("."):
            continue
        try:
            package = run("go", "list", f"./{package_dir}").strip()
        except subprocess.CalledProcessError:
            continue
        if package not in exclusions:
            packages.add(package)
    return packages


def check(report: dict, baseline: dict, changed_packages: set[str]) -> list[str]:
    failures = []
    if report["total"] < baseline["total"]:
        failures.append(f"total coverage {report['total']:.1f}% is below baseline {baseline['total']:.1f}%")
    for package, floor in sorted(baseline["packages"].items()):
        actual = report["packages"].get(package)
        if actual is None:
            failures.append(f"baseline package missing from report: {package}")
        elif actual < floor:
            failures.append(f"{package}: {actual:.1f}% is below baseline {floor:.1f}%")
    for package in sorted(changed_packages):
        if package not in baseline["packages"]:
            failures.append(f"changed production package has no reviewed coverage floor: {package}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("collect", "check"))
    parser.add_argument("--baseline", type=pathlib.Path, default=ROOT / ".nightshift/coverage-baseline.json")
    parser.add_argument("--report", type=pathlib.Path, default=ROOT / "build/coverage/current.json")
    parser.add_argument("--profile", type=pathlib.Path, default=ROOT / "build/coverage/coverage.out")
    parser.add_argument("--exclusions", type=pathlib.Path, default=ROOT / ".nightshift/coverage-exclusions.json")
    parser.add_argument("--base-ref", default="main")
    args = parser.parse_args()
    if args.command == "collect":
        report = collect(args.report, args.profile, args.exclusions)
        print(f"coverage total: {report['total']:.1f}%")
        for package, value in sorted(report["packages"].items()):
            print(f"coverage package: {package} {value:.1f}%")
        return 0
    report = load(args.report)
    baseline = load(args.baseline)
    exclusions = {item["package"] for item in load(args.exclusions)["exclusions"]}
    failures = check(report, baseline, changed_go_packages(args.base_ref, exclusions))
    if failures:
        print("coverage ratchet failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("coverage ratchet passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
