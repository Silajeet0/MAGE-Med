# Clinical Data Access

The common clinical data layer is a read-only domain service over the canonical
SQLAlchemy models in SQLite. FastAPI handlers validate paging and scope, then
delegate to this service; they do not query persistence directly.

## Patient scope

Patient routes use the path patient UUID as the explicit scope. Callers may also
send `X-Patient-Scope`; a mismatch is rejected with HTTP 403. The patient list is
limited to that UUID when the header is present. Source lookup requires a
`patient_id` query parameter and verifies that the artifact contains a normalized
record for that patient. This is deterministic isolation for the current trusted
local PoC, not authentication; authenticated user and purpose-of-use policy remain
deferred.

## Endpoints

- `GET /api/v1/patients?page=1&page_size=25`
- `GET /api/v1/patients/{id}`
- `GET /api/v1/patients/{id}/timeline`
- `GET /api/v1/patients/{id}/observations`
- `GET /api/v1/patients/{id}/notes`
- `GET /api/v1/sources/{id}?patient_id={patient-id}`
- `GET /api/v1/data-quality?dataset_id={dataset-id}`
- `GET /api/v1/data-quality/report?dataset_id={dataset-id}` (plain text)

Timeline, observation, and note lists support bounded paging. Timeline supports
record-type, encounter, inclusive date, and ascending/descending filters.
Observations support source code, FHIR status, encounter, and date filters. Notes
support note type, encounter, and date filters.

## Timeline semantics

The event order uses the source clinical event date/time. When absent, it falls
back first to recorded time and then import time, and returns `sort_time_basis`
so the fallback is visible. Original event, recorded, and import values remain
separate. Exact ties use stable internal IDs.

`value_state=missing` is used only for an Observation with a source
`dataAbsentReason`; this is not a negative result. `observed_negative` is used
only for an exact source `valueString` of `negative`, `not detected`, or `absent`.
Other values remain `observed`; no clinical interpretation or inference occurs.
Source coding, UCUM fields, source quantity, reference range, and raw text are
not converted.

## Provenance and idempotency diagnostics

Every timeline/read item supplies a scoped `provenance_href`. Source lookup
returns immutable artifact metadata, its import manifest, mapping outcomes, and
patient-scoped normalized record IDs. Raw source content is omitted by default
and is returned with `include_content=true` only when the artifact belongs
exclusively to the scoped patient; multi-patient Bundle content is denied.
Mapping and normalized-record lists are always filtered to the selected patient.
The diagnostic exposes the
checksum idempotency key and duplicate mapping count. Replay attempts are not
persisted, so `replay_attempts_persisted` is honestly `false`; the import response
remains the source of truth for whether a particular request was a replay.

## Data quality report

The JSON and text reports count missing patient links, ambiguous patient
identifiers, unsupported FHIR resource types, notes without text, temporal
anomalies, missing terminology/units, contradictory same-patient/same-code/
same-time observations, and duplicate normalized mappings. Examples contain IDs,
not narrative text. The report is an integrity aid, not a clinical conclusion.

```bash
uv run mage-med data-quality-report --dataset-id mage-med-synthetic-r4
```

No LLM, embedding model, graph projection, medical inference, or external network
request is involved in this layer.
