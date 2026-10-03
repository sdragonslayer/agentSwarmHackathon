"""Snapshot bookkeeping: hashes and SNAPSHOT.json provenance records for fetched sources."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

IMPORTER_VERSION = "0.1.0"
CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def sha256_gunzip(path: Path, max_bytes: int | None = None) -> tuple[str, int]:
    """Hash the decompressed stream of a .gz file without writing it to disk.

    Raises ValueError if the decompressed size exceeds max_bytes (decompression-bomb guard).
    """
    h = hashlib.sha256()
    total = 0
    with gzip.open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            total += len(chunk)
            if max_bytes is not None and total > max_bytes:
                raise ValueError(f"{path.name}: decompressed size exceeds {max_bytes} bytes")
            h.update(chunk)
    return h.hexdigest(), total


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_snapshot(dest: Path, source: str, files: list[dict[str, Any]], **extra: Any) -> Path:
    """Write dest/SNAPSHOT.json. Earlier snapshots are kept as SNAPSHOT.<retrieved_at>.json."""
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "SNAPSHOT.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        stamp = old.get("retrieved_at", "unknown").replace(":", "")
        path.rename(dest / f"SNAPSHOT.{stamp}.json")
    record = {
        "source": source,
        "retrieved_at": utc_now(),
        "importer_version": IMPORTER_VERSION,
        "files": files,
        **extra,
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path
