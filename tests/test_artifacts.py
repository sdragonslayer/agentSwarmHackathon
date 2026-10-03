from backend.analysis import artifacts, lineage
from backend.analysis.artifacts import extract
from backend.db import connect
from backend.ingest import aivillage
from tests import synth


def test_url_exact_string_preserved_and_only_host_lowercased():
    (h,) = extract("see (https://Example.TEST/Path/Case?token=AbC&x=1). thanks")
    assert h.raw == "https://Example.TEST/Path/Case?token=AbC&x=1"
    assert h.normalized == "https://example.test/Path/Case?token=AbC&x=1"  # path and query case preserved


def test_domain_alone_and_local_urls_are_not_artifacts():
    assert extract("go to example.test or http://localhost:3000/x and http://127.0.0.1/a") == []


def test_query_parameters_distinguish_artifacts():
    a, b = extract("https://x.test/a?k=1"), extract("https://x.test/a?k=2")
    assert a[0].normalized != b[0].normalized


def test_unqualified_pr_numbers_are_skipped_but_qualified_refs_kept():
    hits = extract("Opened PR #77 and also acme/widgets#12")
    assert [(h.artifact_type, h.normalized) for h in hits] == [("repo_ref", "acme/widgets#12")]


def test_hex_ids_need_digit_and_letter_and_skip_uuids_and_urls():
    hits = extract("commit a1b2c3d4e5 fixed it; word effaced; number 1234567; id 6a87b906-d847-4a4b-92fa-2fde93f60634")
    assert [(h.artifact_type, h.raw) for h in hits] == [("hex_id", "a1b2c3d4e5")]
    assert [h.artifact_type for h in extract("https://x.test/commit/a1b2c3d4e5")] == ["url"]


def test_span_offsets_resolve_in_item_text(tmp_path):
    raw = tmp_path / "raw"
    synth.build(raw)
    db = tmp_path / "t.duckdb"
    aivillage.load(raw, db, hash_files=False)
    con = connect(db)
    lineage.build(con)
    artifacts.build(con)
    rows = con.execute(
        "SELECT a.span_start, a.span_end, t.text, x.raw FROM appearance a "
        "JOIN text_item t USING (item_id) JOIN artifact x USING (artifact_id)"
    ).fetchall()
    assert rows
    for s, e, text, raw_str in rows:
        assert text[s:e] == raw_str


def test_inflation_counts_separate_carryover(tmp_path):
    raw = tmp_path / "raw"
    synth.build(raw)
    db = tmp_path / "t.duckdb"
    aivillage.load(raw, db, hash_files=False)
    con = connect(db)
    lineage.build(con)
    artifacts.build(con)
    aid = artifacts.artifact_id("url", "https://example.test/Path/Case?token=AbC&x=1")
    row = con.execute(
        "SELECT full_occurrences, novel_occurrences, full_items, novel_items, full_labels, novel_labels "
        "FROM artifact_counts WHERE artifact_id = ?",
        [aid],
    ).fetchone()
    # full: 2 chats, stop summary, session goal, memories 1 (first), 2 (inherited), 4 (restored)
    # novel: the same minus the inherited copy and the restored copy
    assert row == (7, 5, 7, 5, 2, 2)
    # The generated summary also mentions the URL but is excluded as secondary material.
    assert con.execute(
        "SELECT count(*) FROM appearance a JOIN text_item t USING (item_id) WHERE t.generated"
    ).fetchone()[0] == 0
    # Restored text is recorded as an appearance but flagged, not counted as novel.
    assert con.execute(
        "SELECT count(*) FROM appearance WHERE artifact_id = ? AND novelty = 'restored'", [aid]
    ).fetchone()[0] == 1


def test_template_placeholders_and_bad_ports_are_not_artifacts():
    """Regression from real data: http://host:${TOKEN} made urlsplit().port raise."""
    assert extract("curl http://example.test:${TOKEN}/x and https://{{host}}/a and http://[::1/b") == []
