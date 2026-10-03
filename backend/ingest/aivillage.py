"""AI Village adapter: load the published JSONL tables into DuckDB without altering source values.

    uv run python -m backend.ingest.aivillage --raw data/raw/aivillage --db data/derived/swarm.duckdb

Mapping decisions (verified against the real tables, see docs/aivillage_findings.md):
- events.jsonl.gz is the full timeline (actionType in data JSON). chat_messages rows map 1:1 to events through
  data.messageId, so a chat row and its event are one action, never two. Chat text lives in chat_messages.
- created_at strings are naive and agree with the transcript's UTC `Z` times to ~0.25 s, so they are read as UTC.
  The source gives no uncertainty, so time bounds stay NULL.
- Author labels: av:agent:<uuid> (agents table) and av:user:<uuid> (humans). Names are never merged.
- Text we keep: chat, agent memories, computer-use session goals, session summaries, outreach messages, goals,
  and LLM-generated summaries (flagged generated). Raw model `output` blobs stay in the source files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from backend.db import DEFAULT_DB, connect
from backend.ingest.snapshot import IMPORTER_VERSION, sha256_file, utc_now

SOURCE = "aivillage"
TERMS = (
    "AI Village research terms: no training/fine-tuning without written permission, no re-identification, "
    "attribute AI Village, notify on publication. Not for redistribution."
)
FILES = [
    "events.jsonl.gz",
    "chat_messages.jsonl.gz",
    "agent_memories.jsonl.gz",
    "computer_use_sessions.jsonl.gz",
    "agents.jsonl.gz",
    "agent_goals.jsonl.gz",
    "village_goals.jsonl.gz",
    "summaries.jsonl.gz",
]


def _q(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def _src(raw: Path, name: str, columns: dict[str, str]) -> str:
    cols = ", ".join(f"'{k}': '{v}'" for k, v in columns.items())
    return f"read_json('{_q(raw / name)}', format = 'newline_delimited', columns = {{{cols}}})"


def load(raw: Path, db_path: Path = DEFAULT_DB, *, hash_files: bool = True) -> dict[str, int]:
    """Rebuild the AI Village ingest tables from `raw`. Derived tables for this source are cleared."""
    missing = [f for f in FILES if not (raw / f).exists()]
    if missing:
        raise FileNotFoundError(f"missing AI Village files in {raw}: {missing}")
    con = connect(db_path)
    _clear(con)
    files = []
    for f in FILES:
        rec = {"name": f, "bytes": (raw / f).stat().st_size}
        if hash_files:
            rec["sha256_compressed"] = sha256_file(raw / f)
        files.append(rec)
    snap = f"av:{utc_now()}"
    notes = (
        "Local download of aidigestorg/ai-village text tables. Not loaded: computer_use_turns, claude_code_*, "
        "screenshots. event_index has gaps (events missing from the release). Times are DB created_at (UTC)."
    )
    con.execute(
        "INSERT INTO snapshot VALUES (?, ?, ?, ?, ?, ?, ?)",
        [snap, SOURCE, utc_now(), IMPORTER_VERSION, json.dumps(files), TERMS, notes],
    )
    _load_events(con, raw, snap)
    _load_actors(con, raw, snap)
    _load_items(con, raw, snap)
    return counts(con)


def _clear(con: duckdb.DuckDBPyConnection) -> None:
    for t in (
        "review", "evidence_edge", "artifact_counts", "appearance", "artifact", "lineage_summary", "text_change",
        "text_item", "event", "actor_label_name", "actor_label", "snapshot",
    ):
        con.execute(f"DELETE FROM {t}")


def _load_events(con: duckdb.DuckDBPyConnection, raw: Path, snap: str) -> None:
    src = _src(
        raw,
        "events.jsonl.gz",
        {"id": "VARCHAR", "event_index": "BIGINT", "data": "JSON", "created_at": "VARCHAR"},
    )
    con.execute(
        f"""
        INSERT INTO event
        SELECT
            'av:ev:' || id, ?, event_index, data->>'actionType',
            CASE data->>'actionType'
                WHEN 'AGENT_TALK' THEN 'av:agent:' || (data->>'speakerId')
                WHEN 'USER_TALK' THEN 'av:user:' || (data->>'speakerId')
                WHEN 'USER_NAME_CHANGE' THEN 'av:user:' || (data->>'userId')
                ELSE 'av:agent:' || (data->>'agentId')
            END,
            'av:room:' || (data->>'roomId'),
            'av:cus:' || (data->>'computerUseSessionId'),
            created_at, try_cast(created_at AS TIMESTAMP), 'db_created_at_utc_naive', NULL, NULL,
            try_cast(data->>'inputTokens' AS BIGINT), try_cast(data->>'outputTokens' AS BIGINT),
            try_cast(data->>'cost' AS BIGINT), 'events.jsonl.gz', id
        FROM {src}
        """,
        [snap],
    )
    # 'av:agent:' || NULL is NULL, but make the intent explicit: unknown actor stays NULL.
    con.execute("UPDATE event SET actor_label_id = NULL WHERE actor_label_id IN ('av:agent:', 'av:user:')")


def _load_actors(con: duckdb.DuckDBPyConnection, raw: Path, snap: str) -> None:
    agents = _src(
        raw, "agents.jsonl.gz", {"id": "VARCHAR", "name": "VARCHAR", "model_string": "VARCHAR"}
    )
    con.execute(
        f"""
        INSERT INTO actor_label
        SELECT 'av:agent:' || a.id, ?, 'agent', a.name, a.model_string, min(e.time_ts), max(e.time_ts),
               'unverified_label'
        FROM {agents} a LEFT JOIN event e ON e.actor_label_id = 'av:agent:' || a.id
        GROUP BY a.id, a.name, a.model_string
        """,
        [snap],
    )
    events = _src(
        raw,
        "events.jsonl.gz",
        {"id": "VARCHAR", "data": "JSON", "created_at": "VARCHAR"},
    )
    con.execute(
        f"""
        CREATE TEMP TABLE human_names AS
        SELECT 'av:user:' || (data->>'speakerId') AS label_id, data->>'speakerName' AS name,
               try_cast(created_at AS TIMESTAMP) AS ts
        FROM {events} WHERE data->>'actionType' = 'USER_TALK' AND (data->>'speakerName') <> ''
        UNION ALL
        SELECT 'av:user:' || (data->>'userId'), data->>'newName', try_cast(created_at AS TIMESTAMP)
        FROM {events} WHERE data->>'actionType' = 'USER_NAME_CHANGE' AND (data->>'newName') <> ''
        """
    )
    con.execute(
        """
        INSERT INTO actor_label
        SELECT label_id, ?, 'human', arg_max(name, ts), NULL, min(ts), max(ts), 'unverified_label'
        FROM human_names WHERE label_id <> 'av:user:' GROUP BY label_id
        """,
        [snap],
    )
    # Humans who only appear as chat speakers or in events with no recorded name keep an unknown (NULL) name.
    con.execute(
        """
        INSERT INTO actor_label
        SELECT DISTINCT e.actor_label_id, ?, 'human', NULL, NULL, NULL, NULL, 'unverified_label'
        FROM event e
        WHERE e.actor_label_id LIKE 'av:user:%' AND e.actor_label_id NOT IN (SELECT label_id FROM actor_label)
        """,
        [snap],
    )
    con.execute(
        """
        INSERT INTO actor_label_name
        SELECT label_id, name, min(ts), max(ts), count(*) FROM human_names GROUP BY label_id, name
        """
    )
    con.execute(
        "INSERT INTO actor_label_name SELECT label_id, display_name, first_seen, last_seen, NULL "
        "FROM actor_label WHERE kind = 'agent' AND display_name IS NOT NULL"
    )


def _load_items(con: duckdb.DuckDBPyConnection, raw: Path, snap: str) -> None:
    def insert(select: str, params: list | None = None) -> None:
        con.execute(
            f"""
            INSERT INTO text_item
            SELECT item_id, ?, kind, actor, event_id, room_id, session_id, source_time, try_cast(source_time AS TIMESTAMP),
                   text, sha256(text), length(text), generated, stream_key, source_file, source_table, source_id
            FROM ({select}) AS t(item_id, kind, actor, event_id, room_id, session_id, source_time, text, generated,
                                 stream_key, source_file, source_table, source_id)
            """,
            [snap, *(params or [])],
        )

    events = _src(raw, "events.jsonl.gz", {"id": "VARCHAR", "data": "JSON", "created_at": "VARCHAR"})
    chat = _src(
        raw,
        "chat_messages.jsonl.gz",
        {
            "id": "VARCHAR", "agent_speaker_id": "VARCHAR", "user_speaker_id": "VARCHAR",
            "speaker_type": "VARCHAR", "content": "VARCHAR", "room_id": "VARCHAR", "created_at": "VARCHAR",
        },
    )
    con.execute(
        f"CREATE TEMP TABLE msg_event AS SELECT data->>'messageId' AS message_id, 'av:ev:' || id AS event_id "
        f"FROM {events} WHERE (data->>'messageId') IS NOT NULL"
    )
    # Chat: one item per chat_messages row, linked to its single event.
    insert(
        f"""
        SELECT 'av:chat:' || c.id AS item_id,
               CASE c.speaker_type WHEN 'agent' THEN 'chat_agent' ELSE 'chat_human' END AS kind,
               CASE WHEN c.agent_speaker_id IS NOT NULL THEN 'av:agent:' || c.agent_speaker_id
                    WHEN c.user_speaker_id IS NOT NULL THEN 'av:user:' || c.user_speaker_id END AS actor,
               m.event_id, 'av:room:' || c.room_id AS room_id, NULL AS session_id, c.created_at AS source_time,
               c.content AS text, FALSE AS generated, NULL AS stream_key,
               'chat_messages.jsonl.gz' AS source_file, 'chat_messages' AS source_table, c.id AS source_id
        FROM {chat} c LEFT JOIN msg_event m ON m.message_id = c.id WHERE c.content IS NOT NULL
        """
    )
    # Human talk events with no chat_messages row: the text exists only in the event.
    insert(
        f"""
        SELECT 'av:evtalk:' || e.id, 'chat_human', 'av:user:' || (e.data->>'speakerId'), 'av:ev:' || e.id,
               'av:room:' || (e.data->>'roomId'), NULL, e.created_at, e.data->>'content', FALSE, NULL,
               'events.jsonl.gz', 'events', e.id
        FROM {events} e
        WHERE e.data->>'actionType' = 'USER_TALK' AND (e.data->>'content') IS NOT NULL
          AND (e.data->>'messageId') NOT IN (SELECT id FROM {chat})
        """
    )
    # Agent memories, one stream per label: later memories carry earlier text forward.
    mem = _src(
        raw,
        "agent_memories.jsonl.gz",
        {"id": "VARCHAR", "agent_id": "VARCHAR", "content": "VARCHAR", "created_at": "VARCHAR"},
    )
    insert(
        f"""
        SELECT 'av:mem:' || id, 'memory', 'av:agent:' || agent_id, NULL, NULL, NULL, created_at, content, FALSE,
               'mem:' || agent_id, 'agent_memories.jsonl.gz', 'agent_memories', id
        FROM {mem} WHERE content IS NOT NULL
        """
    )
    cus = _src(
        raw,
        "computer_use_sessions.jsonl.gz",
        {"id": "VARCHAR", "agent_id": "VARCHAR", "created_at": "VARCHAR", "session_goal": "VARCHAR"},
    )
    insert(
        f"""
        SELECT 'av:sgoal:' || id, 'session_goal', 'av:agent:' || agent_id, NULL, NULL, 'av:cus:' || id, created_at,
               session_goal, FALSE, 'sgoal:' || agent_id, 'computer_use_sessions.jsonl.gz', 'computer_use_sessions', id
        FROM {cus} WHERE session_goal IS NOT NULL
        """
    )
    for kind, action, field, prefix in (
        ("computer_session_summary", "STOP_USING_COMPUTER", "summary", "av:stopsum:"),
        ("human_session_summary", "STOP_HUMAN_USE_SESSION", "summary", "av:humsum:"),
        ("outreach_message", "OUTREACH_APPROVAL_REQUEST", "messageContent", "av:outreach:"),
    ):
        insert(
            f"""
            SELECT '{prefix}' || id, '{kind}', 'av:agent:' || (data->>'agentId'), 'av:ev:' || id,
                   'av:room:' || (data->>'roomId'), 'av:cus:' || (data->>'computerUseSessionId'), created_at,
                   data->>'{field}', FALSE, NULL, 'events.jsonl.gz', 'events', id
            FROM {events} WHERE data->>'actionType' = '{action}' AND (data->>'{field}') IS NOT NULL
            """
        )
    summaries = _src(
        raw,
        "summaries.jsonl.gz",
        {"id": "VARCHAR", "type": "VARCHAR", "content": "VARCHAR", "created_at": "VARCHAR"},
    )
    insert(
        f"""
        SELECT 'av:summary:' || id, 'generated_summary', NULL, NULL, NULL, NULL, created_at, content, TRUE, NULL,
               'summaries.jsonl.gz', 'summaries', id
        FROM {summaries} WHERE content IS NOT NULL
        """
    )
    vgoals = _src(
        raw,
        "village_goals.jsonl.gz",
        {"id": "VARCHAR", "goal": "VARCHAR", "start_time": "VARCHAR"},
    )
    insert(
        f"""
        SELECT 'av:vgoal:' || id, 'village_goal', NULL, NULL, NULL, NULL, start_time, goal, FALSE, NULL,
               'village_goals.jsonl.gz', 'village_goals', id
        FROM {vgoals} WHERE goal IS NOT NULL
        """
    )
    agoals = _src(
        raw,
        "agent_goals.jsonl.gz",
        {"id": "VARCHAR", "agent_id": "VARCHAR", "name": "VARCHAR", "start_time": "VARCHAR"},
    )
    insert(
        f"""
        SELECT 'av:agoal:' || id, 'agent_goal', 'av:agent:' || agent_id, NULL, NULL, NULL, start_time, name, FALSE,
               NULL, 'agent_goals.jsonl.gz', 'agent_goals', id
        FROM {agoals} WHERE name IS NOT NULL
        """
    )


def counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    out = {}
    for t in ("event", "text_item", "actor_label"):
        out[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    for kind, n in con.execute("SELECT kind, count(*) FROM text_item GROUP BY 1 ORDER BY 2 DESC").fetchall():
        out[f"text_item:{kind}"] = n
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", type=Path, default=Path("data/raw/aivillage"))
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--no-hash", action="store_true", help="skip SHA-256 of the large source files")
    args = ap.parse_args()
    for k, v in load(args.raw, args.db, hash_files=not args.no_hash).items():
        print(f"{k:40} {v:>10,}")


if __name__ == "__main__":
    main()
