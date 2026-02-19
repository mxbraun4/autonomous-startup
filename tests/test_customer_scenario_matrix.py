"""Tests for deterministic customer simulation scenario matrix."""

import pytest

from src.simulation.customer_environment import (
    run_customer_environment,
    validate_environment_input,
)
from src.simulation.customer_scenario_matrix import (
    SCENARIO_MATRIX_VERSION,
    build_customer_environment_input_for_scenario,
    get_customer_scenario,
    get_customer_scenario_matrix,
    list_customer_scenarios,
)


def test_scenario_matrix_has_expected_variants():
    assert SCENARIO_MATRIX_VERSION == 1
    assert list_customer_scenarios() == [
        "baseline",
        "high_personalization",
        "better_matching",
        "acquisition_push",
    ]


def test_get_customer_scenario_matrix_returns_copy():
    first = get_customer_scenario_matrix()
    first["baseline"]["params"]["founder_base_interest"] = 0.99

    second = get_customer_scenario_matrix()
    assert second["baseline"]["params"]["founder_base_interest"] == 0.15


def test_unknown_scenario_raises():
    with pytest.raises(ValueError, match="Unknown customer scenario"):
        get_customer_scenario("not_a_scenario")


def test_all_scenarios_build_contract_valid_inputs():
    for scenario_name in list_customer_scenarios():
        environment_input = build_customer_environment_input_for_scenario(
            run_id=f"run_{scenario_name}",
            iteration=1,
            scenario_name=scenario_name,
        )
        errors = validate_environment_input(environment_input)
        assert errors == []


def test_scenario_outputs_are_deterministic():
    for scenario_name in list_customer_scenarios():
        environment_input = build_customer_environment_input_for_scenario(
            run_id=f"run_{scenario_name}",
            iteration=1,
            scenario_name=scenario_name,
        )

        first = run_customer_environment(environment_input)
        second = run_customer_environment(environment_input)

        assert first == second
