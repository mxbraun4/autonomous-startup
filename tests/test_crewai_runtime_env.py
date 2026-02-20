"""Tests for CrewAI runtime path patching in constrained environments."""

from src.crewai_agents.runtime_env import crewai_db_storage_path, patch_crewai_storage_paths


def test_patch_crewai_storage_paths_updates_bound_modules():
    expected = crewai_db_storage_path()
    patched = patch_crewai_storage_paths()

    from crewai.utilities import paths as crewai_paths
    from crewai.memory.storage import kickoff_task_outputs_storage as kickoff_storage

    assert patched == expected
    assert crewai_paths.db_storage_path() == expected
    assert kickoff_storage.db_storage_path() == expected
