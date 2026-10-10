"""Policy layer: classify EVERY tool call before it runs (spec section 6.1).

Fail safe: anything not listed in tools.yaml defaults to write (approval required).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

READ = "read"
WRITE = "write"
DESTRUCTIVE = "destructive"
VALID_CLASSES = {READ, WRITE, DESTRUCTIVE}


@dataclass(frozen=True)
class Classification:
    tool: str
    classification: str
    listed: bool


def load_classes(path: Path | None = None) -> dict[str, str]:
    """Load tools.yaml. Missing file -> empty dict (everything defaults to write)."""
    yaml_path = path or PROJECT_ROOT / "tools.yaml"
    if not yaml_path.exists():
        return {}
    data = yaml.load(yaml_path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader) or {}
    classes: dict[str, str] = {}
    for key, value in data.items():
        normalized = str(value).strip().lower()
        if normalized in VALID_CLASSES:
            classes[str(key).strip()] = normalized
    return classes


def classify(tool: str, classes: dict[str, str]) -> Classification:
    """Classify one tool call. Unlisted tools default to write."""
    if tool in classes:
        return Classification(tool=tool, classification=classes[tool], listed=True)
    return Classification(tool=tool, classification=WRITE, listed=False)


def requires_approval(classification: str) -> bool:
    """Only read-only calls run automatically; everything else waits for approval."""
    return classification != READ


MAX_ARGS_JSON_CHARS = 10_000  # CodeReviewer finding 5: bound edited arguments


def _declares_array(prop: object) -> bool:
    """True when a schema property allows arrays (directly or via anyOf)."""
    if not isinstance(prop, dict):
        return False
    if prop.get("type") == "array" or "items" in prop:
        return True
    return any(
        isinstance(branch, dict) and (branch.get("type") == "array" or "items" in branch)
        for branch in prop.get("anyOf", []) or []
    )


def validate_args(args: object, schema: dict | None) -> list[str]:
    """Basic validation of (possibly user-edited) arguments against a tool schema.

    Returns a list of problems; empty list means valid. Deliberately strict:
    dict with str/int/float/bool/None leaves, bounded size, required keys present.
    M3.8: lists of simple values are allowed when the schema property declares
    an array (Zapier dynamic-enum fields are anyOf[array, null]).
    """
    errors: list[str] = []
    if not isinstance(args, dict):
        return ["Arguments must be a JSON object"]

    encoded = json.dumps(args, ensure_ascii=False)
    if len(encoded) > MAX_ARGS_JSON_CHARS:
        errors.append(f"Arguments too large (max {MAX_ARGS_JSON_CHARS} chars)")

    properties = (schema.get("properties", {}) or {}) if schema else {}
    for key, value in args.items():
        if not isinstance(key, str):
            errors.append(f"Argument key {key!r} must be a string")
        elif isinstance(value, list):
            if not _declares_array(properties.get(key)):
                errors.append(f"Argument '{key}' must be a simple value")
            elif any(
                not isinstance(item, (str, int, float, bool)) or item is None for item in value
            ):
                errors.append(f"Argument '{key}' must contain only simple values")
        elif not isinstance(value, (str, int, float, bool)) and value is not None:
            errors.append(f"Argument '{key}' must be a simple value")

    if schema and isinstance(schema.get("required"), list):
        for required in schema["required"]:
            if required not in args:
                errors.append(f"Missing required argument '{required}'")
        for key, value in args.items():
            expected = (properties.get(key) or {}).get("type")
            if expected == "string" and not isinstance(value, str):
                errors.append(f"Argument '{key}' must be a string")
            elif expected == "number" and not isinstance(value, (int, float)):
                errors.append(f"Argument '{key}' must be a number")

    return errors
