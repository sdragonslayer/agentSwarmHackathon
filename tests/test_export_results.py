import json

from backend.analysis import artifacts, edges, export_results, lineage
from backend.db import connect
from backend.ingest import aivillage
from tests import synth


def test_export_writes_tables_and_resolves_demo_ids(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    synth.build(raw)
    db = tmp_path / "t.duckdb"
    aivillage.load(raw, db, hash_files=False)
    con = connect(db)
    lineage.build(con)
    artifacts.build(con)
    edges.build(con)
    monkeypatch.setattr(export_results, "DEMO_CASES", {"demo": synth.URL, "gone": "https://nowhere.test/x"})
    out = tmp_path / "res"
    summary = export_results.export(con, out)
    assert (out / "lines_by_stream.csv").read_text(encoding="utf-8").startswith("stream,items")
    assert summary["demo_cases"]["demo"]["artifact_id"].startswith("art:url:")
    assert summary["demo_cases"]["gone"]["missing"] is True
    assert json.loads((out / "results.json").read_text(encoding="utf-8"))["scope"]["event"] > 0
