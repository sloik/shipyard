#!/usr/bin/env python3
"""
Dispatch layer — wires the handler registry (SPEC-033) into the LOOP.md
execution path (SPEC-041).

Flow per spec:

    1. Resolve the spec's ``effective_domain`` using the cascade defined in
       LOOP.md § Domain Resolution (spec > stack > config.runner > "code").
    2. Look up the domain in the registry via ``get_handler``.
    3. On miss → fall back to ``CodeHandler`` and emit ``handler_fallback``.
    4. On legacy spec (no ``effective_domain`` anywhere) → default to ``code``
       and emit ``domain_defaulted``.
    5. Always emit ``handler_selected`` before calling ``handler.execute``.
    6. Return the handler's ``Outcome`` unchanged.

Event emission is duck-typed on ``events_logger`` — anything with an
``.emit(event_type, spec_id=?, **fields)`` method (e.g.
``loop_events.RunEventLog``) works. If ``events_logger`` is None, events
are silently dropped (useful for the CLI ``dispatch-spec`` path where the
loop event log may not exist yet).

SPEC-041 — see plans/specs/SPEC-041-wire-handler-registry-into-dispatch.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from handler_registry import (
    CodeHandler,
    HandlerContext,
    HandlerRegistry,
    Outcome,
    SpecHandler,
)


# ---------------------------------------------------------------------------
# Domain resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainResolution:
    """Result of resolving a spec's effective domain."""

    domain: str
    defaulted: bool   # True if no explicit domain anywhere → "code" fallback


def resolve_effective_domain(
    spec: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> DomainResolution:
    """Resolve ``effective_domain`` per LOOP.md cascade.

    Priority: ``spec['effective_domain']`` > ``spec['domain']`` >
    ``config.runner.domain`` > ``"code"`` (with ``defaulted=True``).
    """
    config = config or {}

    explicit = (
        spec.get("effective_domain")
        or spec.get("domain")
        or (config.get("runner") or {}).get("domain")
    )
    if explicit:
        return DomainResolution(domain=str(explicit), defaulted=False)

    return DomainResolution(domain="code", defaulted=True)


# ---------------------------------------------------------------------------
# Handler selection
# ---------------------------------------------------------------------------


def _emit(events_logger: Any, event_type: str, spec_id: Optional[str], **fields: Any) -> None:
    """Best-effort event emission — no-op if logger is None or lacks .emit."""
    if events_logger is None:
        return
    emit = getattr(events_logger, "emit", None)
    if emit is None:
        return
    try:
        emit(event_type, spec_id=spec_id, **fields)
    except Exception:
        # The dispatcher MUST NOT crash the loop over a logging hiccup.
        pass


def select_handler(
    spec: Dict[str, Any],
    registry: HandlerRegistry,
    config: Optional[Dict[str, Any]] = None,
    events_logger: Any = None,
) -> Tuple[SpecHandler, str]:
    """Select the handler for a spec, emitting all dispatch-path events.

    Returns ``(handler, effective_domain)``. Always emits exactly one
    ``handler_selected`` event. May additionally emit ``domain_defaulted``
    (legacy spec) and/or ``handler_fallback`` (unknown domain).
    """
    spec_id = spec.get("id")

    resolution = resolve_effective_domain(spec, config)
    domain = resolution.domain

    # R-AC8: legacy spec with no domain anywhere → log the defaulting.
    if resolution.defaulted:
        _emit(
            events_logger,
            "domain_defaulted",
            spec_id,
            resolved_domain=domain,
        )

    try:
        handler = registry.get_handler(domain)
        selected_domain = domain
    except KeyError:
        # R5 / AC3: unknown domain → fall back to CodeHandler and log.
        handler = _safe_code_handler(registry)
        selected_domain = "code"
        _emit(
            events_logger,
            "handler_fallback",
            spec_id,
            missing_domain=domain,
            fallback_handler="CodeHandler",
        )

    # R6: always emit handler_selected at dispatch time.
    _emit(
        events_logger,
        "handler_selected",
        spec_id,
        effective_domain=selected_domain,
        handler_class_name=type(handler).__name__,
    )

    return handler, selected_domain


def _safe_code_handler(registry: HandlerRegistry) -> SpecHandler:
    """Return the registry's CodeHandler, or a fresh instance as last resort."""
    try:
        return registry.get_handler("code")
    except KeyError:
        # Defensive: an operator-built registry without "code" is extremely
        # unusual, but we still refuse to crash the loop.
        return CodeHandler()


# ---------------------------------------------------------------------------
# Full dispatch
# ---------------------------------------------------------------------------


def dispatch_spec(
    spec: Dict[str, Any],
    registry: HandlerRegistry,
    context: HandlerContext,
    config: Optional[Dict[str, Any]] = None,
) -> Outcome:
    """Select the handler for ``spec`` and invoke its ``execute``.

    This is the function Step 2 of LOOP.md calls after spec selection.
    The returned ``Outcome`` is what the loop persists into per-spec
    metrics YAML.
    """
    handler, _ = select_handler(
        spec=spec,
        registry=registry,
        config=config if config is not None else context.config,
        events_logger=context.events_logger,
    )

    result = handler.execute(spec, context.as_dict())
    if not isinstance(result, Outcome):
        # Defensive contract check — matches test_ac13_execute_returns_outcome.
        raise TypeError(
            f"{type(handler).__name__}.execute() returned "
            f"{type(result).__name__}, expected Outcome"
        )
    return result
