"""Evidence packet export (Markdown + JSON) for one artifact-seeded case.

Corpus text is rendered as inert text: snippets go in fenced blocks with the fence neutralized, never as HTML
or live links.
"""

from __future__ import annotations

import json

import duckdb

from backend.analysis import questions

EXPORT_VERSION = "export-0.1"


def _inert(s: str, limit: int = 300) -> str:
    s = s.replace("```", "'''").replace("\r", " ")
    return s if len(s) <= limit else s[:limit] + " …"


def build_packet(con: duckdb.DuckDBPyConnection, artifact_id: str) -> dict:
    art = con.execute(
        "SELECT a.artifact_type, a.raw, c.full_occurrences, c.novel_occurrences, c.full_items, c.novel_items, "
        "c.full_labels, c.novel_labels FROM artifact a JOIN artifact_counts c USING (artifact_id) "
        "WHERE a.artifact_id = ?",
        [artifact_id],
    ).fetchone()
    if art is None:
        raise KeyError(artifact_id)
    t, raw, fo, no, fi, ni, fl, nl = art
    answers = questions.answer_all(con, artifact_id)
    problems = questions.verify_citations(con, answers)
    edge_cols = ["edge_id", "src_item_id", "dst_item_id", "relation", "evidence_tier", "temporal_status",
                 "directed"]
    edges = [
        dict(zip(edge_cols, r, strict=True))
        for r in con.execute(
            f"SELECT {', '.join(edge_cols)} FROM evidence_edge WHERE artifact_id = ? ORDER BY edge_id", [artifact_id]
        ).fetchall()
    ]
    snap = con.execute("SELECT snapshot_id, source, retrieved_at, importer_version, terms FROM snapshot").fetchall()
    return {
        "export_version": EXPORT_VERSION,
        "artifact": {"artifact_id": artifact_id, "type": t, "raw": raw},
        "counts": {
            "full_occurrences": fo, "novel_occurrences": no, "items_full": fi, "items_novel": ni,
            "labels_full": fl, "labels_novel": nl,
            "note": "full includes carried-forward copies; novel counts non-inherited text only",
        },
        "snapshots": [dict(zip(["snapshot_id", "source", "retrieved_at", "importer_version", "terms"], s, strict=True))
                      for s in snap],
        "edges": edges,
        "answers": answers,
        "citation_problems": problems,
    }


def to_markdown(packet: dict) -> str:
    a, c = packet["artifact"], packet["counts"]
    out = [
        "# SwarmScope evidence packet",
        "",
        f"Seed artifact ({a['type']}): `{_inert(a['raw'], 200).replace('`', ' ')}`",
        "",
        "Author labels are not verified agents. Similarity and shared strings do not establish causation.",
        "",
        "## Counts (with denominators)",
        f"- Occurrences: {c['full_occurrences']} in full text vs {c['novel_occurrences']} in non-inherited text",
        f"- Items: {c['items_full']} vs {c['items_novel']}; author labels: {c['labels_full']} vs {c['labels_novel']}",
        "",
        "## Edges",
    ]
    if not packet["edges"]:
        out.append("- none")
    for e in packet["edges"]:
        out.append(f"- `{e['relation']}` ({e['evidence_tier']}, order: {e['temporal_status']}) "
                   f"{e['src_item_id']} → {e['dst_item_id']}; undirected")
    out += ["", "## Investigation questions"]
    for q in packet["answers"]:
        out += ["", f"### {q['question']}", f"**Status:** {q['status']}", "", q["claim"], ""]
        for cit in q["citations"]:
            out += ["Citation: " + cit["item_id"] + f" [{cit['span_start']}:{cit['span_end']}]",
                    "```", _inert(cit["snippet"]), "```"]
        if q["limitations"]:
            out += ["Limitations:"] + [f"- {x}" for x in q["limitations"]]
    out += ["", "## Provenance"]
    for s in packet["snapshots"]:
        out.append(f"- {s['source']} snapshot {s['snapshot_id']} (importer {s['importer_version']}); {s['terms']}")
    out.append(f"- Citation check: {'all citations resolve' if not packet['citation_problems'] else packet['citation_problems']}")
    return "\n".join(out) + "\n"


def export(con: duckdb.DuckDBPyConnection, artifact_id: str, fmt: str = "markdown") -> str:
    packet = build_packet(con, artifact_id)
    return json.dumps(packet, indent=2, default=str) if fmt == "json" else to_markdown(packet)
