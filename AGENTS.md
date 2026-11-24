# AGENTS.md — MAGE-Med Repository Instructions

> **Scope:** These instructions apply to the entire repository. Read them before every change. A more-specific `AGENTS.md` may add local rules but may not weaken the scope, provenance, security, or clinical-safety requirements here.
>
> **Mission:** Build a reproducible, research-grade, clinician-supervised clinical decision-support **Proof of Concept (PoC)** named MAGE-Med: Multimodal Agentic Graph Ecosystem for Medicine. It is not an autonomous doctor, a clinically validated product, or a production hospital system.

## 1. Final scope and vocabulary

MAGE-Med uses exactly **two clinical patient-data modalities**:

1. **Structured clinical data:** patients, encounters, conditions, laboratory observations, medications, and allergies. The primary exchange format is local **FHIR R4 JSON Bundle** files. CSV and JSON adapters are optional alternatives.
2. **Unstructured clinical text:** consultation notes, clinical histories, progress notes, and clinical narratives. Supported inputs are TXT, CSV, JSON, and text embedded in or linked by FHIR R4 `DocumentReference` resources.

FHIR R4 is an interoperability and exchange format, **not a modality**. External medical literature, terminology, and biomedical knowledge are a **reference knowledge corpus**, not a third patient modality. Derived graph nodes, embeddings, agent messages, and model outputs are representations or artifacts, not new modalities.

Mandatory technologies are:

- Python 3.11+, FastAPI, Pydantic v2, and SQLite;
- React, TypeScript, Vite, and Tailwind CSS;
- Neo4j multi-tier knowledge graph;
- FAISS vector retrieval and pretrained transformer embeddings;
- hybrid GraphRAG and a local Ollama-compatible LLM;
- exactly three specialized clinical agents: Structured Clinical Data Agent, Clinical Text Agent, and Evidence Agent;
- a custom bounded Agent Harness;
- one genuine protocol-compatible MCP server;
- the Evidence Agent as one independently running, protocol-compatible A2A service;
- MLflow, lightweight privacy-safe tracing, automated testing, and evaluation.

Out of scope for this PoC are a mandatory FHIR server; DICOM, PACS, Orthanc, and all imaging workflows; Kubernetes; Kafka; PostgreSQL; model training or fine-tuning; autonomous diagnosis, prescribing, treatment, or medical orders; and production hospital deployment. Do not introduce these as required dependencies or acceptance criteria.

The detailed sources of truth are `docs/POC_SCOPE.md`, `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_PLAN.md`, and `docs/PROGRESS.md`.

## 2. Operating contract

1. **Inspect before editing.** Read this file, the four source-of-truth documents above, applicable code and tests, and the Git status if a repository exists. Preserve unrelated user work.
2. **Implement one milestone at a time.** Follow the 25 milestones in `docs/IMPLEMENTATION_PLAN.md`. Add only the current vertical slice and its necessary dependencies; do not pre-build later milestones.
3. **Keep every slice connected.** Features must use established application boundaries, expose a useful interface, include tests, and update documentation. Do not create disconnected demonstrations or empty architecture trees.
4. **Never disguise a stub.** Fixtures, simulations, placeholders, unavailable services, and TODOs must be explicit. Never fabricate patient records, medical findings, model/LLM output, MCP or A2A traffic, citations, clinician approvals, metrics, or test/evaluation results.
5. **Use synthetic data by default.** The PoC must build, test, and demonstrate without real patient data. Synthetic records and narratives must be obviously fictional and labeled in manifests, APIs, evaluations, and the UI.
6. **No training.** Only supported pretrained embedding models and local LLM inference may be integrated. Record versions, licenses, preprocessing, and runtime requirements.
7. **No clinical autonomy.** All generated hypotheses and summaries remain pending clinician review. The system must not expose endpoints or tools that prescribe, order, treat, or establish a final diagnosis.
8. **Report reality.** State exact commands and outcomes. A missing model, service, credential, or test environment is `blocked`, `unavailable`, `degraded`, or `not run`—never a hard-coded success.
9. **Preserve contracts.** Do not silently break public APIs, Pydantic schemas, graph semantics, SQLite migrations, persisted indexes, agent messages, or protocol contracts. Document and test necessary migrations.
10. **Prefer local, open, and CPU-capable operation.** Avoid paid dependencies. Make resource-heavy components configurable, disclose downloads and licenses, and provide honest degraded states.

When requirements conflict, follow: system/developer instructions and the current user request; clinical safety/privacy rules; current milestone acceptance criteria; established contracts and architectural decisions; the four source-of-truth documents; then repository convention.

## 3. Architecture boundaries

| Boundary | Responsibility | Required implementation |
| --- | --- | --- |
| Ingestion | Validate and normalize the two modalities | Local FHIR R4 Bundle parser plus optional CSV/JSON/TXT adapters |
| Application/API | Authentication boundary, patient scope, workflow and review endpoints | FastAPI + Pydantic |
| Operational store | Normalized records, provenance, workflows, audit, review state | SQLite with migrations |
| Knowledge fabric | Patient, reference, evidence/hypothesis, and provenance tiers | Neo4j with parameterized queries |
| Retrieval | Reference-corpus chunks, embeddings, similarity, graph traversal, fusion | FAISS + pretrained transformer embeddings + hybrid GraphRAG |
| Generation | Schema-constrained, source-grounded local generation | Ollama-compatible local adapter |
| Control plane | Policy, state, budgets, routing, verification, review | Custom bounded Agent Harness |
| Tool plane | Narrow patient-context reads | Exactly one genuine MCP server and protocol client |
| Agent plane | Independent evidence research | Evidence Agent over genuine A2A |
| Clinician UI | Patient selection, timeline, notes, evidence, trace, review | React + TypeScript + Vite + Tailwind |
| Operations | Versioned evaluations, runs, status, privacy-safe traces | MLflow + lightweight tracing |

The harness is the only workflow orchestrator. MCP is transport, not authorization. A2A is delegation transport, not authorization. SQLite is the operational source of truth; Neo4j and FAISS are rebuildable, versioned projections. Patient clinical data and the reference corpus remain logically and physically distinguishable.

Exactly three specialized agents are allowed in scope:

- **Structured Clinical Data Agent:** builds source-linked temporal summaries from authorized normalized structured records.
- **Clinical Text Agent:** extracts source-linked statements from authorized notes while preserving negation, uncertainty, temporality, and experiencer.
- **Evidence Agent:** runs as an independent A2A service and retrieves reference-corpus evidence for a bounded, de-identified question.

The harness may deterministically compose and validate their artifacts into a clinician-review packet; that composer is not another agent. Do not add general-purpose or autonomous agents without an explicit scope revision.

## 4. Expected repository shape

Converge only as milestones require; do not scaffold empty directories:

```text
apps/
  backend/                 # FastAPI composition and routes
  frontend/                # React clinician workbench
services/
  ingestion/               # FHIR R4 and alternative local adapters
  knowledge_graph/         # Neo4j schema, projections, safe queries
  retrieval/               # FAISS, embeddings, and hybrid GraphRAG
  agent_harness/           # policy, state machine, verification, review
  mcp/                     # the single genuine MCP server/client
  a2a_evidence_agent/      # independent genuine A2A service
  evaluation/              # datasets, baselines, metrics, reports
packages/
  shared_schemas/          # versioned Python/wire contracts
data/
  synthetic/               # clearly labeled fictional fixtures
  reference/               # licensed metadata/corpus manifests
tests/                     # unit, integration, protocol, safety, E2E
docs/                      # scope, architecture, plan, progress, ADRs
```

Keep business logic out of route handlers and UI components. Avoid circular imports, duplicated domain rules, arbitrary framework abstractions, and direct agent access to databases or unrestricted tools.

## 5. Coding standards

### Python

- Target Python 3.11+; use type hints, small cohesive modules, and explicit dependency injection.
- Use Pydantic v2 at trust boundaries and typed domain objects internally. Reject malformed or ambiguous input with structured errors.
- Use `snake_case`, concise docstrings for non-obvious public APIs, and comments that explain decisions.
- Use configured `ruff`, static type checks, and `pytest`. Business logic must be independently testable from FastAPI.
- Use migrations for SQLite schema changes; enable foreign keys and intentional indexes. Do not create schemas ad hoc at every startup.

### TypeScript

- Enable strict mode; avoid `any` unless isolated and justified.
- Use generated or shared API types where practical, accessible semantic components, explicit loading/empty/error/unauthorized/degraded states, and reusable UI logic.
- Use `camelCase` internally while preserving external wire-format names.
- Run the configured formatter, linter, type check, tests, and production build.

### Cross-cutting

- Centralize configuration in environment variables with safe defaults and a current `.env.example`. Never commit secrets, tokens, real records, or `.env`.
- Pin direct dependencies and commit reproducible lockfiles. A dependency must serve the current milestone, have a compatible license, and not duplicate an established capability.
- Use stable identifiers, UTC ISO 8601 timestamps, explicit schema versions, deterministic serialization where artifacts are hashed, and structured exceptions.
- Verify version-sensitive FHIR R4, MCP, A2A, Ollama, MLflow, Neo4j, and FAISS APIs against official documentation before implementation; never invent protocol behavior.

## 6. Data, provenance, and knowledge semantics

Every ingested or derived clinical assertion must retain:

- stable internal ID and patient scope;
- modality (`structured_clinical_data` or `unstructured_clinical_text`);
- source type, source file/import ID, original FHIR resource type and ID where applicable, and resolvable source locator;
- event/clinical time, recorded time, ingestion time, and timezone/precision when known;
- original value/text or a content hash plus an immutable source reference;
- terminology system, code, display, version, unit, and reference range when supplied;
- transformation/parser version and actor/run ID;
- assertion class and verification state.

Required assertion classes are `observed`, `extracted`, `model_inferred`, `hypothesized`, `clinician_confirmed`, and `clinician_rejected`. Keep missing, explicitly negative, uncertain, historical, contradictory, and superseded facts distinct. Preserve source units; any conversion must retain the original and record the conversion rule. Never infer patient identity from filenames or merge uncertain identities.

FHIR R4 Bundles remain traceable to their resources; `DocumentReference` text must record whether it was embedded or locally linked and must reject unsafe or unresolved links. Optional CSV/JSON mappings must be explicit, versioned, deterministic, and idempotent.

Neo4j tiers are logically separated: patient observations; reference biomedical concepts; reference literature/guidelines; hypotheses/review; provenance/operations. Every clinically relevant node/relationship requires stable provenance. Similarity or association is not causation. Untrusted LLM text may not become arbitrary Cypher; use allowlisted parameterized query templates and patient-scope checks.

Reference documents require corpus/document/chunk IDs, title, source/publisher, version/date, section/page when available, license, checksum, ingestion version, and retrievable text span. A citation is valid only when its displayed claim is supported by the exact stored span. Automatically extracted reference relations remain unverified until curated.

## 7. Security, privacy, and clinical safety

- Treat this as a research PoC for clinician-supervised decision support only. Never claim clinical validation, regulatory clearance, production readiness, or comprehensive emergency coverage.
- Use synthetic data in committed fixtures, screenshots, demos, and tests. Real data requires explicit user authorization, an approved local data path, access controls, retention rules, and a documented privacy review; it must never be committed.
- Enforce authentication, least privilege, patient isolation, purpose of use, and operation scope server-side. UI filtering is not a security control.
- Do not send patient content to hosted LLMs, hosted embedding APIs, external search, analytics, or telemetry. The default inference and retrieval path is local.
- Redact or omit clinical text, identifiers, prompts, retrieved spans, and secrets from logs, traces, errors, MLflow metadata, and exports. Use synthetic IDs or hashes where correlation is needed.
- Treat files, reference documents, tool results, model output, and retrieved text as untrusted data. Defend against prompt injection with server-side policies, schemas, tool allowlists, content boundaries, and output verification.
- Generated summaries, hypotheses, evidence rankings, and suggested considerations must show their source and uncertainty and remain **pending clinician review**. Approval/rejection is an authenticated, explicit, audited backend action; it is never simulated in UI state.
- Absence of evidence is not negative evidence. On missing, conflicting, stale, or low-quality data, preserve uncertainty and abstain when required.

## 8. Agent and tool permissions

The custom harness owns workflow state, routing, patient and purpose scope, context minimization, agent/tool allowlists, max steps, timeouts, retries, cancellation, idempotency, token/tool budgets, schema validation, evidence verification, audit, and clinician-review transitions. Deterministic gates must not be delegated to an LLM.

Agents receive the minimum authorized context and cannot directly access SQLite, Neo4j, FAISS, the filesystem, the network, or Ollama outside harness-approved adapters. They cannot spawn agents, expand scope, approve their own output, or invoke prescribing/ordering/write tools.

The single MCP server exposes narrow, typed, read-only clinical-context tools. Both harness and server independently enforce patient/operation scope. It must not expose arbitrary SQL/Cypher, general filesystem/network access, shell execution, record mutation, or clinical actions. Use an official/supported MCP SDK and prove tool discovery, invocation, denial, and trace propagation over the real protocol.

The Evidence Agent is a separately started process/service with an Agent Card/capability declaration, genuine A2A task exchange, status transitions, structured evidence artifacts, failure/cancellation handling, authorization propagation, and trace correlation. It receives a minimized question and non-identifying clinical concepts by default—not a wholesale patient chart. It can query only the versioned reference corpus through bounded adapters. Prove the boundary with protocol-level tests; a Python call or custom REST endpoint labeled “A2A” is not acceptable.

## 9. Retrieval, generation, and evaluation integrity

- Pin the pretrained embedding model revision and record task, license, dimensions, normalization, chunking, hardware, and library versions. Tests must not silently download weights.
- Version FAISS indexes with corpus manifest, chunking, embedding, index type/settings, and checksum. Detect incompatible or stale indexes.
- Hybrid GraphRAG must preserve graph, vector, and structured retrieval contributions, source IDs, ranks/scores, temporal filters, contradictory evidence, and missing evidence. Scores are retrieval scores, not clinical probabilities.
- The local Ollama-compatible adapter must report real model identity, availability, parameters, prompt/schema versions, latency, and failure. Validate generated output against a schema and citations against retrieved sources. Never substitute canned text for unavailable inference.
- MLflow records actual configurations, artifacts, metrics, and status. Lightweight traces correlate API, harness, MCP, A2A, retrieval, and generation without patient content.
- Evaluations compare defined baselines with the hybrid workflow, include failure cases and safety/policy tests, and distinguish `run`, `failed`, `blocked`, `not_applicable`, and `not_run`. Never claim superiority without measured results.

## 10. Testing and acceptance gates

| Area | Minimum required evidence |
| --- | --- |
| Contracts | Valid/malformed/version tests for Pydantic, FHIR R4 subset, agent and protocol schemas |
| Ingestion | Determinism, idempotency, provenance, timestamps, missing fields, bad mappings, unsafe links |
| Storage/security | Migrations, constraints, patient isolation, unauthorized access, audit immutability |
| Knowledge graph | Tier separation, provenance, temporal/contradictory assertions, safe queries, rebuildability |
| Retrieval | Stable source IDs, index compatibility, deterministic fixtures, stale/missing/contradictory evidence |
| Agents/harness | Allow/deny policy, budgets, timeouts, retries, cancellation, abstention, review state, audit |
| MCP | Genuine discovery/invocation, server-side denial, malformed request, unavailable server, trace ID |
| A2A | Genuine discovery/task/artifact flow, independent process, failure/cancel states, scope propagation |
| API/UI | Contract, auth, patient scope, accessibility, degraded states, real backend review transition |
| Evaluation | Reproducible manifests, actual metrics, baselines, provenance/citation and policy-failure reporting |
| End to end | One synthetic patient traverses both modalities, retrieval, all three agents, review, and audit |

Run only commands verified to exist. Add regression tests with every fix. Integration tests may require explicitly started Neo4j, Ollama, MLflow, MCP, or A2A services; if unavailable, report the exact skipped/blocked gate. Mocks are acceptable for isolated unit tests but never satisfy protocol or end-to-end acceptance.

## 11. Strict definition of done

A milestone is done only when all of the following are true:

1. Its acceptance criteria in `docs/IMPLEMENTATION_PLAN.md` are demonstrably satisfied and no out-of-scope dependency was introduced.
2. The implementation is connected through established boundaries; no required behavior is a disguised stub, fake protocol, canned model result, fabricated citation, or UI-only state.
3. Relevant unit, integration, contract, security, and failure-path tests pass, or each unrun external-service gate is explicitly recorded as a blocker so the milestone remains incomplete.
4. Formatting, linting, type checking, tests, and builds configured for the affected code pass with exact results recorded.
5. Provenance, patient isolation, authorization, audit, uncertainty, degraded states, and clinician-review boundaries are enforced and tested.
6. Dependencies are justified, pinned, licensed for use, and reflected in lockfiles/configuration; no secret or real patient data is present.
7. `docs/PROGRESS.md` and any affected architecture, contract, evaluation, or decision document are updated with facts only.
8. The resulting slice can be reproduced from documented commands and versioned synthetic fixtures.

Do not call work “fully complete,” “production-ready,” “clinically validated,” “HIPAA-compliant,” or “regulator-approved” without independent evidence that is outside this PoC.

## 12. Incremental delivery and reporting

Before implementation, identify the current milestone, dependencies, affected contracts, risks, and test plan. During implementation, make focused reviewable edits and keep safety gates deterministic. After implementation, update `docs/PROGRESS.md` with milestone status, files changed, exact verification, synthetic/real data status, model/service availability, limitations, blockers, and next dependency.

For every milestone report:

1. milestone and intended scope;
2. implemented files and behavior;
3. exercised services/contracts;
4. exact commands and real outcomes, including skips;
5. safety/data/model status and review boundary;
6. blockers and limitations;
7. documentation updated;
8. readiness for the next milestone.

Do not commit, push, rewrite history, delete data, or perform external side effects unless explicitly requested. Material architectural deviations require a documented decision and explicit scope approval.

---

Build the smallest credible, source-grounded, end-to-end PoC. Its contribution is reproducible integration, bounded agent behavior, genuine protocols, traceable evidence, and honest evaluation—not infrastructure breadth.
