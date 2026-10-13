"""Prüft die Vollständigkeit der privaten HerkunftsREFERENZEN, nicht Originalbelege.

Dies ist ausdrücklich KEINE unabhängige Realabnahme und KEIN Nachweis, dass
private Belegdokumente im öffentlichen Repository enthalten sind.
"""
import json
from pathlib import Path, PurePosixPath
import re


def load_private_evidence_index(root):
    root = Path(root)
    path = root / "docs/private_evidence_index.public.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == "weather_router.public_private_evidence_index.v1"
    assert re.fullmatch(r"[0-9a-f]{40}", data["source_commit"])
    assert data["originals_included"] is False
    assert data["verification_scope"] == "references_only_not_evidence_content"
    entries = data["documents"]
    assert len(entries) == data["count"] and len(entries) == 23
    index = {}
    for entry in entries:
        name = entry["path"]
        parts = PurePosixPath(name).parts
        assert name.startswith("docs/") and name.endswith(".md")
        assert ".." not in parts and "\\" not in name
        assert name not in index
        assert entry["source_visibility"] == "private_original_not_published"
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        assert isinstance(entry["bytes"], int) and entry["bytes"] > 0
        assert not (root / name).exists(), f"Privates Original unerwartet enthalten: {name}"
        index[name] = entry
    return index
