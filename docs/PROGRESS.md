# MAGE-Med Progress

## Current status

| Field | Value |
| --- | --- |
| Current milestone | 10 — Canonical SQLite-to-Neo4j patient projection |
| Status | Complete for the requested synchronization scope; deterministic and real-Neo4j gates pass |
| Application | FastAPI backend and React status frontend are runnable |
| Persistence | Alembic revision `0004_clinical_text`; canonical two-modality records now have one patient-scoped SQLAlchemy read/domain layer |
| Knowledge graph | Four-tier schema plus deterministic, atomic SQLite projection, patient-scoped bounded reads, idempotent rebuild, and real Neo4j integration tests implemented |
| Data | Deterministic FHIR and fictional clinical-text fixtures, all explicitly synthetic; no real patient data |
| Model inference | Not implemented or run; Ollama guidance only |
| Clinical use | Research PoC foundation only; no clinical feature or action |

## Current prompt scope

Synchronize canonical normalized FHIR and clinical-text records from SQLite into
Neo4j without making Neo4j authoritative. Build deterministic patient/encounter/
fact projections with source provenance, safe rebuild, source-supplied terminology
only, fixed patient-scoped read queries, a CLI, deterministic tests, and a live
Neo4j acceptance gate. Do not invoke an LLM or accept arbitrary Cypher.

## Implemented for Milestone 10

- Added `GraphSyncService`, which reads only canonical SQLAlchemy models and
  projects Patient, Encounter, Observation, Condition, Medication, and
  ClinicalNote nodes. Canonical UUIDs, original FHIR type/ID, source locator,
  assertion class, event/recorded/import time, and source terminology are
  preserved. Narrative text is not copied into Neo4j.
- Encounter-linked facts use Patient → Encounter → fact. Facts without an
  encounter use Patient → fact. A patient/encounter ownership mismatch aborts
  synchronization rather than guessing or creating a cross-patient edge.
- Every patient-scoped node has a deterministic `DERIVED_FROM` relation to a
  SourceArtifact. Direct clinical-text notes and FHIR `DocumentReference` notes
  are both projected with checksums and traceable source metadata.
- Added graph migration `0002_patient_projection` for `HAS_MEDICATION` identity
  and SQLite-projection lookup. Clinical fact nodes also carry the
  `ClinicalAssertion` label; assertion types such as `observed` and `extracted`
  remain explicit properties rather than being upgraded to confirmed facts.
- Added atomic patient and full-dataset replacement. It deletes only the scoped
  derived temporal projection, rebuilds it in one managed write transaction, and
  removes only orphaned SQLite-projection concepts/source nodes. Evidence and
  inference tiers are not erased. Stable UUIDv5 edge/concept IDs make reruns
  idempotent.
- Added source-only terminology projection. `MAPS_TO` exists only when the
  canonical record supplies both code system and code, with
  `mapping_basis=source_supplied_code`. No narrative extraction, synonym mapping,
  disease-to-symptom relation, or causal association is generated.
- Added fixed, parameterized repository reads for patient neighborhood, temporal
  lab facts, condition history, note provenance, and visualization graph JSON.
  Each first proves the canonical patient scope; traversal rejects paths through
  another patient. No arbitrary or natural-language-to-Cypher API exists.
- Added `mage-med graph-sync [--patient-id UUID] [--rebuild]` and
  `docs/GRAPH_SYNC.md`. The report gives actual patient/node/relationship/concept/
  source counts and explicitly counts canonical allergies skipped because the
  approved core graph schema has no Allergy node.

## Milestone 10 verification ledger

Only commands actually executed are recorded.

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/mage-med-uv-cache uv run pytest apps/backend/tests/test_graph_sync.py services/knowledge_graph/tests -m 'not neo4j_smoke' -q` | Passed: 13 deterministic tests and 1 real-service test deselected before the direct-TXT-note case was added. The final focused graph-sync file then passed 2 tests in 2.17 seconds. |
| `docker run --rm --detach --name mage-med-graph-m10 ... neo4j:2026.10.1-community` and `docker exec ... cypher-shell ...` | Passed: the isolated pinned Neo4j returned `ready=1` after two expected connection-refused initialization retries. |
| `MAGE_MED_RUN_NEO4J_SMOKE=1 MAGE_MED_NEO4J_URI=bolt://127.0.0.1:17689 ... uv run pytest services/knowledge_graph/tests/test_repository_live.py apps/backend/tests/test_graph_sync_live.py -m neo4j_smoke -q` | Passed: 2 live tests in 13.66 seconds, covering both schema migrations, full sync twice, exact node stability, every bounded read, note-source checksum, graph JSON, and wrong-patient denial. |
| Fresh SQLite migration/import followed by `... uv run mage-med graph-sync --rebuild` twice against the isolated Neo4j | Passed: both runs reported 1 patient, 10 projected nodes, 17 relationships, 3 concepts, 1 source artifact, and 1 intentionally skipped allergy. A direct count after replay remained exactly 10 projected nodes. |
| `docker stop mage-med-graph-m10` | Passed; the temporary `--rm` container was stopped and auto-removed. |
| `UV_CACHE_DIR=/tmp/mage-med-uv-cache make check` | Passed: Ruff/Prettier formatting, Python/TypeScript lint, strict mypy over 35 source files, TypeScript checks, 70 Python tests with 3 live-Neo4j tests deselected from the unit gate, 2 Vitest tests, contracts build, and Vite production build. |

## Implemented for Milestone 9

- Added four explicit graph tier labels and all requested concrete node and
  relationship enums. `Medication` is documented as the projection of the
  canonical medication-request summary, not proof of administration.
- Added strict Pydantic graph write contracts. Every node and relationship has a
  stable UUID, source artifact, provenance ID, assertion type, verification state,
  and timezone-aware import/creation time. Patient-related elements require an
  explicit patient UUID; date-only or absent clinical event time remains allowed.
- Enforced fixed endpoint combinations for all ten relationship types. Scoped
  relationship Cypher checks both patient endpoints, and an unmatched or
  cross-patient write raises `GraphScopeError` instead of creating an edge.
- Kept Hypothesis and InferenceRun nodes `model_inferred`/`hypothesized`,
  `unverified`, `confirmation_status=nonconfirmed`, and
  `clinically_confirmed=false`. Supporting and contradicting evidence links keep
  the same boundary. Automatically extracted concepts cannot be marked verified.
- `ASSOCIATED_WITH` is always stored with `causal=false`; caller properties cannot
  override identity, tier, patient, provenance, time, confirmation, or causal
  semantics.
- Added migration `0001_multi_tier_graph`: global graph-entity and Patient ID
  uniqueness, migration version uniqueness, relationship-ID uniqueness for every
  allowed type, and indexes for patient/time/source/concept/evidence/inference
  access. Named `IF NOT EXISTS` statements and a migration marker make repeated
  initialization idempotent on Neo4j Community.
- Added `Neo4jGraphRepository` with only `initialize_schema`, typed node/edge
  upserts, and a bounded patient-fact read. It exposes no arbitrary Cypher, label,
  relationship, delete, filesystem, shell, or network operation.
- Extended the real Neo4j smoke path to initialize the schema twice, repeat node
  upserts without duplicates, verify constraints, and deny a Patient A to Patient
  B encounter edge. The temporary pinned container was stopped and auto-removed.
- Added `docs/GRAPH_DESIGN.md` with the Mermaid graph, invariants, schema and
  Community-edition limitations. Updated architecture to exactly four graph tiers.
  SQLite remains operational truth; SQLite-to-Neo4j projection is Milestone 10.

## Milestone 9 verification ledger

Only commands actually executed are recorded.

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/mage-med-uv-cache uv lock` | Initial offline attempt failed because registry metadata for other pinned workspace packages was not cached. Approved network retry passed and resolved the existing 49-package lock after adding the graph package's contract dependency. |
| `UV_CACHE_DIR=/tmp/mage-med-uv-cache uv run pytest services/knowledge_graph/tests -m 'not neo4j_smoke' -q` | Passed: 10 deterministic graph unit tests, 1 real-service test deselected. |
| `docker run --rm --detach --name mage-med-graph-m9 ... neo4j:2026.10.1-community` and `docker exec ... cypher-shell ...` | Passed: isolated pinned Neo4j started clean and returned `ready=1` after two expected connection-refused initialization retries. |
| `MAGE_MED_RUN_NEO4J_SMOKE=1 MAGE_MED_NEO4J_URI=bolt://127.0.0.1:17688 ... uv run pytest services/knowledge_graph/tests/test_repository_live.py -m neo4j_smoke -vv` | Passed: 1 real Neo4j test in 6.29 seconds; schema initialization/reinitialization, duplicate prevention, constraints, and cross-patient denial were exercised. |
| `docker stop mage-med-graph-m9` | Passed; the temporary `--rm` container was stopped and auto-removed. |
| `UV_CACHE_DIR=/tmp/mage-med-uv-cache make check` | Passed: Ruff/Prettier formatting, Python/TypeScript lint, strict mypy over 34 source files, TypeScript checks, 67 Python tests with 2 real-Neo4j tests deselected from the unit gate, 2 Vitest tests, contracts build, and Vite production build. |

## Implemented for the Milestone 8 clinical-access slice

- Added versioned Pydantic read contracts for patient pages/details, timeline
  entries, observation and note pages, source provenance, import diagnostics,
  and structured/human-readable data-quality results.
- Added one read-only `ClinicalDataService` over canonical SQLAlchemy tables.
  FastAPI routes are thin and never query persistence directly. Bounded paging,
  record/encounter/date/code/status/note-type filters, and deterministic ordering
  are implemented.
- The timeline covers encounters, conditions, observations, medication requests,
  allergies, and clinical-note references. It orders by clinical event time,
  labels recorded/import fallback explicitly, and returns event, recorded, and
  imported times separately.
- Observation reads preserve source terminology, quantity, UCUM system/code/unit,
  source text, data-absent reason, and reference ranges. Source absence is
  `missing`; only exact source text `negative`, `not detected`, or `absent` is
  labeled `observed_negative`. No inference is performed.
- Added all requested APIs plus JSON/plain-text data-quality endpoints. Path scope
  is explicit; optional `X-Patient-Scope` mismatches return 403. Source lookup
  requires patient scope, filters mappings/records to that patient, and denies
  raw content for multi-patient artifacts.
- Provenance lookup links normalized IDs to immutable artifact metadata and import
  manifests. It exposes checksum idempotency and duplicate-mapping diagnostics;
  replay-attempt persistence is honestly reported as unavailable (`false`).
- Data-quality reporting covers missing links, ambiguous patient identifiers,
  unsupported FHIR types, empty notes, temporal anomalies, terminology/unit
  omissions, conflicting same-code/same-time observations, and duplicate
  mappings. The CLI command `mage-med data-quality-report` prints the same report.
- Added an end-to-end API regression that imports an extended valid synthetic R4
  Bundle plus a linked TXT note. It proves two encounters, an extra fictional
  patient with an ambiguous identifier, contradictory observations, absent versus
  negative values, full timeline composition, unit/range preservation, note
  linkage, scoped source click-through, and multi-patient raw-source denial.
- Added `docs/CLINICAL_DATA_ACCESS.md` and updated README/architecture. No LLM,
  embedding, graph projection, model output, medical conclusion, or real patient
  data was introduced.

## Clinical-access verification ledger

Only commands actually executed are recorded.

| Command | Result |
| --- | --- |
| `timeout 90s .venv/bin/pytest apps/backend/tests/test_clinical_data_api.py -q` | Passed: 1 end-to-end FHIR + text + access/provenance/data-quality test in 1.67 seconds. |
| `UV_CACHE_DIR=/tmp/mage-med-uv-cache make check` | First run stopped at one Ruff import-order finding in the CLI; fixed mechanically. Final post-scope-isolation run passed Ruff/Prettier formatting, Python/TypeScript lint, strict mypy over 31 source files, TypeScript checks, 58 Python tests with 1 real-Neo4j smoke test deselected, 2 Vitest tests, contracts build, and Vite production build. |
| `MAGE_MED_DATABASE_URL=sqlite:////tmp/mage-med-clinical-access.sqlite ... alembic ... upgrade head; ... mage-med import-fhir ...; ... mage-med data-quality-report --dataset-id mage-med-synthetic-r4` | Passed: fresh SQLite upgraded through `0004_clinical_text`, 7 synthetic R4 resources imported, and the human report returned zero issues for the baseline fixture while explicitly warning that missing data is not a negative finding. |

## Implemented for Milestone 7

- Added explicit TXT, CSV, and JSON parsers with UTF-8, NUL, upload, per-note,
  row-count, metadata, timestamp, and note-type validation. No parser infers a
  patient from filenames or narrative content.
- Extended FHIR `DocumentReference` handling across `subject`,
  `context.encounter`, `date`, `author`, and `content.attachment`. Inline base64
  text and configured-root relative TXT files are supported; arbitrary URLs,
  traversal, symlink escape, missing/non-text/oversized/invalid files are recorded
  unavailable without fabricated text or network access.
- Added canonical original versus cleaned note text, content origin, source label,
  stable chunks, exact character offsets, optional section headings, and hashes.
  Migration `0004_clinical_text` upgrades existing notes and creates the chunk
  table with constraints and cascading note ownership.
- Added atomic/idempotent direct text imports. Canonical patient/encounter UUIDs
  are verified in SQLite; missing mappings stay unlinked, wrong-patient pairs
  clear both links, and a later verified mapping can link the stable note.
- Added `mage-med import-text`, `POST /api/v1/import/text`, patient-scoped note
  retrieval, and a combined clinical-context endpoint returning structured
  source summaries with linked unstructured notes/chunks.
- Added fixed-seed narratives covering consultation, progress, history and
  narrative types plus explicit conflict, negation, and stale-time cases. Every
  fixture says it is fictional synthetic fixture-generator text and not
  clinician-authored; no model generated it.
- Added parser, attachment sandbox, persistence, API, idempotency, mapping
  transition, wrong-patient, cross-modality retrieval, offsets/checksums,
  synthetic-manifest, and migration regression tests.

## Milestone 7 verification ledger

Only commands actually executed are recorded.

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/mage-med-uv uv run pytest services/ingestion/tests apps/backend/tests packages/contracts/tests tests/test_synthetic_fhir_fixtures.py -m 'not neo4j_smoke' -q` | Passed: 53 focused tests in 17.07 seconds before the final fixture/API additions. |
| `UV_CACHE_DIR=/tmp/mage-med-uv make check` | First run stopped at 4 Ruff import-order/unused-import findings; fixed mechanically. Second run stopped at one strict mypy CLI union annotation; fixed without suppression. Final post-documentation run passed formatting, Python/TypeScript lint, strict mypy over 27 source files, TypeScript checks, 57 Python tests with 1 real-Neo4j smoke test deselected, 2 Vitest tests, contracts build, and Vite production build. |
| `sha256sum data/synthetic/clinical_text/*` | Passed; exact hashes are recorded in `data/manifests/synthetic_clinical_text.json` and verified by tests. |
| `MAGE_MED_DATABASE_URL=sqlite:////tmp/mage-med-text-cli-final.sqlite UV_CACHE_DIR=/tmp/mage-med-uv uv run alembic -c apps/backend/alembic.ini upgrade head` | Passed against a fresh SQLite database through `0004_clinical_text`. |
| `... uv run mage-med import-fhir ... --dataset-id mage-med-synthetic-r4 ...` followed by `... uv run mage-med import-text data/synthetic/clinical_text/synthetic_notes.json --dataset-id mage-med-synthetic-clinical-text --dataset-version 1.0.0 --synthetic --synthetic-seed 20261123` | Passed: FHIR imported 7 resources; text imported 4 linked notes. Repeating the text command returned the same import ID with `idempotent_replay=true`. |
| Python standard-library SQLite read-only count query against the CLI database | Passed: `(1, 1, 5, 5, 2)` for patients, observations, clinical notes, chunks, and manifests—one embedded FHIR note plus four direct notes, with no replay duplicates. |

## Implemented for Milestone 5

- Added the `services/ingestion` workspace package. `fhirclient==4.2.0` performs
  local FHIR 4.0.1 base model parsing for the seven allowed resource types;
  project invariants add deterministic IDs, coding, explicit-reference, scope,
  and provenance checks. Profile/implementation-guide conformance is explicitly
  `not_evaluated` and no certification is claimed.
- Accepts a FHIR R4 Bundle or individual-resource JSON. Bundle parsing retains
  `entry.fullUrl`, resource type/ID, exact resource JSON, and aliases for both
  `urn:uuid` and relative references. Duplicate/ambiguous aliases reject the
  document; unresolved or patient-inconsistent links are unusable, never guessed.
- Normalizes Patient, Encounter, Condition, Observation, MedicationRequest,
  AllergyIntolerance, and embedded-text DocumentReference into canonical
  Pydantic/SQLite records. Observation quantities and reference ranges retain
  source units. Missing optional fields remain absent.
- Added migration `0003_fhir_ingestion`, import validation metadata, exact
  per-resource outcomes, and source-to-normalized mappings containing each
  original resource. The assertion constraints now include the six repository
  instruction classes, including `clinician_rejected`.
- Added a transactional import service with stable UUIDv5 normalized IDs,
  checksum replay, stable updates for changed sources, and rollback. Exact replay
  returns the existing manifest; it creates no duplicate clinical rows. Stable
  identities are dataset-scoped, so equal relative FHIR IDs in unrelated
  datasets do not merge.
- Added `mage-med import-fhir`, `POST /api/v1/import/fhir`, and
  `GET /api/v1/imports/{id}`. Uploads enforce basename/extension/media-type/size
  limits, never persist the supplied filename, and never fetch external URLs.
- Added contract, parser, service, API, migration, sparse-field, rollback,
  bad-reference, unsupported-resource, invalid-coding, idempotency, and
  no-network-content tests. Added exact operational and Synthea guidance in
  `docs/FHIR_INGESTION.md`.

## Milestone 5 verification ledger

Only commands actually executed are recorded here.

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/mage-med-uv uv lock` | Initial sandbox run failed because DNS/network access was blocked. Approved network retry passed and resolved 49 packages, adding exact pins for `fhirclient==4.2.0` and `python-multipart==0.0.20`. |
| `UV_CACHE_DIR=/tmp/mage-med-uv uv sync --all-packages --frozen` | Initial sandbox run failed on package download. Approved network retry passed. A subsequent `--reinstall-package mage-med-ingestion` passed after the new workspace source was added. |
| `UV_CACHE_DIR=/tmp/mage-med-uv uv run pytest services/ingestion/tests apps/backend/tests/test_fhir_import_service.py apps/backend/tests/test_fhir_import_api.py apps/backend/tests/test_migrations.py packages/contracts/tests/test_clinical_schemas.py -q` | Passed: 27 tests in 9.20 seconds. |
| `UV_CACHE_DIR=/tmp/mage-med-uv uv run ruff format .; npm run format` | Passed: Ruff reformatted 9 Python files and Prettier formatted the TypeScript contract; frontend files were unchanged. |
| `UV_CACHE_DIR=/tmp/mage-med-uv make check` | First run stopped at Ruff with 6 findings; fixed upload dependency annotation, import ordering, exports, and one unused import. Second run stopped at strict mypy with 13 narrowing findings; fixed without suppressions. Final post-regression run passed: format checks; Python/TypeScript lint; strict mypy over 23 files; TypeScript checks; 43 Python tests with 1 real-Neo4j smoke test deselected; 2 Vitest tests; contracts build; and Vite production build. |
| `MAGE_MED_DATABASE_URL=sqlite:////tmp/mage-med-fhir-cli-final.sqlite UV_CACHE_DIR=/tmp/mage-med-uv uv run alembic -c apps/backend/alembic.ini upgrade head` | Passed against a new database through `0003_fhir_ingestion`. |
| `MAGE_MED_DATABASE_URL=sqlite:////tmp/mage-med-fhir-cli-final.sqlite UV_CACHE_DIR=/tmp/mage-med-uv uv run mage-med import-fhir data/synthetic/fhir/r4/synthetic_patient_bundle.json --dataset-id mage-med-synthetic-r4 --dataset-version 1 --synthetic-seed 20261123` | First run passed with 7 imported resources, FHIR 4.0.1, `fhirclient` 4.2.0, and profile conformance `not_evaluated`. Second identical run returned the same import ID with `idempotent_replay=true`. |
| `sqlite3 /tmp/mage-med-fhir-cli-20261123.sqlite ...` | Not run: the `sqlite3` CLI is unavailable (`command not found`). The equivalent read-only query via Python's standard `sqlite3` module passed and returned `(1, 1, 7, 1, 1, 1)` for manifests, artifacts, mappings, patients, encounters, and observations. |
| `rg -n -i "(orthanc|pacs|dicom|kubernetes|kafka|postgres|fhir server)" ...` | Passed scope audit: matches occur only in repository exclusions or statements that no FHIR server is required. A network-client scan found no fetch/client calls in the importer. |

## Implemented for Milestone 3

- Added canonical schema version `1.0.0` Pydantic contracts for `Patient`,
  `Encounter`, `Condition`, `Observation`, `MedicationRequestSummary`, `Allergy`,
  `ClinicalNote`, `SourceArtifact`, `ClinicalAssertion`, and `ImportManifest`.
- Restricted modality to exactly `structured_clinical_data` and
  `unstructured_clinical_text`; FHIR R4 is a source format, not a modality.
- Added stable UUID IDs, source artifact/resource locators, patient/encounter
  links, event/recorded/import times, provenance/run metadata, assertion types,
  verification/lifecycle state, and assertion-type-aware confidence validation.
- Added SQLAlchemy models and Alembic revision
  `0002_canonical_clinical_model` with required source-artifact and import-manifest
  foreign keys, patient and encounter scope, indexes, enum/check constraints, and
  immutable source rows.
- Added TypeScript boundary types for the schema version, two modalities,
  assertion types, source references, provenance, and common clinical facts.
- Added a fixed-seed generator and committed FHIR R4 collection Bundles covering
  linked Patient, Encounter, Condition, Observation with UCUM unit/reference
  range, MedicationRequest, AllergyIntolerance, and embedded-text
  DocumentReference. Every resource is tagged `SYNTHETIC`.
- Added an intentionally unresolved `Observation.subject` fixture and a dataset
  manifest with SHA-256 checksums and expected validation outcomes.
- Documented how pinned local Synthea FHIR R4 output can later enter the same
  canonical model without requiring a FHIR server or real patient data.

## Current verification ledger

Only commands actually executed are recorded here.

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/mage-med-uv uv run pytest packages/contracts/tests tests/test_synthetic_fhir_fixtures.py apps/backend/tests/test_migrations.py apps/backend/tests/test_persistence_models.py -q` | First two runs blocked at collection because `scripts` was not on pytest's import path; fixed with package marker and explicit project `pythonpath`. Third run found one missing assertion modality in test setup; corrected. Final focused run passed: 12 tests. |
| `UV_CACHE_DIR=/tmp/mage-med-uv uv run ruff format .; npm run format` | Passed: Ruff reformatted 5 Python files; Prettier formatted the TypeScript contract and confirmed frontend files. |
| `UV_CACHE_DIR=/tmp/mage-med-uv make check` | First run reached lint and reported seven `datetime.UTC` modernization findings; fixed mechanically. Second run reached mypy and reported the schema constant was typed as `str` instead of `Literal`; corrected. Third and final post-documentation runs passed formatting, Python/TypeScript lint, strict mypy (15 source files), TypeScript checks, 18 Python tests with 1 real-Neo4j smoke test deselected, 2 Vitest tests, contracts build, and Vite production build. |
| `sha256sum data/synthetic/fhir/r4/*.json` | Passed after final fixture generation: valid bundle `00fe9b4d...ebcdf`; deliberate invalid-reference bundle `0632ba2d...9f6e`. Full hashes are in the dataset manifest and verified by tests. |
| `alembic upgrade head; alembic check` against fresh temporary SQLite databases | First drift check correctly detected SQLite enum-reflection differences and two ORM index declarations missing relative to the migration. Metadata/comparison rules were corrected. The second fresh-database run passed: upgraded through `0002_canonical_clinical_model` and reported `No new upgrade operations detected.` |

## Prior Milestone 2 scope

Create a lean modular monorepo foundation with exact-pinned Python and TypeScript dependencies, FastAPI and React applications, shared health/error contracts, SQLite/Alembic wiring, real Neo4j readiness, one-service infrastructure, quality automation, CI, and a live frontend-to-backend-to-Neo4j smoke test. Do not pre-build ingestion, retrieval, agent, MCP, A2A, model, evaluation, or clinical functionality.

## Implemented in Milestone 2

- Added uv workspace packages for `apps/backend`, `packages/contracts`, and `services/knowledge_graph`; unused service/data modules were not created.
- Added an npm workspace for `apps/frontend` and the TypeScript side of `packages/contracts`.
- Implemented typed FastAPI settings, structured JSON logging, safe request-ID propagation, CORS, structured error envelopes, liveness, and readiness APIs.
- Implemented real SQLAlchemy/SQLite and official Neo4j driver readiness queries. Readiness returns HTTP 503 and an `unavailable` component when Neo4j cannot be reached.
- Added an Alembic baseline migration. It creates only Alembic version state; domain tables remain deferred to their owning milestone.
- Added a routed React/TypeScript/Vite/Tailwind application shell and system-status page using the real backend readiness API.
- Added unit tests for health/error behavior, SQLite connectivity, migration execution, Neo4j fixed-query behavior, and frontend response validation.
- Added a live smoke test that imports the frontend API client, starts a real backend process, and requires SQLite plus a real Neo4j query to pass.
- Added exact direct dependency pins, `uv.lock`, `package-lock.json`, `.env.example`, clinical/model-aware `.gitignore`, Make targets, README, one-service Neo4j Compose file, and GitHub Actions quality/smoke jobs.
- Documented optional local Ollama and MLflow 3.18.0 setup without adding either to application startup.

## Milestone 2 verification ledger

Only commands actually executed are recorded here.

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/mage-med-uv uv lock` | Passed: resolved 42 packages under Python 3.11.15 and wrote `uv.lock` |
| `npm install --ignore-scripts` | Initial run failed correctly because TypeScript 7.0.2 violated `typescript-eslint`'s `<6.1` peer constraint; TypeScript was corrected to exact-pinned 6.0.3, then install passed and wrote `package-lock.json` |
| `UV_CACHE_DIR=/tmp/mage-med-uv uv sync --all-packages --frozen --offline` | Passed: checked 39 installed packages without network resolution |
| `npm ci --ignore-scripts --offline` | Passed: installed 156 packages; npm audit reported 0 vulnerabilities |
| `MAGE_MED_DATABASE_URL=sqlite:////tmp/mage-med-milestone2.db UV_CACHE_DIR=/tmp/mage-med-uv uv run alembic -c apps/backend/alembic.ini upgrade head` | Passed: upgraded an empty SQLite database to `0001_baseline` |
| `UV_CACHE_DIR=/tmp/mage-med-uv make check` | Passed: Ruff format (25 files), Ruff lint, ESLint, strict mypy (12 source files), TypeScript checks, 7 Python unit tests, 2 Vitest tests, contracts build, and Vite production build |
| `make neo4j-up` | Blocked in this environment: Docker CLI 29.1.3 is installed but the Docker Compose plugin is absent (`unknown shorthand flag: 'f'`) |
| `ruby -e '...YAML.load_file("infrastructure/compose.yaml")...'` | Passed: Compose YAML parses and contains exactly one service using pinned image `neo4j:2026.10.1-community` |
| `UV_CACHE_DIR=/tmp/mage-med-uv make smoke` with no Neo4j | Failed as designed after reaching the real backend: frontend received `not_ready`, SQLite `available`, and Neo4j `unavailable` |
| `docker run --rm --detach --name mage-med-smoke-neo4j --env NEO4J_AUTH=neo4j/mage-med-local --publish 127.0.0.1:17687:7687 neo4j:2026.10.1-community` | Passed after pulling the exact image; isolated local container started |
| `docker exec mage-med-smoke-neo4j cypher-shell -u neo4j -p mage-med-local 'RETURN 1 AS ready'` | Passed: returned `ready` = `1` after one expected initialization retry |
| `MAGE_MED_NEO4J_URI=bolt://127.0.0.1:17687 UV_CACHE_DIR=/tmp/mage-med-uv make smoke` | Passed: 1 live frontend-client Vitest and 1 independent backend-to-Neo4j pytest passed |
| `docker stop mage-med-smoke-neo4j` | Passed: temporary `--rm` container stopped and was auto-removed; no smoke container remains |

## Safety and data status

- No real patient records, reference corpus, medical findings, citations, agent
  output, or model output were added or generated. Committed patient-like content
  is deterministic fictional test data labeled `SYNTHETIC` in every resource and
  in its manifest.
- Health responses contain only component state, application version, sanitized detail, and opaque request IDs.
- Logs exclude request bodies, clinical content, connection credentials, and raw exception messages returned to clients.
- The frontend labels the application as a clinician-supervised research PoC and presents no diagnosis, recommendation, approval, metric, or clinical action.
- Ollama was detected locally but no model was selected, downloaded, or invoked. MLflow was not installed or invoked.

## Known limitations

- The local Docker installation lacks the Compose plugin, so `make neo4j-up` could not be executed here. The same pinned Neo4j image and credentials were exercised successfully through an isolated `docker run`, and CI defines a real Neo4j service.
- Current Starlette's synchronous `TestClient` and this sandbox's Python 3.11 event-loop thread-executor path hung even for a bare FastAPI app. Tests use current `httpx2` asynchronous ASGI transport and explicit lifespan instead; live uvicorn smoke coverage verifies the process boundary.
- Readiness still performs only two bounded constant connectivity checks. The graph
  schema/repository now exists, but automatic SQLite projection, agent workflow,
  review workflow, authentication, and reference retrieval do not. SQLite remains
  migration-owned and is not created during startup.
- The committed FHIR fixtures are checked for the supported R4 resource shapes,
  required fields, deterministic generation, and local reference resolution.
  `fhirclient==4.2.0` now performs local base-model structural validation. A full
  HL7 validator with profiles, implementation guides, and terminology services
  was not installed or run; comprehensive conformance is not claimed.
- The upload API is bounded and local-only but authentication and purpose-based
  authorization have not yet been implemented. It must remain on a trusted local
  development interface and must not be used with real patient data.
- Remote `DocumentReference` URLs are never resolved. Relative local TXT paths
  work only under an explicitly configured import root; without it they remain
  unavailable. Other local document formats are deferred.
- Patient UUID scope is enforced for the new read APIs, but user authentication,
  roles, and purpose-of-use authorization are later milestones. The API remains a
  trusted local synthetic-data PoC. Raw multi-patient source artifacts are denied.
- Data-quality contradiction detection is deliberately narrow: it flags differing
  source values for the same patient, terminology key, and event time. It does not
  decide which observation is clinically correct.
- The repository environment exposes an empty `.git` mount rather than a usable Git worktree, so Git status/diff verification was unavailable.

## Next milestone readiness

The requested Milestone 10 projection passes deterministic, real-Neo4j, CLI
replay, wrong-patient, and repository-wide quality gates. Milestone 11 can ingest
the separately governed reference corpus without changing SQLite's role as the
clinical source of truth. Full Milestone 8 still needs a committed canonical
multi-patient longitudinal dataset manifest and one documented from-empty-state
two-modality import command; that earlier gap remains explicit. The graph does
not project allergies because Allergy is absent from the approved core graph
schema, and the sync report makes that omission explicit. Persisted stale-
projection state/background scheduling, Milestone 6 optional structured CSV/JSON
adapters, FAISS, reference retrieval, agents, MCP, A2A, models, and evaluation
remain unimplemented.

## Milestone history

| Milestone | Status | Evidence |
| --- | --- | --- |
| 1 — Final scope and architecture documentation | Complete | Scope, architecture, 25 milestones, terminology, and exclusion checks passed |
| 2 — Reproducible repository and quality scaffold | Complete | Full quality gate and real frontend → backend → SQLite/Neo4j smoke passed |
| 3 — Shared contracts and domain vocabulary | Complete | Canonical versioned Pydantic/TypeScript contracts and validation tests pass |
| 4 — SQLite operational persistence | In progress | FHIR-owned transactions, idempotency, rollback, constraints, and migrations pass; general repositories/audit/patient-scope acceptance remain deferred |
| 5 — FHIR R4 local Bundle ingestion | Complete for requested scope | Real local parser/normalizer, CLI/API, SQLite mapping, regression suite, full quality gate, and actual CLI replay pass |
| 6 — Optional structured CSV/JSON adapters | Not started | Optional milestone was not required by the current request |
| 7 — Unstructured clinical text ingestion | Complete for requested scope | Four input paths, safe local attachment handling, chunks, cross-modality retrieval, actual CLI replay, and full quality gate pass |
| 8 — Synthetic dataset and import pipeline | In progress | Common patient access, two-modality timeline, scoped provenance, integrity reporting, and multi-patient regression pass; committed combined dataset workflow remains |
| 9 — Neo4j multi-tier schema and safe access | Complete for requested scope | Four tiers, constraints/indexes, typed safe repository, nonconfirmed semantics, deterministic tests, and clean real-Neo4j gate pass |
| 10 — SQLite-to-Neo4j patient projection | Complete for requested scope | Atomic canonical projection, source-only terminology, traceability, bounded scoped reads, CLI replay, and real Neo4j acceptance gate pass |
| 11–25 | Not started | See `docs/IMPLEMENTATION_PLAN.md` |
