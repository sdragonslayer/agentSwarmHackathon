"""Profile a local data file before writing or adjusting an adapter.

    uv run python -m backend.ingest.profile data/raw/wiki/events.jsonl.gz --group-by event_type
    uv run python -m backend.ingest.profile data/raw/transluce/extracted/all-reports.csv
    uv run python -m backend.ingest.profile data/derived/aivillage/text/chat.parquet --sample 5

Prints row count, column types, null rates, and sample rows; with --group-by, the
row count and non-null fields per group (event schemas vary by type). Local files only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb


def reader(path: Path) -> str:
    p = path.as_posix().replace("'", "''")
    name = path.name.lower()
    if ".parquet" in name:
        return f"read_parquet('{p}')"
    if ".csv" in name:
        return f"read_csv_auto('{p}', sample_size = -1)"
    if ".jsonl" in name or ".ndjson" in name:
        return f"read_json_auto('{p}', format = 'newline_delimited', union_by_name = true, sample_size = -1)"
    if ".json" in name:
        return f"read_json_auto('{p}')"
    raise SystemExit(f"Unsupported file type: {path}")


def profile(path: Path, sample: int, group_by: str | None) -> None:
    con = duckdb.connect()
    src = reader(path)
    con.execute(f"CREATE VIEW t AS SELECT * FROM {src}")
    n = con.execute("SELECT count(*) FROM t").fetchone()[0]
    cols = con.execute("DESCRIBE t").fetchall()
    print(f"{path}  rows={n:,}  columns={len(cols)}\n")
    print(f"{'column':32} {'type':40} null%")
    for name, typ, *_ in cols:
        q = '"' + name.replace('"', '""') + '"'
        nulls = con.execute(f"SELECT count(*) FILTER (WHERE {q} IS NULL) FROM t").fetchone()[0]
        print(f"{name[:32]:32} {typ[:40]:40} {100 * nulls / max(n, 1):5.1f}")
    if group_by:
        q = '"' + group_by.replace('"', '""') + '"'
        print(f"\nper {group_by}:")
        for (value, count) in con.execute(f"SELECT {q}, count(*) FROM t GROUP BY 1 ORDER BY 2 DESC").fetchall():
            present = []
            for name, *_ in cols:
                cq = '"' + name.replace('"', '""') + '"'
                has = con.execute(
                    f"SELECT count(*) FROM t WHERE {q} IS NOT DISTINCT FROM ? AND {cq} IS NOT NULL", [value]
                ).fetchone()[0]
                if has:
                    present.append(name)
            print(f"  {value!s:30} {count:>8,}  fields: {', '.join(present)}")
    if sample:
        print(f"\nsample ({sample} rows, values truncated):")
        for row in con.execute(f"SELECT * FROM t USING SAMPLE {sample} ROWS").fetchall():
            print({c[0]: (str(v)[:120] if v is not None else None) for c, v in zip(cols, row, strict=True)})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", type=Path)
    ap.add_argument("--sample", type=int, default=3)
    ap.add_argument("--group-by")
    a = ap.parse_args()
    profile(a.path, a.sample, a.group_by)


if __name__ == "__main__":
    main()
