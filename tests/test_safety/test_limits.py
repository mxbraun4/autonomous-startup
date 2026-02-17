"""Tests for BudgetLimits and ToolClassification data models."""

from src.framework.safety.limits import BudgetLimits, ToolClassification


class TestBudgetLimits:
    def test_defaults(self):
        bl = BudgetLimits()
        assert bl.max_tokens is None
        assert bl.max_seconds is None
        assert bl.max_steps is None
        assert bl.max_wall_seconds is None
        assert bl.critical_threshold_pct == 10.0

    def test_custom_values(self):
        bl = BudgetLimits(
            max_tokens=5000,
            max_seconds=120.0,
            max_steps=50,
            max_wall_seconds=300.0,
            critical_threshold_pct=5.0,
        )
        assert bl.max_tokens == 5000
        assert bl.max_seconds == 120.0
        assert bl.max_steps == 50
        assert bl.max_wall_seconds == 300.0
        assert bl.critical_threshold_pct == 5.0


class TestToolClassification:
    def test_defaults(self):
        tc = ToolClassification(tool_name="read_file")
        assert tc.tool_name == "read_file"
        assert tc.side_effect_level == 0
        assert tc.risk_tags == []

    def test_risk_tags(self):
        tc = ToolClassification(
            tool_name="send_email",
            side_effect_level=2,
            risk_tags=["external", "pii"],
        )
        assert tc.tool_name == "send_email"
        assert tc.side_effect_level == 2
        assert tc.risk_tags == ["external", "pii"]
