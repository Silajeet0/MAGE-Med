# Synthetic clinical fixtures and future datasets

## Current fixture

The repository contains only deterministic, fictional test data under
`data/synthetic/`. The FHIR fixture is a standards-shaped FHIR R4 `Bundle` with
linked `Patient`, `Encounter`, `Condition`, laboratory `Observation`,
`MedicationRequest`, `AllergyIntolerance`, and `DocumentReference` resources.
Every resource is tagged `SYNTHETIC`, UUIDs are derived from the fixed seed
`20261123`, and the dataset manifest records checksums and expected validation
outcomes.

The valid bundle follows the official [FHIR R4 resource definitions](https://hl7.org/fhir/R4/resourcelist.html)
and uses only R4 JSON properties documented for those resources. The second
bundle is valid JSON with FHIR resource structure but deliberately points an
`Observation.subject` at a missing patient. It exists only to test bundle-local
reference validation and must be rejected by a future importer.

Regenerate to a temporary directory and compare with the committed fixtures:

```bash
uv run python scripts/generate_synthetic_fhir.py --output-dir /tmp/mage-med-fhir
sha256sum /tmp/mage-med-fhir/*.json
```

The local importer now accepts this valid fixture. The deliberate bad-reference
fixture imports its patient but reports its unresolved Observation as unusable;
it does not guess a relationship. See [FHIR ingestion](FHIR_INGESTION.md).

## Replacing fixtures with Synthea FHIR R4

[Synthea](https://github.com/synthetichealth/synthea) can later generate
synthetic patient histories and export FHIR. That export can replace or augment
the small committed fixtures without changing the canonical model:

1. Run a pinned Synthea release locally and configure its exporter for FHIR R4.
2. Keep generated output outside Git under an ignored clinical/import path.
3. Create a new dataset manifest containing the Synthea release/configuration,
   generation seed, output checksums, FHIR version, generation time, and license.
4. Submit each local FHIR R4 Bundle through `mage-med import-fhir`, including the
   pinned dataset release and explicit generation seed. The importer maps the
   supported resources into version `1.0.0` Pydantic contracts and SQLite tables
   shared with clinical-text ingestion.
5. Report unsupported resources and unresolved or cross-patient references;
   never silently coerce or link them.

No FHIR server is required. Adding Synthea output does not authorize real patient
data, hospital-system integration, model training, or expansion beyond the two
defined patient-data modalities.

## Synthetic clinical narratives

`data/synthetic/clinical_text/` contains deterministic TXT, CSV, and JSON
fixtures. The JSON notes link to the canonical IDs produced by importing the
FHIR fixture with dataset ID `mage-med-synthetic-r4`; the TXT and CSV examples
are intentionally unlinked. The manifest records fixed seed `20261123`, exact
checksums, and that the narratives are fictional fixture-generator text—not
clinician-authored notes.

The narratives deliberately retain a structured-text conflict, an explicit
negation, and a six-year-old statement. These are safety test inputs, not medical
findings. No model generated them and no importer reconciles or updates them.
See [clinical text ingestion](CLINICAL_TEXT_INGESTION.md).
