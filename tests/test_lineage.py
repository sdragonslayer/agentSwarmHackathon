from backend.analysis import lineage
from backend.analysis.lineage import classify_stream


def cls(res):
    return {(c[1], c[2]) for c in res.changes}


def test_unchanged_text_across_ten_items_is_one_introduction():
    text = "alpha line one\nbeta line two"
    results = classify_stream((f"i{k}", text) for k in range(10))
    assert [r.status for r in results] == ["first_in_stream"] + ["inferred_predecessor"] * 9
    assert len(results[0].changes) == 2 and all(c[2] == "first_observed" for c in results[0].changes)
    for r in results[1:]:
        assert r.changes == [] and r.n_inherited == 2


def test_first_item_is_incomplete_lineage_not_new():
    (r,) = classify_stream([("only", "a long distinctive line here")])
    assert r.base_item_id is None and r.status == "first_in_stream"
    assert {c[2] for c in r.changes} == {"first_observed"}


def test_restore_is_not_new_authorship():
    a, b, c = "the workaround line is here", "another stable rule", "an insight about caching"
    items = [("1", f"{a}\n{b}"), ("2", f"{b}\n{c}"), ("3", f"{b}\n{c}\n{a}")]
    _, r2, r3 = classify_stream(items)
    assert (c, "new") in cls(r2)
    assert cls(r3) == {(a, "restored")}


def test_modified_vs_new():
    base = "Remember that PR 7 is merged into main"
    edited = "Remember that PR 7 is merged into main and deployed"
    items = [("1", f"{base}\nkeep"), ("2", f"{edited}\nkeep\ncompletely unrelated sentence that is long enough")]
    _, r2 = classify_stream(items)
    kinds = {c[1]: (c[2], c[3]) for c in r2.changes}
    assert kinds[edited][0] == "modified" and kinds[edited][1] >= 0.80
    assert kinds["completely unrelated sentence that is long enough"][0] == "new"


def test_blank_lines_ignored_and_line_numbers_preserved():
    (r,) = classify_stream([("1", "first\n\n\nsecond")])
    assert [(c[0], c[1]) for c in r.changes] == [(0, "first"), (3, "second")]


def test_build_on_synthetic_db(tmp_path):
    from backend.db import connect
    from backend.ingest import aivillage
    from tests import synth

    raw = tmp_path / "raw"
    synth.build(raw)
    db = tmp_path / "t.duckdb"
    aivillage.load(raw, db, hash_files=False)
    con = connect(db)
    totals = lineage.build(con)
    assert totals["items"] == 4 + 1 + 1  # 4 Alpha memories, 1 Beta memory, 1 session goal
    # Beta repeats an Alpha line but is its own stream: first_observed, never "inherited" across labels.
    beta = con.execute(
        "SELECT lineage_status, n_inherited, n_first_observed FROM lineage_summary WHERE item_id = 'av:mem:33333333-0000-0000-0000-000000000005'"
    ).fetchone()
    assert beta == ("first_in_stream", 0, 2)
    restored = con.execute("SELECT text FROM text_change WHERE classification = 'restored'").fetchall()
    assert [r[0] for r in restored] == [f"Workaround: {synth.URL}"]


def test_build_handles_many_rows_before_first_float(tmp_path):
    """Regression: polars used to infer the similarity dtype from the first 100 rows (all None)."""
    from backend.db import connect

    con = connect(tmp_path / "t.duckdb")
    rows = [(f"av:mem:{i:03d}", "mem:x", f"2026-01-01 00:00:{i:02d}") for i in range(2)]
    first = "\n".join(f"unique first line number {i} with enough text" for i in range(150))
    second = first.replace("number 7 ", "number seven ") + "\nbrand new line that is quite long indeed"
    texts = [first, second]
    for (iid, key, ts), text in zip(rows, texts, strict=True):
        con.execute(
            "INSERT INTO text_item (item_id, snapshot_id, kind, actor_label_id, event_id, room_id, session_id, source_time, time_ts, text, text_sha256, text_len, generated, stream_key, source_file, source_table, source_id) VALUES (?, 's', 'memory', NULL, NULL, NULL, NULL, ?, ?::TIMESTAMP, ?, 'h', ?, FALSE, ?, "
            "'f', 't', 'i')",
            [iid, ts, ts, text, len(text), key],
        )
    lineage.build(con)
    got = con.execute("SELECT classification, count(*) FROM text_change GROUP BY 1 ORDER BY 1").fetchall()
    assert dict(got) == {"first_observed": 150, "modified": 1, "new": 1}


def test_explicit_base_page_created_vs_incomplete():
    a, b = "the first revision line is long enough", "a second distinct line that is also long"
    created = classify_stream([("r1", f"{a}\n{b}", None, "page_created"), ("r2", f"{a}", "r1", "explicit")])
    assert created[0].status == "page_created" and {c[2] for c in created[0].changes} == {"new"}
    assert created[1].status == "explicit_base" and created[1].base_item_id == "r1" and created[1].n_inherited == 1
    incomplete = classify_stream([("r1", f"{a}\n{b}", None, "incomplete")])
    assert incomplete[0].status == "first_in_stream" and {c[2] for c in incomplete[0].changes} == {"first_observed"}


def test_explicit_base_must_be_immediate_predecessor():
    import pytest

    with pytest.raises(ValueError):
        classify_stream([("r1", "x" * 30, None, "page_created"), ("r2", "y" * 30, "r1", "explicit"),
                         ("r3", "z" * 30, "r1", "explicit")])
    with pytest.raises(ValueError):
        classify_stream([("r1", "x" * 30, None, "page_created"), ("r2", "y" * 30, None, "page_created")])
