"""CrewAI Tools - Convert our Actors to Tools."""
import json
import time
from typing import Dict, Any, List
from pathlib import Path

from crewai.tools import tool

from src.memory import SemanticMemory, EpisodicMemory
from src.utils.config import settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


def load_json_file(path: str) -> list:
    """Load JSON file helper."""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load {path}: {e}")
        return []


@tool("Scrape Startup Data")
def scraper_tool(sector: str = "all", stage: str = "all") -> str:
    """Collect startup data from various sources.

    Args:
        sector: Target sector (fintech, healthtech, ai_ml, etc.) or 'all'
        stage: Target stage (seed, series_a, series_b) or 'all'

    Returns:
        JSON string with scraped startup data and count
    """
    logger.info(f"Scraper tool: Collecting {sector} startups at {stage} stage")

    # Simulate scraping time
    time.sleep(0.5)

    # Load seed data
    all_startups = load_json_file(settings.seed_startups_path)

    # Filter by sector
    if sector != "all":
        all_startups = [s for s in all_startups if s.get('sector') == sector]

    # Filter by stage
    if stage != "all":
        all_startups = [s for s in all_startups if s.get('stage') == stage]

    result = {
        'status': 'success',
        'sector': sector,
        'stage': stage,
        'count': len(all_startups),
        'startups': all_startups
    }

    logger.info(f"Scraped {len(all_startups)} startups")
    return json.dumps(result, indent=2)


@tool("Validate Data Quality")
def data_validator_tool(data_json: str) -> str:
    """Validate scraped data for quality and completeness.

    Args:
        data_json: JSON string of data to validate

    Returns:
        Validation report with quality score
    """
    logger.info("Data validator: Checking data quality")

    try:
        data = json.loads(data_json)
        startups = data.get('startups', [])

        if not startups:
            return json.dumps({
                'status': 'fail',
                'reason': 'No data to validate'
            })

        # Check required fields
        required_fields = ['id', 'name', 'sector', 'stage', 'description']
        total_fields = 0
        present_fields = 0

        for startup in startups:
            for field in required_fields:
                total_fields += 1
                if field in startup and startup[field]:
                    present_fields += 1

        completeness = present_fields / total_fields if total_fields > 0 else 0

        result = {
            'status': 'pass' if completeness > 0.9 else 'warning',
            'completeness_score': completeness,
            'total_records': len(startups),
            'quality_issues': [] if completeness > 0.9 else ['Some records missing required fields']
        }

        logger.info(f"Validation: {completeness:.1%} complete")
        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({
            'status': 'error',
            'reason': str(e)
        })


@tool("Generate Outreach Content")
def content_generator_tool(startup_name: str, sector: str, recent_news: str = "") -> str:
    """Generate personalized outreach message for a startup.

    Args:
        startup_name: Name of the startup
        sector: Startup sector
        recent_news: Recent news or achievements

    Returns:
        Personalized outreach message
    """
    logger.info(f"Content generator: Creating message for {startup_name}")

    # Simulate content generation
    time.sleep(0.3)

    # Build personalized message
    message_parts = []

    # Opening
    message_parts.append(f"Hi {startup_name} team,")
    message_parts.append("")

    # Personalization
    if recent_news:
        message_parts.append(f"Congratulations on {recent_news.lower()}!")
    else:
        message_parts.append(f"I came across {startup_name} and was impressed by your work in {sector}.")

    message_parts.append("")

    # Value proposition
    message_parts.append(
        "We're working with VCs who are actively looking for innovative "
        f"{sector} startups. Based on your profile, I think there could be "
        "some great matches."
    )
    message_parts.append("")

    # Call to action
    message_parts.append(
        "Would you be open to a brief 15-minute call to explore potential "
        "introductions?"
    )
    message_parts.append("")
    message_parts.append("Best regards")

    message = "\n".join(message_parts)

    # Calculate personalization score
    score = 0.5  # Base
    if recent_news:
        score += 0.3
    if len(message) < 600:  # Keep it concise
        score += 0.2

    result = {
        'message': message,
        'personalization_score': min(score, 1.0),
        'word_count': len(message.split())
    }

    return json.dumps(result, indent=2)


@tool("Build Tool Specification")
def tool_builder_tool(tool_idea: str, requirements: str = "") -> str:
    """Build a specification for a new tool or feature.

    Args:
        tool_idea: Description of the tool to build
        requirements: Specific requirements or constraints

    Returns:
        Tool specification with implementation approach
    """
    logger.info(f"Tool builder: Creating spec for {tool_idea}")

    # Simulate design time
    time.sleep(0.8)

    spec = {
        'tool_name': tool_idea.split()[0].lower() + '_tool',
        'description': tool_idea,
        'requirements': requirements,
        'features': [
            'Core functionality',
            'Input validation',
            'Error handling',
            'Performance optimization'
        ],
        'implementation_approach': [
            '1. Define interface and input/output schema',
            '2. Implement core logic',
            '3. Add validation and error handling',
            '4. Write unit tests',
            '5. Integration testing',
            '6. Documentation'
        ],
        'estimated_complexity': 'medium',
        'dependencies': ['pydantic', 'typing'],
        'test_coverage_target': 0.90
    }

    logger.info(f"Generated spec for {spec['tool_name']}")
    return json.dumps(spec, indent=2)


@tool("Analyze Metrics")
def analytics_tool(campaign_results: str) -> str:
    """Analyze campaign performance metrics.

    Args:
        campaign_results: JSON string with campaign results

    Returns:
        Analysis with insights and recommendations
    """
    logger.info("Analytics tool: Analyzing campaign metrics")

    try:
        results = json.loads(campaign_results)

        response_rate = results.get('response_rate', 0)
        meeting_rate = results.get('meeting_rate', 0)
        total_sent = results.get('total_sent', 0)

        # Analyze performance
        insights = []

        if response_rate > 0.30:
            insights.append("✓ Excellent response rate - campaign is highly effective")
        elif response_rate > 0.20:
            insights.append("✓ Good response rate - above industry average")
        else:
            insights.append("⚠ Low response rate - needs optimization")

        if meeting_rate > 0.10:
            insights.append("✓ Strong meeting conversion")
        else:
            insights.append("⚠ Low meeting conversion - improve call-to-action")

        # Recommendations
        recommendations = []

        if response_rate < 0.25:
            recommendations.append("Increase personalization in messages")
            recommendations.append("Reference recent startup news/achievements")

        if meeting_rate < 0.10:
            recommendations.append("Make call-to-action more specific")
            recommendations.append("Reduce friction in scheduling process")

        analysis = {
            'metrics': {
                'response_rate': response_rate,
                'meeting_rate': meeting_rate,
                'total_sent': total_sent
            },
            'insights': insights,
            'recommendations': recommendations,
            'overall_grade': 'A' if response_rate > 0.30 else 'B' if response_rate > 0.20 else 'C'
        }

        return json.dumps(analysis, indent=2)

    except Exception as e:
        return json.dumps({'error': str(e)})
