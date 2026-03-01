"""Tests for MEASURE phase metrics (outreach removed — always no_signal)."""

from src.crewai_agents import crews


def test_collect_measure_metrics_returns_no_signal():
    """With outreach removed, metrics always return a no-signal baseline."""

    result = crews._collect_measure_metrics(1, build_result_text="anything")

    assert result["measurement_source"] == "no_signal"
    assert result["total_sent"] == 0
    assert result["responses"] == 0
    assert result["meetings"] == 0
    assert result["response_rate"] == 0.0
    assert result["meeting_rate"] == 0.0
