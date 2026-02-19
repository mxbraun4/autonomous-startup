"""Tests for `scripts/run_simulation.py` helpers."""

from pathlib import Path

import pytest

import scripts.run_simulation as run_simulation
from scripts.run_simulation import _percentage_change, _resolve_non_legacy_memory_dir


def test_percentage_change_with_zero_baseline():
    assert _percentage_change(0.0, 0.25) is None


def test_percentage_change_with_nonzero_baseline():
    assert _percentage_change(0.20, 0.30) == pytest.approx(50.0)


def test_resolve_non_legacy_memory_dir_prefers_writable_dir(tmp_path):
    preferred = tmp_path / "memory"
    resolved = _resolve_non_legacy_memory_dir(str(preferred))
    assert Path(resolved) == preferred.resolve()


def test_resolve_non_legacy_memory_dir_uses_runtime_fallback(monkeypatch, tmp_path):
    preferred = tmp_path / "memory"
    preferred_resolved = preferred.resolve()
    fallback_resolved = (preferred_resolved.parent / f"{preferred_resolved.name}_runtime").resolve()

    def fake_is_writable_directory(path: Path) -> bool:
        resolved = Path(path).resolve()
        return resolved in {
            fallback_resolved,
            (fallback_resolved / "chroma").resolve(),
        }

    monkeypatch.setattr(
        run_simulation,
        "_is_writable_directory",
        fake_is_writable_directory,
    )

    resolved = _resolve_non_legacy_memory_dir(str(preferred))
    assert Path(resolved) == fallback_resolved


def test_resolve_non_legacy_memory_dir_raises_when_all_candidates_unwritable(monkeypatch):
    monkeypatch.setattr(
        run_simulation,
        "_is_writable_directory",
        lambda _path: False,
    )

    with pytest.raises(RuntimeError, match="No writable non-legacy memory directory available"):
        _resolve_non_legacy_memory_dir("data/memory")


def test_init_memory_store_rejects_legacy_mode(monkeypatch):
    monkeypatch.setattr(run_simulation.settings, "memory_use_legacy", True)
    with pytest.raises(RuntimeError, match="Legacy memory mode is disabled"):
        run_simulation._init_memory_store()
