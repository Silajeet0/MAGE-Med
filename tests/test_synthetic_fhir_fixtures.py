import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.generate_synthetic_fhir import (
    FIXTURE_SEED,
    build_invalid_reference_bundle,
    build_valid_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "data/synthetic/fhir/r4"
MANIFEST_PATH = ROOT / "data/manifests/synthetic_fhir_r4.json"

REQUIRED_FIELDS = {
    "Patient": set(),
    "Encounter": {"status", "class"},
    "Condition": {"subject"},
    "Observation": {"status", "code"},
    "MedicationRequest": {"status", "intent", "subject"},
    "AllergyIntolerance": {"patient"},
    "DocumentReference": {"status", "content"},
}


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _references(value: Any) -> list[str]:
    if isinstance(value, dict):
        found = [value["reference"]] if isinstance(value.get("reference"), str) else []
        return found + [ref for child in value.values() for ref in _references(child)]
    if isinstance(value, list):
        return [ref for child in value for ref in _references(child)]
    return []


def _unresolved_local_references(bundle: dict[str, Any]) -> set[str]:
    entries = bundle["entry"]
    resolvable = {entry["fullUrl"] for entry in entries}
    resolvable.update(
        f"{entry['resource']['resourceType']}/{entry['resource']['id']}" for entry in entries
    )
    return {
        reference
        for entry in entries
        for reference in _references(entry["resource"])
        if reference not in resolvable
    }


def test_valid_fixture_is_deterministic_linked_fhir_r4_json() -> None:
    committed = _load("synthetic_patient_bundle.json")
    generated = build_valid_bundle(FIXTURE_SEED)

    assert committed == generated
    assert committed["resourceType"] == "Bundle"
    assert committed["type"] == "collection"
    resources = [entry["resource"] for entry in committed["entry"]]
    assert {resource["resourceType"] for resource in resources} == set(REQUIRED_FIELDS)
    assert _unresolved_local_references(committed) == set()

    for entry in committed["entry"]:
        resource = entry["resource"]
        assert entry["fullUrl"].startswith("urn:uuid:")
        assert resource["id"] == entry["fullUrl"].removeprefix("urn:uuid:")
        assert resource["resourceType"] in REQUIRED_FIELDS
        assert REQUIRED_FIELDS[resource["resourceType"]] <= resource.keys()
        assert any(tag["code"] == "SYNTHETIC" for tag in resource["meta"]["tag"])

    medication = next(
        resource for resource in resources if resource["resourceType"] == "MedicationRequest"
    )
    assert "medicationCodeableConcept" in medication
    observation = next(
        resource for resource in resources if resource["resourceType"] == "Observation"
    )
    assert observation["valueQuantity"]["system"] == "http://unitsofmeasure.org"
    assert observation["referenceRange"][0]["high"]["unit"] == "%"


def test_deliberately_incorrect_reference_is_detected() -> None:
    committed = _load("synthetic_invalid_reference_bundle.json")
    assert committed == build_invalid_reference_bundle(FIXTURE_SEED)
    assert _unresolved_local_references(committed) == {"Patient/DELIBERATELY-MISSING"}


def test_dataset_manifest_labels_synthetic_data_and_matches_checksums() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert manifest["contains_real_patient_data"] is False
    assert manifest["seed"] == FIXTURE_SEED

    for item in manifest["files"]:
        fixture_path = ROOT / item["path"]
        digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
        assert digest == item["sha256"]
