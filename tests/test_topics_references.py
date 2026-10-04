from backend.analysis import artifacts, edges, lineage, references, topics
from backend.db import connect
from backend.ingest import wiki
from tests import synth_exchange


def _built(tmp_path):
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
    return con


def test_lexicon_matches_words_phrases_wildcards_and_masks_urls():
    compiled = topics.compile_lexicon(topics.load_lexicon())
    hits = {(c, t) for c, t, _, _ in topics.find_cues("Please RELAYED answers; bypass the proxy. Bitte warten.", compiled)}
    assert ("request_relay", "relayed") in hits and ("answer_sharing", "answers") in hits
    assert ("bypass_circumvention", "bypass") in hits and ("bypass_circumvention", "proxy") in hits
    assert ("request_relay", "bitte") in hits
    # word boundaries: 'proxying' is not 'proxy'; URL text never matches
    assert not any(t == "proxy" for _, t, _, _ in topics.find_cues("proxying along", compiled))
    assert topics.find_cues("see https://proxy.example.test/answer/bypass now", compiled) == []


def test_cues_only_count_new_text_and_spans_resolve(tmp_path):
    con = _built(tmp_path)
    # Charlie's revision PageA@2 inherits Alpha's lines: only its one new line can hold cues
    inherited = con.execute(
        "SELECT count(*) FROM cue_hit WHERE item_id = 'wiki:rev:dse~PageA@2' AND category = 'answer_sharing'").fetchone()[0]
    assert inherited == 0
    rows = con.execute("SELECT h.span_start, h.span_end, h.term, t.text FROM cue_hit h JOIN text_item t USING (item_id)").fetchall()
    assert rows
    for s, e, term, text in rows:
        assert text[s:e].lower().replace("  ", " ") == term or text[s:e].lower().startswith(term[:3])


def test_topics_matrix_uses_source_page_family(tmp_path):
    con = _built(tmp_path)
    m = topics.matrix(con)
    by = {t["topic"]: t for t in m["topics"]}
    assert "datausa-test" in by and "relay-coordination" in by
    assert by["datausa-test"]["cells"]["answer_sharing"]["items"] == 1  # PageA@1 only (PageA@2 inherits)
    assert by["relay-coordination"]["cells"]["bypass_circumvention"]["items"] >= 1
    ex = topics.examples(con, "datausa-test", "answer_sharing")
    assert ex and ex[0]["snippet"]["match"].lower() in ("answer", "answers")


def test_references_resolve_pages_and_labels_and_skip_plain_words(tmp_path):
    con = _built(tmp_path)
    refs = con.execute("SELECT ref_type, target_kind, target_text, resolved FROM reference ORDER BY ref_type, target_text").fetchall()
    kinds = {(r[0], r[2]) for r in refs}
    assert ("wikilink", "PageBravoLive") in kinds
    assert ("label_mention", "AgentBravo09") in kinds and ("label_mention", "AgentAlpha07") in kinds
    assert not any(r[2] == "Research" for r in refs)  # an ordinary word that happens to be a label name
    assert all(r[3] for r in refs)
    # the carried-forward copy in PageA@2 is not a new reference
    n_a2 = con.execute("SELECT count(*) FROM reference WHERE item_id = 'wiki:rev:dse~PageA@2'").fetchone()[0]
    assert n_a2 == 0


def test_exchange_needs_mutual_naming_within_window(tmp_path):
    con = _built(tmp_path)
    ex = con.execute("SELECT a_label_id, b_label_id, seconds FROM exchange").fetchall()
    assert ex == [("wiki:label:AgentAlpha07", "wiki:label:AgentBravo09", 5400)]  # Alpha names Bravo, Bravo names Alpha 90 min later


def test_questions_report_activity_topics_spread_and_references(tmp_path):
    from backend.analysis import questions

    con = _built(tmp_path)
    aid = artifacts.artifact_id("url", synth_exchange.URL)
    ans = {a["id"]: a for a in questions.answer_all(con, aid)}
    assert ans["topics"]["status"] == "supported" and "datausa-test" in ans["topics"]["claim"]
    assert ans["activity"]["status"] == "supported" and "answer sharing" in ans["activity"]["claim"]
    assert ans["spread"]["status"] == "supported" and "AgentBravo09" in ans["spread"]["claim"]
    # the later (Bravo) revision names Alpha, who already wrote the URL on another page
    assert ans["references"]["status"] == "supported" and ans["references"]["citations"]
    # every citation, including the new ones, resolves to its exact source span
    assert questions.verify_citations(con, list(ans.values())) == []
    assert ans["activity"]["limitations"] and "not verdicts" in ans["activity"]["limitations"][1]


def test_trace_tables_have_denominators_and_answer_provenance(tmp_path):
    from backend.analysis import traces

    con = _built(tmp_path)
    ts = {r["topic"]: r for r in traces.topic_summary(con)}
    assert ts["datausa-test"]["revisions"] == 2 and ts["datausa-test"]["cue:answer_sharing"] == 1
    # the exchange is filed under the topic of the page where the first label wrote
    assert ts["datausa-test"]["exchanges"] == 1 and ts["datausa-test"]["exchange_label_pairs"] == 1
    # 9.69 (Alpha) and 9.70 (Bravo) are different numbers, so none is shared by two labels here
    assert traces.answer_numbers(con) == []
    prov = traces.answer_provenance(con)
    assert all(r["with_explicit_pointer"] <= r["repetitions_by_new_labels"] for r in prov)
    hosts = traces.host_adoption(con, min_labels=2)
    assert hosts and hosts[0]["host"] == "example.test" and hosts[0]["labels"] >= 2
    ca = traces.category_adoption(con)
    assert ca and all(r["arrivals_using_cue"] <= r["arrivals"] for r in ca)
    answer = [r for r in ca if r["category"] == "answer_sharing"]
    assert sum(r["arrivals"] for r in answer) == 3 and sum(r["arrivals_using_cue"] for r in answer) == 2  # Alpha, Bravo use it
    burst = traces.arrival_burst(con)
    assert burst["labels"] == 3 and burst["busiest_week_labels"] >= 1 and 0 < burst["share"] <= 1
    assert "not verdicts" in traces.caveat(con)
    ex = traces.exchanges(con)
    assert ex[0]["a"]["snippet"]["match"] == "AgentBravo09" and "request_relay" in ex[0]["a_cues"]
