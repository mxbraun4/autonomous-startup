"""Patch for models that return both content and tool_calls simultaneously.

Some models (e.g. minimax-m2.5 via OpenRouter) return a short text
fragment in the ``content`` field alongside valid ``tool_calls``.
CrewAI 1.9.3's ``LLM._handle_non_streaming_response`` checks:

    if (not tool_calls or not available_functions) and text_response:
        return text_response

When ``available_functions`` is ``None`` (which it always is for native
tool calling), this returns the garbage content fragment ("te.") instead
of the tool_calls list.

This patch intercepts litellm.completion responses and clears the
content field when tool_calls are present, so CrewAI processes the
tool calls correctly.
"""

from __future__ import annotations

from src.utils.logging import get_logger

logger = get_logger(__name__)

_PATCHED = False


def patch_crewai_native_tool_loop() -> None:
    """Patch litellm responses to clear content when tool_calls are present."""
    global _PATCHED
    if _PATCHED:
        return

    import litellm

    _original_completion = litellm.completion

    def _patched_completion(*args, **kwargs):
        response = _original_completion(*args, **kwargs)

        # If the model returned both content and tool_calls, clear the
        # content so CrewAI doesn't mistake it for the final answer.
        if response and response.choices:
            msg = response.choices[0].message
            if (
                getattr(msg, "tool_calls", None)
                and msg.content
                and response.choices[0].finish_reason == "tool_calls"
            ):
                msg.content = None

        return response

    litellm.completion = _patched_completion
    _PATCHED = True
    logger.info(
        "Patched litellm.completion: clear content when tool_calls present"
    )
