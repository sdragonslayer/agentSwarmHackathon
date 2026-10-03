"""Streamed access to the gated AI Village Hugging Face dataset (~117 GB, mostly screenshots).

Three steps, each run by the user:
1. `schema`: list the repo tree and read only Parquet footers -> docs/aivillage_schema.md.
2. `text`: pull small text tables (chat, memories, ...) with binary/image columns excluded.
3. `slice`: pull a filtered window of a large table (computer-use turns), projection pushed down.

DuckDB reads hf:// Parquet with HTTP range requests, so only the selected column chunks
(and, where row-group statistics allow, only matching row groups) are transferred.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from backend.ingest.fetch import DERIVED, ROOT, human
from backend.ingest.snapshot import sha256_file, write_snapshot

AV_DIR = DERIVED / "aivillage"
SCHEMA_JSON = AV_DIR / "schema.json"
SCHEMA_MD = ROOT / "docs" / "aivillage_schema.md"
SHARD_SUFFIX = re.compile(r"(-\d{5}-of-\d{5}|_\d+|-\d+)$")
SPLIT_NAMES = {"train", "test", "validation", "data", "default"}


def _token() -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    from huggingface_hub import get_token

    token = os.environ.get("HF_TOKEN") or get_token()
    if not token:
        sys.exit("No Hugging Face token. Set HF_TOKEN in .env or run `uv run hf auth login`.")
    return token


def table_of(path: str) -> str:
    """Best-effort table name for a repo file path (confirm against the dataset card)."""
    p = PurePosixPath(path)
    dirs = [d for d in p.parts[:-1] if d.lower() not in SPLIT_NAMES]
    if dirs:
        return dirs[0]
    stem = p.name.split(".")[0]
    stem = SHARD_SUFFIX.sub("", stem)
    for split in SPLIT_NAMES:
        stem = re.sub(rf"(^|[-_]){split}($|[-_])", r"\1", stem).strip("-_")
    return stem or p.name


def _is_binary(t: Any) -> bool:
    import pyarrow as pa

    if pa.types.is_binary(t) or pa.types.is_large_binary(t) or pa.types.is_fixed_size_binary(t):
        return True
    if pa.types.is_struct(t):
        return any(_is_binary(t.field(i).type) for i in range(t.num_fields))
    if pa.types.is_list(t) or pa.types.is_large_list(t) or pa.types.is_fixed_size_list(t):
        return _is_binary(t.value_type)
    if pa.types.is_map(t):
        return _is_binary(t.key_type) or _is_binary(t.item_type)
    return False


def excluded(name: str, arrow_type: Any, patterns: list[str]) -> str | None:
    if _is_binary(arrow_type):
        return "binary type"
    for pat in patterns:
        if re.search(pat, name, re.IGNORECASE):
            return f"name matches /{pat}/"
    return None


def _confirm(msg: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("Not a terminal; re-run with --yes to proceed.", file=sys.stderr)
        return False
    return input(f"{msg} [y/N] ").strip().lower() in {"y", "yes"}


# ---------------------------------------------------------------- schema


def schema(c: dict[str, Any], dry_run: bool = False) -> None:
    repo = c["repo_id"]
    if dry_run:
        print(f"[aivillage schema] would list hf://datasets/{repo} and read Parquet footers only")
        print(f"  -> {SCHEMA_JSON.relative_to(ROOT)}, {SCHEMA_MD.relative_to(ROOT)}, docs/aivillage_card.md")
        return
    import pyarrow.parquet as pq
    from huggingface_hub import HfApi, HfFileSystem
    from huggingface_hub.hf_api import RepoFile

    token = _token()
    api = HfApi(token=token)
    fs = HfFileSystem(token=token)
    files = [e for e in api.list_repo_tree(repo, repo_type="dataset", recursive=True) if isinstance(e, RepoFile)]
    total = sum(f.size or 0 for f in files)
    print(f"[aivillage schema] {len(files)} files, {human(total)} total in repo")

    tables: dict[str, dict[str, Any]] = {}
    other: list[dict[str, Any]] = []
    for f in sorted(files, key=lambda x: x.path):
        if not f.path.endswith(".parquet"):
            other.append({"path": f.path, "bytes": f.size})
            continue
        with fs.open(f"datasets/{repo}/{f.path}", "rb", block_size=1 << 18) as fh:
            pf = pq.ParquetFile(fh)
            md, arrow_schema = pf.metadata, pf.schema_arrow
        col_bytes = [0] * md.num_columns
        for rg in range(md.num_row_groups):
            for ci in range(md.num_columns):
                col_bytes[ci] += md.row_group(rg).column(ci).total_compressed_size
        # Map leaf columns back to top-level fields by path prefix.
        top_bytes: dict[str, int] = {}
        for ci in range(md.num_columns):
            top = md.schema.column(ci).path.split(".")[0]
            top_bytes[top] = top_bytes.get(top, 0) + col_bytes[ci]
        t = tables.setdefault(table_of(f.path), {"files": [], "rows": 0, "bytes": 0, "columns": {}})
        t["files"].append(f.path)
        t["rows"] += md.num_rows
        t["bytes"] += f.size or 0
        for field in arrow_schema:
            col = t["columns"].setdefault(field.name, {
                "type": str(field.type),
                "compressed_bytes": 0,
                "excluded": excluded(field.name, field.type, c["exclude_column_patterns"]),
            })
            col["compressed_bytes"] += top_bytes.get(field.name, 0)
        print(f"  read footer {f.path} ({md.num_rows} rows)")

    AV_DIR.mkdir(parents=True, exist_ok=True)
    SCHEMA_JSON.write_text(json.dumps({"repo_id": repo, "tables": tables, "other_files": other}, indent=2),
                           encoding="utf-8")
    try:
        card = fs.read_text(f"datasets/{repo}/README.md", encoding="utf-8")
        (ROOT / "docs" / "aivillage_card.md").write_text(card, encoding="utf-8")
    except FileNotFoundError:
        pass
    _write_schema_md(repo, tables, other)
    print(f"[aivillage schema] wrote {SCHEMA_JSON.relative_to(ROOT)} and {SCHEMA_MD.relative_to(ROOT)}")


def _write_schema_md(repo: str, tables: dict[str, Any], other: list[dict[str, Any]]) -> None:
    lines = [f"# AI Village schema (`{repo}`)", "",
             ("Generated by `fetch aivillage schema` from Parquet footers only. Table names are inferred "
              "from file paths; confirm them against `docs/aivillage_card.md`."), "",
             "| table | files | rows | on-disk | text-only pull (est.) |", "|---|---|---|---|---|"]
    for name, t in sorted(tables.items()):
        keep = sum(c["compressed_bytes"] for c in t["columns"].values() if not c["excluded"])
        lines.append(f"| `{name}` | {len(t['files'])} | {t['rows']:,} | {human(t['bytes'])} | {human(keep)} |")
    for name, t in sorted(tables.items()):
        lines += ["", f"## `{name}`", "", "| column | type | compressed | excluded |", "|---|---|---|---|"]
        for col, info in t["columns"].items():
            lines.append(f"| `{col}` | `{info['type'][:80]}` | {human(info['compressed_bytes'])} | "
                         f"{info['excluded'] or ''} |")
    if other:
        lines += ["", "## Non-Parquet files", ""]
        lines += [f"- `{o['path']}` ({human(o['bytes'])})" for o in other]
    SCHEMA_MD.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- pulls


def _load_schema() -> dict[str, Any]:
    if not SCHEMA_JSON.exists():
        sys.exit("Run `uv run python -m backend.ingest.fetch aivillage schema` first.")
    return json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))


def match_tables(requested: list[str], available: list[str]) -> list[str]:
    req = [r.lower() for r in requested]
    exact = [a for a in available if a.lower() in req]
    return exact or [a for a in available if any(r in a.lower() for r in req)]


def _quote(col: str) -> str:
    return '"' + col.replace('"', '""') + '"'


def _connect(token: str):
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"CREATE SECRET hf_secret (TYPE huggingface, TOKEN '{token.replace(chr(39), chr(39) * 2)}')")
    return con


def _lit(value: str) -> str:
    """SQL string literal. COPY does not accept prepared parameters, so values are inlined."""
    return "'" + str(value).replace("'", "''") + "'"


def build_select(repo: str, files: list[str], columns: list[str], where: str) -> str:
    paths = ", ".join(_lit(f"hf://datasets/{repo}/{f}") for f in files)
    cols = ", ".join(_quote(c) for c in columns)
    return f"SELECT {cols} FROM read_parquet([{paths}], union_by_name = true){where}"


def _copy(con, repo: str, files: list[str], columns: list[str], where: str, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    sql = build_select(repo, files, columns, where)
    con.execute(f"COPY ({sql}) TO {_lit(out.as_posix())} (FORMAT parquet, COMPRESSION zstd)")
    return con.execute(f"SELECT count(*) FROM read_parquet({_lit(out.as_posix())})").fetchone()[0]


def pull_tables(c: dict[str, Any], tables: list[str], dry_run: bool, assume_yes: bool, max_gb: float) -> None:
    sch = _load_schema()
    chosen = match_tables(tables, list(sch["tables"]))
    if not chosen:
        sys.exit(f"No tables match {tables}. Available: {sorted(sch['tables'])}")
    plan = []
    for name in chosen:
        t = sch["tables"][name]
        cols = [k for k, v in t["columns"].items() if not v["excluded"]]
        dropped = [k for k, v in t["columns"].items() if v["excluded"]]
        est = sum(t["columns"][k]["compressed_bytes"] for k in cols)
        plan.append((name, t, cols, est))
        print(f"[aivillage text] {name}: {t['rows']:,} rows, ~{human(est)} "
              f"(dropping {dropped or 'nothing'})")
    total = sum(p[3] for p in plan)
    print(f"  estimated transfer ~{human(total)} -> {(AV_DIR / 'text').relative_to(ROOT)}/")
    if dry_run:
        return
    if total > max_gb * 1e9 and not assume_yes:
        sys.exit(f"Estimate exceeds --max-gb {max_gb}; narrow --tables or pass --yes --max-gb N.")
    if not _confirm("Proceed?", assume_yes):
        return
    con = _connect(_token())
    files = []
    for name, t, cols, _ in plan:
        out = AV_DIR / "text" / f"{name}.parquet"
        print(f"  pulling {name} ...")
        rows = _copy(con, sch["repo_id"], t["files"], cols, "", out)
        files.append({"name": out.name, "table": name, "rows": rows, "columns": cols,
                      "bytes": out.stat().st_size, "sha256": sha256_file(out)})
        print(f"    {rows:,} rows -> {out.relative_to(ROOT)}")
    write_snapshot(AV_DIR / "text", "aivillage", files, repo_id=sch["repo_id"])


def pull_slice(c: dict[str, Any], table: str, args: Any, max_gb: float) -> None:
    sch = _load_schema()
    chosen = match_tables([table], list(sch["tables"]))
    if len(chosen) != 1:
        sys.exit(f"--table {table!r} matched {chosen or 'nothing'}. Available: {sorted(sch['tables'])}")
    name = chosen[0]
    t = sch["tables"][name]
    cols = args.columns or [k for k, v in t["columns"].items() if not v["excluded"]]
    missing = [k for k in cols if k not in t["columns"]]
    if missing:
        sys.exit(f"Unknown columns {missing}. Columns: {list(t['columns'])}")

    where = build_where(args, t["columns"])

    upper = sum(t["columns"][k]["compressed_bytes"] for k in cols)
    slug = args.name or re.sub(r"[^A-Za-z0-9_.-]+", "_", "_".join(
        [name, *(args.equals or []), args.start or "", args.end or ""])).strip("_")[:80]
    out = AV_DIR / "slices" / slug / f"{slug}.parquet"
    print(f"[aivillage slice] {name}: {t['rows']:,} rows total; filter:{where}")
    print(f"  columns: {cols}")
    print(f"  upper-bound transfer ~{human(upper)} (row-group pruning usually reads far less; "
          f"filter columns without useful statistics may force a full scan of those columns)")
    print(f"  -> {out.relative_to(ROOT)}")
    if args.dry_run:
        return
    if upper > max_gb * 1e9 and not args.yes:
        sys.exit(f"Upper bound exceeds --max-gb {max_gb}; drop columns or pass --yes --max-gb N.")
    if not _confirm("Proceed?", args.yes):
        return
    con = _connect(_token())
    rows = _copy(con, sch["repo_id"], t["files"], cols, where, out)
    print(f"  {rows:,} rows -> {out.relative_to(ROOT)}")
    write_snapshot(out.parent, "aivillage", [{"name": out.name, "table": name, "rows": rows, "columns": cols,
                                             "bytes": out.stat().st_size, "sha256": sha256_file(out)}],
                   repo_id=sch["repo_id"], filter=where)


def build_where(args: Any, columns: dict[str, Any]) -> str:
    clauses = []
    for col in (args.time_column, args.where_column):
        if col and col not in columns:
            sys.exit(f"Unknown filter column {col!r}. Columns: {list(columns)}")
    if args.start or args.end:
        if not args.time_column:
            sys.exit("--start/--end need --time-column")
        tc = _quote(args.time_column)
        if args.start:
            clauses.append(f"TRY_CAST({tc} AS TIMESTAMPTZ) >= CAST({_lit(args.start)} AS TIMESTAMPTZ)")
        if args.end:
            clauses.append(f"TRY_CAST({tc} AS TIMESTAMPTZ) < CAST({_lit(args.end)} AS TIMESTAMPTZ)")
    if args.where_column:
        if not args.equals:
            sys.exit("--where-column needs --equals")
        values = ", ".join(_lit(v) for v in args.equals)
        clauses.append(f"CAST({_quote(args.where_column)} AS VARCHAR) IN ({values})")
    if not clauses:
        sys.exit("A slice needs a filter (--start/--end and/or --where-column/--equals).")
    return " WHERE " + " AND ".join(clauses)
