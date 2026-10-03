"""Fetch-layer tests. No network: HTTP goes through httpx.MockTransport, archives are built locally."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from backend.ingest import aivillage_fetch as av
from backend.ingest import fetch

PAYLOAD = b"".join(f'{{"rev_id": {i}, "body": "line {i}"}}\n'.encode() for i in range(5000))
GZ = gzip.compress(PAYLOAD)


def range_transport(data: bytes, calls: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        rng = request.headers.get("range")
        if rng:
            start = int(rng.removeprefix("bytes=").rstrip("-"))
            if start >= len(data):
                return httpx.Response(416)
            return httpx.Response(206, content=data[start:])
        return httpx.Response(200, content=data, headers={"content-length": str(len(data))})

    return httpx.MockTransport(handler)


def offline_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network call: {request.url}")

    return httpx.MockTransport(handler)


def test_download_resumes_from_part(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    target = tmp_path / "revisions.jsonl.gz"
    (tmp_path / "revisions.jsonl.gz.part").write_bytes(GZ[:1000])
    with fetch.make_client(range_transport(GZ, calls)) as client:
        fetch.download(client, "https://example.test/revisions.jsonl.gz", target)
    assert target.read_bytes() == GZ
    assert calls[0].headers["range"] == "bytes=1000-"
    assert not (tmp_path / "revisions.jsonl.gz.part").exists()


def test_describe_file_hashes_decompressed_and_flags_reference(tmp_path: Path, capsys) -> None:
    p = tmp_path / "revisions.jsonl.gz"
    p.write_bytes(GZ)
    good = fetch.describe_file(p, "u", {"revisions.jsonl": hashlib.sha256(PAYLOAD).hexdigest()})
    assert good["decompressed_sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
    assert good["decompressed_bytes"] == len(PAYLOAD)
    assert good["matches_reference"] is True
    bad = fetch.describe_file(p, "u", {"revisions.jsonl": "0" * 64})
    assert bad["matches_reference"] is False
    assert "WARNING" in capsys.readouterr().err


def test_wiki_dry_run_makes_no_network_calls(tmp_path: Path, capsys) -> None:
    args = argparse.Namespace(dest=tmp_path, dry_run=True, check_size=False)
    with fetch.make_client(offline_transport()) as client:
        fetch.cmd_wiki(args, fetch.load_config(), client)
    out = capsys.readouterr().out
    assert "https://collusion.wiki/explorer/download/revisions.jsonl.gz" in out
    assert not any(tmp_path.iterdir())


def test_wiki_fetch_writes_snapshot(tmp_path: Path) -> None:
    cfg = fetch.load_config()
    cfg["wiki"]["files"] = ["revisions.jsonl.gz"]
    args = argparse.Namespace(dest=tmp_path, dry_run=False, check_size=False)
    with fetch.make_client(range_transport(GZ, [])) as client:
        fetch.cmd_wiki(args, cfg, client)
    snap = json.loads((tmp_path / "SNAPSHOT.json").read_text())
    assert snap["source"] == "wiki"
    assert snap["files"][0]["sha256"] == hashlib.sha256(GZ).hexdigest()
    assert snap["files"][0]["matches_reference"] is False  # synthetic data != real snapshot


def test_snapshot_keeps_previous(tmp_path: Path) -> None:
    from backend.ingest.snapshot import write_snapshot

    write_snapshot(tmp_path, "wiki", [])
    write_snapshot(tmp_path, "wiki", [])
    assert len(list(tmp_path.glob("SNAPSHOT*.json"))) == 2


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


def test_safe_extract_keeps_only_selected(tmp_path: Path) -> None:
    z = _zip(tmp_path / "a.zip", {"pkg/all-reports.csv": b"id\n1\n", "pkg/README.md": b"hi",
                                  "pkg/catalog-a.csv": b"x"})
    out = fetch.safe_extract(z, tmp_path / "x", ["all-reports.csv", "README*"], 10_000)
    assert sorted(p.name for p in out) == ["README.md", "all-reports.csv"]


@pytest.mark.parametrize("evil", ["../escape.csv", "/abs/all-reports.csv", "C:/win/all-reports.csv",
                                  "pkg/../../all-reports.csv"])
def test_safe_extract_rejects_traversal(tmp_path: Path, evil: str) -> None:
    z = _zip(tmp_path / "evil.zip", {evil: b"x"})
    with pytest.raises(ValueError, match="unsafe path"):
        fetch.safe_extract(z, tmp_path / "x", ["*"], 10_000)


def test_safe_extract_size_cap(tmp_path: Path) -> None:
    z = _zip(tmp_path / "big.zip", {"all-reports.csv": b"0" * 5000})
    with pytest.raises(ValueError, match="limit"):
        fetch.safe_extract(z, tmp_path / "x", ["*"], 1000)


def test_swarmtraces_requires_url(tmp_path: Path) -> None:
    args = argparse.Namespace(dest=tmp_path, dry_run=True, check_size=False, url=None)
    with pytest.raises(SystemExit, match="swarmtraces.org/viewer"):
        fetch.cmd_swarmtraces(args, fetch.load_config())


# ---------------------------------------------------------------- AI Village helpers (offline)


@pytest.mark.parametrize(("path", "table"), [
    ("data/chat/train-00000-of-00004.parquet", "chat"),
    ("memories/part-0.parquet", "memories"),
    ("data/turns-00003-of-00120.parquet", "turns"),
    ("changelog.parquet", "changelog"),
])
def test_table_of(path: str, table: str) -> None:
    assert av.table_of(path) == table


def test_excluded_detects_binary_and_names() -> None:
    import pyarrow as pa

    pats = fetch.load_config()["aivillage"]["exclude_column_patterns"]
    assert av.excluded("screenshot_path", pa.string(), pats)
    assert av.excluded("frame", pa.struct([("bytes", pa.binary()), ("path", pa.string())]), pats)
    assert av.excluded("content", pa.string(), pats) is None


def test_build_where_quotes_values() -> None:
    args = argparse.Namespace(time_column="ts", start="2026-05-01", end=None,
                              where_column="goal_id", equals=["g1", "o'brien"])
    where = av.build_where(args, {"ts": {}, "goal_id": {}})
    assert "'o''brien'" in where and "TIMESTAMPTZ" in where


def test_build_where_requires_filter() -> None:
    args = argparse.Namespace(time_column=None, start=None, end=None, where_column=None, equals=None)
    with pytest.raises(SystemExit):
        av.build_where(args, {})


def test_slice_select_projects_columns_and_runs_locally(tmp_path: Path) -> None:
    """The generated SQL executes in DuckDB against a local Parquet stand-in for hf:// files."""
    import duckdb
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.table({"ts": ["2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"],
                             "goal_id": ["g1", "g2"], "text": ["a", "b"],
                             "screenshot": [b"\x00", b"\x01"]}), tmp_path / "t.parquet")
    args = argparse.Namespace(time_column="ts", start="2026-05-15", end=None, where_column=None, equals=None)
    where = av.build_where(args, {"ts": {}, "goal_id": {}, "text": {}})
    sql = av.build_select("r", ["t.parquet"], ["ts", "text"], where).replace(
        "hf://datasets/r/", (tmp_path.as_posix() + "/"))
    assert duckdb.sql(sql).fetchall() == [("2026-06-01T00:00:00Z", "b")]
