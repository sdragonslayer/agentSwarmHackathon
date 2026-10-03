from backend.ingest import aivillage
from tests import synth


def _load(tmp_path):
    raw = tmp_path / "raw"
    synth.build(raw)
    return aivillage.load(raw, tmp_path / "t.duckdb", hash_files=False), tmp_path / "t.duckdb"


def test_chat_and_event_are_one_action(tmp_path):
    from backend.db import connect

    _, db = _load(tmp_path)
    con = connect(db)
    # Every chat item links to exactly one event, and no event carries two chat items.
    assert con.execute("SELECT count(*) FROM text_item WHERE kind='chat_agent' AND event_id IS NULL").fetchone()[0] == 0
    dup = con.execute(
        "SELECT count(*) FROM (SELECT event_id FROM text_item WHERE event_id IS NOT NULL AND kind LIKE 'chat%' "
        "GROUP BY 1 HAVING count(*) > 1)"
    ).fetchone()[0]
    assert dup == 0
    # The human line that has no chat row is still kept, once, from the event.
    assert con.execute("SELECT count(*) FROM text_item WHERE item_id LIKE 'av:evtalk:%'").fetchone()[0] == 1


def test_labels_namespaced_and_unmerged(tmp_path):
    from backend.db import connect

    _, db = _load(tmp_path)
    con = connect(db)
    labels = dict(con.execute("SELECT label_id, display_name FROM actor_label").fetchall())
    assert labels[f"av:agent:{synth.A1}"] == "Alpha"
    assert labels[f"av:user:{synth.H1}"] == "visitor"
    assert all(k.startswith(("av:agent:", "av:user:")) for k in labels)
    assert con.execute("SELECT count(*) FROM actor_label WHERE identity_status <> 'unverified_label'").fetchone()[0] == 0


def test_source_text_and_times_verbatim(tmp_path):
    from backend.db import connect

    _, db = _load(tmp_path)
    con = connect(db)
    row = con.execute("SELECT source_time, time_ts, text FROM text_item WHERE item_id = 'av:chat:11111111-0000-0000-0000-000000000001'").fetchone()
    assert row[0] == "2026-01-01 00:00:05.000000"
    assert str(row[1]).startswith("2026-01-01 00:00:05")
    assert synth.URL in row[2]
    # No inferred bounds: the source gives no uncertainty.
    assert con.execute("SELECT count(*) FROM event WHERE time_lower IS NOT NULL OR time_upper IS NOT NULL").fetchone()[0] == 0


def test_generated_summaries_flagged(tmp_path):
    from backend.db import connect

    _, db = _load(tmp_path)
    con = connect(db)
    assert con.execute("SELECT generated FROM text_item WHERE kind='generated_summary'").fetchone()[0] is True
    assert con.execute("SELECT count(*) FROM text_item WHERE generated AND kind <> 'generated_summary'").fetchone()[0] == 0


def test_reload_is_idempotent(tmp_path):
    raw = tmp_path / "raw"
    synth.build(raw)
    db = tmp_path / "t.duckdb"
    a = aivillage.load(raw, db, hash_files=False)
    b = aivillage.load(raw, db, hash_files=False)
    assert a == b
