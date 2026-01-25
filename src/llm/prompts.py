"""Prompt templates for different agent tasks."""


class PromptTemplates:
    """Collection of prompt templates for agent tasks."""

    # Master Planner prompts
    MASTER_ANALYZE_STATE = """You are the Master Planner for an autonomous startup platform.

Current state:
{state_summary}

Recent performance metrics:
{metrics}

Episodic memory (recent experiences):
{episodic_context}

Analyze the current state and identify:
1. What's working well
2. What needs improvement
3. Key opportunities or risks
4. Priority areas for the next iteration

Provide a concise analysis."""

    MASTER_DECOMPOSE_GOALS = """Based on this analysis:
{analysis}

Decompose into specific goals for each specialized planner:

1. Data Strategy Planner goal:
2. Product Strategy Planner goal:
3. Outreach Strategy Planner goal:

Each goal should be specific, measurable, and achievable in one iteration."""

    # Data Strategy Planner prompts
    DATA_IDENTIFY_GAPS = """You are the Data Strategy Planner.

Current data inventory:
{data_summary}

VC preferences data:
{vc_preferences}

Identify data gaps where startup coverage doesn't match VC interests.
Prioritize gaps by potential impact on matching quality."""

    DATA_SCRAPING_PLAN = """Create a data collection plan to address these gaps:
{gaps}

For each gap, specify:
1. Target source (e.g., Crunchbase, Product Hunt)
2. Filter criteria
3. Expected yield
4. Priority (high/medium/low)"""

    # Product Strategy Planner prompts
    PRODUCT_IDENTIFY_NEEDS = """You are the Product Strategy Planner.

User interaction history:
{user_interactions}

Current tool inventory:
{tools}

Identify unmet user needs that could be addressed with new tools or features."""

    PRODUCT_TOOL_SPEC = """Create a detailed specification for this tool:
{tool_idea}

Include:
1. Purpose and use cases
2. Key features
3. Implementation approach
4. Expected impact on user workflow"""

    # Outreach Strategy Planner prompts
    OUTREACH_CAMPAIGN_PLAN = """You are the Outreach Strategy Planner.

Available startup data:
{startup_data_summary}

VC interests:
{vc_interests}

Previous campaign results:
{previous_results}

Create an outreach campaign plan that maximizes response rate and meeting conversions."""

    OUTREACH_MESSAGE_TEMPLATE = """Create a personalized outreach message for this startup:

Startup profile:
{startup_profile}

Matched VCs:
{matched_vcs}

Learnings from previous successful outreach:
{learnings}

Generate a concise, personalized message (under 150 words) that:
1. References specific startup details
2. Highlights relevant VC matches
3. Includes clear call-to-action"""

    # Actor prompts
    VALIDATE_DATA = """Validate this scraped data:
{data}

Check for:
1. Data completeness (required fields populated)
2. Schema compliance
3. Obvious errors or inconsistencies

Return validation result (PASS/FAIL) and any issues found."""

    EVALUATE_TOOL = """Evaluate this tool implementation:
{tool_code}

Test cases:
{test_cases}

Execute tests and report:
1. Which tests passed/failed
2. Any bugs or issues
3. Overall quality assessment"""
