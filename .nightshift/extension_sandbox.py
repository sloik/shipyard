"""Host-enforceable deny-by-default sandbox backends for extension children."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from extension_protocol import ProtocolError

# Prefixes already covered by the sandbox profile's own file-read-data
# allowlist. A resolved active developer directory under one of these needs
# no extra rule (Command Line Tools is the common case).
_ALREADY_ALLOWED_READ_PREFIXES = (
    "/usr",
    "/System",
    "/Library/Apple",
    "/Library/Developer/CommandLineTools",
)

# _CS_DARWIN_USER_TEMP_DIR: not exposed by Python's os.confstr_names (CPython
# only wires the POSIX _CS_* codes), so the numeric value is read directly
# via libc. Stable Darwin ABI constant (System/Library/Frameworks headers
# ship it under <unistd.h> since 10.5); verified empirically on this host
# with getconf(1) DARWIN_USER_TEMP_DIR before use.
_CS_DARWIN_USER_TEMP_DIR = 65537


def _darwin_user_temp_dir() -> str | None:
    """Read-only, non-mutating lookup of the per-user Darwin scratch dir."""
    try:
        libc_path = ctypes.util.find_library("c")
        if not libc_path:
            return None
        libc = ctypes.CDLL(libc_path)
        buf = ctypes.create_string_buffer(1024)
        length = libc.confstr(_CS_DARWIN_USER_TEMP_DIR, buf, ctypes.sizeof(buf))
        if length <= 0 or length >= ctypes.sizeof(buf):
            return None
        value = buf.value.decode()
        if not value:
            return None
        # confstr returns the /var/... form; the sandbox matches literals
        # against the resolved filesystem path (/var is a symlink to
        # /private/var on macOS), so resolve it the same way the kernel
        # will before it is used in a literal rule.
        return os.path.realpath(value)
    except OSError:
        return None


def _resolve_active_developer_dir() -> str | None:
    """Resolve the active developer directory the xcrun shim will see.

    Read-only: resolves the /var/db/xcode_select_link symlink directly
    rather than shelling out to `xcode-select -p` (which honours a
    DEVELOPER_DIR the sandboxed child's scrubbed env will not have, and
    would report a value the child does not actually see). Never mutates
    host state. Returns None if the link is absent, broken, or does not
    resolve to a directory -- the caller must then leave the profile
    byte-identical to today's (R3).
    """
    link = Path("/var/db/xcode_select_link")
    try:
        resolved = Path(os.path.realpath(link))
    except OSError:
        return None
    if not resolved.is_dir():
        return None
    return str(resolved)


@dataclass(frozen=True)
class Launch:
    argv: tuple[str, ...]
    env: dict[str, str]


class SandboxBackend:
    enforceable = False

    def require(self, *, capabilities: Iterable[str], endpoint: str | None) -> None:
        if not self.enforceable:
            raise ProtocolError("host sandbox unavailable")

    def launch(
        self,
        executable: Path,
        job_root: Path,
        capabilities: tuple[str, ...],
        endpoint: str | None,
    ) -> Launch:
        raise NotImplementedError


class MacOSSandboxBackend(SandboxBackend):
    """sandbox-exec profile: no host writes/reads/network unless explicitly named."""

    def __init__(self, binary: str | None = None):
        self.binary = binary or shutil.which("sandbox-exec")
        self.enforceable = bool(self.binary)

    def require(self, *, capabilities: Iterable[str], endpoint: str | None) -> None:
        super().require(capabilities=capabilities, endpoint=endpoint)
        if "network.loopback" in capabilities and not endpoint:
            raise ProtocolError("loopback endpoint missing")

    def launch(
        self,
        executable: Path,
        job_root: Path,
        capabilities: tuple[str, ...],
        endpoint: str | None,
    ) -> Launch:
        self.require(capabilities=capabilities, endpoint=endpoint)
        root = str(job_root.resolve())
        executable = str(executable.resolve())
        ancestor_rules = " ".join(
            f'(literal "{item}")'
            for item in sorted(
                {
                    str(parent)
                    for value in (Path(root), Path(executable))
                    for parent in value.parents
                }
            )
        )
        # System Python (/usr/bin/python3) is an xcrun shim: it loads
        # libxcrun.dylib from the ACTIVE developer directory, which is
        # /Library/Developer/CommandLineTools (already allowed above) only
        # when the Command Line Tools are selected. When a full Xcode.app is
        # selected instead, the load falls outside every existing rule and
        # the child dies at start. Resolve the directory the child will
        # actually see (read-only; SPEC-388) and, if it needs a new rule, add
        # exactly it plus the one cache file the shim also needs to avoid a
        # write-then-fork fallback path this sandbox must not open (R2: no
        # write/fork widening). Resolution failure or an already-covered
        # directory leaves this empty -- the profile stays byte-identical to
        # before this rule existed (R3).
        developer_dir_rules = ""
        developer_dir = _resolve_active_developer_dir()
        if developer_dir and not developer_dir.startswith(
            _ALREADY_ALLOWED_READ_PREFIXES
        ):
            developer_dir_rules = f'(subpath "{developer_dir}") '
            user_temp_dir = _darwin_user_temp_dir()
            if user_temp_dir:
                cache_file = os.path.join(user_temp_dir, "xcrun_db")
                developer_dir_rules += f'(literal "{cache_file}") '
        # sandbox-exec deny rules cannot be reopened by a later allow. Express
        # the filesystem/exec allowlist as exclusions on the deny rule itself.
        profile = [
            "(version 1)",
            "(allow default)",
            "(deny network*)",
            # Observers have no authority over unrelated host processes. This
            # still permits normal exit and sandbox-inherited exec/fork, while
            # kill(2) and equivalent outbound signals fail at the host boundary.
            "(deny signal)",
            # Script runtimes may inspect their own process; unrelated process
            # metadata remains unavailable.
            "(deny process-info* (require-not (target self)))",
            # v1 enforces a stricter one-process policy for every positive
            # max_processes admission. Interpreter/script exec remains allowed;
            # recursive consumers cannot fork another process.
            "(deny process-fork)",
            (
                "(deny file-read-data "
                "(require-not (require-any "
                '(subpath "/usr") '
                '(subpath "/System") '
                '(subpath "/Library/Apple") '
                '(subpath "/Library/Developer/CommandLineTools") '
                '(subpath "/private/var/db/dyld") '
                '(literal "/dev/urandom") '
                f'(literal "{executable}") '
                f'(subpath "{root}") {ancestor_rules}'
                f'{" " + developer_dir_rules.strip() if developer_dir_rules else ""}'
                ")))"
            ),
            # Every admitted extension may write only its declarative transport
            # output. Input and durable source events remain read-only.
            (
                "(deny file-write* (require-not (require-any "
                f'(literal "{root}/output.json") '
                '(literal "/dev/dtracehelper"))))'
            ),
        ]
        # Child networking stays denied even with network.loopback. The trusted
        # parent broker owns the one exact numeric connection; the child can only
        # submit a closed bounded declarative request in output.json.
        env = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "NIGHTSHIFT_EXTENSION_INPUT": "input.json",
            "NIGHTSHIFT_EXTENSION_OUTPUT": "output.json",
            # System Python is a supported script entry-point class. Keep its
            # imports read-only and prevent bytecode cache writes.
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        return Launch((self.binary, "-p", "\n".join(profile), executable), env)


class FakeSandboxBackend(SandboxBackend):
    """Deterministic dependency-injected backend for supervisor tests only."""

    enforceable = True

    def __init__(self, *, supported: Iterable[str] = ()):
        self.supported = frozenset(supported)

    def require(self, *, capabilities: Iterable[str], endpoint: str | None) -> None:
        missing = set(capabilities) - self.supported
        if missing:
            raise ProtocolError(
                "unsupported capabilities: " + ",".join(sorted(missing))
            )

    def launch(
        self,
        executable: Path,
        job_root: Path,
        capabilities: tuple[str, ...],
        endpoint: str | None,
    ) -> Launch:
        self.require(capabilities=capabilities, endpoint=endpoint)
        return Launch(
            (str(executable),),
            {
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "NIGHTSHIFT_EXTENSION_INPUT": "input.json",
                "NIGHTSHIFT_EXTENSION_OUTPUT": "output.json",
            },
        )


def host_backend() -> SandboxBackend:
    return MacOSSandboxBackend() if os.uname().sysname == "Darwin" else SandboxBackend()
