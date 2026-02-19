"""Shared constants for localhost web-product autonomy."""

from __future__ import annotations

# Capabilities
CAP_BROWSER_NAVIGATE = "browser_navigate"
CAP_CODE_EDIT = "code_edit"
CAP_RUN_TESTS = "run_tests"
CAP_RESTART_SERVICE = "restart_service"

WEB_CAPABILITIES = (
    CAP_BROWSER_NAVIGATE,
    CAP_CODE_EDIT,
    CAP_RUN_TESTS,
    CAP_RESTART_SERVICE,
)

# Agent roles/ids
ROLE_WEB_EXPLORER = "web_explorer"
ROLE_WEB_IMPROVER = "web_improver"
ROLE_WEB_VALIDATOR = "web_validator"

# Policy keys
POLICY_ALLOWLIST = "allowlist"
POLICY_WORKSPACE_ROOT = "workspace_root"
POLICY_ALLOWED_LOCALHOST_HOSTS = "allowed_localhost_hosts"
POLICY_ALLOWED_LOCALHOST_PORTS = "allowed_localhost_ports"
POLICY_MAX_EDITS_PER_CYCLE = "max_edits_per_cycle"
POLICY_REQUIRE_TESTS_BEFORE_RESTART = "require_tests_before_restart"
POLICY_ALLOWED_EDIT_PATH_PATTERNS = "allowed_edit_path_patterns"
POLICY_ALLOWED_EDIT_SEARCH_PATTERNS = "allowed_edit_search_patterns"

POLICY_MAX_CHILDREN_PER_PARENT = "max_children_per_parent"
POLICY_MAX_TOTAL_DELEGATED_TASKS = "max_total_delegated_tasks"
POLICY_DEDUPE_DELEGATED_OBJECTIVES = "dedupe_delegated_objectives"
POLICY_LOOP_WINDOW_SIZE = "loop_window_size"
POLICY_MAX_IDENTICAL_TOOL_CALLS = "max_identical_tool_calls"
POLICY_TOOL_LOOP_WINDOW = "tool_loop_window"
POLICY_TOOL_LOOP_MAX_REPEATS = "tool_loop_max_repeats"

# Defaults
DEFAULT_LOCALHOST_HOSTS = ("localhost", "127.0.0.1", "::1")
DEFAULT_MAX_EDITS_PER_CYCLE = 2
