import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest
from mage_med_contracts import SourceFormat
from mage_med_ingestion import (
    AttachmentUnavailable,
    ClinicalTextError,
    LocalTextAttachmentResolver,
    chunk_clinical_text,
    clean_clinical_text,
    parse_text_document,
)


def test_txt_csv_and_json_parse_without_inferred_links() -> None:
    _, txt = parse_text_document(
        b"SYNTHETIC direct note",
        source_format=SourceFormat.TXT,
        max_bytes=1024,
        max_notes=10,
    )
    _, csv_notes = parse_text_document(
        b"id,note_type,text\nn1,progress,SYNTHETIC CSV note\n",
        source_format=SourceFormat.CSV,
        max_bytes=1024,
        max_notes=10,
    )
    _, json_notes = parse_text_document(
        json.dumps({"notes": [{"id": "n2", "text": "SYNTHETIC JSON note"}]}).encode(),
        source_format=SourceFormat.JSON,
        max_bytes=1024,
        max_notes=10,
    )
    assert txt[0].patient_id is None
    assert csv_notes[0].note_type.value == "progress"
    assert json_notes[0].source_id == "n2"


def test_cleanup_and_chunks_preserve_exact_cleaned_offsets() -> None:
    cleaned = clean_clinical_text("  HISTORY:\r\nLine one.   \r\n\r\n\r\nLine two.  ")
    chunks = chunk_clinical_text(
        UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        cleaned,
        max_characters=24,
        overlap_characters=4,
        extract_sections=True,
    )
    assert cleaned == "HISTORY:\nLine one.\n\nLine two."
    assert chunks[0].section == "HISTORY"
    for chunk in chunks:
        assert cleaned[chunk.start_offset : chunk.end_offset] == chunk.text
        assert hashlib.sha256(chunk.text.encode()).hexdigest() == chunk.sha256


def test_encoding_binary_and_note_count_limits_fail_safely() -> None:
    with pytest.raises(ClinicalTextError, match="UTF-8"):
        parse_text_document(
            b"\xff",
            source_format=SourceFormat.TXT,
            max_bytes=100,
            max_notes=1,
        )
    with pytest.raises(ClinicalTextError, match="NUL"):
        parse_text_document(
            b"bad\x00text",
            source_format=SourceFormat.TXT,
            max_bytes=100,
            max_notes=1,
        )
    with pytest.raises(ClinicalTextError, match="note limit"):
        parse_text_document(
            b'[{"text":"one"},{"text":"two"}]',
            source_format=SourceFormat.JSON,
            max_bytes=100,
            max_notes=1,
        )


def test_local_attachment_resolver_allowlist_and_traversal(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "note.txt").write_text("SYNTHETIC linked note", encoding="utf-8")
    resolver = LocalTextAttachmentResolver(root, max_bytes=100)
    resolved = resolver("note.txt", "text/plain")
    assert resolved.text == "SYNTHETIC linked note"
    assert resolved.source_label == "note.txt"

    for unsafe in ("../note.txt", "/etc/passwd", "https://example.invalid/note.txt"):
        with pytest.raises(AttachmentUnavailable):
            resolver(unsafe, "text/plain")
    with pytest.raises(AttachmentUnavailable, match="unavailable"):
        resolver("missing.txt", "text/plain")
