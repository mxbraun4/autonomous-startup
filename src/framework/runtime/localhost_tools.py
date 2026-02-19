"""Localhost-first toolset for autonomous web-product iteration."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Set
from urllib.parse import urlparse
from urllib.request import urlopen

from src.framework.web_constants import DEFAULT_LOCALHOST_HOSTS, DEFAULT_MAX_EDITS_PER_CYCLE


def _truncate(text: str, max_chars: int = 4000) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _strip_html_excerpt(html: str, max_chars: int = 400) -> str:
    stripped = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    stripped = re.sub(r"(?is)<style.*?>.*?</style>", " ", stripped)
    stripped = re.sub(r"(?is)<[^>]+>", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return _truncate(stripped, max_chars=max_chars)


def _extract_title(html: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


class LocalhostAutonomyToolset:
    """Tool implementations for local web iteration loops."""

    def __init__(
        self,
        *,
        workspace_root: str,
        target_url: str = "http://localhost:3000",
        test_command: str = "pytest -q",
        restart_command: str = "",
        max_edits_per_cycle: int = DEFAULT_MAX_EDITS_PER_CYCLE,
        allowed_hosts: Optional[set[str]] = None,
        allowed_ports: Optional[set[int]] = None,
    ) -> None:
        self._workspace_root = Path(workspace_root).resolve()
        self._workspace_root.mkdir(parents=True, exist_ok=True)

        self._target_url = target_url
        self._test_command = test_command
        self._restart_command = restart_command
        self._max_edits_per_cycle = max(1, int(max_edits_per_cycle))

        self._allowed_hosts: Set[str] = set(
            allowed_hosts or set(DEFAULT_LOCALHOST_HOSTS)
        )
        self._allowed_ports: Optional[Set[int]] = (
            {int(p) for p in allowed_ports} if allowed_ports else None
        )

        self._current_cycle_id: Optional[int] = None
        self._edits_in_cycle: int = 0
        self._latest_test_passed: Optional[bool] = None
        self._latest_test_exit_code: Optional[int] = None
        self._latest_test_output: str = ""

    @property
    def workspace_root(self) -> str:
        return str(self._workspace_root)

    @property
    def max_edits_per_cycle(self) -> int:
        return self._max_edits_per_cycle

    def reset_cycle_state(self, cycle_id: int) -> None:
        self._current_cycle_id = int(cycle_id)
        self._edits_in_cycle = 0
        self._latest_test_passed = None
        self._latest_test_exit_code = None
        self._latest_test_output = ""

    def get_state(self) -> Dict[str, Any]:
        return {
            "cycle_id": self._current_cycle_id,
            "edits_in_cycle": self._edits_in_cycle,
            "max_edits_per_cycle": self._max_edits_per_cycle,
            "latest_test_passed": self._latest_test_passed,
            "latest_test_exit_code": self._latest_test_exit_code,
            "latest_test_output": self._latest_test_output,
            "workspace_root": str(self._workspace_root),
        }

    def browser_navigate(
        self,
        *,
        url: Optional[str] = None,
        selector: Optional[str] = None,
        wait_ms: int = 0,
        cycle_id: Optional[int] = None,
        timeout_seconds: int = 15,
    ) -> Dict[str, Any]:
        self._sync_cycle(cycle_id)

        target = _safe_text(url) or self._target_url
        allowed, reason = self._is_allowed_local_url(target)
        if not allowed:
            return {
                "status": "denied",
                "reason": reason,
                "url": target,
            }

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(target, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
                if selector:
                    page.wait_for_selector(selector, timeout=timeout_seconds * 1000)
                elif wait_ms > 0:
                    page.wait_for_timeout(wait_ms)
                content = page.content()
                title = page.title()
                final_url = page.url
                browser.close()
            return {
                "status": "success",
                "url": final_url,
                "title": title,
                "content_excerpt": _strip_html_excerpt(content),
                "used_playwright": True,
            }
        except Exception:
            pass

        try:
            with urlopen(target, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8", errors="replace")
            return {
                "status": "success",
                "url": target,
                "title": _extract_title(body),
                "content_excerpt": _strip_html_excerpt(body),
                "used_playwright": False,
            }
        except Exception as exc:
            return {
                "status": "error",
                "reason": "navigation_failed",
                "error": str(exc),
                "url": target,
            }

    def code_edit(
        self,
        *,
        path: str,
        search: str = "",
        replace: str = "",
        max_replacements: int = 1,
        create_if_missing: bool = False,
        dry_run: bool = False,
        cycle_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._sync_cycle(cycle_id)

        if self._edits_in_cycle >= self._max_edits_per_cycle:
            return {
                "status": "denied",
                "reason": "edit_limit_exceeded",
                "edits_in_cycle": self._edits_in_cycle,
                "max_edits_per_cycle": self._max_edits_per_cycle,
            }

        try:
            target_path = self._resolve_workspace_path(path)
        except ValueError as exc:
            return {
                "status": "denied",
                "reason": "path_outside_workspace",
                "error": str(exc),
            }

        if not target_path.exists():
            if not create_if_missing:
                return {
                    "status": "error",
                    "reason": "file_not_found",
                    "path": str(target_path),
                }
            target_path.parent.mkdir(parents=True, exist_ok=True)
            original = ""
        else:
            original = target_path.read_text(encoding="utf-8")

        if search:
            replacements = max(1, int(max_replacements))
            updated = original.replace(search, replace, replacements)
            replaced_count = min(original.count(search), replacements)
        else:
            updated = original + replace
            replaced_count = 1 if replace else 0

        if updated == original:
            return {
                "status": "no_change",
                "path": str(target_path),
                "replacements": 0,
            }

        if not dry_run:
            target_path.write_text(updated, encoding="utf-8")
            self._edits_in_cycle += 1
            self._latest_test_passed = None
            self._latest_test_exit_code = None

        return {
            "status": "success",
            "path": str(target_path),
            "replacements": replaced_count,
            "dry_run": dry_run,
            "edits_in_cycle": self._edits_in_cycle,
        }

    def run_tests(
        self,
        *,
        command: Optional[str] = None,
        timeout_seconds: int = 120,
        workdir: Optional[str] = None,
        cycle_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._sync_cycle(cycle_id)

        test_command = _safe_text(command) or self._test_command
        run_dir = Path(workdir).resolve() if workdir else self._workspace_root
        if not test_command:
            return {
                "status": "error",
                "reason": "missing_test_command",
            }

        try:
            completed = subprocess.run(
                test_command,
                shell=True,
                cwd=str(run_dir),
                capture_output=True,
                text=True,
                timeout=max(1, int(timeout_seconds)),
            )
            output = (completed.stdout or "") + (completed.stderr or "")
            passed = completed.returncode == 0
            self._latest_test_passed = passed
            self._latest_test_exit_code = int(completed.returncode)
            self._latest_test_output = _truncate(output)
            return {
                "status": "success" if passed else "failed",
                "tests_passed": passed,
                "exit_code": int(completed.returncode),
                "command": test_command,
                "output": self._latest_test_output,
                "workdir": str(run_dir),
            }
        except subprocess.TimeoutExpired as exc:
            output = ((exc.stdout or "") + (exc.stderr or "")).strip()
            self._latest_test_passed = False
            self._latest_test_exit_code = None
            self._latest_test_output = _truncate(output)
            return {
                "status": "failed",
                "tests_passed": False,
                "reason": "timeout",
                "command": test_command,
                "output": self._latest_test_output,
                "workdir": str(run_dir),
            }

    def restart_service(
        self,
        *,
        command: Optional[str] = None,
        timeout_seconds: int = 60,
        workdir: Optional[str] = None,
        require_tests_passed: bool = True,
        cycle_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._sync_cycle(cycle_id)

        if require_tests_passed and self._latest_test_passed is not True:
            return {
                "status": "denied",
                "reason": "tests_not_passed_in_cycle",
            }

        restart_command = _safe_text(command) or self._restart_command
        run_dir = Path(workdir).resolve() if workdir else self._workspace_root

        if not restart_command:
            return {
                "status": "skipped",
                "reason": "no_restart_command",
                "workdir": str(run_dir),
            }

        try:
            completed = subprocess.run(
                restart_command,
                shell=True,
                cwd=str(run_dir),
                capture_output=True,
                text=True,
                timeout=max(1, int(timeout_seconds)),
            )
            output = (completed.stdout or "") + (completed.stderr or "")
            return {
                "status": "success" if completed.returncode == 0 else "failed",
                "exit_code": int(completed.returncode),
                "command": restart_command,
                "output": _truncate(output),
                "workdir": str(run_dir),
            }
        except subprocess.TimeoutExpired as exc:
            output = ((exc.stdout or "") + (exc.stderr or "")).strip()
            return {
                "status": "failed",
                "reason": "timeout",
                "command": restart_command,
                "output": _truncate(output),
                "workdir": str(run_dir),
            }

    def _sync_cycle(self, cycle_id: Optional[int]) -> None:
        if cycle_id is None:
            return
        if self._current_cycle_id != int(cycle_id):
            self.reset_cycle_state(int(cycle_id))

    def _resolve_workspace_path(self, path: str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self._workspace_root / candidate
        resolved = candidate.resolve()

        try:
            resolved.relative_to(self._workspace_root)
        except ValueError as exc:
            raise ValueError(
                f"Path {resolved} is outside workspace {self._workspace_root}"
            ) from exc
        return resolved

    def _is_allowed_local_url(self, url: str) -> tuple[bool, str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False, "unsupported_scheme"
        host = (parsed.hostname or "").lower()
        if host not in self._allowed_hosts:
            return False, "non_localhost_url"
        if self._allowed_ports is not None:
            if parsed.port is None or int(parsed.port) not in self._allowed_ports:
                return False, "port_not_allowed"
        return True, "ok"
