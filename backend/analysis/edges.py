"""Evidence edges between items that contain the same exact artifact.

`same_content` means only that the exact artifact string appears in both items' non-inherited text. It does not
establish direction, copying, or that the two labels are different agents. Endpoints are ordered by *recorded*
order (src first), but `directed` stays FALSE and `temporal_status` says how strong that order is:

- sequence_ordered: both items come from events with different event_index values (the source's own sequence)
- timestamp_ordered_unbounded: recorded timestamps differ, but the source gives no clock uncertainty, so
  wall-clock order is not established
- unresolved: equal or missing timestamps and no shared sequence

Artifacts that appear in very many items are treated as widely repeated strings and get no edges.
"""

from __future__ import annotations

import duckdb

EDGE_VERSION = "edges-0.1"
MAX_ITEMS_PER_ARTIFACT = 200
EDGE_TYPES = ("url", "repo_ref", "hex_id")

ALTERNATIVES = [
    "common external source (both read the same page or message)",
    "shared prompt, scaffold or template text",
    "independent discovery of the same resource",
    "text carried in a memory or goal handed to the later label",
]


def build(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    con.execute("DELETE FROM evidence_edge")
    con.execute("DROP TABLE IF EXISTS _novel_first")
    con.execute(
        f"""
        CREATE TEMP TABLE _novel_first AS
        WITH eligible AS (
            SELECT c.artifact_id FROM artifact_counts c JOIN artifact a USING (artifact_id)
            WHERE a.artifact_type IN {EDGE_TYPES!r}
              AND c.novel_items BETWEEN 2 AND {MAX_ITEMS_PER_ARTIFACT}
        ),
        per_item AS (
            SELECT a.artifact_id, a.item_id, a.actor_label_id, a.time_ts, e.event_index,
                   a.span_start, a.span_end, a.line_no,
                   row_number() OVER (PARTITION BY a.artifact_id, a.item_id ORDER BY a.span_start) AS rn
            FROM appearance a JOIN eligible USING (artifact_id) LEFT JOIN event e ON e.event_id = a.event_id
            WHERE a.novelty IN ('standalone', 'first_observed', 'new', 'modified')
        )
        SELECT artifact_id, item_id, actor_label_id, time_ts, event_index, span_start, span_end, line_no,
               row_number() OVER (PARTITION BY artifact_id
                                  ORDER BY time_ts NULLS LAST, event_index NULLS LAST, item_id) AS pos
        FROM per_item WHERE rn = 1
        """
    )
    con.execute(
        f"""
        INSERT INTO evidence_edge
        SELECT
            'edge:' || md5(f.item_id || '|' || t.item_id || '|' || f.artifact_id || '|same_content'),
            f.item_id, t.item_id, 'same_content', 'rule_derived', f.artifact_id,
            json_object('artifact_id', f.artifact_id,
                        'src', json_object('item_id', f.item_id, 'span_start', f.span_start, 'span_end', f.span_end),
                        'dst', json_object('item_id', t.item_id, 'span_start', t.span_start, 'span_end', t.span_end)),
            CASE
                WHEN f.event_index IS NOT NULL AND t.event_index IS NOT NULL AND f.event_index <> t.event_index
                    THEN 'sequence_ordered'
                WHEN f.time_ts IS NOT NULL AND t.time_ts IS NOT NULL AND f.time_ts <> t.time_ts
                    THEN 'timestamp_ordered_unbounded'
                ELSE 'unresolved'
            END,
            '{_alt_json()}'::JSON, FALSE, '{EDGE_VERSION}'
        FROM _novel_first f
        JOIN _novel_first t ON t.artifact_id = f.artifact_id AND t.pos > 1 AND f.pos = 1
        WHERE f.actor_label_id IS NOT NULL AND t.actor_label_id IS NOT NULL
          AND f.actor_label_id <> t.actor_label_id
        """
    )
    n_edges = con.execute("SELECT count(*) FROM evidence_edge").fetchone()[0]
    omitted = con.execute(
        f"SELECT count(*) FROM artifact_counts WHERE novel_items > {MAX_ITEMS_PER_ARTIFACT}"
    ).fetchone()[0]
    by_status = dict(con.execute("SELECT temporal_status, count(*) FROM evidence_edge GROUP BY 1").fetchall())
    return {"edges": n_edges, "widely_repeated_artifacts_skipped": omitted, **by_status}


def _alt_json() -> str:
    import json

    return json.dumps(ALTERNATIVES).replace("'", "''")
