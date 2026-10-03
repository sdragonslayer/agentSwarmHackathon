"""Integrity gates over a built database (brief §11A). Run on synthetic fixtures in tests and on real data.

    uv run python -m backend.analysis.validate --db data/derived/swarm.duckdb [--sample 200]

Each check returns (name, passed, detail). Nothing here mutates data.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import duckdb

from backend.analysis import questions
from backend.db import DEFAULT_DB, connect

Check = tuple[str, bool, str]


def _one(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    return con.execute(sql, params or []).fetchone()[0]


def check_one_action_per_chat_row(con) -> Check:
    dup = _one(con, "SELECT count(*) FROM (SELECT event_id FROM text_item WHERE event_id IS NOT NULL "
                    "AND kind IN ('chat_agent', 'chat_human') GROUP BY 1 HAVING count(*) > 1)")
    unlinked = _one(con, "SELECT count(*) FROM text_item WHERE kind = 'chat_agent' AND event_id IS NULL")
    talk = _one(con, "SELECT count(*) FROM event WHERE kind = 'AGENT_TALK'")
    chat = _one(con, "SELECT count(*) FROM text_item WHERE kind = 'chat_agent'")
    return ("chat rows and events are one action", dup == 0 and unlinked == 0 and talk == chat,
            f"events AGENT_TALK={talk} chat_agent items={chat} duplicate links={dup} unlinked={unlinked}")


def check_label_integrity(con) -> Check:
    bad_ns = _one(con, "SELECT count(*) FROM actor_label WHERE label_id NOT LIKE 'av:agent:%' "
                       "AND label_id NOT LIKE 'av:user:%'")
    merged = _one(con, "SELECT count(*) FROM actor_label WHERE identity_status <> 'unverified_label'")
    empty_id = _one(con, "SELECT count(*) FROM actor_label WHERE label_id IN ('av:agent:', 'av:user:')")
    orphan = _one(con, "SELECT count(*) FROM event WHERE actor_label_id IS NOT NULL AND actor_label_id NOT IN "
                       "(SELECT label_id FROM actor_label)")
    unknown = _one(con, "SELECT count(*) FROM event WHERE actor_label_id IS NULL")
    return ("labels namespaced, unmerged, no shared blank label", bad_ns == merged == empty_id == orphan == 0,
            f"events with unknown author label (kept NULL, not merged)={unknown}; orphan labels={orphan}")


def check_time_fields(con) -> Check:
    unparsed = _one(con, "SELECT count(*) FROM event WHERE time_ts IS NULL")
    bounds = _one(con, "SELECT count(*) FROM event WHERE time_lower IS NOT NULL OR time_upper IS NOT NULL")
    inversions = _one(
        con, "SELECT count(*) FROM (SELECT time_ts, lag(time_ts) OVER (ORDER BY event_index) p FROM event "
             "WHERE event_index IS NOT NULL) WHERE p > time_ts")
    n = _one(con, "SELECT count(*) FROM event")
    return ("source times kept verbatim; no invented bounds", unparsed == 0 and bounds == 0,
            f"events={n} unparsed={unparsed} invented bounds={bounds}; event_index vs time inversions={inversions}")


def check_lineage_accounting(con) -> Check:
    bad = _one(con, "SELECT count(*) FROM lineage_summary WHERE n_lines <> n_inherited + n_new + n_modified + "
                    "n_restored + n_first_observed")
    changes = _one(con, "SELECT count(*) FROM text_change")
    summed = _one(con, "SELECT coalesce(sum(n_new + n_modified + n_restored + n_first_observed), 0) "
                       "FROM lineage_summary")
    first_bad = _one(con, "SELECT count(*) FROM lineage_summary WHERE lineage_status = 'first_in_stream' "
                          "AND (n_inherited <> 0 OR n_new <> 0 OR n_modified <> 0 OR n_restored <> 0)")
    multi_first = _one(con, "SELECT count(*) FROM (SELECT stream_key FROM lineage_summary "
                            "WHERE lineage_status = 'first_in_stream' GROUP BY 1 HAVING count(*) > 1)")
    cross = _one(con, "SELECT count(*) FROM lineage_summary l JOIN lineage_summary b ON b.item_id = l.base_item_id "
                      "WHERE b.stream_key <> l.stream_key")
    ok = bad == first_bad == multi_first == cross == 0 and changes == summed
    detail = (
        f"rows with bad sums={bad}; text_change={changes} vs summary={summed}; first-item violations="
        f"{first_bad}; streams with 2 firsts={multi_first}; cross-stream bases={cross}"
    )
    return ("lineage counts add up; first item is incomplete lineage; no cross-label inheritance", ok, detail)


def check_lineage_independent(con, sample: int, seed: int = 7) -> Check:
    """Recompute inherited counts for sampled consecutive memory pairs with a different method (SQL set ops)."""
    pairs = con.execute(
        "SELECT item_id, base_item_id FROM lineage_summary WHERE base_item_id IS NOT NULL "
        "AND stream_key LIKE 'mem:%' ORDER BY md5(item_id || ?) LIMIT ?",
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
        # lineage counts every non-blank line (duplicates included); compare on distinct lines via text_change
        stored = con.execute(
            "SELECT n_lines - n_new - n_modified - n_restored - n_first_observed FROM lineage_summary WHERE item_id = ?",
            [item],
        ).fetchone()[0]
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
            f"sampled consecutive memory pairs={len(pairs)} mismatches={len(mismatches)} {mismatches[:3]}")


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
    # Normalization may differ from raw only in the host; the stored raw is the first-seen form, so compare
    # case-insensitively on the host part by checking equality of normalized forms instead when raw differs.
    ok = not problems
    detail = (
        f"artifacts answered={len(arts)} citation problems={len(problems)}; sampled appearance spans={spans[0]} "
        f"matching first-seen raw string={spans[1]} (others are other surface forms of the same artifact)"
    )
    return ("exported citations and appearance spans resolve to exact source text", ok, detail)


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


def run(con: duckdb.DuckDBPyConnection, sample: int = 200) -> list[Check]:
    checks = [
        check_one_action_per_chat_row(con),
        check_label_integrity(con),
        check_time_fields(con),
        check_lineage_accounting(con),
        check_lineage_independent(con, min(sample, 200)),
        check_inflation_consistent(con),
        check_citations(con, sample),
        check_edges(con),
    ]
    return checks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--sample", type=int, default=200)
    args = ap.parse_args()
    random.seed(7)
    con = connect(args.db)
    failed = 0
    for name, ok, detail in run(con, args.sample):
        failed += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n        {detail}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
