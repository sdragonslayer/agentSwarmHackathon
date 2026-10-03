"""Fetch publisher datasets into data/raw/ (or data/derived/aivillage/ for streamed slices).

Usage (see docs/DATA.md):
    uv run python -m backend.ingest.fetch wiki [--dry-run] [--check-size]
    uv run python -m backend.ingest.fetch transluce [--dry-run]
    uv run python -m backend.ingest.fetch swarmtraces [--url URL] [--dry-run]
    uv run python -m backend.ingest.fetch aivillage schema
    uv run python -m backend.ingest.fetch aivillage text [--tables chat memories] [--yes]
    uv run python -m backend.ingest.fetch aivillage slice --table turns --start ... --end ... [--yes]

--dry-run never touches the network unless --check-size is also given (HEAD requests only).
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from backend.ingest.snapshot import sha256_file, sha256_gunzip, utc_now, write_snapshot

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "sources.toml"
RAW = ROOT / "data" / "raw"
DERIVED = ROOT / "data" / "derived"
USER_AGENT = "SwarmScope-research-fetcher/0.1 (hackathon; contact via repo)"
CHUNK = 1 << 20
MAX_GUNZIP_BYTES = 20_000_000_000


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, read=120.0),
        transport=transport,
    )


def human(n: int | None) -> str:
    if n is None:
        return "unknown size"
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def rel(path: Path) -> str:
    """Repo-relative path for display; absolute when outside the repo."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def head_size(client: httpx.Client, url: str) -> int | None:
    r = client.head(url)
    r.raise_for_status()
    value = r.headers.get("content-length")
    return int(value) if value else None


def download(client: httpx.Client, url: str, target: Path) -> Path:
    """Stream url to target, resuming from target.part via HTTP Range when possible."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with client.stream("GET", url, headers=headers) as r:
        if r.status_code == 416:  # range not satisfiable: .part is already complete
            pass
        else:
            r.raise_for_status()
            if offset and r.status_code != 206:
                offset = 0  # server ignored Range; restart
            mode = "ab" if offset else "wb"
            with part.open(mode) as f:
                for chunk in r.iter_bytes(CHUNK):
                    f.write(chunk)
    part.replace(target)
    return target


def describe_file(path: Path, url: str, reference: dict[str, str] | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": path.name,
        "url": url,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if path.suffix == ".gz":
        digest, size = sha256_gunzip(path, MAX_GUNZIP_BYTES)
        inner = path.name[:-3]
        entry |= {"decompressed_name": inner, "decompressed_bytes": size, "decompressed_sha256": digest}
        expected = (reference or {}).get(inner)
        if expected:
            entry["matches_reference"] = expected == digest
            if expected != digest:
                print(
                    f"  WARNING: {inner} hash differs from the brief's reference snapshot. "
                    "Record this as a new snapshot and reconcile counts.",
                    file=sys.stderr,
                )
    return entry


def safe_extract(zip_path: Path, dest: Path, keep: list[str], max_total: int) -> list[Path]:
    """Extract only members whose file name matches `keep`, rejecting path traversal and bombs."""
    dest = dest.resolve()
    out: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        members = [
            m for m in zf.infolist()
            if not m.is_dir() and any(fnmatch.fnmatch(PurePosixPath(m.filename).name, k) for k in keep)
        ]
        total = sum(m.file_size for m in members)
        if total > max_total:
            raise ValueError(f"selected members total {total} bytes > limit {max_total}")
        for m in members:
            rel = PurePosixPath(m.filename)
            if rel.is_absolute() or ".." in rel.parts or ":" in m.filename:
                raise ValueError(f"unsafe path in archive: {m.filename!r}")
            target = (dest / Path(*rel.parts)).resolve()
            if not target.is_relative_to(dest):
                raise ValueError(f"unsafe path in archive: {m.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with zf.open(m) as src, target.open("wb") as dst:
                while chunk := src.read(CHUNK):
                    written += len(chunk)
                    if written > m.file_size:
                        raise ValueError(f"{m.filename}: actual size exceeds declared size")
                    dst.write(chunk)
            out.append(target)
    return out


def plan_report(rows: list[tuple[str, Path, int | None]]) -> None:
    for url, target, size in rows:
        print(f"  {url}\n    -> {rel(target)}  ({human(size)})")


# ---------------------------------------------------------------- URL sources


def fetch_urls(
    source: str,
    urls: list[str],
    dest: Path,
    args: argparse.Namespace,
    reference: dict[str, str] | None = None,
    client: httpx.Client | None = None,
) -> list[Path]:
    client = client or make_client()
    targets = [dest / PurePosixPath(httpx.URL(u).path).name for u in urls]
    sizes = [head_size(client, u) if args.check_size else None for u in urls]
    print(f"[{source}] {'plan' if args.dry_run else 'downloading'}:")
    plan_report(list(zip(urls, targets, sizes, strict=True)))
    if args.dry_run:
        return []
    files = []
    for url, target in zip(urls, targets, strict=True):
        print(f"  GET {url}")
        download(client, url, target)
        files.append(describe_file(target, url, reference))
    snap = write_snapshot(dest, source, files)
    print(f"[{source}] wrote {rel(snap)}")
    return targets


def cmd_wiki(args: argparse.Namespace, cfg: dict[str, Any], client: httpx.Client | None = None) -> None:
    c = cfg["wiki"]
    urls = [c["base_url"] + name for name in c["files"]]
    fetch_urls("wiki", urls, args.dest or RAW / "wiki", args, c.get("reference_sha256"), client)


def cmd_transluce(args: argparse.Namespace, cfg: dict[str, Any], client: httpx.Client | None = None) -> None:
    c = cfg["transluce"]
    dest = args.dest or RAW / "transluce"
    targets = fetch_urls("transluce", [c["url"]], dest, args, client=client)
    if args.dry_run:
        print(f"  then extract {c['keep']} into {rel(dest)}/extracted/")
        return
    extracted = safe_extract(targets[0], dest / "extracted", c["keep"], c["max_uncompressed_bytes"])
    for p in extracted:
        print(f"  extracted {rel(p)}")
    if not any(p.name == "all-reports.csv" for p in extracted):
        print("  WARNING: all-reports.csv not found in archive; inspect it manually.", file=sys.stderr)


def cmd_swarmtraces(args: argparse.Namespace, cfg: dict[str, Any], client: httpx.Client | None = None) -> None:
    url = args.url or cfg["swarmtraces"]["url"]
    if not url:
        sys.exit(
            "SwarmTraces URL not configured. Open https://swarmtraces.org/viewer/, copy the redacted "
            "dataset download link, and pass --url or set [swarmtraces].url in config/sources.toml."
        )
    fetch_urls("swarmtraces", [url], args.dest or RAW / "swarmtraces", args, client=client)


# ---------------------------------------------------------------- AI Village


def cmd_aivillage(args: argparse.Namespace, cfg: dict[str, Any]) -> None:
    from backend.ingest import aivillage_fetch

    c = cfg["aivillage"]
    if args.av_cmd == "schema":
        aivillage_fetch.schema(c, dry_run=args.dry_run)
    elif args.av_cmd == "text":
        aivillage_fetch.pull_tables(
            c, tables=args.tables or c["text_tables"], dry_run=args.dry_run,
            assume_yes=args.yes, max_gb=args.max_gb or c["default_max_gb"],
        )
    elif args.av_cmd == "slice":
        aivillage_fetch.pull_slice(
            c, table=args.table or c["computer_use_table"], args=args,
            max_gb=args.max_gb or c["default_max_gb"],
        )


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backend.ingest.fetch", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="source", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--dest", type=Path, help="override target directory")
        sp.add_argument("--dry-run", action="store_true", help="print the plan; no downloads")
        sp.add_argument("--check-size", action="store_true", help="with --dry-run, HEAD each URL for its size")

    common(sub.add_parser("wiki", help="collusion.wiki German board export"))
    common(sub.add_parser("transluce", help="Transluce urlquery archive"))
    st = sub.add_parser("swarmtraces", help="SwarmTraces redacted payloads")
    common(st)
    st.add_argument("--url", help="download URL (overrides config)")

    av = sub.add_parser("aivillage", help="AI Village (gated HF dataset; streamed)")
    av_sub = av.add_subparsers(dest="av_cmd", required=True)
    for name, text in [("schema", "read Parquet footers only; write docs/aivillage_schema.md"),
                       ("text", "pull text tables with image columns excluded"),
                       ("slice", "pull a filtered window of a large table")]:
        sp = av_sub.add_parser(name, help=text)
        sp.add_argument("--dry-run", action="store_true")
        if name != "schema":
            sp.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
            sp.add_argument("--max-gb", type=float, help="refuse pulls estimated above this size")
    av_sub.choices["text"].add_argument("--tables", nargs="+", help="table names (see schema doc)")
    sl = av_sub.choices["slice"]
    sl.add_argument("--table", help="table name (default: config computer_use_table)")
    sl.add_argument("--columns", nargs="+", help="explicit columns (default: all non-binary)")
    sl.add_argument("--time-column", help="timestamp column for --start/--end")
    sl.add_argument("--start", help="inclusive ISO timestamp")
    sl.add_argument("--end", help="exclusive ISO timestamp")
    sl.add_argument("--where-column", help="column for an equality filter, e.g. an episode/goal id")
    sl.add_argument("--equals", nargs="+", help="allowed values for --where-column")
    sl.add_argument("--name", help="output name (default derived from filters)")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    cfg = load_config()
    print(f"SwarmScope fetch @ {utc_now()}")
    handlers = {"wiki": cmd_wiki, "transluce": cmd_transluce, "swarmtraces": cmd_swarmtraces,
                "aivillage": cmd_aivillage}
    handlers[args.source](args, cfg)


if __name__ == "__main__":
    main()
