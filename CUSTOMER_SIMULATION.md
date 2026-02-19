# Customer Simulation Spec

## Purpose
Define a constrained customer simulation environment for the autonomous startup prototype so product behavior can be tested without relying on live traffic or external systems.

## Why This Exists
- Keep experimentation deterministic and low-cost
- Validate core product loops before production infrastructure
- Measure conversion and match quality signals in a controlled environment

## Environment Contract (v1)

### Scope
- This contract defines the customer-side environment only.
- It primarily covers founder and VC behavioral transitions and environment metrics.
- Visitor simulation remains available but is disabled by default in marketplace-focused runs.
- It does not cover web scraping, live traffic, external APIs, or LLM-generated customer decisions.

### Non-Goals
- Real-world prediction accuracy for production forecasting
- Open-ended conversational roleplay
- Unbounded agent autonomy

### Required Input Interface

The simulator must consume a single environment input object with the following top-level keys:
- `run_context`
- `params`
- `cohorts`
- `signals`

#### 1) `run_context`
- `run_id`: `str`, unique identifier for the run
- `iteration`: `int`, `>= 1`
- `seed`: `int`, deterministic random seed
- Optional qualitative feedback controls:
  - `use_llm_feedback`: `bool`
  - `llm_feedback_steps`: list of step ids (for selective LLM enrichment)
  - `llm_feedback_temperature`: float in `[0.0, 1.0]`
  - `product_surface_only`: `bool` (if true, output strips internal score snapshots)

#### 2) `params`
All values are numeric and bounded in `[0.0, 1.0]` unless noted:
- `founder_base_interest`
- `vc_base_interest`
- `meeting_rate_from_mutual_interest`
- Optional signup behavior params:
  - `founder_signup_base_rate`
  - `vc_signup_base_rate`
  - `founder_signup_cta_clarity`
  - `vc_signup_cta_clarity`
  - `founder_signup_friction`
  - `vc_signup_friction`
  - `founder_signup_trust_score`
  - `founder_signup_form_complexity`
  - `founder_signup_channel_intent_fit`
  - `founder_signup_proof_of_outcomes`
- Optional threshold params:
  - `match_score_threshold`
  - `vc_match_score_threshold` (preferred VC match gate)
  - `shortlist_threshold` (legacy fallback for VC match gate)
  - `interest_threshold`
  - `max_steps_per_customer` (integer, `>= 1`)
- Optional acquisition params (visitor mode only):
  - `visitor_tool_click_rate`
  - `signup_rate_from_tool`

#### 3) `cohorts`
- `founders`: list of founder profiles
- `vcs`: list of VC profiles
- `visitors`: optional list of visitor profiles (used only when visitor simulation is enabled)

Required founder fields:
- `id`, `sector`, `stage`, `geography`, `fundraising_status`, `urgency_score`
- Optional `signup_payload` object for visit->signup modeling
  - Required signup fields when provided: `sector`, `stage`, `geography`, `fundraising_status`

Required VC fields:
- `id`, `thesis_sectors`, `stage_focus`, `geography`, `confidence_threshold`
- Optional `signup_payload` object for visit->signup modeling
  - Required signup fields when provided: `thesis_sectors`, `stage_focus`, `geography`

Required visitor fields:
- `id`, `intent_topic`, `tool_need_score`, `cta_friction`

#### 4) `signals`
Signals are produced by system components and consumed by the environment:
- `match_signals`: list of `{founder_id, vc_id, match_score, explanation_quality}`
- `outreach_signals`: list of `{founder_id, vc_id, personalization_score, timing_score}`
- `acquisition_signals`: optional list of `{visitor_id, article_relevance, tool_usefulness, cta_clarity}`

### Website Event Instrumentation (Pre-Processing)
- Optional `product_events` can be provided to `build_customer_environment_input(...)`.
- Required fields per event:
  - `event_id`, `timestamp` (ISO-8601), `session_id`, `actor_type`, `actor_id`, `event_name`, `properties`
- Event names are constrained to the tracked set only.
- `landing_view` must include at least one channel descriptor:
  - `properties.utm_source` (string) or `properties.channel_intent_fit` (`0..1`)
- These events are deterministically aggregated into founder signup signal overrides before simulation:
  - global founder params: `founder_signup_cta_clarity`, `founder_signup_friction`
  - founder profile signals: `trust_score`, `form_complexity_score`, `channel_intent_fit`, `proof_of_outcomes`
- Deterministic signal formulas:
  - `founder_signup_cta_clarity = clamp(cta_click / cta_impression)` (fallback to default param when no impressions)
  - `founder_signup_friction = clamp(0.15 + 0.35*error_rate + 0.35*abandon_rate + 0.15*incomplete_rate)` (fallback when no signup_start)
  - `trust_score` and `proof_of_outcomes` use observed values when available, otherwise deterministic view-count fallback, then default
  - `form_complexity_score` and `channel_intent_fit` use observed values when available, otherwise default
- Diagnostics expose per-founder measurement transparency:
  - `founder_signal_coverage`, `founder_signal_sources`, `founder_signal_inputs`
  - global `param_sources`, `effective_global_signup_params`
- Current tracked event names:
  - `landing_view`, `cta_impression`, `cta_click`, `signup_start`, `signup_submit`, `signup_field_error`, `signup_abandon`, `trust_block_view`, `proof_block_view`

### Output Interface

Each environment run must return a JSON-serializable object with:
- `metrics`
- `events`
- `final_states`
- `diagnostics`

Required `metrics` keys:
- `founder_visit_to_signup`
- `vc_visit_to_signup`
- `founder_interested_rate`
- `vc_interested_rate`
- `mutual_interest_rate`
- `meeting_conversion_rate`
- `average_match_relevance`
- `explanation_coverage`
- `personalization_quality_score`
- Optional acquisition metrics (visitor mode):
  - `visitor_to_tool_use`
  - `tool_use_to_signup`
  - `signup_to_first_match`

Event shape (`events[]`):
- `event_id`
- `iteration`
- `actor_type` (`founder|vc|visitor`)
- `actor_id`
- `from_state`
- `to_state`
- `reason_code`
- `score_snapshot` (object with relevant numeric values)

`final_states` shape:
- `founders`: map of `founder_id -> state`
- `vcs`: map of `vc_id -> state`
- `visitors`: map of `visitor_id -> state`

`diagnostics` minimum:
- `dropoff_reasons`: map of reason code to count
- `input_validation_errors`: list
- `interaction_logs`: per-actor interaction trace with outcome and feedback
- `failure_feedback`: normalized list of failed-transition feedback records
- `feedback_contract_version`: version number for feedback payload schema
- `product_surface`: product-facing view containing only observable events/interactions and failure feedback

### Determinism and Safety Invariants
- No external network dependency for customer behavior decisions
- Same `{seed, params, cohorts, signals}` must produce identical outputs
- Bounded state transitions; no loops outside defined state graph
- At most `max_steps_per_customer` transitions per actor per run
- Missing required fields must fail validation and be reported in `diagnostics`

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

## Customer State Machines

### Founder Journey
`visit -> signup -> engaged -> matched -> interested -> meeting`

Transition drivers:
- `signup`: deterministic `signup_complete` precheck on required signup fields, then CTA clarity, signup friction, trust, form complexity, channel-intent fit, proof of outcomes, urgency
- `engaged`: content/tool relevance
- `matched`: match score above threshold
- `interested`: outreach personalization + fit explanation quality
- `meeting`: founder interest + VC reciprocal interest

### VC Journey
`visit -> signup -> engaged -> matched -> interested -> meeting`

Transition drivers:
- `signup`: deterministic `signup_complete` precheck on required signup fields, then CTA clarity, signup friction, preview match quality, confidence threshold
- `engaged`: startup quality + relevance to thesis
- `matched`: alignment and confidence threshold
- `interested`: strong signal on fit and timing
- `meeting`: reciprocal founder interest

### Visitor Journey (Optional)
`visit -> article_read -> tool_use -> signup -> first_match`

Transition drivers:
- article clarity and intent match
- tool output usefulness
- CTA clarity and friction

## Founder/VC Transition Logic (Deterministic)

### Founder
1. `visit -> signup`
   - Inputs: `founder_signup_base_rate`, `founder_signup_cta_clarity`, `founder_signup_friction`, `founder_signup_trust_score`, `founder_signup_form_complexity`, `founder_signup_channel_intent_fit`, `founder_signup_proof_of_outcomes`, `urgency_score`
   - Deterministic precheck:
     - `signup_complete = all(sector, stage, geography, fundraising_status are non-empty in signup payload)`
     - on failure: `reason_code = founder_signup_incomplete_profile`
   - Derived:
     - `signup_prob = clamp(founder_signup_base_rate * (0.60 + 0.40 * founder_signup_cta_clarity) * (1.00 - 0.35 * founder_signup_friction) * (1.00 - 0.35 * form_complexity_score) * (0.60 + 0.40 * trust_score) * (0.60 + 0.40 * channel_intent_fit) * (0.60 + 0.40 * proof_of_outcomes) * (0.60 + 0.40 * urgency_score))`
   - Decision: `signup_complete and (rng.random() < signup_prob)`
2. `signup -> engaged`
   - `engaged_prob = clamp(0.20 + 0.45 * match_score + 0.25 * urgency_score)`
   - Decision: `rng.random() < engaged_prob`
3. `engaged -> matched`
   - Gate: `match_score >= match_score_threshold`
4. `matched -> interested`
   - `interest_prob = clamp(founder_base_interest + 0.35 * personalization_score + 0.20 * explanation_quality + 0.15 * timing_score + 0.15 * urgency_score)`
   - Gate + decision: `interest_prob >= interest_threshold` and `rng.random() < interest_prob`
5. `interested -> meeting`
   - Requires mutual interest with VC, then `rng.random() < meeting_rate_from_mutual_interest`

### VC
1. `visit -> signup`
   - Inputs: `vc_signup_base_rate`, `vc_signup_cta_clarity`, `vc_signup_friction`, `confidence_threshold`, `match_score`, `explanation_quality`
   - Deterministic precheck:
     - `signup_complete = all(thesis_sectors, stage_focus, geography are non-empty in signup payload)`
     - on failure: `reason_code = vc_signup_incomplete_profile`
   - Derived:
     - `preview_match_quality = clamp(0.70 * match_score + 0.30 * explanation_quality)`
     - `confidence_factor = clamp(1.00 - confidence_threshold)`
     - `signup_prob = clamp(vc_signup_base_rate * (0.60 + 0.40 * vc_signup_cta_clarity) * (0.50 + 0.50 * preview_match_quality) * (1.00 - 0.35 * vc_signup_friction) * (0.55 + 0.45 * confidence_factor))`
   - Decision: `signup_complete and (rng.random() < signup_prob)`
2. `signup -> engaged`
   - `engaged_prob = clamp(0.15 + 0.55 * match_score + 0.20 * explanation_quality)`
   - Decision: `rng.random() < engaged_prob`
3. `engaged -> matched`
   - Gate: `match_score >= vc_match_score_threshold` (fallback to `shortlist_threshold` for compatibility)
4. `matched -> interested`
   - `interest_prob = clamp(vc_base_interest + 0.40 * match_score + 0.20 * explanation_quality + 0.15 * timing_score)`
   - `gate_threshold = max(confidence_threshold, interest_threshold)`
   - Gate + decision: `interest_prob >= gate_threshold` and `rng.random() < interest_prob`
5. `interested -> meeting`
   - Requires mutual interest with Founder, then `rng.random() < meeting_rate_from_mutual_interest`

## Interaction + Feedback Contract
- Every founder/VC transition step records one interaction item with:
  - `step_id`, `interaction`, `decision_mode`, `outcome`, `reason_code`, `score_snapshot`
- On failed transitions, feedback is emitted to the system with:
  - `actor_type`, `actor_id`, `step_id`, `reason_code`, `feedback_to_system`, `feedback_source`, `feedback_category`, `feedback_action_hint`, `feedback_contract_version`
- Feedback source:
  - `template` by default (deterministic)
  - `llm` only for selected steps when `use_llm_feedback=true` and an LLM is available
- Deterministic feedback categories include:
  - `signup_validation`, `signup_conversion`, `engagement`, `match_quality`, `interest_gate`, `reciprocal_interest`, `meeting_conversion`, `guardrail`

## Transition Evaluation Order
- Validate actor input and current state
- Compute deterministic gates (hard thresholds)
- Compute probabilistic transition using seeded RNG
- Emit one event per accepted state transition
- Stop at terminal state or `max_steps_per_customer`
- Default runtime mode executes founder + VC only (`include_visitors=false`)

## Example Parameter Set (MVP)
- founder_base_interest = 0.15
- vc_base_interest = 0.12
- founder_signup_base_rate = 0.70
- vc_signup_base_rate = 0.66
- founder_signup_trust_score = 1.00
- founder_signup_form_complexity = 0.00
- founder_signup_channel_intent_fit = 1.00
- founder_signup_proof_of_outcomes = 1.00
- visitor_tool_click_rate = 0.20
- signup_rate_from_tool = 0.10
- meeting_rate_from_mutual_interest = 0.35

These are simulation defaults and should be tuned through experiments, not treated as real-world benchmarks.

## Metrics
- Funnel metrics:
  - founder visit -> signup
  - VC visit -> signup
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
- Existing simulation actors:
  - `src/simulation/startup_agent.py`
  - `src/simulation/vc_agent.py`
- Next environment components:
  - `src/simulation/customer_agent.py`
  - `src/simulation/customer_environment.py`
  - `src/simulation/customer_scenario_matrix.py`
  - `data/seed/customers.json`
  - `src/simulation/scenarios.py` (legacy generic scenario helpers)
- Experiment linkage:
  - Use `EXPERIMENT.md` Track D for customer simulation validation

## Initial Experiment Scenarios
1. Baseline customer flow with default parameters
2. High personalization variant (higher outreach quality)
3. Better matching variant (higher fit score thresholds)
4. Acquisition variant (stronger article/tool CTA design)

## Deterministic Scenario Runner
- Run all Track D matrix scenarios:
  - `python scripts/run_customer_simulation.py`
- Enable visitor cohort explicitly:
  - `python scripts/run_customer_simulation.py --include-visitors`
- Enable optional LLM feedback for selected steps (transitions remain deterministic):
  - `python scripts/run_customer_simulation.py --use-llm-feedback --llm-feedback-steps matched_to_interested`
- Run with product-event instrumentation input:
  - `python scripts/run_customer_simulation.py --product-events-path data/seed/product_events.json`
- Product-facing output only (no internal score snapshots):
  - `python scripts/run_customer_simulation.py --product-surface-only`
- Run a subset:
  - `python scripts/run_customer_simulation.py --scenarios baseline better_matching`
- Export JSON summary:
  - `python scripts/run_customer_simulation.py --json-out data/memory/customer_matrix_summary.json`

## Hypothesis Contract (Track D)
Hypotheses are defined in `data/seed/customer_hypotheses.json` and evaluated against deterministic scenario outputs.

Top-level structure:
- `version`: integer (`>= 1`)
- `hypotheses`: list of hypothesis objects

Required fields per hypothesis:
- `id`: non-empty string, unique
- `scenario`: one of `baseline|high_personalization|better_matching|acquisition_push`
- `metric`: non-empty metric key string
- `direction`: `increase` or `decrease`
- `min_delta`: numeric threshold (`>= 0.0`)

Optional fields:
- `guardrails`: list of guardrail objects
  - each guardrail requires `metric` and at least one of `min_delta` or `max_delta`

Loader and validator:
- `src/simulation/customer_hypotheses.py`

Evaluator:
- `src/simulation/customer_hypothesis_evaluator.py`
- CLI runner:
  - `python scripts/evaluate_customer_simulation.py --summary-path data/memory/customer_matrix_summary.json`
  - add `--allow-warn` while the hypothesis file is intentionally empty

## Acceptance Criteria
- Input and output interfaces are stable and validated at runtime
- Simulation runs end-to-end with fixed inputs and reproducible outputs
- At least one variant improves:
  - signup -> first match conversion
  - or mutual interest -> meeting conversion
- Results are explainable by parameter and behavior changes
