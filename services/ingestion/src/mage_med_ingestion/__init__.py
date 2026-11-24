"""Local-only ingestion for both MAGE-Med clinical modalities."""

from mage_med_ingestion.clinical_text import (
    AttachmentUnavailable,
    ClinicalTextError,
    LocalTextAttachmentResolver,
    ParsedTextNote,
    ResolvedAttachment,
    chunk_clinical_text,
    clean_clinical_text,
    parse_text_document,
)
from mage_med_ingestion.normalization import (
    FhirNormalizationError,
    NormalizationContext,
    NormalizationResult,
    NormalizedResource,
    ResolvedReference,
    normalize_document,
    normalized_id_for,
)
from mage_med_ingestion.validation import (
    FHIR_VERSION,
    VALIDATION_PACKAGE,
    VALIDATION_PACKAGE_VERSION,
    FhirDocumentError,
    ParsedFhirDocument,
    ParsedResource,
    parse_fhir_json,
)

__all__ = [
    "FHIR_VERSION",
    "VALIDATION_PACKAGE",
    "VALIDATION_PACKAGE_VERSION",
    "AttachmentUnavailable",
    "ClinicalTextError",
    "FhirDocumentError",
    "FhirNormalizationError",
    "LocalTextAttachmentResolver",
    "NormalizationContext",
    "NormalizationResult",
    "NormalizedResource",
    "ParsedFhirDocument",
    "ParsedResource",
    "ParsedTextNote",
    "ResolvedAttachment",
    "ResolvedReference",
    "chunk_clinical_text",
    "clean_clinical_text",
    "normalize_document",
    "normalized_id_for",
    "parse_fhir_json",
    "parse_text_document",
]
