export type HealthStatus = "healthy" | "not_ready";
export type ComponentStatus = "available" | "unavailable";

export interface ComponentCheck {
  name: string;
  status: ComponentStatus;
  detail: string;
}

export interface HealthResponse {
  service: string;
  version: string;
  status: HealthStatus;
  request_id: string;
  components: ComponentCheck[];
}

export interface ErrorBody {
  code: string;
  message: string;
  request_id: string;
}

export interface ErrorResponse {
  error: ErrorBody;
}

export const CLINICAL_SCHEMA_VERSION = "1.0.0" as const;
export type ClinicalSchemaVersion = typeof CLINICAL_SCHEMA_VERSION;
export type DataModality =
  "structured_clinical_data" | "unstructured_clinical_text";
export type AssertionType =
  | "observed"
  | "extracted"
  | "model_inferred"
  | "hypothesized"
  | "clinician_confirmed"
  | "clinician_rejected";
export type VerificationStatus = "unverified" | "verified" | "rejected";

export interface SourceReference {
  source_artifact_id: string;
  source_locator: string;
  resource_type: string | null;
  resource_id: string | null;
}

export interface Provenance {
  import_manifest_id: string;
  importer_name: string;
  importer_version: string;
  transformation_version: string;
  run_id: string;
  actor_id: string;
  synthetic: boolean;
  seed: number | null;
}

export interface ClinicalFact {
  schema_version: ClinicalSchemaVersion;
  internal_id: string;
  modality: DataModality;
  source_reference: SourceReference;
  patient_id: string | null;
  encounter_id: string | null;
  event_time: string | null;
  recorded_time: string | null;
  imported_at: string;
  provenance: Provenance;
  assertion_type: AssertionType;
}

export type ResourceImportStatus =
  "imported" | "updated" | "unavailable" | "unusable" | "unsupported";

export interface ResourceImportOutcome {
  source_key: string;
  resource_type: string | null;
  resource_id: string | null;
  full_url: string | null;
  status: ResourceImportStatus;
  normalized_type: string | null;
  normalized_id: string | null;
  issues: string[];
}

export interface FhirImportReport {
  import_id: string;
  status: "pending" | "succeeded" | "failed";
  source_artifact_id: string | null;
  source_sha256: string;
  validation_package: "fhirclient";
  validation_package_version: "4.2.0";
  fhir_version: "4.0.1";
  validation_scope: "base_structure_and_project_invariants";
  profile_conformance: "not_evaluated";
  idempotent_replay: boolean;
  started_at: string;
  completed_at: string | null;
  record_counts: Record<string, number>;
  resources: ResourceImportOutcome[];
  errors: string[];
}

export type NoteType =
  "consultation" | "clinical_history" | "progress" | "clinical_narrative";
export type NoteContentOrigin =
  "direct_file" | "fhir_embedded" | "fhir_local_file";
export type TextNoteImportStatus =
  "imported" | "updated" | "unlinked" | "unusable";

export interface NoteChunkResponse {
  chunk_id: string;
  chunk_index: number;
  start_offset: number;
  end_offset: number;
  text: string;
  section: string | null;
  sha256: string;
}

export interface ClinicalNoteResponse {
  note_id: string;
  patient_id: string | null;
  encounter_id: string | null;
  note_type: NoteType;
  title: string | null;
  original_text: string;
  text: string;
  authored_at: string | null;
  author_reference: string | null;
  source_label: string | null;
  content_origin: NoteContentOrigin;
  source_artifact_id: string;
  source_locator: string;
  assertion_type: AssertionType;
  synthetic: boolean;
  chunks: NoteChunkResponse[];
}

export interface StructuredRecordSummary {
  record_id: string;
  record_type: string;
  encounter_id: string | null;
  event_time: string | null;
  source_artifact_id: string;
  source_locator: string;
}

export interface PatientClinicalContextResponse {
  patient_id: string;
  structured_records: StructuredRecordSummary[];
  notes: ClinicalNoteResponse[];
}

export interface TextNoteImportOutcome {
  source_id: string;
  status: TextNoteImportStatus;
  note_id: string | null;
  patient_id: string | null;
  encounter_id: string | null;
  chunk_count: number;
  issues: string[];
}

export interface TextImportReport {
  import_id: string;
  status: "pending" | "succeeded" | "failed";
  source_artifact_id: string;
  source_sha256: string;
  idempotent_replay: boolean;
  started_at: string;
  completed_at: string | null;
  record_counts: Record<string, number>;
  notes: TextNoteImportOutcome[];
  errors: string[];
}
