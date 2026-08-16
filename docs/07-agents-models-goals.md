# Agent, model-routing, goal, intervention, and reasoning architecture

## Purpose

Define how Melli reasons across timescales, uses models without becoming identified with them, delegates to workers, represents goals, and learns whether interventions help.

## Persistent intelligence versus workers

Melli is the durable principal responsible for a stream of decisions. Workers are temporary executions. A worker record contains:

- parent intelligence and requesting event;
- task specification and success criteria;
- selected context manifest;
- capability lease and policy constraints;
- model route and fallback;
- time, step, token, and monetary budget;
- output schema;
- termination status and artifacts.

Workers do not automatically write long-term memory. They return proposed assertions or artifacts that a memory/action pipeline validates and records.

## Reasoning architecture

Reasoning is divided by function rather than by anthropomorphic “agent roles”:

1. **Ingest and normalize** — deterministic parsing and schema validation.
2. **Interpret** — turn observations into uncertainty-aware claims.
3. **Update state** — maintain current projections and detect contradictions.
4. **Assess relevance** — connect new information to goals, commitments, anomalies, and policies.
5. **Plan** — propose actions or experiments with expected value, risk, and evidence.
6. **Authorize** — deterministic capability broker decision.
7. **Execute** — capability adapter performs an approved action.
8. **Evaluate** — compare observed outcomes with the hypothesis and costs.
9. **Reflect** — update strategy, memory, thresholds, or propose software changes.

A single model call may support several functions, but the durable records remain separate.

## Model hierarchy

### Tier 0 — no generative model

- motion/scene change;
- thresholds and debouncing;
- hashes and duplicate suppression;
- timers, quiet hours, rate limits;
- deterministic schema conversion;
- SQL queries and policy checks.

### Tier 1 — small/local

- object/state classification;
- embeddings;
- simple extraction and routing;
- sensitive summarization when quality is adequate;
- first-pass image descriptions.

Candidates should be benchmarked on the actual hardware and task. llama.cpp provides a broad local LLM/VLM execution path, while MLX-LM is attractive on Apple Silicon and vLLM on suitable GPU servers; none should become the domain interface. [S32](research/primary-sources.md#S32) [S33](research/primary-sources.md#S33) [S34](research/primary-sources.md#S34)

### Tier 2 — efficient hosted or medium local

- event clustering;
- daily summaries;
- structured memory extraction;
- moderate planning;
- routine code review and classification.

### Tier 3 — frontier

- difficult multimodal ambiguity;
- long-horizon strategy review;
- complex coding/refactoring;
- threat analysis;
- architecture changes;
- periodic deep reviews where quality justifies cost.

## Routing contract

A route request includes:

```text
task_type
required_modalities
minimum_quality_profile
sensitivity_class
allowed_processing_locations
provider_retention_constraints
latency_deadline
context/token limits
cost ceiling
reliability requirement
structured-output schema
fallback and escalation rules
```

The router applies hard constraints first, then ranks eligible routes. An illustrative score is:

```text
utility = quality_fit
        - latency_penalty
        - expected_cost_penalty
        - privacy_exposure_penalty
        - failure_rate_penalty
        - context_truncation_penalty
```

Privacy is not a soft score when a class is `device_only`; ineligible providers are filtered out. Price snapshots are useful for budgets, but routes should reference configurable provider price cards because model names and prices change rapidly. OpenAI's current API page, for example, spans roughly $0.20/$1.20 per million input/output tokens for its low-cost GPT-5.6 tier to $5/$30 for the flagship tier, demonstrating why routing and caching matter. [S35](research/primary-sources.md#S35)

## Model registry

For each model/revision, record:

- provider, model ID, release/verification date;
- modality and context limits;
- task-specific evaluation results and confidence intervals;
- latency percentiles and failure rate;
- input/output/tool pricing;
- data retention/training/residency profile;
- structured-output and tool-use reliability;
- known safety or regression notes;
- approved sensitivity classes;
- fallback compatibility.

Provider-level statements are insufficient. A provider may offer zero-retention only for selected models or enterprise configurations. Eligibility must be attached to the exact route and account setting, then periodically re-verified.

## Escalation rules

Escalate when one or more are true:

- calibrated confidence is below the task threshold;
- competing interpretations are close;
- expected harm from error is high;
- the task requires a modality/context unavailable locally;
- a cheaper model fails validation;
- the owner explicitly asks for deeper analysis;
- periodic sampling is needed to detect degradation in a cheap route.

Do not escalate merely because a larger model exists. Escalation should be logged as a decision with expected marginal value.

## Structured decision records

Every meaningful reasoning run produces an owner-inspectable record containing the trigger, selected evidence, retrieval manifest, model/prompt/runtime versions, assumptions, uncertainty, alternatives where relevant, chosen plan, policy requests and decisions, tool calls, action receipts, costs, disclosures, and outcomes. The Owner Console renders this record. It is not a promise to expose hidden chain-of-thought; durable trust depends on evidence and structured decisions that can be replayed and corrected.

## Goal architecture

```text
Values
  ↓ constrain
Long-term objectives
  ↓ decompose
Current goals
  ↓ pursued through
Strategies and hypotheses
  ↓ tested by
Experiments / interventions
  ↓ produce
Actions and observed outcomes
  ↓ inform
Goal and strategy review
```

### Goal record

A goal should include:

- owner and acceptance status;
- desired direction/state, not just a metric;
- rationale and linked values;
- constraints and prohibited trade-offs;
- priority and conflicts with other goals;
- evidence sources and uncertainty;
- review cadence and expiry;
- success, failure, and stop criteria;
- interventions currently authorized;
- metrics as indicators, not the goal itself.

“Make me healthier” is not executable. A better goal might be:

> Increase the probability of completing two enjoyable 30-minute runs per week for eight weeks, without sacrificing sleep below an agreed threshold or prompting during meetings; review after four weeks and stop reminders if they reduce motivation.

## Goodhart and multi-objective safeguards

- Keep the human-readable goal and constraints beside metrics.
- Track adverse indicators and intervention burden.
- Do not let one proxy authorize actions outside its domain.
- Require periodic owner review for goals that persist or broaden.
- Preserve “do nothing” as a valid strategy.
- Detect optimization pressure: repeated actions aimed only at moving a metric without evidence of underlying benefit.
- Separate measurement from authorization; a high score never bypasses policy.

## Intervention model

Each intervention record includes:

- hypothesis and mechanism;
- target goal and expected outcome;
- target population/time/context—usually the single owner;
- treatment and comparison schedule where appropriate;
- delivery channel and interruption cost;
- confounders and carryover assumptions;
- outcome measures and collection method;
- minimum/maximum duration;
- stopping, safety, and fatigue rules;
- analysis method and uncertainty;
- decision: keep, modify, pause, or retire.

N-of-1 experiments are appropriate only when effects arise reasonably quickly, carryover can be managed, the intervention is reversible, and outcomes can be measured repeatedly. Not every before/after change supports causal language. [S46](research/primary-sources.md#S46) [S47](research/primary-sources.md#S47)

### Example

```text
Hypothesis: A 07:25 prompt on planned run days increases run starts by 09:00.
Constraint: Never prompt after <6.5 h sleep or during a calendar meeting.
Design: Randomized prompt/no-prompt across 12 eligible mornings.
Outcome: Run start detected and owner confirmation.
Fatigue stop: Two dismissals with “annoying” feedback in seven days.
Decision threshold: Continue only if estimated benefit is meaningful and burden low.
```

## Periodic reasoning loops

### Continuous / seconds

- sensor health;
- local motion and scene change;
- bounded ingestion and deduplication;
- hard safety and budget circuit breakers.

### Event-driven / minutes

- selected semantic interpretation;
- current-state update;
- urgent relevance and policy assessment;
- clarification request when uncertainty matters.

### Daily

- summarize significant events with citations;
- reconcile contradictions and missing data;
- check goal-relevant deviations;
- evaluate pending intervention outcomes;
- batch low-urgency messages.

### Weekly

- detect behavioral patterns with sample sizes and uncertainty;
- review intervention usefulness and fatigue;
- inspect false-positive/correction clusters;
- propose threshold, prompt, or workflow changes;
- review model and provider costs.

### Monthly

- review goals and conflicts;
- assess permissions, capabilities, and data retention;
- test a backup restore or rotate through recovery checks;
- archive/compress selected memories;
- review dependency/security posture and framework escape paths.

### Occasional

- propose a new capability or software artifact;
- conduct an architecture review;
- migrate a model/provider;
- retire a sensor or workflow that is not producing value.

Loops are jobs with explicit inputs, budgets, and idempotency—not immortal agents “thinking in the background.”

## Proactive interaction policy

A proactive-message score may consider:

```text
urgency × expected benefit × confidence
--------------------------------------
interruption cost × recent message load × uncertainty
```

Hard rules override the score. V1 controls:

- owner-defined quiet hours;
- per-channel daily and weekly budgets;
- urgency classes;
- cooldown by topic;
- batch windows for non-urgent items;
- current activity/calendar context when available;
- confidence thresholds;
- “no action” and “save for review” options;
- one-tap feedback: useful, wrong, too late, too frequent, sensitive.

## Build now

- One persistent Melli and explicit worker executions.
- Tiered model gateway with hard privacy/cost constraints.
- Goal and intervention records with review/stop conditions.
- Daily loop and a conservative weekly loop.
- Proactivity budgets and feedback.
- Task-specific evaluation registry for every enabled model route.

## Design for

- Alternate persistent identities.
- Local accelerator and remote edge inference.
- Formal experiment randomization and analysis modules.
- Model ensembles or independent reviewers for high-risk proposals.

## Defer

- Self-directed creation of new long-term goals without owner acceptance.
- Permanent specialist personalities as architecture.
- Continuous chain-of-thought storage; retain evidence, decisions, and concise rationale instead.
- Causal claims from weak observational patterns.
- Model routing based solely on generic benchmark leaderboards.
