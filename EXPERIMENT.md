# Autonomous Startup Experiment Plan

## Purpose
Define how we test the core concept of "the autonomous startup": a multi-agent system that runs Build-Measure-Learn loops and improves startup-VC matching and outreach performance over time.

## Core Hypothesis
A coordinated agent system with memory can improve matching and outreach outcomes across repeated iterations with minimal human intervention.

## Experiment Questions
1. Can the system run end-to-end Build-Measure-Learn cycles reliably?
2. Does performance trend upward across iterations?
3. Does memory lead to better decisions in later iterations?
4. Can content and tool ideas feed acquisition for the matching platform concept?
5. Can constrained simulated customers approximate marketplace behavior well enough for pre-production decisions?

## System Under Test
- Orchestration: `src/crewai_agents/crews.py`
- Agent definitions: `src/crewai_agents/agents.py`
- Tools: `src/crewai_agents/tools.py`
- Persistence: `src/data/database.py`
- Simulation actors: `src/simulation/startup_agent.py`, `src/simulation/vc_agent.py`, `src/simulation/scenarios.py`
- Runtime scripts: `scripts/seed_memory.py`, `scripts/run_simulation.py`, `scripts/run_customer_simulation.py`, `scripts/evaluate_customer_simulation.py`
- Customer simulation model: `CUSTOMER_SIMULATION.md`

## Baseline Setup
1. Install deps
   - `pip install -r requirements.txt`
2. Configure environment
   - `cp .env.example .env`
   - Keep `MOCK_MODE=true` for deterministic simulation
3. Seed memory and data
   - `python scripts/seed_memory.py`
4. Smoke test
   - `python scripts/test_crewai_quick.py`
5. Confirm customer simulation parameters
   - Review and lock cohort sizes/thresholds in `CUSTOMER_SIMULATION.md`
6. Validate deterministic customer scenario matrix
   - `python scripts/run_customer_simulation.py`
7. Evaluate Track D hypotheses against matrix output
   - `python scripts/evaluate_customer_simulation.py --summary-path data/memory/customer_matrix_summary.json --allow-warn`

## Experiment Protocol
1. Baseline run
   - `python scripts/run_simulation.py --iterations 3 --verbose 1`
2. Extended stability run
   - `python scripts/run_simulation.py --iterations 5 --verbose 0`
3. Repeatability run (same config)
   - Run the same command 2-3 times and compare trends
4. Capture outputs
   - Record metrics and qualitative agent outputs in the run log template below

## Success Criteria (Simulation Phase)
- Reliability
  - All runs complete without exceptions
  - `scripts/test_crewai_quick.py` passes
- Outcome trend
  - Response rate in final iteration >= first iteration
  - Meeting rate in final iteration >= first iteration
- Learning evidence
  - LEARN phase returns actionable recommendations each iteration
  - Memory artifacts are updated during runs (episodic/procedural activity)
- Product relevance
  - BUILD phase output includes matching-quality and outreach-quality improvements
- Customer behavior relevance
  - Simulated founder/VC/customer funnel transitions are reproducible with fixed inputs
  - At least one variant improves either:
    - signup -> first qualified match conversion
    - mutual interest -> meeting conversion

## Experiment Tracks

### Track A: Matching Quality Simulation
Goal: validate that decisions increasingly optimize startup-VC fit.

- Variable: matching heuristics and tool prompts
- Metrics:
  - Predicted response rate
  - Predicted meeting rate
  - Match explanation quality (manual rubric 1-5)
- Pass condition:
  - Upward trend across at least 3 iterations

### Track B: Outreach Quality Simulation
Goal: test whether personalized outreach improves campaign metrics.

- Variable: message generation prompts and personalization inputs
- Metrics:
  - Personalization score from tool output
  - Message quality rubric (clarity, relevance, CTA)
  - Response and meeting trend
- Pass condition:
  - Higher average personalization and positive rate trend

### Track C: Acquisition Layer Simulation (Articles + Tools)
Goal: validate the growth model around the core matching product.

- Variable: article topic clusters and utility tool concepts
- Metrics:
  - Number of publish-ready article briefs created
  - Number of usable tool specs generated
  - Funnel mapping completeness (Article -> Tool -> Signup -> Match)
- Pass condition:
  - At least 10 article briefs + 3 tool specs with clear CTA flow

### Track D: Customer Behavior Simulation (Constrained Environment)
Goal: validate customer-side dynamics without leaving the simulation environment.

- Variable: cohort mix, transition thresholds, and behavior parameters
- Deterministic scenario matrix:
  - `baseline`
  - `high_personalization`
  - `better_matching`
  - `acquisition_push`
- Hypothesis contract file:
  - `data/seed/customer_hypotheses.json`
- Metrics:
  - founder visit -> signup conversion
  - VC visit -> signup conversion
  - visitor -> tool use conversion
  - tool use -> signup conversion
  - signup -> first match conversion
  - founder interest rate, VC interest rate, mutual interest rate
  - mutual interest -> meeting conversion
- Pass condition:
  - Reproducible outputs with fixed seed and configuration
  - At least one tested variant improves a downstream conversion metric
- Execution command:
  - `python scripts/run_customer_simulation.py`
- Evaluation command:
  - `python scripts/evaluate_customer_simulation.py --summary-path data/memory/customer_matrix_summary.json --allow-warn`

## Run Log Template
Use this for each experiment run.

- Run ID:
- Date:
- Config: iterations, verbose, mock mode
- Build output summary:
- Measure output:
  - Iteration 1 response/meeting:
  - Iteration N response/meeting:
- Learn output summary:
- What improved:
- What regressed:
- Decision:
  - Keep
  - Iterate
  - Rollback

## Decision Gates
- Gate 1: Technical viability
  - Pass if system runs reliably and tests pass
- Gate 2: Learning viability
  - Pass if iteration metrics trend upward in repeated runs
- Gate 3: Product viability signal
  - Pass if generated outputs clearly support matching platform outcomes
- Gate 4: Acquisition viability signal
  - Pass if content + tool strategy yields clear top-of-funnel assets and funnel path
- Gate 5: Customer simulation viability signal
  - Pass if constrained customer behavior outputs are reproducible and decision-useful

## Known Limitations (Current Prototype)
- MEASURE phase metrics are currently simulated, not from real user behavior
- Matching quality is mostly heuristic/prompt-driven, not yet benchmarked on real labeled outcomes
- Acquisition signals are design-time outputs, not live SEO traffic data
- Customer behavior model is simplified and parameterized, not calibrated to production usage yet

## Next Phase After Passing
1. Add real match scoring evaluation against labeled startup-VC fit data
2. Add API endpoints for recommendations and tool experiences
3. Launch first content cluster and first two utility tools
4. Replace simulated outcome signals with real usage analytics
5. Implement dedicated customer simulation components in `src/simulation/` for repeatable scenario testing
