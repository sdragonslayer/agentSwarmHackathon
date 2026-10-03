from backend.analysis import artifacts, edges, inflation, lineage, questions
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


def test_questionnaire_answers_and_abstains(tmp_path):
    con = _con(tmp_path)
    aid = artifacts.artifact_id("url", "https://example.test/Path/Case?token=AbC&x=1")
    answers = questions.answer_all(con, aid)
    by_id = {a["id"]: a for a in answers}
    assert len(answers) == 10
    assert by_id["earliest"]["status"] == "supported"
    assert by_id["earliest"]["citations"][0]["item_id"].endswith("0001")
    assert "2 author label" in by_id["introducers"]["claim"]
    # Unanswerable from the loaded data: abstain rather than guess.
    for q in ("references", "resemble", "claimed_use", "observed_use", "warnings"):
        assert by_id[q]["status"] == "unknown", q
    # Carryover is named as a competing explanation with real numbers.
    assert "2 of 7 total occurrences are carried-forward" in by_id["alternatives"]["claim"]
    assert all(a["limitations"] for a in answers)


def test_every_citation_resolves_to_exact_span(tmp_path):
    con = _con(tmp_path)
    for aid, in con.execute("SELECT artifact_id FROM artifact").fetchall():
        assert questions.verify_citations(con, questions.answer_all(con, aid)) == []


def test_tampered_citation_is_caught(tmp_path):
    con = _con(tmp_path)
    aid = artifacts.artifact_id("url", "https://example.test/Path/Case?token=AbC&x=1")
    answers = questions.answer_all(con, aid)
    answers[0]["citations"][0]["snippet"] = "not the source text"
    assert questions.verify_citations(con, answers)


def test_inflation_headline_has_denominators(tmp_path):
    con = _con(tmp_path)
    h = inflation.headline(con)
    mem = next(s for s in h["line_level_by_stream"] if s["stream"] == "mem")
    assert mem["items"] == 5 and mem["inherited_lines"] > 0
    url = next(t for t in h["artifact_level_by_type"] if t["artifact_type"] == "url")
    assert url["full_occurrences"] > url["novel_occurrences"]
