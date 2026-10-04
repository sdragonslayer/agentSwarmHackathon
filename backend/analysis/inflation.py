"""Occurrence inflation: how much counting carried-forward text overstates how often things appear.

Reported as occurrence inflation (full-text occurrences vs occurrences in non-inherited text), never as an
estimate of false transmission. Every figure keeps its denominator and scope.
"""

from __future__ import annotations

import duckdb

from backend.display import stream_label


def headline(con: duckdb.DuckDBPyConnection, top: int = 15) -> dict:
    lines = con.execute(
        """
        SELECT split_part(stream_key, ':', 1) AS stream, count(*) AS items, sum(n_lines) AS lines,
               sum(n_inherited) AS inherited,
               sum(n_new + n_modified + n_first_observed) AS novel, sum(n_restored) AS restored
        FROM lineage_summary GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    by_stream = [
        {
            "stream": s, "label": stream_label(s), "items": i, "lines": int(ln), "inherited_lines": int(inh), "novel_lines": int(nov),
            "restored_lines": int(res), "inherited_share": round(inh / ln, 4) if ln else None,
        }
        for s, i, ln, inh, nov, res in lines
    ]
    per_type = con.execute(
        """
        SELECT a.artifact_type, count(*) AS artifacts, sum(c.full_occurrences) AS full_occ,
               sum(c.novel_occurrences) AS novel_occ,
               count(*) FILTER (WHERE c.full_items >= 2) AS multi_item_full,
               count(*) FILTER (WHERE c.novel_items >= 2) AS multi_item_novel,
               count(*) FILTER (WHERE c.full_labels >= 2) AS multi_label_full,
               count(*) FILTER (WHERE c.novel_labels >= 2) AS multi_label_novel
        FROM artifact_counts c JOIN artifact a USING (artifact_id) GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    types = [
        {
            "artifact_type": t, "artifacts": n, "full_occurrences": int(f), "novel_occurrences": int(nv),
            "occurrence_inflation": round(f / nv, 3) if nv else None,
            "artifacts_in_2plus_items": {"full": mf, "novel": mn},
            "artifacts_in_2plus_labels": {"full": lf, "novel": ln},
        }
        for t, n, f, nv, mf, mn, lf, ln in per_type
    ]
    top_rows = con.execute(
        """
        SELECT c.artifact_id, a.artifact_type, a.raw, c.full_occurrences, c.novel_occurrences, c.full_items,
               c.novel_items, c.full_labels, c.novel_labels
        FROM artifact_counts c JOIN artifact a USING (artifact_id)
        WHERE c.novel_occurrences >= 1 AND c.full_occurrences >= 20
        ORDER BY c.full_occurrences * 1.0 / c.novel_occurrences DESC, c.full_occurrences DESC LIMIT ?
        """,
        [top],
    ).fetchall()
    cols = ["artifact_id", "type", "raw", "full_occurrences", "novel_occurrences", "full_items", "novel_items",
            "full_labels", "novel_labels"]
    return {
        "scope": "all loaded text items except LLM-generated summaries",
        "line_level_by_stream": by_stream,
        "artifact_level_by_type": types,
        "most_inflated_artifacts": [dict(zip(cols, r, strict=True)) for r in top_rows],
    }
