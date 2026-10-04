"""Explicit references between texts: wiki links, wiki URLs, and one label naming another.

These are *resolvable pointers* (brief §7C `references`): a span that names a page or an author label that exists in the
release. A reference shows that the writer knew of the target; it does not show they read it or acted on it. Only new
(non-inherited) text counts, and only exact names: page names and label names of at least MIN_NAME chars that look like
handles (a digit or two capitals), case-sensitive. Wiki links and wiki URLs resolve by exact page name.

An *exchange* is the minimal back-and-forth this data can show: label A names label B in a revision, and B names A in a
later revision within EXCHANGE_HOURS. It is a recorded sequence of mutual naming, not proof of a conversation.
"""

from __future__ import annotations

import re

import duckdb
import polars as pl

REFERENCES_VERSION = "references-0.1"
MIN_NAME = 8
EXCHANGE_HOURS = 24
URL_RE = re.compile(r"https?://\S+")
WIKILINK_RE = re.compile(r"\[\[([^\]|#\n]{2,80}?)(?:[|#][^\]\n]*)?\]\]")
WIKI_URL_RE = re.compile(r"wiki\.cgi\?[^\s\]\)]*?\bid=([A-Za-z0-9_%.\-]+)")
TOKEN_RE = re.compile(r"(?<![\w\-])[\w\-]{8,}(?![\w\-])")
FLUSH_ROWS = 100_000


def namelike(name: str) -> bool:
    """A token that looks like a made-up handle, not an ordinary word: has a digit or at least two capital letters.
    ("Research" is a label here, but it is also just a word, so a plain mention proves nothing.)"""
    return len(name) >= MIN_NAME and (any(c.isdigit() for c in name) or sum(c.isupper() for c in name) >= 2)


def _page_name(stream_key: str) -> str:
    rest = stream_key.split(":", 1)[1] if ":" in stream_key else stream_key
    return rest.split("~", 1)[1] if "~" in rest else rest


def build(con: duckdb.DuckDBPyConnection) -> dict:
    con.execute("DELETE FROM reference")
    con.execute("DELETE FROM exchange")
    pages: dict[str, list[str]] = {}
    for (sk,) in con.execute("SELECT DISTINCT stream_key FROM text_item WHERE stream_key LIKE 'page:%'").fetchall():
        pages.setdefault(_page_name(sk), []).append(sk)
    labels = {n: i for i, n in con.execute(
        "SELECT label_id, display_name FROM actor_label WHERE display_name IS NOT NULL").fetchall() if namelike(n)}
    mentionable_pages = {n: v for n, v in pages.items() if namelike(n)}
    totals = {"references": 0, "resolved": 0, "ambiguous_or_unknown": 0}
    by_type: dict[str, int] = {}
    if not pages and not labels:
        return {**totals, "exchanges": 0}
    reader = con.cursor()
    reader.execute(
        """
        SELECT i.item_id, i.actor_label_id, i.stream_key, i.stream_key IS NOT NULL AS in_stream, i.text, tc.lines
        FROM text_item i
        LEFT JOIN (SELECT item_id, list(line_no) AS lines FROM text_change
                   WHERE classification IN ('new', 'modified', 'first_observed') GROUP BY item_id) tc USING (item_id)
        WHERE NOT i.generated
        """
    )
    rows: list[tuple] = []

    def flush() -> None:
        if rows:
            df = pl.DataFrame(rows, schema=["item_id", "line_no", "ref_type", "target_kind", "target_id", "target_text",
                                            "span_start", "span_end", "resolved", "detector_version"], orient="row",
                              schema_overrides={"target_id": pl.String}, infer_schema_length=None)
            con.register("ref_df", df)
            con.execute("INSERT INTO reference SELECT * FROM ref_df")
            con.unregister("ref_df")
            rows.clear()

    def add(item_id, n, rtype, kind, target, text, s, e):
        resolved = target is not None
        rows.append((item_id, n, rtype, kind, target, text, s, e, resolved, REFERENCES_VERSION))
        totals["references"] += 1
        totals["resolved" if resolved else "ambiguous_or_unknown"] += 1
        by_type[rtype] = by_type.get(rtype, 0) + 1

    while batch := reader.fetchmany(300):
        for item_id, author, own_stream, in_stream, text, novel_lines in batch:
            novel = set(novel_lines or [])
            offset = 0
            for n, line in enumerate(text.split("\n")):
                start = offset
                offset += len(line) + 1
                if (in_stream and n not in novel) or len(line) < 8:
                    continue
                masked = list(line)

                def mask(a, b, masked=masked):
                    for k in range(a, b):
                        masked[k] = " "

                for m in URL_RE.finditer(line):
                    u = WIKI_URL_RE.search(m.group(0))
                    if u:
                        name = u.group(1).replace("%20", "_")
                        found = pages.get(name, [])
                        target = found[0] if len(found) == 1 else None
                        if target != own_stream:
                            add(item_id, n, "wiki_url", "page", target, name, start + m.start(), start + m.end())
                    mask(m.start(), m.end())
                for m in WIKILINK_RE.finditer(line):
                    name = m.group(1).strip().replace(" ", "_")
                    found = pages.get(name, [])
                    target = found[0] if len(found) == 1 else None
                    if target != own_stream:
                        add(item_id, n, "wikilink", "page", target, name, start + m.start(), start + m.end())
                    mask(m.start(), m.end())
                scan = "".join(masked)
                for m in TOKEN_RE.finditer(scan):
                    tok = m.group(0)
                    lab = labels.get(tok)
                    if lab is not None and lab != author:
                        add(item_id, n, "label_mention", "label", lab, tok, start + m.start(), start + m.end())
                    found = mentionable_pages.get(tok, [])
                    if len(found) == 1 and found[0] != own_stream:
                        add(item_id, n, "page_mention", "page", found[0], tok, start + m.start(), start + m.end())
        if len(rows) >= FLUSH_ROWS:
            flush()
    flush()
    con.execute(
        f"""
        INSERT INTO exchange
        SELECT a.item_id, b.item_id, ta.actor_label_id, tb.actor_label_id,
               CAST(epoch(tb.time_ts) - epoch(ta.time_ts) AS BIGINT), '{REFERENCES_VERSION}'
        FROM reference ra JOIN text_item ta ON ta.item_id = ra.item_id
        JOIN text_item tb ON tb.actor_label_id = ra.target_id
        JOIN reference rb ON rb.item_id = tb.item_id AND rb.target_kind = 'label' AND rb.target_id = ta.actor_label_id
        CROSS JOIN (SELECT 1) AS d
        JOIN (SELECT DISTINCT item_id FROM reference) a ON a.item_id = ra.item_id
        JOIN (SELECT DISTINCT item_id FROM reference) b ON b.item_id = tb.item_id
        WHERE ra.target_kind = 'label' AND ra.resolved AND ta.actor_label_id IS NOT NULL
          AND ta.actor_label_id <> tb.actor_label_id AND tb.time_ts > ta.time_ts
          AND tb.time_ts <= ta.time_ts + INTERVAL {EXCHANGE_HOURS} HOUR
        QUALIFY row_number() OVER (PARTITION BY a.item_id, tb.actor_label_id ORDER BY tb.time_ts, b.item_id) = 1
        """
    )
    n_ex = con.execute("SELECT count(*) FROM exchange").fetchone()[0]
    return {**totals, **{f"type:{k}": v for k, v in sorted(by_type.items())}, "exchanges": n_ex}
