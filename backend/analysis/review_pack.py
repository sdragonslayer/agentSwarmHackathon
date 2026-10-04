"""Build a human-review pack: sampled edges, artifact extractions, lineage lines, question answers, and (when the
cue and reference steps have run) cue lines, request/reply exchanges and explicit references.

    uv run python -m backend.analysis.review_pack --db data/derived/swarm.duckdb --out data/derived/review

Writes review_pack.html (interactive, saves in the browser, exports JSON), review_sheet.csv (same items for a
spreadsheet) and review_key.json (the system's claims; keep it away from reviewers until they finish).
The pack contains corpus text: keep it under data/derived/ and do not redistribute it.

Sampling is seeded and stratified so a rerun on the same database gives the same items. Edges are sampled one per
artifact so items are independent. Candidate retrieval (`possible_reuse`) only runs with --candidates and then
adds those edges to the database.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import duckdb
from rapidfuzz import fuzz, process

from backend.analysis import candidates, questions, topics, traces
from backend.db import DEFAULT_DB, connect

PACK_VERSION = "review-pack-0.2"
SEED = "swarmscope-review-1"
CTX = 220
N_EDGE_URL, N_EDGE_HEX, N_EDGE_REPO, N_CAND_CASES = 20, 15, 5, 6
N_EXTRACT = {"url": 20, "hex_id": 15, "repo_ref": 5}
N_LINEAGE = {"inherited": 10, "new": 10, "modified": 10}
N_QUESTION_ARTIFACTS = 10
# per-source sample sizes (the wiki pack is smaller and adds cue/exchange/reference sections)
WIKI_SIZES = {"edge": {"url": 14, "hex_id": 10}, "extract": {"url": 12, "hex_id": 8},
              "lineage": {"inherited": 5, "new": 5, "modified": 5}, "cues": 36, "exchanges": 16, "references": 16,
              "question_artifacts": 3, "qids": ("earliest", "spread", "references")}


def _ctx(text: str, start: int, end: int) -> dict:
    a, b = max(start - CTX, 0), min(end + CTX, len(text))
    return {"before": text[a:start], "match": text[start:end], "after": text[end:b]}


def _item_meta(con, item_id: str) -> dict:
    r = con.execute(
        "SELECT t.kind, t.source_time, coalesce(l.display_name, t.actor_label_id, 'unknown author label') "
        "FROM text_item t LEFT JOIN actor_label l ON l.label_id = t.actor_label_id WHERE t.item_id = ?",
        [item_id],
    ).fetchone()
    return {"item_id": item_id, "kind": r[0], "time": r[1], "label": r[2]}


def _edge_item(con, item_id: str, start: int, end: int) -> dict:
    text = con.execute("SELECT text FROM text_item WHERE item_id = ?", [item_id]).fetchone()[0]
    return {**_item_meta(con, item_id), "context": _ctx(text, start, end)}


def sample_same_content(con, atype: str, n: int) -> list[dict]:
    rows = con.execute(
        """
        SELECT e.edge_id, e.artifact_id, e.temporal_status, e.support, a.raw
        FROM evidence_edge e JOIN artifact a USING (artifact_id) JOIN artifact_counts c USING (artifact_id)
        WHERE e.relation = 'same_content' AND a.artifact_type = ? AND c.novel_items BETWEEN 2 AND 60
        QUALIFY row_number() OVER (PARTITION BY e.artifact_id ORDER BY md5(e.edge_id || ?)) = 1
        ORDER BY md5(e.artifact_id || ?) LIMIT ?
        """,
        [atype, SEED, SEED, n],
    ).fetchall()
    out = []
    for edge_id, aid, temporal, support, raw in rows:
        s = json.loads(support)
        out.append({
            "section": "edge", "relation": "same_content", "artifact_type": atype, "edge_id": edge_id,
            "artifact_id": aid, "artifact": raw, "temporal_status": temporal,
            "a": _edge_item(con, s["src"]["item_id"], s["src"]["span_start"], s["src"]["span_end"]),
            "b": _edge_item(con, s["dst"]["item_id"], s["dst"]["span_start"], s["dst"]["span_end"]),
        })
    return out


def sample_candidates(con, n_cases: int) -> list[dict]:
    seeds = con.execute(
        """
        SELECT c.artifact_id FROM artifact_counts c JOIN artifact a USING (artifact_id)
        WHERE a.artifact_type = 'url' AND c.novel_labels >= 2 AND c.novel_items BETWEEN 3 AND 30
        ORDER BY md5(c.artifact_id || ?) LIMIT ?
        """,
        [SEED, n_cases],
    ).fetchall()
    out = []
    for (aid,) in seeds:
        candidates.build_for_artifact(con, aid)
    rows = con.execute(
        """
        SELECT e.edge_id, e.artifact_id, e.temporal_status, e.support, a.raw FROM evidence_edge e
        JOIN artifact a USING (artifact_id) WHERE e.relation = 'possible_reuse' AND e.artifact_id IN
        (SELECT unnest(?::VARCHAR[])) ORDER BY md5(e.edge_id || ?) LIMIT 20
        """,
        [[s[0] for s in seeds], SEED],
    ).fetchall()
    for edge_id, aid, temporal, support, raw in rows:
        s = json.loads(support)
        seed_row = con.execute(
            "SELECT line_no, span_start, t.text FROM appearance a JOIN text_item t USING (item_id) "
            "WHERE a.artifact_id = ? AND a.item_id = ? LIMIT 1", [aid, s["seed_item"]]
        ).fetchone()
        seed_line = seed_row[2].split("\n")[seed_row[0]] if seed_row else ""
        cand_text = con.execute("SELECT text FROM text_item WHERE item_id = ?", [s["candidate_item"]]).fetchone()[0]
        if s.get("candidate_line_no") is not None:
            cand_text = cand_text.split("\n")[int(s["candidate_line_no"])]
        out.append({
            "section": "edge", "relation": "possible_reuse", "artifact_type": "url", "edge_id": edge_id,
            "artifact_id": aid, "artifact": raw, "temporal_status": temporal,
            "jaccard": s["jaccard_word_shingles"], "shared_rare_shingles": s["shared_rare_shingles"],
            "a": {**_item_meta(con, s["seed_item"]), "text": seed_line[:900]},
            "b": {**_item_meta(con, s["candidate_item"]), "text": cand_text[:900]},
        })
    return out


def sample_extractions(con, n_by_type: dict | None = None) -> list[dict]:
    out = []
    for atype, n in (n_by_type or N_EXTRACT).items():
        rows = con.execute(
            """
            SELECT a.artifact_id, a.item_id, a.span_start, a.span_end, a.novelty, x.raw
            FROM appearance a JOIN artifact x USING (artifact_id)
            WHERE x.artifact_type = ? AND a.novelty <> 'restored'
            ORDER BY md5(a.item_id || a.artifact_id || ?) LIMIT ?
            """,
            [atype, SEED, n],
        ).fetchall()
        for aid, item_id, s, e, novelty, raw in rows:
            out.append({"section": "extraction", "artifact_type": atype, "artifact_id": aid, "artifact": raw,
                        "a": _edge_item(con, item_id, s, e), "novelty": novelty})
    return out


def sample_lineage(con, n_by_class: dict | None = None) -> list[dict]:
    out = []
    for cls, n in (n_by_class or N_LINEAGE).items():
        if cls == "inherited":
            rows = con.execute(
                """
                SELECT l.item_id, l.base_item_id FROM lineage_summary l
                WHERE l.lineage_status = 'inferred_predecessor' AND l.n_inherited > 0
                ORDER BY md5(l.item_id || ?) LIMIT ?
                """,
                [SEED, n],
            ).fetchall()
            picks = []
            for item_id, base in rows:
                text = con.execute("SELECT text FROM text_item WHERE item_id = ?", [item_id]).fetchone()[0]
                changed = {r[0] for r in con.execute("SELECT line_no FROM text_change WHERE item_id = ?", [item_id])
                           .fetchall()}
                lines = [(i, t.rstrip()) for i, t in enumerate(text.split("\n")) if t.strip() and i not in changed]
                lines = [x for x in lines if len(x[1]) >= 25]
                if lines:
                    i, t = min(lines, key=lambda x: hashlib.md5((SEED + item_id + str(x[0])).encode()).hexdigest())
                    picks.append((item_id, base, i, t, "inherited", None))
        else:
            rows = con.execute(
                """
                SELECT c.item_id, c.base_item_id, c.line_no, c.text, c.classification, c.similarity
                FROM text_change c JOIN lineage_summary l USING (item_id)
                WHERE c.classification = ? AND c.base_item_id IS NOT NULL AND length(c.text) >= 25
                ORDER BY md5(c.item_id || c.line_no || ?) LIMIT ?
                """,
                [cls, SEED, n],
            ).fetchall()
            picks = list(rows)
        for item_id, base, line_no, text, klass, sim in picks:
            base_text = con.execute("SELECT text FROM text_item WHERE item_id = ?", [base]).fetchone()[0]
            base_lines = [t.rstrip() for t in base_text.split("\n") if t.strip()]
            near = process.extract(text, base_lines, scorer=fuzz.ratio, limit=3)
            out.append({
                "section": "lineage", "system_class": klass, "similarity": sim, "line": text[:700],
                "item": _item_meta(con, item_id), "line_no": line_no,
                "base": _item_meta(con, base),
                "nearest_in_predecessor": [{"text": t[:700], "ratio": round(r / 100, 3)} for t, r, _ in near],
                "predecessor_lines": len(base_lines),
            })
    return out


def sample_questions(con, artifact_ids: list[str], qids=("earliest", "introducers"), n_artifacts: int = N_QUESTION_ARTIFACTS) -> list[dict]:
    out = []
    for aid in artifact_ids[:n_artifacts]:
        raw = con.execute("SELECT raw FROM artifact WHERE artifact_id = ?", [aid]).fetchone()[0]
        answers = {a["id"]: a for a in questions.answer_all(con, aid)}
        for qid in qids:
            if qid not in answers:
                continue
            a = answers[qid]
            out.append({"section": "question", "artifact_id": aid, "artifact": raw, "question_id": qid,
                        "question": a["question"], "claim": a["claim"], "status": a["status"],
                        "citations": a["citations"][:3], "limitations": a["limitations"]})
    return out


def sample_cues(con, n: int) -> list[dict]:
    """Cue lines for the reviewer, stratified over categories, one revision per line, seeded."""
    cats = [r[0] for r in con.execute("SELECT DISTINCT category FROM cue_hit ORDER BY 1").fetchall()]
    per = max(n // max(len(cats), 1), 1)
    out = []
    for cat in cats:
        rows = con.execute(
            f"""
            SELECT h.item_id, h.term, h.span_start, h.span_end, t.text, {topics.topic_expr()} AS topic
            FROM cue_hit h JOIN text_item t USING (item_id) WHERE h.category = ?
            QUALIFY row_number() OVER (PARTITION BY h.item_id ORDER BY h.span_start) = 1
            ORDER BY md5(h.item_id || ? || h.category) LIMIT ?
            """,
            [cat, SEED, per],
        ).fetchall()
        for item_id, term, s, e, text, topic in rows:
            out.append({"section": "cue", "category": cat, "term": term, "topic": topic,
                        "a": {**_item_meta(con, item_id), "context": _ctx(text, s, e)}})
    return out


def sample_exchanges(con, n: int) -> list[dict]:
    allx = traces.exchanges(con, 1000)
    allx.sort(key=lambda x: hashlib.md5((SEED + x["a"]["item_id"] + x["b"]["item_id"]).encode()).hexdigest())
    out = []
    for x in allx[:n]:
        out.append({"section": "exchange", "topic": x["topic"], "reply_seconds": x["seconds"],
                    "a": {**_item_meta(con, x["a"]["item_id"]), "context": x["a"]["snippet"]},
                    "b": {**_item_meta(con, x["b"]["item_id"]), "context": x["b"]["snippet"]}})
    return out


def sample_references(con, n: int) -> list[dict]:
    plan = {"label_mention": n * 3 // 8, "wikilink": n // 4, "wiki_url": n // 4}
    plan["page_mention"] = n - sum(plan.values())
    out = []
    for rtype, k in plan.items():
        rows = con.execute(
            """
            SELECT r.item_id, r.span_start, r.span_end, r.target_kind, r.target_text, r.target_id, t.text
            FROM reference r JOIN text_item t USING (item_id) WHERE r.ref_type = ? AND r.resolved
            ORDER BY md5(r.item_id || r.span_start || ?) LIMIT ?
            """,
            [rtype, SEED, k],
        ).fetchall()
        for item_id, s, e, kind, target_text, target_id, text in rows:
            out.append({"section": "reference", "ref_type": rtype, "target_kind": kind, "target_text": target_text,
                        "a": {**_item_meta(con, item_id), "context": _ctx(text, s, e)}})
    return out


def build_items(con: duckdb.DuckDBPyConnection, with_candidates: bool = False) -> list[dict]:
    source = con.execute("SELECT source FROM snapshot LIMIT 1").fetchone()[0]
    if source == "wiki":
        return _build_wiki_items(con, with_candidates)
    items: list[dict] = []
    items += sample_same_content(con, "url", N_EDGE_URL)
    items += sample_same_content(con, "hex_id", N_EDGE_HEX)
    items += sample_same_content(con, "repo_ref", N_EDGE_REPO)
    if with_candidates:
        items += sample_candidates(con, N_CAND_CASES)
    items += sample_extractions(con)
    items += sample_lineage(con)
    qa = [i["artifact_id"] for i in items if i["section"] == "edge" and i["relation"] == "same_content"]
    items += sample_questions(con, list(dict.fromkeys(qa)))
    for n, it in enumerate(items, 1):
        it["id"] = f"R{n:03d}"
    return items


def _build_wiki_items(con, with_candidates: bool) -> list[dict]:
    z = WIKI_SIZES
    items: list[dict] = []
    for atype, n in z["edge"].items():
        items += sample_same_content(con, atype, n)
    if with_candidates:
        items += sample_candidates(con, N_CAND_CASES)
    items += sample_extractions(con, z["extract"])
    items += sample_lineage(con, z["lineage"])
    if con.execute("SELECT count(*) FROM cue_hit").fetchone()[0]:
        items += sample_cues(con, z["cues"])
        items += sample_exchanges(con, z["exchanges"])
        items += sample_references(con, z["references"])
    qa = [i["artifact_id"] for i in items if i["section"] == "edge" and i["relation"] == "same_content"]
    items += sample_questions(con, list(dict.fromkeys(qa)), z["qids"], z["question_artifacts"])
    for n, it in enumerate(items, 1):
        it["id"] = f"R{n:03d}"
    return items


def _key(it: dict) -> dict:
    k = {"id": it["id"], "section": it["section"]}
    for f in ("relation", "artifact_type", "temporal_status", "system_class", "status", "question_id", "edge_id",
              "artifact_id", "similarity", "jaccard", "category", "ref_type", "topic", "reply_seconds"):
        if f in it:
            k[f] = it[f]
    return k


def _public(it: dict) -> dict:
    """What the reviewer sees: no system class/status (avoid anchoring)."""
    hide = {"system_class", "status", "similarity", "jaccard", "temporal_status", "ref_type", "reply_seconds"}
    return {k: v for k, v in it.items() if k not in hide}


def write(items: list[dict], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "review_key.json").write_text(json.dumps({"version": PACK_VERSION, "seed": SEED,
                                                      "items": [_key(i) for i in items]}, indent=2), encoding="utf-8")
    public = [_public(i) for i in items]
    data = json.dumps({"version": PACK_VERSION, "items": public}).replace("<", "\\u003c")
    html = TEMPLATE.replace("/*__DATA__*/null", data)
    (out / "review_pack.html").write_text(html, encoding="utf-8")
    with (out / "review_sheet.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "section", "prompt", "text_a", "text_b", "answer", "second_answer", "notes"])
        for it in public:
            w.writerow([it["id"], it["section"], PROMPTS[it["section"]], _flat(it, "a"), _flat(it, "b"), "", "", ""])


PROMPTS = {
    "edge": "Does the link hold as defined? answer: accept | reject | uncertain; second_answer: none | plausible | explicit",
    "extraction": "Is the extracted string a real artifact of its type? answer: yes | no; second_answer: distinctive | generic | unsure",
    "lineage": "Relative to the predecessor memory: answer: same | edit | new | unsure",
    "question": "Is the system's answer correct and supported by its citations? answer: correct | partly | incorrect | cannot_tell",
    "cue": "Does the highlighted line really do what the cue category says? answer: yes | partly | no",
    "exchange": "Is the second author replying to the first? answer: yes | partly | no | cannot_tell; second_answer: answers | timing | other | none",
    "reference": "Is the highlighted text really a pointer to that label or page? answer: yes | no",
}


def _flat(it: dict, side: str) -> str:
    if it["section"] == "lineage":
        if side == "a":
            return it["line"]
        return " || ".join(n["text"] for n in it["nearest_in_predecessor"])
    if it["section"] == "question":
        return it["claim"] if side == "a" else json.dumps(it["citations"])
    part = it.get(side)
    if not part:
        return ""
    if "context" in part:
        c = part["context"]
        return c["before"] + "[[" + c["match"] + "]]" + c["after"]
    return part.get("text", "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=Path("data/derived/review"))
    ap.add_argument("--candidates", action="store_true", help="also retrieve possible_reuse candidates (adds edges)")
    args = ap.parse_args()
    items = build_items(connect(args.db), args.candidates)
    write(items, args.out)
    by = {}
    for i in items:
        by[i["section"]] = by.get(i["section"], 0) + 1
    print(f"wrote {len(items)} items to {args.out}: {by}")


TEMPLATE = (Path(__file__).parent / "review_template.html").read_text(encoding="utf-8")

if __name__ == "__main__":
    main()
