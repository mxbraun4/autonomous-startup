"""Tests for shared web-autonomy constants."""

from src.framework.web_constants import (
    CAP_BROWSER_NAVIGATE,
    CAP_CODE_EDIT,
    CAP_RESTART_SERVICE,
    CAP_RUN_TESTS,
    POLICY_ALLOWED_EDIT_PATH_PATTERNS,
    POLICY_ALLOWED_EDIT_SEARCH_PATTERNS,
    WEB_CAPABILITIES,
)


def test_web_capability_constants_are_stable():
    assert CAP_BROWSER_NAVIGATE == "browser_navigate"
    assert CAP_CODE_EDIT == "code_edit"
    assert CAP_RUN_TESTS == "run_tests"
    assert CAP_RESTART_SERVICE == "restart_service"
    assert WEB_CAPABILITIES == (
        "browser_navigate",
        "code_edit",
        "run_tests",
        "restart_service",
    )
    assert POLICY_ALLOWED_EDIT_PATH_PATTERNS == "allowed_edit_path_patterns"
    assert POLICY_ALLOWED_EDIT_SEARCH_PATTERNS == "allowed_edit_search_patterns"
