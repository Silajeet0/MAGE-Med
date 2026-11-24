"""Local-only base structural validation for FHIR R4 JSON resources."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from fhirclient.models.allergyintolerance import AllergyIntolerance as FhirAllergyIntolerance
from fhirclient.models.bundle import Bundle as FhirBundle
from fhirclient.models.condition import Condition as FhirCondition
from fhirclient.models.documentreference import DocumentReference as FhirDocumentReference
from fhirclient.models.encounter import Encounter as FhirEncounter
from fhirclient.models.fhirabstractbase import FHIRValidationError
from fhirclient.models.medicationrequest import MedicationRequest as FhirMedicationRequest
from fhirclient.models.observation import Observation as FhirObservation
from fhirclient.models.patient import Patient as FhirPatient

FHIR_VERSION = "4.0.1"
VALIDATION_PACKAGE = "fhirclient"
VALIDATION_PACKAGE_VERSION = "4.2.0"

SUPPORTED_RESOURCE_MODELS: dict[str, type[Any]] = {
    "Patient": FhirPatient,
    "Encounter": FhirEncounter,
    "Condition": FhirCondition,
    "Observation": FhirObservation,
    "MedicationRequest": FhirMedicationRequest,
    "AllergyIntolerance": FhirAllergyIntolerance,
    "DocumentReference": FhirDocumentReference,
}


class FhirDocumentError(ValueError):
    """A safe error indicating that the input document cannot be processed."""


@dataclass(frozen=True, slots=True)
class ParsedResource:
    """One resource and its exact source location within an input document."""

    index: int
    raw: dict[str, Any]
    resource_type: str | None
    resource_id: str | None
    full_url: str | None
    source_key: str
    supported: bool
    structurally_valid: bool
    issues: tuple[str, ...] = ()

    @property
    def aliases(self) -> tuple[str, ...]:
        aliases: list[str] = []
        if self.full_url:
            aliases.append(self.full_url)
        if self.resource_type and self.resource_id:
            aliases.append(f"{self.resource_type}/{self.resource_id}")
        return tuple(dict.fromkeys(aliases))


@dataclass(frozen=True, slots=True)
class ParsedFhirDocument:
    """Validated document shell and individually validated resources."""

    root_resource_type: str
    raw: dict[str, Any]
    resources: tuple[ParsedResource, ...]
    alias_to_index: dict[str, int] = field(default_factory=dict)


def _safe_source_key(resource_type: str | None, resource_id: str | None, index: int) -> str:
    if resource_type and resource_id:
        return f"fhir-r4:{resource_type}/{resource_id}"
    return f"fhir-r4:unusable-entry-{index}"


def _validate_supported_resource(resource: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    resource_type = resource.get("resourceType")
    if not isinstance(resource_type, str):
        return False, ("resourceType is required and must be a string",)
    model_type = SUPPORTED_RESOURCE_MODELS.get(resource_type)
    if model_type is None:
        return True, ()
    try:
        model = model_type(resource, strict=True)
        model.as_json()
    except (FHIRValidationError, TypeError, ValueError):
        return False, ("FHIR R4 base structural validation failed",)
    return True, ()


def _parse_entry(index: int, entry: Any) -> ParsedResource:
    if not isinstance(entry, dict):
        return ParsedResource(
            index=index,
            raw={},
            resource_type=None,
            resource_id=None,
            full_url=None,
            source_key=_safe_source_key(None, None, index),
            supported=False,
            structurally_valid=False,
            issues=("Bundle.entry must be an object",),
        )
    resource = entry.get("resource")
    full_url = entry.get("fullUrl") if isinstance(entry.get("fullUrl"), str) else None
    if not isinstance(resource, dict):
        return ParsedResource(
            index=index,
            raw={},
            resource_type=None,
            resource_id=None,
            full_url=full_url,
            source_key=_safe_source_key(None, None, index),
            supported=False,
            structurally_valid=False,
            issues=("Bundle.entry.resource is required and must be an object",),
        )
    resource_type = resource.get("resourceType")
    resource_id = resource.get("id")
    typed_resource_type = resource_type if isinstance(resource_type, str) else None
    typed_resource_id = resource_id if isinstance(resource_id, str) else None
    issues: list[str] = []
    if typed_resource_type is None:
        issues.append("resourceType is required and must be a string")
    if typed_resource_id is None:
        issues.append("resource id is required for deterministic local import")
    valid, validation_issues = _validate_supported_resource(resource)
    issues.extend(validation_issues)
    supported = typed_resource_type in SUPPORTED_RESOURCE_MODELS
    if typed_resource_type and not supported:
        issues.append(f"unsupported resource type: {typed_resource_type}")
    return ParsedResource(
        index=index,
        raw=resource,
        resource_type=typed_resource_type,
        resource_id=typed_resource_id,
        full_url=full_url,
        source_key=_safe_source_key(typed_resource_type, typed_resource_id, index),
        supported=supported,
        structurally_valid=valid and typed_resource_id is not None,
        issues=tuple(issues),
    )


def _index_aliases(resources: tuple[ParsedResource, ...]) -> dict[str, int]:
    aliases: dict[str, int] = {}
    ambiguous: set[str] = set()
    for resource in resources:
        for alias in resource.aliases:
            if alias in aliases and aliases[alias] != resource.index:
                ambiguous.add(alias)
            else:
                aliases[alias] = resource.index
    if ambiguous:
        raise FhirDocumentError("FHIR document contains duplicate or ambiguous resource references")
    return aliases


def parse_fhir_json(content: bytes) -> ParsedFhirDocument:
    """Decode and base-validate one Bundle or individual FHIR R4 resource."""

    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FhirDocumentError("FHIR input must be UTF-8 JSON") from exc
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise FhirDocumentError("FHIR input is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise FhirDocumentError("FHIR input root must be a JSON object")
    root_type = payload.get("resourceType")
    if not isinstance(root_type, str):
        raise FhirDocumentError("FHIR input requires a string resourceType")

    if root_type == "Bundle":
        shell = dict(payload)
        entries = shell.pop("entry", [])
        if not isinstance(entries, list):
            raise FhirDocumentError("Bundle.entry must be an array")
        try:
            FhirBundle(shell, strict=True).as_json()
        except (FHIRValidationError, TypeError, ValueError) as exc:
            raise FhirDocumentError("FHIR R4 Bundle base structural validation failed") from exc
        resources = tuple(_parse_entry(index, entry) for index, entry in enumerate(entries))
    else:
        resources = (
            _parse_entry(
                0, {"fullUrl": f"{root_type}/{payload.get('id', '')}", "resource": payload}
            ),
        )

    return ParsedFhirDocument(
        root_resource_type=root_type,
        raw=payload,
        resources=resources,
        alias_to_index=_index_aliases(resources),
    )
