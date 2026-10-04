"""German message-board adapter (collusion.wiki export): revisions, events and labels into DuckDB.

    uv run python -m backend.ingest.wiki --raw data/raw/full-wiki-logs --db data/derived/wiki.duckdb

Use a database file of its own: loading wipes the database it is given.

Verified against the real files (see docs/wiki_findings.md):
- `body` holds the raw bytes one character per byte (latin-1). `sha256(body.encode('latin-1'))` equals
  `body_sha256` for every row. `body_encoding` says how those bytes are text: utf8/ascii -> decode as UTF-8,
  latin1 -> keep. The decoded text is what we store; the source hash is kept and re-checked by `validate`.
- Hunks index lines split on "\\n", 0-based and half-open; `lines` = len(body.split("\\n")). We do not build on
  hunks: lineage compares bodies, and `validate_raw` proves the hunk convention against the real data.
- `diff_base` is always the immediate predecessor within the same page; each page's first revision has none.
  `diff_base_reason` = page_created means the whole text is new; earlier_revisions_not_published means the
  history before the published cut is missing (incomplete lineage).
- Clock: time/time_grade/winning_clock/uncertainty_seconds are kept verbatim in `clock_provenance`. The export does
  not say what uncertainty_seconds means, so no time bounds are derived. `archived_at` is never an action time.
- An empty `label` means unknown author (899 revisions); it is never one shared author. `ip16` is not a label
  and is not merged into anything.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from datetime import datetime
from pathlib import Path

import duckdb
import polars as pl

from backend.db import DEFAULT_DB, clear_all, connect
from backend.ingest.snapshot import IMPORTER_VERSION, sha256_file, utc_now

SOURCE = "wiki"
FILES = ["revisions.jsonl", "events.jsonl", "labels.jsonl", "pages.jsonl", "manifest.json"]
TERMS = (
    "collusion.wiki public export; redistribution rights unconfirmed. The host redacted personal information and "
    "reconstructed deleted pages from edit history. Do not commit data/ to a public repo."
)
PY_ENCODING = {"ascii": "utf-8", "utf8": "utf-8", "latin1": "latin-1"}
Check = tuple[str, bool, str]


def _jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=None)  # the export uses UTC "Z" timestamps


def source_bytes(rev: dict) -> bytes:
    """The raw bytes the source hashed: `body` stores them one character per byte."""
    return rev["body"].encode("latin-1")


def decode_body(rev: dict) -> str:
    return source_bytes(rev).decode(PY_ENCODING[rev["body_encoding"]])


def clock_text(row: dict) -> str:
    unc = row.get("uncertainty_seconds")
    return (f"{row.get('time_grade')}; winning_clock={row.get('winning_clock') or 'n/a'}; uncertainty_seconds={unc} "
            "(meaning not documented by the source, so no time bounds are derived)")


def _reference_hashes() -> dict[str, str]:
    cfg = Path(__file__).resolve().parents[2] / "config" / "sources.toml"
    if not cfg.exists():
        return {}
    ref = tomllib.loads(cfg.read_text(encoding="utf-8")).get("wiki", {}).get("reference_sha256", {})
    return {k: v for k, v in ref.items()}


def load(raw: Path, db_path: Path = DEFAULT_DB) -> dict[str, int]:
    missing = [f for f in FILES if not (raw / f).exists()]
    if missing:
        raise FileNotFoundError(f"missing wiki files in {raw}: {missing}")
    con = connect(db_path)
    clear_all(con)
    sums = {}
    if (raw / "SHA256SUMS").exists():
        for line in (raw / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2:
                sums[parts[1].lstrip("*")] = parts[0]
    ref = _reference_hashes()
    files = []
    for name in FILES:
        digest = sha256_file(raw / name)
        rec = {"name": name, "bytes": (raw / name).stat().st_size, "sha256": digest,
               "matches_SHA256SUMS": (digest == sums[name]) if name in sums else None}
        if name in ref:
            rec["matches_reference_snapshot"] = digest == ref[name]
        files.append(rec)
    revs = _jsonl(raw / "revisions.jsonl")
    events = _jsonl(raw / "events.jsonl")
    labels = _jsonl(raw / "labels.jsonl")
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    snap = f"wiki:{manifest.get('generated_at', utc_now())}"
    hash_bad = sum(hashlib.sha256(source_bytes(r)).hexdigest() != r["body_sha256"] for r in revs)
    first_by_page: dict[str, dict] = {}
    for r in sorted(revs, key=lambda r: r["seq"]):
        first_by_page.setdefault(r["page_key"], r)
    incomplete = sum(1 for r in first_by_page.values() if r["diff_base_reason"] != "page_created")
    pops = ", ".join(sorted(manifest.get("population_counts", {}).keys() & {"save", "delete", "revert", "probe"}))
    notes = (
        f"Manifest generated {manifest.get('generated_at')}; cut: {manifest['cut']['field']} "
        f"{manifest['cut']['operator']} {manifest['cut']['value']}. Revisions before the cut are not published, so "
        f"{incomplete} of {len(first_by_page)} pages start with incomplete lineage. Event populations ({pops}) overlap "
        f"and are not independent incidents. Body hash round-trip failures at load: {hash_bad}."
    )
    con.execute("INSERT INTO snapshot VALUES (?, ?, ?, ?, ?, ?, ?)",
                [snap, SOURCE, utc_now(), IMPORTER_VERSION, json.dumps(files), TERMS, notes])
    _load_actors(con, snap, labels, events)
    rev_by_id = {r["rev_id"]: r for r in revs}
    save_event = {e["revision_ref"]: e["event_id"] for e in events if e["event_type"] == "save"}
    _load_events(con, snap, events, rev_by_id)
    _load_revisions(con, snap, revs, save_event)
    _load_page_meta(con, _jsonl(raw / "pages.jsonl"))
    return counts(con)


def _label_id(name: str | None) -> str | None:
    return f"wiki:label:{name}" if name else None  # empty label = unknown author, never a shared one


def _load_actors(con, snap: str, labels: list[dict], events: list[dict]) -> None:
    rows, seen = [], set()
    for lab in labels:
        name = lab["label"]
        if not name:
            continue  # the published blank-label entry stands for unknown authors; not an actor
        seen.add(name)
        rows.append((_label_id(name), snap, "label", name, None, _ts(lab.get("first_write")), _ts(lab.get("last_write")),
                     "unverified_label"))
    for e in events:  # actors that only appear on deletion/revert events (e.g. admin handles)
        name = e.get("actor_label")
        if name and name not in seen:
            seen.add(name)
            rows.append((_label_id(name), snap, "label", name, None, None, None, "unverified_label"))
    df = pl.DataFrame(rows, schema=["label_id", "snapshot_id", "kind", "display_name", "model_string", "first_seen",
                                    "last_seen", "identity_status"], orient="row",
                      schema_overrides={"model_string": pl.String, "first_seen": pl.Datetime("us"),
                                        "last_seen": pl.Datetime("us")}, infer_schema_length=None)
    con.register("wiki_actors", df)
    con.execute("INSERT INTO actor_label SELECT * FROM wiki_actors")
    con.unregister("wiki_actors")
    con.execute("INSERT INTO actor_label_name SELECT label_id, display_name, first_seen, last_seen, NULL "
                "FROM actor_label")


def _load_events(con, snap: str, events: list[dict], rev_by_id: dict) -> None:
    rows = []
    for e in events:
        actor = None
        clock_src = e
        if e["event_type"] == "save":
            rev = rev_by_id.get(e["revision_ref"])
            actor = _label_id(rev["label"]) if rev else None
            clock_src = rev or e
        elif e.get("actor_label"):
            actor = _label_id(e["actor_label"])
        rows.append((f"wiki:ev:{e['event_id']}", snap, None, e["event_type"], actor, None, None, e.get("time"),
                     _ts(e.get("time")), clock_text(clock_src), None, None, None, None, None, "events.jsonl",
                     e["event_id"]))
    df = pl.DataFrame(rows, schema=["event_id", "snapshot_id", "event_index", "kind", "actor_label_id", "room_id",
                                    "session_id", "source_time", "time_ts", "clock_provenance", "time_lower",
                                    "time_upper", "input_tokens", "output_tokens", "cost", "source_file", "source_id"],
                      orient="row",
                      schema_overrides={"event_index": pl.Int64, "room_id": pl.String, "session_id": pl.String,
                                        "time_ts": pl.Datetime("us"), "time_lower": pl.Datetime("us"),
                                        "time_upper": pl.Datetime("us"), "input_tokens": pl.Int64,
                                        "output_tokens": pl.Int64, "cost": pl.Int64},
                      infer_schema_length=None)
    con.register("wiki_events", df)
    con.execute("INSERT INTO event SELECT * FROM wiki_events")
    con.unregister("wiki_events")


def _load_revisions(con, snap: str, revs: list[dict], save_event: dict[str, str]) -> None:
    rows = []
    for r in revs:
        text = decode_body(r)
        if r["diff_base"]:
            base, note = f"wiki:rev:{r['diff_base']}", "explicit"
        else:
            base, note = None, ("page_created" if r["diff_base_reason"] == "page_created" else "incomplete")
        ev = save_event.get(r["rev_id"])
        rows.append((f"wiki:rev:{r['rev_id']}", snap, "wiki_revision", _label_id(r["label"]),
                     f"wiki:ev:{ev}" if ev else None, None, None, r["time"], _ts(r["time"]), text,
                     hashlib.sha256(text.encode("utf-8")).hexdigest(), len(text), False, f"page:{r['page_key']}",
                     "revisions.jsonl", "revisions", r["rev_id"], r["seq"], base, note, r["body_sha256"],
                     r["body_encoding"]))
    df = pl.DataFrame(rows, schema=["item_id", "snapshot_id", "kind", "actor_label_id", "event_id", "room_id",
                                    "session_id", "source_time", "time_ts", "text", "text_sha256", "text_len",
                                    "generated", "stream_key", "source_file", "source_table", "source_id",
                                    "stream_seq", "base_item_id", "base_note", "source_sha256", "source_encoding"],
                      orient="row",
                      schema_overrides={"room_id": pl.String, "session_id": pl.String, "time_ts": pl.Datetime("us"),
                                        "stream_seq": pl.Int64, "base_item_id": pl.String},
                      infer_schema_length=None)
    con.register("wiki_items", df)
    con.execute("INSERT INTO text_item (item_id, snapshot_id, kind, actor_label_id, event_id, room_id, session_id, "
                "source_time, time_ts, text, text_sha256, text_len, generated, stream_key, source_file, source_table, "
                "source_id, stream_seq, base_item_id, base_note, source_sha256, source_encoding) "
                "SELECT * FROM wiki_items")
    con.unregister("wiki_items")


PAGE_META_KEYS = ("page_family", "page_family_confidence", "page_family_method", "page_family_cohort", "bucket")


def _load_page_meta(con, pages: list[dict]) -> None:
    """The publisher's per-page classification. Kept as source attributes, never as our own finding."""
    rows = [(f"page:{p['page_key']}", k, str(p[k]), "pages.jsonl") for p in pages for k in PAGE_META_KEYS
            if p.get(k) is not None]
    if rows:
        df = pl.DataFrame(rows, schema=["stream_key", "key", "value", "source_file"], orient="row")
        con.register("wiki_meta", df)
        con.execute("INSERT INTO stream_meta SELECT * FROM wiki_meta")
        con.unregister("wiki_meta")


def counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    out = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("event", "text_item", "actor_label")}
    for kind, n in con.execute("SELECT kind, count(*) FROM event GROUP BY 1 ORDER BY 2 DESC").fetchall():
        out[f"event:{kind}"] = n
    return out


# ---- checks that need the raw files (run by `backend.analysis.validate --raw`) ----

def validate_raw(raw: Path) -> list[Check]:
    revs = _jsonl(raw / "revisions.jsonl")
    events = _jsonl(raw / "events.jsonl")
    labels = _jsonl(raw / "labels.jsonl")
    pages = _jsonl(raw / "pages.jsonl")
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    by_id = {r["rev_id"]: r for r in revs}
    out: list[Check] = []

    sums = {}
    if (raw / "SHA256SUMS").exists():
        for line in (raw / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2:
                sums[parts[1].lstrip("*")] = parts[0]
    mism = [n for n, h in sums.items() if (raw / n).exists() and sha256_file(raw / n) != h]
    ref = _reference_hashes()
    ref_mism = [n for n, h in ref.items() if (raw / n).exists() and sha256_file(raw / n) != h]
    ref_note = ("matches the reference snapshot inspected in the brief" if not ref_mism else
                f"differs from the reference snapshot for {ref_mism} (a newer release is allowed: counts are "
                "reconciled against this release's own manifest, not forced to match)")
    out.append(("source files match the release's own SHA256SUMS", not mism,
                f"checked {len(sums)} files; SHA256SUMS mismatches={mism}; {ref_note}"))

    bad_hash = sum(hashlib.sha256(source_bytes(r)).hexdigest() != r["body_sha256"] for r in revs)
    bad_rt = sum(hashlib.sha256(decode_body(r).encode(PY_ENCODING[r["body_encoding"]])).hexdigest()
                 != r["body_sha256"] for r in revs)
    out.append(("body_sha256 verified under the documented encoding, and decoding round-trips", bad_hash == bad_rt == 0,
                (f"revisions={len(revs)} source-hash mismatches={bad_hash} decode round-trip mismatches={bad_rt}; "
                 f"encodings={sorted({r['body_encoding'] for r in revs})}")))

    gaps_bad = lines_bad = with_base = 0
    for r in revs:
        if len(r["body"].split("\n")) != r["lines"]:
            lines_bad += 1
        if not r["diff_base"]:
            continue
        with_base += 1
        a, n = by_id[r["diff_base"]]["body"].split("\n"), r["body"].split("\n")
        last_a = last_b = 0
        ok = True
        for h in r["hunks"]:
            if h["a0"] < last_a or h["b0"] < last_b or h["a1"] > len(a) or h["b1"] > len(n) or \
                    a[last_a:h["a0"]] != n[last_b:h["b0"]]:
                ok = False
                break
            last_a, last_b = h["a1"], h["b1"]
        gaps_bad += (not ok) or a[last_a:] != n[last_b:]
    out.append(("hunk offsets: 0-based half-open on newline-split lines (unchanged gaps identical)",
                gaps_bad == lines_bad == 0,
                (f"revisions with a base={with_base} violating gap identity={gaps_bad}; `lines` != newline-split "
                 f"count={lines_bad}")))

    bypage: dict[str, list[dict]] = {}
    for r in revs:
        bypage.setdefault(r["page_key"], []).append(r)
    not_imm = cross = first_has_base = later_no_base = 0
    for v in bypage.values():
        v.sort(key=lambda r: r["seq"])
        first_has_base += v[0]["diff_base"] is not None
        for i, r in enumerate(v):
            if i > 0 and r["diff_base"] is None:
                later_no_base += 1
            if r["diff_base"]:
                cross += by_id[r["diff_base"]]["page_key"] != r["page_key"]
                not_imm += i == 0 or v[i - 1]["rev_id"] != r["diff_base"]
    reasons = {}
    for v in bypage.values():
        reasons[v[0]["diff_base_reason"]] = reasons.get(v[0]["diff_base_reason"], 0) + 1
    out.append(("diff_base is the immediate predecessor in the same page; only page starts lack one",
                not_imm == cross == first_has_base == later_no_base == 0,
                (f"pages={len(bypage)} not-immediate={not_imm} cross-page={cross} first-with-base={first_has_base} "
                 f"later-without-base={later_no_base}; first-revision reasons={reasons}")))

    saves = [e for e in events if e["event_type"] == "save"]
    refs = {e["revision_ref"] for e in saves}
    time_diff = sum(by_id[e["revision_ref"]]["time"] != e["time"] for e in saves if e["revision_ref"] in by_id)
    out.append(("save events and revisions are one action each (no double counting)",
                len(saves) == len(revs) == len(refs) and refs == set(by_id) and time_diff == 0,
                (f"save events={len(saves)} revisions={len(revs)} distinct revision_ref={len(refs)} "
                 f"time disagreements={time_diff}")))

    mc = manifest["counts"]
    pc = manifest["population_counts"]
    by_type = {}
    for e in events:
        by_type[e["event_type"]] = by_type.get(e["event_type"], 0) + 1
    expect = {"revisions": (mc["revisions"]["value"], len(revs)), "pages": (mc["pages"]["value"], len(pages)),
              "labels (incl. blank entry)": (mc["labels"]["value"], len(labels)),
              "distinct pages in revisions": (mc["pages"]["value"], len(bypage)),
              **{f"{k} events": (pc[k]["value"], by_type.get(k, 0)) for k in ("save", "delete", "revert", "probe")}}
    wrong = {k: v for k, v in expect.items() if v[0] != v[1]}
    blank_rev = sum(1 for r in revs if not r["label"])
    blank_entry = next((lab for lab in labels if not lab["label"]), None)
    blank_ok = blank_entry is not None and int(blank_entry["stored_revisions"]) == blank_rev
    out.append(("counts reconcile with the publisher's manifest (expected, actual)", not wrong and blank_ok,
                (f"mismatches={wrong}; revisions with blank label={blank_rev} (published blank-label entry says "
                 f"{blank_entry['stored_revisions'] if blank_entry else 'missing'}); physical event rows={len(events)} "
                 "(not an incident count)")))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=Path("data/raw/full-wiki-logs"))
    ap.add_argument("--db", type=Path, default=Path("data/derived/wiki.duckdb"))
    args = ap.parse_args()
    for k, v in load(args.raw, args.db).items():
        print(f"{k:28} {v:>10,}")


if __name__ == "__main__":
    main()
