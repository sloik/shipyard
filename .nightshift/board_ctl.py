#!/usr/bin/env python3
"""Client for a Nightshift board: reads (SPEC-417-002) and management (SPEC-417-003).

Finds, lists, searches and inspects specs without hand-built ports, curl calls or
JSON filtering. Runs on system ``python3``: it imports no FastAPI or uvicorn, only
PyYAML and this kit's FastAPI-free modules. When the board is down, ``list``, ``show``,
``search`` and ``deps`` read the specs directory and the status store read-only.

Management: ``start|stop|restart|status`` (Control or ``board.sh --no-open``; never signals),
``board-doctor``, ``transition`` (the board's gates; commits only the spec and its artifacts) and
``validate``. Exit codes: 0 ok, 1 not found, 2 usage, 3 board unreachable for a board-only command,
4 refused by the transition policy or a gate, 5 operation failed or board-doctor found a problem.
``rules check <id>`` (SPEC-417-004) runs every machine-checkable rule against one spec, read-only (guide ``.nightshift/guides/rules.md``).
``describe --json`` lists every command; the guide is ``.nightshift/guides/board-and-api.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import socket
import string
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
GUIDE = ".nightshift/guides/board-and-api.md"
EXIT_OK, EXIT_NOT_FOUND, EXIT_USAGE, EXIT_DOWN = 0, 1, 2, 3
# SPEC-417-003: a transition the policy or a gate refuses; an operation that failed or a doctor finding.
EXIT_REFUSED, EXIT_PROBLEM = 4, 5
HTTP_TIMEOUT = 15.0
# The board's own derived keys are not spec frontmatter; they are dropped from `show`.
_DERIVED_KEYS = frozenset({
    "readiness", "readiness_evidence", "readiness_dimensions", "run_state_summary",
    "release_handoff_state",
})


# ---------------------------------------------------------------------------
# Port formula (shared with board.py, which imports it; there is no second copy)
# ---------------------------------------------------------------------------

def project_root_for_specs_dir(specs_dir: Path) -> Path:
    """The project root for a Nightshift specs directory."""
    specs_dir = Path(specs_dir)
    return specs_dir.parent.parent if specs_dir.name == "specs" else specs_dir.parent


def project_name_for_root(project_root: Path) -> str:
    """The board's project name: root directory name, leading dots stripped, upper-cased."""
    return Path(project_root).name.lstrip(".").upper() or "PROJECT"


def default_port_for_name(project_name: str) -> int:
    """The board's default port for a project name (range 7800-7999)."""
    return 7800 + sum(ord(c) for c in project_name) % 200


# ---------------------------------------------------------------------------
# Errors and output
# ---------------------------------------------------------------------------

class CtlError(Exception):
    def __init__(self, code: int, name: str, message: str, next_step: str = "") -> None:
        super().__init__(message)
        self.code, self.name, self.message, self.next_step = code, name, message, next_step


def _down(port: int, offline_ok: bool) -> CtlError:
    hint = "`board_ctl.py list` works offline; start the board with `board_ctl.py start`"
    detail = f"board not reachable on 127.0.0.1:{port}"
    if not offline_ok:
        detail += " (this command needs a running board)"
    return CtlError(EXIT_DOWN, "board_unreachable", detail, f"board down -> {hint}")


def _not_found(spec_id: str) -> CtlError:
    return CtlError(EXIT_NOT_FOUND, "spec_not_found", f"spec not found: {spec_id}",
                    "`board_ctl.py list --text <words>` or `board_ctl.py search <words>` finds the exact id")


def _emit(args: argparse.Namespace, payload: dict, text: str) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(text)


# ---------------------------------------------------------------------------
# Context: where the specs are and which port the board uses
# ---------------------------------------------------------------------------

class Ctx:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project: str | None = args.project
        self._entry: dict | None = None
        if args.project:
            self._entry = self._registry_by_name(args.project)
            if self._entry is None:
                raise CtlError(EXIT_NOT_FOUND, "project_not_found",
                               f"project not in the registry: {args.project}",
                               "names are in `.nightshift/projects-registry.json` (`name` field)")
            self.specs_dir = _specs_dir_of(_registry_path(self._entry))
        elif args.specs_dir:
            self.specs_dir = Path(args.specs_dir).resolve()
        else:
            self.specs_dir = HERE / "specs"
        self.project_root = project_root_for_specs_dir(self.specs_dir)

    # -- registry -----------------------------------------------------------
    def _registry_files(self) -> list[Path]:
        base = HERE / "specs" if not self.args.specs_dir else Path(self.args.specs_dir).resolve()
        found = []
        for cand in (base.parent / "projects-registry.json",
                     base.parent / ".nightshift" / "projects-registry.json",
                     HERE / "projects-registry.json"):
            if cand.is_file() and cand not in found:
                found.append(cand)
        return found

    def _registry_projects(self) -> list[dict]:
        for registry in self._registry_files():
            try:
                data = json.loads(registry.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            projects = data.get("projects") if isinstance(data, dict) else None
            if isinstance(projects, list):
                return [p for p in projects if isinstance(p, dict)]
        return []

    def _registry_by_name(self, name: str) -> dict | None:
        wanted = name.upper()
        return next((p for p in self._registry_projects() if str(p.get("name", "")).upper() == wanted), None)

    def _own_registry_entry(self) -> dict | None:
        # The flat canonical layout registers specs_dir.parent; an install registers the project root.
        for root in (self.specs_dir.parent, self.project_root):
            for entry in self._registry_projects():
                if _registry_path(entry).resolve() == root.resolve():
                    return entry
        return None

    # -- port ---------------------------------------------------------------
    def resolve_port(self) -> tuple[int, str]:
        if self.args.port is not None:
            return self.args.port, "flag"
        entry = self._entry or self._own_registry_entry()
        if entry is not None and isinstance(entry.get("port"), int):
            return entry["port"], "registry"
        return default_port_for_name(project_name_for_root(self.project_root)), "formula"

    # -- board access -------------------------------------------------------
    def request(self, path: str, *, method: str = "GET", timeout: float = HTTP_TIMEOUT,
                offline_ok: bool = False) -> Any:
        port, _ = self.resolve_port()
        url = f"http://127.0.0.1:{port}{path}"
        req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = {}
            raise _HttpStatus(exc.code, parsed) from None
        except (urllib.error.URLError, OSError, ValueError):
            raise _down(port, offline_ok) from None


class _HttpStatus(Exception):
    def __init__(self, status: int, body: dict) -> None:
        super().__init__(status)
        self.status, self.body = status, body


def _registry_path(entry: dict) -> Path:
    raw = str(entry.get("path", "")).replace("{{HOME}}", str(Path.home()))
    return Path(raw).expanduser()


def _specs_dir_of(project_path: Path) -> Path:
    for cand in (project_path / ".nightshift" / "specs", project_path / "specs"):
        if cand.is_dir():
            return cand.resolve()
    return (project_path / ".nightshift" / "specs").resolve()


# ---------------------------------------------------------------------------
# Offline reader: spec files + read-only store reads. Never writes the store.
# ---------------------------------------------------------------------------

def _offline_specs(specs_dir: Path) -> dict[str, dict]:
    """``{id: record}`` for every top-level ``*.md`` with an ``id``, statuses as the board shows them."""
    sys.path.insert(0, str(HERE))
    import spec_frontmatter  # noqa: PLC0415 (kept lazy so `describe` needs only the stdlib)
    import status_store  # noqa: PLC0415

    records: dict[str, dict] = {}
    if not specs_dir.is_dir():
        return records
    for name in sorted(os.listdir(specs_dir)):
        if not name.endswith(".md"):
            continue
        path = specs_dir / name
        try:
            parsed = spec_frontmatter.parse_spec_file(path)
            mtime = path.stat().st_mtime
        except (spec_frontmatter.FrontmatterError, OSError):
            continue
        fm = parsed.frontmatter
        if not fm.get("id"):
            continue
        body = parsed.body.lstrip("\n")
        title = next((ln[2:].strip() for ln in body.splitlines() if ln.startswith("# ")), "")
        records[str(fm["id"])] = {"fm": fm, "body": body, "title": title, "mtime": mtime, "path": path}
    states = status_store.read_durable_states_readonly(
        status_store.default_db_path_for_specs_dir(specs_dir), list(records))
    projections = status_store.read_terminal_projection_diagnostics_readonly(
        status_store.default_db_path_for_specs_dir(specs_dir), list(records))
    for spec_id, rec in records.items():
        file_status = str(rec["fm"].get("status", "draft"))
        view = status_store.effective_status_view(file_status, states.get(spec_id), rec["mtime"], rec["path"])
        rec["view"], rec["status"] = view, view["effective"]
        rec['terminal_projection'] = projections.get(spec_id)
    return records


def _summary(spec_id: str, fm: dict, status: str, title: str) -> dict:
    return {"id": spec_id, "status": status, "title": title or spec_id, "layer": fm.get("layer"),
            "type": fm.get("type"), "parent": fm.get("parent")}


def _board_or_offline(ctx: Ctx, path: str, offline) -> tuple[str, Any]:
    """Board answer when it is up, else the offline answer; HTTP statuses are never masked."""
    try:
        return "board", ctx.request(path, offline_ok=True)
    except CtlError as exc:
        if exc.code != EXIT_DOWN:
            raise
    return "offline", offline()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_port(ctx: Ctx, args) -> int:
    port, via = ctx.resolve_port()
    _emit(args, {"port": port, "via": via, "project": ctx.project or project_name_for_root(ctx.project_root)},
          str(port))
    return EXIT_OK


def cmd_health(ctx: Ctx, args) -> int:
    health = ctx.request("/api/health")
    health_out = {"source": "board", **health} if isinstance(health, dict) else {"source": "board", "health": health}
    _emit(args, health_out, f"{health.get('status')} specs={health.get('spec_count')} "
          f"status_sync_mismatches={health.get('status_sync_mismatches')}")
    return EXIT_OK


def _filter(rows: list[dict], args) -> list[dict]:
    out = []
    needle = (args.text or "").lower()
    for row in rows:
        if args.status and row["status"] not in args.status:
            continue
        if args.layer is not None and str(row.get("layer")) != str(args.layer):
            continue
        if args.type and row.get("type") != args.type:
            continue
        if args.parent and str(row.get("parent")) != args.parent:
            continue
        if needle and needle not in f"{row['id']} {row['title']}".lower():
            continue
        out.append(row)
    return out


def cmd_list(ctx: Ctx, args) -> int:
    def offline():
        return [_summary(i, r["fm"], r["status"], r["title"]) for i, r in _offline_specs(ctx.specs_dir).items()]

    source, data = _board_or_offline(ctx, "/api/specs", offline)
    if source == "board":
        data = [_summary(str(s["id"]), s, str(s.get("status", "draft")), s.get("_title", "")) for s in data if s.get("id")]
    rows = sorted(_filter(data, args), key=lambda r: r["id"])
    text = "\n".join([f"# source: {source}  count: {len(rows)}"] + [f"{r['id']}\t{r['status']}\t{r['title']}" for r in rows])
    _emit(args, {"source": source, "count": len(rows), "specs": rows}, text)
    return EXIT_OK


def _explain_offline(rec: dict) -> dict:
    return {"declared": rec["view"]["declared"], "effective": rec["view"]["effective"],
            "status_source": rec["view"]["source"], "sync": rec["view"]["sync"],
            "note": "offline: the full run-state explanation needs the board"}


def cmd_show(ctx: Ctx, args) -> int:
    quoted = urllib.parse.quote(args.id, safe="")
    try:
        source, data = _board_or_offline(ctx, f"/api/spec/{quoted}", lambda: None)
    except _HttpStatus as exc:
        if exc.status == 404:
            raise _not_found(args.id) from None
        raise CtlError(EXIT_NOT_FOUND, "board_error", f"board answered {exc.status}") from None
    if source == "board":
        fm = {k: v for k, v in data["frontmatter"].items() if not k.startswith("_") and k not in _DERIVED_KEYS}
        payload = {"id": args.id, "source": "board", "status": data["frontmatter"].get("status"),
                   "title": data.get("title"), "frontmatter": fm, "run_state": data.get("run_state_explanation"),
                   "artifacts": data.get("artifacts", []), "artifact_index_state": data.get("artifact_index_state")}
        payload['terminal_projection'] = data['frontmatter'].get('terminal_projection')
        body = data.get("body_md", "")
    else:
        rec = _offline_specs(ctx.specs_dir).get(args.id)
        if rec is None:
            raise _not_found(args.id)
        import spec_artifacts  # noqa: PLC0415
        state, entries, _detail = spec_artifacts.read_index_state(
            spec_artifacts.reports_root_for_spec_path(rec["path"]), args.id)
        fm = dict(rec["fm"], status=rec["status"])
        payload = {"id": args.id, "source": "offline", "status": rec["status"], "title": rec["title"] or args.id,
                   "frontmatter": fm, "run_state": _explain_offline(rec), "artifacts": entries,
                   "artifact_index_state": state}
        payload['terminal_projection'] = rec.get('terminal_projection')
        body = rec["body"]
    if args.body:
        payload["body"] = body
    lines = [f"# source: {source}", f"{args.id}  [{payload['status']}]  {payload['title']}"]
    lines += [f"{k}: {json.dumps(v, default=str)}" for k, v in fm.items() if k != "scope"]
    lines.append(f"run_state: {json.dumps(payload['run_state'], default=str)}")
    if payload.get('terminal_projection'):
        lines.append(f"terminal_projection: {json.dumps(payload['terminal_projection'], default=str)}")
    lines.append(f"artifacts: {len(payload['artifacts'])} ({payload['artifact_index_state']})")
    if args.body:
        lines += ["", body]
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK


def cmd_search(ctx: Ctx, args) -> int:
    def offline():
        needle, hits = args.q.lower(), []
        for spec_id, rec in _offline_specs(ctx.specs_dir).items():
            haystack = f"{spec_id} {rec['title']} {rec['body']}".lower()
            idx = haystack.find(needle)
            if idx == -1:
                continue
            excerpt = "..." + haystack[max(0, idx - 60):idx + len(needle) + 60] + "..."
            hits.append({"id": spec_id, "title": rec["title"] or spec_id, "status": rec["status"], "excerpt": excerpt})
        return hits

    source, data = _board_or_offline(ctx, "/api/search?q=" + urllib.parse.quote(args.q, safe=""), offline) \
        if args.q else ("board", [])
    rows = sorted(({"id": h["id"], "title": h.get("title"), "status": h.get("status"), "excerpt": h.get("excerpt")}
                   for h in data), key=lambda r: r["id"])
    text = "\n".join([f"# source: {source}  count: {len(rows)}"] + [f"{r['id']}\t{r['status']}\t{r['title']}" for r in rows])
    _emit(args, {"source": source, "query": args.q, "count": len(rows), "results": rows}, text)
    return EXIT_OK


def cmd_history(ctx: Ctx, args) -> int:
    try:
        data = ctx.request(f"/api/spec/{urllib.parse.quote(args.id, safe='')}/status/history")
    except _HttpStatus as exc:
        raise _not_found(args.id) if exc.status == 404 else CtlError(EXIT_NOT_FOUND, "board_error", f"board answered {exc.status}") from None
    rows = data.get("history", [])
    text = "\n".join([f"# source: board  count: {len(rows)}"] + [
        f"{r.get('created_at')}\t{r.get('status')}\t{r.get('source')}\t{r.get('note') or ''}" for r in rows])
    _emit(args, {"id": args.id, "source": "board", "history": rows}, text)
    return EXIT_OK


def cmd_deps(ctx: Ctx, args) -> int:
    def offline():
        specs = _offline_specs(ctx.specs_dir)
        if args.id not in specs:
            return None
        node = lambda i: {"id": str(i), "status": specs[str(i)]["status"] if str(i) in specs else None}  # noqa: E731
        waits = [node(d) for d in specs[args.id]["fm"].get("after") or []]
        by = [node(i) for i, r in specs.items() if args.id in [str(d) for d in r["fm"].get("after") or []]]
        return {"waits_on": waits, "waited_on_by": by}

    source, data = _board_or_offline(ctx, "/api/graph", offline)
    if source == "board":
        nodes = {str(n["id"]): n for n in data["nodes"]}
        if args.id not in nodes:
            raise _not_found(args.id)
        node = lambda i: {"id": str(i), "status": nodes[str(i)]["status"] if str(i) in nodes else None}  # noqa: E731
        data = {"waits_on": [node(e["from"]) for e in data["edges"] if str(e["to"]) == args.id],
                "waited_on_by": [node(e["to"]) for e in data["edges"] if str(e["from"]) == args.id]}
    elif data is None:
        raise _not_found(args.id)
    for key in ("waits_on", "waited_on_by"):
        data[key] = sorted(data[key], key=lambda n: n["id"])
    lines = [f"# source: {source}", f"{args.id} waits on:"] + [f"  {n['id']}\t{n['status']}" for n in data["waits_on"]]
    lines += ["waited on by:"] + [f"  {n['id']}\t{n['status']}" for n in data["waited_on_by"]]
    _emit(args, {"id": args.id, "source": source, **data}, "\n".join(lines))
    return EXIT_OK


def cmd_artifacts(ctx: Ctx, args) -> int:
    quoted = urllib.parse.quote(args.id, safe="")
    try:
        if args.path:
            data = ctx.request(f"/api/spec/{quoted}/artifact?path=" + urllib.parse.quote(args.path, safe=""))
            _emit(args, {"id": args.id, "source": "board", "path": args.path, "artifact": data},
                  json.dumps(data, indent=2, default=str))
            return EXIT_OK
        data = ctx.request(f"/api/spec/{quoted}")
    except _HttpStatus as exc:
        error = exc.body.get("error", {}) if isinstance(exc.body, dict) else {}
        if error.get("code") == "spec_not_found" or (exc.status == 404 and not error):
            raise _not_found(args.id) from None
        raise CtlError(EXIT_NOT_FOUND, str(error.get("code", "board_error")),
                       str(error.get("message", f"board answered {exc.status}")),
                       f"`board_ctl.py artifacts {args.id}` lists the exact paths") from None
    rows = data.get("artifacts", [])
    text = "\n".join([f"# source: board  index: {data.get('artifact_index_state')}  count: {len(rows)}"]
                     + [json.dumps(r, default=str) for r in rows])
    _emit(args, {"id": args.id, "source": "board", "artifact_index_state": data.get("artifact_index_state"),
                 "artifacts": rows}, text)
    return EXIT_OK


def cmd_who(ctx: Ctx, args) -> int:
    specs = ctx.request("/api/specs")
    worktrees = ctx.request("/api/worktree-status")
    rows = [{"id": str(s["id"]), "title": s.get("_title", ""), "worktrees": worktrees.get(str(s["id"]), [])}
            for s in specs if s.get("status") == "in_progress"]
    rows.sort(key=lambda r: r["id"])
    lines = [f"# source: board  in_progress: {len(rows)}"]
    for r in rows:
        where = "; ".join(f"{w.get('branch')}={w.get('status')}" for w in r["worktrees"]) or "no differing worktree"
        lines.append(f"{r['id']}\t{r['title']}\t{where}")
    _emit(args, {"source": "board", "in_progress": rows}, "\n".join(lines))
    return EXIT_OK


def cmd_refresh(ctx: Ctx, args) -> int:
    data = ctx.request("/api/refresh", method="POST", timeout=120.0)
    _emit(args, {"source": "board", **data}, f"refreshed: {data.get('count')} specs")
    return EXIT_OK


def _delegate(script: str, argv: list[str]) -> int:
    path = HERE / script
    if not path.is_file():
        raise CtlError(EXIT_NOT_FOUND, "tool_missing", f"{script} is not installed next to board_ctl.py",
                       "run `/nightshift doctor` to check the install")
    return subprocess.run([sys.executable, str(path), *argv]).returncode


def cmd_next(ctx: Ctx, args) -> int:
    return _delegate("nightshift-dag.py", ["next", "--specs-dir", str(ctx.specs_dir)] + (["--json"] if args.json else []))


def cmd_brief(ctx: Ctx, args) -> int:
    return _delegate("nightshift-instructions.py", [
        "apply", "--spec", args.id, "--nightshift-dir", str(HERE), "--specs-dir", str(ctx.specs_dir),
        "--project-root", str(ctx.project_root)] + (["--json"] if args.json else []))


# ---------------------------------------------------------------------------
# Management (SPEC-417-003): lifecycle, board-doctor, transition, validate
# ---------------------------------------------------------------------------

CONTROL_DEFAULT_PORT = 7799
HEALTH_WAIT_SECONDS = 60.0
_RUNTIME_MODULES = ("fastapi", "uvicorn", "yaml")


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, timeout: float = 5.0):
    """``(status, parsed-json-or-None)``; ``None`` status when nothing answered."""
    data = json.dumps(body).encode("utf-8") if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(url, method=method, data=data,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw, status = response.read().decode("utf-8", "replace"), response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read().decode("utf-8", "replace"), exc.code
    except (urllib.error.URLError, OSError, ValueError):
        return None, None
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


def _port_listening(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(2.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _board_health(port: int) -> dict | None:
    """The board's ``/api/health`` payload when something board-shaped answers, else ``None``."""
    status, data = _http_json(f"http://127.0.0.1:{port}/api/health", timeout=5.0)
    return data if isinstance(data, dict) and "status" in data else None


def _control_port(args: argparse.Namespace) -> int:
    if args.control_port is not None:
        return args.control_port
    raw = os.environ.get("NIGHTSHIFT_CONTROL_PORT", "")
    return int(raw) if raw.isdigit() else CONTROL_DEFAULT_PORT


def _control_entry(ctx: Ctx) -> tuple[bool, dict | None]:
    """``(control reachable, this project's Control entry or None)``."""
    status, data = _http_json(f"http://127.0.0.1:{_control_port(ctx.args)}/api/projects", timeout=5.0)
    if status != 200 or not isinstance(data, list):
        return False, None
    port, _ = ctx.resolve_port()
    entry = ctx._entry or ctx._own_registry_entry() or {}
    name = str(entry.get("name") or project_name_for_root(ctx.project_root)).upper()
    match = next((p for p in data if isinstance(p, dict) and str(p.get("name", "")).upper() == name
                  and p.get("port") == port), None)
    return True, match


class BoardInstall:
    """Where this project's board launcher, PID record and runtime live."""

    def __init__(self, ctx: Ctx) -> None:
        self.dir = ctx.specs_dir.parent
        self.specs_dir = ctx.specs_dir
        self.script = self.dir / "board.sh"
        self.pid_file = self.dir / "board.pid"

    def runtime(self) -> str:
        if os.environ.get("NIGHTSHIFT_BOARD_PYTHON"):
            return os.environ["NIGHTSHIFT_BOARD_PYTHON"]
        venv = self.dir / ".board-venv" / "bin" / "python"
        return str(venv) if os.access(venv, os.X_OK) else "python3"

    def pid_state(self) -> tuple[str, int | None]:
        """``(state, pid)``: none | invalid | stale | foreign | live. Reads only; never signals."""
        if not self.pid_file.is_file():
            return "none", None
        raw = self.pid_file.read_text(encoding="utf-8", errors="replace").strip()
        if not raw.isdigit():
            return "invalid", None
        pid = int(raw)
        done = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
        command = done.stdout.strip()
        if done.returncode != 0 or not command:
            return "stale", pid
        return ("live", pid) if f"{self.dir}/board.py" in command else ("foreign", pid)


def _need_launcher(install: BoardInstall) -> None:
    if not install.script.is_file():
        raise CtlError(EXIT_NOT_FOUND, "tool_missing", f"board.sh is not installed next to {install.dir.name}",
                       "run `/nightshift doctor` to check the install")


def _wait_health(port: int, *, up: bool, seconds: float = HEALTH_WAIT_SECONDS) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if (_board_health(port) is not None) == up:
            return True
        time.sleep(0.25)
    return False


def _launcher_info(ctx: Ctx, install: BoardInstall, up: bool) -> dict:
    state, pid = install.pid_state()
    if state == "live":
        return {"kind": "board.sh", "pid": pid}
    if up:
        if _control_entry(ctx)[1] is not None:
            return {"kind": "control", "pid": None}
        return {"kind": "unknown", "pid": None}
    return {"kind": None, "pid": None}


def _run_launcher(ctx: Ctx, install: BoardInstall, action: str, port: int) -> subprocess.CompletedProcess:
    _need_launcher(install)
    if action == "stop":
        argv = ["bash", str(install.script), "stop"]
    else:
        argv = ["bash", str(install.script), "--no-open", "--port", str(port)]
        if install.specs_dir != install.dir / "specs":
            argv += ["--specs", str(install.specs_dir)]
    return subprocess.run(argv, capture_output=True, text=True, timeout=180)


def _do_start(ctx: Ctx, install: BoardInstall, port: int) -> dict:
    if _board_health(port) is not None:
        return {"action": "start", "result": "already-up", "via": None}
    reachable, entry = _control_entry(ctx)
    if entry is not None:
        status, data = _http_json(
            f"http://127.0.0.1:{_control_port(ctx.args)}/api/projects/{urllib.parse.quote(str(entry['name']), safe='')}"
            f"/start?port={port}", method="POST", timeout=30.0)
        if status != 200:
            raise CtlError(EXIT_PROBLEM, "start_failed", f"Control refused the start: {data}",
                           "`board_ctl.py board-doctor` names the cause")
        if not _wait_health(port, up=True):
            raise CtlError(EXIT_PROBLEM, "start_timeout", f"the board did not answer /api/health on port {port}",
                           f"see {install.dir / 'board.restart.log'}; `board_ctl.py board-doctor`")
        return {"action": "start", "result": "started", "via": "control"}
    done = _run_launcher(ctx, install, "start", port)
    if done.returncode != 0:
        raise CtlError(EXIT_PROBLEM, "start_failed", (done.stderr or done.stdout).strip() or "board.sh failed",
                       "`board_ctl.py board-doctor` names the cause")
    return {"action": "start", "result": "started", "via": "board.sh"}


def _do_stop(ctx: Ctx, install: BoardInstall, port: int) -> dict:
    up = _board_health(port) is not None
    state, _pid = install.pid_state()
    reachable, entry = _control_entry(ctx)
    if up and state != "live" and entry is not None:
        status, data = _http_json(
            f"http://127.0.0.1:{_control_port(ctx.args)}/api/projects/{urllib.parse.quote(str(entry['name']), safe='')}"
            f"/stop?port={port}", method="POST", timeout=60.0)
        if status != 200:
            raise CtlError(EXIT_PROBLEM, "stop_failed", f"Control refused the stop: {data}",
                           "`board_ctl.py board-doctor` names the cause")
        return {"action": "stop", "result": "stopped", "via": "control"}
    if not up and state == "none":
        return {"action": "stop", "result": "already-down", "via": None}
    done = _run_launcher(ctx, install, "stop", port)
    if done.returncode != 0:
        raise CtlError(EXIT_PROBLEM, "stop_failed", (done.stderr or done.stdout).strip() or "board.sh stop failed",
                       "`board_ctl.py board-doctor` names the cause")
    return {"action": "stop", "result": "stopped", "via": "board.sh"}


def cmd_start(ctx: Ctx, args) -> int:
    port, _ = ctx.resolve_port()
    out = _do_start(ctx, BoardInstall(ctx), port)
    _emit(args, {**out, "port": port}, f"start: {out['result']} (port {port}, via {out['via'] or 'n/a'})")
    return EXIT_OK


def cmd_stop(ctx: Ctx, args) -> int:
    port, _ = ctx.resolve_port()
    out = _do_stop(ctx, BoardInstall(ctx), port)
    _emit(args, {**out, "port": port}, f"stop: {out['result']} (port {port}, via {out['via'] or 'n/a'})")
    return EXIT_OK


def cmd_restart(ctx: Ctx, args) -> int:
    port, _ = ctx.resolve_port()
    install = BoardInstall(ctx)
    stopped = _do_stop(ctx, install, port)
    if stopped["result"] == "stopped" and not _wait_health(port, up=False, seconds=15.0):
        raise CtlError(EXIT_PROBLEM, "stop_incomplete", f"port {port} still answers after the stop",
                       "`board_ctl.py board-doctor`")
    started = _do_start(ctx, install, port)
    _emit(args, {"action": "restart", "stop": stopped, "start": started, "port": port},
          f"restart: {stopped['result']} then {started['result']} (port {port}, via {started['via'] or 'n/a'})")
    return EXIT_OK


def cmd_status(ctx: Ctx, args) -> int:
    port, via = ctx.resolve_port()
    install = BoardInstall(ctx)
    up = _board_health(port) is not None
    launcher = _launcher_info(ctx, install, up)
    reachable, entry = _control_entry(ctx)
    payload = {"up": up, "port": port, "port_source": via, "launcher": launcher,
               "control": {"reachable": reachable, "registered": entry is not None,
                           "port": _control_port(args)}}
    pid = f" pid {launcher['pid']}" if launcher["pid"] else ""
    text = (f"board: {'up' if up else 'down'}  port: {port} ({via})  launcher: "
            f"{launcher['kind'] or 'none'}{pid}  control: "
            f"{'registered' if entry else ('reachable' if reachable else 'unreachable')}")
    _emit(args, payload, text)
    return EXIT_OK


# -- board-doctor ----------------------------------------------------------

def _finding(code: str, severity: str, message: str, fix: str) -> dict:
    return {"code": code, "severity": severity, "message": message, "fix": fix}


_SYNC_FIX = {
    "durable-terminal-ahead-of-file": "the store holds a terminal status the file lags: for `blocked` run "
                                      "`/nightshift unblock {id}`; otherwise align the file with the store",
    "durable-stale-behind-file": "a stale store row the repair refused: `board_ctl.py transition {id} <status> "
                                 "--reason <why>` writes a fresh checkpoint",
}


def _sync_findings(ctx: Ctx, up: bool, port: int) -> list[dict]:
    rows: list[dict] = []
    if up:
        status, data = _http_json(f"http://127.0.0.1:{port}/api/status-sync", timeout=30.0)
        if status == 200 and isinstance(data, dict):
            rows = list(data.get("mismatches") or [])
            for spec_id, projection in (data.get('terminal_projections') or {}).items():
                if projection.get('projection') == 'pending':
                    rows.append({'id': spec_id, 'reason': 'terminal-projection-pending',
                                 'detail': projection.get('reason'),
                                 'recovery_action': projection.get('recovery_action')})
    else:
        for spec_id, rec in _offline_specs(ctx.specs_dir).items():
            projection = rec.get('terminal_projection')
            if projection and projection.get('projection') == 'pending':
                rows.append({'id': spec_id, 'reason': 'terminal-projection-pending',
                             'detail': projection.get('reason'),
                             'recovery_action': projection.get('recovery_action')})
            sync = rec["view"]["sync"]
            if not sync["in_sync"]:
                rows.append({"id": spec_id, "frontmatter": rec["view"]["declared"], "durable": sync["durable"],
                             "reason": sync["reason"]})
    return [_finding("status_sync_mismatch", "warn",
                     f"{r['id']}: tracked terminal projection pending: {r.get('detail')}" if r.get('reason') == 'terminal-projection-pending'
                     else f"{r['id']}: frontmatter {r.get('frontmatter')!r} vs store {r.get('durable')!r} ({r.get('reason')})",
                     r.get('recovery_action') or _SYNC_FIX.get(str(r.get("reason")), "`board_ctl.py show {id}`").format(id=r["id"]))
            for r in rows]


def cmd_board_doctor(ctx: Ctx, args) -> int:
    port, via = ctx.resolve_port()
    install = BoardInstall(ctx)
    findings: list[dict] = []
    health = _board_health(port)
    up = health is not None
    listening = up or _port_listening(port)
    stop_cmd = f"bash {install.script} stop"

    state, pid = install.pid_state()
    if state == "invalid":
        findings.append(_finding("pid_file_invalid", "warn", f"{install.pid_file} does not hold a PID",
                                 f"`{stop_cmd}` removes the invalid record"))
    elif state == "stale":
        findings.append(_finding("pid_file_stale", "warn", f"{install.pid_file} names PID {pid}, which is not running",
                                 f"`{stop_cmd}` removes the stale record"))
    elif state == "foreign":
        findings.append(_finding("pid_not_board", "error", f"{install.pid_file} names PID {pid}, which is not this board",
                                 f"check `ps -p {pid} -o command=`; if it is not yours to stop, delete {install.pid_file}"))
    elif state == "live" and not listening:
        findings.append(_finding("board_not_listening", "error", f"board PID {pid} is running but port {port} refuses connections",
                                 f"`{stop_cmd}` then `board_ctl.py start`; see {install.dir / 'board.restart.log'}"))

    if listening and not up:
        holder = ""
        done = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fcp"], capture_output=True, text=True) \
            if shutil.which("lsof") else None
        if done is not None and done.stdout:
            holder = " (holder: " + ", ".join(l[1:] for l in done.stdout.split() if l[:1] in "cp") + ")"
        findings.append(_finding("port_held_by_other", "error",
                                 f"port {port} answers but not as a Nightshift board{holder}",
                                 f"free the port (`lsof -nP -iTCP:{port} -sTCP:LISTEN`) or give this project another port in "
                                 "projects-registry.json and pass `--port`"))

    probe = "import importlib.util as u;print(','.join(m for m in %r if u.find_spec(m) is None))" % (_RUNTIME_MODULES,)
    try:
        done = subprocess.run([install.runtime(), "-c", probe], capture_output=True, text=True, timeout=30)
        missing = done.stdout.strip() if done.returncode == 0 else ",".join(_RUNTIME_MODULES)
    except (OSError, subprocess.SubprocessError):
        missing = ",".join(_RUNTIME_MODULES)
    if missing:
        findings.append(_finding("runtime_missing_modules", "error",
                                 f"board runtime {install.runtime()} lacks: {missing}",
                                 "set NIGHTSHIFT_BOARD_PYTHON to a Python with fastapi, uvicorn and pyyaml, or create "
                                 f"{install.dir / '.board-venv'} and `pip install fastapi 'uvicorn[standard]' pyyaml` in it"))

    if up and health.get("status") != "ok":
        findings.append(_finding("health_failing", "error", f"/api/health reports status {health.get('status')!r}",
                                 f"`board_ctl.py health`; `board_ctl.py restart` if it persists; log: {install.dir / 'board.restart.log'}"))
    if up and state in ("none", "invalid", "stale"):
        _reachable, entry = _control_entry(ctx)
        if entry is not None:
            findings.append(_finding("control_launched_no_pid", "info",
                                     "the board was launched by Control, so there is no live board.pid and `board.sh stop` cannot see it",
                                     "stop it with `board_ctl.py stop` (uses Control)"))
    findings += _sync_findings(ctx, up, port)

    payload = {"up": up, "port": port, "port_source": via, "findings": findings, "ok": not findings}
    lines = [f"# board-doctor: port {port} ({via}), board {'up' if up else 'down'}, findings: {len(findings)}"]
    lines += [f"[{f['severity']}] {f['code']}: {f['message']}\n    fix: {f['fix']}" for f in findings]
    _emit(args, payload, "\n".join(lines))
    return EXIT_OK if not findings else EXIT_PROBLEM


# -- transition ------------------------------------------------------------

_TO_PLANNED_OR_BLOCKED = frozenset({"planned", "blocked"})
_PROMOTION_FLAGS = ("gap_resolved", "gap_waived_reason", "resolution_rationale", "finding", "evidence", "readiness_reviewed")


def classify_edge(current: str, target: str) -> tuple[str, str]:
    """``(route, message)``: route is ``board``, ``promotion`` or ``refused`` (message names the owner)."""
    sys.path.insert(0, str(HERE))
    import lifecycle  # noqa: PLC0415
    if current == "in_progress" or target == "in_progress":
        return "refused", ("in_progress moves belong to `/nightshift run` (kickoff, reconcile and the verifier); "
                           "board_ctl never starts or leaves in_progress")
    if target == "done":
        return "refused", ("done is reached only through the verifier and the merge flow "
                           "(`/nightshift run`, then the parent's merge); board_ctl does not mark specs done")
    if current == "blocked" and target in ("draft", "planned", "ready"):
        return "refused", "a blocked spec leaves blocked only through `/nightshift unblock <spec-id>`"
    allowed = sorted(lifecycle.LIFECYCLE_TRANSITIONS.get(current, ()))
    if target not in allowed:
        return "refused", (f"{current} -> {target} is not a lifecycle edge; allowed from {current}: "
                           + (", ".join(allowed) if allowed else "none"))
    if target == "ready":
        return "promotion", ""
    return "board", ""


def _random_token(n: int = 8) -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(n))


def _git(root: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True)


def _git_root(path: Path) -> Path | None:
    done = _git(path, "rev-parse", "--show-toplevel")
    return Path(done.stdout.strip()).resolve() if done.returncode == 0 and done.stdout.strip() else None


def _changed(root: Path, paths: list[str]) -> list[str]:
    """Paths git reports as modified, staged or untracked (each file, not directories) under ``paths``."""
    done = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)
    entries = [e for e in done.stdout.split("\0") if e]
    return [e[3:] for e in entries]


def _commit_transition(spec_id: str, current: str, target: str, spec_path: Path, reports_dir: Path,
                       before: list[str] | None, no_commit: bool) -> dict:
    root = _git_root(spec_path.parent)
    if root is None:
        return {"committed": False, "commit": None, "note": "not inside a git repository; nothing committed",
                "commit_command": None}
    rel = lambda p: os.path.relpath(p, root)  # noqa: E731
    scope = [rel(spec_path), rel(reports_dir)]
    subject = f"[{spec_id}] chore: status {current} -> {target} (board_ctl)"
    manual = f"git -C {root} add -- {' '.join(scope)} && git -C {root} commit -m \"{subject}\" -- {' '.join(scope)}"
    if before is None:
        before = []
    if no_commit or before:
        why = "--no-commit given" if no_commit else "the spec or its artifacts directory had uncommitted changes before the transition"
        return {"committed": False, "commit": None, "note": f"{why}; left in the working tree. Review `git status`, then run:",
                "commit_command": manual}
    created = _changed(root, scope)
    if not created:
        return {"committed": False, "commit": None, "note": "no changed files to commit", "commit_command": None}
    add = _git(root, "add", "--", *created)
    done = _git(root, "commit", "-q", "-m", subject, "--", *created) if add.returncode == 0 else add
    if done.returncode != 0:
        _git(root, "reset", "-q", "--", *created)
        raise CtlError(EXIT_PROBLEM, "commit_failed",
                       "the transition was written but the commit failed: " + (done.stderr or done.stdout).strip()[-600:],
                       f"fix the cause, then run: {manual}")
    sha = _git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    return {"committed": True, "commit": sha, "files": created, "note": None, "commit_command": None}


def _require(cond: bool, message: str, next_step: str = "") -> None:
    if not cond:
        raise CtlError(EXIT_USAGE, "usage", message, next_step)


def cmd_transition(ctx: Ctx, args) -> int:
    spec_id, target = args.id, args.status
    specs = _offline_specs(ctx.specs_dir)
    rec = specs.get(spec_id)
    if rec is None:
        raise _not_found(spec_id)
    port, _via = ctx.resolve_port()
    board_up = _board_health(port) is not None
    current = rec["status"]
    if board_up:
        try:
            detail = ctx.request(f"/api/spec/{urllib.parse.quote(spec_id, safe='')}")
        except _HttpStatus as exc:
            if exc.status == 404:
                raise CtlError(EXIT_NOT_FOUND, "wrong_board",
                               f"the board answering on port {port} does not know {spec_id} (another project's board?)",
                               "check `board_ctl.py port` and `board_ctl.py status`") from None
            raise
        current = str(detail["frontmatter"].get("status", current))

    route, message = classify_edge(current, target)
    if route == "refused":
        raise CtlError(EXIT_REFUSED, "transition_refused", f"{spec_id}: {message}", message.split("`")[1] if "`" in message else "")
    promotion_given = [f for f in _PROMOTION_FLAGS if getattr(args, f)]
    if route == "board":
        _require(not promotion_given, "promotion flags apply only to draft/planned -> ready")
        _require(bool(args.reason and args.reason.strip()), f"{current} -> {target} requires --reason")
        if target in _TO_PLANNED_OR_BLOCKED:
            _require(bool(args.reconsider_when and args.reconsider_when.strip()),
                     f"{current} -> {target} requires --reconsider-when")
    else:
        _require(bool(args.reason and args.reason.strip()), f"{current} -> {target} requires --reason")
        _require(not args.reconsider_when, "--reconsider-when is not supported on the promotion path (draft/planned -> ready)")

    spec_path = Path(rec["path"]).resolve()
    reports_dir = spec_artifacts_root(spec_path) / spec_id
    root = _git_root(spec_path.parent)
    before = _changed(root, [os.path.relpath(spec_path, root), os.path.relpath(reports_dir, root)]) if root else None

    if route == "board" and board_up:
        quoted = urllib.parse.quote(spec_id, safe="")
        body = {"status": target, "reason": args.reason}
        if args.reconsider_when:
            body["reconsider_when"] = args.reconsider_when
        status, data = _http_json(f"http://127.0.0.1:{port}/api/spec/{quoted}/status", method="PUT", body=body, timeout=60.0)
        if status == 400:
            detail = data.get("detail") if isinstance(data, dict) else data
            raise CtlError(EXIT_REFUSED, "transition_refused", f"{spec_id}: the board refused: {detail}")
        if status != 200:
            raise CtlError(EXIT_PROBLEM, "board_error", f"board answered {status} to the status write")
        via = "board"
    else:
        via = _write_offline(ctx, rec, spec_path, current, target, args, route)
    if board_up:
        try:
            ctx.request("/api/refresh", method="POST", timeout=120.0)
        except (CtlError, _HttpStatus):
            pass
    commit = _commit_transition(spec_id, current, target, spec_path, reports_dir, before, args.no_commit)
    payload = {"id": spec_id, "from": current, "to": target, "route": route, "via": via, "board_up": board_up, **commit}
    lines = [f"{spec_id}: {current} -> {target} (via {via})"]
    if commit["committed"]:
        lines.append(f"committed {commit['commit']}: {', '.join(commit['files'])}")
    else:
        lines.append(commit["note"] or "")
        if commit["commit_command"]:
            lines.append(f"  {commit['commit_command']}")
    _emit(args, payload, "\n".join(l for l in lines if l))
    return EXIT_OK


def spec_artifacts_root(spec_path: Path) -> Path:
    sys.path.insert(0, str(HERE))
    import spec_artifacts  # noqa: PLC0415
    return spec_artifacts.reports_root_for_spec_path(spec_path)


def _write_offline(ctx: Ctx, rec: dict, spec_path: Path, current: str, target: str, args, route: str) -> str:
    """The board-down write: the same gates, then the same durable store write (never re-implemented here)."""
    sys.path.insert(0, str(HERE))
    import status_store  # noqa: PLC0415
    import status_transition  # noqa: PLC0415
    spec_id = args.id
    run_id = f"ctl-{spec_id}-{_random_token()}"
    if route == "promotion":
        import spec_promotion  # noqa: PLC0415
        gap = {"resolved": True} if args.gap_resolved else ({"waived_reason": args.gap_waived_reason} if args.gap_waived_reason else None)
        try:
            spec_promotion.promote_to_ready(
                spec_path, reason=args.reason, run_id=run_id, actor="board_ctl",
                status_store=status_store.StatusStore.for_specs_dir(ctx.specs_dir), gap_resolution=gap,
                resolution_rationale=args.resolution_rationale, findings=args.finding, evidence=args.evidence,
                readiness_reviewed=args.readiness_reviewed)
        except spec_promotion.PromotionError as exc:
            raise CtlError(EXIT_REFUSED, "transition_refused", f"{spec_id}: {exc}") from None
        except status_store.LifecyclePersistenceError as exc:
            raise CtlError(EXIT_PROBLEM, "write_failed", str(exc)) from None
        return "spec_promotion"
    try:
        reason_text = status_transition.gate_status_write(
            rec["fm"], target, reason=args.reason, specs_dir=ctx.specs_dir, canonical_dir=HERE,
            record_refusal=lambda message: status_transition.record_transfer_refusal_on_file(spec_path, message))
    except ValueError as exc:
        raise CtlError(EXIT_REFUSED, "transition_refused", f"{spec_id}: {exc}") from None
    store = status_store.StatusStore.for_specs_dir(ctx.specs_dir)
    try:
        store.transition_commit_backed(spec_path, target, run_id=run_id, source="board_ctl", reason=reason_text,
                                       reconsider_when=args.reconsider_when, state_rationale_evidence=())
    except (status_store.LifecyclePersistenceError, status_store.TransitionReasonRequired) as exc:
        raise CtlError(EXIT_PROBLEM, "write_failed", str(exc)) from None
    status_transition.clear_transfer_refusal_on_file(spec_path)
    return "offline"


# -- validate --------------------------------------------------------------

def cmd_validate(ctx: Ctx, args) -> int:
    chosen = [bool(args.ids), args.staged, args.all]
    _require(sum(chosen) <= 1, "pick one of <id>..., --staged or --all")
    _require(any(chosen) or args.install, "name specs (<id>... | --staged | --all) or pass --install")
    runs: list[tuple[str, list[str]]] = []
    if args.ids:
        specs = _offline_specs(ctx.specs_dir)
        missing = [i for i in args.ids if i not in specs]
        if missing:
            raise _not_found(missing[0])
        runs.append(("validate_specs.py", [str(specs[i]["path"]) for i in args.ids]))
    elif args.all:
        runs.append(("validate_specs.py", [str(ctx.specs_dir)]))
    elif args.staged:
        root = _git_root(ctx.specs_dir)
        _require(root is not None, "--staged needs a git repository")
        runs.append(("validate_specs.py", ["--staged", str(root), os.path.relpath(ctx.specs_dir, root)]))
    results = []
    for tool, tool_args in runs:
        results.append(_run_tool(tool, tool_args))
    if args.install:
        installed = HERE.name == ".nightshift"
        root = HERE.parent if installed else HERE
        results.append(_run_tool("validate_install.py", ["--profile", "installed" if installed else "canonical",
                                                          "--root", str(root)]))
    failed = [r for r in results if r["exit"] != 0]
    payload = {"ok": not failed, "results": results}
    lines = [f"{r['tool']}: {'PASS' if r['exit'] == 0 else 'FAIL'} (exit {r['exit']})" for r in results]
    for r in failed:
        lines += ["  " + l for l in r["tail"].splitlines()[-12:]]
    lines.append("validate: " + ("all passed" if not failed else f"{len(failed)} of {len(results)} failed"))
    _emit(args, payload, "\n".join(lines))
    return failed[0]["exit"] if failed else EXIT_OK


def _run_tool(tool: str, tool_args: list[str]) -> dict:
    path = HERE / tool
    if not path.is_file():
        raise CtlError(EXIT_NOT_FOUND, "tool_missing", f"{tool} is not installed next to board_ctl.py",
                       "run `/nightshift doctor` to check the install")
    done = subprocess.run([sys.executable, str(path), *tool_args], capture_output=True, text=True)
    return {"tool": tool, "exit": done.returncode, "tail": ((done.stdout or "") + (done.stderr or ""))[-2000:]}


# -- rules check (SPEC-417-004) --------------------------------------------

RULES_GUIDE = ".nightshift/guides/rules.md"
# One row per rule family: (id, primary source `file#anchor`, fnmatch globs over validate_specs finding
# families). guides/rules.md carries the same table; test_board_ctl_rules.py keeps the two in step.
# A finding with no matching glob is routed by _MESSAGE_ROUTES, else to spec-format.
RULE_ROWS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("spec-format", "SPEC-GUIDE.md#spec-types",
     ("missing-*", "invalid-status-value", "legacy-planning-status", "attachments-*", "followup-shape",
      "*template-token", "path-traversal-token", "absolute-path-leak", "block-reason-as-title",
      "transfer-refusal-shape", "done-spec-unchecked-checkbox", "unregistered-type",
      "unclassified-finding", "spec-id-*", "registry-code-invalid", "staged-configuration-invalid",
      "deploy-environment", "board-column-defaults", "resolved-blocker-field-residual",
      "artifact-*", "untracked-*")),
    ("state-rationale", "SPEC-GUIDE.md#state-rationale-why-a-spec-has-its-current-status-spec-357",
     ("state_rationale_*",)),
    ("lifecycle", "SPEC-GUIDE.md#draft-promotion-gaps-spec-210", ("promotion-gap-*", "status-sync-mismatch", "unknown-dependency", "spec-metadata-*",
                  "blocker-evidence-unresolved")),
    ("scope", "SPEC-GUIDE.md#write-scope", ()),
    ("release-handoff", "ORCHESTRATOR.md#versioned-release-handoff-spec-189",
     ("release-handoff-*", "*release*handoff*")),
    ("nfr", "SPEC-GUIDE.md#creating-an-nfr-spec", ("nfr-*", "scope-tags-shape")),
    ("real-use-evidence", "SPEC-GUIDE.md#interactive-spec-creation-guide", ("real-use-evidence", "real-use-evidence-*", "live-item-evidence-*")),
    ("amendments", "SPEC-GUIDE.md#ac-amendments", ("ac-amendment-*",)),
    ("commit-hooks", "GIT.md#commit-format", ()),
    ("merge", "GIT.md#merge-and-post-merge-validation", ()),
    ("no-test-loosening", "SPEC-GUIDE.md#ac-amendments", ()),
    ("worktree-isolation", "GIT.md#branches-and-worktrees", ()),
)
_RULE_SOURCE = {row[0]: row[1] for row in RULE_ROWS}
# Findings the validator classifies as unclassified-finding but whose text names their rule family.
_MESSAGE_ROUTES: tuple[tuple[str, str], ...] = (
    (r"Scope Amendments|AC Amendments|ac_amendment", "amendments"),
    (r"^(WARNING: )?(scope\b|no scope:)", "scope"),
    (r"real_use_evidence|Live Execution|live execution", "real-use-evidence"),
    (r"\bNFR\b|\bnfrs?\b", "nfr"),
)
_VALIDATOR_ROWS = ("spec-format", "state-rationale", "scope", "release-handoff", "nfr", "real-use-evidence",
                   "amendments")


def rule_row_for_family(family: str, message: str = "") -> str:
    """The rules.md row a validate_specs finding belongs to (family globs first, then the message)."""
    import fnmatch
    import re
    for row, _source, globs in RULE_ROWS:
        if any(fnmatch.fnmatchcase(family, g) for g in globs):
            if family != "unclassified-finding":
                return row
            break
    for pattern, row in _MESSAGE_ROUTES:
        if re.search(pattern, message):
            return row
    return "spec-format"


def _rules_env() -> dict:
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE="1", GIT_OPTIONAL_LOCKS="0")
    return env


def _spec_type_registry() -> set[str] | None:
    """The ``type:`` values listed in SPEC-GUIDE.md ``## Spec Types``; ``None`` when the guide is absent."""
    sys.path.insert(0, str(HERE))
    import validate_specs  # noqa: PLC0415
    return validate_specs.load_spec_type_registry(HERE / "SPEC-GUIDE.md")


def _line(rule: str, status: str, reason: str, source: str | None = None) -> dict:
    return {"rule": rule, "status": status, "reason": reason, "source": source or _RULE_SOURCE[rule.split("/")[0]]}


def _validator_lines(spec_path: Path) -> list[dict]:
    """validate_specs.py findings for one spec, one line per validator-backed rule family."""
    sys.path.insert(0, str(HERE))
    import validate_specs  # noqa: PLC0415
    tool = HERE / "validate_specs.py"
    done = subprocess.run([sys.executable, "-B", str(tool), str(spec_path), "--format", "json"],
                          capture_output=True, text=True, env=_rules_env())
    try:
        results = json.loads(done.stdout)["results"]
    except (ValueError, KeyError):
        tail = ((done.stdout or "") + (done.stderr or "")).strip()[-300:]
        return [_line("spec-format", "fail", f"validate_specs.py gave no report: {tail}")]
    findings = [m for messages in results.values() for m in messages]
    by_row: dict[str, list[str]] = {row: [] for row in _VALIDATOR_ROWS}
    for message in findings:
        family = validate_specs.classify_finding_family(message)
        if family == "unregistered-type":
            continue  # reported once, by the spec-format/type line (same registry loader)
        by_row.setdefault(rule_row_for_family(family, message), []).append(message)
    out = []
    for row in _VALIDATOR_ROWS:
        if row == "release-handoff" and not (HERE / "release-manifest.json").is_file():
            out.append(_line(row, "skip", "no release-manifest.json next to this kit (install): the validator does not check handoffs"))
            continue
        errors = [m for m in by_row[row] if not m.startswith("WARNING: ")]
        warnings = [m for m in by_row[row] if m.startswith("WARNING: ")]
        if errors:
            out.append(_line(row, "fail", "; ".join(errors)[:600]))
        elif warnings:
            out.append(_line(row, "pass", f"{len(warnings)} warning(s): {warnings[0][len('WARNING: '):][:160]}"))
        else:
            out.append(_line(row, "pass", "validate_specs.py reports nothing for this rule family"))
    return out


def _dependency_line(ctx: Ctx, rec: dict, specs: dict[str, dict]) -> dict:
    sys.path.insert(0, str(HERE))
    import dependency_registry  # noqa: PLC0415
    fm = rec["fm"]
    after = [str(i) for i in (fm.get("after") or [])]
    qualified, shape_error = dependency_registry.parse_requires_specs(fm)
    resolver = dependency_registry.DependencyRegistryResolver(ctx.specs_dir, cache_seconds=0)
    seen, bad = [], []
    for spec_id in after:
        if spec_id in specs:
            seen.append(f"{spec_id} ({specs[spec_id]['status']})")
            continue
        record = resolver.resolve([spec_id]).resolved.get(spec_id)
        (seen if record is not None else bad).append(f"{spec_id} ({record.status})" if record else spec_id)
    for project, spec_id in qualified:
        record, error = resolver.resolve_in_project(project, spec_id)
        (seen if record is not None else bad).append(f"{project}:{spec_id} ({record.status})" if record else f"{project}:{spec_id}")
    if shape_error:
        bad.append(shape_error)
    if bad:
        return _line("lifecycle/dependencies", "fail", "unresolved after:/requires_specs: " + ", ".join(bad))
    return _line("lifecycle/dependencies", "pass", "resolved: " + (", ".join(seen) if seen else "no after: or requires_specs:"))


def _promotion_line(ctx: Ctx, rec: dict) -> dict:
    sys.path.insert(0, str(HERE))
    import spec_frontmatter  # noqa: PLC0415
    status = rec["status"]
    if status not in ("draft", "planned"):
        return _line("lifecycle/promotion", "skip", f"status is {status}; only draft/planned -> ready is a promotion")
    refusal = spec_frontmatter.promotion_transition_error({**rec["fm"], "status": "draft"}, "ready",
                                                          specs_dir=ctx.specs_dir)
    if refusal:
        return _line("lifecycle/promotion", "fail", refusal)
    import spec_promotion  # noqa: PLC0415
    refusal, _readiness = spec_promotion.readiness_refusal(
        {**rec["fm"], "status": "draft"}, rec["body"], specs_dir=ctx.specs_dir)
    if refusal:
        return _line("lifecycle/promotion", "fail", refusal)
    return _line("lifecycle/promotion", "pass",
                 "no unresolved promotion_gap and intrinsic readiness PASS; the promotion write gate would not refuse")


def _type_line(rec: dict) -> dict:
    registry = _spec_type_registry()
    spec_type = rec["fm"].get("type")
    source = "SPEC-GUIDE.md#spec-types"
    if registry is None:
        return _line("spec-format/type", "skip", "SPEC-GUIDE.md is not installed next to this kit", source)
    if spec_type in registry:
        return _line("spec-format/type", "pass", f"type {spec_type!r} is registered", source)
    if str(rec["fm"].get("id", "")).startswith("NFR-"):
        # SPEC-GUIDE "Spec Types / Rules": an NFR- id is NFR-family whatever type: a dated run used (e.g. task).
        return _line("spec-format/type", "pass", f"NFR-family id; type {spec_type!r} is allowed there", source)
    import validate_specs  # noqa: PLC0415
    status = rec["fm"].get("status")
    if isinstance(status, str) and status in validate_specs.UNREGISTERED_TYPE_AUDIT_STATUSES:
        # BUG-NS-KIT-118: finished specs get the validator's audit warning, not a fail.
        return _line("spec-format/type", "pass",
                     f"warning: audit: type {spec_type!r} is not in the registry (status {status}; history is not rewritten)", source)
    return _line("spec-format/type", "fail", f"type {spec_type!r} is not in the registry: " + ", ".join(sorted(registry)), source)


def _diff_line(ctx: Ctx, spec_id: str, rev_range: str | None, main: str) -> dict:
    source = "SPEC-GUIDE.md#write-scope"
    if not rev_range:
        return _line("scope/diff", "skip", "no --diff given", source)
    root = _git_root(ctx.specs_dir)
    _require(root is not None, "--diff needs a git repository")
    env = _rules_env()
    names = subprocess.run(["git", "-C", str(root), "diff", "--name-only", "-z", rev_range],
                           capture_output=True, text=True, env=env)
    if names.returncode != 0:
        raise CtlError(EXIT_USAGE, "bad_diff", f"git diff {rev_range} failed: {names.stderr.strip()[-300:]}")
    paths = [p for p in names.stdout.split("\0") if p]
    if not paths:
        return _line("scope/diff", "pass", f"{rev_range} changes no paths", source)
    guard = HERE / "scope_guard.py"
    done = subprocess.run([sys.executable, "-B", str(guard), "check", "--spec", spec_id, "--root", str(root),
                           "--main", main, "--json", *paths], capture_output=True, text=True, env=env)
    try:
        decisions = json.loads(done.stdout)
    except ValueError:
        return _line("scope/diff", "fail", f"scope_guard.py gave no verdict: {(done.stderr or done.stdout).strip()[-300:]}", source)
    denied = [f"{d['path']} ({d['reason']})" for d in decisions if not d["allowed"]]
    if denied:
        return _line("scope/diff", "fail", f"outside {spec_id} scope.write: " + ", ".join(denied), source)
    return _line("scope/diff", "pass", f"{len(paths)} path(s) in {rev_range} are inside the scope read from {main}", source)


def cmd_rules(ctx: Ctx, args) -> int:
    """``rules check <id>``: every machine-checkable rule against one spec; read-only."""
    sys.dont_write_bytecode = True
    spec_id = args.id
    specs = _offline_specs(ctx.specs_dir)
    rec = specs.get(spec_id)
    if rec is None:
        raise _not_found(spec_id)
    lines = _validator_lines(Path(rec["path"]))
    lines.insert(1, _type_line(rec))
    lines.append(_dependency_line(ctx, rec, specs))
    lines.append(_promotion_line(ctx, rec))
    lines.append(_diff_line(ctx, spec_id, args.diff, args.main))
    failed = [l for l in lines if l["status"] == "fail"]
    payload = {"id": spec_id, "ok": not failed, "guide": RULES_GUIDE, "results": lines}
    text = [f"{l['rule']} | {l['status']} | {l['reason']} | {l['source']}" for l in lines]
    text.append(f"rules check {spec_id}: " + ("all rules pass" if not failed else
                f"{len(failed)} rule(s) failed: " + ", ".join(l["rule"] for l in failed)))
    _emit(args, payload, "\n".join(text))
    return EXIT_PROBLEM if failed else EXIT_OK


# name -> (handler, args spec, writes, offline-capable, summary)
COMMANDS: dict[str, tuple] = {
    "health": (cmd_health, [], False, False, "board /api/health"),
    "list": (cmd_list, ["[--status S]...", "[--layer N]", "[--type T]", "[--parent ID]", "[--text Q]"], False, True,
             "filter specs (effective status)"),
    "show": (cmd_show, ["<id>", "[--body]"], False, True, "frontmatter, run-state explanation, artifact index"),
    "search": (cmd_search, ["<q>"], False, True, "substring over id, title and body"),
    "history": (cmd_history, ["<id>"], False, False, "status checkpoints, newest first"),
    "deps": (cmd_deps, ["<id>"], False, True, "what a spec waits on and what waits on it"),
    "artifacts": (cmd_artifacts, ["<id>", "[--path P]"], False, False, "artifact index or one artifact"),
    "next": (cmd_next, [], False, True, "delegates to nightshift-dag.py next"),
    "who": (cmd_who, [], False, False, "in-progress specs joined with worktree status"),
    "brief": (cmd_brief, ["<id>"], False, True, "delegates to nightshift-instructions.py apply"),
    "refresh": (cmd_refresh, [], False, False, "POST /api/refresh: re-reads spec files, writes nothing"),
    "port": (cmd_port, [], False, True, "the resolved port and how it was resolved"),
    "start": (cmd_start, [], True, True, "start the board (Control when registered, else board.sh --no-open)"),
    "stop": (cmd_stop, [], True, True, "stop the board (Control, else board.sh stop); never signals itself"),
    "restart": (cmd_restart, [], True, True, "stop then start"),
    "status": (cmd_status, [], False, True, "up/down, port and its source, launcher (Control or board.sh PID)"),
    "board-doctor": (cmd_board_doctor, [], False, True, "read-only board diagnosis; each finding names its fix"),
    "transition": (cmd_transition, ["<id>", "<status>", "--reason R", "[--reconsider-when W]", "[--no-commit]",
                                    "[--gap-resolved|--gap-waived-reason R] [--resolution-rationale R] [--finding F]... [--evidence E]... [--readiness-reviewed R]"],
                   True, True, "policy-checked status move through the board's gates; commits spec + artifacts only"),
    "validate": (cmd_validate, ["[<id>... | --staged | --all]", "[--install]"], False, True,
                 "validate_specs.py and, with --install, validate_install.py; one summary"),
    "rules": (cmd_rules, ["check <id>", "[--diff RANGE]", "[--main BRANCH]"], False, True,
              "read-only pre-flight: every machine-checkable rule for one spec, pass/fail/skip with a source"),
}


def describe() -> dict:
    return {"tool": "board_ctl.py", "guide": GUIDE, "exit_codes": {"0": "ok", "1": "not found", "2": "usage",
            "3": "board unreachable for a board-only command",
            "4": "transition refused by the policy or a gate",
            "5": "operation failed, board-doctor found a problem, or a rules check failed"},
            "global_options": ["--json", "--port N", "--project NAME", "--specs-dir DIR", "--control-port N"],
            "port_resolution": ["--port", "projects-registry.json entry", "board.py project-root formula"],
            "commands": [{"name": n, "args": a, "writes": w, "works_offline": o, "summary": s,
                          "guide": GUIDE} for n, (_h, a, w, o, s) in COMMANDS.items()]
            + [{"name": "describe", "args": [], "writes": False, "works_offline": True,
                "summary": "this self-description", "guide": GUIDE}]}


def cmd_describe(ctx: Ctx, args) -> int:
    info = describe()
    text = "\n".join(f"{c['name']} {' '.join(c['args'])}".rstrip() + f"\t{c['summary']}" for c in info["commands"])
    _emit(args, info, text + f"\nguide: {GUIDE}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="machine-readable output")
    common.add_argument("--port", type=int, default=None, help="board port (wins over the registry and the formula)")
    common.add_argument("--project", default=None, help="another registered project, by registry name")
    common.add_argument("--specs-dir", default=None, help="specs directory (default: next to this script)")
    common.add_argument("--control-port", type=int, default=None,
                        help=f"Nightshift Control port for start/stop/status (default: $NIGHTSHIFT_CONTROL_PORT or {CONTROL_DEFAULT_PORT})")
    parser = argparse.ArgumentParser(prog="board_ctl.py", description="Nightshift board client: reads and management")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    def add(name: str, summary: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[common], help=summary, description=summary)

    for name in ("health", "history", "who", "refresh", "port", "next", "start", "stop", "restart", "status",
                 "board-doctor"):
        p = add(name, COMMANDS[name][4])
        if name == "history":
            p.add_argument("id")
    p = add("list", COMMANDS["list"][4])
    p.add_argument("--status", action="append", default=[])
    p.add_argument("--layer", type=int, default=None)
    p.add_argument("--type", default=None)
    p.add_argument("--parent", default=None)
    p.add_argument("--text", default=None)
    p = add("show", COMMANDS["show"][4])
    p.add_argument("id")
    p.add_argument("--body", action="store_true")
    add("search", COMMANDS["search"][4]).add_argument("q")
    add("deps", COMMANDS["deps"][4]).add_argument("id")
    p = add("artifacts", COMMANDS["artifacts"][4])
    p.add_argument("id")
    p.add_argument("--path", default=None)
    add("brief", COMMANDS["brief"][4]).add_argument("id")
    p = add("transition", COMMANDS["transition"][4])
    p.add_argument("id")
    p.add_argument("status")
    p.add_argument("--reason", default=None)
    p.add_argument("--reconsider-when", default=None)
    p.add_argument("--no-commit", action="store_true", help="leave the change in the working tree and print the commit command")
    p.add_argument("--gap-resolved", action="store_true")
    p.add_argument("--gap-waived-reason", default=None)
    p.add_argument("--resolution-rationale", default=None)
    p.add_argument("--readiness-reviewed", default=None, metavar="RATIONALE")
    p.add_argument("--finding", action="append", default=[])
    p.add_argument("--evidence", action="append", default=[])
    p = add("validate", COMMANDS["validate"][4])
    p.add_argument("ids", nargs="*")
    p.add_argument("--staged", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--install", action="store_true")
    p = add("rules", COMMANDS["rules"][4])
    p.add_argument("action", choices=("check",))
    p.add_argument("id")
    p.add_argument("--diff", default=None, help="a git revision range; its paths are checked against the spec's scope")
    p.add_argument("--main", default="main", help="branch the spec's scope is read from (default: main)")
    add("describe", "emit every command with its arguments, whether it writes, and the guide path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ctx = Ctx(args)
        if args.command == "describe":
            return cmd_describe(ctx, args)
        return COMMANDS[args.command][0](ctx, args)
    except CtlError as exc:
        if args.json:
            print(json.dumps({"error": {"code": exc.name, "message": exc.message, "next": exc.next_step,
                                        "exit": exc.code}}, indent=2, sort_keys=True))
        else:
            print(f"board_ctl: {exc.message}" + (f"\n  next: {exc.next_step}" if exc.next_step else ""),
                  file=sys.stderr)
        return exc.code
    except _HttpStatus as exc:
        message = f"board answered {exc.status}"
        if args.json:
            print(json.dumps({"error": {"code": "board_error", "message": message, "exit": EXIT_NOT_FOUND}}))
        else:
            print(f"board_ctl: {message}", file=sys.stderr)
        return EXIT_NOT_FOUND


if __name__ == "__main__":
    sys.exit(main())
