# MAGE-Med Proof-of-Concept Scope

## 1. Purpose

MAGE-Med (Multimodal Agentic Graph Ecosystem for Medicine) is a reproducible, research-grade, clinician-supervised clinical decision-support Proof of Concept. It demonstrates how bounded agents, a multi-tier knowledge graph, hybrid retrieval, and local language-model generation can organize synthetic longitudinal clinical information and reference evidence into a source-grounded review packet.

It does not diagnose, prescribe, order treatment, replace a clinician, claim clinical validation, or target production hospital deployment.

## 2. Fixed interpretation of “multimodal”

The platform supports exactly two patient-data modalities.

### 2.1 Structured clinical data

Included domains:

- patients;
- encounters;
- conditions;
- laboratory observations;
- medications;
- allergies.

The primary ingestion format is a local FHIR R4 JSON Bundle. Optional adapters may accept CSV or JSON when their mappings are explicit and versioned.

FHIR R4 is a healthcare interoperability and exchange format, not a clinical modality. A single FHIR Bundle can carry structured resources and `DocumentReference` resources associated with unstructured text; each item is classified by its clinical content, not by its container.

### 2.2 Unstructured clinical text

Included document types:

- consultation notes;
- clinical histories;
- progress notes;
- clinical narratives.

Supported formats are TXT, CSV, JSON, and text embedded in or safely linked from FHIR R4 `DocumentReference`. Remote or unsafe links are rejected by default; locally permitted links must resolve within an allowlisted import root and retain a source locator and checksum.

### 2.3 Reference knowledge is not a modality

External medical literature, terminology, and biomedical knowledge form a reference knowledge corpus. This corpus supports evidence retrieval and concept linkage but is not patient data and is not a third modality. Graph projections, vector embeddings, extracted assertions, prompts, and agent artifacts are derived representations, not modalities.

## 3. Required capabilities and technologies

| Capability | Required technology or constraint |
| --- | --- |
| Backend and contracts | Python 3.11+, FastAPI, Pydantic v2 |
| Operational persistence | SQLite with migrations |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Knowledge fabric | Neo4j multi-tier knowledge graph |
| Vector retrieval | FAISS |
| Embeddings | Version-pinned pretrained transformer embeddings |
| Retrieval/synthesis | Hybrid GraphRAG with exact source identifiers |
| Generation | Local Ollama-compatible LLM; honest unavailable state |
| Agents | Exactly three specialized clinical agents |
| Orchestration | Custom bounded Agent Harness |
| Tool protocol | One genuine MCP server |
| Agent protocol | One independently running A2A Evidence Agent |
| Operations | MLflow and lightweight privacy-safe tracing |
| Quality | Automated tests and reproducible evaluation |

The three specialized agents are:

1. **Structured Clinical Data Agent** — creates a temporal, source-linked summary of authorized structured records.
2. **Clinical Text Agent** — extracts and summarizes source-linked statements while retaining negation, temporality, uncertainty, and experiencer.
3. **Evidence Agent** — independently deployed over A2A; retrieves and returns bounded, source-linked reference evidence.

The custom harness orchestrates these agents and deterministically validates/composes their artifacts. It is not a fourth agent.

## 4. Intended users and use case

The intended user is a researcher or clinician evaluating the PoC with synthetic or explicitly approved local data. The primary use case is review of a single patient's longitudinal context and a clinician-entered evidence question. The system gathers structured history, analyzes associated narrative text, retrieves external reference evidence, shows contradictions and gaps, and presents an AI-generated draft that requires explicit clinician review.

## 5. End-to-end demonstration

The canonical demonstration uses one clearly labeled synthetic patient and runs only against versioned local fixtures and services:

1. An authenticated demo clinician imports a local FHIR R4 Bundle containing supported structured resources and a `DocumentReference`, with associated unstructured note text.
2. Validation rejects unsupported or malformed content without partially corrupting state. Accepted records enter SQLite with resource-level provenance and modality labels.
3. A deterministic projection loads traceable patient assertions into the patient/provenance tiers of Neo4j. Reference concepts and a small licensed or redistributable reference corpus remain in separate tiers.
4. Reference documents are chunked, embedded with a pinned pretrained transformer, and indexed in a versioned FAISS index.
5. The clinician selects the synthetic patient and enters a bounded clinical evidence question; no diagnosis or treatment action is requested.
6. The Agent Harness creates an auditable workflow, enforces patient/purpose scope and budgets, and invokes the one real MCP server for read-only patient context.
7. The Structured Clinical Data Agent returns a source-linked temporal summary. The Clinical Text Agent returns source-linked extracted statements with negation and uncertainty preserved.
8. The harness sends a minimized, non-identifying evidence question to the independently running Evidence Agent through genuine A2A task exchange.
9. The Evidence Agent performs bounded hybrid retrieval across Neo4j reference tiers and FAISS, returning exact corpus/document/chunk IDs, supporting and contradicting evidence, and missing-evidence signals.
10. If the configured local Ollama-compatible model is available, the harness produces a schema-valid draft synthesis grounded only in authorized artifacts; otherwise it displays a real `unavailable` state and does not substitute canned output.
11. Verification checks every displayed citation against the retrieved span and marks unsupported claims or schema failures. The UI shows the patient timeline, notes, evidence, provenance, agent/tool trace, uncertainty, and service status.
12. The draft remains `pending_clinician_review` until the authenticated user explicitly accepts or rejects it. The backend records the action in an audit trail. No treatment, prescription, medical order, or final diagnosis is emitted.
13. The run configuration and actual evaluation measurements are recorded in MLflow, while lightweight traces correlate components without storing patient text.

The demo fails honestly if required services are unavailable. Unit mocks do not satisfy the protocol or end-to-end demonstration.

## 6. Data and safety boundaries

- Committed and default demonstration data are deterministic, obviously fictional, and labeled `synthetic` in manifests, API responses, UI, traces, and evaluations.
- Real patient data is not required. Any future local use requires explicit authorization and a privacy/security review; no patient content may leave the local deployment by default.
- All facts and derived assertions retain source IDs, times, transformations, assertion class, and verification state.
- Generated summaries and hypotheses are advisory drafts, visibly uncertain and pending authenticated clinician review.
- The PoC contains no prescribing, ordering, autonomous diagnosis, treatment initiation, or automatic approval tool or endpoint.
- Missing, contradictory, stale, and low-quality evidence remains visible; the system may abstain.

## 7. Explicit exclusions

The PoC does not require or implement:

- a FHIR server (local FHIR R4 JSON import is sufficient);
- DICOM, PACS, Orthanc, and all imaging workflows or infrastructure;
- distributed production orchestration or event-streaming infrastructure;
- an alternative production relational database;
- model training, fine-tuning, or clinical calibration claims;
- autonomous diagnosis, prescribing, treatment, medical orders, or emergency triage coverage;
- production deployment, high availability, enterprise identity federation, billing, regulatory certification, or hospital-system integration.

These exclusions must not appear as mandatory dependencies, milestones, demo steps, or acceptance gates.

## 8. Deferred features

The following are intentionally deferred beyond the 25-milestone PoC and require a new scope decision:

- additional clinical modalities or unsupported FHIR resource domains;
- remote FHIR APIs and bidirectional write-back;
- real-world dataset onboarding and formal data-governance workflows;
- broader terminology services, corpus licensing pipelines, and curator interfaces;
- additional MCP servers, A2A agents, or autonomous/general-purpose agents;
- model training/fine-tuning, prospective clinical studies, clinical validation, and calibration;
- multi-tenant deployment, enterprise SSO, advanced RBAC, key management, high availability, and disaster recovery;
- production observability, capacity engineering, and regulated deployment controls;
- clinical actions of any kind.

## 9. PoC success criteria

The PoC succeeds when the canonical synthetic-patient demonstration reproducibly traverses both modalities; preserves provenance; exercises SQLite, Neo4j, FAISS, a real local embedding model, hybrid GraphRAG, all three agents, the one genuine MCP server, the independent A2A Evidence Agent, a real Ollama-compatible availability/inference path, clinician review, audit, MLflow, and privacy-safe tracing; and passes the test and evaluation gates in the implementation plan.

Success does not imply clinical efficacy, safety in practice, compliance certification, production readiness, or superiority over baselines. Results must be actual measurements, not fabricated or assumed values.
