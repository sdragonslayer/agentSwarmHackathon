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


def test_frontend_and_case_endpoints(tmp_path):
    c, aid = _client(tmp_path)
    page = c.get("/")
    assert page.status_code == 200 and "SwarmScope" in page.text and "innerHTML" not in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    st = c.get("/stats").json()
    assert st["inflation"]["line_level_by_stream"] and st["scope"]["text_item"] > 0
    cases = c.get("/cases").json()["cases"]
    assert cases and cases[0]["counts"]["novel_labels"] >= 2
    detail = c.get(f"/cases/{aid}").json()
    assert detail["edges"][0]["edge_id"].startswith("edge:") and len(detail["answers"]) == 10
    assert c.post(f"/cases/{aid}/candidates").status_code in (404, 405)  # similarity search is not exposed
    item = c.get("/events/av:mem:33333333-0000-0000-0000-000000000002").json()
    classes = {line["cls"] for line in item["lines"]}
    assert "inherited" in classes and "new" in classes
    edge_id = detail["edges"][0]["edge_id"]
    c.post("/reviews", json={"edge_id": edge_id, "decision": "accept", "rationale": "exact string"})
    revs = c.get(f"/cases/{aid}/reviews").json()["reviews"]
    assert [r["decision"] for r in revs] == ["accept"]
    assert c.get("/cases/nope").status_code == 404


def test_case_detail_answers_carry_citations(tmp_path):
    """Regression: the frontend renders answer.citations; the case payload must include them."""
    c, aid = _client(tmp_path)
    answers = c.get(f"/cases/{aid}").json()["answers"]
    assert all("citations" in a and "limitations" in a for a in answers)
    assert any(a["citations"] for a in answers)


def test_text_item_lists_its_artifacts_for_opening_a_case(tmp_path):
    c, aid = _client(tmp_path)
    item = c.get("/events/av:chat:11111111-0000-0000-0000-000000000001").json()
    assert aid in [a["artifact_id"] for a in item["artifacts"]]
    top = item["artifacts"][0]
    assert top["novel_labels"] >= 2 and top["raw"] == synth.URL
    assert c.get(f"/cases/{top['artifact_id']}").json()["appearances"]


def test_search_timeline_plots_phrase_hits_without_links(tmp_path):
    c, _ = _client(tmp_path)
    r = c.get("/search/timeline", params={"q": "workaround"}).json()
    assert r["total"] >= 1 and r["appearances"] and "no edges are drawn" in r["note"]
    first = r["appearances"][0]
    assert first["snippet"]["match"].lower() == "workaround" and first["novelty"] == "standalone"
    assert c.get("/search/timeline", params={"q": "zzzz-no-such-phrase"}).json()["total"] == 0


def test_topics_and_traces_endpoints(tmp_path):
    from backend.analysis import references, topics
    from backend.ingest import wiki
    from tests import synth_exchange

    raw = tmp_path / "raw"
    synth_exchange.build(raw)
    db = tmp_path / "x.duckdb"
    wiki.load(raw, db)
    con = connect(db)
    lineage.build(con)
    artifacts.build(con)
    edges.build(con)
    topics.build(con)
    references.build(con)
    con.close()
    c = TestClient(create_app(db))
    m = c.get("/topics/matrix").json()
    assert m["available"] and "datausa-test" in [t["topic"] for t in m["topics"]] and "not verdicts" in m["caveat"]
    ex = c.get("/topics/examples", params={"topic": "datausa-test", "category": "answer_sharing"}).json()["examples"]
    assert ex and ex[0]["snippet"]["match"].lower().startswith("answer")
    sm = c.get("/traces/summary").json()
    assert sm["available"] and sm["topics"] and "answer_provenance" in sm
    xs = c.get("/traces/exchanges").json()
    assert len(xs["exchanges"]) == 1 and xs["exchanges"][0]["a"]["label"] == "AgentAlpha07"
    assert "not proof of a conversation" in xs["definition"]
    assert c.get("/traces/hosts", params={"min_labels": 2}).status_code == 200


def test_topics_endpoints_degrade_when_analysis_not_built(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/topics/matrix").json()["available"] is False
    assert c.get("/traces/summary").json()["available"] is False
    assert c.get("/traces/exchanges").json()["exchanges"] == []
