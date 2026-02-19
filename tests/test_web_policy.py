"""Tests for web-domain policy hooks."""

from __future__ import annotations

from pathlib import Path

from src.framework.safety.web_policy import build_web_domain_policy_hook


def test_web_policy_blocks_non_localhost_navigation(tmp_path):
    state = {"edits_in_cycle": 0, "latest_test_passed": False}
    hook = build_web_domain_policy_hook(
        {
            "workspace_root": str(tmp_path),
            "allowed_localhost_hosts": ["localhost", "127.0.0.1"],
        },
        toolset_state_accessor=lambda: state,
    )

    denied = hook("browser_navigate", "browser_navigate", {"url": "https://example.com"})
    allowed = hook("browser_navigate", "browser_navigate", {"url": "http://127.0.0.1:3000"})

    assert denied is not None
    assert "localhost" in denied.lower()
    assert allowed is None


def test_web_policy_enforces_workspace_paths_and_edit_caps(tmp_path):
    inside = tmp_path / "inside.txt"
    outside = tmp_path.parent / "outside.txt"
    inside.write_text("x", encoding="utf-8")
    outside.write_text("y", encoding="utf-8")

    state = {"edits_in_cycle": 0, "latest_test_passed": False}
    hook = build_web_domain_policy_hook(
        {
            "workspace_root": str(tmp_path),
            "max_edits_per_cycle": 1,
        },
        toolset_state_accessor=lambda: state,
    )

    denied_outside = hook("code_edit", "code_edit", {"path": str(outside)})
    assert denied_outside is not None
    assert "outside workspace" in denied_outside.lower()

    allowed_inside = hook("code_edit", "code_edit", {"path": str(inside)})
    assert allowed_inside is None

    state["edits_in_cycle"] = 1
    denied_limit = hook("code_edit", "code_edit", {"path": str(inside)})
    assert denied_limit is not None
    assert "max edits per cycle" in denied_limit.lower()


def test_web_policy_requires_passing_tests_before_restart(tmp_path):
    state = {"edits_in_cycle": 0, "latest_test_passed": False}
    hook = build_web_domain_policy_hook(
        {
            "workspace_root": str(tmp_path),
            "require_tests_before_restart": True,
        },
        toolset_state_accessor=lambda: state,
    )

    denied = hook("restart_service", "restart_service", {})
    assert denied is not None
    assert "tests have not passed" in denied.lower()

    state["latest_test_passed"] = True
    allowed = hook("restart_service", "restart_service", {})
    assert allowed is None


def test_web_policy_enforces_approved_edit_paths_and_search_patterns(tmp_path):
    allowed_dir = tmp_path / "web"
    allowed_dir.mkdir()
    allowed_file = allowed_dir / "page.txt"
    denied_file = tmp_path / "other.txt"
    allowed_file.write_text("title", encoding="utf-8")
    denied_file.write_text("x", encoding="utf-8")

    hook = build_web_domain_policy_hook(
        {
            "workspace_root": str(tmp_path),
            "allowed_edit_path_patterns": ["web/*.txt"],
            "allowed_edit_search_patterns": [r"^title$"],
        },
        toolset_state_accessor=lambda: {"edits_in_cycle": 0, "latest_test_passed": True},
    )

    allowed = hook(
        "code_edit",
        "code_edit",
        {"path": str(allowed_file), "search": "title"},
    )
    assert allowed is None

    denied_scope = hook(
        "code_edit",
        "code_edit",
        {"path": str(denied_file), "search": "title"},
    )
    assert denied_scope is not None
    assert "approved edit scopes" in denied_scope.lower()

    denied_search = hook(
        "code_edit",
        "code_edit",
        {"path": str(allowed_file), "search": "headline"},
    )
    assert denied_search is not None
    assert "search pattern" in denied_search.lower()
