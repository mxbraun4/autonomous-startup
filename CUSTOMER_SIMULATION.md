# Customer Simulation Spec

## Purpose
Define a constrained customer simulation model for the autonomous startup prototype so product behavior can be tested without relying on live traffic or external systems.

## Why This Exists
- Keep experimentation deterministic and low-cost
- Validate core product loops before production infrastructure
- Measure conversion and match quality signals in a controlled environment

## Simulated Customer Types

### 1) Founder Customer
A startup operator looking for relevant VC introductions.

- Primary goals:
  - Find investors that match sector, stage, and geography
  - Receive useful, personalized outreach
- Key behavior signals:
  - Match relevance score
  - Outreach personalization score
  - Fundraising urgency

### 2) VC Customer
An investor user evaluating startup opportunities.

- Primary goals:
  - Filter to high-fit startups quickly
  - Receive explainable recommendations
- Key behavior signals:
  - Thesis alignment score
  - Stage alignment score
  - Pipeline quality threshold

### 3) Content Visitor (Acquisition)
A top-of-funnel user arriving via article or tool pages.

- Primary goals:
  - Learn something actionable
  - Use a practical tool
- Key behavior signals:
  - Article-topic relevance
  - Tool usefulness score
  - CTA friction

## Constrained Simulation Rules
- No external network dependency for customer behavior decisions
- Fixed cohort sizes per run (example: 50 founders, 30 VCs, 200 visitors)
- Deterministic randomness via seedable random generator
- Bounded state transitions (no unbounded loops)
- Keep feature inputs limited to fields already produced by the system
- Enforce runtime guardrails (tool-call loop detection, bounded delegation, policy-denied actions)

## Customer State Machines

### Founder Journey
`unaware -> engaged -> matched -> interested -> meeting`

Transition drivers:
- `engaged`: content/tool relevance
- `matched`: match score above threshold
- `interested`: outreach personalization + fit explanation quality
- `meeting`: founder interest + VC reciprocal interest

### VC Journey
`unaware -> engaged -> shortlist -> interested -> meeting`

Transition drivers:
- `engaged`: startup quality + relevance to thesis
- `shortlist`: alignment and confidence threshold
- `interested`: strong signal on fit and timing
- `meeting`: reciprocal founder interest

### Visitor Journey
`visit -> article_read -> tool_use -> signup -> first_match`

Transition drivers:
- article clarity and intent match
- tool output usefulness
- CTA clarity and friction

## Example Parameter Set (MVP)
- founder_base_interest = 0.15
- vc_base_interest = 0.12
- visitor_tool_click_rate = 0.20
- signup_rate_from_tool = 0.10
- meeting_rate_from_mutual_interest = 0.35

These are simulation defaults and should be tuned through experiments, not treated as real-world benchmarks.

## Metrics
- Funnel metrics:
  - visitor -> tool use
  - tool use -> signup
  - signup -> first qualified match
- Marketplace metrics:
  - founder interested rate
  - VC interested rate
  - mutual interest rate
  - meeting conversion rate
- Quality metrics:
  - average match relevance
  - explanation coverage (% of matches with rationale)
  - personalization quality score

## Integration With Current Code
- Existing agents:
  - `src/simulation/startup_agent.py`
  - `src/simulation/vc_agent.py`
- Framework safety/runtime modules:
  - `src/framework/runtime/agent_runtime.py`
  - `src/framework/orchestration/delegation.py`
  - `src/framework/safety/action_guard.py`
- Live run observability:
  - `scripts/live_dashboard.py`
  - `python scripts/run.py --mode dashboard --events-path data/memory/web_autonomy_events.ndjson`
- Extend with:
  - `src/simulation/customer_agent.py` (new, optional next step)
  - `data/seed/customers.json` (new cohort definitions)
  - `src/simulation/scenarios.py` customer-focused scenarios
- Experiment linkage:
  - Use `EXPERIMENT.md` Track D for customer simulation validation

## Initial Experiment Scenarios
1. Baseline customer flow with default parameters
2. High personalization variant (higher outreach quality)
3. Better matching variant (higher fit score thresholds)
4. Acquisition variant (stronger article/tool CTA design)

## Acceptance Criteria
- Simulation runs end-to-end with fixed inputs and reproducible outputs
- Loop-prone repeated action patterns are blocked consistently by guardrails
- Delegated/derived task expansion remains within configured bounds
- At least one variant improves:
  - signup -> first match conversion
  - or mutual interest -> meeting conversion
- Results are explainable by parameter and behavior changes
