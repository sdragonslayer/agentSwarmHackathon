"""Integrity gates over a built database (brief §11A). Source-agnostic, with per-source extras.

    uv run python -m backend.analysis.validate --db data/derived/swarm.duckdb [--sample 200]
    uv run python -m backend.analysis.validate --db data/derived/wiki.duckdb --raw data/raw/full-wiki-logs

Generic gates run on any database that follows the schema (namespaced ids, unmerged labels, verbatim times, lineage
accounting, explicit-base consistency, source-hash round-trips, edge semantics, citations). Source-specific gates
are selected by the snapshot's `source`: AI Village adds its chat/event pairing; the wiki adds raw-file checks
(hash and hunk conventions, manifest reconciliation) when `--raw` points at the downloaded files.
Each check returns (name, passed, detail). Nothing here mutates data.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import duckdb

from backend.analysis import questions
from backend.db import DEFAULT_DB, connect

Check = tuple[str, bool, str]
# Python codec that reproduces the bytes a source hashed, by the source's declared encoding name.
HASH_CODECS = {"ascii": "utf-8", "utf8": "utf-8", "latin1": "latin-1"}
NAMESPACE_RE = r"^[a-z][a-z0-9]*:"
LABEL_RE = r"^[a-z][a-z0-9]*:[a-z]+:.+"


def _one(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    return con.execute(sql, params or []).fetchone()[0]


def source_of(con) -> str:
    row = con.execute("SELECT source FROM snapshot LIMIT 1").fetchone()
    return row[0] if row else "unknown"


def check_one_record_per_event(con) -> Check:
    """A source action must not appear as two independent records (e.g. a chat row plus its event)."""
    dup = _one(con, "SELECT count(*) FROM (SELECT event_id FROM text_item WHERE event_id IS NOT NULL "
                    "GROUP BY event_id, kind HAVING count(*) > 1)")
    dangling = _one(con, "SELECT count(*) FROM text_item WHERE event_id IS NOT NULL AND event_id NOT IN "
                         "(SELECT event_id FROM event)")
    src = source_of(con)
    extra, ok = "", True
    if src == "aivillage":
        talk = _one(con, "SELECT count(*) FROM event WHERE kind = 'AGENT_TALK'")
        chat = _one(con, "SELECT count(*) FROM text_item WHERE kind = 'chat_agent'")
        unlinked = _one(con, "SELECT count(*) FROM text_item WHERE kind = 'chat_agent' AND event_id IS NULL")
        extra, ok = f"; AGENT_TALK events={talk} chat_agent items={chat} unlinked={unlinked}", talk == chat and unlinked == 0
    elif src == "wiki":
        saves = _one(con, "SELECT count(*) FROM event WHERE kind = 'save'")
        revs = _one(con, "SELECT count(*) FROM text_item WHERE kind = 'wiki_revision'")
        unlinked = _one(con, "SELECT count(*) FROM text_item WHERE kind = 'wiki_revision' AND event_id IS NULL")
        extra, ok = f"; save events={saves} revision items={revs} unlinked={unlinked}", saves == revs and unlinked == 0
    return ("one record per source action (no double counting)", dup == dangling == 0 and ok,
            f"events linked to 2+ items of one kind={dup} dangling links={dangling}{extra}")


def check_label_integrity(con) -> Check:
    bad_ns = _one(con, f"SELECT count(*) FROM actor_label WHERE NOT regexp_matches(label_id, '{LABEL_RE}')")
    merged = _one(con, "SELECT count(*) FROM actor_label WHERE identity_status <> 'unverified_label'")
    empty_id = _one(con, "SELECT count(*) FROM actor_label WHERE label_id LIKE '%:' OR "
                         "(display_name IS NOT NULL AND trim(display_name) = '')")
    bad_ids = _one(con, f"SELECT (SELECT count(*) FROM text_item WHERE NOT regexp_matches(item_id, '{NAMESPACE_RE}')) + "
                        f"(SELECT count(*) FROM event WHERE NOT regexp_matches(event_id, '{NAMESPACE_RE}'))")
    orphan = _one(con, "SELECT count(*) FROM event WHERE actor_label_id IS NOT NULL AND actor_label_id NOT IN "
                       "(SELECT label_id FROM actor_label)")
    orphan_i = _one(con, "SELECT count(*) FROM text_item WHERE actor_label_id IS NOT NULL AND actor_label_id NOT IN "
                         "(SELECT label_id FROM actor_label)")
    unknown_e = _one(con, "SELECT count(*) FROM event WHERE actor_label_id IS NULL")
    unknown_i = _one(con, "SELECT count(*) FROM text_item WHERE actor_label_id IS NULL")
    return ("ids namespaced; labels unmerged; blank author stays unknown (never a shared label)",
            bad_ns == merged == empty_id == bad_ids == orphan == orphan_i == 0,
            (f"unknown author (kept NULL, not merged): events={unknown_e} items={unknown_i}; orphan labels="
             f"{orphan + orphan_i}; bad namespaces={bad_ns + bad_ids}"))


def check_time_fields(con) -> Check:
    unparsed = _one(con, "SELECT count(*) FROM event WHERE time_ts IS NULL AND source_time IS NOT NULL")
    bounds = _one(con, "SELECT count(*) FROM event WHERE time_lower IS NOT NULL OR time_upper IS NOT NULL")
    inversions = _one(
        con, "SELECT count(*) FROM (SELECT time_ts, lag(time_ts) OVER (ORDER BY event_index) p FROM event "
             "WHERE event_index IS NOT NULL) WHERE p > time_ts")
    n = _one(con, "SELECT count(*) FROM event")
    no_seq = _one(con, "SELECT count(*) FROM event WHERE event_index IS NULL")
    return ("source times kept verbatim; no invented bounds", unparsed == 0 and bounds == 0,
            (f"events={n} unparsed={unparsed} invented bounds={bounds}; event_index vs time inversions={inversions}; "
             f"events without a source sequence number={no_seq}"))


def check_lineage_accounting(con) -> Check:
    bad = _one(con, "SELECT count(*) FROM lineage_summary WHERE n_lines <> n_inherited + n_new + n_modified + "
                    "n_restored + n_first_observed")
    changes = _one(con, "SELECT count(*) FROM text_change")
    summed = _one(con, "SELECT coalesce(sum(n_new + n_modified + n_restored + n_first_observed), 0) "
                       "FROM lineage_summary")
    first_bad = _one(con, "SELECT count(*) FROM lineage_summary WHERE lineage_status = 'first_in_stream' "
                          "AND (n_inherited <> 0 OR n_new <> 0 OR n_modified <> 0 OR n_restored <> 0)")
    created_bad = _one(con, "SELECT count(*) FROM lineage_summary WHERE lineage_status = 'page_created' AND "
                            "(n_inherited <> 0 OR n_modified <> 0 OR n_restored <> 0 OR n_first_observed <> 0)")
    cont_bad = _one(con, "SELECT count(*) FROM lineage_summary WHERE lineage_status IN "
                         "('inferred_predecessor', 'explicit_base') AND (n_first_observed <> 0 OR base_item_id IS NULL)")
    multi_start = _one(con, "SELECT count(*) FROM (SELECT stream_key FROM lineage_summary WHERE lineage_status IN "
                            "('first_in_stream', 'page_created') GROUP BY 1 HAVING count(*) > 1)")
    no_start = _one(con, "SELECT count(*) FROM (SELECT stream_key FROM lineage_summary GROUP BY 1 HAVING "
                         "count(*) FILTER (WHERE lineage_status IN ('first_in_stream', 'page_created')) = 0)")
    cross = _one(con, "SELECT count(*) FROM lineage_summary l JOIN lineage_summary b ON b.item_id = l.base_item_id "
                      "WHERE b.stream_key <> l.stream_key")
    starts = dict(con.execute("SELECT lineage_status, count(*) FROM lineage_summary GROUP BY 1").fetchall())
    ok = bad == first_bad == created_bad == cont_bad == multi_start == no_start == cross == 0 and changes == summed
    detail = (
        f"rows with bad sums={bad}; text_change={changes} vs summary={summed}; start-item violations="
        f"{first_bad + created_bad}; continuation violations={cont_bad}; streams with 2 starts={multi_start}; "
        f"streams with none={no_start}; cross-stream bases={cross}; statuses={starts}"
    )
    return ("lineage counts add up; stream starts are labelled correctly; no cross-stream inheritance", ok, detail)


def check_explicit_bases(con) -> Check:
    """An explicit source base must be the immediate predecessor in its stream, ordered by the source's sequence."""
    n = _one(con, "SELECT count(*) FROM text_item WHERE base_item_id IS NOT NULL")
    bad = _one(con, """
        SELECT count(*) FROM (
            SELECT item_id, base_item_id, lag(item_id) OVER (PARTITION BY stream_key ORDER BY stream_seq, item_id) AS prev
            FROM text_item WHERE stream_key IS NOT NULL AND stream_seq IS NOT NULL
        ) WHERE base_item_id IS NOT NULL AND base_item_id IS DISTINCT FROM prev""")
    missing = _one(con, "SELECT count(*) FROM text_item WHERE base_item_id IS NOT NULL AND base_item_id NOT IN "
                        "(SELECT item_id FROM text_item)")
    dup_seq = _one(con, "SELECT count(*) FROM (SELECT stream_key, stream_seq FROM text_item WHERE stream_seq IS NOT NULL "
                        "GROUP BY 1, 2 HAVING count(*) > 1)")
    return ("explicit bases are the immediate predecessor; stream sequence numbers are unique", bad == missing == dup_seq == 0,
            f"items with an explicit base={n} not the predecessor={bad} missing base={missing} duplicate seq={dup_seq}")


def check_source_hashes(con) -> Check:
    rows = con.execute("SELECT item_id, text, source_sha256, source_encoding FROM text_item "
                       "WHERE source_sha256 IS NOT NULL").fetchall()
    bad = unknown_enc = 0
    for _, text, digest, enc in rows:
        codec = HASH_CODECS.get(enc)
        if codec is None:
            unknown_enc += 1
            continue
        bad += hashlib.sha256(text.encode(codec)).hexdigest() != digest
    return ("source-declared hashes round-trip from the stored text (no silent normalization)",
            bad == unknown_enc == 0, f"items with a source hash={len(rows)} mismatches={bad} unknown encodings={unknown_enc}")


def check_lineage_independent(con, sample: int, seed: int = 7) -> Check:
    """Recompute inherited counts for sampled item/base pairs with a different method (SQL set operations)."""
    pairs = con.execute(
        "SELECT item_id, base_item_id FROM lineage_summary WHERE base_item_id IS NOT NULL "
        "ORDER BY md5(item_id || ?) LIMIT ?",
        [str(seed), sample],
    ).fetchall()
    mismatches = []
    for item, base in pairs:
        n_inh = con.execute(
            """
            WITH cur AS (SELECT DISTINCT rtrim(l) AS l FROM (SELECT unnest(string_split(text, chr(10))) AS l
                                                             FROM text_item WHERE item_id = ?) WHERE trim(l) <> ''),
                 prev AS (SELECT DISTINCT rtrim(l) AS l FROM (SELECT unnest(string_split(text, chr(10))) AS l
                                                              FROM text_item WHERE item_id = ?) WHERE trim(l) <> '')
            SELECT count(*) FROM cur WHERE l IN (SELECT l FROM prev)
            """,
            [item, base],
        ).fetchone()[0]
        stored = con.execute(
            "SELECT n_lines - n_new - n_modified - n_restored - n_first_observed FROM lineage_summary WHERE item_id = ?",
            [item],
        ).fetchone()[0]
        # lineage counts every non-blank line (duplicates included); the SQL check counts distinct lines
        dup_extra = con.execute(
            """
            SELECT count(*) - count(DISTINCT rtrim(l)) FROM (SELECT unnest(string_split(text, chr(10))) AS l
                   FROM text_item WHERE item_id = ?) WHERE trim(l) <> '' AND rtrim(l) IN (
                   SELECT rtrim(p) FROM (SELECT unnest(string_split(text, chr(10))) AS p
                                         FROM text_item WHERE item_id = ?))
            """,
            [item, base],
        ).fetchone()[0]
        if stored != n_inh + dup_extra:
            mismatches.append((item, stored, n_inh + dup_extra))
    return ("lineage inherited counts match an independent SQL computation", not mismatches,
            f"sampled item/base pairs={len(pairs)} mismatches={len(mismatches)} {mismatches[:3]}")


def check_citations(con, sample: int, seed: int = 7) -> Check:
    arts = [r[0] for r in con.execute(
        "SELECT artifact_id FROM artifact_counts WHERE novel_items >= 2 ORDER BY md5(artifact_id || ?) LIMIT ?",
        [str(seed), sample]).fetchall()]
    problems = []
    for a in arts:
        problems += questions.verify_citations(con, questions.answer_all(con, a))
    spans = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE substr(t.text, a.span_start + 1, a.span_end - a.span_start) = x.raw) "
        "FROM (SELECT * FROM appearance ORDER BY md5(item_id || artifact_id || ?) LIMIT ?) a "
        "JOIN text_item t USING (item_id) JOIN artifact x USING (artifact_id)",
        [str(seed), sample * 50],
    ).fetchone()
    detail = (
        f"artifacts answered={len(arts)} citation problems={len(problems)}; sampled appearance spans={spans[0]} "
        f"matching first-seen raw string={spans[1]} (others are other surface forms of the same artifact)"
    )
    return ("exported citations and appearance spans resolve to exact source text", not problems, detail)


def check_edges(con) -> Check:
    same_label = _one(con, "SELECT count(*) FROM evidence_edge e JOIN text_item a ON a.item_id = e.src_item_id "
                           "JOIN text_item b ON b.item_id = e.dst_item_id "
                           "WHERE a.actor_label_id = b.actor_label_id OR a.actor_label_id IS NULL "
                           "OR b.actor_label_id IS NULL")
    directed = _one(con, "SELECT count(*) FROM evidence_edge WHERE directed AND relation IN "
                         "('same_content', 'possible_reuse')")
    bad_tier = _one(con, "SELECT count(*) FROM evidence_edge WHERE evidence_tier NOT IN "
                         "('source_recorded', 'rule_derived', 'model_proposed', 'human_reviewed')")
    no_alt = _one(con, "SELECT count(*) FROM evidence_edge WHERE alternatives IS NULL")
    generated = _one(con, "SELECT count(*) FROM evidence_edge e JOIN text_item t ON t.item_id IN "
                          "(e.src_item_id, e.dst_item_id) WHERE t.generated")
    bad_seq = _one(con, "SELECT count(*) FROM evidence_edge e JOIN text_item a ON a.item_id = e.src_item_id "
                        "JOIN text_item b ON b.item_id = e.dst_item_id JOIN event x ON x.event_id = a.event_id "
                        "JOIN event y ON y.event_id = b.event_id "
                        "WHERE e.temporal_status = 'sequence_ordered' AND x.event_index >= y.event_index")
    n = _one(con, "SELECT count(*) FROM evidence_edge")
    ok = same_label == directed == bad_tier == no_alt == generated == bad_seq == 0
    detail = (
        f"edges={n} same/unknown-label={same_label} directed={directed} bad tier={bad_tier} "
        f"missing alternatives={no_alt} touching generated text={generated} bad sequence claims={bad_seq}"
    )
    return ("edges: cross-label, undirected, tiered, with alternatives, never from generated text", ok, detail)


def check_inflation_consistent(con) -> Check:
    bad = _one(con, "SELECT count(*) FROM artifact_counts WHERE novel_occurrences > full_occurrences "
                    "OR novel_items > full_items OR novel_labels > full_labels")
    orphan = _one(con, "SELECT count(*) FROM artifact_counts WHERE artifact_id NOT IN (SELECT artifact_id FROM artifact)")
    no_novel = _one(con, "SELECT count(*) FROM artifact_counts WHERE novel_occurrences = 0")
    return ("artifact counts consistent (novel <= full)", bad == orphan == 0,
            f"violations={bad} orphans={orphan}; artifacts seen only in restored text (no novel appearance)={no_novel}")


def run(con: duckdb.DuckDBPyConnection, sample: int = 200, raw: Path | None = None) -> list[Check]:
    checks = [
        check_one_record_per_event(con),
        check_label_integrity(con),
        check_time_fields(con),
        check_lineage_accounting(con),
        check_explicit_bases(con),
        check_source_hashes(con),
        check_lineage_independent(con, min(sample, 200)),
        check_inflation_consistent(con),
        check_citations(con, sample),
        check_edges(con),
    ]
    if source_of(con) == "wiki" and raw is not None:
        from backend.ingest import wiki

        checks += wiki.validate_raw(raw)
    return checks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--sample", type=int, default=200)
    ap.add_argument("--raw", type=Path, help="raw files directory, enables source-specific raw checks (wiki)")
    args = ap.parse_args()
    con = connect(args.db)
    src = source_of(con)
    print(f"source: {src}")
    if src == "wiki" and args.raw is None:
        print("note: pass --raw <dir> to also run the wiki raw-file checks (hashes, hunks, manifest)")
    failed = 0
    for name, ok, detail in run(con, args.sample, args.raw):
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {detail}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
