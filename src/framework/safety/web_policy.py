"""Domain policy helpers for localhost web-product autonomy."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
import re
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

from src.framework.web_constants import (
    CAP_BROWSER_NAVIGATE,
    CAP_CODE_EDIT,
    CAP_RESTART_SERVICE,
    DEFAULT_LOCALHOST_HOSTS,
    POLICY_ALLOWED_EDIT_PATH_PATTERNS,
    POLICY_ALLOWED_EDIT_SEARCH_PATTERNS,
    POLICY_ALLOWED_LOCALHOST_HOSTS,
    POLICY_ALLOWED_LOCALHOST_PORTS,
    POLICY_MAX_EDITS_PER_CYCLE,
    POLICY_REQUIRE_TESTS_BEFORE_RESTART,
    POLICY_WORKSPACE_ROOT,
)


def _to_int_set(values: Any) -> Optional[set[int]]:
    if values in (None, "", []):
        return None
    if not isinstance(values, (list, tuple, set)):
        return None
    result: set[int] = set()
    for item in values:
        try:
            result.add(int(item))
        except (TypeError, ValueError):
            continue
    return result if result else None


def _allowed_localhost_url(
    url: str,
    allowed_hosts: set[str],
    allowed_ports: Optional[set[int]],
) -> bool:
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    if host not in allowed_hosts:
        return False
    if allowed_ports is None:
        return True
    if parsed.port is None:
        return False
    return int(parsed.port) in allowed_ports


def _path_in_workspace(path: str, workspace_root: Path) -> bool:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    try:
        candidate.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        return False
    return True


def _workspace_relative_path(path: str, workspace_root: Path) -> Optional[str]:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    try:
        rel = candidate.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        return None
    return rel.as_posix()


def _normalize_path_pattern(pattern: str) -> str:
    return str(pattern).strip().replace("\\", "/")


def _matches_path_patterns(path: str, patterns: list[str]) -> bool:
    norm_path = path.replace("\\", "/")
    for pattern in patterns:
        if fnmatch(norm_path, pattern):
            return True
    return False


def build_web_domain_policy_hook(
    config: Dict[str, Any],
    toolset_state_accessor: Optional[Callable[[], Dict[str, Any]]] = None,
) -> Callable[[str, str, Dict[str, Any]], Optional[str]]:
    """Build a domain hook for web-autonomy safety constraints."""

    workspace_root = Path(
        str(config.get(POLICY_WORKSPACE_ROOT, "."))
    ).resolve()
    allowed_hosts = {
        str(host).lower()
        for host in (config.get(POLICY_ALLOWED_LOCALHOST_HOSTS) or list(DEFAULT_LOCALHOST_HOSTS))
    }
    allowed_ports = _to_int_set(config.get(POLICY_ALLOWED_LOCALHOST_PORTS))
    require_tests_before_restart = bool(
        config.get(POLICY_REQUIRE_TESTS_BEFORE_RESTART, True)
    )
    max_edits_per_cycle = int(config.get(POLICY_MAX_EDITS_PER_CYCLE, 0))
    allowed_edit_path_patterns = [
        _normalize_path_pattern(item)
        for item in (config.get(POLICY_ALLOWED_EDIT_PATH_PATTERNS) or [])
        if str(item).strip()
    ]

    allowed_edit_search_patterns = []
    for pattern_text in (config.get(POLICY_ALLOWED_EDIT_SEARCH_PATTERNS) or []):
        text = str(pattern_text).strip()
        if not text:
            continue
        try:
            allowed_edit_search_patterns.append(re.compile(text))
        except re.error:
            continue

    def _state() -> Dict[str, Any]:
        if toolset_state_accessor is None:
            return {}
        try:
            return dict(toolset_state_accessor() or {})
        except Exception:
            return {}

    def hook(
        tool_name: str,
        capability: str,
        arguments: Dict[str, Any],
    ) -> Optional[str]:
        cap = capability or tool_name

        if cap == CAP_BROWSER_NAVIGATE:
            url = arguments.get("url")
            if url and not _allowed_localhost_url(str(url), allowed_hosts, allowed_ports):
                return "Navigation blocked: URL must be localhost/127.0.0.1"

        if cap == CAP_CODE_EDIT:
            path = arguments.get("path")
            if not path:
                return "Code edit blocked: missing path argument"
            if not _path_in_workspace(str(path), workspace_root):
                return "Code edit blocked: path outside workspace"

            relative_path = _workspace_relative_path(str(path), workspace_root)
            if (
                allowed_edit_path_patterns
                and relative_path is not None
                and not _matches_path_patterns(relative_path, allowed_edit_path_patterns)
            ):
                return (
                    "Code edit blocked: path is outside approved edit scopes "
                    f"({relative_path})"
                )

            if allowed_edit_search_patterns:
                search_value = str(arguments.get("search", ""))
                if not search_value:
                    return "Code edit blocked: search argument required by policy"
                if not any(
                    pattern.search(search_value)
                    for pattern in allowed_edit_search_patterns
                ):
                    return "Code edit blocked: search pattern is not approved"

            if max_edits_per_cycle > 0:
                state = _state()
                try:
                    edits_in_cycle = int(state.get("edits_in_cycle", 0))
                except (TypeError, ValueError):
                    edits_in_cycle = 0
                if edits_in_cycle >= max_edits_per_cycle:
                    return (
                        "Code edit blocked: max edits per cycle reached "
                        f"({max_edits_per_cycle})"
                    )

        if cap == CAP_RESTART_SERVICE and require_tests_before_restart:
            state = _state()
            if state.get("latest_test_passed") is not True:
                return "Restart blocked: tests have not passed in current cycle"

        return None

    return hook
