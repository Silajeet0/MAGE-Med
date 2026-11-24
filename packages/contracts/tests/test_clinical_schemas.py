from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from mage_med_contracts import (
    Allergy,
    AssertionType,
    ClinicalAssertion,
    ClinicalNote,
    CodeableConcept,
    Condition,
    DataModality,
    Encounter,
    Identifier,
    ImportManifest,
    ImportStatus,
    MedicationRequestSummary,
    NoteContentOrigin,
    NoteType,
    Observation,
    Patient,
    Provenance,
    Quantity,
    ReferenceRange,
    SourceArtifact,
    SourceFormat,
    SourceReference,
    VerificationStatus,
)
from pydantic import ValidationError

ARTIFACT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
MANIFEST_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
RUN_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
PATIENT_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
ENCOUNTER_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
IMPORTED_AT = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)


def provenance() -> Provenance:
    return Provenance(
        import_manifest_id=MANIFEST_ID,
        importer_name="canonical-contract-test",
        importer_version="1.0.0",
        transformation_version="1.0.0",
        run_id=RUN_ID,
        actor_id="test-suite",
        synthetic=True,
        seed=20261123,
    )


def fact_fields(
    internal_id: UUID,
    resource_type: str,
    *,
    patient_id: UUID | None = PATIENT_ID,
    encounter_id: UUID | None = ENCOUNTER_ID,
    assertion_type: AssertionType = AssertionType.OBSERVED,
) -> dict[str, object]:
    return {
        "internal_id": internal_id,
        "source_reference": SourceReference(
            source_artifact_id=ARTIFACT_ID,
            source_locator=f"bundle.json#/{resource_type}/{internal_id}",
            resource_type=resource_type,
            resource_id=str(internal_id),
        ),
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "event_time": datetime(2026, 1, 15, 9, 0, tzinfo=UTC),
        "recorded_time": datetime(2026, 1, 15, 9, 5, tzinfo=UTC),
        "imported_at": IMPORTED_AT,
        "provenance": provenance(),
        "assertion_type": assertion_type,
    }


def test_all_canonical_record_schemas_validate() -> None:
    patient = Patient(
        **fact_fields(PATIENT_ID, "Patient", patient_id=None, encounter_id=None),
        identifiers=[Identifier(system="urn:test", value="SYNTHETIC-001")],
        family_name="SYNTHETIC-Testpatient",
        birth_date=date(1975, 1, 1),
    )
    encounter = Encounter(
        **fact_fields(ENCOUNTER_ID, "Encounter", encounter_id=None),
        status="finished",
        period_start=datetime(2026, 1, 15, 9, 0, tzinfo=UTC),
        period_end=datetime(2026, 1, 15, 9, 30, tzinfo=UTC),
    )
    condition = Condition(
        **fact_fields(UUID("11111111-1111-4111-8111-111111111111"), "Condition"),
        code=CodeableConcept(system="http://snomed.info/sct", code="44054006"),
    )
    observation = Observation(
        **fact_fields(UUID("22222222-2222-4222-8222-222222222222"), "Observation"),
        code=CodeableConcept(system="http://loinc.org", code="4548-4"),
        status="final",
        value_quantity=Quantity(value=Decimal("7.2"), unit="%"),
        reference_range=[ReferenceRange(high=Decimal("6.5"), unit="%")],
    )
    medication = MedicationRequestSummary(
        **fact_fields(UUID("33333333-3333-4333-8333-333333333333"), "MedicationRequest"),
        medication=CodeableConcept(code="860975", text="SYNTHETIC metformin"),
        status="active",
        intent="order",
    )
    allergy = Allergy(
        **fact_fields(UUID("44444444-4444-4444-8444-444444444444"), "AllergyIntolerance"),
        substance=CodeableConcept(code="764146007", text="SYNTHETIC penicillin"),
    )
    note = ClinicalNote(
        **fact_fields(
            UUID("55555555-5555-4555-8555-555555555555"),
            "DocumentReference",
            assertion_type=AssertionType.OBSERVED,
        ),
        note_type=NoteType.CONSULTATION,
        original_text="SYNTHETIC fictional consultation note.",
        text="SYNTHETIC fictional consultation note.",
        content_origin=NoteContentOrigin.FHIR_EMBEDDED,
    )

    assert patient.schema_version == "1.0.0"
    assert encounter.patient_id == PATIENT_ID
    assert condition.code.code == "44054006"
    assert observation.value_quantity.value == Decimal("7.2")
    assert medication.record_type == "medication_request"
    assert allergy.categories == []
    assert note.modality is DataModality.UNSTRUCTURED_CLINICAL_TEXT


def test_original_fhir_resource_is_preserved_exactly() -> None:
    original = {
        "resourceType": "Observation",
        "id": "synthetic-observation",
        "valueQuantity": {"value": 7.2, "unit": "%"},
    }
    artifact = SourceArtifact(
        internal_id=ARTIFACT_ID,
        modality=DataModality.STRUCTURED_CLINICAL_DATA,
        source_format=SourceFormat.FHIR_R4_JSON,
        source_locator="data/synthetic/example.json",
        original_filename="example.json",
        media_type="application/fhir+json",
        sha256="a" * 64,
        raw_content=original,
        imported_at=IMPORTED_AT,
        synthetic=True,
    )

    restored = SourceArtifact.model_validate_json(artifact.model_dump_json())
    assert restored.raw_content == original
    assert restored.raw_content is not original


def test_assertion_type_is_distinct_from_verification_status() -> None:
    assert {value.value for value in AssertionType} == {
        "observed",
        "extracted",
        "model_inferred",
        "hypothesized",
        "clinician_confirmed",
        "clinician_rejected",
    }
    assert not (
        {value.value for value in AssertionType} & {value.value for value in VerificationStatus}
    )

    confirmed = ClinicalAssertion(
        **fact_fields(
            UUID("66666666-6666-4666-8666-666666666666"),
            "DocumentReference",
            assertion_type=AssertionType.CLINICIAN_CONFIRMED,
        ),
        subject_record_type="clinical_note",
        subject_record_id=UUID("55555555-5555-4555-8555-555555555555"),
        predicate="contains_statement",
        value="SYNTHETIC verified test statement",
        modality=DataModality.UNSTRUCTURED_CLINICAL_TEXT,
        verification_status=VerificationStatus.VERIFIED,
    )
    assert confirmed.confidence is None

    rejected = confirmed.model_copy(
        update={
            "assertion_type": AssertionType.CLINICIAN_REJECTED,
            "verification_status": VerificationStatus.REJECTED,
        }
    )
    assert (
        ClinicalAssertion.model_validate(rejected.model_dump()).verification_status
        is VerificationStatus.REJECTED
    )

    with pytest.raises(ValidationError, match="confidence is not meaningful"):
        ClinicalAssertion(
            **fact_fields(
                UUID("77777777-7777-4777-8777-777777777777"),
                "Observation",
                assertion_type=AssertionType.OBSERVED,
            ),
            subject_record_type="observation",
            subject_record_id=UUID("22222222-2222-4222-8222-222222222222"),
            predicate="has_value",
            value="7.2 %",
            modality=DataModality.STRUCTURED_CLINICAL_DATA,
            confidence=Decimal("0.9"),
        )


def test_units_ranges_and_timezone_dates_are_validated() -> None:
    with pytest.raises(ValidationError, match="reference range unit"):
        Observation(
            **fact_fields(UUID("88888888-8888-4888-8888-888888888888"), "Observation"),
            code=CodeableConcept(text="SYNTHETIC laboratory value"),
            status="final",
            value_quantity=Quantity(value=Decimal("7.2"), unit="%"),
            reference_range=[ReferenceRange(high=Decimal("6.5"), unit="mmol/L")],
        )

    fields = fact_fields(UUID("99999999-9999-4999-8999-999999999999"), "Condition")
    fields["imported_at"] = datetime(2026, 1, 15, 10, 0)
    with pytest.raises(ValidationError, match="explicit UTC offset"):
        Condition(**fields, code=CodeableConcept(text="SYNTHETIC condition"))

    with pytest.raises(ValidationError, match="low cannot exceed high"):
        ReferenceRange(low=Decimal("8"), high=Decimal("6"), unit="%")


def test_incomplete_optional_fields_remain_explicitly_absent() -> None:
    condition = Condition(
        **fact_fields(UUID("12121212-1212-4212-8212-121212121212"), "Condition"),
        code=CodeableConcept(text="SYNTHETIC condition with sparse metadata"),
    )
    absent_observation = Observation(
        **fact_fields(UUID("13131313-1313-4313-8313-131313131313"), "Observation"),
        code=CodeableConcept(text="SYNTHETIC missing measurement"),
        status="final",
        data_absent_reason=CodeableConcept(code="unknown"),
    )

    assert condition.onset_time is None
    assert condition.clinical_status is None
    assert absent_observation.value_quantity is None
    assert absent_observation.data_absent_reason.code == "unknown"


def test_invalid_versions_and_manifest_outcomes_are_rejected() -> None:
    fields = fact_fields(UUID("14141414-1414-4414-8414-141414141414"), "Condition")
    fields["schema_version"] = "2.0.0"
    with pytest.raises(ValidationError):
        Condition(**fields, code=CodeableConcept(text="SYNTHETIC"))

    manifest = ImportManifest(
        internal_id=MANIFEST_ID,
        dataset_id="mage-med-synthetic-fhir-r4",
        dataset_version="1.0.0",
        source_format=SourceFormat.FHIR_R4_JSON,
        status=ImportStatus.SUCCEEDED,
        source_artifact_ids=[ARTIFACT_ID],
        started_at=datetime(2026, 1, 15, 9, 59, tzinfo=UTC),
        completed_at=IMPORTED_AT,
        importer_name="future-fhir-importer",
        importer_version="1.0.0",
        synthetic=True,
        seed=20261123,
        record_counts={"Patient": 1},
    )
    assert manifest.record_counts == {"Patient": 1}

    with pytest.raises(ValidationError, match="completed imports require"):
        ImportManifest.model_validate({**manifest.model_dump(), "completed_at": None})
