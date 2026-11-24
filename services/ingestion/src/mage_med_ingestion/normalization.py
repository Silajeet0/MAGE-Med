"""Reference-safe normalization from FHIR R4 JSON into canonical contracts."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid5

from mage_med_contracts import (
    Allergy,
    AssertionType,
    CanonicalClinicalRecord,
    ClinicalNote,
    CodeableConcept,
    Condition,
    Encounter,
    Identifier,
    MedicationRequestSummary,
    NoteContentOrigin,
    NoteType,
    Observation,
    Patient,
    Provenance,
    Quantity,
    ReferenceRange,
    ResourceImportOutcome,
    ResourceImportStatus,
    SourceReference,
)
from pydantic import ValidationError

from mage_med_ingestion.clinical_text import (
    AttachmentUnavailable,
    LocalTextAttachmentResolver,
    clean_clinical_text,
)
from mage_med_ingestion.validation import ParsedFhirDocument, ParsedResource

NORMALIZED_ID_NAMESPACE = UUID("1489df13-ce99-4326-861f-a5bb6467fe9c")
IMPORTER_NAME = "mage-med-fhir-r4"
IMPORTER_VERSION = "1.0.0"
TRANSFORMATION_VERSION = "1.0.0"

RESOURCE_TABLES = {
    "Patient": "patients",
    "Encounter": "encounters",
    "Condition": "conditions",
    "Observation": "observations",
    "MedicationRequest": "medication_requests",
    "AllergyIntolerance": "allergies",
    "DocumentReference": "clinical_notes",
}


class FhirNormalizationError(ValueError):
    """A safe resource-level normalization failure."""


class FhirAttachmentUnavailable(FhirNormalizationError):
    """A DocumentReference attachment could not be safely resolved."""


@dataclass(frozen=True, slots=True)
class ResolvedReference:
    """Normalized target returned by local or persisted reference resolution."""

    normalized_type: str
    normalized_id: UUID
    patient_id: UUID | None = None


ExternalReferenceResolver = Callable[[str, str], ResolvedReference | None]


@dataclass(frozen=True, slots=True)
class NormalizationContext:
    dataset_id: str
    source_artifact_id: UUID
    import_manifest_id: UUID
    run_id: UUID
    source_locator: str
    imported_at: datetime
    actor_id: str
    synthetic_seed: int | None = None
    max_note_bytes: int = 256 * 1024


@dataclass(frozen=True, slots=True)
class NormalizedResource:
    parsed: ParsedResource
    record: CanonicalClinicalRecord
    normalized_table: str


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    records: tuple[NormalizedResource, ...]
    outcomes: tuple[ResourceImportOutcome, ...]


def normalized_id_for(dataset_id: str, resource_type: str, resource_id: str) -> UUID:
    """Return the stable internal ID for a local FHIR source identity."""

    return uuid5(NORMALIZED_ID_NAMESPACE, f"fhir-r4:{dataset_id}:{resource_type}/{resource_id}")


def _source_key(context: NormalizationContext, resource: ParsedResource) -> str:
    return f"fhir-r4:{context.dataset_id}:{resource.source_key.removeprefix('fhir-r4:')}"


def _is_synthetic(resource: dict[str, Any]) -> bool:
    meta = resource.get("meta")
    tags = meta.get("tag", []) if isinstance(meta, dict) else []
    return any(isinstance(tag, dict) and tag.get("code") == "SYNTHETIC" for tag in tags)


def _provenance(context: NormalizationContext, resource: ParsedResource) -> Provenance:
    synthetic = _is_synthetic(resource.raw)
    if synthetic and context.synthetic_seed is None:
        raise FhirNormalizationError("synthetic resource requires an explicit generation seed")
    return Provenance(
        import_manifest_id=context.import_manifest_id,
        importer_name=IMPORTER_NAME,
        importer_version=IMPORTER_VERSION,
        transformation_version=TRANSFORMATION_VERSION,
        run_id=context.run_id,
        actor_id=context.actor_id,
        synthetic=synthetic,
        seed=context.synthetic_seed if synthetic else None,
    )


def _concept(value: Any, *, required: bool = False) -> CodeableConcept | None:
    if value is None and not required:
        return None
    if not isinstance(value, dict):
        raise FhirNormalizationError("coded element must be an object")
    text = value.get("text") if isinstance(value.get("text"), str) else None
    codings = value.get("coding", [])
    if not isinstance(codings, list):
        raise FhirNormalizationError("coding must be an array")
    for coding in codings:
        if not isinstance(coding, dict):
            raise FhirNormalizationError("coding entries must be objects")
        code = coding.get("code")
        if isinstance(code, str) and code:
            return CodeableConcept(
                system=coding.get("system") if isinstance(coding.get("system"), str) else None,
                code=code,
                display=coding.get("display") if isinstance(coding.get("display"), str) else None,
                version=coding.get("version") if isinstance(coding.get("version"), str) else None,
                text=text,
            )
    if text:
        return CodeableConcept(text=text)
    raise FhirNormalizationError("coded element has no usable code or text")


def _required_concept(value: Any) -> CodeableConcept:
    concept = _concept(value, required=True)
    if concept is None:  # Defensive narrowing; required=True either returns or raises.
        raise FhirNormalizationError("coded element is required")
    return concept


def _coding(value: Any) -> CodeableConcept | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise FhirNormalizationError("coding element must be an object")
    code = value.get("code")
    if not isinstance(code, str) or not code:
        raise FhirNormalizationError("coding element has no usable code")
    return CodeableConcept(
        system=value.get("system") if isinstance(value.get("system"), str) else None,
        code=code,
        display=value.get("display") if isinstance(value.get("display"), str) else None,
        version=value.get("version") if isinstance(value.get("version"), str) else None,
    )


def _reference_value(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise FhirNormalizationError(f"{field_name} reference must be an object")
    reference = value.get("reference")
    if not isinstance(reference, str) or not reference:
        raise FhirNormalizationError(f"{field_name} requires an explicit reference")
    return reference


def _common(
    context: NormalizationContext,
    resource: ParsedResource,
    *,
    patient_id: UUID | None,
    encounter_id: UUID | None,
    event_time: Any = None,
    recorded_time: Any = None,
) -> dict[str, Any]:
    if resource.resource_type is None or resource.resource_id is None:
        raise FhirNormalizationError("resource identity is incomplete")
    suffix = (
        f"entry/{resource.index}"
        if context.source_locator.endswith(".json")
        else f"resource/{resource.index}"
    )
    return {
        "internal_id": normalized_id_for(
            context.dataset_id, resource.resource_type, resource.resource_id
        ),
        "source_reference": SourceReference(
            source_artifact_id=context.source_artifact_id,
            source_locator=f"{context.source_locator}#{suffix}",
            resource_type=resource.resource_type,
            resource_id=resource.resource_id,
        ),
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "event_time": event_time,
        "recorded_time": recorded_time,
        "imported_at": context.imported_at,
        "provenance": _provenance(context, resource),
        "assertion_type": AssertionType.OBSERVED,
    }


def _resolve(
    reference: str | None,
    expected_resource_type: str,
    local_targets: dict[str, ResolvedReference],
    external_resolver: ExternalReferenceResolver,
) -> ResolvedReference | None:
    if reference is None:
        return None
    target = local_targets.get(reference)
    if target is None:
        target = external_resolver(reference, expected_resource_type)
    if target is None:
        raise FhirNormalizationError(f"unresolved {expected_resource_type} reference")
    expected_table = RESOURCE_TABLES[expected_resource_type]
    if target.normalized_type != expected_table:
        raise FhirNormalizationError(f"reference does not resolve to {expected_resource_type}")
    return target


def _reference_range(raw_ranges: Any) -> list[ReferenceRange]:
    if raw_ranges is None:
        return []
    if not isinstance(raw_ranges, list):
        raise FhirNormalizationError("Observation.referenceRange must be an array")
    ranges: list[ReferenceRange] = []
    for raw_range in raw_ranges:
        if not isinstance(raw_range, dict):
            raise FhirNormalizationError("Observation reference range must be an object")
        low: dict[str, Any] = raw_range["low"] if isinstance(raw_range.get("low"), dict) else {}
        high: dict[str, Any] = raw_range["high"] if isinstance(raw_range.get("high"), dict) else {}
        unit_source = low or high
        ranges.append(
            ReferenceRange(
                low=low.get("value"),
                high=high.get("value"),
                unit=unit_source.get("unit"),
                unit_system=unit_source.get("system"),
                unit_code=unit_source.get("code"),
                text=raw_range.get("text"),
            )
        )
    return ranges


def _document_text(
    resource: dict[str, Any],
    context: NormalizationContext,
    attachment_resolver: LocalTextAttachmentResolver | None,
) -> tuple[str, str | None, Any, NoteContentOrigin, str | None]:
    content = resource.get("content")
    if not isinstance(content, list) or not content:
        raise FhirNormalizationError("DocumentReference requires content")
    linked_content_seen = False
    for item in content:
        attachment = item.get("attachment") if isinstance(item, dict) else None
        if not isinstance(attachment, dict):
            continue
        url = attachment.get("url")
        if url is not None:
            linked_content_seen = True
        encoded = attachment.get("data")
        if not isinstance(encoded, str):
            continue
        media_type = attachment.get("contentType")
        if not isinstance(media_type, str) or not media_type.startswith("text/"):
            raise FhirNormalizationError("embedded DocumentReference content must be text")
        try:
            decoded_bytes = base64.b64decode(encoded, validate=True)
            if len(decoded_bytes) > context.max_note_bytes:
                raise FhirAttachmentUnavailable(
                    "embedded DocumentReference text exceeds the configured size limit"
                )
            decoded = decoded_bytes.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise FhirNormalizationError(
                "DocumentReference text is not valid base64 UTF-8"
            ) from exc
        if not decoded.strip():
            raise FhirNormalizationError("DocumentReference text is empty")
        title = attachment.get("title") if isinstance(attachment.get("title"), str) else None
        return (
            decoded,
            title,
            attachment.get("creation"),
            NoteContentOrigin.FHIR_EMBEDDED,
            None,
        )
    if linked_content_seen:
        for item in content:
            attachment = item.get("attachment") if isinstance(item, dict) else None
            if not isinstance(attachment, dict) or not isinstance(attachment.get("url"), str):
                continue
            if attachment_resolver is None:
                raise FhirAttachmentUnavailable(
                    "unavailable linked DocumentReference: local attachment import root "
                    "is not configured"
                )
            try:
                resolved = attachment_resolver(
                    attachment["url"],
                    attachment.get("contentType")
                    if isinstance(attachment.get("contentType"), str)
                    else None,
                )
            except AttachmentUnavailable as exc:
                raise FhirAttachmentUnavailable(
                    f"unavailable linked DocumentReference: {exc}"
                ) from exc
            title = attachment.get("title") if isinstance(attachment.get("title"), str) else None
            return (
                resolved.text,
                title,
                attachment.get("creation"),
                NoteContentOrigin.FHIR_LOCAL_FILE,
                resolved.source_label,
            )
    raise FhirNormalizationError("DocumentReference has no supported embedded text")


def _normalize_one(
    resource: ParsedResource,
    context: NormalizationContext,
    patient_target: ResolvedReference | None,
    encounter_target: ResolvedReference | None,
    attachment_resolver: LocalTextAttachmentResolver | None,
) -> CanonicalClinicalRecord:
    raw = resource.raw
    resource_type = resource.resource_type
    patient_id = patient_target.normalized_id if patient_target else None
    encounter_id = encounter_target.normalized_id if encounter_target else None
    if (
        patient_id is not None
        and encounter_target is not None
        and encounter_target.patient_id is not None
        and encounter_target.patient_id != patient_id
    ):
        raise FhirNormalizationError(
            "patient and encounter references resolve to different patients"
        )

    if resource_type == "Patient":
        names = raw.get("name", [])
        primary_name = names[0] if isinstance(names, list) and names else {}
        identifiers = raw.get("identifier", [])
        return Patient(
            **_common(context, resource, patient_id=None, encounter_id=None),
            identifiers=[
                Identifier(system=item.get("system"), value=item["value"])
                for item in identifiers
                if isinstance(item, dict) and isinstance(item.get("value"), str)
            ],
            family_name=(primary_name.get("family") if isinstance(primary_name, dict) else None),
            given_names=(primary_name.get("given", []) if isinstance(primary_name, dict) else []),
            birth_date=raw.get("birthDate"),
            administrative_gender=raw.get("gender"),
            active=raw.get("active"),
        )
    if resource_type == "Encounter":
        period: dict[str, Any] = raw["period"] if isinstance(raw.get("period"), dict) else {}
        types = raw.get("type", [])
        return Encounter(
            **_common(
                context,
                resource,
                patient_id=patient_id,
                encounter_id=None,
                event_time=period.get("start"),
            ),
            status=raw["status"],
            class_code=_coding(raw.get("class")),
            encounter_type=_concept(types[0]) if isinstance(types, list) and types else None,
            period_start=period.get("start"),
            period_end=period.get("end"),
        )
    if resource_type == "Condition":
        return Condition(
            **_common(
                context,
                resource,
                patient_id=patient_id,
                encounter_id=encounter_id,
                event_time=raw.get("onsetDateTime") or raw.get("onsetDate"),
                recorded_time=raw.get("recordedDate"),
            ),
            code=_required_concept(raw.get("code")),
            clinical_status=_concept(raw.get("clinicalStatus")),
            verification_status=_concept(raw.get("verificationStatus")),
            onset_time=raw.get("onsetDateTime") or raw.get("onsetDate"),
            abatement_time=raw.get("abatementDateTime") or raw.get("abatementDate"),
        )
    if resource_type == "Observation":
        quantity_raw = raw.get("valueQuantity")
        quantity = None
        if isinstance(quantity_raw, dict):
            if quantity_raw.get("value") is None:
                raise FhirNormalizationError("Observation quantity requires a value")
            quantity = Quantity(
                value=Decimal(str(quantity_raw["value"])),
                unit=quantity_raw.get("unit"),
                system=quantity_raw.get("system"),
                code=quantity_raw.get("code"),
            )
        return Observation(
            **_common(
                context,
                resource,
                patient_id=patient_id,
                encounter_id=encounter_id,
                event_time=raw.get("effectiveDateTime"),
                recorded_time=raw.get("issued"),
            ),
            code=_required_concept(raw.get("code")),
            status=raw["status"],
            value_quantity=quantity,
            value_text=raw.get("valueString"),
            data_absent_reason=_concept(raw.get("dataAbsentReason")),
            reference_range=_reference_range(raw.get("referenceRange")),
        )
    if resource_type == "MedicationRequest":
        medication = raw.get("medicationCodeableConcept")
        if medication is None:
            raise FhirNormalizationError("MedicationRequest medicationReference is not supported")
        dosages = raw.get("dosageInstruction", [])
        dosage_text = dosages[0].get("text") if isinstance(dosages, list) and dosages else None
        return MedicationRequestSummary(
            **_common(
                context,
                resource,
                patient_id=patient_id,
                encounter_id=encounter_id,
                event_time=raw.get("authoredOn"),
                recorded_time=raw.get("authoredOn"),
            ),
            medication=_required_concept(medication),
            status=raw["status"],
            intent=raw["intent"],
            authored_on=raw.get("authoredOn"),
            dosage_text=dosage_text,
        )
    if resource_type == "AllergyIntolerance":
        reactions: list[CodeableConcept] = []
        for reaction in raw.get("reaction", []):
            if not isinstance(reaction, dict):
                continue
            for manifestation in reaction.get("manifestation", []):
                concept = _concept(manifestation)
                if concept:
                    reactions.append(concept)
        return Allergy(
            **_common(
                context,
                resource,
                patient_id=patient_id,
                encounter_id=encounter_id,
                event_time=raw.get("onsetDateTime") or raw.get("recordedDate"),
                recorded_time=raw.get("recordedDate"),
            ),
            substance=_required_concept(raw.get("code")),
            clinical_status=_concept(raw.get("clinicalStatus")),
            verification_status=_concept(raw.get("verificationStatus")),
            allergy_type=raw.get("type"),
            categories=raw.get("category", []),
            criticality=raw.get("criticality"),
            reactions=reactions,
        )
    if resource_type == "DocumentReference":
        original_text, title, creation, content_origin, linked_source_label = _document_text(
            raw, context, attachment_resolver
        )
        authors = raw.get("author", [])
        author_reference = None
        author_label = None
        if isinstance(authors, list) and authors:
            author = authors[0]
            if isinstance(author, dict):
                author_reference = (
                    author.get("reference") if isinstance(author.get("reference"), str) else None
                )
                author_label = (
                    author.get("display") if isinstance(author.get("display"), str) else None
                )
        return ClinicalNote(
            **_common(
                context,
                resource,
                patient_id=patient_id,
                encounter_id=encounter_id,
                event_time=creation or raw.get("date"),
                recorded_time=raw.get("date"),
            ),
            note_type=NoteType.CONSULTATION,
            title=title or raw.get("description"),
            original_text=original_text,
            text=clean_clinical_text(original_text),
            authored_at=creation or raw.get("date"),
            author_reference=author_reference,
            source_label=linked_source_label or author_label,
            content_origin=content_origin,
        )
    raise FhirNormalizationError("unsupported resource type")


def normalize_document(
    document: ParsedFhirDocument,
    context: NormalizationContext,
    external_resolver: ExternalReferenceResolver,
    attachment_resolver: LocalTextAttachmentResolver | None = None,
) -> NormalizationResult:
    """Resolve references and normalize usable resources without guessing."""

    local_targets: dict[str, ResolvedReference] = {}
    records: list[NormalizedResource] = []
    indexed_outcomes: list[tuple[int, ResourceImportOutcome]] = []
    resource_priority = {"Patient": 0, "Encounter": 1}
    ordered_resources = sorted(
        document.resources,
        key=lambda resource: (
            resource_priority.get(resource.resource_type or "", 2),
            resource.index,
        ),
    )
    for resource in ordered_resources:
        if not resource.supported:
            indexed_outcomes.append(
                (
                    resource.index,
                    ResourceImportOutcome(
                        source_key=_source_key(context, resource),
                        resource_type=resource.resource_type,
                        resource_id=resource.resource_id,
                        full_url=resource.full_url,
                        status=ResourceImportStatus.UNSUPPORTED,
                        issues=list(resource.issues),
                    ),
                )
            )
            continue
        if not resource.structurally_valid:
            indexed_outcomes.append(
                (
                    resource.index,
                    ResourceImportOutcome(
                        source_key=_source_key(context, resource),
                        resource_type=resource.resource_type,
                        resource_id=resource.resource_id,
                        full_url=resource.full_url,
                        status=ResourceImportStatus.UNUSABLE,
                        issues=list(resource.issues),
                    ),
                )
            )
            continue
        try:
            raw = resource.raw
            patient_field = (
                "patient" if resource.resource_type == "AllergyIntolerance" else "subject"
            )
            patient_ref = (
                None
                if resource.resource_type == "Patient"
                else _reference_value(
                    raw.get(patient_field), f"{resource.resource_type}.{patient_field}"
                )
            )
            patient = _resolve(patient_ref, "Patient", local_targets, external_resolver)
            encounter_value: Any = raw.get("encounter")
            if resource.resource_type == "DocumentReference":
                context_value = raw.get("context")
                encounters = (
                    context_value.get("encounter", []) if isinstance(context_value, dict) else []
                )
                encounter_value = encounters[0] if encounters else None
            encounter_ref = _reference_value(encounter_value, f"{resource.resource_type}.encounter")
            encounter = _resolve(encounter_ref, "Encounter", local_targets, external_resolver)
            record = _normalize_one(resource, context, patient, encounter, attachment_resolver)
        except FhirAttachmentUnavailable as exc:
            indexed_outcomes.append(
                (
                    resource.index,
                    ResourceImportOutcome(
                        source_key=_source_key(context, resource),
                        resource_type=resource.resource_type,
                        resource_id=resource.resource_id,
                        full_url=resource.full_url,
                        status=ResourceImportStatus.UNAVAILABLE,
                        issues=[str(exc)],
                    ),
                )
            )
            continue
        except FhirNormalizationError as exc:
            indexed_outcomes.append(
                (
                    resource.index,
                    ResourceImportOutcome(
                        source_key=_source_key(context, resource),
                        resource_type=resource.resource_type,
                        resource_id=resource.resource_id,
                        full_url=resource.full_url,
                        status=ResourceImportStatus.UNUSABLE,
                        issues=[str(exc)],
                    ),
                )
            )
            continue
        except (ValidationError, ValueError, TypeError):
            indexed_outcomes.append(
                (
                    resource.index,
                    ResourceImportOutcome(
                        source_key=_source_key(context, resource),
                        resource_type=resource.resource_type,
                        resource_id=resource.resource_id,
                        full_url=resource.full_url,
                        status=ResourceImportStatus.UNUSABLE,
                        issues=["resource could not be safely normalized"],
                    ),
                )
            )
            continue
        table = RESOURCE_TABLES[resource.resource_type or ""]
        records.append(NormalizedResource(parsed=resource, record=record, normalized_table=table))
        indexed_outcomes.append(
            (
                resource.index,
                ResourceImportOutcome(
                    source_key=_source_key(context, resource),
                    resource_type=resource.resource_type,
                    resource_id=resource.resource_id,
                    full_url=resource.full_url,
                    status=ResourceImportStatus.IMPORTED,
                    normalized_type=table,
                    normalized_id=record.internal_id,
                ),
            )
        )
        patient_scope = None
        if isinstance(record, Patient):
            patient_scope = record.internal_id
        elif isinstance(record, Encounter):
            patient_scope = record.patient_id
        target = ResolvedReference(
            normalized_type=table,
            normalized_id=record.internal_id,
            patient_id=patient_scope,
        )
        for alias in resource.aliases:
            local_targets[alias] = target

    priority = {"patients": 0, "encounters": 1}
    records.sort(key=lambda item: priority.get(item.normalized_table, 2))
    outcomes = [item for _, item in sorted(indexed_outcomes, key=lambda item: item[0])]
    return NormalizationResult(records=tuple(records), outcomes=tuple(outcomes))
