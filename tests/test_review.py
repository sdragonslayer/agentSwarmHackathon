import json

from backend.analysis import artifacts, edges, lineage, review_pack, review_score
from backend.db import connect
from backend.ingest import aivillage
from tests import synth


def _con(tmp_path):
    raw = tmp_path / "raw"
    synth.build(raw)
    db = tmp_path / "t.duckdb"
    aivillage.load(raw, db, hash_files=False)
    con = connect(db)
    lineage.build(con)
    artifacts.build(con)
    edges.build(con)
    return con


def test_pack_is_blind_deterministic_and_inert(tmp_path):
    con = _con(tmp_path)
    items = review_pack.build_items(con)
    assert items and [i["id"] for i in items][:2] == ["R001", "R002"]
    sections = {i["section"] for i in items}
    assert {"edge", "extraction", "question"} <= sections
    out = tmp_path / "pack"
    review_pack.write(items, out)
    html = (out / "review_pack.html").read_text(encoding="utf-8")
    assert "innerHTML" not in html and html.count("</script>") == 1
    # The reviewer-facing payload never carries the system's own class/status/score (avoids anchoring).
    pack_json = html.split("const PACK = ")[1].split(";\nconst KEY")[0]
    for hidden in ('"system_class"', '"status"', '"jaccard"', '"temporal_status"'):
        assert hidden not in pack_json
    key = json.loads((out / "review_key.json").read_text(encoding="utf-8"))
    assert any("temporal_status" in k for k in key["items"])
    assert (out / "review_sheet.csv").read_text(encoding="utf-8").startswith("item_id,section")
    again = review_pack.build_items(con)
    assert [i["id"] for i in again] == [i["id"] for i in items]


def test_scoring_and_wilson_interval():
    lo, hi = review_score.wilson(9, 10)
    assert 0.55 < lo < 0.60 and 0.97 < hi < 0.99
    assert review_score.wilson(0, 0) == (0.0, 0.0)
    key = {"items": [
        {"id": "R001", "section": "edge", "relation": "same_content", "artifact_type": "url",
         "temporal_status": "sequence_ordered"},
        {"id": "R002", "section": "edge", "relation": "same_content", "artifact_type": "url",
         "temporal_status": "timestamp_ordered_unbounded"},
        {"id": "R003", "section": "lineage", "system_class": "modified"},
        {"id": "R004", "section": "extraction", "artifact_type": "hex_id"},
    ]}
    rv = [{"reviewer": "A", "results": {
        "R001": {"a1": "accept", "a2": "none"}, "R002": {"a1": "reject", "a2": "none"},
        "R003": {"a1": "edit"}, "R004": {"a1": "yes", "a2": "distinctive"}}}]
    tallies, md = review_score.score(key, rv)
    assert tallies["same_content (all types)"] == {"hits": 1, "n": 2}
    assert tallies["lineage (all classes)"] == {"hits": 1, "n": 1}
    assert tallies["extraction precision (all types)"] == {"hits": 1, "n": 1}
    assert "1/2 = 50%" in md and "95% CI" in md
