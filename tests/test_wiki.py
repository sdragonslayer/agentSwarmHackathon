import json

import pytest

from backend.analysis import artifacts, edges, lineage, validate
from backend.db import connect
from backend.ingest import wiki
from tests import synth_wiki


def _built(tmp_path):
    raw = tmp_path / "raw"
    synth_wiki.build(raw)
    db = tmp_path / "w.duckdb"
    wiki.load(raw, db)
    con = connect(db)
    lineage.build(con)
    artifacts.build(con)
    edges.build(con)
    return raw, con


def test_load_maps_revisions_events_and_unknown_authors(tmp_path):
    _, con = _built(tmp_path)
    assert con.execute("SELECT count(*) FROM text_item WHERE kind = 'wiki_revision'").fetchone()[0] == 4
    assert con.execute("SELECT count(*) FROM event").fetchone()[0] == 6  # 4 saves + delete + probe
    # blank label = unknown author, never a shared label; ip16 never becomes a label
    assert con.execute("SELECT actor_label_id FROM text_item WHERE item_id = 'wiki:rev:dse~P1@3'").fetchone()[0] is None
    labels = {r[0] for r in con.execute("SELECT label_id FROM actor_label").fetchall()}
    assert labels == {"wiki:label:AgentAlpha", "wiki:label:AgentBeta", "wiki:label:[Admin1]"}
    # mojibake bodies are decoded by their documented encoding; the stored text is real text
    text = con.execute("SELECT text FROM text_item WHERE item_id = 'wiki:rev:dse~P1@2'").fetchone()[0]
    assert "Grüße aus München" in text
    # every save event carries its clock verbatim, with no derived bounds
    ev = con.execute("SELECT clock_provenance, time_lower FROM event WHERE event_id = 'wiki:ev:save:dse~P1@1'").fetchone()
    assert "uncertainty_seconds=1" in ev[0] and ev[1] is None
    note = con.execute("SELECT coverage_notes FROM snapshot").fetchone()[0]
    assert "1 of 2 pages start with incomplete lineage" in note  # computed from the data, not typed in


def test_lineage_uses_explicit_bases(tmp_path):
    _, con = _built(tmp_path)
    st = dict(con.execute("SELECT item_id, lineage_status FROM lineage_summary").fetchall())
    assert st["wiki:rev:dse~P1@1"] == "page_created"  # complete history: the whole text really is new
    assert st["wiki:rev:dse~P1@2"] == "explicit_base" and st["wiki:rev:dse~P1@3"] == "explicit_base"
    assert st["wiki:rev:dse~P2@5"] == "first_in_stream"  # earlier revisions unpublished: incomplete lineage
    inh = con.execute("SELECT n_inherited, n_new FROM lineage_summary WHERE item_id = 'wiki:rev:dse~P1@2'").fetchone()
    assert inh == (2, 1)  # two carried lines, one new line
    basis = {r[0] for r in con.execute("SELECT DISTINCT attribution_basis FROM text_change").fetchall()}
    assert basis == {"page_created", "explicit_diff_base", "inferred_predecessor_by_recorded_time"}


def test_all_validation_gates_pass_including_raw_checks(tmp_path):
    raw, con = _built(tmp_path)
    results = validate.run(con, sample=20, raw=raw)
    failed = [(n, d) for n, ok, d in results if not ok]
    assert not failed, failed
    assert any("hunk offsets" in n for n, _, _ in results)


def test_validator_catches_corruption(tmp_path):
    raw, con = _built(tmp_path)
    revs = [json.loads(x) for x in (raw / "revisions.jsonl").read_text(encoding="utf-8").splitlines()]
    # a hunk that lies about what changed
    revs[1]["hunks"] = [{"op": "insert", "a0": 0, "a1": 0, "b0": 0, "b1": 1}]
    (raw / "revisions.jsonl").write_text("\n".join(json.dumps(r) for r in revs) + "\n", encoding="utf-8")
    assert any(not ok and "hunk offsets" in n for n, ok, _ in wiki.validate_raw(raw))
    # a body that no longer matches its declared hash
    revs[1]["hunks"] = [{"op": "insert", "a0": 2, "a1": 2, "b0": 2, "b1": 3}]
    revs[0]["body_sha256"] = "0" * 64
    (raw / "revisions.jsonl").write_text("\n".join(json.dumps(r) for r in revs) + "\n", encoding="utf-8")
    assert any(not ok and "body_sha256" in n for n, ok, _ in wiki.validate_raw(raw))
    # the same kind of corruption in the database is caught by the generic hash gate
    con.execute("UPDATE text_item SET text = text || ' tampered' WHERE item_id = 'wiki:rev:dse~P1@2'")
    assert not validate.check_source_hashes(con)[1]


def test_loader_requires_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        wiki.load(tmp_path / "empty", tmp_path / "x.duckdb")


def test_exact_url_links_labels_across_pages(tmp_path):
    _, con = _built(tmp_path)
    # the URL is first written by AgentAlpha on P1 and appears in AgentBeta's new text on P2
    assert con.execute("SELECT count(*) FROM evidence_edge WHERE relation = 'same_content'").fetchone()[0] == 1
