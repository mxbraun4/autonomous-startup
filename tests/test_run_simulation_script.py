"""Tests for `scripts/run_simulation.py` helpers."""

from pathlib import Path

import pytest

import scripts.run_simulation as run_simulation
from scripts.run_simulation import _percentage_change


def test_percentage_change_with_zero_baseline():
    assert _percentage_change(0.0, 0.25) is None


def test_percentage_change_with_nonzero_baseline():
    assert _percentage_change(0.20, 0.30) == pytest.approx(50.0)


def test_init_memory_store_uses_configured_data_dir(monkeypatch, tmp_path):
    calls = {}

    class DummyUnifiedStore:
        def __init__(self, data_dir: str):
            calls["data_dir"] = data_dir

    class DummySyncStore:
        def __init__(self, store):
            calls["store"] = store

    monkeypatch.setattr("src.utils.config.settings.memory_data_dir", str(tmp_path / "memory"))

    import src.framework.storage.unified_store as unified_store_module
    import src.framework.storage.sync_wrapper as sync_wrapper_module
    import src.crewai_agents.tools as tools_module

    monkeypatch.setattr(unified_store_module, "UnifiedStore", DummyUnifiedStore)
    monkeypatch.setattr(sync_wrapper_module, "SyncUnifiedStore", DummySyncStore)

    injected = {}
    monkeypatch.setattr(tools_module, "set_memory_store", lambda store: injected.setdefault("store", store))

    result = run_simulation._init_memory_store()
    assert Path(calls["data_dir"]) == (tmp_path / "memory").resolve()
    assert injected["store"] is result
