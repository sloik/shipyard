"""Host-enforceable deny-by-default sandbox backends for extension children."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from extension_protocol import ProtocolError


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
                f'(subpath "{root}") {ancestor_rules})))'
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
