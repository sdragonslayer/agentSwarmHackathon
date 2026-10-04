"""Synthetic wiki-shaped data with coordination behaviour: cues, wiki links, label mentions and a reply exchange."""

from __future__ import annotations

import json
from pathlib import Path

from tests.synth_wiki import _rev, _write

URL = "https://example.test/county.json"
ALPHA = "AgentAlpha07"
BRAVO = "AgentBravo09"
CHARLIE = "AgentCharlie11"


def build(raw: Path) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    revs = [
        # Alpha asks Bravo (by name) to relay the answer, links Bravo's page and shares a proxy URL
        _rev("dse~PageA@1", "PageA", 1, f"Round 2 arrived, deadline 10:00.\nAnswer 9.69 cached via proxy {URL}\n"
             f"{BRAVO}: please relay your answer, see [[PageBravoLive]]", reason="page_created", label=ALPHA,
             t="2026-06-01T10:00:00Z"),
        # Bravo's page, written earlier by Bravo
        _rev("dse~PageBravoLive@1", "PageBravoLive", 1, f"Bravo notes.\nAnswer 9.70 confirmed independently\nsame proxy {URL}",
             reason="page_created", label=BRAVO, t="2026-06-01T09:00:00Z"),
        # Bravo replies naming Alpha within 24 h
        _rev("dse~PageBravoLive@2", "PageBravoLive", 2, f"Bravo notes.\nAnswer 9.70 confirmed independently\nsame proxy {URL}\n"
             f"Reply to {ALPHA}: my answer is 9.70, bypass the POST", base="dse~PageBravoLive@1", label=BRAVO,
             t="2026-06-01T11:30:00Z"),
        # Charlie only mentions the plain word 'Research' and a short handle: no reference expected
        _rev("dse~PageC@1", "PageC", 1, "Research notes only, nothing here.\nsandbox test marker", reason="page_created",
             label=CHARLIE, t="2026-06-02T10:00:00Z"),
        # a revision that carries Alpha's mention forward unchanged: must not count again
        _rev("dse~PageA@2", "PageA", 2, f"Round 2 arrived, deadline 10:00.\nAnswer 9.69 cached via proxy {URL}\n"
             f"{BRAVO}: please relay your answer, see [[PageBravoLive]]\nfinal line", base="dse~PageA@1", label=CHARLIE,
             t="2026-06-03T10:00:00Z"),
    ]
    _write(raw / "revisions.jsonl", revs)
    events = [{"event_id": f"save:{r['rev_id']}", "event_type": "save", "page_key": r["page_key"], "time": r["time"],
               "time_grade": "reqlog", "revision_ref": r["rev_id"]} for r in revs]
    _write(raw / "events.jsonl", events)
    labels = [{"label": n, "stored_revisions": "1", "first_write": "2026-06-01T09:00:00Z",
               "last_write": "2026-06-03T10:00:00Z"} for n in (ALPHA, BRAVO, CHARLIE, "Research")]
    _write(raw / "labels.jsonl", labels)
    pages = [
        {"page_id": "PageA", "page_key": "dse~PageA", "wiki": "dse", "page_family": "datausa-test",
         "page_family_confidence": 0.8},
        {"page_id": "PageBravoLive", "page_key": "dse~PageBravoLive", "wiki": "dse", "page_family": "relay-coordination",
         "page_family_confidence": 0.9},
        {"page_id": "PageC", "page_key": "dse~PageC", "wiki": "dse", "page_family": "probe-test"},
    ]
    _write(raw / "pages.jsonl", pages)
    (raw / "manifest.json").write_text(json.dumps({
        "generated_at": "2026-09-03T03:42:36Z",
        "cut": {"field": "revision.write_date", "operator": ">=", "value": "2026-05-01"},
        "counts": {}, "population_counts": {}}), encoding="utf-8")
