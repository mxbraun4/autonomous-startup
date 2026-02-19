"""Edit template helpers for bounded web-autonomy code edits."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from src.framework.web_constants import (
    POLICY_ALLOWED_EDIT_PATH_PATTERNS,
    POLICY_ALLOWED_EDIT_SEARCH_PATTERNS,
)


DEFAULT_EDIT_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "readme_run_command_note": {
        "description": "Adjust run-command wording in README.md",
        "path": "README.md",
        "search": "# Unified runner (default mode: crewai)",
        "replace": "# Unified runner (default mode: crewai)",
        "max_replacements": 1,
    },
    "quickstart_run_command_note": {
        "description": "Adjust run-command wording in QUICKSTART.md",
        "path": "QUICKSTART.md",
        "search": "python scripts/run.py",
        "replace": "python scripts/run.py",
        "max_replacements": 1,
    },
}


def _normalize_template_mapping(payload: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Template file must be a JSON object keyed by template name")

    normalized: Dict[str, Dict[str, Any]] = {}
    for name, value in payload.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(value, dict):
            continue
        if "path" not in value or "search" not in value:
            continue
        normalized[name.strip()] = dict(value)
    return normalized


def load_edit_templates(template_file: Optional[str]) -> Dict[str, Dict[str, Any]]:
    """Load optional JSON template definitions from disk."""
    if not template_file:
        return {}
    path = Path(template_file)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_template_mapping(payload)


def get_edit_templates(template_file: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Return merged template registry (built-ins + optional file templates)."""
    templates = dict(DEFAULT_EDIT_TEMPLATES)
    templates.update(load_edit_templates(template_file))
    return templates


def list_edit_templates(template_file: Optional[str] = None) -> List[Dict[str, str]]:
    """Return sorted template metadata for CLI listing."""
    templates = get_edit_templates(template_file)
    rows: List[Dict[str, str]] = []
    for name in sorted(templates):
        row = templates[name]
        rows.append(
            {
                "name": name,
                "description": str(row.get("description", "")),
                "path": str(row.get("path", "")),
            }
        )
    return rows


def resolve_edit_template(
    template_name: str,
    *,
    template_file: Optional[str] = None,
    dry_run: bool = False,
    replace_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve one edit template into instruction + policy overrides."""
    templates = get_edit_templates(template_file)
    if template_name not in templates:
        names = ", ".join(sorted(templates))
        raise ValueError(
            f"Unknown edit template '{template_name}'. Available: {names or '<none>'}"
        )

    template = dict(templates[template_name])
    path = str(template.get("path", "")).strip()
    search = str(template.get("search", ""))
    replace = (
        replace_override
        if replace_override is not None and replace_override != ""
        else str(template.get("replace", ""))
    )
    if not path:
        raise ValueError(f"Template '{template_name}' is missing 'path'")
    if not search:
        raise ValueError(f"Template '{template_name}' is missing 'search'")

    max_replacements = int(template.get("max_replacements", 1))
    create_if_missing = bool(template.get("create_if_missing", False))

    allowed_path_patterns = list(
        template.get(POLICY_ALLOWED_EDIT_PATH_PATTERNS) or [path]
    )
    allowed_search_patterns = list(
        template.get(POLICY_ALLOWED_EDIT_SEARCH_PATTERNS)
        or [f"^{re.escape(search)}$"]
    )

    return {
        "instruction": {
            "path": path,
            "search": search,
            "replace": replace,
            "dry_run": bool(dry_run),
            "max_replacements": max_replacements,
            "create_if_missing": create_if_missing,
        },
        "policy_overrides": {
            POLICY_ALLOWED_EDIT_PATH_PATTERNS: allowed_path_patterns,
            POLICY_ALLOWED_EDIT_SEARCH_PATTERNS: allowed_search_patterns,
        },
        "template_name": template_name,
    }
