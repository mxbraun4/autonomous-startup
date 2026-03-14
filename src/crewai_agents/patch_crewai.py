"""Monkey-patch CrewAI's native tool call loop to be more generous with text responses.

CrewAI 1.9.3 treats ANY text response after iteration 1 as the final answer,
even if the agent is just "thinking aloud" (e.g. "Let me check the files and
then start building").  This causes agents to exit after 2-3 turns without
doing real work.

This patch nudges the agent back to tool usage whenever it produces a text
response that is too short to be a real final answer, up to a configurable
threshold (default: half of max_iter).

Usage: call ``patch_crewai_native_tool_loop()`` once before any Crew kickoff.
"""

from __future__ import annotations

from src.utils.logging import get_logger

logger = get_logger(__name__)

_PATCHED = False

# Text responses shorter than this are considered "thinking aloud", not final answers.
_MIN_FINAL_ANSWER_LENGTH = 200

# Keep nudging until this fraction of max_iter is reached.
_NUDGE_FRACTION = 0.5


def patch_crewai_native_tool_loop() -> None:
    """Replace the native tool loop with a more generous version."""
    global _PATCHED
    if _PATCHED:
        return

    from pydantic import BaseModel

    from crewai.agents.crew_agent_executor import (
        CrewAgentExecutor,
        convert_tools_to_openai_schema,
        enforce_rpm_limit,
        get_llm_response,
        handle_context_length,
        handle_max_iterations_exceeded,
        handle_unknown_error,
        has_reached_max_iterations,
        is_context_length_exceeded,
    )
    from crewai.agents.parser import AgentFinish

    def _invoke_loop_native_tools_patched(self) -> AgentFinish:
        """Patched native tool loop: nudges text responses back to tool usage."""
        if not self.original_tools:
            return self._invoke_loop_native_no_tools()

        openai_tools, available_functions = convert_tools_to_openai_schema(
            self.original_tools
        )

        # Track consecutive text responses to avoid infinite nudge loops
        _consecutive_text_responses = 0
        _max_consecutive_text = 3

        nudge_limit = max(3, int(self.max_iter * _NUDGE_FRACTION))

        while True:
            try:
                if has_reached_max_iterations(self.iterations, self.max_iter):
                    formatted_answer = handle_max_iterations_exceeded(
                        None,
                        printer=self._printer,
                        i18n=self._i18n,
                        messages=self.messages,
                        llm=self.llm,
                        callbacks=self.callbacks,
                        verbose=self.agent.verbose,
                    )
                    self._show_logs(formatted_answer)
                    return formatted_answer

                enforce_rpm_limit(self.request_within_rpm_limit)

                answer = get_llm_response(
                    llm=self.llm,
                    messages=self.messages,
                    callbacks=self.callbacks,
                    printer=self._printer,
                    tools=openai_tools,
                    available_functions=None,
                    from_task=self.task,
                    from_agent=self.agent,
                    response_model=self.response_model,
                    executor_context=self,
                    verbose=self.agent.verbose,
                )

                # Tool calls — execute and continue
                if (
                    isinstance(answer, list)
                    and answer
                    and self._is_tool_call_list(answer)
                ):
                    tool_finish = self._handle_native_tool_calls(
                        answer, available_functions
                    )
                    _consecutive_text_responses = 0
                    if tool_finish is not None:
                        return tool_finish
                    continue

                # Text response
                if isinstance(answer, str):
                    is_short = len(answer.strip()) < _MIN_FINAL_ANSWER_LENGTH
                    within_nudge_budget = self.iterations < nudge_limit
                    under_consecutive_cap = _consecutive_text_responses < _max_consecutive_text

                    # Nudge back to tools if the text looks like thinking, not a real answer
                    if is_short and within_nudge_budget and under_consecutive_cap and openai_tools:
                        _consecutive_text_responses += 1
                        self._append_message(answer)
                        self.messages.append({
                            "role": "user",
                            "content": (
                                "Do not respond with text. You must call a tool now. "
                                "Use your tools to take action."
                            ),
                        })
                        continue

                    # Accept as final answer
                    _consecutive_text_responses = 0
                    formatted_answer = AgentFinish(
                        thought="",
                        output=answer,
                        text=answer,
                    )
                    self._invoke_step_callback(formatted_answer)
                    self._append_message(answer)
                    self._show_logs(formatted_answer)
                    return formatted_answer

                if isinstance(answer, BaseModel):
                    output_json = answer.model_dump_json()
                    formatted_answer = AgentFinish(
                        thought="",
                        output=answer,
                        text=output_json,
                    )
                    self._invoke_step_callback(formatted_answer)
                    self._append_message(output_json)
                    self._show_logs(formatted_answer)
                    return formatted_answer

                formatted_answer = AgentFinish(
                    thought="",
                    output=str(answer),
                    text=str(answer),
                )
                self._invoke_step_callback(formatted_answer)
                self._append_message(str(answer))
                self._show_logs(formatted_answer)
                return formatted_answer

            except Exception as e:
                if e.__class__.__module__.startswith("litellm"):
                    raise e
                if is_context_length_exceeded(e):
                    handle_context_length(
                        respect_context_window=self.respect_context_window,
                        printer=self._printer,
                        messages=self.messages,
                        llm=self.llm,
                        callbacks=self.callbacks,
                        i18n=self._i18n,
                        verbose=self.agent.verbose,
                    )
                    continue
                handle_unknown_error(self._printer, e, verbose=self.agent.verbose)
                raise e
            finally:
                self.iterations += 1

    CrewAgentExecutor._invoke_loop_native_tools = _invoke_loop_native_tools_patched
    _PATCHED = True
    logger.info(
        "Patched CrewAI native tool loop: nudge text responses for up to %d%% of max_iter",
        int(_NUDGE_FRACTION * 100),
    )
