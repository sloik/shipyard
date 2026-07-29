#!/usr/bin/env python3
"""
Pluggable handler architecture for the Nightshift Kit.

Each domain (code, research, analysis) is a SpecHandler subclass.
The HandlerRegistry maps names to handlers and resolves the correct
handler for a given spec + config combination.

SPEC-033 — see plans/specs/SPEC-033-handler-architecture.md
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import importlib.util

# ---------------------------------------------------------------------------
# Step constants
# ---------------------------------------------------------------------------

ALL_STEPS: List[float] = [
    1, 2, 3, 4, 5, 6, 7, 8, 8.5, 9, 9.5, 10, 11, 12, 13, 14, 15, 16,
]

RESEARCH_ACTIVE_STEPS = {1, 4, 5, 7, 8, 9, 10}

# ---------------------------------------------------------------------------
# Outcome dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """Immutable result of a handler execution."""

    status: str  # "success" | "failure" | "blocked" | "skipped"
    artifacts: List[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    next_action: Optional[str] = None


# ---------------------------------------------------------------------------
# HandlerContext — SPEC-041 R2
# ---------------------------------------------------------------------------


@dataclass
class HandlerContext:
    """Runtime context passed to ``SpecHandler.execute``.

    SPEC-041 R2. Fields are intentionally generic so that per-domain handlers
    can pull what they need without coupling to the loop internals.
    """

    project_root: Optional[Path] = None
    spec_path: Optional[Path] = None
    events_logger: Any = None   # duck-typed: .emit(event_type, spec_id=?, **fields)
    config: Dict[str, Any] = field(default_factory=dict)
    checkpoint_dir: Optional[Path] = None

    def as_dict(self) -> Dict[str, Any]:
        """Shallow dict view (used where existing handlers expect ``context: dict``)."""
        return {
            "project_root": self.project_root,
            "spec_path": self.spec_path,
            "events_logger": self.events_logger,
            "config": self.config,
            "checkpoint_dir": self.checkpoint_dir,
        }


# ---------------------------------------------------------------------------
# SpecHandler ABC
# ---------------------------------------------------------------------------


class SpecHandler(ABC):
    """Abstract base class for domain-specific spec handlers."""

    @abstractmethod
    def execute(self, spec: dict, context: dict) -> Outcome:
        """Return execution instructions for the LOOP agent.

        Handlers do NOT run shell commands — they return structured data
        describing what the LOOP engine should do.
        """
        ...

    @abstractmethod
    def validate(self, spec: dict, config: dict) -> List[str]:
        """Validate that spec + config satisfy this handler's requirements.

        Returns a list of error strings (empty list = valid).
        """
        ...

    @abstractmethod
    def step_profile(self) -> Dict[float, str]:
        """Map LOOP step numbers to behaviour modes.

        Returns a dict mapping step number (int or float) to one of:
        "active", "standard", or "skip".
        """
        ...

    def teardown(self, context: dict) -> None:
        """Optional cleanup hook.  Default is a no-op."""
        pass


# ---------------------------------------------------------------------------
# Built-in handlers
# ---------------------------------------------------------------------------


class CodeHandler(SpecHandler):
    """Handler for domain: code — default TDD cycle."""

    def execute(self, spec: dict, context: dict) -> Outcome:
        return Outcome(
            status="success",
            artifacts=[],
            metrics={},
            next_action=None,
        )

    def validate(self, spec: dict, config: dict) -> List[str]:
        errors: List[str] = []
        commands = config.get("commands", {})
        build_cmd = commands.get("build", "")
        test_cmd = commands.get("test", "")
        if not build_cmd:
            errors.append("commands.build must be a non-empty string")
        if not test_cmd:
            errors.append("commands.test must be a non-empty string")
        return errors

    def step_profile(self) -> Dict[float, str]:
        return {step: "standard" for step in ALL_STEPS}


class ResearchHandler(SpecHandler):
    """Handler for domain: research — source gathering and synthesis."""

    def execute(self, spec: dict, context: dict) -> Outcome:
        return Outcome(
            status="success",
            artifacts=[],
            metrics={},
            next_action=None,
        )

    def validate(self, spec: dict, config: dict) -> List[str]:
        errors: List[str] = []
        domain = config.get("domain", {})
        if not domain.get("output_dir"):
            errors.append("domain.output_dir must be configured")
        if not domain.get("output_format"):
            errors.append("domain.output_format must be configured")
        return errors

    def step_profile(self) -> Dict[float, str]:
        profile: Dict[float, str] = {}
        for step in ALL_STEPS:
            if step in RESEARCH_ACTIVE_STEPS:
                profile[step] = "active"
            else:
                profile[step] = "standard"
        return profile


class AnalysisHandler(SpecHandler):
    """Handler for domain: analysis — data processing and reporting."""

    def execute(self, spec: dict, context: dict) -> Outcome:
        return Outcome(
            status="success",
            artifacts=[],
            metrics={},
            next_action=None,
        )

    def validate(self, spec: dict, config: dict) -> List[str]:
        errors: List[str] = []
        domain = config.get("domain", {})
        if not domain.get("output_dir"):
            errors.append("domain.output_dir must be configured")
        if not domain.get("validate"):
            errors.append("domain.validate must be a non-empty command")
        return errors

    def step_profile(self) -> Dict[float, str]:
        profile: Dict[float, str] = {}
        for step in ALL_STEPS:
            if step in RESEARCH_ACTIVE_STEPS:
                profile[step] = "active"
            else:
                profile[step] = "standard"
        return profile


# ---------------------------------------------------------------------------
# HandlerRegistry
# ---------------------------------------------------------------------------


class HandlerRegistry:
    """Registry that maps handler names to SpecHandler instances."""

    def __init__(self) -> None:
        self._handlers: Dict[str, SpecHandler] = {}

    def register(self, name: str, handler: SpecHandler) -> None:
        """Register a handler by name.  Raises ValueError on duplicate."""
        if name in self._handlers:
            raise ValueError(
                f"Handler '{name}' is already registered. "
                f"Registered handlers: {sorted(self._handlers)}"
            )
        self._handlers[name] = handler

    def get(self, name: str) -> SpecHandler:
        """Return handler by name.  Raises KeyError if not found."""
        if name not in self._handlers:
            raise KeyError(
                f"Handler '{name}' not found. "
                f"Available handlers: {sorted(self._handlers)}"
            )
        return self._handlers[name]

    def get_handler(self, domain: str) -> SpecHandler:
        """Return handler registered for ``domain``.

        SPEC-041 alias: handler domain == registry name in the dispatch path.
        Raises ``KeyError`` on miss so callers can apply a fallback policy.
        """
        return self.get(domain)

    def resolve(self, spec: dict, config: dict) -> SpecHandler:
        """Resolve the correct handler for a spec.

        Resolution order:
        1. spec["handler"] if present
        2. config["runner"]["domain"] mapped to a registered handler
        3. Fallback to "code"
        """
        # 1. Spec-level override
        handler_name = spec.get("handler")

        # 2. Config domain
        if handler_name is None:
            runner = config.get("runner", {})
            handler_name = runner.get("domain")

        # 3. Fallback
        if handler_name is None:
            handler_name = "code"

        return self.get(handler_name)

    def list_handlers(self) -> List[str]:
        """Return sorted list of registered handler names."""
        return sorted(self._handlers)


# ---------------------------------------------------------------------------
# Custom handler loading
# ---------------------------------------------------------------------------


def load_custom_handlers(registry: HandlerRegistry, config: dict) -> None:
    """Load custom handlers from config.

    Two config shapes are accepted (SPEC-033 + SPEC-041 AC4):

    1. ``handlers: {custom_handlers: [{name, module, class}, ...]}``  (legacy)
    2. ``handlers: [{domain, module, class}, ...]``                    (SPEC-041)

    ``domain`` and ``name`` are aliases for the registry key. Each entry
    must provide a file-path ``module`` and a ``class`` name exported by it.
    """
    handlers_cfg = config.get("handlers")

    # Shape 2 (SPEC-041 AC4): handlers is a flat list of entries.
    if isinstance(handlers_cfg, list):
        custom_list = handlers_cfg
    # Shape 1 (SPEC-033): dict with nested custom_handlers list.
    elif isinstance(handlers_cfg, dict):
        custom_list = handlers_cfg.get("custom_handlers", [])
    else:
        custom_list = []

    for entry in custom_list:
        # ``domain`` and ``name`` are aliases — either is accepted.
        name = entry.get("name") or entry.get("domain")
        if not name:
            raise ValueError(
                "custom handler entry missing 'name'/'domain' key: "
                f"{entry!r}"
            )
        module_path = entry["module"]
        class_name = entry["class"]

        mod_spec = importlib.util.spec_from_file_location(name, module_path)
        if mod_spec is None or mod_spec.loader is None:
            raise ImportError(
                f"Cannot load handler module from '{module_path}'"
            )
        module = importlib.util.module_from_spec(mod_spec)
        mod_spec.loader.exec_module(module)

        handler_cls = getattr(module, class_name)
        registry.register(name, handler_cls())


# ---------------------------------------------------------------------------
# Convenience: create a registry with built-in handlers
# ---------------------------------------------------------------------------


def create_default_registry() -> HandlerRegistry:
    """Create a HandlerRegistry pre-loaded with built-in handlers."""
    registry = HandlerRegistry()
    registry.register("code", CodeHandler())
    registry.register("research", ResearchHandler())
    registry.register("analysis", AnalysisHandler())
    return registry
