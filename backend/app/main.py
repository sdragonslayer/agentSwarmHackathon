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
from pydantic import BaseModel

from backend.analysis import export_case, questions
from backend.db import DEFAULT_DB, connect

MAX_GRAPH_NODES = 100


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
        item["text"] = item["text"][:20000]
        ls = con.execute(
            "SELECT lineage_status, base_item_id, n_lines, n_inherited, n_new, n_modified, n_restored, "
            "n_first_observed FROM lineage_summary WHERE item_id = ?", [item_id]).fetchone()
        item["lineage"] = dict(zip(["status", "base_item_id", "n_lines", "n_inherited", "n_new", "n_modified",
                                    "n_restored", "n_first_observed"], ls, strict=True)) if ls else None
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

    return app


app = create_app()
