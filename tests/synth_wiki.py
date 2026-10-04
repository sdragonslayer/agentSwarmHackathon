"""Explicitly synthetic wiki-shaped data (collusion.wiki export layout) for offline tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

URL = "https://example.test/data/set?id=7&Mode=A"


def _rev(rev_id, page, seq, text, *, base=None, reason=None, hunks=(), label="", enc="utf8", t="2026-05-24T06:00:00Z"):
    raw = text.encode("utf-8" if enc in ("utf8", "ascii") else "latin-1")
    return {
        "rev_id": rev_id, "page_id": page, "page_key": f"dse~{page}", "wiki": "dse", "name": page, "seq": seq,
        "body": raw.decode("latin-1"), "body_len": len(raw), "body_sha256": hashlib.sha256(raw).hexdigest(),
        "lines": len(raw.decode("latin-1").split("\n")), "diff_base": base, "diff_base_reason": reason,
        "hunks": list(hunks), "label": label, "ip16": "1.2", "time": t, "time_grade": "reqlog",
        "winning_clock": "revision.pref_ts", "uncertainty_seconds": 1, "body_encoding": enc,
    }


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def build(raw: Path) -> dict:
    raw.mkdir(parents=True, exist_ok=True)
    p1 = [
        _rev("dse~P1@1", "P1", 1, f"Intro line one\nShared resource: {URL}", reason="page_created", label="AgentAlpha",
             hunks=[{"op": "replace", "a0": 0, "a1": 1, "b0": 0, "b1": 2}], t="2026-05-24T06:00:00Z"),
        _rev("dse~P1@2", "P1", 2, f"Intro line one\nShared resource: {URL}\nGrüße aus München, new text",
             base="dse~P1@1", label="AgentBeta", hunks=[{"op": "insert", "a0": 2, "a1": 2, "b0": 2, "b1": 3}],
             t="2026-05-24T06:05:00Z"),
        # blank label: unknown author; unchanged text is inherited
        _rev("dse~P1@3", "P1", 3, f"Intro line one\nShared resource: {URL}\nGrüße aus München, new text\nextra tail",
             base="dse~P1@2", label="", hunks=[{"op": "insert", "a0": 3, "a1": 3, "b0": 3, "b1": 4}],
             t="2026-05-24T06:10:00Z"),
    ]
    p2 = [_rev("dse~P2@5", "P2", 5, f"Other page quoting {URL}", reason="earlier_revisions_not_published",
               label="AgentBeta", enc="latin1", hunks=[{"op": "replace", "a0": 0, "a1": 1, "b0": 0, "b1": 1}],
               t="2026-05-25T09:00:00Z")]
    revs = p1 + p2
    _write(raw / "revisions.jsonl", revs)
    events = [{"event_id": f"save:{r['rev_id']}", "event_type": "save", "wiki": "dse", "page": r["name"],
               "page_key": r["page_key"], "time": r["time"], "time_grade": "reqlog", "revision_ref": r["rev_id"],
               "related_event_id": None, "relation_type": None, "round_id": None} for r in revs]
    events.append({"event_id": "delete:dse:rclog:1", "event_type": "delete", "wiki": "dse", "page": "P9",
                   "page_key": "dse~P9", "time": "2026-06-01T00:00:00Z", "time_grade": "reqlog",
                   "winning_clock": "rclog.unix_ts", "uncertainty_seconds": 1, "actor_label": "[Admin1]",
                   "ip16": "9.9", "request_action": "delete"})
    events.append({"event_id": "probe:1", "event_type": "probe", "time": "2026-06-02T00:00:00Z", "time_grade": "reqlog",
                   "ip16": "8.8", "request_action": "probe"})
    _write(raw / "events.jsonl", events)
    labels = [
        {"label": "", "stored_revisions": "1", "first_write": "2026-05-24T06:10:00Z",
         "last_write": "2026-05-24T06:10:00Z"},
        {"label": "AgentAlpha", "stored_revisions": "1", "first_write": "2026-05-24T06:00:00Z",
         "last_write": "2026-05-24T06:00:00Z"},
        {"label": "AgentBeta", "stored_revisions": "2", "first_write": "2026-05-24T06:05:00Z",
         "last_write": "2026-05-25T09:00:00Z"},
    ]
    _write(raw / "labels.jsonl", labels)
    _write(raw / "pages.jsonl", [{"page_id": "P1", "page_key": "dse~P1", "wiki": "dse"},
                                 {"page_id": "P2", "page_key": "dse~P2", "wiki": "dse"}])
    manifest = {
        "generated_at": "2026-09-03T03:42:36Z",
        "cut": {"field": "revision.write_date", "operator": ">=", "value": "2026-05-01"},
        "counts": {"revisions": {"value": 4}, "pages": {"value": 2}, "labels": {"value": 3}},
        "population_counts": {"save": {"value": 4}, "delete": {"value": 1}, "revert": {"value": 0},
                              "probe": {"value": 1}},
    }
    (raw / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return {"url": URL}
