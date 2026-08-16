# Testing, evaluation, and simulation

## Purpose

Test deterministic software, probabilistic reasoning, policy boundaries, hardware integrations, and long-term behavioral interventions without pretending they share one pass/fail methodology.

## Test pyramid and evidence types

| Layer | Primary question | Method |
|---|---|---|
| Unit | does a function enforce its invariant? | deterministic fast tests, property tests |
| Contract/schema | can versions and plugins interoperate safely? | JSON Schema/protobuf compatibility, fixtures, consumer tests |
| Integration | do adapters and stores behave with real dependencies? | disposable Postgres, fake/recorded APIs, container tests |
| Policy/security | can an unsafe proposal cross a boundary? | table/property/fuzz tests, adversarial inputs, deny-by-default tests |
| Replay/simulation | would a change behave acceptably on representative history? | deterministic event replay, virtual clock, mocked side effects |
| Agent/model eval | is quality, safety, cost, and latency acceptable statistically? | scenario suite, rubric/model/human graders, repeated samples |
| End-to-end | can a real owner journey complete? | staged system with synthetic and selected consented data |
| Hardware | do camera/network/power paths survive reality? | soak, disconnect, low-light, clock drift, bandwidth tests |
| Disaster recovery | can the system be restored safely? | clean-machine restore and integrity checks |
| Intervention | did an action help the owner? | predeclared outcome, N-of-1/observational analysis, feedback |

## Deterministic software tests

- Domain invariants for provenance, supersession, sensitivity inheritance, and action authorization.
- Job lease/retry/idempotency properties under crashes and duplicates.
- Event schema validation and compatibility fixtures across versions.
- Database migration up/down/forward tests on restored production-shaped data.
- Capability adapter contract tests with malformed, slow, duplicated, and spoofed responses.
- Timezone, DST, clock skew, leap-day, and delayed-event tests.
- Retention/deletion propagation and backup-expiry behavior.
- Cost and quota arithmetic.
- Guardian mode and fail-closed behavior.

Use property-based testing for policy and event invariants; manually enumerated happy paths are insufficient.

## Policy and security testing

Generate combinations of:

- actor/identity and authentication strength;
- capability and action parameters;
- data sensitivity and taint source;
- destination/recipient;
- budget and rate state;
- time/quiet hours;
- active grant/approval and exact action hash;
- Guardian mode;
- compromised or malformed tool output.

Assert that absence, ambiguity, stale approval, or policy-engine failure cannot broaden authority. Maintain regression cases for prompt injection, cross-tenant/identity leakage, path traversal, SSRF, malicious attachment types, encoded instructions, oversized payloads, and tool-output spoofing.

## Agent/model evaluation

Inspect AI is an open-source evaluation framework supporting tasks, solvers, scorers, models, tools, logs, and sandboxed environments; it is a good provider-neutral foundation rather than a proprietary tracing dependency. [S53](research/primary-sources.md#S53)

Each evaluation case specifies:

```text
scenario and source data
expected epistemic behavior (fact/inference/abstention)
allowed tools and exact forbidden effects
required policy outcome
quality rubric and critical errors
maximum tokens/cost/latency/tool steps
acceptable output schema
privacy/disclosure expectation
```

Report distributions over repeated runs, model/version/temperature, confidence intervals where meaningful, and critical-error counts. A single successful sample is not a release gate.

### Evaluation dimensions

- factual grounding and evidence citation;
- uncertainty calibration and willingness to ask/abstain;
- memory precision/recall and contradiction handling;
- plan quality and goal/policy alignment;
- prompt-injection resistance;
- correct tool choice and minimal authority request;
- policy compliance independent of answer quality;
- token, latency, monetary cost, and external disclosure;
- proactivity usefulness and interruption cost;
- degradation/fallback behavior.

## Replay system

The replay engine is a first-class safety mechanism.

### Inputs

- versioned canonical events and evidence references;
- a frozen or virtual clock;
- snapshot of goals, policies, grants, and memory visible at the historical time;
- model route or recorded deterministic outputs;
- simulated provider/capability responses;
- random seeds where supported;
- expected outcomes and known corrections.

### Modes

1. **Exact software replay:** deterministic code and recorded model/tool outputs; catches schema/state regressions.
2. **Counterfactual model replay:** new model/prompt against historical retrieval manifests; no real side effects.
3. **Policy replay:** new policy over historical action proposals.
4. **Failure injection:** timeouts, duplicates, out-of-order events, unavailable provider, full disk, corrupt response.
5. **Behavior simulation:** synthetic user/environment event sequences for workflow coverage, not proof of real-world benefit.

All side effects are replaced with receipts in simulation. The engine records proposed deltas and never writes production memory.

## Golden and adversarial datasets

- Curate small, high-quality cases from owner corrections and real failures, with sensitivity-aware storage.
- Use synthetic public fixtures for open-source CI.
- Keep a withheld owner-private regression set for local release gates.
- Label uncertain cases and grader disagreement; do not force false ground truth.
- Version datasets and document their purpose, provenance, consent, and limitations.
- Refresh adversarial cases so the system cannot merely fit a static injection checklist.

## Camera evaluation

Measure components separately:

- motion/scene segmentation precision and event fragmentation;
- person/object detector precision/recall by lighting and position;
- semantic activity classification with an explicit unknown class;
- time-to-event and frames/cloud calls per useful event;
- false “absence” or identity claims;
- low-light/IR artifacts, occlusion, camera move, pets, visitors, mirrors/screens;
- privacy retention and camera-off behavior.

A camera event becomes trusted only through evidence/provenance, not a headline accuracy percentage.

## Release gates

A change cannot promote when:

- any critical policy/security invariant regresses;
- an executed side effect lacks audit/authorization linkage;
- a schema migration loses or silently changes meaning;
- the critical-error count rises above zero for forbidden actions;
- privacy eligibility broadens without explicit review;
- median/percentile cost exceeds the declared bound without approval;
- proactivity exceeds frequency/quiet-hour constraints;
- backup/restore compatibility is untested for a durable-schema change.

Noncritical quality changes use declared tolerances and trade-off review; one score should not conceal safety or cost regressions.

## Intervention evaluation

A behavioral intervention contains:

- goal and hypothesis;
- target behavior/outcome and guardrails;
- intervention definition and delivery context;
- baseline window;
- planned duration/sample opportunity count;
- confounders and measurement limitations;
- stop conditions and burden budget;
- owner feedback question;
- review decision: continue, modify, stop, or inconclusive.

N-of-1 methods are useful only when repeated measurements, a sufficiently stable/reversible intervention, and meaningful outcome timing are possible. [S46](research/primary-sources.md#S46) Reporting should follow disciplined protocols rather than claiming causal certainty from one before/after observation. [S47](research/primary-sources.md#S47)

For many personal goals, the honest output is “suggestive but confounded.” Avoid randomization when withholding an intervention is unsafe or when the burden exceeds the likely learning value.

## Human evaluation

Owner feedback is scarce and costly. Use it deliberately:

- low-friction correction at the point of error;
- periodic sampled review rather than rating every response;
- explicit usefulness/annoyance controls for proactive actions;
- post-intervention review tied to a hypothesis;
- incident review for trust failures;
- never infer that lack of complaint equals benefit.

## Build now

- Unit/integration/contract/policy tests.
- Deterministic fake model and fake capability adapters.
- Event/policy replay with virtual clock and disabled side effects.
- Small model/prompt regression suite with repeated samples and cost accounting.
- Camera calibration set and monthly restore test.

## Design for

- Inspect AI-based provider-neutral suites, private withheld datasets, failure injection, canary comparison, and intervention-analysis notebooks/reports.

## Defer

- A giant benchmark platform, synthetic “digital twin” claims, automated causal conclusions, and promotion based only on a model-graded quality score.
