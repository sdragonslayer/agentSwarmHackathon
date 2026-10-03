import json

from backend.analysis import artifacts, candidates, edges, lineage
from backend.db import connect
from backend.ingest import aivillage
from tests import synth

AID = artifacts.artifact_id("url", "https://example.test/Path/Case?token=AbC&x=1")


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


def _add_chat(con, n, actor, text, minute):
    ts = f"2026-01-01 00:{minute:02d}:00"
    con.execute(
        "INSERT INTO text_item VALUES (?, 's', 'chat_agent', ?, NULL, NULL, NULL, ?, ?::TIMESTAMP, ?, 'h', ?, FALSE, NULL, "
        "'f', 't', 'i')",
        [f"av:chat:x{n}", actor, ts, ts, text, len(text)],
    )


def test_paraphrase_from_other_label_is_a_possible_reuse_candidate(tmp_path):
    con = _con(tmp_path)
    _add_chat(con, 1, f"av:agent:{synth.A2}",
              "Found a workaround: https://example.test/Path/Case?token=AbC works for me. See PR #7 too, thanks", 6)
    res = candidates.build_for_artifact(con, AID)
    assert res["edges"] >= 1
    rows = con.execute(
        "SELECT relation, evidence_tier, directed, alternatives, support FROM evidence_edge "
        "WHERE relation = 'possible_reuse'"
    ).fetchall()
    rel, tier, directed, alts, support = rows[0]
    assert (rel, tier, directed) == ("possible_reuse", "rule_derived", False)
    s = json.loads(support)
    assert s["jaccard_word_shingles"] > 0.3 and s["settings"]["max_candidates"] == 20
    assert json.loads(alts)


def test_same_label_text_is_not_a_candidate(tmp_path):
    con = _con(tmp_path)
    _add_chat(con, 1, f"av:agent:{synth.A1}",
              "Found a workaround: https://example.test/Path/Case?token=AbC works for me. See PR #7 too, thanks", 6)
    assert candidates.build_for_artifact(con, AID)["edges"] == 0


def test_common_boilerplate_creates_no_candidate(tmp_path):
    con = _con(tmp_path)
    text = "Found a workaround: https://example.test/Path/Case?token=AbC works for me. See PR #7 too, thanks"
    for i in range(6):
        _add_chat(con, i, f"av:agent:{synth.A2}", text, 6 + i)
    # The shared phrases occur in six pool items, so they are boilerplate-like and carry no evidence.
    assert candidates.build_for_artifact(con, AID)["edges"] == 0


def test_rebuild_is_idempotent(tmp_path):
    con = _con(tmp_path)
    _add_chat(con, 1, f"av:agent:{synth.A2}",
              "Found a workaround: https://example.test/Path/Case?token=AbC works for me. See PR #7 too, thanks", 6)
    a = candidates.build_for_artifact(con, AID)
    b = candidates.build_for_artifact(con, AID)
    assert a == b
    assert con.execute("SELECT count(*) FROM evidence_edge WHERE relation = 'possible_reuse'").fetchone()[0] == a["edges"]
