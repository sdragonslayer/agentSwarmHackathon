from fastapi.testclient import TestClient

from backend.analysis import artifacts, edges, lineage
from backend.app.main import create_app
from backend.db import connect
from backend.ingest import aivillage
from tests import synth


def _client(tmp_path):
    raw = tmp_path / "raw"
    synth.build(raw)
    db = tmp_path / "t.duckdb"
    aivillage.load(raw, db, hash_files=False)
    con = connect(db)
    lineage.build(con)
    artifacts.build(con)
    edges.build(con)
    con.close()
    return TestClient(create_app(db)), artifacts.artifact_id("url", "https://example.test/Path/Case?token=AbC&x=1")


def test_endpoints(tmp_path):
    c, aid = _client(tmp_path)
    d = c.get("/datasets").json()
    assert d["counts"]["text_item"] > 0 and "author labels" in d["label_note"]
    s = c.get("/search", params={"q": "workaround"}).json()
    assert any("workaround" in i["snippet"].lower() for i in s["items"])
    apps = c.get(f"/artifacts/{aid}/appearances").json()
    assert apps["total"] == 5 and "not established action order" in apps["order_note"]
    g = c.get(f"/cases/{aid}/graph").json()
    assert len(g["nodes"]) == 2 and len(g["edges"]) == 1 and g["edges"][0]["directed"] is False
    q = c.get(f"/cases/{aid}/questions").json()["answers"]
    assert len(q) == 10
    ex = c.get(f"/cases/{aid}/export", params={"format": "markdown"}).json()["body"]
    assert "Author labels are not verified agents" in ex and "all citations resolve" in ex
    item = c.get("/events/av:mem:33333333-0000-0000-0000-000000000002").json()
    assert item["lineage"]["status"] == "inferred_predecessor" and item["changes"]
    assert c.get("/events/nope").status_code == 404


def test_reviews_are_append_only(tmp_path):
    c, aid = _client(tmp_path)
    edge_id = c.get(f"/cases/{aid}/graph").json()["edges"][0]["edge_id"]
    a = c.post("/reviews", json={"edge_id": edge_id, "decision": "accept", "rationale": "exact string"}).json()
    b = c.post("/reviews", json={"edge_id": edge_id, "decision": "uncertain"}).json()
    assert a["review_id"] != b["review_id"]
    assert c.post("/reviews", json={"edge_id": "missing", "decision": "accept"}).status_code == 404
    assert c.post("/reviews", json={"edge_id": edge_id, "decision": "bogus"}).status_code == 422
