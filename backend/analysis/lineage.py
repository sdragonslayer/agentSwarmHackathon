"""Separate carried-forward text from newly written text inside lineage streams.

AI Village memories and session goals are rewritten by the same label again and again, and each rewrite
repeats most of the previous text. Counting every repeat as a new utterance would inflate apparent spread, so
each item is split into lines and each line is classified against the stream's earlier items:

- inherited: the line is in the immediately preceding item (not a new utterance)
- restored: not in the predecessor but present in an earlier item (a restore is not new authorship)
- modified: not seen before, but a close edit of a line the predecessor had and this item dropped
- new: not seen before in this stream
- first_observed: every line of the first item in a stream. Earlier items may exist outside the release, so
  this is an *incomplete lineage*, not "newly written".

The predecessor is inferred from recorded time within a (label, kind) stream. The release has no explicit base
pointer, so every classification here has attribution_basis `inferred_predecessor_by_recorded_time`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

import duckdb
import polars as pl
from rapidfuzz import fuzz, process

LINEAGE_VERSION = "lineage-0.1"
ATTRIBUTION_BASIS = "inferred_predecessor_by_recorded_time"
MODIFIED_CUTOFF = 80.0
MIN_FUZZY_LEN = 20
FLUSH_ROWS = 200_000


@dataclass
class ItemResult:
    item_id: str
    base_item_id: str | None
    status: str  # first_in_stream | inferred_predecessor
    n_lines: int = 0
    n_inherited: int = 0
    # (line_no, text, classification, similarity)
    changes: list[tuple[int, str, str, float | None]] = field(default_factory=list)

    def count(self, cls: str) -> int:
        return sum(1 for _, _, c, _ in self.changes if c == cls)


def split_lines(text: str) -> list[tuple[int, str]]:
    """Non-blank lines with their 0-based line numbers in the original text; trailing whitespace dropped."""
    out = []
    for i, raw in enumerate(text.split("\n")):
        line = raw.rstrip()
        if line.strip():
            out.append((i, line))
    return out


class StreamClassifier:
    """Feed items of one stream in order; each call returns that item's classification."""

    def __init__(self) -> None:
        self.prev_id: str | None = None
        self.prev_lines: set[str] = set()
        self.seen: set[str] = set()

    def feed(self, item_id: str, text: str) -> ItemResult:
        lines = split_lines(text)
        cur = {line for _, line in lines}
        if self.prev_id is None:
            res = ItemResult(item_id, None, "first_in_stream", n_lines=len(lines))
            res.changes = [(n, line, "first_observed", None) for n, line in lines]
        else:
            res = ItemResult(item_id, self.prev_id, "inferred_predecessor", n_lines=len(lines))
            dropped = list(self.prev_lines - cur)
            for n, line in lines:
                if line in self.prev_lines:
                    res.n_inherited += 1
                elif line in self.seen:
                    res.changes.append((n, line, "restored", None))
                else:
                    match = None
                    if dropped and len(line) >= MIN_FUZZY_LEN:
                        match = process.extractOne(line, dropped, scorer=fuzz.ratio, score_cutoff=MODIFIED_CUTOFF)
                    if match:
                        res.changes.append((n, line, "modified", round(match[1] / 100, 4)))
                    else:
                        res.changes.append((n, line, "new", None))
        self.prev_id = item_id
        self.prev_lines = cur
        self.seen |= cur
        return res


def classify_stream(items: Iterable[tuple[str, str]]) -> list[ItemResult]:
    c = StreamClassifier()
    return [c.feed(i, t) for i, t in items]


def build(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """(Re)build text_change and lineage_summary for every stream in text_item."""
    con.execute("DELETE FROM text_change")
    con.execute("DELETE FROM lineage_summary")
    reader = con.cursor()
    reader.execute(
        "SELECT stream_key, item_id, text FROM text_item WHERE stream_key IS NOT NULL "
        "ORDER BY stream_key, time_ts, item_id"
    )
    change_rows: list[tuple] = []
    summary_rows: list[tuple] = []
    totals = {"items": 0, "lines": 0, "inherited": 0, "new": 0, "modified": 0, "restored": 0, "first_observed": 0}
    current, clf = None, None

    def flush() -> None:
        if change_rows:
            df = pl.DataFrame(
                change_rows,
                schema=["item_id", "base_item_id", "line_no", "text", "classification", "similarity",
                        "attribution_basis", "detector_version"],
                orient="row",
                schema_overrides={"similarity": pl.Float64, "line_no": pl.Int32},
                infer_schema_length=None,
            )
            con.register("changes_df", df)
            con.execute("INSERT INTO text_change SELECT * FROM changes_df")
            con.unregister("changes_df")
            change_rows.clear()
        if summary_rows:
            df = pl.DataFrame(
                summary_rows,
                schema=["item_id", "stream_key", "base_item_id", "lineage_status", "n_lines", "n_inherited", "n_new",
                        "n_modified", "n_restored", "n_first_observed", "detector_version"],
                orient="row",
                infer_schema_length=None,
            )
            con.register("summary_df", df)
            con.execute("INSERT INTO lineage_summary SELECT * FROM summary_df")
            con.unregister("summary_df")
            summary_rows.clear()

    while rows := reader.fetchmany(500):
        for stream, item_id, text in rows:
            if stream != current:
                current, clf = stream, StreamClassifier()
            r = clf.feed(item_id, text)
            for n, line, cls, sim in r.changes:
                change_rows.append((item_id, r.base_item_id, n, line, cls, sim, ATTRIBUTION_BASIS, LINEAGE_VERSION))
            counts = {k: r.count(k) for k in ("new", "modified", "restored", "first_observed")}
            summary_rows.append(
                (item_id, stream, r.base_item_id, r.status, r.n_lines, r.n_inherited, counts["new"],
                 counts["modified"], counts["restored"], counts["first_observed"], LINEAGE_VERSION)
            )
            totals["items"] += 1
            totals["lines"] += r.n_lines
            totals["inherited"] += r.n_inherited
            for k, v in counts.items():
                totals[k] += v
        if len(change_rows) >= FLUSH_ROWS:
            flush()
    flush()
    return totals
