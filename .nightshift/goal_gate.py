#!/usr/bin/env python3
"""
Goal gate evaluation and retry routing support for Nightshift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # Optional integration for local canonical usage.
    from loop_events import RunEventLog
except ImportError:  # pragma: no cover - standalone usage
    RunEventLog = Any  # type: ignore[misc,assignment]


ALLOWED_ACTIONS = {"replan", "retry", "skip", "block"}
ALLOWED_VARIABLES: Dict[str, Any] = {
    "tests_pass": False,
    "test_count": 0,
    "test_failures": 0,
    "coverage": 0.0,
    "lint_clean": False,
    "type_check_clean": False,
    "build_clean": False,
    "review_approved": False,
    "duration_s": 0,
}
TOKEN_RE = re.compile(
    r"\s*(>=|<=|==|!=|>|<|\bAND\b|\bOR\b|\bNOT\b|[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
COMPARISON_OPERATORS = {">=", ">", "<=", "<", "==", "!="}
ACTION_PRIORITY = {"skip": 0, "retry": 1, "replan": 2, "block": 3}


@dataclass(frozen=True)
class GoalGate:
    gate_id: str
    condition: str
    on_fail: str
    max_retries: int = 2
    retry_from_step: Optional[int] = None


@dataclass(frozen=True)
class GateResult:
    passed: bool
    gate_id: str
    condition: str
    observed: Dict[str, Any]
    action: Optional[str]
    retries_remaining: int


Token = Tuple[str, str]
AstNode = Tuple[Any, ...]


def _tokenize(condition: str) -> List[Token]:
    tokens: List[Token] = []
    position = 0
    while position < len(condition):
        match = TOKEN_RE.match(condition, position)
        if not match:
            remaining = condition[position:].strip()
            if remaining:
                raise ValueError(f"invalid token near {remaining!r}")
            break
        raw = match.group(1)
        upper = raw.upper()
        token_type = upper if upper in {"AND", "OR", "NOT"} else "ATOM"
        tokens.append((token_type, raw))
        position = match.end()

    if not tokens:
        raise ValueError("condition must not be empty")
    return tokens


class _Parser:
    def __init__(self, condition: str):
        self._condition = condition
        self._tokens = _tokenize(condition)
        self._index = 0

    def parse(self) -> AstNode:
        expression = self._parse_or()
        if self._index != len(self._tokens):
            _, value = self._peek()
            raise ValueError(f"unexpected token {value!r}")
        return expression

    def _parse_or(self) -> AstNode:
        node = self._parse_and()
        while self._match("OR"):
            node = ("or", node, self._parse_and())
        return node

    def _parse_and(self) -> AstNode:
        node = self._parse_not()
        while self._match("AND"):
            node = ("and", node, self._parse_not())
        return node

    def _parse_not(self) -> AstNode:
        if self._match("NOT"):
            return ("not", self._parse_not())
        return self._parse_primary()

    def _parse_primary(self) -> AstNode:
        token_type, value = self._advance()
        if token_type != "ATOM":
            raise ValueError(f"unexpected token {value!r}")

        if value in {"(", ")"}:
            raise ValueError("parentheses are not supported")

        left = self._parse_identifier(value)
        next_token = self._peek()
        if next_token is None or next_token[1] not in COMPARISON_OPERATORS:
            return ("var", left)

        operator = self._advance()[1]
        right_type, right_value = self._advance()
        if right_type != "ATOM":
            raise ValueError(f"expected comparison value, got {right_value!r}")
        return ("cmp", left, operator, self._parse_value(right_value))

    def _parse_identifier(self, value: str) -> str:
        if _is_number(value):
            raise ValueError(f"expected variable name, got {value!r}")
        if value not in ALLOWED_VARIABLES:
            raise ValueError(f"unknown variable {value!r}")
        return value

    def _parse_value(self, value: str) -> Tuple[str, Any]:
        if _is_number(value):
            if "." in value:
                return ("number", float(value))
            return ("number", int(value))
        if value not in ALLOWED_VARIABLES:
            raise ValueError(f"unknown variable {value!r}")
        return ("var", value)

    def _peek(self) -> Optional[Token]:
        if self._index >= len(self._tokens):
            return None
        return self._tokens[self._index]

    def _advance(self) -> Token:
        token = self._peek()
        if token is None:
            raise ValueError("unexpected end of condition")
        self._index += 1
        return token

    def _match(self, token_type: str) -> bool:
        token = self._peek()
        if token is None or token[0] != token_type:
            return False
        self._index += 1
        return True


def _is_number(value: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", value))


def _parse_condition(condition: str) -> AstNode:
    if "(" in condition or ")" in condition:
        raise ValueError("parentheses are not supported")
    return _Parser(condition).parse()


def _resolve_value(name: str, context: Dict[str, Any], observed: Dict[str, Any]) -> Any:
    value = context.get(name, ALLOWED_VARIABLES[name])
    observed[name] = value
    return value


def _eval_ast(node: AstNode, context: Dict[str, Any], observed: Dict[str, Any]) -> bool:
    kind = node[0]
    if kind == "var":
        return bool(_resolve_value(node[1], context, observed))
    if kind == "cmp":
        left = _resolve_value(node[1], context, observed)
        operator = node[2]
        right_spec = node[3]
        if right_spec[0] == "var":
            right = _resolve_value(right_spec[1], context, observed)
        else:
            right = right_spec[1]
        if operator == ">=":
            return left >= right
        if operator == ">":
            return left > right
        if operator == "<=":
            return left <= right
        if operator == "<":
            return left < right
        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
        raise ValueError(f"unsupported operator {operator!r}")
    if kind == "not":
        return not _eval_ast(node[1], context, observed)
    if kind == "and":
        return _eval_ast(node[1], context, observed) and _eval_ast(node[2], context, observed)
    if kind == "or":
        return _eval_ast(node[1], context, observed) or _eval_ast(node[2], context, observed)
    raise ValueError(f"unsupported AST node {kind!r}")


def _build_gate(raw_gate: Dict[str, Any]) -> GoalGate:
    if not isinstance(raw_gate, dict):
        raise ValueError("goal gate entries must be dicts")

    gate_id = raw_gate.get("gate_id")
    condition = raw_gate.get("condition")
    on_fail = raw_gate.get("on_fail")

    if not isinstance(gate_id, str) or not gate_id.strip():
        raise ValueError("goal gate gate_id must be a non-empty string")
    if not isinstance(condition, str) or not condition.strip():
        raise ValueError(f"goal gate {gate_id!r} condition must be a non-empty string")
    if not isinstance(on_fail, str) or on_fail not in ALLOWED_ACTIONS:
        raise ValueError(
            f"goal gate {gate_id!r} on_fail must be one of {sorted(ALLOWED_ACTIONS)}"
        )

    max_retries = raw_gate.get("max_retries", 2)
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        raise ValueError(f"goal gate {gate_id!r} max_retries must be a non-negative int")

    retry_from_step = raw_gate.get("retry_from_step")
    if retry_from_step is not None and (
        isinstance(retry_from_step, bool)
        or not isinstance(retry_from_step, int)
        or retry_from_step < 0
    ):
        raise ValueError(
            f"goal gate {gate_id!r} retry_from_step must be a non-negative int or None"
        )

    error = validate_condition(condition)
    if error is not None:
        raise ValueError(f"goal gate {gate_id!r} has invalid condition: {error}")

    return GoalGate(
        gate_id=gate_id,
        condition=condition,
        on_fail=on_fail,
        max_retries=max_retries,
        retry_from_step=retry_from_step,
    )


def evaluate_gate(gate: GoalGate, context: Dict[str, Any]) -> GateResult:
    observed: Dict[str, Any] = {}
    passed = _eval_ast(_parse_condition(gate.condition), context, observed)
    return GateResult(
        passed=passed,
        gate_id=gate.gate_id,
        condition=gate.condition,
        observed=observed,
        action=None if passed else gate.on_fail,
        retries_remaining=gate.max_retries,
    )


class GateTracker:
    def __init__(self, gates: Sequence[GoalGate], event_log: Optional[RunEventLog] = None):
        self._gates = {gate.gate_id: gate for gate in gates}
        self._order = [gate.gate_id for gate in gates]
        self._event_log = event_log
        self._retries_remaining = {gate.gate_id: gate.max_retries for gate in gates}
        self._latest_results: Dict[str, GateResult] = {}
        self._exhausted: set[str] = set()

    def check(self, gate_id: str, context: Dict[str, Any]) -> GateResult:
        if gate_id not in self._gates:
            raise KeyError(f"unknown gate_id {gate_id!r}")

        gate = self._gates[gate_id]
        base_result = evaluate_gate(gate, context)
        retries_remaining = self._retries_remaining[gate_id]

        if base_result.passed:
            self._exhausted.discard(gate_id)
            result = replace(base_result, retries_remaining=retries_remaining)
        else:
            if retries_remaining > 0:
                retries_remaining -= 1
                self._retries_remaining[gate_id] = retries_remaining
            else:
                self._exhausted.add(gate_id)
            result = replace(base_result, retries_remaining=retries_remaining)

        self._latest_results[gate_id] = result
        self._emit_event(result)
        return result

    def check_all(self, context: Dict[str, Any]) -> List[GateResult]:
        return [self.check(gate_id, context) for gate_id in self._order]

    def is_blocked(self) -> bool:
        return any(
            gate_id in self._exhausted and self._gates[gate_id].on_fail == "block"
            for gate_id in self._order
        )

    def get_action(self) -> Optional[Tuple[str, GoalGate]]:
        blocked_gates = [
            gate_id
            for gate_id in self._order
            if gate_id in self._exhausted and self._gates[gate_id].on_fail == "block"
        ]
        if blocked_gates:
            gate_id = blocked_gates[0]
            return ("block", self._gates[gate_id])

        best: Optional[Tuple[str, GoalGate]] = None
        best_priority = -1
        for gate_id in self._order:
            result = self._latest_results.get(gate_id)
            if result is None or result.passed or result.action is None:
                continue
            priority = ACTION_PRIORITY[result.action]
            if priority > best_priority:
                best_priority = priority
                best = (result.action, self._gates[gate_id])
        return best

    def _emit_event(self, result: GateResult) -> None:
        if self._event_log is None:
            return
        self._event_log.emit(
            "goal_gate_evaluated",
            gate_id=result.gate_id,
            passed=result.passed,
            action=result.action,
            retries_remaining=result.retries_remaining,
        )


def parse_gates(spec_frontmatter: Dict[str, Any], config: Dict[str, Any]) -> List[GoalGate]:
    if "goal_gates" in spec_frontmatter:
        raw_gates = spec_frontmatter.get("goal_gates") or []
    else:
        goal_gate_config = config.get("goal_gates", {})
        if isinstance(goal_gate_config, dict):
            raw_gates = goal_gate_config.get("defaults") or []
        else:
            raw_gates = []

    if not isinstance(raw_gates, list):
        raise ValueError("goal_gates must be a list")
    return [_build_gate(raw_gate) for raw_gate in raw_gates]


def validate_condition(condition: str) -> Optional[str]:
    try:
        _parse_condition(condition)
    except ValueError as exc:
        return str(exc)
    return None
