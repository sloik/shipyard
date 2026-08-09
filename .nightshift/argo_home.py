"""Resolve Argo Home explicitly, instead of by counting directory levels.

SPEC-ARGO-017. Before the 2026-08-09 move, code and tests in this kit found Argo
Home by walking up a fixed number of parents:

    ARGO_HOME = CANONICAL.parent.parent.parent          # canonical -> Argo
    Path(__file__).resolve().parents[4] / "Skills"      # tests/     -> Argo

That worked only because the kit sat at exactly ``Argo/ManagedProjects/Nightshift/``.
The nesting depth was load-bearing and invisible: none of those expressions contain
a path string, so no grep for the old location could find them. When the tree moved
to ``Developer/ManagedProjects`` every one of them silently began resolving to a
different directory — ``parents[3]`` became ``Developer`` rather than ``Argo``.

Why not ``path_vars._argo_home``: that resolver walks up looking for a ``session.md``
marker, which worked when the kit lived *inside* Argo Home. From the new location
there is no such marker on any ancestor, so the walk-up cannot succeed. The env var
is now the only load-bearing route, with a documented default.

This helper is deliberately small and has no dependency on where the kit lives.
"""

from __future__ import annotations

import os
from pathlib import Path

# The conventional location. Overridable by $ARGO_HOME, which is what a VM, a test
# fixture, or a relocated Argo Home should set. Kept as a documented constant rather
# than a bare literal so there is one place to change it.
DEFAULT_ARGO_HOME = Path.home() / "Dropbox" / "Argo"


def argo_home() -> Path:
    """Return Argo Home: ``$ARGO_HOME`` if set, else the conventional default.

    Never derived from this file's position on disk — that is the coupling this
    module exists to remove. The result is not checked for existence: callers fail
    loudly and specifically on the file they actually wanted, which is a better
    error than a generic "Argo Home not found" from here.
    """
    env = os.environ.get("ARGO_HOME")
    if env:
        return Path(env).expanduser()
    return DEFAULT_ARGO_HOME


DEFAULT_MANAGED_PROJECTS = Path.home() / "Dropbox" / "Developer" / "ManagedProjects"


def managed_projects_home() -> Path:
    """Return the managed-projects root: ``$MANAGED_PROJECTS_HOME`` or the default.

    SPEC-ARGO-017, second move (2026-08-09): Cortex and DevKB left Argo Home too, so
    ``argo_home() / "Cortex"`` — correct that morning — was a dead path by evening.
    Peers of this kit are addressed from here, not from Argo Home.
    """
    env = os.environ.get("MANAGED_PROJECTS_HOME")
    if env:
        return Path(env).expanduser()
    return DEFAULT_MANAGED_PROJECTS


def cortex_root() -> Path:
    """Return the Cortex checkout root; its module paths hang off this.

    The Cortex *database* is not here and has not been since SPEC-CTX-CORE-021 — it
    lives under ``~/Dropbox/ArgoData`` and Cortex resolves it itself, which is why
    neither relocation touched it.
    """
    return managed_projects_home() / "Cortex"


def argo_home_available() -> bool:
    """True when Argo Home is present and looks like Argo Home.

    For tests that assert kit-vs-Argo conformance and should be skipped rather than
    failed on a machine that has the kit checked out without Argo Home beside it —
    the kit is now a separate repository and that combination is legitimate.
    """
    return (argo_home() / "session.md").is_file()
