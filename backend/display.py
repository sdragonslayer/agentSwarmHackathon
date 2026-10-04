"""Display names for sources and text streams. Anything not listed falls back to the raw identifier."""

from __future__ import annotations

SOURCE_LABELS = {"aivillage": "AI Village", "wiki": "German message board (collusion.wiki)"}
# stream_key prefix -> what one stream is
STREAM_LABELS = {"mem": "Agent memories", "sgoal": "Session goals", "page": "Wiki page revisions"}


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


def stream_label(prefix: str) -> str:
    return STREAM_LABELS.get(prefix, prefix)
