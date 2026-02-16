"""CrewAI Tools - Including web-enabled data collection tools."""
import json
import time
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from pathlib import Path

from crewai.tools import tool

from src.data.database import StartupDatabase
from src.utils.config import settings
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.framework.storage.sync_wrapper import SyncUnifiedStore

logger = get_logger(__name__)

# Global database instance
_db = None

# Global memory store instance (SyncUnifiedStore)
_memory_store: Optional["SyncUnifiedStore"] = None


def get_database() -> StartupDatabase:
    """Get or create database instance."""
    global _db
    if _db is None:
        _db = StartupDatabase()
    return _db


def set_memory_store(store: "SyncUnifiedStore") -> None:
    """Inject the unified memory store for tool use."""
    global _memory_store
    _memory_store = store
    logger.info("Memory store injected into CrewAI tools")


def get_memory_store() -> Optional["SyncUnifiedStore"]:
    """Get the current memory store (may be None if not initialised)."""
    return _memory_store


# =============================================================================
# WEB DATA COLLECTION TOOLS
# =============================================================================

@tool("Search Web for Startups")
def web_search_startups(query: str, sector: str = "technology") -> str:
    """Search the web for startup information.

    Use this tool to find startups by searching for them online. The LLM will
    process the search results and extract relevant startup information.

    Args:
        query: Search query (e.g., "fintech startups funding 2024", "YC batch startups")
        sector: Target sector to focus on

    Returns:
        Instructions for the agent to perform web search and extract data
    """
    logger.info(f"Web search for startups: {query} (sector: {sector})")

    # This tool returns instructions for the LLM to use its web capabilities
    return json.dumps({
        'action': 'web_search',
        'query': query,
        'sector': sector,
        'instructions': f"""
Search the web for: "{query}"

From the search results, extract startup information including:
- Company name
- Description/what they do
- Sector: {sector}
- Funding stage (seed, series_a, series_b, etc.)
- Recent news or achievements
- Website URL if available
- Location if mentioned

After extracting, use the 'Save Startup to Database' tool to store each startup found.
""",
        'suggested_searches': [
            f"{sector} startups funding 2024",
            f"new {sector} companies launched",
            f"Y Combinator {sector} startups",
            f"Product Hunt {sector} launches",
            f"TechCrunch {sector} funding news"
        ]
    }, indent=2)


@tool("Search Web for VCs")
def web_search_vcs(query: str, focus_sector: str = "technology") -> str:
    """Search the web for VC and investor information.

    Use this tool to find VCs and investors by searching online. The LLM will
    process the results and extract relevant VC information.

    Args:
        query: Search query (e.g., "seed stage VCs fintech", "active VC firms 2024")
        focus_sector: Sector focus to filter VCs

    Returns:
        Instructions for the agent to perform web search and extract data
    """
    logger.info(f"Web search for VCs: {query} (focus: {focus_sector})")

    return json.dumps({
        'action': 'web_search',
        'query': query,
        'focus_sector': focus_sector,
        'instructions': f"""
Search the web for: "{query}"

From the search results, extract VC/investor information including:
- Firm name
- Investment sectors they focus on
- Stage focus (seed, series_a, series_b, growth)
- Check size range if mentioned
- Recent investments or activity
- Geographic focus
- Website URL if available

After extracting, use the 'Save VC to Database' tool to store each VC found.
""",
        'suggested_searches': [
            f"{focus_sector} venture capital firms",
            f"seed stage investors {focus_sector}",
            f"active VCs investing in {focus_sector} 2024",
            f"top {focus_sector} investors",
            f"VC firms recent investments {focus_sector}"
        ]
    }, indent=2)


@tool("Fetch and Parse Webpage")
def fetch_webpage(url: str, extract_type: str = "startups") -> str:
    """Fetch a webpage and extract startup or VC information.

    Use this tool to fetch a specific URL and extract structured data from it.

    Args:
        url: The URL to fetch
        extract_type: What to extract - 'startups' or 'vcs'

    Returns:
        Instructions for the agent to fetch and parse the page
    """
    logger.info(f"Fetch webpage: {url} (extract: {extract_type})")

    extraction_fields = {
        'startups': ['name', 'description', 'sector', 'stage', 'funding', 'website', 'location', 'recent_news'],
        'vcs': ['name', 'sectors', 'stage_focus', 'check_size', 'geography', 'recent_activity', 'website']
    }

    return json.dumps({
        'action': 'fetch_url',
        'url': url,
        'extract_type': extract_type,
        'instructions': f"""
Fetch the webpage at: {url}

Extract {extract_type} information from the page content. Look for:
{', '.join(extraction_fields.get(extract_type, extraction_fields['startups']))}

For each {extract_type[:-1]} found, use the appropriate 'Save to Database' tool.
""",
        'fields_to_extract': extraction_fields.get(extract_type, extraction_fields['startups'])
    }, indent=2)


@tool("Save Startup to Database")
def save_startup(
    name: str,
    description: str = "",
    sector: str = "technology",
    stage: str = "seed",
    website: str = "",
    location: str = "",
    recent_news: str = "",
    source: str = "web_search"
) -> str:
    """Save a startup to the database.

    Args:
        name: Startup name (required)
        description: What the startup does
        sector: Business sector (fintech, healthtech, ai_ml, devtools, etc.)
        stage: Funding stage (seed, series_a, series_b, growth)
        website: Company website URL
        location: Company location
        recent_news: Recent news or achievements
        source: Where the data came from

    Returns:
        Confirmation of save status
    """
    logger.info(f"Saving startup: {name}")

    db = get_database()
    startup = {
        'name': name,
        'description': description,
        'sector': sector.lower().replace(' ', '_'),
        'stage': stage.lower().replace(' ', '_'),
        'website': website,
        'location': location,
        'recent_news': recent_news,
        'source': source,
        'fundraising_status': 'unknown'
    }

    success = db.add_startup(startup)

    return json.dumps({
        'status': 'success' if success else 'failed',
        'startup': name,
        'message': f"Startup '{name}' saved to database" if success else f"Failed to save '{name}'"
    }, indent=2)


@tool("Save VC to Database")
def save_vc(
    name: str,
    sectors: str = "technology",
    stage_focus: str = "seed",
    check_size: str = "",
    geography: str = "",
    recent_activity: str = "",
    website: str = "",
    source: str = "web_search"
) -> str:
    """Save a VC/investor to the database.

    Args:
        name: VC firm name (required)
        sectors: Investment sectors (comma-separated, e.g., "fintech, ai_ml, saas")
        stage_focus: Investment stage focus (seed, series_a, series_b, growth)
        check_size: Typical check size (e.g., "500K-2M", "5M-15M")
        geography: Geographic focus (e.g., "US, Europe")
        recent_activity: Recent investments or news
        website: Firm website URL
        source: Where the data came from

    Returns:
        Confirmation of save status
    """
    logger.info(f"Saving VC: {name}")

    db = get_database()

    # Parse sectors into list
    sector_list = [s.strip().lower().replace(' ', '_') for s in sectors.split(',')]

    vc = {
        'name': name,
        'sectors': sector_list,
        'stage_focus': stage_focus.lower().replace(' ', '_'),
        'check_size': check_size,
        'geography': geography,
        'recent_activity': recent_activity,
        'website': website,
        'source': source
    }

    success = db.add_vc(vc)

    return json.dumps({
        'status': 'success' if success else 'failed',
        'vc': name,
        'message': f"VC '{name}' saved to database" if success else f"Failed to save '{name}'"
    }, indent=2)


# =============================================================================
# DATA RETRIEVAL TOOLS
# =============================================================================

@tool("Get Startups from Database")
def get_startups_tool(sector: str = "all", stage: str = "all", limit: int = 20) -> str:
    """Retrieve startups from the database.

    Args:
        sector: Filter by sector (fintech, healthtech, ai_ml, etc.) or 'all'
        stage: Filter by stage (seed, series_a, series_b) or 'all'
        limit: Maximum number of results

    Returns:
        JSON with startups from database
    """
    logger.info(f"Getting startups: sector={sector}, stage={stage}")

    db = get_database()
    startups = db.get_startups(sector=sector, stage=stage, limit=limit)

    return json.dumps({
        'status': 'success',
        'count': len(startups),
        'sector': sector,
        'stage': stage,
        'startups': startups
    }, indent=2)


@tool("Get VCs from Database")
def get_vcs_tool(sector: str = "all", stage_focus: str = "all", limit: int = 20) -> str:
    """Retrieve VCs from the database.

    Args:
        sector: Filter by sector focus or 'all'
        stage_focus: Filter by stage focus or 'all'
        limit: Maximum number of results

    Returns:
        JSON with VCs from database
    """
    logger.info(f"Getting VCs: sector={sector}, stage={stage_focus}")

    db = get_database()
    vcs = db.get_vcs(sector=sector, stage_focus=stage_focus, limit=limit)

    return json.dumps({
        'status': 'success',
        'count': len(vcs),
        'sector': sector,
        'stage_focus': stage_focus,
        'vcs': vcs
    }, indent=2)


@tool("Get Database Stats")
def get_database_stats() -> str:
    """Get statistics about collected data.

    Returns:
        Database statistics including counts and sectors
    """
    db = get_database()
    stats = db.get_stats()

    return json.dumps({
        'status': 'success',
        'stats': stats,
        'message': f"Database has {stats['total_startups']} startups and {stats['total_vcs']} VCs"
    }, indent=2)


# =============================================================================
# OUTREACH TOOLS
# =============================================================================

@tool("Send Outreach Email")
def send_outreach_email(
    recipient_name: str,
    recipient_email: str,
    subject: str,
    message: str,
    recipient_type: str = "startup",
    recipient_id: str = "",
    campaign_id: str = "default"
) -> str:
    """Send a simulated outreach email and log it to the database.

    This tool simulates sending an email and records the outreach attempt
    in the database for tracking and analytics.

    Args:
        recipient_name: Name of the recipient (company or person)
        recipient_email: Email address to send to
        subject: Email subject line
        message: Email body content
        recipient_type: Type of recipient ('startup' or 'vc')
        recipient_id: Database ID of the recipient (if known)
        campaign_id: Campaign identifier for grouping outreach

    Returns:
        Confirmation with outreach ID
    """
    logger.info(f"Sending outreach email to {recipient_name} <{recipient_email}>")

    db = get_database()

    # Log the outreach attempt
    outreach_id = db.log_outreach(
        recipient_type=recipient_type,
        recipient_id=recipient_id or recipient_name.lower().replace(' ', '_'),
        recipient_name=recipient_name,
        recipient_email=recipient_email,
        subject=subject,
        message=message,
        channel="email",
        campaign_id=campaign_id,
        metadata={
            'simulated': True,
            'word_count': len(message.split()),
            'subject_length': len(subject)
        }
    )

    return json.dumps({
        'status': 'sent',
        'outreach_id': outreach_id,
        'recipient': recipient_name,
        'email': recipient_email,
        'subject': subject,
        'message_preview': message[:100] + '...' if len(message) > 100 else message,
        'note': 'Email simulated - logged to database for tracking'
    }, indent=2)


@tool("Get Outreach History")
def get_outreach_history(campaign_id: str = "", limit: int = 20) -> str:
    """Get history of outreach attempts.

    Args:
        campaign_id: Filter by campaign (optional)
        limit: Maximum number of records to return

    Returns:
        JSON with outreach history
    """
    logger.info(f"Getting outreach history (campaign: {campaign_id or 'all'})")

    db = get_database()
    history = db.get_outreach_history(
        campaign_id=campaign_id if campaign_id else None,
        limit=limit
    )

    # Calculate stats
    total = len(history)
    responded = sum(1 for h in history if h.get('status') == 'responded')
    response_rate = responded / total if total > 0 else 0

    return json.dumps({
        'status': 'success',
        'total_outreach': total,
        'responded': responded,
        'response_rate': response_rate,
        'history': history
    }, indent=2)


@tool("Record Outreach Response")
def record_outreach_response(outreach_id: int, response: str, interested: bool = False) -> str:
    """Record a response to an outreach attempt.

    Args:
        outreach_id: ID of the outreach record
        response: The response received
        interested: Whether the recipient expressed interest

    Returns:
        Confirmation of update
    """
    logger.info(f"Recording response for outreach {outreach_id}")

    db = get_database()
    status = "interested" if interested else "responded"
    success = db.update_outreach_response(outreach_id, response, status)

    return json.dumps({
        'status': 'success' if success else 'failed',
        'outreach_id': outreach_id,
        'new_status': status,
        'message': f"Response recorded for outreach {outreach_id}" if success else "Failed to update"
    }, indent=2)


# =============================================================================
# ANALYSIS AND CONTENT TOOLS
# =============================================================================

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

        required_fields = ['name', 'sector', 'description']
        total_fields = 0
        present_fields = 0

        for startup in startups:
            for field in required_fields:
                total_fields += 1
                if field in startup and startup[field]:
                    present_fields += 1

        completeness = present_fields / total_fields if total_fields > 0 else 0

        return json.dumps({
            'status': 'pass' if completeness > 0.8 else 'warning',
            'completeness_score': completeness,
            'total_records': len(startups),
            'quality_issues': [] if completeness > 0.8 else ['Some records missing required fields']
        }, indent=2)

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

    message_parts = [
        f"Hi {startup_name} team,",
        "",
    ]

    if recent_news:
        message_parts.append(f"Congratulations on {recent_news.lower()}!")
    else:
        message_parts.append(f"I came across {startup_name} and was impressed by your work in {sector}.")

    message_parts.extend([
        "",
        f"We're working with VCs who are actively looking for innovative {sector} startups. "
        "Based on your profile, I think there could be some great matches.",
        "",
        "Would you be open to a brief 15-minute call to explore potential introductions?",
        "",
        "Best regards"
    ])

    message = "\n".join(message_parts)

    score = 0.5
    if recent_news:
        score += 0.3
    if len(message) < 600:
        score += 0.2

    return json.dumps({
        'message': message,
        'personalization_score': min(score, 1.0),
        'word_count': len(message.split())
    }, indent=2)


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
        'estimated_complexity': 'medium'
    }

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

        insights = []
        if response_rate > 0.30:
            insights.append("Excellent response rate - campaign is highly effective")
        elif response_rate > 0.20:
            insights.append("Good response rate - above industry average")
        else:
            insights.append("Low response rate - needs optimization")

        recommendations = []
        if response_rate < 0.25:
            recommendations.extend([
                "Increase personalization in messages",
                "Reference recent startup news/achievements"
            ])

        return json.dumps({
            'metrics': results,
            'insights': insights,
            'recommendations': recommendations,
            'overall_grade': 'A' if response_rate > 0.30 else 'B' if response_rate > 0.20 else 'C'
        }, indent=2)

    except Exception as e:
        return json.dumps({'error': str(e)})


# =============================================================================
# LEGACY COMPATIBILITY - Scraper tool that uses database
# =============================================================================

@tool("Scrape Startup Data")
def scraper_tool(sector: str = "all", stage: str = "all") -> str:
    """Get startup data from the database (collected via web search).

    If database is empty, this indicates web collection needs to be done first.

    Args:
        sector: Target sector or 'all'
        stage: Target stage or 'all'

    Returns:
        JSON string with startup data
    """
    logger.info(f"Scraper tool: Getting {sector} startups at {stage} stage")

    db = get_database()
    startups = db.get_startups(sector=sector, stage=stage, limit=50)

    if not startups:
        return json.dumps({
            'status': 'empty',
            'message': 'No startups in database. Use web search tools to collect data first.',
            'suggestion': 'Use "Search Web for Startups" tool to find and collect startup data'
        }, indent=2)

    return json.dumps({
        'status': 'success',
        'sector': sector,
        'stage': stage,
        'count': len(startups),
        'startups': startups
    }, indent=2)
