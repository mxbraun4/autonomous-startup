"""Deterministic local mock LLM for offline CrewAI simulation."""

from __future__ import annotations

from typing import Any

from crewai.llms.base_llm import BaseLLM


class DeterministicMockLLM(BaseLLM):
    """A tiny deterministic LLM implementation for mock-mode runs.

    This prevents network calls in constrained environments while still
    returning valid ReAct-style outputs that CrewAI can parse.
    """

    def __init__(self, model: str = "mock/deterministic") -> None:
        super().__init__(model=model, temperature=0.0, provider="mock")

    def call(
        self,
        messages: str | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        callbacks: list[Any] | None = None,
        available_functions: dict[str, Any] | None = None,
        from_task: Any | None = None,
        from_agent: Any | None = None,
        response_model: Any | None = None,
    ) -> str:
        del tools, callbacks, available_functions, from_task, from_agent, response_model

        # Keep content deterministic and parseable by CrewAI parser.
        return (
            "Thought: I can provide a deterministic mock-mode result.\n"
            "Final Answer: Mock-mode execution completed with placeholder analysis "
            "that is deterministic and network-free."
        )

    def get_context_window_size(self) -> int:
        return 8192
