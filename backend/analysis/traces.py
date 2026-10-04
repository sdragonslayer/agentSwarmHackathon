"""Traces of coordination per topic: what the recorded text can and cannot show.

    uv run python -m backend.analysis.traces --db data/derived/wiki.duckdb --out data/derived/experiments

Nothing here is a verdict or a score. Each table is a count of recorded things with its denominator:
- topic_summary: per topic, how many revisions/labels, how many carry each cue, how many explicit references point at pages
  the writer never wrote, and how many mutual-naming exchanges there are.
- answer_numbers: numbers written on lines that also carry an answer cue, and how many labels wrote the same number.
  Shared numbers prove nothing alone (labels may compute the same correct value independently).
- answer_provenance: of the later repetitions of a shared number by new labels, how many name or link an earlier writer.
- host_adoption: for each web host, how many labels used it and how fast it spread (a resource count, not an edge).
- category_adoption: per week, labels that first appeared and how many of them use each cue category (arrivals vs
  usage, so a mass arrival is not mistaken for diffusion).
- exchanges: A names B, then B names A within the window, with the text of both revisions.
Order and timing use recorded time, whose uncertainty the source does not document.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import duckdb

from backend.analysis import topics
from backend.analysis.references import EXCHANGE_HOURS
from backend.db import DEFAULT_DB, connect

TRACES_VERSION = "traces-0.1"
NUM_RE = re.compile(r"(?<![\w.:/-])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+%?|\d{4,})(?![\w:/-])")
URL_RE = re.compile(r"https?://\S+")


def arrival_burst(con: duckdb.DuckDBPyConnection) -> dict:
    """How concentrated label arrivals are in time (a confound for any 'spread' reading)."""
    rows = con.execute(
        """
        SELECT date_trunc('week', first_ts) AS w, count(*) FROM (
            SELECT actor_label_id, min(time_ts) AS first_ts FROM text_item
            WHERE actor_label_id IS NOT NULL AND time_ts IS NOT NULL GROUP BY 1) GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()
    total = sum(n for _, n in rows)
    if not total:
        return {"labels": 0, "busiest_week": None, "busiest_week_labels": 0, "share": None}
    return {"labels": total, "busiest_week": str(rows[0][0])[:10], "busiest_week_labels": rows[0][1],
            "share": round(rows[0][1] / total, 3)}


def caveat(con: duckdb.DuckDBPyConnection) -> str:
    b = arrival_burst(con)
    text = ("Cues and counts are recorded text patterns, not verdicts. Order and timing use recorded time, whose uncertainty the "
            "source does not document. Shared numbers can come from independent work on the same data.")
    if b["share"] is not None and b["share"] >= 0.25:
        text += (f" {b['share']:.0%} of the {b['labels']:,} author labels first appear in a single week (week of "
                 f"{b['busiest_week']}), so many labels may be working the same assigned task at the same time: a burst of the "
                 "same number, host or phrase is expected even without any relaying.")
    return text


def topic_summary(con: duckdb.DuckDBPyConnection) -> list[dict]:
    t = topics.topic_expr()
    base = {r[0]: {"topic": r[0], "revisions": r[1], "labels": r[2], "pages": r[3]} for r in con.execute(
        f"SELECT {t} AS topic, count(*), count(DISTINCT t.actor_label_id), count(DISTINCT t.stream_key) "
        "FROM text_item t WHERE NOT t.generated GROUP BY 1").fetchall()}
    for topic, cat, n in con.execute(
            f"SELECT {t} AS topic, h.category, count(DISTINCT h.item_id) FROM cue_hit h JOIN text_item t USING (item_id) "
            "GROUP BY ALL").fetchall():
        base[topic][f"cue:{cat}"] = n
    for topic, n, k in con.execute(
            f"""
            WITH wrote AS (SELECT stream_key, actor_label_id FROM text_item WHERE actor_label_id IS NOT NULL GROUP BY ALL)
            SELECT {t} AS topic, count(*), count(DISTINCT (t.actor_label_id, r.target_id))
            FROM reference r JOIN text_item t USING (item_id)
            WHERE r.target_kind = 'page' AND r.resolved AND t.actor_label_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM wrote w WHERE w.stream_key = r.target_id AND w.actor_label_id = t.actor_label_id)
            GROUP BY 1""").fetchall():
        base[topic]["refs_to_pages_never_written_by_author"] = n
        base[topic]["ref_author_page_pairs"] = k
    for topic, n in con.execute(
            f"SELECT {t} AS topic, count(DISTINCT r.item_id || r.target_id) FROM reference r JOIN text_item t USING (item_id) "
            "WHERE r.ref_type = 'label_mention' AND r.resolved GROUP BY 1").fetchall():
        base[topic]["label_mentions"] = n
    for topic, n, pairs in con.execute(
            f"SELECT {t} AS topic, count(*), count(DISTINCT least(e.a_label_id, e.b_label_id) || greatest(e.a_label_id, e.b_label_id)) "
            "FROM exchange e JOIN text_item t ON t.item_id = e.a_item_id GROUP BY 1").fetchall():
        base[topic]["exchanges"] = n
        base[topic]["exchange_label_pairs"] = pairs
    span = {r[0]: (str(r[1]), str(r[2])) for r in con.execute(
        f"SELECT {t} AS topic, min(t.time_ts), max(t.time_ts) FROM text_item t GROUP BY 1").fetchall()}
    for topic, row in base.items():
        row["first_time"], row["last_time"] = span.get(topic, (None, None))
    return sorted(base.values(), key=lambda r: -r["revisions"])


def _answer_groups(con: duckdb.DuckDBPyConnection) -> dict:
    """(topic, number) -> labels, pages and time-ordered events, for numbers on lines that carry an answer cue."""
    t = topics.topic_expr()
    rows = con.execute(
        f"""
        SELECT DISTINCT h.item_id, h.line_no, {t} AS topic, t.actor_label_id, t.stream_key, t.time_ts, t.text
        FROM cue_hit h JOIN text_item t USING (item_id) WHERE h.category = 'answer_sharing'
        """
    ).fetchall()
    seen: dict[tuple[str, str], dict] = {}
    for item_id, line_no, topic, label, stream, ts, text in rows:
        lines = text.split("\n")
        if line_no >= len(lines):
            continue
        line = URL_RE.sub(" ", lines[line_no])
        for m in NUM_RE.finditer(line):
            raw = m.group(1)
            core = raw.replace(",", "").rstrip("%")
            try:
                val = float(core)
            except ValueError:
                continue
            if 1900 <= val <= 2100 and "." not in core:
                continue  # looks like a year
            if val >= 1e9:
                continue  # looks like an epoch timestamp or an id
            rec = seen.setdefault((topic, core), {"topic": topic, "number": raw, "labels": set(), "pages": set(), "events": []})
            if label:
                rec["labels"].add(label)
            rec["pages"].add(stream)
            rec["events"].append((ts, label, item_id, stream))
    return seen


def answer_numbers(con: duckdb.DuckDBPyConnection, min_labels: int = 2) -> list[dict]:
    """Numbers written on lines that carry an answer cue, grouped by topic."""
    seen = _answer_groups(con)
    out = []
    for rec in seen.values():
        if len(rec["labels"]) < min_labels:
            continue
        ev = sorted((e for e in rec["events"] if e[0] is not None and e[1]), key=lambda e: e[0])
        first_t, first_label = (ev[0][0], ev[0][1]) if ev else (None, None)
        later_24h = len({e[1] for e in ev if e[1] != first_label and (e[0] - first_t).total_seconds() <= 86400}) if ev else 0
        out.append({"topic": rec["topic"], "number": rec["number"], "labels": len(rec["labels"]), "pages": len(rec["pages"]),
                    "first_label_id": first_label, "first_time": str(first_t) if first_t else None,
                    "other_labels_within_24h": later_24h})
    return sorted(out, key=lambda r: (-r["labels"], -r["pages"]))


def answer_provenance(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Of the later repetitions of a number by other labels, how many carry an explicit pointer to an earlier writer?

    For each shared number, events are taken in recorded order. A later event by a label that had not written the number
    before is a *repetition*; it has an *explicit pointer* if its revision names or links a label or page that wrote the
    number earlier. No pointer does not mean independent: a writer may have read the page without naming it.
    """
    refs: dict[str, set[str]] = {}
    for item, target in con.execute("SELECT item_id, target_id FROM reference WHERE resolved").fetchall():
        refs.setdefault(item, set()).add(target)
    per_topic: dict[str, dict] = {}
    for (topic, _), rec in _answer_groups(con).items():
        if len(rec["labels"]) < 2:
            continue
        ev = sorted((e for e in rec["events"] if e[0] is not None and e[1]), key=lambda e: e[0])
        seen_labels: set[str] = set()
        seen_streams: set[str] = set()
        row = per_topic.setdefault(topic, {"topic": topic, "shared_numbers": 0, "repetitions_by_new_labels": 0,
                                           "with_explicit_pointer": 0})
        row["shared_numbers"] += 1
        for ts, label, item, stream in ev:
            if label not in seen_labels and seen_labels:
                row["repetitions_by_new_labels"] += 1
                if refs.get(item, set()) & (seen_labels | seen_streams):
                    row["with_explicit_pointer"] += 1
            seen_labels.add(label)
            seen_streams.add(stream)
    out = []
    for row in per_topic.values():
        n = row["repetitions_by_new_labels"]
        row["share_with_pointer"] = round(row["with_explicit_pointer"] / n, 3) if n else None
        out.append(row)
    return sorted(out, key=lambda r: -r["repetitions_by_new_labels"])


def host_adoption(con: duckdb.DuckDBPyConnection, min_labels: int = 5) -> list[dict]:
    rows = con.execute(
        """
        WITH hosts AS (
            SELECT regexp_extract(x.normalized, '^https?://([^/:?#]+)', 1) AS host, a.actor_label_id AS label, a.time_ts AS ts,
                   a.item_id, a.line_no
            FROM appearance a JOIN artifact x USING (artifact_id)
            WHERE x.artifact_type = 'url' AND a.novelty IN ('standalone', 'first_observed', 'new', 'modified')
              AND a.actor_label_id IS NOT NULL AND a.time_ts IS NOT NULL
        ), first AS (
            SELECT host, arg_min(label, ts) AS first_label, min(ts) AS first_ts FROM hosts GROUP BY host
        )
        SELECT h.host, count(DISTINCT h.label) AS labels, f.first_label, f.first_ts,
               count(DISTINCT h.label) FILTER (WHERE h.ts <= f.first_ts + INTERVAL 24 HOUR AND h.label <> f.first_label)
                   AS other_labels_within_24h,
               count(DISTINCT h.item_id) AS revisions,
               count(DISTINCT h.item_id) FILTER (WHERE EXISTS (
                   SELECT 1 FROM cue_hit c WHERE c.item_id = h.item_id AND c.line_no = h.line_no
                   AND c.category = 'bypass_circumvention')) AS revisions_with_bypass_cue
        FROM hosts h JOIN first f USING (host) GROUP BY h.host, f.first_label, f.first_ts
        HAVING count(DISTINCT h.label) >= ? ORDER BY other_labels_within_24h DESC, labels DESC
        """,
        [min_labels],
    ).fetchall()
    names = dict(con.execute("SELECT label_id, display_name FROM actor_label").fetchall())
    return [{"host": r[0], "labels": r[1], "first_label": names.get(r[2], r[2]), "first_time": str(r[3]),
             "other_labels_within_24h": r[4], "revisions": r[5], "revisions_with_bypass_cue": r[6]} for r in rows]


def category_adoption(con: duckdb.DuckDBPyConnection, bucket: str = "week") -> list[dict]:
    """Per time bucket: labels that first appeared then (arrivals) and how many of them ever use each cue category.

    Reading this as diffusion would be wrong when most labels arrive in one burst: a label that arrives already using the
    language has not "adopted" it from anyone. Arrivals are shown next to usage so the two can be told apart.
    """
    rows = con.execute(
        f"""
        WITH first AS (
            SELECT actor_label_id AS label, date_trunc('{bucket}', min(time_ts)) AS b FROM text_item
            WHERE actor_label_id IS NOT NULL AND time_ts IS NOT NULL GROUP BY 1
        ), cue AS (
            SELECT DISTINCT t.actor_label_id AS label, h.category FROM cue_hit h JOIN text_item t USING (item_id)
            WHERE t.actor_label_id IS NOT NULL
        ), first_rev AS (
            SELECT DISTINCT t.actor_label_id AS label, h.category FROM cue_hit h JOIN text_item t USING (item_id)
            JOIN (SELECT actor_label_id AS l, arg_min(item_id, time_ts) AS item FROM text_item
                  WHERE actor_label_id IS NOT NULL GROUP BY 1) f ON f.item = t.item_id
        )
        SELECT cat.category, f.b, count(*) AS arrivals,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM cue c WHERE c.label = f.label AND c.category = cat.category))
                   AS arrivals_using_cue,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM first_rev c WHERE c.label = f.label AND c.category = cat.category))
                   AS arrivals_using_cue_in_first_revision
        FROM first f CROSS JOIN (SELECT DISTINCT category FROM cue_hit) cat GROUP BY 1, 2 ORDER BY 1, 2
        """
    ).fetchall()
    return [{"category": c, "bucket": str(b), "arrivals": n, "arrivals_using_cue": u, "arrivals_using_cue_in_first_revision": f,
             "share": round(u / n, 3) if n else None} for c, b, n, u, f in rows]


def exchanges(con: duckdb.DuckDBPyConnection, limit: int = 40) -> list[dict]:
    t = topics.topic_expr()
    rows = con.execute(
        f"""
        SELECT e.a_item_id, e.b_item_id, la.display_name, lb.display_name, e.seconds, {t} AS topic,
               (SELECT list(DISTINCT category) FROM cue_hit c WHERE c.item_id = e.a_item_id) AS a_cues,
               (SELECT list(DISTINCT category) FROM cue_hit c WHERE c.item_id = e.b_item_id) AS b_cues
        FROM exchange e JOIN text_item t ON t.item_id = e.a_item_id
        JOIN actor_label la ON la.label_id = e.a_label_id JOIN actor_label lb ON lb.label_id = e.b_label_id
        ORDER BY e.seconds LIMIT ?
        """,
        [limit],
    ).fetchall()
    out = []
    for a_item, b_item, la, lb, sec, topic, a_cues, b_cues in rows:
        sides = {}
        for key, item, who in (("a", a_item, la), ("b", b_item, lb)):
            ref = con.execute("SELECT span_start, span_end FROM reference WHERE item_id = ? AND ref_type = 'label_mention' "
                              "AND resolved ORDER BY span_start LIMIT 1", [item]).fetchone()
            text = con.execute("SELECT text FROM text_item WHERE item_id = ?", [item]).fetchone()[0]
            s0, e0 = (ref if ref else (0, 0))
            a, b = max(s0 - 120, 0), min(e0 + 220, len(text))
            sides[key] = {"item_id": item, "label": who,
                          "snippet": {"before": text[a:s0], "match": text[s0:e0], "after": text[e0:b]}}
        out.append({"topic": topic, "seconds": sec, "window_hours": EXCHANGE_HOURS, "a": sides["a"], "b": sides["b"],
                    "a_cues": a_cues or [], "b_cues": b_cues or []})
    return out


def _write(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = sorted({k for r in rows for k in r})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (r.get(k) if not isinstance(r.get(k), (dict, list)) else str(r.get(k))) for k in keys})


def export(con: duckdb.DuckDBPyConnection, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    m = topics.matrix(con, 60)
    flat = [{"topic": t["topic"], "revisions_total": t["items_total"], "category": c, **t["cells"][c]}
            for t in m["topics"] for c in m["categories"]]
    parts = {
        "topic_by_cue_matrix": flat, "topic_summary": topic_summary(con), "answer_numbers": answer_numbers(con), "answer_provenance": answer_provenance(con),
        "host_adoption": host_adoption(con), "category_adoption": category_adoption(con),
        "exchanges": [{"topic": e["topic"], "seconds": e["seconds"], "a_label": e["a"]["label"], "b_label": e["b"]["label"],
                       "a_item": e["a"]["item_id"], "b_item": e["b"]["item_id"], "a_cues": ",".join(e["a_cues"]),
                       "b_cues": ",".join(e["b_cues"])} for e in exchanges(con, 500)],
    }
    for name, rows in parts.items():
        _write(out / f"{name}.csv", rows)
    return {k: len(v) for k, v in parts.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=Path("data/derived/experiments"))
    args = ap.parse_args()
    for k, v in export(connect(args.db), args.out).items():
        print(f"{k:24} {v:>7} rows")


if __name__ == "__main__":
    main()
