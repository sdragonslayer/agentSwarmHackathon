"""Export the results tables (CSV + one JSON) for the writeup, plus the demo case ids.

    uv run python -m backend.analysis.export_results --db data/derived/swarm.duckdb --out data/derived/results

Everything here is aggregate or an artifact string; no free text from the corpus beyond artifact strings.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import duckdb

from backend.analysis import inflation
from backend.db import DEFAULT_DB, connect

# Demo cases chosen by hand from the real data (see docs/DEMO.md): artifact strings, resolved to ids at run time.
DEMO_CASES_BY_SOURCE = {
    "aivillage": {
        "docs_link_typo": "https://docs.google.com/document/d/1y5GGAIthIP_N-4D5nxO-caPYTi7OrL-edit",
        "chronicle_pr3": "https://github.com/ai-village-agents/village-chronicle/pull/3",
        "chronicle_commit": "https://github.com/ai-village-agents/village-chronicle/commit/4078515",
        "carryover": "https://animal-welfare-site-64148b.gitlab.io/guides.html",
        "shared_resource": "https://github.com/ai-village-agents/basecamp",
    },
    "wiki": {
        "proxy_workaround": "https://www.proxymule.com/__PROXY__/https/www.sec.gov/files/county.json",
        "direct_variant_list": "https://www.sec.gov/files/county.json?a=.txt",
        "carryover": ("https://jqp.vercel.app/api/v0?jq=%7Bmethod%3A.regCF_county_methodology%2Cdata%3A%5B."
                      "regCF_county_2019%5B%5D%7C"),
    },
}
DEMO_CASES: dict[str, str] | None = None  # tests may override; otherwise chosen by the database's source


def _write_csv(path: Path, header: list[str], rows: list[tuple]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def export(con: duckdb.DuckDBPyConnection, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    inf = inflation.headline(con, top=50)
    _write_csv(out / "lines_by_stream.csv",
               ["stream", "items", "lines", "inherited_lines", "novel_lines", "restored_lines", "inherited_share"],
               [(r["stream"], r["items"], r["lines"], r["inherited_lines"], r["novel_lines"], r["restored_lines"],
                 r["inherited_share"]) for r in inf["line_level_by_stream"]])
    _write_csv(out / "inflation_by_artifact_type.csv",
               ["artifact_type", "distinct_artifacts", "full_occurrences", "novel_occurrences", "inflation",
                "in_2plus_items_full", "in_2plus_items_novel", "in_2plus_labels_full", "in_2plus_labels_novel"],
               [(t["artifact_type"], t["artifacts"], t["full_occurrences"], t["novel_occurrences"],
                 t["occurrence_inflation"], t["artifacts_in_2plus_items"]["full"], t["artifacts_in_2plus_items"]["novel"],
                 t["artifacts_in_2plus_labels"]["full"], t["artifacts_in_2plus_labels"]["novel"])
                for t in inf["artifact_level_by_type"]])
    _write_csv(out / "most_inflated_artifacts.csv",
               ["artifact_id", "type", "artifact", "full_occurrences", "novel_occurrences", "full_items", "novel_items",
                "full_labels", "novel_labels"],
               [(a["artifact_id"], a["type"], a["raw"], a["full_occurrences"], a["novel_occurrences"], a["full_items"],
                 a["novel_items"], a["full_labels"], a["novel_labels"]) for a in inf["most_inflated_artifacts"]])
    edges = con.execute(
        "SELECT e.relation, a.artifact_type, e.temporal_status, e.evidence_tier, count(*) FROM evidence_edge e "
        "JOIN artifact a USING (artifact_id) GROUP BY ALL ORDER BY 5 DESC"
    ).fetchall()
    _write_csv(out / "edges_summary.csv", ["relation", "artifact_type", "temporal_status", "evidence_tier", "edges"], edges)
    labels = con.execute(
        """
        SELECT coalesce(l.display_name, a.actor_label_id) AS label, l.kind, l.model_string,
               count(*) FILTER (WHERE a.novelty <> 'restored') AS novel_appearances,
               count(DISTINCT a.artifact_id) AS distinct_artifacts
        FROM appearance a LEFT JOIN actor_label l ON l.label_id = a.actor_label_id
        GROUP BY ALL ORDER BY 4 DESC LIMIT 60
        """
    ).fetchall()
    _write_csv(out / "author_labels_by_artifact_activity.csv",
               ["author_label", "kind", "model_string", "novel_appearances", "distinct_artifacts"], labels)
    kinds = con.execute(
        "SELECT t.kind, a.novelty, count(*) FROM appearance a JOIN text_item t USING (item_id) GROUP BY ALL "
        "ORDER BY 3 DESC"
    ).fetchall()
    _write_csv(out / "appearances_by_kind_and_novelty.csv", ["text_kind", "novelty", "appearances"], kinds)
    demo = {}
    source = con.execute("SELECT source FROM snapshot LIMIT 1").fetchone()[0]
    for name, raw in (DEMO_CASES if DEMO_CASES is not None else DEMO_CASES_BY_SOURCE.get(source, {})).items():
        row = con.execute(
            "SELECT a.artifact_id, c.full_occurrences, c.novel_occurrences, c.novel_items, c.novel_labels "
            "FROM artifact a JOIN artifact_counts c USING (artifact_id) WHERE a.artifact_type = 'url' "
            "AND a.raw LIKE ? || '%'",
            [raw[:90]],
        ).fetchone()
        demo[name] = ({"artifact_id": row[0], "artifact": raw, "full_occurrences": row[1], "novel_occurrences": row[2],
                       "novel_items": row[3], "novel_labels": row[4]} if row else {"artifact": raw, "missing": True})
    summary = {
        "scope": {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("event", "text_item", "actor_label", "artifact", "appearance", "evidence_edge")},
        "inflation": {k: inf[k] for k in ("line_level_by_stream", "artifact_level_by_type")},
        "demo_cases": demo,
    }
    (out / "results.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=Path("data/derived/results"))
    args = ap.parse_args()
    s = export(connect(args.db), args.out)
    print(f"wrote results to {args.out}")
    for k, v in s["demo_cases"].items():
        print(f"  {k:18} {v.get('artifact_id', 'MISSING')}")


if __name__ == "__main__":
    main()
