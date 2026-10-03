"""Deterministic artifact extraction: exact URLs, hex ids and qualified repo refs.

Strings are preserved as they appeared (case and query parameters kept). Normalization only lowercases the
URL scheme and host. A bare domain is never an artifact, and unqualified "PR #7" is skipped because the number
means different things in different repos. Extraction never fetches or follows anything it finds.

Appearances are stored only for non-inherited text. Inherited carryover is counted in `artifact_counts`
(full_occurrences vs novel_occurrences), which is what the inflation analysis reads.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlsplit

import duckdb
import polars as pl

EXTRACTION_VERSION = "artifacts-0.1"
NOVEL = ("standalone", "first_observed", "new", "modified")  # restored text is not new authorship
FLUSH_ROWS = 200_000

URL_RE = re.compile(r"https?://[^\s<>\"'`\)\]\}\|\*]+")
HEX_RE = re.compile(r"(?<![0-9a-fA-F-])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![0-9a-fA-F-])")
REPO_REF_RE = re.compile(r"(?<![\w/.-])([A-Za-z0-9][\w.-]{0,38}/[A-Za-z0-9][\w.-]{0,99})#(\d{1,7})(?!\w)")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]"}


@dataclass(frozen=True)
class Hit:
    artifact_type: str
    raw: str
    normalized: str
    start: int
    end: int


def artifact_id(artifact_type: str, normalized: str) -> str:
    return f"art:{artifact_type}:{hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:16]}"


def normalize_url(raw: str) -> str | None:
    """Lowercase scheme and host only; keep path, query and fragment exactly. None for non-shareable URLs."""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    try:
        host = (parts.hostname or "").lower()
        port = f":{parts.port}" if parts.port else ""
    except ValueError:  # template placeholders such as http://host:${PORT} are not shareable artifacts
        return None
    if not host or host in LOCAL_HOSTS or "{" in host or "$" in host:
        return None
    netloc = parts.netloc
    at = netloc.rfind("@")
    userinfo = netloc[: at + 1] if at >= 0 else ""
    return parts._replace(scheme=parts.scheme.lower(), netloc=f"{userinfo}{host}{port}").geturl()


def extract(line: str) -> list[Hit]:
    """Extract artifacts from one line; offsets are relative to `line`."""
    hits: list[Hit] = []
    masked: list[tuple[int, int]] = []
    if "http" in line:
        for m in URL_RE.finditer(line):
            raw = m.group(0).rstrip(".,;:!?")
            norm = normalize_url(raw)
            if norm is None:
                continue
            hits.append(Hit("url", raw, norm, m.start(), m.start() + len(raw)))
            masked.append((m.start(), m.start() + len(raw)))

    def inside(a: int, b: int) -> bool:
        return any(a >= s and b <= e for s, e in masked)

    if "#" in line:
        for m in REPO_REF_RE.finditer(line):
            if inside(m.start(), m.end()):
                continue
            norm = f"{m.group(1).lower()}#{m.group(2)}"
            hits.append(Hit("repo_ref", m.group(0), norm, m.start(), m.end()))
    for m in HEX_RE.finditer(line):
        if inside(m.start(), m.end()):
            continue
        hits.append(Hit("hex_id", m.group(0), m.group(0), m.start(), m.end()))
    return hits


def build(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    for t in ("appearance", "artifact_counts", "artifact"):
        con.execute(f"DELETE FROM {t}")
    reader = con.cursor()
    reader.execute(
        """
        SELECT i.item_id, i.actor_label_id, i.event_id, i.time_ts, i.stream_key IS NOT NULL AS in_stream, i.text,
               tc.lines, tc.classes
        FROM text_item i
        LEFT JOIN (SELECT item_id, list(line_no) AS lines, list(classification) AS classes
                   FROM text_change GROUP BY item_id) tc USING (item_id)
        WHERE NOT i.generated
        """
    )
    artifacts: dict[str, tuple[str, str, str]] = {}
    # per artifact: full_occ, novel_occ, full_items, novel_items, full_label_mask, novel_label_mask
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    label_bit: dict[str, int] = {}
    rows: list[tuple] = []
    totals = {"items": 0, "appearances": 0}

    def flush() -> None:
        if not rows:
            return
        df = pl.DataFrame(
            rows,
            schema=["artifact_id", "item_id", "actor_label_id", "event_id", "time_ts", "line_no", "span_start",
                    "span_end", "novelty", "extraction_version"],
            orient="row",
            schema_overrides={"time_ts": pl.Datetime("us")},
            infer_schema_length=None,
        )
        con.register("app_df", df)
        con.execute(
            "INSERT INTO appearance (artifact_id, item_id, actor_label_id, event_id, time_ts, line_no, span_start, "
            "span_end, novelty, extraction_version) SELECT * FROM app_df"
        )
        con.unregister("app_df")
        rows.clear()

    while batch := reader.fetchmany(200):
        for item_id, actor, event_id, time_ts, in_stream, text, change_lines, change_classes in batch:
            totals["items"] += 1
            novelty_by_line = dict(zip(change_lines or [], change_classes or [], strict=False))
            bit = 0
            if actor:
                bit = 1 << label_bit.setdefault(actor, len(label_bit))
            seen_full: set[str] = set()
            seen_novel: set[str] = set()
            offset = 0
            for n, line in enumerate(text.split("\n")):
                line_start = offset
                offset += len(line) + 1
                if "http" not in line and "#" not in line and len(line) < 7:
                    continue
                hits = extract(line)
                if not hits:
                    continue
                if in_stream:
                    novelty = novelty_by_line.get(n)  # None => inherited from the predecessor
                else:
                    novelty = "standalone"
                for h in hits:
                    aid = artifact_id(h.artifact_type, h.normalized)
                    artifacts.setdefault(aid, (h.artifact_type, h.raw, h.normalized))
                    s = stats[aid]
                    s[0] += 1
                    seen_full.add(aid)
                    is_novel = novelty in NOVEL
                    if is_novel:
                        s[1] += 1
                        seen_novel.add(aid)
                    if novelty is not None:
                        rows.append((aid, item_id, actor, event_id, time_ts, n, line_start + h.start,
                                     line_start + h.end, novelty, EXTRACTION_VERSION))
                        totals["appearances"] += 1
            for aid in seen_full:
                stats[aid][2] += 1
                stats[aid][4] |= bit
            for aid in seen_novel:
                stats[aid][3] += 1
                stats[aid][5] |= bit
        if len(rows) >= FLUSH_ROWS:
            flush()
    flush()

    art_df = pl.DataFrame(
        [(a, t, r, n, EXTRACTION_VERSION) for a, (t, r, n) in artifacts.items()],
        schema=["artifact_id", "artifact_type", "raw", "normalized", "extraction_version"],
        orient="row",
    )
    con.register("art_df", art_df)
    con.execute("INSERT INTO artifact SELECT * FROM art_df")
    con.unregister("art_df")
    cnt_df = pl.DataFrame(
        [(a, s[0], s[1], s[2], s[3], s[4].bit_count(), s[5].bit_count(), EXTRACTION_VERSION) for a, s in stats.items()],
        schema=["artifact_id", "full_occurrences", "novel_occurrences", "full_items", "novel_items", "full_labels",
                "novel_labels", "extraction_version"],
        orient="row",
    )
    con.register("cnt_df", cnt_df)
    con.execute("INSERT INTO artifact_counts SELECT * FROM cnt_df")
    con.unregister("cnt_df")
    totals["artifacts"] = len(artifacts)
    return totals
