"""Persist chat sessions for sidebar history."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import CONFIG_DIR
from .providers import ChatMessage, ImageAttachment, TokenUsage

SESSIONS_DIR = CONFIG_DIR / "sessions"
PROJECTS_FILE = CONFIG_DIR / "projects.json"
DEFAULT_PROJECT = "Umum"


@dataclass
class ChatSession:
    id: str
    title: str
    updated_at: str
    messages: list[ChatMessage] = field(default_factory=list)
    title_is_custom: bool = False
    project: str = DEFAULT_PROJECT

    @classmethod
    def new(cls, project: str = DEFAULT_PROJECT) -> ChatSession:
        now = datetime.now().isoformat(timespec="seconds")
        return cls(
            id=uuid.uuid4().hex[:12],
            title="Chat baru",
            updated_at=now,
            project=normalize_project_name(project),
        )

    def touch(
        self,
        title: str | None = None,
        *,
        manual_title: bool = False,
        reset_title: bool = False,
    ) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        # Keep a user-renamed title when the first message is edited later.
        if title and (manual_title or reset_title or not self.title_is_custom):
            self.title = title
        if manual_title:
            self.title_is_custom = True
        elif reset_title:
            self.title_is_custom = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "title_is_custom": self.title_is_custom,
            "updated_at": self.updated_at,
            "project": self.project,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "images": [
                        {"name": image.name, "mime_type": image.mime_type, "data": image.data}
                        for image in m.images
                    ],
                    "token_usage": (
                        {
                            "input_tokens": m.token_usage.input_tokens,
                            "output_tokens": m.token_usage.output_tokens,
                            "total_tokens": m.token_usage.total_tokens,
                            "estimated": m.token_usage.estimated,
                        }
                        if m.token_usage
                        else None
                    ),
                }
                for m in self.messages
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChatSession:
        messages = [
            ChatMessage(
                role=str(m["role"]),
                content=str(m["content"]),
                images=[
                    ImageAttachment(
                        name=str(image.get("name", "gambar")),
                        mime_type=str(image.get("mime_type", "application/octet-stream")),
                        data=str(image.get("data", "")),
                    )
                    for image in m.get("images", [])
                    if isinstance(image, dict) and image.get("data")
                ],
                token_usage=(
                    TokenUsage(
                        input_tokens=int(m["token_usage"].get("input_tokens", 0)),
                        output_tokens=int(m["token_usage"].get("output_tokens", 0)),
                        total_tokens=int(m["token_usage"].get("total_tokens", 0)),
                        estimated=bool(m["token_usage"].get("estimated", False)),
                    )
                    if isinstance(m.get("token_usage"), dict)
                    else None
                ),
            )
            for m in data.get("messages", [])
            if isinstance(m, dict) and "role" in m and "content" in m
        ]
        return cls(
            id=str(data.get("id", uuid.uuid4().hex[:12])),
            title=str(data.get("title", "Chat")),
            title_is_custom=bool(data.get("title_is_custom", False)),
            updated_at=str(data.get("updated_at", datetime.now().isoformat(timespec="seconds"))),
            project=normalize_project_name(str(data.get("project", DEFAULT_PROJECT))),
            messages=messages,
        )


def normalize_project_name(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    return cleaned[:60] or DEFAULT_PROJECT


def list_projects() -> list[str]:
    projects = [DEFAULT_PROJECT]
    if PROJECTS_FILE.exists():
        try:
            with PROJECTS_FILE.open(encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                projects.extend(str(name) for name in data)
        except (json.JSONDecodeError, OSError):
            pass
    if SESSIONS_DIR.exists():
        projects.extend(session.project for session in list_sessions())

    unique: list[str] = []
    seen: set[str] = set()
    for name in projects:
        normalized = normalize_project_name(name)
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def create_project(name: str) -> str:
    normalized = normalize_project_name(name)
    projects = list_projects()
    existing = next(
        (project for project in projects if project.casefold() == normalized.casefold()),
        None,
    )
    if existing:
        return existing
    projects.append(normalized)
    _save_projects(projects)
    return normalized


def rename_project(old_name: str, new_name: str) -> str:
    """Rename a project and update every session assigned to it."""
    projects = list_projects()
    old_project = next(
        (project for project in projects if project.casefold() == old_name.casefold()),
        None,
    )
    if old_project is None:
        raise ValueError(f"Project tidak ditemukan: {old_name}")
    if old_project.casefold() == DEFAULT_PROJECT.casefold():
        raise ValueError(f"Project {DEFAULT_PROJECT} tidak dapat diganti namanya.")

    normalized = normalize_project_name(new_name)
    collision = next(
        (
            project
            for project in projects
            if project.casefold() == normalized.casefold() and project != old_project
        ),
        None,
    )
    if collision:
        raise ValueError(f"Nama Project sudah digunakan: {collision}")
    if normalized.casefold() == DEFAULT_PROJECT.casefold():
        raise ValueError(f"Nama {DEFAULT_PROJECT} dikhususkan untuk chat tanpa Project.")

    for session in list_sessions():
        if session.project.casefold() == old_project.casefold():
            session.project = normalized
            save_session(session)
    _save_projects([normalized if project == old_project else project for project in projects])
    return normalized


def delete_project(name: str) -> int:
    """Delete a project and all sessions contained in it."""
    projects = list_projects()
    project = next(
        (item for item in projects if item.casefold() == name.casefold()),
        None,
    )
    if project is None:
        raise ValueError(f"Project tidak ditemukan: {name}")
    if project.casefold() == DEFAULT_PROJECT.casefold():
        raise ValueError(f"Project {DEFAULT_PROJECT} tidak dapat dihapus.")

    deleted = 0
    for session in list_sessions():
        if session.project.casefold() == project.casefold():
            delete_session(session.id)
            deleted += 1
    _save_projects([item for item in projects if item != project])
    return deleted


def _save_projects(projects: list[str]) -> None:
    PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with PROJECTS_FILE.open("w", encoding="utf-8") as f:
        json.dump(projects, f, indent=2, ensure_ascii=False)


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
