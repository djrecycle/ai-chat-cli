"""Small terminal-native file browser for selecting chat documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FileBrowserEntry:
    path: Path
    is_dir: bool

    @property
    def label(self) -> str:
        suffix = "/" if self.is_dir else ""
        return f"{self.path.name}{suffix}"


@dataclass
class FileBrowserState:
    cwd: Path = field(default_factory=Path.home)
    filter_text: str = ""

    def __post_init__(self) -> None:
        self.cwd = self.cwd.expanduser().resolve()

    def entries(self) -> list[FileBrowserEntry]:
        try:
            children = list(self.cwd.iterdir())
        except OSError:
            children = []

        filter_text = self.filter_text.lower().strip()
        visible = [
            child
            for child in children
            if child.name != "."
            and (not child.name.startswith(".") or filter_text.startswith("."))
            and (not filter_text or filter_text in child.name.lower())
        ]
        visible.sort(key=lambda path: (not path.is_dir(), path.name.lower()))
        return [FileBrowserEntry(path=path, is_dir=path.is_dir()) for path in visible]


def render_browser_lines(state: FileBrowserState, *, limit: int = 24) -> list[str]:
    lines = [
        "File browser",
        f"Folder: {state.cwd}",
        f"Filter: {state.filter_text or '-'}",
        "",
        "Ketik nomor untuk buka/pilih. Command: .. naik, /teks filter, / clear, q batal.",
        "",
        "  0  ../",
    ]

    entries = state.entries()
    for index, entry in enumerate(entries[:limit], start=1):
        icon = "[D]" if entry.is_dir else "[F]"
        lines.append(f"{index:>3}  {icon} {entry.label}")

    remaining = len(entries) - limit
    if remaining > 0:
        lines.append(f"... {remaining} item lain disembunyikan, pakai filter untuk mempersempit.")
    if not entries:
        lines.append("(kosong)")

    return lines


def handle_browser_input(state: FileBrowserState, text: str) -> tuple[Path | None, str | None]:
    value = text.strip()
    if not value:
        return None, None
    if value.lower() in ("q", "quit", "cancel", "batal"):
        return None, "cancel"
    if value == ".." or value == "0":
        state.cwd = state.cwd.parent
        return None, None
    if value.startswith("/"):
        state.filter_text = value[1:].strip()
        return None, None

    entries = state.entries()
    selected: FileBrowserEntry | None = None
    if value.isdigit():
        index = int(value)
        if 1 <= index <= len(entries):
            selected = entries[index - 1]
    else:
        candidate = (state.cwd / value).expanduser()
        if candidate.exists():
            selected = FileBrowserEntry(path=candidate, is_dir=candidate.is_dir())

    if selected is None:
        return None, "Pilihan tidak ditemukan."

    if selected.is_dir:
        state.cwd = selected.path.resolve()
        state.filter_text = ""
        return None, None

    return selected.path.resolve(), None
