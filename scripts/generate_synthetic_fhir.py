"""Generate the deterministic, explicitly synthetic FHIR R4 test bundles."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

FIXTURE_SEED = 20261123
FIXTURE_NAMESPACE = UUID("7a9cf178-8e89-4f4a-9f43-bcdfe7256ec4")
SYNTHETIC_TAG = {
    "system": "https://mage-med.example/tags",
    "code": "SYNTHETIC",
    "display": "SYNTHETIC TEST DATA - NOT A REAL PATIENT",
}


def _id(label: str, seed: int) -> str:
    return str(uuid5(FIXTURE_NAMESPACE, f"mage-med:{seed}:{label}"))


def _meta() -> dict[str, Any]:
    return {"tag": [SYNTHETIC_TAG]}


def build_valid_bundle(seed: int = FIXTURE_SEED) -> dict[str, Any]:
    """Return one linked FHIR R4 collection Bundle with no real patient data."""

    ids = {
        label: _id(label, seed)
        for label in (
            "bundle",
            "patient",
            "encounter",
            "condition",
            "observation",
            "medication-request",
            "allergy",
            "document-reference",
        )
    }
    refs = {label: f"urn:uuid:{value}" for label, value in ids.items()}
    note = (
        "SYNTHETIC consultation note. Patient reports no medication side effects. "
        "This record is fictional and for testing only."
    )

    resources: list[tuple[str, dict[str, Any]]] = [
        (
            "patient",
            {
                "resourceType": "Patient",
                "id": ids["patient"],
                "meta": _meta(),
                "identifier": [
                    {
                        "system": "https://mage-med.example/synthetic-patient-id",
                        "value": "SYNTHETIC-PATIENT-001",
                    }
                ],
                "active": True,
                "name": [
                    {
                        "use": "official",
                        "text": "SYNTHETIC Ada Testpatient",
                        "family": "SYNTHETIC-Testpatient",
                        "given": ["Ada"],
                    }
                ],
                "gender": "female",
                "birthDate": "1975-01-01",
            },
        ),
        (
            "encounter",
            {
                "resourceType": "Encounter",
                "id": ids["encounter"],
                "meta": _meta(),
                "status": "finished",
                "class": {
                    "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                    "code": "AMB",
                    "display": "ambulatory",
                },
                "type": [
                    {
                        "coding": [
                            {
                                "system": "http://snomed.info/sct",
                                "code": "185349003",
                                "display": "Encounter for check up",
                            }
                        ]
                    }
                ],
                "subject": {"reference": refs["patient"]},
                "period": {
                    "start": "2026-01-15T09:00:00Z",
                    "end": "2026-01-15T09:30:00Z",
                },
            },
        ),
        (
            "condition",
            {
                "resourceType": "Condition",
                "id": ids["condition"],
                "meta": _meta(),
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                            "code": "active",
                        }
                    ]
                },
                "verificationStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                            "code": "confirmed",
                        }
                    ]
                },
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "44054006",
                            "display": "Type 2 diabetes mellitus",
                        }
                    ]
                },
                "subject": {"reference": refs["patient"]},
                "encounter": {"reference": refs["encounter"]},
                "onsetDateTime": "2024-06-01T10:00:00Z",
                "recordedDate": "2026-01-15T09:10:00Z",
            },
        ),
        (
            "observation",
            {
                "resourceType": "Observation",
                "id": ids["observation"],
                "meta": _meta(),
                "status": "final",
                "category": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                "code": "laboratory",
                                "display": "Laboratory",
                            }
                        ]
                    }
                ],
                "code": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "4548-4",
                            "display": "Hemoglobin A1c/Hemoglobin.total in Blood",
                        }
                    ]
                },
                "subject": {"reference": refs["patient"]},
                "encounter": {"reference": refs["encounter"]},
                "effectiveDateTime": "2026-01-15T08:45:00Z",
                "issued": "2026-01-15T09:05:00Z",
                "valueQuantity": {
                    "value": 7.2,
                    "unit": "%",
                    "system": "http://unitsofmeasure.org",
                    "code": "%",
                },
                "referenceRange": [
                    {
                        "high": {
                            "value": 6.5,
                            "unit": "%",
                            "system": "http://unitsofmeasure.org",
                            "code": "%",
                        },
                        "text": "SYNTHETIC example reference threshold",
                    }
                ],
            },
        ),
        (
            "medication-request",
            {
                "resourceType": "MedicationRequest",
                "id": ids["medication-request"],
                "meta": _meta(),
                "status": "active",
                "intent": "order",
                "medicationCodeableConcept": {
                    "coding": [
                        {
                            "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                            "code": "860975",
                            "display": "metformin hydrochloride 500 MG Oral Tablet",
                        }
                    ]
                },
                "subject": {"reference": refs["patient"]},
                "encounter": {"reference": refs["encounter"]},
                "authoredOn": "2026-01-15T09:20:00Z",
                "dosageInstruction": [{"text": "SYNTHETIC test instruction: one tablet daily"}],
            },
        ),
        (
            "allergy",
            {
                "resourceType": "AllergyIntolerance",
                "id": ids["allergy"],
                "meta": _meta(),
                "clinicalStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                            "code": "active",
                        }
                    ]
                },
                "verificationStatus": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                            "code": "confirmed",
                        }
                    ]
                },
                "type": "allergy",
                "category": ["medication"],
                "criticality": "high",
                "code": {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "764146007",
                            "display": "Penicillin",
                        }
                    ]
                },
                "patient": {"reference": refs["patient"]},
                "encounter": {"reference": refs["encounter"]},
                "recordedDate": "2026-01-15T09:12:00Z",
                "reaction": [
                    {
                        "manifestation": [
                            {
                                "coding": [
                                    {
                                        "system": "http://snomed.info/sct",
                                        "code": "271807003",
                                        "display": "Skin rash",
                                    }
                                ]
                            }
                        ]
                    }
                ],
            },
        ),
        (
            "document-reference",
            {
                "resourceType": "DocumentReference",
                "id": ids["document-reference"],
                "meta": _meta(),
                "status": "current",
                "type": {
                    "coding": [
                        {
                            "system": "http://loinc.org",
                            "code": "11488-4",
                            "display": "Consult note",
                        }
                    ]
                },
                "subject": {"reference": refs["patient"]},
                "date": "2026-01-15T09:25:00Z",
                "description": "SYNTHETIC consultation note - NOT A REAL CLINICAL RECORD",
                "content": [
                    {
                        "attachment": {
                            "contentType": "text/plain",
                            "data": base64.b64encode(note.encode("utf-8")).decode("ascii"),
                            "title": "SYNTHETIC consultation note",
                            "creation": "2026-01-15T09:25:00Z",
                        }
                    }
                ],
                "context": {"encounter": [{"reference": refs["encounter"]}]},
            },
        ),
    ]

    return {
        "resourceType": "Bundle",
        "id": ids["bundle"],
        "meta": _meta(),
        "identifier": {
            "system": "https://mage-med.example/synthetic-bundle-id",
            "value": f"SYNTHETIC-FHIR-R4-{seed}",
        },
        "type": "collection",
        "timestamp": "2026-01-15T10:00:00Z",
        "entry": [{"fullUrl": refs[label], "resource": resource} for label, resource in resources],
    }


def build_invalid_reference_bundle(seed: int = FIXTURE_SEED) -> dict[str, Any]:
    """Return valid FHIR JSON structure with one deliberately unresolved subject reference."""

    patient_id = _id("patient", seed)
    observation_id = _id("broken-observation", seed)
    return {
        "resourceType": "Bundle",
        "id": _id("broken-bundle", seed),
        "meta": _meta(),
        "identifier": {
            "system": "https://mage-med.example/synthetic-bundle-id",
            "value": f"SYNTHETIC-BROKEN-REFERENCE-{seed}",
        },
        "type": "collection",
        "timestamp": "2026-01-15T10:00:00Z",
        "entry": [
            {
                "fullUrl": f"urn:uuid:{patient_id}",
                "resource": {
                    "resourceType": "Patient",
                    "id": patient_id,
                    "meta": _meta(),
                    "name": [{"text": "SYNTHETIC Broken Reference Testpatient"}],
                },
            },
            {
                "fullUrl": f"urn:uuid:{observation_id}",
                "resource": {
                    "resourceType": "Observation",
                    "id": observation_id,
                    "meta": _meta(),
                    "status": "final",
                    "code": {"text": "SYNTHETIC reference-resolution test"},
                    "subject": {"reference": "Patient/DELIBERATELY-MISSING"},
                    "effectiveDateTime": "2026-01-15T08:45:00Z",
                    "valueString": "SYNTHETIC test value",
                },
            },
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=FIXTURE_SEED)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "synthetic_patient_bundle.json": build_valid_bundle(args.seed),
        "synthetic_invalid_reference_bundle.json": build_invalid_reference_bundle(args.seed),
    }
    for filename, payload in fixtures.items():
        (args.output_dir / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
