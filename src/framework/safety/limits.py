"""Data models for budget limits and tool risk classification."""

from typing import List

from pydantic import BaseModel, Field


class BudgetLimits(BaseModel):
    """Declarative budget caps consumed by BudgetManager.

    Fields mirror ``RunConfig`` budget fields but add wall-clock and
    step limits as well as a critical-threshold percentage.
    """

    max_tokens: int | None = None
    max_seconds: float | None = None
    max_steps: int | None = None
    max_wall_seconds: float | None = None
    critical_threshold_pct: float = 10.0


class ToolClassification(BaseModel):
    """Risk metadata for a single tool.

    ``side_effect_level`` semantics:
    - 0 = read-only (safe at any autonomy level)
    - 1 = simulation / staging write
    - 2 = real-world write (e.g. send email, deploy)

    ``risk_tags`` are free-form labels for domain-specific filtering.
    """

    tool_name: str
    side_effect_level: int = 0
    risk_tags: List[str] = Field(default_factory=list)
