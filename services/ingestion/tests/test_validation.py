import copy
import json
from pathlib import Path

import pytest
from mage_med_ingestion import FhirDocumentError, parse_fhir_json

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "data/synthetic/fhir/r4/synthetic_patient_bundle.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parses_bundle_and_individual_resource_with_base_validation() -> None:
    payload = _fixture()
    document = parse_fhir_json(json.dumps(payload).encode())
    assert document.root_resource_type == "Bundle"
    assert len(document.resources) == 7
    assert all(resource.structurally_valid for resource in document.resources)

    patient = copy.deepcopy(payload["entry"][0]["resource"])  # type: ignore[index]
    individual = parse_fhir_json(json.dumps(patient).encode())
    assert individual.root_resource_type == "Patient"
    assert individual.resources[0].aliases[0].startswith("Patient/")


@pytest.mark.parametrize("content", [b"", b"not-json", b"[]", b'{"id":"missing-type"}'])
def test_rejects_corrupt_or_non_fhir_documents(content: bytes) -> None:
    with pytest.raises(FhirDocumentError):
        parse_fhir_json(content)


def test_rejects_duplicate_full_url_as_ambiguous() -> None:
    payload = _fixture()
    duplicated = copy.deepcopy(payload["entry"][0])  # type: ignore[index]
    duplicated["resource"]["id"] = "different-id"
    payload["entry"].append(duplicated)  # type: ignore[union-attr]

    with pytest.raises(FhirDocumentError, match="ambiguous"):
        parse_fhir_json(json.dumps(payload).encode())


def test_marks_wrong_base_type_as_structurally_invalid() -> None:
    payload = _fixture()
    observation = payload["entry"][3]["resource"]  # type: ignore[index]
    observation["status"] = 42
    document = parse_fhir_json(json.dumps(payload).encode())

    parsed = document.resources[3]
    assert parsed.structurally_valid is False
    assert parsed.issues == ("FHIR R4 base structural validation failed",)
