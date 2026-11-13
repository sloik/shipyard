#!/usr/bin/env python3
"""Copy only explicitly allowed, non-secret project config to a linked worktree.

Records deliberately contain no contents, exception strings or absolute OS paths.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile

from config_migrations import load_config_documents, merge_config_documents
from scanner import FixtureRegistry, ScannerConfig, scan_diff
from spec_artifacts import project_config_path
from worktree_paths import assert_worktree_owner

DEFAULT_COPY = ('.claude/settings.local.json',)
BUILTIN_DENY = ('.env', '.env.*', '*.pem', '*.key', '.netrc', 'id_rsa*', '*credentials*')


class LocalConfigError(ValueError):
    """A configuration error whose fixed message is safe for reports."""


def load_local_config(repo: Path) -> dict:
    # Same installed/flat layout as project_config_path; canonical is the kit's
    # flat project inside its Git root. Never search other projects or parents.
    candidates = (repo / '.nightshift', repo / 'canonical', repo)
    home = next((p for p in candidates if (p / 'config.yaml').is_file()), repo)
    path = project_config_path(home / 'specs')
    try:
        config = merge_config_documents(load_config_documents(path.read_text())) if path.exists() else {}
        git = config.get('git', {})
        value = git.get('worktree_local_config', {})
        if not isinstance(value, dict):
            raise ValueError
        copy = value.get('copy', list(DEFAULT_COPY))
        deny = value.get('deny', [])
        required = value.get('required', False)
        if (not isinstance(copy, list) or not all(isinstance(p, str) for p in copy)
                or not isinstance(deny, list) or not all(isinstance(p, str) and '\n' not in p and '\r' not in p for p in deny)
                or type(required) is not bool):
            raise ValueError
        return {'copy': copy, 'deny': deny, 'required': required}
    except (OSError, ValueError, TypeError, AttributeError):
        raise LocalConfigError('invalid_config') from None


def _git(repo: Path, *args: str):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, check=False)


def _denied(path: str, patterns: list[str] | tuple[str, ...]) -> bool:
    if not patterns:
        return False
    # Git supplies its own gitignore grammar. Use an isolated repository so
    # ordinary ignored permission files and global ignores are not secret rules.
    with tempfile.TemporaryDirectory(prefix='nightshift-config-deny-') as directory:
        root = Path(directory)
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        for key in list(env):
            if key.startswith(('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE')):
                env.pop(key)
        init = subprocess.run(['git', 'init', '-q', str(root)], env=env, capture_output=True)
        if init.returncode:
            raise LocalConfigError('deny_check_failed')
        (root / '.gitignore').write_text('\n'.join(patterns) + '\n')
        result = subprocess.run(['git', '-C', str(root), '-c', 'core.excludesFile=' + os.devnull,
                                 'check-ignore', '--no-index', '-q', '--', path], env=env, capture_output=True)
        if result.returncode not in (0, 1):
            raise LocalConfigError('deny_check_failed')
        return result.returncode == 0


def _relative(path: str) -> bool:
    p = PurePosixPath(path)
    return (bool(path) and not p.is_absolute() and all(x not in ('..', '.', '') for x in path.split('/'))
            and not any(c in path for c in ('\\', '\x00', '\n', '\r', '*', '?', '[', ']'))
            and '.git' not in p.parts)


def _open_parent(root: Path, parts: tuple[str, ...], *, create: bool) -> int:
    """Directory descriptors plus O_NOFOLLOW close parent-symlink races."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _copy_one(repo: Path, worktree: Path, path: str, deny: list[str]) -> tuple[str, str]:
    if not _relative(path):
        return 'skipped', 'invalid_path'
    if _denied(path, BUILTIN_DENY) or _denied(path, deny):
        return 'skipped', 'secret_path'
    tracked = _git(worktree, 'ls-files', '--error-unmatch', '--', path)
    if tracked.returncode == 0:
        return 'skipped', 'tracked'
    if tracked.returncode != 1:
        return 'failed', 'git_check_failed'
    source_tracked = _git(repo, 'ls-files', '--error-unmatch', '--', path)
    if source_tracked.returncode == 0:
        return 'skipped', 'tracked'
    if source_tracked.returncode != 1:
        return 'failed', 'git_check_failed'
    parts = PurePosixPath(path).parts
    try:
        source_parent = _open_parent(repo, parts[:-1], create=False)
    except FileNotFoundError:
        return 'absent', 'missing'
    except OSError as exc:
        return ('skipped', 'unsafe_source') if exc.errno in (errno.ELOOP, errno.ENOTDIR) else ('failed', 'source_read_failed')
    try:
        try:
            source = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_parent)
        except FileNotFoundError:
            return 'absent', 'missing'
        except OSError as exc:
            return ('skipped', 'unsafe_source') if exc.errno in (errno.ELOOP, errno.ENOTDIR) else ('failed', 'source_read_failed')
        try:
            info = os.fstat(source)
            if not stat.S_ISREG(info.st_mode):
                return 'skipped', 'not_file'
            with os.fdopen(source, 'rb', closefd=False) as stream:
                content = stream.read()
        finally:
            os.close(source)
    finally:
        os.close(source_parent)
    diff = 'diff --git a/local-config b/local-config\n+++ b/local-config\n@@ -0,0 +1 @@\n' + ''.join('+' + line + '\n' for line in content.decode('utf-8', errors='replace').splitlines())
    if scan_diff(diff, config=ScannerConfig(), fixtures=FixtureRegistry()).blocked:
        return 'skipped', 'secret_content'
    target_parent = _open_parent(worktree, parts[:-1], create=True)
    try:
        try:
            target = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             stat.S_IMODE(info.st_mode), dir_fd=target_parent)
        except FileExistsError:
            try:
                existing = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=target_parent)
                with os.fdopen(existing, 'rb') as stream:
                    existing_info = os.fstat(stream.fileno())
                    same = stat.S_ISREG(existing_info.st_mode) and stream.read() == content
                return ('unchanged', 'identical') if same else ('skipped', 'exists')
            except OSError:
                return 'skipped', 'exists'
        try:
            with os.fdopen(target, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
        except BaseException:
            os.unlink(parts[-1], dir_fd=target_parent)
            raise
    finally:
        os.close(target_parent)
    return 'copied', 'allowed'


def copy_local_config(repo_root: Path, worktree: Path, *, config: dict | None = None) -> list[dict]:
    repo, target = Path(repo_root).resolve(), Path(worktree).resolve()
    assert_worktree_owner(repo, target)
    settings = load_local_config(repo) if config is None else config
    records = []
    for path in dict.fromkeys(settings['copy']):
        try:
            action, reason = _copy_one(repo, target, path, settings['deny'])
        except (OSError, subprocess.SubprocessError, LocalConfigError):
            action, reason = 'failed', 'copy_failed'
        # Absolute invalid input is not exposed as an OS path in diagnostics.
        safe_path = path if not Path(path).is_absolute() else '<invalid-path>'
        records.append({'path': safe_path, 'action': action, 'reason': reason})
    return records


def required_failed(records: list[dict], settings: dict) -> bool:
    return settings['required'] and any(r['action'] not in ('copied', 'unchanged', 'absent') for r in records)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('copy')
    command.add_argument('--repo', type=Path, required=True)
    command.add_argument('--worktree', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        settings = load_local_config(args.repo.resolve())
        records = copy_local_config(args.repo, args.worktree, config=settings)
        code = int(required_failed(records, settings))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        records, code = [{'path': '', 'action': 'failed', 'reason': 'configuration_or_worktree_invalid'}], 1
    print(json.dumps(records))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
