from backend.analysis import artifacts, edges, lineage, validate
from backend.db import connect
from backend.ingest import aivillage
from tests import synth


def test_all_gates_pass_on_synthetic_data(tmp_path):
    raw = tmp_path / "raw"
    synth.build(raw)
    db = tmp_path / "t.duckdb"
    aivillage.load(raw, db, hash_files=False)
    con = connect(db)
    lineage.build(con)
    artifacts.build(con)
    edges.build(con)
    results = validate.run(con, sample=50)
    failed = [(n, d) for n, ok, d in results if not ok]
    assert not failed, failed
