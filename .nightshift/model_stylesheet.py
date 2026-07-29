"""CSS-like model stylesheet resolution for Nightshift specs."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

RESULT_KEYS = ("model", "harness", "api_base")
VALID_TYPES = {"feature", "bugfix", "refactor", "eval", "skill", "main"}
SELECTOR_RE = re.compile(
    r"^(?P<wildcard>\*)$|^(?P<type>type:(?P<type_value>[^:]+))$|^(?P<layer>layer:(?P<layer_value>-?\d+))$|^(?P<id>#[^\s]+)$"
)


def _empty_result() -> Dict[str, Optional[str]]:
    return {key: None for key in RESULT_KEYS}


def _selector_specificity(selector: str) -> Optional[int]:
    if selector == "*":
        return 0
    if selector.startswith("type:"):
        return 1
    if selector.startswith("layer:"):
        return 2
    if selector.startswith("#"):
        return 3
    return None


def _matches(selector: str, spec_frontmatter: Dict) -> bool:
    if selector == "*":
        return True

    if selector.startswith("type:"):
        return spec_frontmatter.get("type") == selector.split(":", 1)[1]

    if selector.startswith("layer:"):
        layer_value = spec_frontmatter.get("layer")
        if layer_value is None:
            return False
        return str(layer_value) == selector.split(":", 1)[1]

    if selector.startswith("#"):
        return spec_frontmatter.get("id") == selector[1:]

    return False


def resolve_model(spec_frontmatter: Dict, stylesheet: Dict) -> Dict[str, Optional[str]]:
    """
    Resolve model configuration for a spec using CSS-like specificity.

    Higher specificity overrides lower specificity. For rules with the same
    specificity, later definitions win. Missing fields fall through.
    """
    if not stylesheet:
        return _empty_result()

    matched_rules: List[Tuple[int, Dict]] = []
    for selector, value in stylesheet.items():
        specificity = _selector_specificity(selector)
        if specificity is None or not isinstance(value, dict):
            continue
        if _matches(selector, spec_frontmatter):
            matched_rules.append((specificity, value))

    if not matched_rules:
        return _empty_result()

    resolved = _empty_result()
    for _, value in sorted(matched_rules, key=lambda item: item[0]):
        for key in RESULT_KEYS:
            if key in value:
                resolved[key] = value[key]

    return resolved


def validate_stylesheet(stylesheet: Dict) -> List[str]:
    """Return validation errors for a Nightshift model stylesheet."""
    errors: List[str] = []

    if not isinstance(stylesheet, dict):
        return ["stylesheet must be a mapping"]

    for selector, value in stylesheet.items():
        if not isinstance(selector, str) or not SELECTOR_RE.match(selector):
            errors.append(f"invalid selector format: {selector}")
            continue

        if selector.startswith("type:"):
            type_value = selector.split(":", 1)[1]
            if type_value not in VALID_TYPES:
                errors.append(f"invalid type value in selector {selector}: {type_value}")
        elif selector.startswith("layer:"):
            layer_text = selector.split(":", 1)[1]
            try:
                layer_value = int(layer_text)
            except ValueError:
                errors.append(f"invalid layer value in selector {selector}: {layer_text}")
            else:
                if layer_value < 0 or layer_value > 4:
                    errors.append(
                        f"invalid layer value in selector {selector}: {layer_value}"
                    )

        if not isinstance(value, dict):
            errors.append(f"selector {selector} must map to a dict")
            continue

        model = value.get("model")
        if not isinstance(model, str) or model.strip() == "":
            errors.append(f"selector {selector} must define a non-empty model")

    return errors
