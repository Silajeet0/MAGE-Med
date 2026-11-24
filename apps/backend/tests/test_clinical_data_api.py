import copy
import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from conftest import AvailableConnectivity
from httpx2 import ASGITransport, AsyncClient
from mage_med_backend.config import Settings
from mage_med_backend.main import create_app

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "data/synthetic/fhir/r4/synthetic_patient_bundle.json"

pytestmark = pytest.mark.anyio


def _migrate(settings: Settings) -> None:
    config = Config(ROOT / "apps/backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


def _extended_bundle() -> bytes:
    bundle = json.loads(FIXTURE.read_text(encoding="utf-8"))
    patient = bundle["entry"][0]["resource"]
    encounter = bundle["entry"][1]["resource"]
    observation = bundle["entry"][3]["resource"]

    second_encounter = copy.deepcopy(encounter)
    second_encounter["id"] = "21111111-1111-4111-8111-111111111111"
    second_encounter["period"] = {
        "start": "2026-02-20T10:00:00Z",
        "end": "2026-02-20T10:30:00Z",
    }

    contradiction = copy.deepcopy(observation)
    contradiction["id"] = "22222222-2222-4222-8222-222222222222"
    contradiction["valueQuantity"]["value"] = 8.1

    absent = copy.deepcopy(observation)
    absent["id"] = "23333333-3333-4333-8333-333333333333"
    absent["code"] = {
        "coding": [{"system": "http://loinc.org", "code": "718-7", "display": "Hemoglobin"}]
    }
    absent.pop("valueQuantity")
    absent.pop("referenceRange")
    absent["effectiveDateTime"] = "2026-02-20T10:05:00Z"
    absent["dataAbsentReason"] = {
        "coding": [
            {
                "system": "http://terminology.hl7.org/CodeSystem/data-absent-reason",
                "code": "not-performed",
            }
        ]
    }

    negative = copy.deepcopy(observation)
    negative["id"] = "24444444-4444-4444-8444-444444444444"
    negative["code"] = {
        "coding": [{"system": "http://loinc.org", "code": "94500-6", "display": "SARS-CoV-2 RNA"}]
    }
    negative.pop("valueQuantity")
    negative.pop("referenceRange")
    negative["effectiveDateTime"] = "2026-02-20T10:10:00Z"
    negative["valueString"] = "Negative"

    second_patient = copy.deepcopy(patient)
    second_patient["id"] = "25555555-5555-4555-8555-555555555555"
    second_patient["name"] = [{"family": "SYNTHETIC-Duplicate", "given": ["Test"]}]

    for resource in (second_encounter, contradiction, absent, negative, second_patient):
        bundle["entry"].append({"fullUrl": f"urn:uuid:{resource['id']}", "resource": resource})
    return json.dumps(bundle, sort_keys=True).encode()


async def test_end_to_end_patient_timeline_provenance_and_quality(settings: Settings) -> None:
    _migrate(settings)
    app = create_app(settings, neo4j_connectivity=AvailableConnectivity())
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            imported = await client.post(
                "/api/v1/import/fhir",
                files={"file": ("extended-synthetic.json", _extended_bundle(), "application/json")},
                data={
                    "dataset_id": "clinical-access-synthetic",
                    "synthetic_seed": "20261123",
                },
            )
            assert imported.status_code == 201, imported.text
            resources = imported.json()["resources"]
            patient = next(
                item
                for item in resources
                if item["resource_type"] == "Patient"
                and item["resource_id"] == "3a00db93-1f84-5801-b358-bf9b46340c8d"
            )
            encounters = [item for item in resources if item["resource_type"] == "Encounter"]
            patient_id = patient["normalized_id"]
            other_patient_id = next(
                item["normalized_id"]
                for item in resources
                if item["resource_type"] == "Patient"
                and item["resource_id"] == "25555555-5555-4555-8555-555555555555"
            )
            encounter_id = encounters[0]["normalized_id"]

            text_import = await client.post(
                "/api/v1/import/text",
                files={
                    "file": (
                        "timeline-note.txt",
                        b"SYNTHETIC timeline note; not clinician-authored.",
                        "text/plain",
                    )
                },
                data={
                    "dataset_id": "clinical-access-synthetic",
                    "synthetic": "true",
                    "synthetic_seed": "20261123",
                    "patient_id": patient_id,
                    "encounter_id": encounter_id,
                    "note_type": "progress",
                    "authored_at": "2026-02-21T12:00:00Z",
                    "source_label": "SYNTHETIC TEST FIXTURE; not clinician-authored",
                },
            )
            assert text_import.status_code == 201, text_import.text

            scoped_list = await client.get(
                "/api/v1/patients", headers={"X-Patient-Scope": patient_id}
            )
            assert scoped_list.status_code == 200
            assert scoped_list.json()["page"]["total"] == 1
            detail = await client.get(f"/api/v1/patients/{patient_id}")
            assert detail.status_code == 200
            assert detail.json()["encounter_count"] == 2
            assert detail.json()["observation_count"] == 4

            wrong_scope = await client.get(
                f"/api/v1/patients/{patient_id}",
                headers={"X-Patient-Scope": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"},
            )
            assert wrong_scope.status_code == 403

            timeline = await client.get(
                f"/api/v1/patients/{patient_id}/timeline", params={"page_size": 100}
            )
            assert timeline.status_code == 200, timeline.text
            timeline_body = timeline.json()
            types = {item["record_type"] for item in timeline_body["items"]}
            assert {
                "encounter",
                "condition",
                "observation",
                "medication_request",
                "allergy",
                "clinical_note",
            }.issubset(types)
            assert timeline_body["items"][0]["event_time"].startswith("2026-02-21")
            absent_entry = next(
                item
                for item in timeline_body["items"]
                if item["details"].get("data_absent_reason") is not None
            )
            negative_entry = next(
                item for item in timeline_body["items"] if item["details"].get("value_text")
            )
            assert absent_entry["value_state"] == "missing"
            assert negative_entry["value_state"] == "observed_negative"

            observations = await client.get(
                f"/api/v1/patients/{patient_id}/observations",
                params={"code": "4548-4"},
            )
            assert observations.status_code == 200
            assert observations.json()["page"]["total"] == 2
            for item in observations.json()["items"]:
                assert item["value_unit"] == "%"
                assert item["value_unit_system"] == "http://unitsofmeasure.org"
                assert item["reference_range"][0]["high"] == "6.5"

            notes = await client.get(f"/api/v1/patients/{patient_id}/notes")
            assert notes.status_code == 200
            assert notes.json()["page"]["total"] == 2
            source_href = next(
                item["source"]["provenance_href"]
                for item in timeline_body["items"]
                if item["record_type"] == "observation"
            )
            source = await client.get(source_href)
            assert source.status_code == 200, source.text
            assert source.json()["import_diagnostic"]["duplicate_normalized_mappings"] == 0
            assert source.json()["import_diagnostic"]["replay_attempts_persisted"] is False
            assert source.json()["raw_content"] is None
            assert any(
                item["record_type"] == "observation" for item in source.json()["normalized_records"]
            )
            cross_patient_source = await client.get(
                source_href.split("?")[0], params={"patient_id": other_patient_id}
            )
            assert cross_patient_source.status_code == 200
            assert all(
                item["patient_id"] == other_patient_id
                for item in cross_patient_source.json()["normalized_records"]
            )
            multi_patient_raw = await client.get(
                source_href.split("?")[0],
                params={"patient_id": patient_id, "include_content": "true"},
            )
            assert multi_patient_raw.status_code == 404

            quality = await client.get(
                "/api/v1/data-quality", params={"dataset_id": "clinical-access-synthetic"}
            )
            assert quality.status_code == 200
            issue_counts = {item["category"]: item["count"] for item in quality.json()["issues"]}
            assert issue_counts["ambiguous_patient_identifiers"] == 1
            assert issue_counts["contradictory_observations"] == 1
            assert (
                "missing data is not an observed negative finding"
                in quality.json()["human_readable"]
            )
            text_report = await client.get(
                "/api/v1/data-quality/report",
                params={"dataset_id": "clinical-access-synthetic"},
            )
            assert text_report.status_code == 200
            assert "unsupported_fhir_types" in text_report.text
