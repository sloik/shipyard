#!/usr/bin/env python3
"""Mechanical stable-checkpoint helper used by both official skill routes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml
from extension_protocol import EVENTS, ProtocolError, digest
from extension_registry import ExtensionRegistry
from extension_runtime import ExtensionRuntime, ExtensionSpool, ExtensionSupervisor
from extension_sandbox import host_backend


def _load_extensions_config(path: Path) -> dict:
    """Load only the public extension declarations from multi-document config."""
    extensions = []
    for document in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        if isinstance(document, dict) and "extensions" in document:
            extensions = document["extensions"]
    return {"extensions": extensions}


def _load_artifact_refs(path: Path | None) -> list[dict]:
    if path is None:
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ProtocolError("artifact refs file must contain a list")
    return value


def official_payload(
    *,
    event: str,
    run_kind: str,
    spec_id: str,
    outcome: str,
    config_path: Path,
    artifact_refs_path: Path | None,
) -> dict:
    """Build one closed stable payload from controlled official-route fields."""
    refs = _load_artifact_refs(artifact_refs_path)
    if event == "run.started":
        return {
            "run_kind": run_kind,
            "spec_id": spec_id,
            "config_digest": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        }
    if event == "work.completed":
        return {"spec_id": spec_id, "outcome": outcome, "artifact_refs": refs}
    if event == "verification.requested":
        return {"spec_id": spec_id, "artifact_refs": refs}
    if event == "verification.completed":
        return {"spec_id": spec_id, "outcome": outcome, "artifact_refs": refs}
    if event == "run.completed":
        return {"run_kind": run_kind, "outcome": outcome, "artifact_refs": refs}
    raise ProtocolError("unsupported official checkpoint event")


def publish_checkpoint(
    *,
    project_root: Path,
    private_root: Path,
    user_root: Path,
    run_id: str,
    sequence: int,
    event: str,
    payload: dict,
    config: dict,
    artifact_root: Path | None = None,
    experiment_observer: Any | None = None,
) -> dict:
    """Optional extension failures never alter the authoritative caller result."""
    registry = ExtensionRegistry(
        project_root / ".nightshift" / "extensions",
        user_root,
        project_id=(experiment_observer.context.project_id if experiment_observer else None),
        experiment_observer=experiment_observer,
    )
    admissions, failures = registry.admit(config, sandbox_backend=host_backend())
    if not admissions:
        # No-config is a strict no-child control. Existing orphaned work is
        # reconciled synchronously and never launches extension code. Explicit
        # unavailable enablements receive a private durable disposition.
        runtime = ExtensionRuntime(
            spool_root=private_root, run_id=run_id, admissions=()
        )
        enabled = config.get("extensions", [])
        if enabled:
            runtime.spool.record_admission_failures(failures)
        if runtime.spool.run_root.exists():
            supervisor = ExtensionSupervisor(runtime.spool, backend=host_backend())
            try:
                supervisor.recover({})
            finally:
                supervisor.shutdown()
        return {
            "status": "no-admissions",
            "failures": failures,
            "jobs": 0,
            "supervisor_started": False,
        }
    runtime = ExtensionRuntime(
        spool_root=private_root, run_id=run_id, admissions=admissions
    )
    runtime.spool.ingest_artifact_refs(payload, artifact_root)
    envelope, jobs = runtime.publish(sequence=sequence, event=event, payload=payload)
    launch_kwargs = {"run_completed": event == "run.completed"}
    if experiment_observer is not None:
        launch_kwargs["experiment_observer"] = experiment_observer
    started = launch_supervisor(runtime, admissions, jobs, **launch_kwargs)
    return {
        "status": "published",
        "event_id": envelope["event_id"],
        "jobs": len(jobs),
        "supervisor_started": started,
        "failures": failures,
    }


def launch_supervisor(
    runtime: ExtensionRuntime,
    admissions: list,
    jobs: list[Path],
    *,
    run_completed: bool,
    experiment_observer: Any | None = None,
) -> bool:
    """Fork a detached one-shot drain after durable enqueue.

    The publisher never waits for the optional jobs. The child reconstructs all
    execution authority from the already-validated in-memory admissions and the
    durable private spool; it emits no stdout/stderr and owns its descendants.
    """
    if not jobs and not runtime.spool.run_root.exists():
        return False
    try:
        pid = os.fork()
    except OSError:
        return False
    if pid:
        return True
    try:
        os.setsid()
        _detach_standard_streams()
        maximum = os.sysconf("SC_OPEN_MAX")
        os.closerange(3, min(maximum, 65536))
        drain_supervisor(runtime, admissions, experiment_observer=experiment_observer)
    finally:
        os._exit(0)


def _detach_standard_streams() -> None:
    """Stop the detached drain from retaining a caller's capture pipes."""
    devnull = os.open(os.devnull, os.O_RDWR)
    try:
        for descriptor in (0, 1, 2):
            os.dup2(devnull, descriptor)
    finally:
        if devnull > 2:
            os.close(devnull)


def drain_supervisor(
    runtime: ExtensionRuntime, admissions: list, *, experiment_observer: Any | None = None
) -> None:
    """Recover all jobs and always reap the drain's owned process tree."""
    supervisor = ExtensionSupervisor(runtime.spool, backend=host_backend())
    try:
        by_id = {item.namespace: item for item in admissions}
        # Reconstruct the durable run on every checkpoint. This includes the
        # just-enqueued jobs and any pending work left by a crashed drain.
        # Atomic claims prevent overlap with a still-live prior drain.
        futures = supervisor.recover(by_id)
        for future in futures:
            try:
                future.result()
            except Exception:  # noqa: BLE001, S112 -- optional job is contained
                continue
        if experiment_observer is not None:
            by_namespace = {item.namespace: item for item in admissions}
            for job in sorted(runtime.spool.run_root.glob("extensions/*/jobs/*")):
                terminal = job / "terminal.json"
                if not terminal.is_file() or terminal.is_symlink():
                    continue
                admission = by_namespace.get(job.parent.parent.name)
                if admission is None:
                    continue
                try:
                    state = json.loads(terminal.read_text(encoding="utf-8")).get("state")
                    correlations = {
                        "subject_digest": digest(admission.extension_id),
                        "admission_digest": admission.config_digest,
                        "job_digest": digest(job.name),
                        "run_digest": digest(runtime.spool.run_id),
                        **({"package_digest": admission.package_digest} if admission.package_digest else {}),
                        **({"plan_digest": admission.plan_digest} if admission.plan_digest else {}),
                    }
                    operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{runtime.spool.run_id}:{job.name}"))
                    experiment_observer.emit(
                        "package.runtime.job_terminal",
                        operation_id=operation_id,
                        correlations=correlations,
                        outcome="succeeded" if state in {"completed", "completed-after-run"} else "failed",
                        payload={"successful": state in {"completed", "completed-after-run"}},
                        source_class="passive",
                    )
                except Exception:
                    # Optional evidence collection never changes extension or run outcomes.
                    continue
    finally:
        supervisor.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--user-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--sequence",
        required=True,
        help="positive integer, or 'auto' for the next durable applicable event",
    )
    parser.add_argument("--event", choices=sorted(EVENTS), required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--payload-file", type=Path)
    inputs.add_argument("--official-config", type=Path)
    parser.add_argument("--config-file", type=Path)
    parser.add_argument("--run-kind", choices=("run", "kickoff"))
    parser.add_argument("--spec-id")
    parser.add_argument(
        "--outcome",
        choices=("passed", "failed", "blocked", "cancelled", "unknown"),
        default="unknown",
    )
    parser.add_argument("--artifact-refs-file", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.sequence == "auto":
            sequence = len(ExtensionSpool(args.private_root, args.run_id).events()) + 1
        else:
            sequence = int(args.sequence)
            if sequence <= 0:
                raise ProtocolError("sequence must be positive")
        if args.official_config is not None:
            if not args.run_kind or not args.spec_id:
                raise ProtocolError("official checkpoints require run kind and spec id")
            config = _load_extensions_config(args.official_config)
            payload = official_payload(
                event=args.event,
                run_kind=args.run_kind,
                spec_id=args.spec_id,
                outcome=args.outcome,
                config_path=args.official_config,
                artifact_refs_path=args.artifact_refs_file,
            )
        else:
            if args.config_file is None:
                raise ProtocolError("payload-file mode requires config-file")
            config = json.loads(args.config_file.read_text(encoding="utf-8"))
            payload = json.loads(args.payload_file.read_text(encoding="utf-8"))
        result = publish_checkpoint(
            project_root=args.project_root,
            private_root=args.private_root,
            user_root=args.user_root,
            run_id=args.run_id,
            sequence=sequence,
            event=args.event,
            payload=payload,
            config=config,
            artifact_root=args.artifact_root,
        )
    except (ProtocolError, json.JSONDecodeError, OSError, ValueError) as exc:
        try:
            ExtensionSpool(args.private_root, args.run_id).record_checkpoint_failure(
                type(exc).__name__
            )
        except OSError:
            pass
        print(
            json.dumps(
                {"status": "publication-failed", "reason": type(exc).__name__},
                sort_keys=True,
            )
        )
        # Extensions are observational. A publication failure is reported to
        # the private diagnostic channel but cannot change the authoritative
        # run command's result.
        return 0
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
