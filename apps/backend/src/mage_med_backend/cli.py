"""Command-line entry point for local MAGE-Med workflows."""

import argparse
import json
from pathlib import Path
from uuid import UUID

from mage_med_contracts import FhirImportReport, NoteType, SourceFormat, TextImportReport
from mage_med_knowledge_graph import Neo4jGraphRepository, create_neo4j_driver

from mage_med_backend.clinical_data import ClinicalDataService
from mage_med_backend.config import Settings
from mage_med_backend.database import create_sqlite_engine
from mage_med_backend.graph_sync import GraphSyncError, GraphSyncService
from mage_med_backend.importing import (
    ClinicalTextService,
    FhirImportRejected,
    FhirImportService,
    TextImportRejected,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mage-med")
    subparsers = parser.add_subparsers(dest="command", required=True)
    import_parser = subparsers.add_parser("import-fhir", help="Import local FHIR R4 JSON")
    import_parser.add_argument("path", type=Path)
    import_parser.add_argument("--dataset-id", default="local-fhir-r4")
    import_parser.add_argument("--dataset-version", default="1")
    import_parser.add_argument("--synthetic-seed", type=int)
    text_parser = subparsers.add_parser(
        "import-text", help="Import local TXT, CSV, or JSON clinical notes"
    )
    text_parser.add_argument("path", type=Path)
    text_parser.add_argument("--dataset-id", default="local-clinical-text")
    text_parser.add_argument("--dataset-version", default="1")
    text_parser.add_argument("--synthetic", action="store_true")
    text_parser.add_argument("--synthetic-seed", type=int)
    text_parser.add_argument("--patient-id")
    text_parser.add_argument("--encounter-id")
    text_parser.add_argument("--note-type", choices=[item.value for item in NoteType])
    text_parser.add_argument("--title")
    text_parser.add_argument("--source-label")
    text_parser.add_argument("--authored-at")
    quality_parser = subparsers.add_parser(
        "data-quality-report", help="Print a human-readable SQLite data quality report"
    )
    quality_parser.add_argument("--dataset-id")
    graph_parser = subparsers.add_parser(
        "graph-sync", help="Synchronize canonical SQLite patient records into Neo4j"
    )
    graph_parser.add_argument("--patient-id", type=UUID)
    graph_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Explicitly report this atomic replacement as a rebuild",
    )
    return parser


def main() -> None:
    """Run a bounded CLI workflow and emit a JSON report."""

    args = _build_parser().parse_args()
    settings = Settings()
    engine = create_sqlite_engine(settings.database_url)
    if args.command == "data-quality-report":
        try:
            print(ClinicalDataService(engine).data_quality_report(args.dataset_id).human_readable)
        finally:
            engine.dispose()
        return
    if args.command == "graph-sync":
        driver = create_neo4j_driver(
            uri=settings.neo4j_uri,
            username=settings.neo4j_username,
            password=settings.neo4j_password,
            timeout_seconds=settings.neo4j_timeout_seconds,
        )
        try:
            graph_report = GraphSyncService(
                engine,
                Neo4jGraphRepository(driver, database=settings.neo4j_database),
            ).synchronize(patient_id=args.patient_id, rebuild=args.rebuild)
        except GraphSyncError as exc:
            raise SystemExit(str(exc)) from exc
        finally:
            driver.close()
            engine.dispose()
        print(json.dumps(graph_report.model_dump(mode="json"), indent=2, sort_keys=True))
        return
    path: Path = args.path
    if not path.is_file():
        raise SystemExit("import input must be an existing local file")
    max_bytes = (
        settings.fhir_max_upload_bytes
        if args.command == "import-fhir"
        else settings.clinical_text_max_upload_bytes
    )
    if path.stat().st_size > max_bytes:
        raise SystemExit("import input exceeds the configured size limit")
    content = path.read_bytes()
    report: FhirImportReport | TextImportReport
    try:
        if args.command == "import-fhir":
            if path.suffix.lower() != ".json":
                raise SystemExit("FHIR input must use a .json extension")
            report = FhirImportService(
                engine,
                max_bytes=settings.fhir_max_upload_bytes,
                text_import_root=settings.clinical_text_import_root,
                max_note_bytes=settings.clinical_text_max_note_bytes,
                chunk_characters=settings.clinical_text_chunk_characters,
                chunk_overlap=settings.clinical_text_chunk_overlap,
            ).import_bytes(
                content,
                original_filename=path.name,
                source_locator=str(path.resolve()),
                dataset_id=args.dataset_id,
                dataset_version=args.dataset_version,
                synthetic_seed=args.synthetic_seed,
                actor_id="local-cli",
            )
        elif args.command == "import-text":
            try:
                source_format = SourceFormat(path.suffix.lower().removeprefix("."))
            except ValueError as exc:
                raise SystemExit("Clinical text input must be TXT, CSV, or JSON") from exc
            defaults = None
            if source_format is SourceFormat.TXT:
                defaults = {
                    "patient_id": args.patient_id,
                    "encounter_id": args.encounter_id,
                    "note_type": args.note_type or NoteType.CLINICAL_NARRATIVE.value,
                    "title": args.title,
                    "source_label": args.source_label,
                    "authored_at": args.authored_at,
                }
            report = ClinicalTextService(
                engine,
                max_upload_bytes=settings.clinical_text_max_upload_bytes,
                max_note_bytes=settings.clinical_text_max_note_bytes,
                max_notes=settings.clinical_text_max_notes,
                chunk_characters=settings.clinical_text_chunk_characters,
                chunk_overlap=settings.clinical_text_chunk_overlap,
            ).import_bytes(
                content,
                source_format=source_format,
                original_filename=path.name,
                source_locator=str(path.resolve()),
                dataset_id=args.dataset_id,
                dataset_version=args.dataset_version,
                synthetic=args.synthetic,
                synthetic_seed=args.synthetic_seed,
                actor_id="local-cli",
                txt_defaults=defaults,
            )
        else:
            raise SystemExit(2)
    except (FhirImportRejected, TextImportRejected) as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        engine.dispose()
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
