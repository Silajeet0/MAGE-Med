import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/synthetic_clinical_text.json"


def test_synthetic_text_manifest_checksums_and_labels() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert manifest["contains_real_patient_data"] is False
    assert manifest["seed"] == 20261123
    assert "NOT CLINICIAN-AUTHORED" in manifest["description"]
    for item in manifest["files"]:
        content = (ROOT / item["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
        assert b"SYNTHETIC" in content


def test_semantic_safety_cases_are_explicit_fixture_text() -> None:
    payload = json.loads(
        (ROOT / "data/synthetic/clinical_text/synthetic_notes.json").read_text(encoding="utf-8")
    )
    combined = "\n".join(note["text"] for note in payload["notes"])
    labels = {note["source_label"] for note in payload["notes"]}
    assert "INTENTIONAL CONFLICT" in combined
    assert "NEGATION TEST" in combined
    assert "OUTDATED TEST DATA" in combined
    assert labels == {"SYNTHETIC fixture generator; not clinician-authored"}
