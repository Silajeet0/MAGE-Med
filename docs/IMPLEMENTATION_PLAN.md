# MAGE-Med 25-Milestone Implementation Plan

## 1. Delivery rules

Milestones are sequential. Implement only the active milestone plus unavoidable dependencies, preserve earlier contracts, and update `docs/PROGRESS.md` after each prompt. A milestone passes only when its implementation is connected, its acceptance criteria are demonstrated, relevant tests and checks actually pass, and limitations are recorded. Unit mocks cannot satisfy genuine MCP, A2A, local-model, or end-to-end gates.

The plan builds one vertical path around deterministic synthetic data. It does not authorize application scaffolding during Milestone 1.

## 2. Milestones and acceptance criteria

### Milestone 1 — Final scope and architecture documentation

**Scope:** Establish the final two-modality PoC contract and delivery sequence.

**Acceptance criteria:**

- `AGENTS.md` defines exactly two patient modalities, mandatory technologies, safety constraints, permissions, tests, dependency rules, incremental delivery, and strict definition of done.
- `docs/POC_SCOPE.md`, `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_PLAN.md`, and `docs/PROGRESS.md` exist and agree.
- Mermaid documents the architecture and workflow.
- The canonical end-to-end demonstration, all 25 milestones, their acceptance criteria, and deferred features are documented.
- Removed technologies appear only as exclusions/deferred context and are not required by architecture, milestones, or acceptance gates.
- No application code or scaffolding is created.

### Milestone 2 — Reproducible repository and quality scaffold

**Scope:** Create the minimum Python/TypeScript project skeleton, configuration, and documented commands.

**Acceptance criteria:**

- Python 3.11+ backend and React/TypeScript/Vite/Tailwind frontend skeletons start with health/status pages only.
- Direct dependencies are justified and pinned; reproducible lockfiles and `.env.example` are committed.
- Formatter, linter, type-check, test, and frontend build commands are configured and pass.
- No empty service forest, clinical feature stub, fake metric, or fake integration is added.

### Milestone 3 — Shared contracts and domain vocabulary

**Scope:** Define versioned Pydantic/wire contracts for identifiers, two modalities, provenance, assertions, errors, and service status.

**Acceptance criteria:**

- Contracts represent source locators, clinical/recorded/ingested times, assertion class, synthetic status, and verification/review state.
- The modality enum contains only `structured_clinical_data` and `unstructured_clinical_text`.
- Invalid versions, timestamps, identifiers, and assertion transitions are rejected by tests.
- OpenAPI exposes stable typed error and health contracts.

### Milestone 4 — SQLite operational persistence

**Scope:** Add migrations and repositories for imports, supported patient records, documents, provenance, workflows, artifacts, audit, and review state.

**Acceptance criteria:**

- Migrations apply to an empty database and upgrade through the current revision; foreign keys and intended indexes are enabled.
- Repository tests cover transactions, idempotency keys, uniqueness, patient scoping, and rollback.
- Clinical records link to immutable source/provenance rows; Neo4j and FAISS metadata can reference projection versions.
- No clinical schema is created ad hoc at application startup.

### Milestone 5 — FHIR R4 local Bundle ingestion

**Scope:** Validate and import the supported FHIR R4 domains from local JSON
Bundles or individual-resource JSON without a server. `DocumentReference`
embedded text enters the clinical-text modality rather than creating a modality.

**Acceptance criteria:**

- Supported resources cover Patient, Encounter, Condition, laboratory Observation, MedicationRequest, AllergyIntolerance, and DocumentReference.
- Base structural validation and project invariants are distinguished from full profile/implementation-guide conformance; no certification is claimed.
- Bundle/resource IDs, coding, units, values, clinical/recorded times, references, and original source checksum/locator are preserved.
- `entry.fullUrl`, `urn:uuid` and relative references resolve uniquely; unresolved or ambiguous references are reported rather than guessed.
- Deterministic synthetic fixtures and generated test cases cover valid, corrupt,
  missing, duplicate, conflicting, unsupported, bad-reference, and cross-patient cases.
- Imports are atomic and idempotent; unsupported resources are reported, not silently coerced.
- CLI and bounded upload API tests prove size/type/path handling, status lookup, rollback, stable updates, and no external content fetch.
- FHIR is labeled as an exchange format, not a modality.

### Milestone 6 — Alternative structured CSV/JSON adapters

**Scope:** Add explicit optional mappings for the same structured domains.

**Acceptance criteria:**

- Versioned mapping specifications produce the same normalized contracts as FHIR ingestion.
- Required columns/fields, timestamps, codes, units, patient identifiers, and mapping errors are validated.
- Re-import is deterministic/idempotent and provenance identifies adapter/mapping version.
- No unsupported domain or modality is introduced.

### Milestone 7 — Unstructured clinical text ingestion

**Scope:** Ingest TXT, CSV, JSON, and FHIR R4 `DocumentReference` text.

**Acceptance criteria:**

- Consultation, history, progress, and narrative fixtures enter the unstructured-text modality with patient linkage and provenance.
- Embedded and allowlisted local linked content are supported; remote, escaping, missing, oversized, or unsafe links fail safely.
- Encoding, empty content, duplicates, ambiguous patient linkage, and malformed metadata have tests.
- Original content/checksum and document/source locators are retained without logging note text.
- Cleaned text, optional sections, stable chunks, exact offsets, and checksums remain traceable to original notes.
- Patient-scoped retrieval returns linked structured summaries and notes; wrong-patient mappings and note reads fail safely.

### Milestone 8 — Synthetic dataset and import pipeline

**Scope:** Assemble the canonical fictional longitudinal patient and deterministic import workflow.

**Acceptance criteria:**

- A manifest labels every record and note synthetic and records fixture version/checksums/licenses.
- The fixture includes both modalities, temporal history, at least one contradiction, missing information, and `DocumentReference` linkage without implying a real person.
- A documented command imports from empty state reproducibly and a second run creates no duplicates.
- Tests prove patient isolation with at least one additional fictional patient.

### Milestone 9 — Neo4j multi-tier schema and safe access

**Scope:** Define constraints, indexes, tier semantics, and an allowlisted parameterized query layer.

**Acceptance criteria:**

- Patient, biomedical concept, reference evidence, hypothesis/review, and provenance/operations tiers are distinguishable.
- Stable IDs, assertion classes, patient scope, time, and provenance are mandatory on relevant nodes/relationships.
- Constraints and idempotent upserts are tested against a real Neo4j test service.
- The API rejects arbitrary Cypher and cross-patient queries.

### Milestone 10 — Patient graph projection and temporal queries

**Scope:** Project normalized structured records and text metadata/assertions into Neo4j.

**Acceptance criteria:**

- Projection is deterministic, idempotent, versioned, and rebuildable from SQLite.
- Timeline queries preserve event versus recorded time, missingness, negation, contradictions, and source IDs.
- Cross-patient isolation and stale projection detection are integration-tested.
- Projection failure does not corrupt operational truth and reports a degraded state.

### Milestone 11 — Reference corpus ingestion

**Scope:** Create a small legally usable reference corpus and its graph projection.

**Acceptance criteria:**

- Each document/chunk records title, source, version/date, section/page if available, license, checksum, and exact text span.
- Corpus records are visibly separate from patient data and are reproducibly ingested/versioned.
- Reference concept/evidence graph links retain provenance and do not overstate association as causation.
- Unsupported licenses, malformed documents, and duplicate/version-conflict cases are reported.

### Milestone 12 — Pretrained embeddings and FAISS indexing

**Scope:** Embed reference chunks and build a versioned local FAISS index.

**Acceptance criteria:**

- The pretrained transformer model name, immutable revision, task, license, preprocessing, dimensions, normalization, and runtime are recorded.
- Index manifest binds corpus, chunker, embedding, FAISS settings, and artifact checksum.
- Build/search tests use actual model inference when weights are available and otherwise report a blocked integration gate; no canned vectors satisfy acceptance.
- Incompatible, corrupted, or stale indexes fail safely; tests do not silently download weights.

### Milestone 13 — Deterministic vector retrieval baseline

**Scope:** Expose source-aware reference retrieval without an LLM.

**Acceptance criteria:**

- Queries return exact document/chunk IDs, text spans, native similarity scores, corpus/index versions, and filters.
- Stable fixture queries test ranking, ties, no-result, stale-index, and unavailable-model/index behavior.
- Scores are labeled retrieval similarity, not probability or clinical confidence.
- Measured baseline results are recorded through the evaluation contract.

### Milestone 14 — Hybrid GraphRAG retrieval

**Scope:** Fuse structured constraints, safe graph traversal, and FAISS results.

**Acceptance criteria:**

- Fusion is deterministic/configured and preserves each candidate's graph/vector/structured contribution and source IDs.
- Results separate supporting, contradicting, stale, and missing evidence.
- Patient concepts are minimized and authorized before reference retrieval.
- Tests compare the hybrid retriever with the vector baseline and record actual results without superiority claims.

### Milestone 15 — Local Ollama-compatible generation adapter

**Scope:** Add schema-constrained local generation with capability and failure reporting.

**Acceptance criteria:**

- Configuration is local by default and records endpoint, real model identity, parameters, prompt/schema versions, latency, and status without secrets.
- Structured output is Pydantic-validated and restricted to supplied source IDs.
- Unavailable, timeout, malformed, unsupported-model, and citation-reference errors are tested.
- No canned response is returned when inference is unavailable; no training or fine-tuning occurs.

### Milestone 16 — Custom bounded Agent Harness

**Scope:** Implement the deterministic workflow state machine and policy boundary.

**Acceptance criteria:**

- State transitions match the architecture and persist idempotently with correlation IDs.
- Patient/purpose scope, tool/agent allowlists, max steps/time/tokens/tool calls, bounded retry, cancellation, and abstention are enforced.
- Policy denial occurs before model/tool access; failures cannot transition directly to acceptance.
- Unit tests cover allow/deny, budgets, retry exhaustion, timeout, cancellation, resume/idempotency, and audit events.

### Milestone 17 — One genuine Clinical Context MCP server

**Scope:** Implement the single read-only MCP tool server and harness client.

**Acceptance criteria:**

- A supported MCP SDK provides real server/client initialization, discovery, schema negotiation, and invocation.
- Narrow tools return authorized timeline/record/note context with provenance; the server independently rechecks patient and operation scope.
- Protocol integration tests cover discovery, success, malformed input, unauthorized/cross-patient denial, unavailable server, and trace correlation.
- No arbitrary SQL/Cypher, filesystem/network, shell, mutation, approval, prescription, or ordering tool exists.

### Milestone 18 — Structured Clinical Data Agent

**Scope:** Implement the first specialized agent under harness control.

**Acceptance criteria:**

- The agent can access only harness-authorized structured context via the MCP path and returns a versioned schema artifact.
- Temporal summaries cite exact record/source IDs and distinguish missing, historical, contradictory, and current information.
- It cannot call unapproved tools, expand patient scope, create a final diagnosis, or approve itself.
- Deterministic fixtures test grounded output, abstention, budget enforcement, and unavailable-model behavior.

### Milestone 19 — Clinical Text Agent

**Scope:** Implement the second specialized agent under harness control.

**Acceptance criteria:**

- The agent returns source-linked statements from authorized notes with negation, temporality, uncertainty, and experiencer preserved.
- Each claim cites an exact document/source locator; unsupported claims fail verification.
- Prompt-injection fixtures cannot expand tools/scope or override system policy.
- Tests cover conflicting notes, missing context, abstention, budgets, and unavailable-model behavior.

### Milestone 20 — Independent A2A Evidence Agent

**Scope:** Implement the third specialized agent as a separately running genuine A2A service.

**Acceptance criteria:**

- A supported A2A SDK/protocol exposes a versioned Agent Card/capability and real task/status/artifact exchange across a process boundary.
- Inputs default to a minimized question and non-identifying concepts; authorization and constraints propagate and are rechecked.
- Structured output contains exact evidence IDs/spans, ranks/scores, supporting/contradicting groups, limitations, and corpus/index versions.
- Protocol tests cover discovery, success, failure, timeout/cancellation, malformed artifact, scope denial, and trace correlation. Direct function calls or ad hoc REST do not pass.

### Milestone 21 — Three-agent workflow, verification, and review API

**Scope:** Connect all three agents, hybrid retrieval, optional local generation, deterministic verification, and authenticated review.

**Acceptance criteria:**

- One harness workflow invokes exactly the three defined agents and no implicit fourth agent.
- Artifact schemas, source existence, citation spans, patient scope, and policy outcomes are verified before composition.
- The packet shows supporting, contradicting, missing, and uncertain information and stays `pending_clinician_review`.
- Authenticated accept/reject actions are valid only from pending state and create immutable audit records; no clinical action endpoint exists.
- Failures and degraded dependencies remain visible and cannot produce fake success.

### Milestone 22 — Clinician workbench frontend

**Scope:** Build the functional React workbench against real APIs.

**Acceptance criteria:**

- The UI provides synthetic patient selection, timeline, structured records, note/source view, evidence/provenance, agent/tool trace, service status, and explicit review action.
- Synthetic data, AI-generated hypotheses, source verification, uncertainty, pending review, and unavailable/degraded services are visibly labeled.
- Loading, empty, invalid, unauthorized, contradiction, failure, and cancellation states are covered.
- Review state comes from the audited backend; accessibility checks, TypeScript checks, component tests, and production build pass.

### Milestone 23 — MLflow and privacy-safe lightweight tracing

**Scope:** Track reproducibility artifacts and correlate the distributed workflow without logging clinical content.

**Acceptance criteria:**

- MLflow records dataset/corpus, transformation, graph, embedding/index, retriever, prompt/model, workflow/policy/tool contracts, metrics, artifacts, and explicit outcome status from actual runs.
- Correlation IDs cross API, harness, MCP, A2A, retrieval, generation, and review.
- Automated tests prove patient/note text, prompts containing clinical content, secrets, and raw retrieved spans are absent from general traces and MLflow metadata.
- Unavailable tracking degrades visibly without falsifying run persistence.

### Milestone 24 — Reproducible evaluation and safety suite

**Scope:** Evaluate baselines and the integrated workflow on versioned synthetic cases.

**Acceptance criteria:**

- Evaluation manifests pin inputs, expected sources, configs, model/index/corpus/workflow versions, and random seeds where relevant.
- Actual measurements cover retrieval/source recall or another justified metric, citation/provenance coverage, policy denials, patient isolation, abstention, review-state correctness, latency, and errors.
- Structured/vector baselines and hybrid/agent workflow are compared with failure cases; no unsupported clinical performance or superiority claim is made.
- Reports distinguish `run`, `failed`, `blocked`, `not_applicable`, and `not_run` and are reproducible from a documented command.

### Milestone 25 — End-to-end demonstration and research release candidate

**Scope:** Verify the canonical demonstration and package an honest reproducible PoC release candidate.

**Acceptance criteria:**

- From clean documented setup, the canonical synthetic patient traverses both modalities, SQLite, Neo4j, FAISS, actual pretrained embeddings, hybrid GraphRAG, all three agents, genuine MCP, independent genuine A2A, actual local Ollama-compatible inference, review, audit, MLflow, and tracing.
- Protocol and end-to-end tests use real local processes/services; all source/citation links resolve and no cross-patient or unauthorized access succeeds.
- A service outage produces the documented degraded/blocked state, never fabricated output.
- All configured lint, type, unit, integration, security, frontend, evaluation, and build checks pass with exact results recorded; any unmet required gate means the milestone is not done.
- Documentation includes setup, demo, limitations, licenses, model/resource requirements, evaluation facts, and the clinician-supervised research-only boundary.

## 3. Cross-milestone acceptance invariants

Every milestone must preserve:

- exactly two patient-data modalities;
- source-level provenance and patient isolation;
- synthetic-by-default data and no patient content in general telemetry;
- exactly three specialized agents, one genuine MCP server, and one independent A2A Evidence Agent when those milestones are reached;
- no fabricated outputs, findings, citations, approvals, metrics, or test results;
- no training/fine-tuning or autonomous clinical action;
- honest unavailable/degraded/blocked states;
- pinned, licensed, justified dependencies and reproducible commands;
- updated `docs/PROGRESS.md` with actual verification.

## 4. Deferred work

Deferred work is listed in `POC_SCOPE.md`. It is not acceptance work for these milestones and must not be introduced opportunistically. Any proposal to add modalities, remote clinical systems, broader infrastructure, more agents/tools, real datasets, model training, production deployment, or clinical actions requires a new explicit scope decision and architectural review.
