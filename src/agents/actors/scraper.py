"""Scraper Actor - Simulated data collection agent."""
import json
import time
from pathlib import Path
from typing import Dict, Any
from src.agents.base import BaseActor
from src.llm.client import LLMClient
from src.llm.prompts import PromptTemplates
from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


class ScraperActor(BaseActor):
    """Actor that simulates data scraping."""

    def __init__(self, llm_client: LLMClient, memory_system: Dict[str, Any]):
        """Initialize Scraper Actor.

        Args:
            llm_client: LLM client instance
            memory_system: Memory system dict
        """
        super().__init__("scraper_actor", llm_client, memory_system)

    def execute(self, task: Dict[str, Any]) -> Any:
        """Execute scraping task (simulated).

        Args:
            task: Task dict

        Returns:
            Scraped data
        """
        self.log(f"Executing scraping task: {task.get('description', 'Unknown')}")

        # Simulate processing time
        time.sleep(0.5)

        # Determine what to scrape based on task description
        description = task.get('description', '').lower()

        if 'fintech' in description:
            data = self._load_filtered_data('fintech')
        elif 'healthtech' in description:
            data = self._load_filtered_data('healthtech')
        elif 'startup' in description:
            data = self._load_seed_data(settings.seed_startups_path)
        elif 'vc' in description:
            data = self._load_seed_data(settings.seed_vcs_path)
        else:
            # Load all startup data as default
            data = self._load_seed_data(settings.seed_startups_path)

        self.log(f"Scraped {len(data)} records")

        # Store in semantic memory
        for item in data[:5]:  # Store sample in semantic memory
            self.semantic_memory.add(
                text=self._item_to_text(item),
                metadata=item
            )

        return {
            'status': 'completed',
            'data': data,
            'count': len(data)
        }

    def validate(self, result: Any) -> bool:
        """Validate scraped data.

        Args:
            result: Execution result

        Returns:
            True if valid
        """
        if not result or result.get('status') != 'completed':
            return False

        data = result.get('data', [])

        if not data:
            self.log("Validation failed: No data scraped", level="warning")
            return False

        # Check data schema
        required_fields = ['id', 'name']
        for item in data[:10]:  # Validate sample
            if not all(field in item for field in required_fields):
                self.log("Validation failed: Missing required fields", level="warning")
                return False

        # Use LLM to validate data quality (in mock mode, this is fast)
        sample = data[:3]
        prompt = PromptTemplates.VALIDATE_DATA.format(data=json.dumps(sample, indent=2))
        validation_result = self.llm.generate(prompt)

        is_valid = 'pass' in validation_result.lower()

        if is_valid:
            self.log("Data validation: PASS")
        else:
            self.log(f"Data validation result: {validation_result}")

        return is_valid

    def _load_seed_data(self, path: str) -> list:
        """Load data from seed file.

        Args:
            path: Path to seed JSON file

        Returns:
            List of data items
        """
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.log(f"Failed to load seed data from {path}: {e}", level="error")
            return []

    def _load_filtered_data(self, sector: str) -> list:
        """Load filtered data by sector.

        Args:
            sector: Sector to filter by

        Returns:
            Filtered list
        """
        all_data = self._load_seed_data(settings.seed_startups_path)
        filtered = [item for item in all_data if item.get('sector') == sector]

        self.log(f"Filtered {len(filtered)} items for sector: {sector}")
        return filtered

    def _item_to_text(self, item: Dict[str, Any]) -> str:
        """Convert item to searchable text.

        Args:
            item: Data item

        Returns:
            Text representation
        """
        if 'sector' in item:  # Startup
            return (
                f"{item.get('name', 'Unknown')} - {item.get('sector', 'Unknown')} startup. "
                f"{item.get('description', '')} Stage: {item.get('stage', 'Unknown')}. "
                f"Location: {item.get('location', 'Unknown')}. "
                f"Recent: {item.get('recent_news', '')}"
            )
        elif 'sectors' in item:  # VC
            sectors = ', '.join(item.get('sectors', []))
            return (
                f"{item.get('name', 'Unknown')} - VC firm focusing on {sectors}. "
                f"Stage focus: {item.get('stage_focus', 'Unknown')}. "
                f"Check size: {item.get('check_size', 'Unknown')}. "
                f"Recent: {item.get('recent_activity', '')}"
            )
        else:
            return json.dumps(item)
