import re

from backend.analysis import artifacts, candidates, edges, lineage, report
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


def test_report_is_self_contained_and_escapes_corpus_text(tmp_path):
    con = _con(tmp_path)
    # Hostile text in the corpus must not be able to close the script tag or inject markup.
    evil = "x </script><script>alert(1)</script> <!-- https://example.test/Path/Case?token=AbC&x=1"
    con.execute("UPDATE text_item SET text = ? WHERE item_id = 'av:chat:11111111-0000-0000-0000-000000000002'", [evil])
    artifacts.build(con)
    edges.build(con)
    candidates.build_for_artifact(con, artifacts.artifact_id("url", "https://example.test/Path/Case?token=AbC&x=1"))
    html = report.render(report.build_payload(con))
    assert html.count("</script>") == 1  # only the template's own closing tag survives
    assert "<script>alert(1)" not in html
    assert not re.search(r"https?://(?!example\.test|www\.w3\.org|collusion|swarmtraces)[^\s\"']*\.(js|css)", html)
    assert "innerHTML" not in html and "eval(" not in html


def test_payload_has_cases_with_edges_and_questions(tmp_path):
    con = _con(tmp_path)
    p = report.build_payload(con)
    assert p["cases"] and p["inflation"]["line_level_by_stream"]
    case = p["cases"][0]
    assert len(case["answers"]) == 10 and case["edges"]
    assert case["appearances"][0]["snippet"]["match"] == synth.URL
