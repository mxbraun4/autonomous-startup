"""Minimal LLM client wrapper with deterministic mock fallback."""

from __future__ import annotations

import hashlib
from typing import Optional

from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class LLMClient:
    """Simple text-generation wrapper for Anthropic/OpenAI models."""

    def __init__(self) -> None:
        self._anthropic_api_key = settings.anthropic_api_key
        self._openai_api_key = settings.openai_api_key
        self.mock_mode = bool(
            settings.mock_mode or (not self._anthropic_api_key and not self._openai_api_key)
        )

    def generate(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
        max_tokens: int = 256,
        temperature: float = 0.0,
    ) -> str:
        """Return generated text from the configured model."""
        if self.mock_mode:
            return self._mock_response(prompt)

        model_name = (model or "").strip()
        if not model_name:
            model_name = (
                settings.anthropic_model
                if self._anthropic_api_key
                else settings.openai_model
            )

        provider, resolved_model = self._resolve_provider_model(model_name)
        if provider == "anthropic":
            return self._generate_anthropic(
                prompt=prompt,
                system=system,
                model=resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        if provider == "openai":
            return self._generate_openai(
                prompt=prompt,
                system=system,
                model=resolved_model,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        logger.warning("Unsupported model provider for model '%s'; falling back to mock", model_name)
        return self._mock_response(prompt)

    def _resolve_provider_model(self, model_name: str) -> tuple[str, str]:
        if model_name.startswith("anthropic/"):
            return ("anthropic", model_name.split("/", 1)[1])
        if model_name.startswith("openai/"):
            return ("openai", model_name.split("/", 1)[1])

        # Heuristic fallback for plain model ids.
        if "claude" in model_name.lower():
            return ("anthropic", model_name)
        return ("openai", model_name)

    def _generate_anthropic(
        self,
        prompt: str,
        system: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        if not self._anthropic_api_key:
            logger.warning("Anthropic model requested but API key missing; using mock response.")
            return self._mock_response(prompt)

        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=self._anthropic_api_key)
            response = client.messages.create(
                model=model,
                max_tokens=max(1, int(max_tokens)),
                temperature=float(temperature),
                system=system or "",
                messages=[{"role": "user", "content": prompt}],
            )
            parts = []
            for block in getattr(response, "content", []):
                text = getattr(block, "text", None)
                if isinstance(text, str):
                    parts.append(text)
            return " ".join(part.strip() for part in parts if part.strip()).strip()
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            logger.warning("Anthropic generation failed: %s", exc)
            return self._mock_response(prompt)

    def _generate_openai(
        self,
        prompt: str,
        system: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        if not self._openai_api_key:
            logger.warning("OpenAI model requested but API key missing; using mock response.")
            return self._mock_response(prompt)

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self._openai_api_key)
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system or "You are a concise assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=float(temperature),
                max_tokens=max(1, int(max_tokens)),
            )
            content = response.choices[0].message.content
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
                return " ".join(part.strip() for part in text_parts if part.strip()).strip()
            return ""
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            logger.warning("OpenAI generation failed: %s", exc)
            return self._mock_response(prompt)

    @staticmethod
    def _mock_response(prompt: str) -> str:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        return f"mock_response_{digest}"
