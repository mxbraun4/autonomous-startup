"""Tests for non-synthetic MEASURE phase metrics."""

from src.crewai_agents import crews


def test_collect_measure_metrics_prefers_outreach_logs(monkeypatch):
    """When outreach records exist, metrics are computed from logged statuses."""

    class FakeDB:
        def get_outreach_history(self, campaign_id=None, limit=500):
            assert campaign_id == "iteration_2"
            assert limit == 500
            return [
                {"status": "sent"},
                {"status": "responded"},
                {"status": "interested"},
                {"status": "meeting_scheduled"},
            ]

    monkeypatch.setattr("src.crewai_agents.tools.get_database", lambda: FakeDB())

    result = crews._collect_measure_metrics(2, build_result_text="ignored")

    assert result["measurement_source"] == "outreach_logs"
    assert result["campaign_id"] == "iteration_2"
    assert result["total_sent"] == 4
    assert result["responses"] == 3
    assert result["meetings"] == 1
    assert result["response_rate"] == 0.75
    assert result["meeting_rate"] == 0.25


def test_collect_measure_metrics_returns_no_signal_when_no_logs(monkeypatch):
    """When no logs exist, return zero metrics with 'no_signal' source.

    Agent-predicted rates in build output text are NOT used as measurements
    because that would be self-referential (predictions != measurements).
    """

    class FakeDB:
        def get_outreach_history(self, campaign_id=None, limit=500):
            return []

    monkeypatch.setattr("src.crewai_agents.tools.get_database", lambda: FakeDB())

    build_output = """
    Campaign quality metrics:
    Predicted response rate: 35%
    Predicted meeting rate: 12%
    """
    result = crews._collect_measure_metrics(1, build_result_text=build_output)

    assert result["measurement_source"] == "no_signal"
    assert result["campaign_id"] == "iteration_1"
    assert result["total_sent"] == 0
    assert result["responses"] == 0
    assert result["meetings"] == 0
    assert result["response_rate"] == 0.0
    assert result["meeting_rate"] == 0.0


def test_collect_measure_metrics_handles_no_signal(monkeypatch):
    """No logs and no parseable rates should return zero metrics."""

    class FakeDB:
        def get_outreach_history(self, campaign_id=None, limit=500):
            return []

    monkeypatch.setattr("src.crewai_agents.tools.get_database", lambda: FakeDB())

    result = crews._collect_measure_metrics(
        3,
        build_result_text="Mock-mode execution completed with placeholder analysis.",
    )

    assert result["measurement_source"] == "no_signal"
    assert result["campaign_id"] == "iteration_3"
    assert result["response_rate"] == 0.0
    assert result["meeting_rate"] == 0.0
    assert result["total_sent"] == 0
    assert result["responses"] == 0
    assert result["meetings"] == 0
