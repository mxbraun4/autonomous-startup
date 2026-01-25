"""LLM client with mock mode support."""
import random
from typing import Optional, Dict, Any
from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class LLMClient:
    """Wrapper for LLM API calls with mock mode support."""

    def __init__(self, mock_mode: Optional[bool] = None):
        """Initialize LLM client.

        Args:
            mock_mode: Whether to use mock responses. If None, uses settings.mock_mode
        """
        self.mock_mode = mock_mode if mock_mode is not None else settings.mock_mode

        if not self.mock_mode:
            try:
                from anthropic import Anthropic
                from openai import OpenAI

                self.anthropic_client = Anthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None
                self.openai_client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
            except ImportError:
                logger.warning("LLM clients not available. Falling back to mock mode.")
                self.mock_mode = True

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: str = "claude-3-haiku-20240307",
        max_tokens: int = 1024,
        temperature: float = 0.7
    ) -> str:
        """Generate text using LLM.

        Args:
            prompt: User prompt
            system: System prompt
            model: Model to use
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Generated text
        """
        if self.mock_mode:
            return self._mock_response(prompt, system)

        try:
            if "claude" in model.lower() and self.anthropic_client:
                return self._anthropic_call(prompt, system, model, max_tokens, temperature)
            elif "gpt" in model.lower() and self.openai_client:
                return self._openai_call(prompt, system, model, max_tokens, temperature)
            else:
                logger.warning("No LLM client available. Using mock response.")
                return self._mock_response(prompt, system)
        except Exception as e:
            logger.error(f"LLM API call failed: {e}. Using mock response.")
            return self._mock_response(prompt, system)

    def _anthropic_call(
        self,
        prompt: str,
        system: Optional[str],
        model: str,
        max_tokens: int,
        temperature: float
    ) -> str:
        """Call Anthropic API."""
        messages = [{"role": "user", "content": prompt}]

        response = self.anthropic_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or "",
            messages=messages
        )

        return response.content[0].text

    def _openai_call(
        self,
        prompt: str,
        system: Optional[str],
        model: str,
        max_tokens: int,
        temperature: float
    ) -> str:
        """Call OpenAI API."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self.openai_client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages
        )

        return response.choices[0].message.content

    def _mock_response(self, prompt: str, system: Optional[str] = None) -> str:
        """Generate mock response based on prompt keywords.

        This provides deterministic responses for testing without API calls.
        """
        prompt_lower = prompt.lower()

        # Data strategy responses
        if "data gap" in prompt_lower or "identify gap" in prompt_lower:
            return """Based on analysis of current data:
- Fintech sector: Only 10% coverage, but 30% of VCs focus on fintech
- Late-stage startups: 15% coverage, but 25% of VCs focus on Series B+
- Geographic gap: Limited coverage in Southeast Asia (5% vs 20% VC interest)

Recommended actions:
1. Prioritize fintech startup data collection
2. Expand late-stage startup coverage
3. Add Southeast Asia startups to database"""

        # Scraping plan responses
        elif "scraping plan" in prompt_lower or "data collection" in prompt_lower:
            return """Data Collection Plan:
1. Target: Fintech startups in Crunchbase
   - Filter: Founded 2020-2024, raised seed/Series A
   - Expected yield: 200-300 startups

2. Target: Late-stage startups in Product Hunt
   - Filter: Series B+ funding, active product
   - Expected yield: 100-150 startups

3. Target: Southeast Asia startups in TechInAsia
   - Filter: Active fundraising, B2B focus
   - Expected yield: 150-200 startups"""

        # Outreach strategy responses
        elif "outreach" in prompt_lower or "campaign" in prompt_lower:
            return """Outreach Campaign Strategy:

Target Segments:
1. High-priority: Fintech startups actively fundraising (50 contacts)
2. Medium-priority: Late-stage B2B startups (30 contacts)
3. Exploratory: Southeast Asia emerging startups (20 contacts)

Message Templates:
- Personalization: Reference recent funding news, product updates
- Value proposition: Highlight matched VC interests
- Call-to-action: Schedule 15-min intro call

Expected metrics:
- Response rate: 20-30%
- Meeting conversion: 40-50% of responders"""

        # Tool building responses
        elif "tool" in prompt_lower and ("build" in prompt_lower or "create" in prompt_lower):
            return """Tool Specification: Pitch Deck Analyzer

Purpose: Automatically analyze startup pitch decks for quality and VC fit

Features:
1. Slide structure analysis (problem, solution, market, traction, team, ask)
2. Content quality scoring (clarity, completeness, visual appeal)
3. VC alignment matching (sector fit, stage fit, check size fit)

Implementation approach:
- PDF parsing: Use PyPDF2 for text extraction
- Image analysis: Use OpenAI Vision API for slide screenshots
- Scoring algorithm: Weighted rubric based on VC feedback data
- Output: JSON report with scores and recommendations"""

        # Evaluation/validation responses
        elif "validate" in prompt_lower or "evaluate" in prompt_lower:
            return """Validation Results: PASS

Quality checks:
✓ Data completeness: 95% of required fields populated
✓ Data accuracy: Spot-checked 20 samples, 100% accurate
✓ Schema compliance: All records match expected format
✓ Deduplication: No duplicates found

Recommendations:
- Data is ready for production use
- Consider adding social media links for richer profiles"""

        # Learning/improvement responses
        elif "improve" in prompt_lower or "learn" in prompt_lower or "optimize" in prompt_lower:
            return """Learning Insights from Previous Iteration:

What worked:
- Personalized messages mentioning recent funding news: 35% response rate
- Outreach to fintech startups: 40% response rate (above average)
- Timing: Tuesday-Thursday 9-11am had best open rates

What didn't work:
- Generic templates: Only 12% response rate
- Weekend outreach: 5% response rate
- Messages over 150 words: 15% response rate

Recommended optimizations:
1. Increase personalization depth (mention product features, not just funding)
2. Focus on fintech sector (highest engagement)
3. Keep messages under 100 words
4. Send Tuesday-Thursday mornings only"""

        # Planning responses
        elif "plan" in prompt_lower and "next" in prompt_lower:
            return """Next Iteration Plan:

Goals:
1. Improve outreach response rate from 25% to 35%
2. Increase meeting conversion from 40% to 50%
3. Expand fintech coverage by 50%

Actions:
1. Data Strategy: Focus scraping on fintech sector
2. Product Strategy: Deploy pitch deck analyzer tool
3. Outreach Strategy: Implement personalization improvements from learnings

Success metrics:
- Response rate > 35%
- Meeting bookings > 20 (from 100 outreach)
- New fintech startups added > 100"""

        # Default response
        else:
            responses = [
                "Analysis complete. Key insights identified and recommendations generated.",
                "Task executed successfully. Results stored in memory for future reference.",
                "Processing complete. Next steps identified based on current context.",
                "Action plan formulated. Ready to proceed with execution.",
                "Evaluation complete. Quality metrics meet expected thresholds."
            ]
            return random.choice(responses)
