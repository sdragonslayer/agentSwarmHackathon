"""Small read-mostly query API. Corpus text is returned as JSON strings only; nothing is fetched or executed.

    uv run uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.analysis import export_case, inflation, questions, report, topics, traces
from backend.db import DEFAULT_DB, connect
from backend.display import source_label

MAX_GRAPH_NODES = 100
MAX_ITEM_LINES = 600
STATIC = Path(__file__).parent / "static"


class ReviewIn(BaseModel):
    edge_id: str
    decision: Literal["accept", "reject", "uncertain"]
    rationale: str = ""
    reviewer: str = "local"


def create_app(db_path: str | Path | None = None) -> FastAPI:
    path = Path(db_path or os.environ.get("SWARMSCOPE_DB", DEFAULT_DB))
    app = FastAPI(title="SwarmScope", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])

    base: dict[str, duckdb.DuckDBPyConnection] = {}

    def db() -> duckdb.DuckDBPyConnection:
        """One shared connection (DuckDB forbids mixed modes per file); a cursor per request. Only /reviews writes."""
        if "con" not in base:
            base["con"] = connect(path)
        return base["con"].cursor()

    @app.get("/datasets")
    def datasets():
        con = db()
        snaps = con.execute("SELECT snapshot_id, source, retrieved_at, importer_version, files, terms, coverage_notes "
                            "FROM snapshot").fetchall()
        counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("event", "text_item", "actor_label", "artifact", "appearance", "evidence_edge")}
        return {
            "snapshots": [dict(zip(["snapshot_id", "source", "retrieved_at", "importer_version", "files", "terms",
                                    "coverage_notes"], s, strict=True)) for s in snaps],
            "counts": counts,
            "label_note": "Counts are author labels, not verified agents.",
        }

    @app.get("/search")
    def search(q: str = Query(min_length=2, max_length=200), kind: str | None = None, limit: int = Query(20, le=100),
               offset: int = 0):
        con = db()
        pat = f"%{q.replace('%', '').replace('_', '')}%"
        arts = con.execute(
            "SELECT a.artifact_id, a.artifact_type, a.raw, c.full_occurrences, c.novel_occurrences, c.novel_items, "
            "c.novel_labels FROM artifact a JOIN artifact_counts c USING (artifact_id) WHERE a.raw ILIKE ? "
            "ORDER BY c.novel_items DESC LIMIT ?",
            [pat, limit],
        ).fetchall()
        # Memories are huge and mostly carryover, so text search skips them unless asked for explicitly.
        kind_sql, params = ("t.kind = ?", [kind]) if kind else ("t.kind <> 'memory'", [])
        items = con.execute(
            f"SELECT t.item_id, t.kind, t.actor_label_id, t.time_ts, strpos(lower(t.text), lower(?)) - 1 AS pos, "
            f"substr(t.text, greatest(strpos(lower(t.text), lower(?)) - 60, 1), 200) AS snippet "
            f"FROM text_item t WHERE {kind_sql} AND t.text ILIKE ? AND NOT t.generated "
            f"ORDER BY t.time_ts LIMIT ? OFFSET ?",
            [q, q, *params, pat, limit, offset],
        ).fetchall()
        return {
            "artifacts": [dict(zip(["artifact_id", "type", "raw", "full_occurrences", "novel_occurrences",
                                    "novel_items", "novel_labels"], r, strict=True)) for r in arts],
            "items": [dict(zip(["item_id", "kind", "actor_label_id", "time", "match_pos", "snippet"], r, strict=True))
                      for r in items],
            "order_note": "Items are sorted by recorded time, which is not established action order.",
        }

    @app.get("/search/timeline")
    def search_timeline(q: str = Query(min_length=2, max_length=200), kind: str | None = None,
                        limit: int = Query(150, le=300)):
        """Every text hit for a phrase, by author label over time. No links are inferred from a phrase match."""
        con = db()
        needle = q.replace("%", "").replace("_", "")
        kind_sql, params = ("t.kind = ?", [kind]) if kind else ("t.kind <> 'memory'", [])
        where = f"{kind_sql} AND NOT t.generated AND t.text ILIKE ?"
        total = con.execute(f"SELECT count(*) FROM text_item t WHERE {where}", [*params, f"%{needle}%"]).fetchone()[0]
        rows = con.execute(
            f"SELECT t.item_id, coalesce(l.display_name, t.actor_label_id, 'unknown author label'), t.actor_label_id, "
            f"t.kind, t.time_ts, e.event_index, strpos(lower(t.text), lower(?)) AS pos, t.text "
            f"FROM text_item t LEFT JOIN actor_label l ON l.label_id = t.actor_label_id "
            f"LEFT JOIN event e ON e.event_id = t.event_id WHERE {where} ORDER BY t.time_ts NULLS LAST, t.item_id "
            f"LIMIT ?", [needle, *params, f"%{needle}%", limit]).fetchall()
        apps = []
        for item_id, label, lid, k, ts, idx, pos, text in rows:
            a = max(pos - 61, 0)
            apps.append({"item_id": item_id, "label": label, "label_id": lid, "kind": k, "time": str(ts) if ts else None,
                         "novelty": "standalone", "event_index": idx,
                         "snippet": {"before": text[a:pos - 1], "match": text[pos - 1:pos - 1 + len(needle)],
                                     "after": text[pos - 1 + len(needle):pos - 1 + len(needle) + 60]}})
        return {"query": q, "total": total, "shown": len(apps), "appearances": apps,
                "note": "A phrase match is not a reference or a link; no edges are drawn."}

    @app.get("/events/{item_id:path}")
    def get_item(item_id: str):
        con = db()
        row = con.execute(
            "SELECT t.item_id, t.kind, t.actor_label_id, l.display_name, t.event_id, t.room_id, t.source_time, "
            "t.text, t.source_file, t.source_table, t.source_id, t.generated FROM text_item t "
            "LEFT JOIN actor_label l ON l.label_id = t.actor_label_id WHERE t.item_id = ?",
            [item_id],
        ).fetchone()
        if row is None:
            raise HTTPException(404, "unknown item")
        cols = ["item_id", "kind", "actor_label_id", "author_label", "event_id", "room_id", "source_time", "text",
                "source_file", "source_table", "source_id", "generated"]
        item = dict(zip(cols, row, strict=True))
        full_text = item["text"]
        item["text"] = full_text[:20000]
        ls = con.execute(
            "SELECT lineage_status, base_item_id, n_lines, n_inherited, n_new, n_modified, n_restored, "
            "n_first_observed FROM lineage_summary WHERE item_id = ?", [item_id]).fetchone()
        item["lineage"] = dict(zip(["status", "base_item_id", "n_lines", "n_inherited", "n_new", "n_modified",
                                    "n_restored", "n_first_observed"], ls, strict=True)) if ls else None
        if ls:
            cls = dict(con.execute("SELECT line_no, classification FROM text_change WHERE item_id = ?",
                                   [item_id]).fetchall())
            raw_lines = full_text.split("\n")
            item["lines"] = [{"n": n, "text": t[:600], "cls": cls.get(n, "inherited") if t.strip() else "blank"}
                             for n, t in enumerate(raw_lines[:MAX_ITEM_LINES])]
            item["lines_truncated"] = len(raw_lines) > MAX_ITEM_LINES
        item["artifacts"] = [
            dict(zip(["artifact_id", "type", "raw", "novel_items", "novel_labels", "novelty"], r, strict=True))
            for r in con.execute(
                "SELECT a.artifact_id, x.artifact_type, x.raw, c.novel_items, c.novel_labels, min(a.novelty) "
                "FROM appearance a JOIN artifact x USING (artifact_id) JOIN artifact_counts c USING (artifact_id) "
                "WHERE a.item_id = ? GROUP BY a.artifact_id, x.artifact_type, x.raw, c.novel_items, c.novel_labels "
                "ORDER BY c.novel_labels DESC, c.novel_items DESC LIMIT 30", [item_id]).fetchall()]
        item["changes"] = [
            dict(zip(["line_no", "text", "classification", "similarity"], r, strict=True))
            for r in con.execute("SELECT line_no, text, classification, similarity FROM text_change "
                                 "WHERE item_id = ? ORDER BY line_no LIMIT 200", [item_id]).fetchall()]
        return item

    @app.get("/artifacts/{artifact_id}/appearances")
    def appearances(artifact_id: str, novel_only: bool = True, limit: int = Query(50, le=500), offset: int = 0):
        con = db()
        if not con.execute("SELECT 1 FROM artifact WHERE artifact_id = ?", [artifact_id]).fetchone():
            raise HTTPException(404, "unknown artifact")
        rows = questions._appearances(con, artifact_id, novel_only=novel_only)
        return {
            "total": len(rows), "items": rows[offset: offset + limit],
            "order_note": "Sorted by recorded time then source sequence; not established action order.",
        }

    @app.get("/cases/{artifact_id}/graph")
    def graph(artifact_id: str, include_candidates: bool = True):
        con = db()
        rels = "('same_content', 'possible_reuse')" if include_candidates else "('same_content')"
        edge_rows = con.execute(
            f"SELECT edge_id, src_item_id, dst_item_id, relation, evidence_tier, temporal_status, directed "
            f"FROM evidence_edge WHERE artifact_id = ? AND relation IN {rels} ORDER BY edge_id", [artifact_id]
        ).fetchall()
        node_ids = []
        for e in edge_rows:
            for n in (e[1], e[2]):
                if n not in node_ids:
                    node_ids.append(n)
        omitted = max(len(node_ids) - MAX_GRAPH_NODES, 0)
        node_ids = node_ids[:MAX_GRAPH_NODES]
        nodes = []
        for n in node_ids:
            r = con.execute("SELECT t.item_id, t.kind, t.actor_label_id, l.display_name, t.time_ts FROM text_item t "
                            "LEFT JOIN actor_label l ON l.label_id = t.actor_label_id WHERE t.item_id = ?",
                            [n]).fetchone()
            nodes.append(dict(zip(["item_id", "kind", "actor_label_id", "author_label", "time"], r, strict=True)))
        keep = set(node_ids)
        return {
            "nodes": nodes,
            "edges": [dict(zip(["edge_id", "src", "dst", "relation", "evidence_tier", "temporal_status", "directed"],
                               e, strict=True)) for e in edge_rows if e[1] in keep and e[2] in keep],
            "omitted_nodes": omitted,
            "legend_note": "Even an exact shared string does not prove causal influence.",
        }

    @app.get("/cases/{artifact_id}/questions")
    def case_questions(artifact_id: str):
        con = db()
        try:
            return {"answers": questions.answer_all(con, artifact_id)}
        except KeyError:
            raise HTTPException(404, "unknown artifact") from None

    @app.get("/cases/{artifact_id}/export")
    def case_export(artifact_id: str, format: Literal["markdown", "json"] = "markdown"):
        con = db()
        try:
            body = export_case.export(con, artifact_id, format)
        except KeyError:
            raise HTTPException(404, "unknown artifact") from None
        return {"format": format, "body": body}

    @app.post("/reviews")
    def post_review(r: ReviewIn):
        con = db()
        if not con.execute("SELECT 1 FROM evidence_edge WHERE edge_id = ?", [r.edge_id]).fetchone():
            raise HTTPException(404, "unknown edge")
        rid = f"rev:{uuid.uuid4()}"
        # Append-only: later decisions are new rows, earlier ones are never edited.
        con.execute("INSERT INTO review VALUES (?, ?, ?, ?, ?, ?)",
                    [rid, r.edge_id, r.decision, r.rationale, r.reviewer, datetime.now(UTC).isoformat()])
        return {"review_id": rid}

    cache: dict[str, list] = {}

    def cues_built(con) -> bool:
        return con.execute("SELECT count(*) FROM cue_hit").fetchone()[0] > 0


    @app.get("/topics/matrix")
    def topics_matrix():
        con = db()
        if not cues_built(con):
            return {"available": False, "note": "Run `backend.analysis.build --steps cues references` for this database."}
        return {"available": True, **topics.matrix(con, 16), "caveat": traces.caveat(con)}

    @app.get("/topics/examples")
    def topics_examples(topic: str, category: str, limit: int = Query(12, le=50)):
        return {"examples": topics.examples(db(), topic, category, limit)}

    @app.get("/traces/summary")
    def traces_summary():
        con = db()
        if not cues_built(con):
            return {"available": False}
        return {"available": True, "topics": traces.topic_summary(con)[:20], "answer_provenance": traces.answer_provenance(con),
                "category_adoption": traces.category_adoption(con), "caveat": traces.caveat(con),
                "arrival_burst": traces.arrival_burst(con)}

    @app.get("/traces/exchanges")
    def traces_exchanges(limit: int = Query(20, le=100)):
        con = db()
        return {"exchanges": traces.exchanges(con, limit) if cues_built(con) else [],
                "definition": "Label A names label B in a revision and B names A in a later revision within the window. "
                              "Mutual naming is a recorded sequence, not proof of a conversation."}

    @app.get("/traces/hosts")
    def traces_hosts(min_labels: int = Query(10, ge=2)):
        con = db()
        return {"hosts": traces.host_adoption(con, min_labels)[:40] if cues_built(con) else [],
                "definition": "Per web host: labels using it and how many other labels used it within 24 h of the first use. "
                              "A resource count, not a link between labels."}

    @app.get("/stats")
    def stats():
        con = db()
        counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("event", "text_item", "actor_label", "artifact", "appearance", "evidence_edge")}
        snap = con.execute("SELECT source, coverage_notes FROM snapshot").fetchone()
        generated = con.execute("SELECT count(*) FROM text_item WHERE generated").fetchone()[0]
        kinds = [r[0] for r in con.execute("SELECT DISTINCT kind FROM text_item ORDER BY 1").fetchall()]
        return {"scope": counts, "inflation": inflation.headline(con, top=12), "source_label": source_label(snap[0]),
                "coverage_notes": snap[1], "generated_items": generated, "text_kinds": kinds}

    @app.get("/cases")
    def list_cases():
        """Inspectable seed artifacts: shared across labels, plus one carryover example (see report.pick_cases)."""
        con = db()
        if "cases" not in cache:
            out = []
            for aid, kind in report.pick_cases(con):
                atype, raw = con.execute("SELECT artifact_type, raw FROM artifact WHERE artifact_id = ?",
                                         [aid]).fetchone()
                c = con.execute("SELECT full_occurrences, novel_occurrences, full_items, novel_items, full_labels, "
                                "novel_labels FROM artifact_counts WHERE artifact_id = ?", [aid]).fetchone()
                out.append({"artifact_id": aid, "type": atype, "raw": raw, "case_kind": kind,
                            "counts": dict(zip(["full_occurrences", "novel_occurrences", "full_items", "novel_items",
                                                "full_labels", "novel_labels"], c, strict=True))})
            cache["cases"] = out
        return {"cases": cache["cases"]}

    @app.get("/cases/{artifact_id}")
    def case_detail(artifact_id: str):
        con = db()
        if not con.execute("SELECT 1 FROM artifact WHERE artifact_id = ?", [artifact_id]).fetchone():
            raise HTTPException(404, "unknown artifact")
        return report.case_payload(con, artifact_id, "selected")

    @app.get("/cases/{artifact_id}/reviews")
    def case_reviews(artifact_id: str):
        con = db()
        rows = con.execute(
            "SELECT r.review_id, r.edge_id, r.decision, r.rationale, r.reviewer, r.created_at FROM review r "
            "JOIN evidence_edge e USING (edge_id) WHERE e.artifact_id = ? ORDER BY r.created_at", [artifact_id]
        ).fetchall()
        return {"reviews": [dict(zip(["review_id", "edge_id", "decision", "rationale", "reviewer", "created_at"], r,
                                     strict=True)) for r in rows]}

    @app.get("/", include_in_schema=False)
    @app.get("/app", include_in_schema=False)
    def frontend():
        return FileResponse(STATIC / "index.html", headers={
            "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                       "script-src 'self' 'unsafe-inline'; img-src 'self' data:"})

    return app


app = create_app()
