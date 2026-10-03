"""The fixed investigation questionnaire, answered deterministically for one artifact-seeded case.

Each answer is {id, question, claim, status, citations, limitations}. Status is one of supported | partial |
unknown | conflicting. Where the loaded data cannot answer, the answer abstains (`unknown`) and says why.
Citations are exact spans: text_item.text[span_start:span_end] must equal `snippet` (see verify_citations).
"""

from __future__ import annotations

import duckdb

QUESTIONS_VERSION = "questions-0.1"
NOVEL_SQL = "a.novelty IN ('standalone', 'first_observed', 'new', 'modified')"
SCOPE_NOTE = (
    "Scope is the loaded AI Village text tables only; computer_use_turns, claude_code_* and screenshots are not "
    "loaded, and the release has gaps in event_index."
)


def _cite(row: dict) -> dict:
    return {k: row[k] for k in ("item_id", "event_id", "span_start", "span_end", "snippet")}


def _appearances(con: duckdb.DuckDBPyConnection, artifact_id: str, novel_only: bool = True) -> list[dict]:
    cols = ["item_id", "event_id", "actor_label_id", "kind", "time_ts", "event_index", "span_start", "span_end",
            "snippet", "novelty", "display_name"]
    rows = con.execute(
        f"""
        SELECT a.item_id, a.event_id, a.actor_label_id, t.kind, a.time_ts, e.event_index, a.span_start, a.span_end,
               substr(t.text, a.span_start + 1, a.span_end - a.span_start) AS snippet, a.novelty, l.display_name
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
    out: list[dict] = []

    def add(qid, question, claim, status, citations=(), limitations=()):
        out.append({
            "id": qid, "question": question, "claim": claim, "status": status,
            "citations": [_cite(c) for c in citations], "limitations": [SCOPE_NOTE, *limitations],
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

    # 3-4. references and resemblance
    add("references", "Which later appearances explicitly reference earlier material?",
        "No detector for resolvable references between items is implemented, so no reference edges are claimed.",
        "unknown", [], ["Absence of reference edges is not evidence that none exist."])
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

    # 6-8. claims, observation, warnings: not answerable deterministically here
    add("claimed_use", "Did anyone claim to use the information?",
        "Claim detection is not run in the deterministic mode; no self-report is asserted.", "unknown", [],
        ["A self-report would be labeled as such: it does not establish that use happened or succeeded."])
    add("observed_use", "Is use or success independently observed?",
        "Not established: the action/turn tables that could show use are not loaded.", "unknown", [],
        ["Do not infer use from the text appearing in memory or chat."])
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

    # 10. what cannot be reconstructed
    gaps = con.execute(
        "SELECT count(*) FROM (SELECT event_index - lag(event_index) OVER (ORDER BY event_index) AS d FROM event) "
        "WHERE d > 1"
    ).fetchone()[0]
    add("unreconstructable", "What cannot be reconstructed?",
        f"event_index has {gaps} gaps (events missing from the release); {unknown_n} appearance(s) have no author "
        "label; model tool-call output and screenshots are not loaded; no read logs show who saw what.",
        "supported", [], [])
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
