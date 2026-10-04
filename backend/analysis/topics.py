"""Activity cues per topic: what are labels doing in their new text, and where?

Reads the lexicon in config/lexicon.toml and records every cue hit in non-inherited text (carried-forward and
restored lines never count: they are not new writing). A hit is a cue, never a verdict. Topics are the source's own
stream attributes (the wiki's `page_family`, stored in stream_meta), shown with the source's stated confidence; they
are secondary evidence, not our classification.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import duckdb
import polars as pl

TOPICS_VERSION = "topics-0.1"
LEXICON_PATH = Path(__file__).resolve().parents[2] / "config" / "lexicon.toml"
URL_RE = re.compile(r"https?://\S+")
NOVEL_CLASSES = ("new", "modified", "first_observed")
FLUSH_ROWS = 200_000


def load_lexicon(path: Path | None = None) -> dict:
    return tomllib.loads((path or LEXICON_PATH).read_text(encoding="utf-8"))


def _term_regex(term: str) -> str:
    wild = term.endswith("*")
    body = re.escape(term[:-1] if wild else term).replace(r"\ ", r"\s+")
    return body + (r"\w*" if wild else "")


def compile_lexicon(lex: dict) -> list[tuple[str, re.Pattern]]:
    out = []
    for name, spec in lex["categories"].items():
        terms = sorted(spec["terms"], key=len, reverse=True)
        pattern = r"(?<!\w)(?:" + "|".join(_term_regex(t) for t in terms) + r")(?!\w)"
        out.append((name, re.compile(pattern, re.IGNORECASE)))
    return out


def find_cues(line: str, compiled: list[tuple[str, re.Pattern]]) -> list[tuple[str, str, int, int]]:
    """(category, matched term lower-cased, start, end) for one line; URLs are masked so they never match."""
    masked = URL_RE.sub(lambda m: " " * len(m.group(0)), line)
    hits = []
    for name, rx in compiled:
        for m in rx.finditer(masked):
            hits.append((name, re.sub(r"\s+", " ", m.group(0).lower()), m.start(), m.end()))
    return hits


def build(con: duckdb.DuckDBPyConnection, lexicon_path: Path | None = None) -> dict:
    lex = load_lexicon(lexicon_path)
    compiled = compile_lexicon(lex)
    version = f"{TOPICS_VERSION}/{lex['meta']['version']}"
    con.execute("DELETE FROM cue_hit")
    reader = con.cursor()
    reader.execute(
        """
        SELECT i.item_id, i.stream_key IS NOT NULL AS in_stream, i.text, tc.lines
        FROM text_item i
        LEFT JOIN (SELECT item_id, list(line_no) AS lines FROM text_change
                   WHERE classification IN ('new', 'modified', 'first_observed') GROUP BY item_id) tc USING (item_id)
        WHERE NOT i.generated
        """
    )
    rows: list[tuple] = []
    totals = {"items": 0, "hits": 0}
    by_cat: dict[str, int] = {}

    def flush() -> None:
        if rows:
            df = pl.DataFrame(rows, schema=["item_id", "line_no", "category", "term", "span_start", "span_end",
                                            "detector_version"], orient="row", infer_schema_length=None)
            con.register("cue_df", df)
            con.execute("INSERT INTO cue_hit SELECT * FROM cue_df")
            con.unregister("cue_df")
            rows.clear()

    while batch := reader.fetchmany(300):
        for item_id, in_stream, text, novel_lines in batch:
            totals["items"] += 1
            novel = set(novel_lines or [])
            offset = 0
            for n, line in enumerate(text.split("\n")):
                start = offset
                offset += len(line) + 1
                if in_stream and n not in novel:
                    continue  # inherited or restored: not new writing
                if len(line) < 3:
                    continue
                for cat, term, s, e in find_cues(line, compiled):
                    rows.append((item_id, n, cat, term, start + s, start + e, version))
                    by_cat[cat] = by_cat.get(cat, 0) + 1
                    totals["hits"] += 1
        if len(rows) >= FLUSH_ROWS:
            flush()
    flush()
    return {**totals, **{f"cat:{k}": v for k, v in sorted(by_cat.items())}}


# ---- summaries used by the app, report and questions ----

def topic_expr() -> str:
    """SQL that gives an item's topic: the source's page_family if it has one, else 'unclassified'."""
    return ("coalesce((SELECT value FROM stream_meta m WHERE m.stream_key = t.stream_key AND m.key = 'page_family'), "
            "'unclassified')")


def matrix(con: duckdb.DuckDBPyConnection, top_topics: int = 20) -> dict:
    """Topic x category: distinct revisions (items) with at least one cue, distinct labels, and cue hits."""
    rows = con.execute(
        f"""
        SELECT {topic_expr()} AS topic, h.category, count(DISTINCT h.item_id) AS items,
               count(DISTINCT t.actor_label_id) AS labels, count(*) AS hits
        FROM cue_hit h JOIN text_item t USING (item_id) GROUP BY ALL
        """
    ).fetchall()
    volume = dict(con.execute(
        f"SELECT {topic_expr()} AS topic, count(DISTINCT t.item_id) FROM text_item t WHERE NOT t.generated GROUP BY 1"
    ).fetchall())
    cats = [r[0] for r in con.execute("SELECT DISTINCT category FROM cue_hit ORDER BY 1").fetchall()]
    topics = sorted({r[0] for r in rows}, key=lambda t: -sum(r[2] for r in rows if r[0] == t))[:top_topics]
    cell = {(r[0], r[1]): {"items": r[2], "labels": r[3], "hits": r[4]} for r in rows}
    return {
        "categories": cats,
        "topics": [{"topic": t, "items_total": volume.get(t, 0),
                    "cells": {c: cell.get((t, c), {"items": 0, "labels": 0, "hits": 0}) for c in cats}} for t in topics],
    }


def examples(con: duckdb.DuckDBPyConnection, topic: str, category: str, limit: int = 12) -> list[dict]:
    rows = con.execute(
        f"""
        SELECT h.item_id, coalesce(l.display_name, '(unknown author)'), t.time_ts, h.term, h.span_start, h.span_end,
               t.text
        FROM cue_hit h JOIN text_item t USING (item_id) LEFT JOIN actor_label l ON l.label_id = t.actor_label_id
        WHERE h.category = ? AND {topic_expr()} = ?
        QUALIFY row_number() OVER (PARTITION BY h.item_id ORDER BY h.span_start) = 1
        ORDER BY md5(h.item_id || ?) LIMIT ?
        """,
        [category, topic, category, limit],
    ).fetchall()
    out = []
    for item_id, label, ts, term, s, e, text in rows:
        a, b = max(s - 100, 0), min(e + 140, len(text))
        out.append({"item_id": item_id, "label": label, "time": str(ts) if ts else None, "term": term,
                    "snippet": {"before": text[a:s], "match": text[s:e], "after": text[e:b]}})
    return out


def timeline(con: duckdb.DuckDBPyConnection, bucket: str = "week") -> dict:
    """Revisions with a cue per time bucket and category (recorded time; not established action order)."""
    rows = con.execute(
        f"""
        SELECT date_trunc('{bucket}', t.time_ts) AS b, h.category, count(DISTINCT h.item_id)
        FROM cue_hit h JOIN text_item t USING (item_id) WHERE t.time_ts IS NOT NULL GROUP BY ALL ORDER BY 1
        """
    ).fetchall()
    return {"bucket": bucket, "points": [{"t": str(b), "category": c, "items": n} for b, c, n in rows]}
