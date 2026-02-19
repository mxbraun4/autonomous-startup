"""Tests for web edit template helpers."""

from __future__ import annotations

import json
import pytest

from src.framework.runtime.web_edit_templates import (
    get_edit_templates,
    list_edit_templates,
    resolve_edit_template,
)


def test_list_edit_templates_includes_builtins():
    names = {row["name"] for row in list_edit_templates()}
    assert "readme_run_command_note" in names
    assert "quickstart_run_command_note" in names


def test_resolve_edit_template_returns_instruction_and_policy():
    resolved = resolve_edit_template(
        "readme_run_command_note",
        dry_run=True,
        replace_override="replacement",
    )

    instruction = resolved["instruction"]
    policies = resolved["policy_overrides"]

    assert instruction["path"] == "README.md"
    assert instruction["search"] == "# Unified runner (default mode: crewai)"
    assert instruction["replace"] == "replacement"
    assert instruction["dry_run"] is True
    assert policies["allowed_edit_path_patterns"] == ["README.md"]
    assert policies["allowed_edit_search_patterns"] == [
        r"^\#\ Unified\ runner\ \(default\ mode:\ crewai\)$"
    ]


def test_get_edit_templates_merges_file_templates(tmp_path):
    template_file = tmp_path / "web_templates.json"
    template_file.write_text(
        json.dumps(
            {
                "custom_edit": {
                    "description": "Custom edit",
                    "path": "src/app.txt",
                    "search": "before",
                    "replace": "after",
                }
            }
        ),
        encoding="utf-8",
    )

    templates = get_edit_templates(str(template_file))
    assert "custom_edit" in templates
    assert templates["custom_edit"]["path"] == "src/app.txt"


def test_resolve_edit_template_raises_for_unknown_template():
    with pytest.raises(ValueError):
        resolve_edit_template("does_not_exist")
