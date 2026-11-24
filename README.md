# MAGE-Med

MAGE-Med is a reproducible, clinician-supervised clinical decision-support research Proof of Concept. The current vertical slice includes the FastAPI/React foundation, canonical clinical contracts and SQLite models, real Neo4j readiness, both local clinical-data ingestion paths, and patient-scoped longitudinal reads.

It is not a diagnostic system, does not prescribe or order treatment, and is not intended for production hospital use. No clinical data or model-generated findings are included.

## Repository layout

```text
apps/backend/                 FastAPI composition, SQLite readiness, Alembic
apps/frontend/                React/Vite/Tailwind application shell and status page
packages/contracts/           Shared Python and TypeScript health/error contracts
services/ingestion/           Local FHIR R4 parsing and canonical normalization
services/knowledge_graph/     Bounded four-tier Neo4j schema and repository
data/synthetic/               Fixed-seed, explicitly synthetic FHIR fixtures
tests/smoke/                  Real backend-to-Neo4j smoke test
infrastructure/compose.yaml   One Neo4j Community service
scripts/smoke.sh              Live frontend → backend → Neo4j verification
docs/                         Scope, architecture, plan, and factual progress
```

Later retrieval, agent, protocol, and evaluation modules remain absent until
their owning milestones add connected behavior.

## Prerequisites

- Python 3.11 or newer (CI uses 3.11)
- [uv](https://docs.astral.sh/uv/)
- Node.js 24 or newer and npm 11
- Docker with the Compose plugin for real Neo4j readiness and smoke checks

Copy `.env.example` to `.env` and change the local example password when appropriate. Never commit `.env`, clinical data, database files, model weights, or generated indexes.

## Install

```bash
uv sync --all-packages
npm install
uv run alembic -c apps/backend/alembic.ini upgrade head
```

After lockfiles exist, use the reproducible path:

```bash
make bootstrap
make db-upgrade
```

## Run locally

Start the only required infrastructure container:

```bash
make neo4j-up
```

In separate terminals:

```bash
make backend
make frontend
```

Open `http://127.0.0.1:5173`. The frontend makes a real request to `GET /api/v1/health/ready`. Readiness is HTTP 200 only when both SQLite and Neo4j have answered fixed connectivity queries. Neo4j failure returns HTTP 503 with `not_ready`; no success is simulated.

Backend, frontend, and Neo4j host ports are configurable through the `MAGE_MED_*` variables documented in `.env.example`. The smoke test uses `MAGE_MED_SMOKE_PORT` and defaults to loopback port 18000 to avoid development-server collisions.

## Verification

```bash
make format-check
make lint
make typecheck
make test
make build
make smoke
```

`make smoke` starts a real backend process and invokes the frontend's typed API client. The same backend readiness request executes `SELECT 1` through SQLAlchemy and `RETURN 1 AS ready` through the official Neo4j driver. It then runs an independent Python integration assertion against the same real Neo4j service. The smoke target must fail when Neo4j is unavailable.

The real Neo4j smoke path also applies the idempotent multi-tier schema, verifies
repeat upserts do not duplicate nodes, and proves cross-patient relationship
creation is denied. See [graph design](docs/GRAPH_DESIGN.md). SQLite-to-graph
patient projection is implemented by the Milestone 10 synchronizer.

Milestone 10 now provides the explicit projection command:

```bash
uv run mage-med graph-sync --rebuild
```

It atomically rebuilds the canonical patient projection from SQLite, preserves
source provenance and source-supplied terminology only, and exposes bounded
patient-scoped repository reads. See [graph synchronization](docs/GRAPH_SYNC.md).

## API behavior

- `GET /api/v1/health/live` verifies that the HTTP process can respond.
- `GET /api/v1/health/ready` checks SQLite and Neo4j and returns HTTP 503 if either fails.
- Every response includes `X-Request-ID`; safe caller-provided IDs are propagated.
- Errors use a stable JSON envelope and do not expose connection details or credentials.
- Application access logs are structured JSON and exclude bodies and clinical content.
- Patient reads expose bounded timeline, observation, note, and source-provenance APIs through a common domain service; see [clinical data access](docs/CLINICAL_DATA_ACCESS.md).

## Local FHIR R4 import

Apply migrations and import the deterministic synthetic Bundle:

```bash
make db-upgrade
uv run mage-med import-fhir data/synthetic/fhir/r4/synthetic_patient_bundle.json \
  --dataset-id mage-med-synthetic-r4 --dataset-version 1 \
  --synthetic-seed 20261123
```

The same service is exposed as `POST /api/v1/import/fhir`; status is available at
`GET /api/v1/imports/{id}`. Imports require local JSON, use bounded uploads, make
no network fetches, preserve original resources and mappings, and report
unusable/unsupported entries. Validation covers FHIR R4 base model structure and
project invariants, not full profile conformance or certification. See
[FHIR ingestion](docs/FHIR_INGESTION.md) for exact behavior and a Synthea example.

## Clinical text import and retrieval

TXT, CSV, JSON, and embedded or allowlisted-local FHIR `DocumentReference` text
enter the unstructured clinical-text modality. The importer preserves original
and cleaned text, verified patient/encounter links, source metadata, and exact
chunk offsets/checksums. It does not fetch URLs or infer identity.

```bash
uv run mage-med import-text data/synthetic/clinical_text/synthetic_notes.json \
  --dataset-id mage-med-synthetic-clinical-text --dataset-version 1.0.0 \
  --synthetic --synthetic-seed 20261123
```

See [clinical text ingestion](docs/CLINICAL_TEXT_INGESTION.md) for schemas,
configured-root rules, limits, and retrieval APIs.

## Optional Ollama and MLflow guidance

Ollama and MLflow are mandatory in later project milestones but deliberately do not block Milestone 2 startup.

- If Ollama is installed, `ollama serve` exposes the default local endpoint at `http://localhost:11434`. No model is selected or downloaded in this milestone, and the application does not claim inference availability.
- MLflow is not installed into the application environment yet. For optional local exploration, run `uvx --from mlflow==3.18.0 mlflow server --host 127.0.0.1 --port 5000`. The application does not connect to or claim MLflow tracking until its owning milestone.

The corresponding optional URLs are documented in `.env.example`. Neither service sends or receives patient content in this milestone.

## Scope references

- [PoC scope](docs/POC_SCOPE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md)
- [Progress and actual verification](docs/PROGRESS.md)
