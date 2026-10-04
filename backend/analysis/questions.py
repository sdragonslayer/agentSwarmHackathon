"""The fixed investigation questionnaire, answered deterministically for one artifact-seeded case.

Each answer is {id, question, claim, status, citations, limitations}. Status is one of supported | partial |
unknown | conflicting. Where the loaded data cannot answer, the answer abstains (`unknown`) and says why.
Citations are exact spans: text_item.text[span_start:span_end] must equal `snippet` (see verify_citations).
"""

from __future__ import annotations

import duckdb

QUESTIONS_VERSION = "questions-0.1"
NOVEL_SQL = "a.novelty IN ('standalone', 'first_observed', 'new', 'modified')"


def scope_note(con: duckdb.DuckDBPyConnection) -> str:
    row = con.execute("SELECT source, coverage_notes FROM snapshot LIMIT 1").fetchone()
    return f"Scope is the loaded {row[0]} tables only. {row[1]}" if row else "Scope is the loaded tables only."


def _cite(row: dict) -> dict:
    return {k: row[k] for k in ("item_id", "event_id", "span_start", "span_end", "snippet")}


def _appearances(con: duckdb.DuckDBPyConnection, artifact_id: str, novel_only: bool = True) -> list[dict]:
    cols = ["item_id", "event_id", "actor_label_id", "kind", "time_ts", "event_index", "span_start", "span_end",
            "snippet", "novelty", "display_name", "line_no", "stream_key"]
    rows = con.execute(
        f"""
        SELECT a.item_id, a.event_id, a.actor_label_id, t.kind, a.time_ts, e.event_index, a.span_start, a.span_end,
               substr(t.text, a.span_start + 1, a.span_end - a.span_start) AS snippet, a.novelty, l.display_name,
               a.line_no, t.stream_key
        FROM appearance a JOIN text_item t USING (item_id)
        LEFT JOIN event e ON e.event_id = a.event_id LEFT JOIN actor_label l ON l.label_id = a.actor_label_id
        WHERE a.artifact_id = ? {"AND " + NOVEL_SQL if novel_only else ""}
        ORDER BY a.time_ts NULLS LAST, e.event_index NULLS LAST, a.item_id
        """,
        [artifact_id],
    ).fetchall()
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _label(a: dict) -> str:
    return a["display_name"] or a["actor_label_id"] or "unknown author label"


def answer_all(con: duckdb.DuckDBPyConnection, artifact_id: str) -> list[dict]:
    art = con.execute("SELECT artifact_type, raw FROM artifact WHERE artifact_id = ?", [artifact_id]).fetchone()
    if art is None:
        raise KeyError(artifact_id)
    counts = con.execute(
        "SELECT full_occurrences, novel_occurrences, full_items, novel_items, novel_labels "
        "FROM artifact_counts WHERE artifact_id = ?",
        [artifact_id],
    ).fetchone()
    full_occ, novel_occ, _, novel_items, novel_labels = counts
    novel = _appearances(con, artifact_id)
    scope = scope_note(con)
    out: list[dict] = []

    def add(qid, question, claim, status, citations=(), limitations=()):
        out.append({
            "id": qid, "question": question, "claim": claim, "status": status,
            "citations": [_cite(c) for c in citations], "limitations": [scope, *limitations],
        })

    # 1. earliest appearance
    if novel:
        first = novel[0]
        ties = [a for a in novel[1:] if a["time_ts"] == first["time_ts"]]
        lim = [
            "Order is by recorded database time, whose clock uncertainty the source does not give.",
            "Items without an event (memories, session goals) have no source sequence number.",
        ]
        if ties:
            lim.append(f"{len(ties)} other appearance(s) share the same recorded timestamp; order among them is unresolved.")
        add("earliest", "What is the earliest observed appearance?",
            f"Earliest recorded appearance is a {first['kind']} by {_label(first)} at {first['time_ts']}.",
            "partial" if ties else "supported", [first, *ties], lim)
    else:
        add("earliest", "What is the earliest observed appearance?", "No non-inherited appearance recorded.", "unknown")

    # 2. who introduced new material
    by_label: dict[str, list[dict]] = {}
    for a in novel:
        by_label.setdefault(_label(a), []).append(a)
    unknown_n = sum(1 for a in novel if not a["actor_label_id"])
    if novel:
        summary = "; ".join(f"{k}: {len(v)}" for k, v in sorted(by_label.items(), key=lambda kv: -len(kv[1]))[:8])
        add("introducers", "Which author labels introduced new material?",
            f"{len(by_label)} author label(s) wrote non-inherited text containing it ({summary}).", "supported",
            [v[0] for v in by_label.values()][:10],
            ["Labels are not verified agents and are never merged.",
             "A label's text may quote or restate someone else's words; authorship of the idea is not established.",
             f"{unknown_n} appearance(s) have an unknown author label."])
    else:
        add("introducers", "Which author labels introduced new material?", "No data.", "unknown")

    # topics the artifact is discussed under (the source's own page classification)
    fam = con.execute(
        "SELECT m.value, count(DISTINCT a.item_id), count(DISTINCT a.actor_label_id) FROM appearance a "
        "JOIN text_item t USING (item_id) JOIN stream_meta m ON m.stream_key = t.stream_key AND m.key = 'page_family' "
        f"WHERE a.artifact_id = ? AND {NOVEL_SQL} GROUP BY 1 ORDER BY 2 DESC",
        [artifact_id],
    ).fetchall()
    if fam:
        top = "; ".join(f"{v} ({n} revisions, {lab} labels)" for v, n, lab in fam[:6])
        add("topics", "Which topics is it discussed under?", f"Pages carrying it fall in {len(fam)} topic group(s): {top}.",
            "supported", [], [("Topic groups are the source's own page classification with its stated method and confidence; "
                               "they are not verified here.")])

    # what labels are doing in the lines where it appears (lexicon cues, not verdicts)
    n_cues = con.execute("SELECT count(*) FROM cue_hit").fetchone()[0]
    if n_cues == 0:
        add("activity", "What are labels doing with it?", "Cue analysis has not been run on this database.", "unknown", [],
            ["Run `backend.analysis.build --steps cues` to enable it."])
    else:
        cues = con.execute(
            f"""
            SELECT h.category, count(*) AS hits, count(DISTINCT a.item_id) AS items, count(DISTINCT a.actor_label_id) AS labels
            FROM appearance a JOIN cue_hit h ON h.item_id = a.item_id AND h.line_no = a.line_no
            WHERE a.artifact_id = ? AND {NOVEL_SQL} GROUP BY 1 ORDER BY 3 DESC, 2 DESC
            """,
            [artifact_id],
        ).fetchall()
        if not cues:
            # weaker evidence: cue words elsewhere in the new text of the same revisions
            wider = con.execute(
                f"""
                SELECT h.category, count(DISTINCT a.item_id), count(DISTINCT a.actor_label_id)
                FROM appearance a JOIN cue_hit h ON h.item_id = a.item_id
                WHERE a.artifact_id = ? AND {NOVEL_SQL} GROUP BY 1 ORDER BY 2 DESC
                """,
                [artifact_id],
            ).fetchall()
            n_items = con.execute(
                f"SELECT count(DISTINCT a.item_id) FROM appearance a WHERE a.artifact_id = ? AND {NOVEL_SQL}", [artifact_id]
            ).fetchone()[0]
            if wider:
                parts = "; ".join(f"{c.replace('_', ' ')}: {n} revision(s)" for c, n, _ in wider[:5])
                add("activity", "What are labels doing with it?",
                    f"No cue word on the same line, but elsewhere in the new text of the {n_items} revision(s) that contain it: "
                    f"{parts}.", "partial", [],
                    ["This is weaker: the cue words are on other lines of the same revision and may be about something else.",
                     "Cues are matched words (config/lexicon.toml), not verdicts."])
            else:
                add("activity", "What are labels doing with it?",
                    "None of the lexicon cue words appear in the new text of the revisions where it is written.", "partial", [],
                    ["The lexicon is a fixed word list (config/lexicon.toml): no hit does not mean no activity."])
        else:
            parts = "; ".join(f"{c.replace('_', ' ')}: {n} revision(s) by {lab} label(s)" for c, _, n, lab in cues[:6])
            cites = []
            for c, *_ in cues[:4]:
                row = con.execute(
                    f"""
                    SELECT h.item_id, t.event_id, h.span_start, h.span_end, substr(t.text, h.span_start + 1, h.span_end - h.span_start)
                    FROM appearance a JOIN cue_hit h ON h.item_id = a.item_id AND h.line_no = a.line_no
                    JOIN text_item t ON t.item_id = h.item_id WHERE a.artifact_id = ? AND {NOVEL_SQL} AND h.category = ?
                    ORDER BY t.time_ts NULLS LAST, h.item_id LIMIT 1
                    """,
                    [artifact_id, c],
                ).fetchone()
                if row:
                    cites.append({"item_id": row[0], "event_id": row[1], "span_start": row[2], "span_end": row[3],
                                  "snippet": row[4]})
            out.append({
                "id": "activity", "question": "What are labels doing with it?",
                "claim": f"Cue words on the lines where it is written: {parts}.", "status": "supported",
                "citations": cites,
                "limitations": [scope, ("Cues are matched words (config/lexicon.toml), not verdicts: 'answer' or 'proxy' on a "
                                 "line does not show what the author did or whether it worked.")],
            })

    # how fast it reached other labels
    firsts = {}
    for a in novel:
        if a["actor_label_id"] and a["actor_label_id"] not in firsts:
            firsts[a["actor_label_id"]] = a
    ordered = sorted(firsts.values(), key=lambda a: (a["time_ts"] is None, a["time_ts"]))
    if len(ordered) >= 2 and ordered[0]["time_ts"] is not None:
        t0 = ordered[0]["time_ts"]
        gaps = [(_label(a), (a["time_ts"] - t0).total_seconds()) for a in ordered[1:6] if a["time_ts"] is not None]

        def fmt(sec):
            return f"{sec / 3600:.1f} h" if sec >= 7200 else f"{sec / 60:.1f} min" if sec >= 120 else f"{sec:.0f} s"

        text = "; ".join(f"{lab} after {fmt(sec)}" for lab, sec in gaps)
        add("spread", "How quickly did it reach other labels?",
            f"First written by {_label(ordered[0])}; next author labels: {text}. {len(ordered)} label(s) in total.",
            "supported", ordered[:4],
            ["Gaps use recorded time, whose uncertainty the source does not give, so the order of close events is not established.",
             "Reaching a second label shows the string was written again, not that it was read from the first."])
    elif novel:
        add("spread", "How quickly did it reach other labels?",
            "Only one author label wrote it in new text, so there is no spread to measure.", "supported", [], [])

    # explicit references from later appearances to earlier appearances' pages or authors
    n_refs = con.execute("SELECT count(*) FROM reference").fetchone()[0]
    if n_refs == 0:
        add("references", "Which later appearances explicitly reference earlier material?",
            "Reference analysis has not been run on this database.", "unknown", [],
            ["Run `backend.analysis.build --steps references` to enable it."])
    elif novel:
        first_item = novel[0]["item_id"]
        earlier_labels = {a["actor_label_id"] for a in novel if a["actor_label_id"]}
        earlier_streams = {a["stream_key"] for a in novel if a["stream_key"]}
        later = [a["item_id"] for a in novel if a["item_id"] != first_item]
        found = []
        if later:
            found = con.execute(
                """
                SELECT r.item_id, t.event_id, r.span_start, r.span_end,
                       substr(t.text, r.span_start + 1, r.span_end - r.span_start), r.ref_type, r.target_text
                FROM reference r JOIN text_item t USING (item_id)
                WHERE r.resolved AND r.item_id IN (SELECT unnest(?::VARCHAR[]))
                  AND ((r.target_kind = 'label' AND r.target_id IN (SELECT unnest(?::VARCHAR[])))
                    OR (r.target_kind = 'page' AND r.target_id IN (SELECT unnest(?::VARCHAR[]))))
                ORDER BY t.time_ts NULLS LAST, r.item_id LIMIT 200
                """,
                [later, sorted(earlier_labels), sorted(earlier_streams)],
            ).fetchall()
        lim = ["Only exact names and links are detected (page and label names that look like handles, wiki links, wiki URLs).",
               "A reference shows the writer knew of the target; it does not show they read it or acted on it.",
               "No hit does not mean no communication."]
        if found:
            items = {r[0] for r in found}
            kinds = sorted({r[5] for r in found})
            add("references", "Which later appearances explicitly reference earlier material?",
                f"{len(items)} later revision(s) containing it also explicitly name or link a label or page that already "
                f"wrote it ({', '.join(kinds)}).", "supported",
                [{"item_id": r[0], "event_id": r[1], "span_start": r[2], "span_end": r[3], "snippet": r[4]} for r in found[:6]],
                lim)
        else:
            add("references", "Which later appearances explicitly reference earlier material?",
                "No later revision containing it explicitly names or links an earlier author label or page.", "partial", [], lim)

    sim = con.execute(
        "SELECT count(*) FROM evidence_edge WHERE artifact_id = ? AND relation = 'possible_reuse'", [artifact_id]
    ).fetchone()[0]
    add("resemble", "Which appearances merely resemble one another?",
        f"{sim} possible_reuse candidate edge(s) recorded." if sim else
        "No similarity candidates were retrieved for this artifact.",
        "partial" if sim else "unknown", [], ["Similarity candidates are not references and never imply causation."])

    # 5. how it changed
    variants = con.execute(
        "SELECT count(DISTINCT substr(t.text, a.span_start + 1, a.span_end - a.span_start)) "
        "FROM appearance a JOIN text_item t USING (item_id) WHERE a.artifact_id = ?",
        [artifact_id],
    ).fetchone()[0]
    modified = sum(1 for a in _appearances(con, artifact_id, novel_only=False) if a["novelty"] == "modified")
    add("changes", "How did the content change?",
        f"{variants} distinct surface form(s) of the identifier; {modified} appearance(s) sit in lines classified "
        "as edits of an earlier line." if variants > 1 or modified else
        "Only one surface form appears and no edited lines contain it.",
        "partial" if variants > 1 or modified else "supported", [], ["Only the identifier is compared, not the surrounding claim."])

    # warnings and corrections are not detected deterministically: abstain
    add("warnings", "Were there warnings or corrections?",
        "No correction detector is run in the deterministic mode.", "unknown", [],
        ["A missing recorded response is not proof a warning was ignored; per-agent read logs are absent."])

    # 9. competing explanations
    carry = full_occ - novel_occ
    expl = [f"{carry} of {full_occ} total occurrences are carried-forward copies in later memories or goals"]
    if novel_labels <= 1:
        expl.append("all non-inherited appearances share one author label")
    if novel_items > 20:
        expl.append(f"the string appears in {novel_items} separate items, so it may be widely shared boilerplate")
    expl.append("common external source, shared prompt or scaffold text, and independent discovery all remain possible")
    add("alternatives", "What competing explanation fits?", "; ".join(expl) + ".", "partial", [],
        ["These are generic alternatives; none is ruled out by the data."])

    # what cannot be reconstructed
    gaps = con.execute(
        "SELECT count(*) FROM (SELECT event_index - lag(event_index) OVER (ORDER BY event_index) AS d FROM event "
        "WHERE event_index IS NOT NULL) WHERE d > 1"
    ).fetchone()[0]
    incomplete = con.execute("SELECT count(*) FROM lineage_summary WHERE lineage_status = 'first_in_stream'").fetchone()[0]
    parts = []
    if gaps:
        parts.append(f"event_index has {gaps} gaps (events missing from the release)")
    if incomplete:
        parts.append(f"{incomplete} text stream(s) start with incomplete lineage (earlier versions are not in the release)")
    parts.append(f"{unknown_n} appearance(s) have no author label")
    parts.append("no read logs show who saw what")
    add("unreconstructable", "What cannot be reconstructed?", "; ".join(parts) + ".", "supported", [], [])
    return out


def verify_citations(con: duckdb.DuckDBPyConnection, answers: list[dict]) -> list[str]:
    """Return a list of problems; empty means every citation resolves to its exact source span."""
    problems = []
    for a in answers:
        for c in a["citations"]:
            row = con.execute("SELECT text FROM text_item WHERE item_id = ?", [c["item_id"]]).fetchone()
            if row is None:
                problems.append(f"{a['id']}: unknown item {c['item_id']}")
            elif row[0][c["span_start"]:c["span_end"]] != c["snippet"]:
                problems.append(f"{a['id']}: span does not match snippet for {c['item_id']}")
    return problems
