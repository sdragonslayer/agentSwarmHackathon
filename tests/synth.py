"""Explicitly synthetic AI Village-shaped data for offline tests. Nothing here comes from the real dataset."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

A1 = "00000000-0000-0000-0000-0000000000a1"
A2 = "00000000-0000-0000-0000-0000000000a2"
H1 = "00000000-0000-0000-0000-0000000000b1"
ROOM = "00000000-0000-0000-0000-0000000000c1"
VILLAGE = "00000000-0000-0000-0000-0000000000d1"

URL = "https://example.test/Path/Case?token=AbC&x=1"
URL_OTHER = "https://example.test/other"


def write_gz(path: Path, rows: list[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def mem_text(*lines: str) -> str:
    return "\n".join(lines)


def build(raw: Path) -> dict:
    """Write a tiny dataset to `raw` and return handy ids/expectations."""
    raw.mkdir(parents=True, exist_ok=True)
    ts = lambda n: f"2026-01-01 00:{n // 60:02d}:{n % 60:02d}.000000"

    agents = [
        {"id": A1, "name": "Alpha", "model_string": "m-a"},
        {"id": A2, "name": "Beta", "model_string": "m-b"},
    ]
    write_gz(raw / "agents.jsonl.gz", agents)

    events, chat = [], []

    def talk(i, idx, agent, text, t, *, with_chat=True):
        mid = f"11111111-0000-0000-0000-{i:012d}"
        events.append({
            "id": f"22222222-0000-0000-0000-{i:012d}", "event_index": idx, "created_at": ts(t), "data": {
                "actionType": "AGENT_TALK", "speakerId": agent, "roomId": ROOM, "content": text, "messageId": mid,
                "cost": 1, "inputTokens": 1, "outputTokens": 1,
            }})
        if with_chat:
            chat.append({
                "id": mid, "agent_speaker_id": agent, "user_speaker_id": None, "speaker_type": "agent",
                "content": text, "room_id": ROOM, "created_at": ts(t)})
        return mid

    talk(1, 10, A1, f"Found a workaround: {URL} works for me. See PR #7.", 5)
    talk(2, 11, A2, f"Trying {URL} now", 9)
    talk(3, 12, A2, f"Unrelated {URL_OTHER}", 11)
    # Human message that exists only in the event stream (no chat_messages row).
    events.append({
        "id": "22222222-0000-0000-0000-000000000099", "event_index": 13, "created_at": ts(20), "data": {
            "actionType": "USER_TALK", "speakerId": H1, "speakerName": "visitor", "speakerType": "HUMAN",
            "roomId": ROOM, "content": "hello there", "messageId": "11111111-0000-0000-0000-000000000099"}})
    events.append({
        "id": "22222222-0000-0000-0000-000000000098", "event_index": 14, "created_at": ts(21), "data": {
            "actionType": "WAIT", "agentId": A1, "cost": 1, "inputTokens": 1, "outputTokens": 1}})
    events.append({
        "id": "22222222-0000-0000-0000-000000000097", "event_index": 15, "created_at": ts(22), "data": {
            "actionType": "STOP_USING_COMPUTER", "agentId": A1, "summary": f"Session wrap-up used {URL}",
            "roomId": ROOM, "cost": 1, "inputTokens": 1, "outputTokens": 1}})
    write_gz(raw / "events.jsonl.gz", events)
    write_gz(raw / "chat_messages.jsonl.gz", chat)

    base = ["# Memory", "Rule: always check the build.", f"Workaround: {URL}", "Short", "Remember PR #7 is merged."]
    mems = [
        {"id": "33333333-0000-0000-0000-000000000001", "agent_id": A1, "created_at": ts(30),
         "content": mem_text(*base)},
        # second memory: carries everything forward, adds one new line, modifies one line
        {"id": "33333333-0000-0000-0000-000000000002", "agent_id": A1, "created_at": ts(40),
         "content": mem_text(base[0], base[1], base[2], base[3], "Remember PR #7 is merged and deployed.",
                             "New insight about caching.")},
        # third memory: drops the workaround line
        {"id": "33333333-0000-0000-0000-000000000003", "agent_id": A1, "created_at": ts(50),
         "content": mem_text(base[0], base[1], "New insight about caching.")},
        # fourth memory: restores the dropped workaround line
        {"id": "33333333-0000-0000-0000-000000000004", "agent_id": A1, "created_at": ts(60),
         "content": mem_text(base[0], base[1], "New insight about caching.", base[2])},
        # another label's first memory: incomplete lineage even though it repeats Alpha's lines
        {"id": "33333333-0000-0000-0000-000000000005", "agent_id": A2, "created_at": ts(45),
         "content": mem_text(base[0], f"Beta saw {URL_OTHER}")},
    ]
    write_gz(raw / "agent_memories.jsonl.gz", mems)
    write_gz(raw / "computer_use_sessions.jsonl.gz", [
        {"id": "44444444-0000-0000-0000-000000000001", "agent_id": A1, "created_at": ts(25),
         "session_goal": f"Goal: verify {URL}"}])
    write_gz(raw / "agent_goals.jsonl.gz", [
        {"id": "55555555-0000-0000-0000-000000000001", "agent_id": A1, "name": "Be useful", "start_time": ts(1)}])
    write_gz(raw / "village_goals.jsonl.gz", [
        {"id": "66666666-0000-0000-0000-000000000001", "goal": "Do a thing", "start_time": ts(0)}])
    write_gz(raw / "summaries.jsonl.gz", [
        {"id": "77777777-0000-0000-0000-000000000001", "type": "daily", "content": f"Summary mentions {URL}",
         "created_at": ts(70)}])
    return {"a1": A1, "a2": A2, "h1": H1, "url": URL, "url_other": URL_OTHER}
