"""Deterministic, local-only clinical-text parsing and chunking."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid5

from mage_med_contracts import ClinicalNoteChunk, NoteType, SourceFormat

TEXT_IMPORTER_VERSION = "1.0.0"
CHUNK_ID_NAMESPACE = UUID("4e44daf9-b342-49f7-a94b-a51d3cd88245")
_HEADING = re.compile(r"^(?P<heading>[A-Z][A-Z0-9 /_-]{2,63}):?$")


class ClinicalTextError(ValueError):
    """A safe text parsing or validation error."""


class AttachmentUnavailable(ClinicalTextError):
    """A linked attachment was intentionally not resolved."""


@dataclass(frozen=True, slots=True)
class ParsedTextNote:
    source_id: str
    original_text: str
    note_type: NoteType
    title: str | None = None
    authored_at: str | datetime | None = None
    author_reference: str | None = None
    source_label: str | None = None
    patient_id: str | None = None
    encounter_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedAttachment:
    text: str
    source_label: str


def decode_utf8(content: bytes, *, max_bytes: int, label: str) -> str:
    if len(content) > max_bytes:
        raise ClinicalTextError(f"{label} exceeds the configured size limit")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ClinicalTextError(f"{label} must be UTF-8") from exc
    if "\x00" in text:
        raise ClinicalTextError(f"{label} contains unsupported NUL bytes")
    return text


def clean_clinical_text(text: str) -> str:
    """Normalize display-safe plain text without interpreting its content."""

    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "".join(
        character for character in normalized if character in {"\n", "\t"} or ord(character) >= 32
    )
    lines = [line.rstrip() for line in normalized.split("\n")]
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    if not cleaned:
        raise ClinicalTextError("clinical note text is empty after safe cleanup")
    return cleaned


def _optional_string(value: Any, field: str, *, maximum: int = 512) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ClinicalTextError(f"{field} must be a string")
    if len(value) > maximum:
        raise ClinicalTextError(f"{field} exceeds {maximum} characters")
    return value


def _note_from_mapping(value: Any, index: int) -> ParsedTextNote:
    if not isinstance(value, dict):
        raise ClinicalTextError(f"note {index} must be an object")
    text = value.get("text")
    if not isinstance(text, str) or not text:
        raise ClinicalTextError(f"note {index} requires non-empty text")
    source_id = value.get("id", f"note-{index}")
    if not isinstance(source_id, str) or not source_id or len(source_id) > 512:
        raise ClinicalTextError(f"note {index} has an invalid id")
    try:
        note_type = NoteType(value.get("note_type", NoteType.CLINICAL_NARRATIVE))
    except ValueError as exc:
        raise ClinicalTextError(f"note {index} has an unsupported note_type") from exc
    return ParsedTextNote(
        source_id=source_id,
        original_text=text,
        note_type=note_type,
        title=_optional_string(value.get("title"), "title"),
        authored_at=_optional_string(value.get("authored_at"), "authored_at", maximum=64),
        author_reference=_optional_string(value.get("author_reference"), "author_reference"),
        source_label=_optional_string(
            value.get("source_label") or value.get("author_label"), "source_label"
        ),
        patient_id=_optional_string(value.get("patient_id"), "patient_id", maximum=36),
        encounter_id=_optional_string(value.get("encounter_id"), "encounter_id", maximum=36),
    )


def parse_text_document(
    content: bytes,
    *,
    source_format: SourceFormat,
    max_bytes: int,
    max_notes: int,
    txt_defaults: dict[str, Any] | None = None,
) -> tuple[str | dict[str, Any] | list[Any], tuple[ParsedTextNote, ...]]:
    """Parse one explicit TXT, CSV, or JSON note document."""

    decoded = decode_utf8(content, max_bytes=max_bytes, label="clinical text input")
    if source_format is SourceFormat.TXT:
        defaults = dict(txt_defaults or {})
        defaults["text"] = decoded
        defaults.setdefault("id", "note-0")
        return decoded, (_note_from_mapping(defaults, 0),)
    if source_format is SourceFormat.JSON:
        try:
            raw = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise ClinicalTextError("clinical text JSON is invalid") from exc
        values = raw.get("notes") if isinstance(raw, dict) and "notes" in raw else raw
        if isinstance(values, dict):
            values = [values]
        if not isinstance(values, list):
            raise ClinicalTextError(
                "clinical text JSON must be a note, note array, or notes object"
            )
        if len(values) > max_notes:
            raise ClinicalTextError("clinical text JSON exceeds the configured note limit")
        return raw, tuple(_note_from_mapping(value, index) for index, value in enumerate(values))
    if source_format is SourceFormat.CSV:
        reader = csv.DictReader(io.StringIO(decoded))
        if reader.fieldnames is None or "text" not in reader.fieldnames:
            raise ClinicalTextError("clinical text CSV requires a text column")
        rows = list(reader)
        if len(rows) > max_notes:
            raise ClinicalTextError("clinical text CSV exceeds the configured note limit")
        return decoded, tuple(_note_from_mapping(row, index) for index, row in enumerate(rows))
    raise ClinicalTextError("unsupported clinical text source format")


def chunk_clinical_text(
    note_id: UUID,
    text: str,
    *,
    max_characters: int,
    overlap_characters: int,
    extract_sections: bool,
) -> tuple[ClinicalNoteChunk, ...]:
    """Create exact cleaned-text spans with stable IDs and optional headings."""

    if overlap_characters >= max_characters:
        raise ClinicalTextError("chunk overlap must be smaller than chunk size")
    headings: list[tuple[int, str]] = []
    if extract_sections:
        cursor = 0
        for line in text.splitlines(keepends=True):
            match = _HEADING.fullmatch(line.rstrip("\n"))
            if match:
                headings.append((cursor, match.group("heading").rstrip(":")))
            cursor += len(line)
    chunks: list[ClinicalNoteChunk] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + max_characters, len(text))
        if end < len(text):
            break_at = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
            if break_at > start:
                end = break_at + (1 if text[break_at] == "\n" else 0)
        while end > start and text[end - 1].isspace() and text[end - 1] != "\n":
            end -= 1
        if end <= start:
            end = min(start + max_characters, len(text))
        chunk_text = text[start:end]
        section = None
        for heading_offset, heading in headings:
            if heading_offset <= start:
                section = heading
            else:
                break
        digest = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
        chunk_id = uuid5(CHUNK_ID_NAMESPACE, f"{note_id}:{index}:{start}:{end}:{digest}")
        chunks.append(
            ClinicalNoteChunk(
                internal_id=chunk_id,
                note_id=note_id,
                chunk_index=index,
                start_offset=start,
                end_offset=end,
                text=chunk_text,
                section=section,
                sha256=digest,
            )
        )
        if end == len(text):
            break
        start = max(end - overlap_characters, start + 1)
        index += 1
    return tuple(chunks)


class LocalTextAttachmentResolver:
    """Read allowlisted relative plain-text attachments without network access."""

    def __init__(self, root: Path | None, *, max_bytes: int) -> None:
        self._root = root.resolve() if root is not None else None
        self._max_bytes = max_bytes

    def __call__(self, url: str, declared_content_type: str | None) -> ResolvedAttachment:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise AttachmentUnavailable("external or non-file attachment URL is unavailable")
        if self._root is None:
            raise AttachmentUnavailable("local attachment import root is not configured")
        decoded_path = unquote(parsed.path)
        if not decoded_path or "\\" in decoded_path:
            raise AttachmentUnavailable("attachment path is invalid")
        relative = PurePosixPath(decoded_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise AttachmentUnavailable("attachment path escapes the configured import root")
        if relative.suffix.lower() != ".txt":
            raise AttachmentUnavailable("linked attachment must be a .txt file")
        if declared_content_type and not declared_content_type.startswith("text/"):
            raise AttachmentUnavailable("linked attachment content type is not text")
        candidate = (self._root / Path(*relative.parts)).resolve()
        if not candidate.is_relative_to(self._root):
            raise AttachmentUnavailable("attachment path escapes the configured import root")
        if not candidate.is_file():
            raise AttachmentUnavailable("linked attachment file is unavailable")
        content = candidate.read_bytes()
        text = decode_utf8(content, max_bytes=self._max_bytes, label="linked attachment")
        return ResolvedAttachment(text=text, source_label=relative.as_posix())
