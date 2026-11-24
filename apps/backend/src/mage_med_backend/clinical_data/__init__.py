"""Patient-scoped clinical data access boundary."""

from mage_med_backend.clinical_data.service import ClinicalDataNotFound, ClinicalDataService

__all__ = ["ClinicalDataNotFound", "ClinicalDataService"]
