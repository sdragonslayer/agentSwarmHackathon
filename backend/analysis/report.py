"""Static HTML results report (no build step): inflation figures plus inspectable cases.

    uv run python -m backend.analysis.report --db data/derived/swarm.duckdb --out data/derived/report.html

The page is self-contained (inline CSS/JS/SVG). It embeds corpus text, so it lives under data/derived/ (ignored
by git) and is subject to the same data-rights limits as the corpus. All corpus strings reach the DOM through
textContent only; the JSON payload is escaped so it cannot close the script tag.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from backend.analysis import inflation, questions
from backend.db import DEFAULT_DB, connect

REPORT_VERSION = "report-0.1"
MAX_CASES = 12
MAX_APPEARANCES = 80
CONTEXT = 90


def _snippet(text: str, start: int, end: int) -> dict:
    a, b = max(start - CONTEXT, 0), min(end + CONTEXT, len(text))
    return {"before": text[a:start], "match": text[start:end], "after": text[end:b]}


def pick_cases(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    """Inspectable handoff candidates first, then one carryover example. Returns (artifact_id, case_kind)."""
    handoff = con.execute(
        f"""
        SELECT c.artifact_id FROM artifact_counts c JOIN artifact a USING (artifact_id)
        JOIN (SELECT artifact_id, count(*) AS n FROM evidence_edge GROUP BY 1) e USING (artifact_id)
        WHERE a.artifact_type IN ('url', 'repo_ref') AND c.novel_labels BETWEEN 2 AND 8 AND c.novel_items <= 60
        ORDER BY c.novel_labels DESC, e.n DESC, c.novel_items DESC LIMIT {MAX_CASES - 1}
        """
    ).fetchall()
    carry = con.execute(
        """
        SELECT artifact_id FROM artifact_counts c JOIN artifact a USING (artifact_id)
        WHERE a.artifact_type IN ('url', 'repo_ref') AND c.novel_occurrences >= 1 AND c.full_occurrences >= 50
        ORDER BY c.full_occurrences * 1.0 / c.novel_occurrences DESC LIMIT 1
        """
    ).fetchall()
    out = [(r[0], "handoff-candidate") for r in handoff]
    out += [(r[0], "carryover") for r in carry if r[0] not in {a for a, _ in out}]
    return out


def case_payload(con: duckdb.DuckDBPyConnection, artifact_id: str, case_kind: str) -> dict:
    atype, raw = con.execute("SELECT artifact_type, raw FROM artifact WHERE artifact_id = ?", [artifact_id]).fetchone()
    counts = con.execute(
        "SELECT full_occurrences, novel_occurrences, full_items, novel_items, full_labels, novel_labels "
        "FROM artifact_counts WHERE artifact_id = ?",
        [artifact_id],
    ).fetchone()
    rows = con.execute(
        """
        SELECT a.item_id, coalesce(l.display_name, a.actor_label_id, 'unknown author label') AS label,
               a.actor_label_id, t.kind, a.time_ts, a.novelty, a.span_start, a.span_end, t.text, e.event_index
        FROM appearance a JOIN text_item t USING (item_id)
        LEFT JOIN actor_label l ON l.label_id = a.actor_label_id LEFT JOIN event e ON e.event_id = a.event_id
        WHERE a.artifact_id = ?
        ORDER BY a.time_ts NULLS LAST, e.event_index NULLS LAST, a.item_id LIMIT ?
        """,
        [artifact_id, MAX_APPEARANCES],
    ).fetchall()
    apps = [
        {
            "item_id": i, "label": label, "label_id": lid, "kind": kind, "time": str(ts) if ts else None,
            "novelty": nov, "event_index": idx, "snippet": _snippet(text, s, e),
        }
        for i, label, lid, kind, ts, nov, s, e, text, idx in rows
    ]
    keep = {a["item_id"] for a in apps}
    edges = [
        {"src": s, "dst": d, "relation": r, "tier": tier, "temporal": tmp}
        for s, d, r, tier, tmp in con.execute(
            "SELECT src_item_id, dst_item_id, relation, evidence_tier, temporal_status FROM evidence_edge "
            "WHERE artifact_id = ?",
            [artifact_id],
        ).fetchall()
        if s in keep and d in keep
    ]
    answers = [
        {k: a[k] for k in ("id", "question", "claim", "status", "limitations")}
        for a in questions.answer_all(con, artifact_id)
    ]
    return {
        "artifact_id": artifact_id, "type": atype, "raw": raw, "case_kind": case_kind,
        "counts": dict(zip(["full_occurrences", "novel_occurrences", "full_items", "novel_items", "full_labels",
                            "novel_labels"], counts, strict=True)),
        "appearances": apps, "edges": edges, "answers": answers,
    }


def build_payload(con: duckdb.DuckDBPyConnection) -> dict:
    snap = con.execute("SELECT snapshot_id, source, retrieved_at, importer_version FROM snapshot").fetchone()
    scope = {
        t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("event", "text_item", "actor_label", "artifact", "appearance", "evidence_edge")
    }
    return {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot": dict(zip(["snapshot_id", "source", "retrieved_at", "importer_version"], snap, strict=True)),
        "scope": scope,
        "inflation": inflation.headline(con, top=12),
        "cases": [case_payload(con, a, k) for a, k in pick_cases(con)],
    }


def render(payload: dict) -> str:
    # Every "<" becomes <, so corpus text can never form a tag or an HTML comment inside the script block.
    data = json.dumps(payload, default=str).replace("<", "\\u003c")
    data = data.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return TEMPLATE.replace("/*__DATA__*/null", data)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=Path("data/derived/report.html"))
    args = ap.parse_args()
    con = connect(args.db)
    html = render(build_payload(con))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"wrote {args.out} ({len(html) / 1e6:.1f} MB)")


TEMPLATE = (Path(__file__).parent / "report_template.html").read_text(encoding="utf-8")

if __name__ == "__main__":
    main()
