"""Domain adapter protocol for framework-domain isolation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from src.framework.contracts import EvaluationResult, TaskSpec


class BaseDomainAdapter(ABC):
    """Adapter interface consumed by core autonomy/runtime layers."""

    @abstractmethod
    def build_cycle_tasks(self, run_context: Any) -> List[TaskSpec]:
        """Build task specs for one cycle."""

    @abstractmethod
    def simulate_environment(
        self,
        cycle_outputs: Any,
        run_context: Any,
    ) -> Dict[str, Any]:
        """Simulate environment outcomes from cycle outputs."""

    @abstractmethod
    def compute_domain_metrics(self, simulation_outputs: Dict[str, Any]) -> Dict[str, Any]:
        """Compute domain-specific metrics for evaluation."""

    @abstractmethod
    def suggest_procedure_updates(
        self,
        evaluation_result: EvaluationResult,
    ) -> List[Any]:
        """Return procedure update proposals derived from evaluation."""

    @abstractmethod
    def get_domain_policies(self) -> Dict[str, Any]:
        """Return domain-default policies to merge into run config."""

