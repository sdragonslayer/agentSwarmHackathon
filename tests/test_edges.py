import json

from backend.analysis import artifacts, edges, lineage
from backend.db import connect
from backend.ingest import aivillage
from tests import synth


def _build(tmp_path):
    raw = tmp_path / "raw"
    synth.build(raw)
    db = tmp_path / "t.duckdb"
    aivillage.load(raw, db, hash_files=False)
    con = connect(db)
    lineage.build(con)
    artifacts.build(con)
    return con, edges.build(con)


def test_same_content_edge_is_cross_label_undirected_and_honest(tmp_path):
    con, _ = _build(tmp_path)
    rows = con.execute(
        "SELECT src_item_id, dst_item_id, relation, evidence_tier, temporal_status, directed, alternatives, support "
        "FROM evidence_edge"
    ).fetchall()
    assert len(rows) == 1  # same-label repeats and inherited/restored copies create no edges
    src, dst, rel, tier, temporal, directed, alts, support = rows[0]
    assert src.endswith("0001") and dst.endswith("0002")
    assert rel == "same_content" and tier == "rule_derived"
    assert directed is False
    assert temporal == "sequence_ordered"  # both are chat events with distinct event_index
    assert json.loads(alts)  # competing explanations are always attached
    s = json.loads(support)
    text = con.execute("SELECT text FROM text_item WHERE item_id = ?", [src]).fetchone()[0]
    assert text[s["src"]["span_start"]:s["src"]["span_end"]] == synth.URL


def test_same_label_repeat_makes_no_edge(tmp_path):
    con, _ = _build(tmp_path)
    # URL_OTHER appears only in Beta's chat and Beta's own memory: no cross-label edge.
    n = con.execute(
        "SELECT count(*) FROM evidence_edge e JOIN artifact a USING (artifact_id) WHERE a.raw = ?",
        [synth.URL_OTHER],
    ).fetchone()[0]
    assert n == 0


def test_widely_repeated_artifact_gets_no_edges(tmp_path, monkeypatch):
    monkeypatch.setattr(edges, "MAX_ITEMS_PER_ARTIFACT", 3)
    _, res = _build(tmp_path)
    assert res["edges"] == 0 and res["widely_repeated_artifacts_skipped"] >= 1
