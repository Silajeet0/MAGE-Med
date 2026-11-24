# Clinical text ingestion

## Scope

Clinical text is MAGE-Med's second and only other patient-data modality. The
local importer accepts UTF-8 TXT, CSV, JSON, and FHIR R4 `DocumentReference`
attachments. It performs deterministic parsing, cleanup, optional heading
recognition, and character-offset chunking. It does not train or invoke a model,
interpret note claims, reconcile contradictions, or infer patient identity from
text, filenames, or proximity.

Original text and cleaned text are stored separately. Every note retains source
artifact/import IDs, locator, note type, authored/event/recorded time when
supplied, author reference or source label, content origin, patient/encounter
links, assertion class, and synthetic provenance. Every chunk retains a stable
ID, note ID, zero-based index, exact cleaned-text start/end offsets, optional
section heading, text, and SHA-256 checksum.

## Direct TXT, CSV, and JSON formats

TXT represents one note. Optional metadata is supplied through CLI flags or API
form fields. CSV requires a `text` header and supports:

```text
id,note_type,title,authored_at,author_reference,source_label,patient_id,encounter_id,text
```

JSON is a note object, an array of note objects, or an object with a `notes`
array. Each note supports the same fields. `note_type` is one of
`consultation`, `clinical_history`, `progress`, or `clinical_narrative`.
`authored_at` must be an ISO 8601 timestamp with a timezone.

`patient_id` and `encounter_id` are canonical internal UUIDs, not arbitrary
source identifiers. The importer verifies that they exist in SQLite and that an
encounter belongs to the supplied patient. Missing or unavailable mappings leave
the note unlinked. A patient/encounter mismatch clears both links and records the
issue; it never selects one side or guesses. Reimporting the same source note ID
with a verified mapping can transition an unlinked note to linked.

## FHIR R4 DocumentReference

The FHIR importer parses `DocumentReference.subject`,
`DocumentReference.context.encounter`, `date`, `author`, and each
`content.attachment`. Base64 `data` is accepted only with a `text/*` content
type, valid UTF-8, and the configured per-note byte limit.

Relative attachment `url` values can be read only beneath the explicitly set
`MAGE_MED_CLINICAL_TEXT_IMPORT_ROOT`. Resolution rejects absolute paths,
`..`, backslashes, paths escaping through symlinks, query/fragment components,
non-TXT files, non-text declared types, oversized files, and invalid UTF-8.
HTTP(S), `file:`, and every other URL scheme are never fetched. Missing, unsafe,
or external references are stored in the original FHIR resource with a distinct
`unavailable` import status; no substitute text is fabricated.

Files are decoded as inert plain text. Embedded markup, instructions, or code is
not rendered or executed.

## Limits and cleanup

Defaults are a 2 MiB upload, 256 KiB per note, 1,000 notes per CSV/JSON import,
1,000-character chunks, and 100-character overlap. Configuration is listed in
`.env.example`. UTF-8 and NUL checks happen before parsing. Cleanup applies NFC
Unicode normalization, newline normalization, removal of unsupported control
characters, trailing-whitespace removal, and blank-line compaction. It does not
change words, negate statements, correct medical content, or silently update
dates.

Chunk offsets refer to the cleaned text returned by the API. `original_text`
preserves the input exactly after UTF-8 decoding.

## Commands and APIs

```bash
uv run alembic -c apps/backend/alembic.ini upgrade head
uv run mage-med import-text data/synthetic/clinical_text/synthetic_notes.json \
  --dataset-id mage-med-synthetic-clinical-text \
  --dataset-version 1.0.0 \
  --synthetic --synthetic-seed 20261123
```

For TXT, verified links can be supplied with `--patient-id` and
`--encounter-id`; CSV/JSON carry mappings per note.

- `POST /api/v1/import/text` imports one bounded multipart upload.
- `GET /api/v1/patients/{patient_id}/clinical-context` returns source-linked
  structured summaries and linked notes with chunks.
- `GET /api/v1/patients/{patient_id}/notes/{note_id}` returns a note only when it
  belongs to the path patient.

The current research PoC API still lacks authentication. Keep it bound to a
trusted local interface and use only synthetic data until the authorization
milestone is implemented.
