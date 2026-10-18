"""Shared local prompt authority; reads never create or migrate stores.

Schema 2 stores snippets/folders in an object. The first legacy-list mutation
retains its exact bytes in ``<store>.v1.<sha256>.bak``. Rollback means stopping
all writers and restoring that backup (post-migration edits must be exported
first). Old list-only writers are unsupported once schema 2 is written; legacy
HTTP writers must upgrade and supply a revision, never bypass CAS.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

API_VERSION = 1

SCOPES = ("prebuilt", "repo", "project")
_DEFAULTS = {"tags": [], "harness_overrides": {}, "variables": [], "created_at": "", "updated_at": ""}
_VARIABLE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
_ACTION = re.compile(r"([/$])\bnightshift\s+([a-z][a-z-]*)", re.I)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]*\Z")


class LibraryError(Exception):
    def __init__(self, status, code, message="", **details):
        super().__init__(message or code)
        self.status, self.code, self.details = status, code, details
        self.message = message or code


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _atomic(path, raw):
    """Unique same-directory temporary, fsync before atomic replacement."""
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class PromptLibrary:
    def __init__(self, paths, *, board_url="", known_actions=()):
        self.paths = {s: Path(paths[s]).resolve() if paths.get(s) is not None else None for s in SCOPES}
        self.board_url, self.known_actions = board_url, set(known_actions)

    def _path(self, scope):
        if scope not in SCOPES:
            raise LibraryError(400, "invalid_scope")
        path = self.paths[scope]
        if path is None:
            raise LibraryError(400, "no_repo_root" if scope == "repo" else "unavailable")
        return path

    def _authority(self, scope):
        return _digest((scope + "\0" + str(self._path(scope))).encode())

    def _read(self, scope):
        path = self._path(scope)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = None
        except OSError as exc:
            raise LibraryError(503, "store_unavailable", str(exc), scope=scope) from exc
        legacy = False
        if raw is None:
            document = {"schema_version": 2, "snippets": [], "folders": []}
        else:
            try:
                data = json.loads(raw)
                legacy = isinstance(data, list)
                document = {"schema_version": 2, "snippets": data, "folders": []} if legacy else data
                if not isinstance(document, dict) or document.get("schema_version") != 2:
                    raise ValueError("unsupported schema")
                snippets, folders = document["snippets"], document["folders"]
                if not isinstance(snippets, list) or not isinstance(folders, list):
                    raise ValueError("expected snippets/folders lists")
                ids = set()
                for item in snippets:
                    if not isinstance(item, dict) or not {"id", "title", "scope", "body"} <= item.keys():
                        raise ValueError("malformed snippet")
                    if not all(isinstance(item[k], str) for k in ("id", "title", "scope", "body")) or item["id"] in ids:
                        raise ValueError("invalid or duplicate snippet identity")
                    ids.add(item["id"])
                folder_ids, names = set(), set()
                for folder in folders:
                    if not isinstance(folder, dict) or not isinstance(folder.get("id"), str) or not isinstance(folder.get("name"), str):
                        raise ValueError("malformed folder")
                    key = folder["name"].strip().casefold()
                    if not key or key in names or folder["id"] in folder_ids:
                        raise ValueError("duplicate folder")
                    folder_ids.add(folder["id"])
                    names.add(key)
                if any(item.get("folder_id") is not None and item["folder_id"] not in folder_ids for item in snippets):
                    raise ValueError("unknown folder")
            except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                raise LibraryError(503, "malformed_store", str(exc), scope=scope) from exc
        revision = self._authority(scope) + ":" + _digest(raw if raw is not None else b"missing")
        return document, raw, legacy, revision

    def _item(self, scope, entry, revision):
        result = copy.deepcopy(_DEFAULTS)
        result.update(copy.deepcopy(entry))
        result.update(scope=scope, identity=self._authority(scope) + ":" + entry["id"], revision=revision)
        result.setdefault("folder_id", None)
        result.setdefault("kind", "plain")
        return result

    def snapshot(self):
        items, stores = [], {}
        for scope in SCOPES:
            if self.paths[scope] is None:
                continue
            document, _, _, revision = self._read(scope)
            stores[scope] = {"identity": self._authority(scope), "revision": revision, "folders": copy.deepcopy(document["folders"])}
            items.extend(self._item(scope, e, revision) for e in document["snippets"])
        items.sort(key=lambda e: (e["title"].casefold(), e["identity"]))
        return {"items": items, "stores": stores}

    @contextmanager
    def _locks(self):
        # Sorted resolved authority paths avoid cross-scope deadlocks and ensure
        # collision checks see concurrent creates in the other writable scope.
        with ExitStack() as stack:
            for path in sorted(set(p for s, p in self.paths.items() if s != "prebuilt" and p is not None)):
                path.parent.mkdir(parents=True, exist_ok=True)
                stream = stack.enter_context(path.with_name(path.name + ".lock").open("a+b"))
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            yield

    def _find(self, scope, id):
        document, _, _, revision = self._read(scope)
        for item in document["snippets"]:
            if item["id"] == id:
                return self._item(scope, item, revision)
        raise LibraryError(404, "not_found")

    def mutate(self, scope, action, payload, revision):
        path = self._path(scope)
        if scope == "prebuilt":
            raise LibraryError(403, "prebuilt_read_only")
        if not revision:
            raise LibraryError(428, "precondition_required", "Reload with an upgraded client and supply the store revision.")
        if not isinstance(revision, str) or not revision.startswith(self._authority(scope) + ":"):
            raise LibraryError(409, "conflict", "Revision belongs to another authority; reload/reapply.")
        allowed = {"create", "update", "delete", "duplicate", "folder_create", "folder_rename", "folder_delete", "move"}
        if action not in allowed:
            raise LibraryError(400, "invalid_action")
        try:
            with self._locks():
                # Refuse unreadable peer stores before committing: the merged
                # post-write response must not discover a pre-existing error
                # only after the target bytes have already changed.
                for other in SCOPES:
                    if self.paths[other] is not None:
                        self._read(other)
                document, raw, legacy, current = self._read(scope)
                if revision != current and action not in {"create", "duplicate", "folder_create"}:
                    raise LibraryError(409, "conflict", "Store changed; reload/reapply.", revision=current)
                entries, folders = document["snippets"], document["folders"]
                item = None
                if action.startswith("folder_"):
                    if action == "folder_create":
                        item = {"id": "folder-" + uuid.uuid4().hex, "name": ""}
                    else:
                        item = next((f for f in folders if f["id"] == payload.get("id")), None)
                        if item is None:
                            raise LibraryError(404, "folder_not_found")
                    if action == "folder_delete":
                        count = sum(e.get("folder_id") == item["id"] for e in entries)
                        if count:
                            raise LibraryError(409, "folder_not_empty", count=count)
                        folders.remove(item)
                        item = None
                    else:
                        name = payload.get("name", "")
                        if not isinstance(name, str) or not name.strip():
                            raise LibraryError(400, "invalid_folder_name")
                        name = name.strip()
                        if any(f["id"] != item["id"] and f["name"].strip().casefold() == name.casefold() for f in folders):
                            raise LibraryError(409, "folder_name_collision")
                        item["name"] = name
                        if action == "folder_create":
                            folders.append(item)
                elif action in {"create", "duplicate"}:
                    if action == "duplicate":
                        source = self._find(payload.get("source_scope", scope), payload.get("source_id"))
                        item = {k: copy.deepcopy(v) for k, v in source.items() if k not in {"identity", "revision", "scope", "id", "created_at", "updated_at", "folder_id"}}
                        item["title"] = payload.get("title", item["title"] + " (copy)")
                        item["id"] = payload.get("id") or (source["id"] + "-" + uuid.uuid4().hex[:12])
                    else:
                        item = {k: copy.deepcopy(v) for k, v in payload.items() if k not in {"action", "revision", "identity", "scope", "created_at", "updated_at"}}
                        title = item.get("title", "")
                        item["id"] = item.get("id") or re.sub(r"[^a-z0-9]+", "-", str(title).strip().lower()).strip("-") or "snippet"
                        item.setdefault("title", "")
                        item.setdefault("body", "")
                    if not isinstance(item["id"], str) or not item["id"]:
                        raise LibraryError(400, "invalid_id")
                    for other in SCOPES:
                        if self.paths[other] is not None and any(e["id"] == item["id"] for e in self._read(other)[0]["snippets"]):
                            raise LibraryError(409, "id_collision", existing_scope=other)
                    item.update(scope=scope, created_at=_now(), updated_at=_now())
                    item.setdefault("kind", "plain")
                    item["folder_id"] = payload.get("folder_id")
                    entries.append(item)
                else:
                    item = next((e for e in entries if e["id"] == payload.get("id")), None)
                    if item is None:
                        raise LibraryError(404, "not_found")
                    if action == "delete":
                        entries.remove(item)
                        item = None
                    else:
                        fields = ("folder_id",) if action == "move" else ("title", "body", "tags", "variables", "harness_overrides", "kind", "folder_id")
                        for field in fields:
                            if field in payload:
                                item[field] = copy.deepcopy(payload[field])
                        item["updated_at"] = _now()
                if item is not None and not action.startswith("folder_"):
                    self._validate_item(item, folders, canonicalize=action in {"create", "duplicate"} or "kind" in payload or "body" in payload)
                if legacy:
                    backup = path.with_name(path.name + ".v1." + _digest(raw) + ".bak")
                    if backup.exists():
                        if backup.read_bytes() != raw:
                            raise LibraryError(503, "backup_conflict")
                    else:
                        # Under the authority lock; never replace a backup.
                        with backup.open("xb") as stream:
                            stream.write(raw)
                            stream.flush()
                            os.fsync(stream.fileno())
                _atomic(path, json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"))
                snapshot = self.snapshot()
                if item is not None and not action.startswith("folder_"):
                    item = next(e for e in snapshot["items"] if e["scope"] == scope and e["id"] == item["id"])
                return {"item": copy.deepcopy(item), "snapshot": snapshot}
        except OSError as exc:
            raise LibraryError(503, "write_failed", str(exc)) from exc

    @staticmethod
    def _validate_item(item, folders, *, canonicalize):
        if not isinstance(item.get("title"), str) or not isinstance(item.get("body"), str):
            raise LibraryError(400, "invalid_snippet")
        if not isinstance(item.get("tags", []), list) or not all(isinstance(t, str) for t in item.get("tags", [])):
            raise LibraryError(400, "invalid_tags")
        if not isinstance(item.get("variables", []), list) or not isinstance(item.get("harness_overrides", {}), dict):
            raise LibraryError(400, "invalid_snippet")
        if item.get("folder_id") is not None and not any(f["id"] == item["folder_id"] for f in folders):
            raise LibraryError(400, "folder_not_found")
        kind = item.get("kind", "plain")
        if kind not in {"plain", "command"}:
            raise LibraryError(400, "invalid_kind")
        if kind == "command":
            body = item["body"]
            if canonicalize and body[:1] in {"$", "/"}:
                body = body[1:]
            token = re.split(r"\s", body, maxsplit=1)[0]
            if not _TOKEN.fullmatch(token):
                raise LibraryError(400, "invalid_command")
            item["body"] = body

    def render(self, scope, id, payload=None):
        item = self._find(scope, id)
        payload = payload or {}
        variables = dict(payload.get("variables") or {})
        variables["board_url"] = self.board_url
        text = (item.get("harness_overrides") or {}).get(payload.get("harness") or "other")
        if text is None:
            text = item["body"]
        warnings, seen = [], set()
        def substitute(match):
            name = match.group(1)
            if name in variables:
                return str(variables[name])
            if name not in seen:
                seen.add(name)
                warnings.append("missing_variable:" + name)
            return match.group(0)
        text = _VARIABLE.sub(substitute, text)
        seen = set()
        for match in _ACTION.finditer(text):
            action = match.group(2).lower()
            if action not in self.known_actions and action not in seen:
                seen.add(action)
                warnings.append("stale_command:" + action)
        return {"text": text, "warnings": warnings}

    def copy(self, scope, id, mode):
        item = self._find(scope, id)
        if mode == "plain":
            return {"text": item["body"]}
        if mode not in {"codex", "claude"}:
            raise LibraryError(400, "invalid_copy_mode")
        if item["kind"] != "command":
            raise LibraryError(400, "not_command")
        self._validate_item(item, self._read(scope)[0]["folders"], canonicalize=False)
        return {"text": ("$" if mode == "codex" else "/") + item["body"]}


def register_library_routes(app, provider, prefix="/api/prompt-library"):
    from fastapi import Request
    from fastapi.responses import JSONResponse

    def respond(operation):
        try:
            return operation()
        except LibraryError as exc:
            return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message, **exc.details})

    # Explicit annotations avoid postponed local Request-name resolution.
    def snapshot(request):
        return respond(lambda: provider(request).snapshot())
    snapshot.__annotations__ = {"request": Request}
    app.get(prefix)(snapshot)

    def mutate(scope, payload, request):
        return respond(lambda: provider(request).mutate(scope, payload.get("action"), payload, payload.get("revision")))
    mutate.__annotations__ = {"scope": str, "payload": dict, "request": Request}
    app.post(prefix + "/{scope}/mutate")(mutate)

    def render(scope, id, payload, request):
        return respond(lambda: provider(request).render(scope, id, payload))
    render.__annotations__ = {"scope": str, "id": str, "payload": dict, "request": Request}
    app.post(prefix + "/{scope}/{id}/render")(render)

    def copy_text(scope, id, payload, request):
        return respond(lambda: provider(request).copy(scope, id, payload.get("mode", "plain")))
    copy_text.__annotations__ = {"scope": str, "id": str, "payload": dict, "request": Request}
    app.post(prefix + "/{scope}/{id}/copy")(copy_text)
