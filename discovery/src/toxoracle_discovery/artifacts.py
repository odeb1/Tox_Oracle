"""Checksummed artifacts with filenames independent of user-supplied IDs."""

import hashlib
import json
from pathlib import Path


def artifact_key(identifier: str) -> str:
    return "compound_" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()


def write_text(directory: Path, name: str, content: str) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    data = content.encode("utf-8")
    path.write_bytes(data)
    return {
        "artifact_id": path.stem,
        "format": path.suffix.lstrip("."),
        "uri": str(path.resolve()),
        "checksum": "sha256:" + hashlib.sha256(data).hexdigest(),
    }


def write_json(directory: Path, name: str, value) -> dict:
    return write_text(directory, name, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
