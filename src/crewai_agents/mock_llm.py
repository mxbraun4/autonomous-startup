"""Deterministic local mock LLM for offline CrewAI simulation."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from crewai.llms.base_llm import BaseLLM


# Regex that matches a Pydantic model schema block embedded in a converter
# prompt, e.g.  '{"properties": {"predicted_improvement": {"type": "number"}, ...}}'
_SCHEMA_RE = re.compile(r'"properties"\s*:\s*\{([^}]+)\}', re.DOTALL)
_FIELD_RE = re.compile(r'"(\w+)"\s*:\s*\{[^}]*"type"\s*:\s*"(\w+)"')


class DeterministicMockLLM(BaseLLM):
    """A tiny deterministic LLM implementation for mock-mode runs.

    This prevents network calls in constrained environments while still
    returning valid ReAct-style outputs that CrewAI can parse.

    When CrewAI's converter re-prompts for structured output the mock
    detects the JSON-schema hint in the prompt and returns a conforming
    JSON blob so that ``output_pydantic`` tasks work correctly.
    """

    def __init__(self, model: str = "mock/deterministic") -> None:
        super().__init__(model=model, temperature=0.0, provider="mock")

    # ------------------------------------------------------------------
    # CrewAI v1.9 converter compat
    # ------------------------------------------------------------------

    def supports_function_calling(self) -> bool:  # noqa: D401
        """The mock LLM does not support native function-calling."""
        return False

    # ------------------------------------------------------------------

    @staticmethod
    def _default_for_json_type(json_type: str) -> Any:
        """Return a sensible default for a JSON Schema type string."""
        return {
            "string": "mock_value",
            "number": 0.0,
            "integer": 0,
            "boolean": True,
            "array": [],
            "object": {},
        }.get(json_type, "mock_value")

    @staticmethod
    def _default_for_field(field_info: Any) -> Any:
        """Return a sensible mock default for a Pydantic FieldInfo."""
        annotation = field_info.annotation
        origin = getattr(annotation, "__origin__", None)

        if annotation is str:
            return "mock_value"
        if annotation is int:
            return 0
        if annotation is float:
            return 0.0
        if annotation is bool:
            return True
        if origin is list:
            return []
        if origin is dict:
            return {}
        return "mock_value"

    def _build_structured_response(self, response_model: Any) -> str:
        """Build a JSON string that satisfies *response_model* (Pydantic).

        Iterates over model fields and populates them with realistic mock
        data so that downstream phases (LEARN, EVALUATE) receive non-empty
        inputs.  Works generically for any Pydantic model.
        """
        overrides: dict[str, Any] = {}
        for name, field_info in response_model.model_fields.items():
            annotation = field_info.annotation
            origin = getattr(annotation, "__origin__", None)
            args = getattr(annotation, "__args__", ())

            if origin is list and args and args[0] is str:
                overrides[name] = [
                    f"Mock {name} 1: deterministic placeholder insight",
                    f"Mock {name} 2: systematic improvement signal",
                ]
            elif origin is dict and args and args == (str, str):
                overrides[name] = {
                    "developer": f"Mock {name}: focus on incremental improvements",
                    "product": f"Mock {name}: prioritize user-facing value",
                }
            elif annotation is float:
                overrides[name] = 0.15
            elif annotation is str:
                overrides[name] = f"mock_{name}: deterministic placeholder"

        instance = response_model(**overrides)
        return instance.model_dump_json()

    @staticmethod
    def _try_build_json_from_prompt(text: str) -> str | None:
        """If the prompt contains a JSON schema, build a matching object."""
        if "properties" not in text:
            return None
        schema_match = _SCHEMA_RE.search(text)
        if not schema_match:
            return None
        fields_block = schema_match.group(0)
        fields = _FIELD_RE.findall(fields_block)
        if not fields:
            return None
        payload: dict[str, Any] = {}
        for name, json_type in fields:
            payload[name] = DeterministicMockLLM._default_for_json_type(json_type)
        return json.dumps(payload)

    # ------------------------------------------------------------------

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
        del tools, callbacks, available_functions, from_task

        agent_name = getattr(from_agent, "role", "") if from_agent else ""
        t0 = time.monotonic()

        # Structured-output path: return valid JSON for the Pydantic model.
        if response_model is not None:
            response = self._build_structured_response(response_model)
        else:
            # If the prompt looks like a converter re-prompt with an embedded
            # schema, return conforming JSON so output_pydantic parsing succeeds.
            prompt_text = messages if isinstance(messages, str) else json.dumps(messages)
            schema_json = self._try_build_json_from_prompt(prompt_text)
            if schema_json is not None:
                response = schema_json
            else:
                # Keep content deterministic and parseable by CrewAI parser.
                response = (
                    "Thought: I can provide a deterministic mock-mode result.\n"
                    "Final Answer: Mock-mode execution completed with placeholder analysis "
                    "that is deterministic and network-free."
                )

        duration_ms = round((time.monotonic() - t0) * 1000, 1)

        # Emit llm_call event
        try:
            from src.crewai_agents.tools import get_event_logger

            el = get_event_logger()
            if el is not None:
                if isinstance(messages, list) and messages:
                    last_msg = str(messages[-1].get("content", ""))
                elif isinstance(messages, str):
                    last_msg = messages
                else:
                    last_msg = ""
                msg_summary = last_msg[:200] + "..." if len(last_msg) > 200 else last_msg
                resp_summary = response[:200] + "..." if len(response) > 200 else response
                el.emit("llm_call", {
                    "agent": agent_name,
                    "model": self.model,
                    "message_summary": msg_summary,
                    "response_summary": resp_summary,
                    "duration_ms": duration_ms,
                })
        except Exception:
            pass

        return response

    def get_context_window_size(self) -> int:
        return 8192
