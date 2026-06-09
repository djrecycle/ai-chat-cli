"""Persist chat sessions for sidebar history."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import CONFIG_DIR
from .providers import ChatMessage

SESSIONS_DIR = CONFIG_DIR / "sessions"


@dataclass
class ChatSession:
    id: str
    title: str
    updated_at: str
    messages: list[ChatMessage] = field(default_factory=list)

    @classmethod
    def new(cls) -> ChatSession:
        now = datetime.now().isoformat(timespec="seconds")
        return cls(id=uuid.uuid4().hex[:12], title="Chat baru", updated_at=now)

    def touch(self, title: str | None = None) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        if title:
            self.title = title

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "updated_at": self.updated_at,
            "messages": [{"role": m.role, "content": m.content} for m in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChatSession:
        messages = [
            ChatMessage(role=str(m["role"]), content=str(m["content"]))
            for m in data.get("messages", [])
            if isinstance(m, dict) and "role" in m and "content" in m
        ]
        return cls(
            id=str(data.get("id", uuid.uuid4().hex[:12])),
            title=str(data.get("title", "Chat")),
            updated_at=str(data.get("updated_at", datetime.now().isoformat(timespec="seconds"))),
            messages=messages,
        )


def _session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def list_sessions() -> list[ChatSession]:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sessions: list[ChatSession] = []
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                sessions.append(ChatSession.from_dict(data))
        except (json.JSONDecodeError, OSError, KeyError):
            continue
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return sessions


def load_session(session_id: str) -> ChatSession | None:
    path = _session_path(session_id)
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return None
    return ChatSession.from_dict(data)


def save_session(session: ChatSession) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with _session_path(session.id).open("w", encoding="utf-8") as f:
        json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)


def delete_session(session_id: str) -> None:
    path = _session_path(session_id)
    if path.exists():
        path.unlink()


def title_from_message(text: str, limit: int = 36) -> str:
    one_line = " ".join(text.strip().split())
    if len(one_line) <= limit:
        return one_line or "Chat baru"
    return one_line[: limit - 1] + "…"
