# Local FHIR R4 ingestion

## Supported boundary

MAGE-Med imports UTF-8 JSON from a local FHIR R4 `Bundle` or one individual
FHIR R4 resource. It does not require or contact a FHIR server. The allowlist is
`Patient`, `Encounter`, `Condition`, `Observation`, `MedicationRequest`,
`AllergyIntolerance`, and `DocumentReference`.

FHIR is an exchange format, not a patient-data modality. Structured resources
normalize into the structured clinical modality. Embedded textual
`DocumentReference` content normalizes into the unstructured clinical-text
modality while retaining the same import manifest and source artifact.

The importer uses `fhirclient==4.2.0`, whose published compatibility table maps
that release to FHIR `4.0.1`, for local base model parsing and structural/type
checks. MAGE-Med adds deterministic identity, reference, coding, patient-scope,
and provenance invariants. This is deliberately narrower than full conformance:

- it does not load or validate implementation guides, profiles, terminology
  bindings, invariants requiring a full validator, or server capability;
- it does not claim comprehensive FHIR validation, certification, or profile
  conformance;
- every import report therefore says
  `validation_scope=base_structure_and_project_invariants` and
  `profile_conformance=not_evaluated`.

## Resolution and persistence rules

For each Bundle entry the importer retains `entry.fullUrl`, `resourceType`, `id`,
and the exact resource JSON. It accepts Bundle-local `urn:uuid:<uuid>` and
relative `ResourceType/id` references. An individual resource can resolve a
relative reference only when an earlier successful import established a unique
source mapping. References are never inferred from filenames, display strings,
or the presence of a single patient.

Missing optional elements remain missing. Invalid supported resources,
unresolved references, invalid coding, unsupported resource types, and linked
remote `DocumentReference` content receive explicit per-resource outcomes.
Ambiguous aliases reject the document. Patient and encounter references that
resolve to different patients are unusable rather than silently relinked.

One SQLite transaction writes the immutable source artifact, import manifest,
normalized records, and source-to-normalized mappings. A failure rolls the whole
transaction back. An exact content checksum replay returns the existing import
without duplicate rows. A changed source with the same FHIR resource identities
updates the stable normalized rows and creates a new immutable artifact and
manifest. Internal identities and mappings include `dataset_id`, preventing equal
FHIR-relative IDs from unrelated datasets from being merged. Conflicting facts
with distinct source IDs remain distinct. SQLite migrations must be applied
before importing.

The importer performs no external network fetch. URL-only `DocumentReference`
attachments are reported unavailable in this milestone. Embedded base64 UTF-8 text
with a `text/*` content type is supported.

## CLI

Initialize SQLite, then import a local Bundle or individual resource:

```bash
uv run alembic -c apps/backend/alembic.ini upgrade head
uv run mage-med import-fhir data/synthetic/fhir/r4/synthetic_patient_bundle.json \
  --dataset-id mage-med-synthetic-r4 \
  --dataset-version 1 \
  --synthetic-seed 20261123
```

For an already generated Synthea R4 Bundle kept outside Git:

```bash
uv run mage-med import-fhir /absolute/path/to/synthea/output/fhir/patient.json \
  --dataset-id synthea-r4 \
  --dataset-version <pinned-synthea-release> \
  --synthetic-seed <generation-seed>
```

The CLI accepts only an existing `.json` file and applies the configured byte
limit before reading it. Synthetic-tagged resources require an explicit seed.

## HTTP API

`POST /api/v1/import/fhir` accepts one multipart local upload and optional form
fields `dataset_id`, `dataset_version`, and `synthetic_seed`. The filename must be
a basename ending in `.json`; allowed media types are `application/json`,
`application/fhir+json`, `application/octet-stream`, and `text/json`. The default maximum is
10 MiB and is configurable with `MAGE_MED_FHIR_MAX_UPLOAD_BYTES`. Bytes are
processed in memory and are not written using the caller-supplied filename.

```bash
curl --fail-with-body -X POST http://127.0.0.1:8000/api/v1/import/fhir \
  -F file=@data/synthetic/fhir/r4/synthetic_patient_bundle.json\;type=application/fhir+json \
  -F dataset_id=mage-med-synthetic-r4 \
  -F dataset_version=1 \
  -F synthetic_seed=20261123
```

`GET /api/v1/imports/{id}` returns the persisted import report. A new import is
HTTP 201; an exact replay is HTTP 200. Rejected files use the API's structured
error envelope. The current local PoC API does not yet implement authentication;
do not expose it to untrusted networks or use it with real patient data.
