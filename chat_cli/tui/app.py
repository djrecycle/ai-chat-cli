"""Clickable full-screen chat UI."""

from __future__ import annotations

import asyncio
import re
import shlex
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from textwrap import shorten, wrap

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.clipboard import ClipboardData
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.auto_suggest import load_auto_suggest_bindings
from prompt_toolkit.key_binding.key_bindings import merge_key_bindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, ScrollablePane, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.widgets import TextArea

from ..clipboard_util import copy_to_system_clipboard
from ..config import (
    ACCENT_COLORS,
    SUPPORTED_THEMES,
    AppConfig,
    DEFAULT_SYSTEM_PROMPT,
    PROVIDER_HELP_TEXT,
    normalize_accent,
    normalize_theme,
    resolve_accent_color,
    save_config,
)
from ..document_loader import (
    IMAGE_EXTENSIONS,
    DocumentLoadError,
    build_document_prompt,
    build_image_message,
    load_document,
)
from ..history_store import (
    ChatSession,
    MAX_PROJECT_REFERENCES,
    MAX_PROJECT_REFERENCE_CHARS,
    add_project_reference,
    compose_project_system_prompt,
    create_project,
    delete_project,
    delete_session,
    get_project_settings,
    list_projects,
    list_sessions,
    load_session,
    remove_project_reference,
    rename_project,
    save_session,
    set_project_system_prompt,
    title_from_message,
)
from ..providers import ChatMessage, DeepSeekProvider, GeminiProvider, LocalAIProvider, OllamaProvider, OpenAIProvider, estimate_token_usage
from ..providers.base import ChatProvider
from ..suggestions import ChatAutoSuggest
from ..system_monitor import ProcessResourceMonitor, ResourceStats
from ..terminal_file_browser import FileBrowserState, handle_browser_input
from ..ui import (
    sanitize_assistant_output,
    sanitize_visible_thinking,
    split_think_sections,
    strip_think_tags,
    with_response_format_prompt,
    with_visible_thinking_prompt,
)


TUI_LOGO = [
    " ____       _   ____ _           _      _    ___",
    "|  _ \\     | | / ___| |__   __ _| |_   / \\  |_ _|",
    "| | | | _  | || |   | '_ \\ / _` | __| / _ \\  | |",
    "| |_| || |_| || |___| | | | (_| | |_ / ___ \\ | |",
    "|____/  \\___/  \\____|_| |_|\\__,_|\\__/_/   \\_\\___|",
]

THEME_PALETTES = {
    "dark": {
        "bg": "#0b1120",
        "panel": "#111827",
        "bar": "#0f172a",
        "surface": "#1f2937",
        "border": "#374151",
        "code_border": "#4b5563",
        "text": "#d1d5db",
        "bright": "#f3f4f6",
        "muted": "#9ca3af",
        "secondary": "#5eead4",
        "blue": "#93c5fd",
        "danger": "#fca5a5",
        "thinking_body": "#fde68a",
    },
    "midnight": {
        "bg": "#080b18",
        "panel": "#10162a",
        "bar": "#0b1020",
        "surface": "#17213a",
        "border": "#2a3b5f",
        "code_border": "#42567d",
        "text": "#d8e2ff",
        "bright": "#f2f5ff",
        "muted": "#8492b5",
        "secondary": "#7dd3fc",
        "blue": "#93c5fd",
        "danger": "#fda4af",
        "thinking_body": "#fde68a",
    },
    "forest": {
        "bg": "#07130f",
        "panel": "#0d1f18",
        "bar": "#0a1914",
        "surface": "#163126",
        "border": "#2e5142",
        "code_border": "#466b5a",
        "text": "#d7e8df",
        "bright": "#f0faf5",
        "muted": "#86a394",
        "secondary": "#6ee7b7",
        "blue": "#93c5fd",
        "danger": "#fca5a5",
        "thinking_body": "#fde68a",
    },
    "light": {
        "bg": "#f8fafc",
        "panel": "#eef2f7",
        "bar": "#e2e8f0",
        "surface": "#d8e1ec",
        "border": "#94a3b8",
        "code_border": "#64748b",
        "text": "#334155",
        "bright": "#0f172a",
        "muted": "#64748b",
        "secondary": "#0f766e",
        "blue": "#2563eb",
        "danger": "#b91c1c",
        "thinking_body": "#92400e",
    },
}

LIGHT_ACCENT_COLORS = {
    "amber": "#b45309",
    "cyan": "#0e7490",
    "green": "#15803d",
    "blue": "#1d4ed8",
    "purple": "#7e22ce",
    "pink": "#be185d",
    "red": "#b91c1c",
}


class TuiChatApp:
    """Interactive terminal app with mouse-aware message actions."""

    
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.provider = self._make_provider()
        self.sessions: list[ChatSession] = list_sessions()
        self.session = self.sessions[0] if self.sessions else ChatSession.new()
        if not self.sessions:
            save_session(self.session)
            self.sessions = [self.session]
        self.projects = list_projects()
        self.active_project = self.session.project
        self.expanded_projects: set[str] = {self.active_project}

        self.selected_message_index: int | None = None
        self.editing_message_index: int | None = None
        self.status = "Fitur baru: /rename untuk mengganti judul chat. Ketik /help untuk detail."
        self.hover_hint: str | None = None
        self.mouse_enabled = True
        self.streaming = False
        self._stream_task: asyncio.Task[None] | None = None
        self.models: list[str] = []
        self.models_error: str | None = None
        self._chat_line_count = 1
        self._scroll_to_bottom_pending = True
        self.file_browser: FileBrowserState | None = None
        self.file_browser_mode = "chat"
        self.file_browser_question_parts: list[str] = []
        self.expanded_thinking_indices: set[int] = set()
        self.resource_monitor = ProcessResourceMonitor()
        self.resource_stats = ResourceStats()

        self.input = TextArea(
            height=4,
            prompt=[("class:input.prompt", " Tulis > ")],
            multiline=True,
            auto_suggest=ChatAutoSuggest(),
            history=FileHistory(str(self._input_history_path())),
            wrap_lines=True,
            focus_on_click=True,
            style="class:input",
        )
        self.input.buffer.accept_handler = self._accept_input

        self.header_control = FormattedTextControl(self._render_header)
        self.header_window = Window(
            self.header_control,
            height=D(min=1, max=3),
            wrap_lines=True,
            always_hide_cursor=True,
            style="class:header",
        )
        self.sidebar_control = FormattedTextControl(self._render_sidebar, focusable=True)
        self.chat_control = FormattedTextControl(self._render_chat, focusable=True)
        self.toolbar_control = FormattedTextControl(self._render_toolbar, focusable=True)
        self.status_control = FormattedTextControl(self._render_status)
        self.status_window = Window(
            self.status_control,
            height=D(min=1, max=2),
            wrap_lines=True,
            always_hide_cursor=True,
            style="class:statusbar",
        )
        self.chat_window = Window(
            self.chat_control,
            wrap_lines=True,
            always_hide_cursor=True,
            style="class:chat",
        )
        self.chat_pane = ScrollablePane(
            self.chat_window,
            show_scrollbar=True,
            display_arrows=False,
            keep_cursor_visible=False,
            keep_focused_window_visible=False,
        )

        body = VSplit(
            [
                ConditionalContainer(
                    Window(
                        self.sidebar_control,
                        width=D(preferred=30, min=24, max=36),
                        wrap_lines=False,
                        style="class:sidebar",
                    ),
                    filter=Condition(lambda: self.mouse_enabled),
                ),
                ConditionalContainer(
                    Window(width=1, char="│", style="class:divider"),
                    filter=Condition(lambda: self.mouse_enabled),
                ),
                HSplit(
                    [
                        self.header_window,
                        Window(height=1, char="─", style="class:divider"),
                        self.chat_pane,
                        Window(height=1, char=" ", style="class:divider"),
                        Window(height=1, char="─", style="class:divider"),
                        Window(self.toolbar_control, height=1, style="class:toolbar"),
                        self.input,
                        self.status_window,
                    ]
                ),
            ]
        )

        self._render_cache: dict[tuple, list[tuple]] = {}

        self.app = Application(
            layout=Layout(body, focused_element=self.input),
            key_bindings=merge_key_bindings(
                [self._key_bindings(), load_auto_suggest_bindings()]
            ),
            mouse_support=Condition(lambda: self.mouse_enabled),
            full_screen=True,
            style=self._style(),
        )

    def _make_provider(self) -> ChatProvider:
        if self.cfg.provider == "deepseek":
            return DeepSeekProvider(self.cfg.deepseek_base_url, self.cfg.deepseek_api_key)
        if self.cfg.provider == "gemini":
            return GeminiProvider(self.cfg.gemini_base_url, self.cfg.gemini_api_key)
        if self.cfg.provider == "openai":
            return OpenAIProvider(self.cfg.openai_base_url, self.cfg.openai_api_key)
        if self.cfg.provider == "localai":
            return LocalAIProvider(self.cfg.localai_base_url, self.cfg.localai_api_key)
        return OllamaProvider(self.cfg.ollama_base_url)

    def _style(self):
        from prompt_toolkit.styles import Style

        theme = normalize_theme(self.cfg.theme)
        palette = THEME_PALETTES[theme]
        accent = (
            LIGHT_ACCENT_COLORS.get(self.cfg.accent, resolve_accent_color(self.cfg.accent))
            if theme == "light"
            else resolve_accent_color(self.cfg.accent)
        )
        bg = palette["bg"]
        panel = palette["panel"]
        bar = palette["bar"]
        surface = palette["surface"]
        border = palette["border"]
        code_border = palette["code_border"]
        text = palette["text"]
        bright = palette["bright"]
        muted = palette["muted"]
        secondary = palette["secondary"]
        blue = palette["blue"]
        danger = palette["danger"]
        thinking_body = palette["thinking_body"]

        return Style.from_dict(
            {
                "sidebar": f"bg:{panel} {text}",
                "sidebar.title": f"bold {accent}",
                "sidebar.section": f"bold {secondary}",
                "sidebar.item": text,
                "sidebar.active": f"bg:{surface} {accent} bold",
                "sidebar.model": blue,
                "sidebar.model.active": f"bg:{surface} {secondary} bold",
                "sidebar.meta": muted,
                "divider": border,
                "header": f"bg:{bar} {text}",
                "header.title": f"bold {accent}",
                "header.meta": muted,
                "header.value": f"bold {secondary}",
                "chat": f"bg:{bg} {text}",
                "message.user": bright,
                "message.assistant": text,
                "message.assistant.dim": muted,
                "message.thinking": f"italic {accent}",
                "thinking.border": accent,
                "thinking.title": f"bold {accent}",
                "thinking.body": f"italic {thinking_body}",
                "thinking.separator": border,
                "answer.title": f"bold {secondary}",
                "answer.border": secondary,
                "answer.separator": border,
                "answer.meta": muted,
                "message.selected": f"bg:{surface} {bright} bold",
                "message.meta": muted,
                "message.label.user": f"bold {blue}",
                "message.label.assistant": f"bold {secondary}",
                "message.label.edit": f"bold {accent}",
                "welcome.logo": f"bold {accent}",
                "welcome.title": f"bold {secondary}",
                "welcome.text": text,
                "welcome.key": f"{blue} bold",
                "welcome.command": f"{accent} bold",
                "welcome.rule": border,
                "markdown.heading": f"bold {accent}",
                "markdown.list": text,
                "markdown.list.marker": f"bold {secondary}",
                "markdown.quote": f"italic {muted}",
                "markdown.code": f"bg:{panel} {text}",
                "markdown.code.border": f"bg:{panel} {code_border}",
                "markdown.code.lang": f"bg:{surface} {secondary} bold",
                "markdown.inline_code": f"bg:{panel} {accent}",
                "markdown.bold": f"bold {bright}",
                "markdown.table": f"bg:{panel} {text}",
                "markdown.table.border": f"bg:{panel} {code_border}",
                "markdown.table.header": f"bg:{surface} {accent} bold",
                "toolbar": f"bg:{bar} {text}",
                "button": f"bg:{surface} {text}",
                "button.hot": f"bg:{surface} {accent} bold",
                "button.danger": f"bg:{surface} {danger} bold",
                "statusbar": f"bg:{panel} {text}",
                "status.mode": f"bold {secondary}",
                "status.text": text,
                "status.help": muted,
                "status.tooltip": f"bold {accent}",
                "input": f"bg:{bg} {bright}",
                "input.prompt": f"bold {secondary}",
                "auto-suggestion": muted,
            }
        )

    def _input_history_path(self):
        from ..config import CONFIG_DIR

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        return CONFIG_DIR / "input_history"

    def _get_help_text(self) -> str:
        return "C-n: New, C-e: Edit, C-y: Copy, C-u/d: Scroll, C-q: Quit"

    def _command_rows(self) -> list[tuple[str, str]]:
        return [
            ("/file <path> [tanya]", "baca dokumen lokal"),
            ("/file --browse [tanya]", "buka browser file terminal"),
            ("/help", "tampilkan daftar perintah"),
            ("/new", "buat chat baru"),
            ("/delete", "hapus chat aktif"),
            ("/rename <judul>", "ganti judul chat aktif"),
            ("/project", "lihat project aktif dan daftar project"),
            ("/project new <nama>", "buat folder project baru"),
            ("/project <nama>", "buka folder project"),
            ("/project move <nama>", "pindahkan chat aktif ke project"),
            ("/project rename <nama>", "ganti nama project aktif"),
            ("/project delete confirm", "hapus project aktif beserta semua chat"),
            ("/project system [prompt]", "lihat atau ubah system project"),
            ("/project system reset", "hapus system khusus project"),
            ("/project file [path]", "tambahkan file referensi project"),
            ("/project files", "lihat file referensi project"),
            ("/project file remove <nomor>", "hapus file referensi project"),
            ("/models [all]", "refresh daftar model"),
            ("/model <nama>", "ganti model"),
            (f"/provider {PROVIDER_HELP_TEXT}", "ganti backend"),
            ("/apikey <key>", "set api key"),
            ("/clear", "hapus chat saat ini"),
            ("/stop", "hentikan jawaban AI yang sedang diproses"),
            ("/regen", "generate ulang jawaban"),
            ("/mouse on|off", "klik tombol / blok teks"),
            (f"/theme {'|'.join(SUPPORTED_THEMES)}", "ganti tema tampilan"),
            ("/accent <preset|#RRGGBB>", "ganti warna aksen"),
            ("/system", "lihat system global aktif"),
            ("/system <teks>", "ubah system global"),
            ("/system reset", "kembali ke system global default"),
            ("/thinking on|off", "tampil proses berpikir"),
            ("/status", "cek koneksi aktif"),
            ("/save", "simpan konfigurasi"),
            ("/exit", "keluar"),
        ]

    def _show_help_message(self) -> None:
        lines = ["### Bantuan Command", ""]
        for command, description in self._command_rows():
            lines.append(f"- `{command}` — {description}")
        lines.extend(
            [
                "",
                "Shortcut utama: `Esc` hentikan jawaban, `Ctrl-N` chat baru, `Ctrl-Y` copy, `Ctrl-E` edit, `Ctrl-R` generate ulang, `F2` toggle mode klik/blok teks, `Ctrl-Q` keluar.",
                "",
                "Ikon: `⧉` salin, `✎` edit, `⚙` sistem, `✐` rename, `▣` project, `↻` ulang, `⌑` file, `▤` blok teks, `＋` baru, `×` hapus, `■` hentikan.",
            ]
        )
        self.session.messages.append(ChatMessage("assistant", "\n".join(lines)))
        self.selected_message_index = len(self.session.messages) - 1
        self._request_scroll_to_bottom()
        self._touch_session()
        self.status = "Bantuan command ditambahkan ke layar chat."

    def _show_system_prompt_message(self) -> None:
        content = "\n".join(
            [
                "### System Global Aktif",
                "",
                "```text",
                self.cfg.system_prompt.strip() or "(kosong)",
                "```",
            ]
        )
        self.session.messages.append(ChatMessage("assistant", content))
        self.selected_message_index = len(self.session.messages) - 1
        self._request_scroll_to_bottom()
        self._touch_session()
        self.status = "System global aktif ditampilkan di layar chat."

    def _show_project_system_message(self) -> None:
        settings = get_project_settings(self.active_project)
        lines = [
            f"### System Project: {settings.name}",
            "",
            "```text",
            settings.system_prompt.strip() or "(belum diatur; hanya memakai system global)",
            "```",
            "",
            f"### File Referensi ({len(settings.references)})",
            "",
        ]
        if settings.references:
            for index, reference in enumerate(settings.references, start=1):
                suffix = " — dipotong" if reference.truncated else ""
                lines.append(f"- `{index}. {reference.name}`{suffix}")
        else:
            lines.append("- Belum ada file referensi.")
        self.session.messages.append(ChatMessage("assistant", "\n".join(lines)))
        self.selected_message_index = len(self.session.messages) - 1
        self._request_scroll_to_bottom()
        self._touch_session()
        self.status = f"System dan referensi Project {settings.name} ditampilkan."

    def _key_bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-c")
        @kb.add("c-q")
        def _(event) -> None:
            self._cancel_stream()
            event.app.exit()

        @kb.add("c-n")
        def _(event) -> None:
            self._new_session()

        @kb.add("c-e")
        def _(event) -> None:
            self._edit_selected()

        @kb.add("c-y")
        def _(event) -> None:
            self._copy_selected()

        @kb.add("c-r")
        def _(event) -> None:
            self._regenerate_selected()

        @kb.add("f2")
        def _(event) -> None:
            self._toggle_mouse_mode()

        @kb.add("pageup")
        @kb.add("c-u")
        def _(event) -> None:
            self._scroll_chat(-8)

        @kb.add("pagedown")
        @kb.add("c-d")
        def _(event) -> None:
            self._scroll_chat(8)

        @kb.add("escape")
        def _(event) -> None:
            if self.streaming:
                self._cancel_stream()
                event.app.invalidate()
                return
            self.editing_message_index = None
            self.selected_message_index = None
            self.input.text = ""
            self.status = "Pilihan dibatalkan."
            event.app.invalidate()

        @kb.add("enter")
        def _(event) -> None:
            if event.app.layout.current_control == self.input.control:
                self.input.buffer.validate_and_handle()

        return kb

    def _accept_input(self, buffer: Buffer) -> bool:
        text = buffer.text.strip()
        if not text or self.streaming:
            return False
        buffer.text = ""
        self._stream_task = asyncio.create_task(self._submit(text))
        return True

    async def _submit(self, text: str) -> None:
        if self.streaming:
            return

        if not text:
            if self.session.messages and self.session.messages[-1].role == "user":
                await self._stream_reply()
            return

        if self.file_browser is not None:
            await self._handle_file_browser_input(text)
            return

        if text.startswith("/"):
            await self._handle_command(text)
            self.app.invalidate()
            return

        if self.editing_message_index is not None:
            await self._save_edit(text)
            return

        self.session.messages.append(ChatMessage("user", text))
        self._touch_session(title_from_message(text) if len(self.session.messages) == 1 else None)
        self._request_scroll_to_bottom()
        await self._stream_reply()

    async def _save_edit(self, text: str) -> None:
        index = self.editing_message_index
        self.editing_message_index = None
        if index is None or index >= len(self.session.messages):
            return

        role = self.session.messages[index].role
        self.session.messages[index] = ChatMessage(
            role, text, images=self.session.messages[index].images
        )
        self._render_cache.clear()
        if role == "user":
            del self.session.messages[index + 1 :]
            self.selected_message_index = index
            self._touch_session(title_from_message(text) if index == 0 else None)
            await self._stream_reply()
        else:
            self.selected_message_index = index
            self._touch_session()
            self.status = "Pesan asisten diperbarui."
            self.app.invalidate()

    async def _stream_reply(self) -> None:
        self.streaming = True
        self.status = "Asisten sedang menjawab..."
        self.session.messages.append(ChatMessage("assistant", ""))
        assistant_index = len(self.session.messages) - 1
        self.selected_message_index = assistant_index
        self._request_scroll_to_bottom()
        self.app.invalidate()
        request_messages = self._api_messages()

        try:
            async for chunk in self.provider.chat_stream(
                request_messages,
                model=self.cfg.active_model,
                temperature=self.cfg.temperature,
            ):
                current = self.session.messages[assistant_index]
                self.session.messages[assistant_index] = ChatMessage(
                    "assistant", current.content + chunk, images=current.images
                )
                self._request_scroll_to_bottom()
                self.app.invalidate()
        except asyncio.CancelledError:
            current = self.session.messages[assistant_index]
            if current.content.strip():
                self._touch_session()
            else:
                self.session.messages.pop(assistant_index)
                self.selected_message_index = (
                    len(self.session.messages) - 1 if self.session.messages else None
                )
            self.status = "Jawaban AI dihentikan."
        except Exception as exc:
            self.session.messages.pop(assistant_index)
            self.status = f"Error: {exc}"
        else:
            current = self.session.messages[assistant_index]
            usage = self.provider.last_usage or estimate_token_usage(
                request_messages, current.content
            )
            self.session.messages[assistant_index] = ChatMessage(
                "assistant",
                current.content,
                images=current.images,
                token_usage=usage,
            )
            estimate_label = " estimasi" if usage.estimated else ""
            self.status = (
                f"Jawaban selesai | token{estimate_label}: "
                f"masuk {usage.input_tokens} | keluar {usage.output_tokens} | "
                f"total {usage.total_tokens}"
            )
            self._touch_session()
        finally:
            self.streaming = False
            self.app.invalidate()

    def _api_messages(self) -> list[ChatMessage]:
        combined_system_prompt = compose_project_system_prompt(
            self.cfg.system_prompt,
            self.active_project,
        )
        system_prompt = with_response_format_prompt(
            with_visible_thinking_prompt(
                combined_system_prompt,
                self.cfg.show_thinking,
            )
        )
        messages = [ChatMessage("system", system_prompt)]
        for message in self.session.messages:
            content = (
                strip_think_tags(message.content, False)
                if message.role == "assistant"
                else message.content
            )
            if content.strip() or message.role != "assistant":
                messages.append(ChatMessage(message.role, content, images=message.images))
        return messages

    async def _handle_command(self, text: str) -> None:
        parts = text.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd in ("/exit", "/quit", "/q"):
            self._cancel_stream()
            self.app.exit()
            return
        if cmd == "/help":
            self._show_help_message()
            return
        if cmd in ("/stop", "/hentikan"):
            self.status = "Tidak ada jawaban AI yang sedang diproses."
            return
        if cmd == "/clear":
            self.session.messages.clear()
            self.selected_message_index = None
            self.editing_message_index = None
            self._render_cache.clear()
            self._touch_session("Chat baru", reset_title=True)
            self.status = "Riwayat buffer ini dikosongkan."
            return
        if cmd == "/new":
            self._new_session()
            return
        if cmd == "/delete":
            self._delete_current_session()
            return
        if cmd == "/rename":
            new_title = text[len(parts[0]) :].strip()
            if not new_title:
                self.status = "Gunakan: /rename <judul chat>"
                return
            title = title_from_message(new_title, limit=80)
            self._touch_session(title, manual_title=True)
            self.status = f"Judul chat diubah menjadi: {title}"
            return
        if cmd == "/project":
            args = text[len(parts[0]) :].strip()
            if not args:
                projects = ", ".join(self.projects)
                self.status = f"Project aktif: {self.active_project} | Tersedia: {projects}"
                return
            action, _, value = args.partition(" ")
            if action.lower() == "system":
                prompt = value.strip()
                if not prompt or prompt.casefold() in ("show", "lihat", "aktif"):
                    self._show_project_system_message()
                    return
                if prompt.casefold() in ("reset", "default", "hapus"):
                    set_project_system_prompt(self.active_project, "")
                    self.status = f"System khusus Project {self.active_project} dihapus."
                    self._render_cache.clear()
                    return
                if prompt.casefold().startswith("set "):
                    prompt = prompt[4:].strip()
                set_project_system_prompt(self.active_project, prompt)
                self.status = f"System Project {self.active_project} diperbarui dan disimpan."
                self._render_cache.clear()
                return
            if action.lower() == "files":
                self._show_project_system_message()
                return
            if action.lower() == "file":
                try:
                    file_args = shlex.split(args)
                except ValueError as exc:
                    self.status = f"Format /project file tidak valid: {exc}"
                    return
                if len(file_args) >= 3 and file_args[1].casefold() == "remove":
                    selector = " ".join(file_args[2:])
                    try:
                        removed = remove_project_reference(self.active_project, selector)
                    except ValueError as exc:
                        self.status = str(exc)
                    else:
                        self.status = f"Referensi dihapus dari Project: {removed.name}"
                        self._render_cache.clear()
                    return
                if len(file_args) < 2 or file_args[1] in ("--browse", "-b"):
                    self.file_browser = FileBrowserState()
                    self.file_browser_mode = "project_reference"
                    self.file_browser_question_parts = []
                    self.status = f"Pilih file referensi untuk Project {self.active_project}."
                    self._request_scroll_to_bottom()
                    return
                self._add_project_reference(file_args[1])
                return
            if action.lower() == "new":
                if not value.strip():
                    self.status = "Gunakan: /project new <nama>"
                    return
                project = create_project(value)
                self.projects = list_projects()
                self.active_project = project
                self.expanded_projects.add(project)
                self._new_session()
                self.status = f"Project dibuat dan dibuka: {project}"
                return
            if action.lower() == "move":
                if not value.strip():
                    self.status = "Gunakan: /project move <nama>"
                    return
                project = create_project(value)
                self.projects = list_projects()
                self.session.project = project
                self.active_project = project
                self.expanded_projects.add(project)
                self._touch_session()
                self.status = f"Chat dipindahkan ke project: {project}"
                return
            if action.lower() == "rename":
                if not value.strip():
                    self.status = "Gunakan: /project rename <nama baru>"
                    return
                old_project = self.active_project
                try:
                    project = rename_project(old_project, value)
                except ValueError as exc:
                    self.status = str(exc)
                    return
                self.projects = list_projects()
                self.sessions = list_sessions()
                self.active_project = project
                self.session = load_session(self.session.id) or self.session
                self.expanded_projects.discard(old_project)
                self.expanded_projects.add(project)
                self._render_cache.clear()
                self.status = f"Nama Project diubah: {old_project} → {project}"
                self.app.invalidate()
                return
            if action.lower() == "delete":
                if value.strip().casefold() != "confirm":
                    self.status = "Untuk menghapus Project aktif dan semua chatnya, ketik: /project delete confirm"
                    return
                project = self.active_project
                try:
                    deleted = delete_project(project)
                except ValueError as exc:
                    self.status = str(exc)
                    return
                self.projects = list_projects()
                self.sessions = list_sessions()
                self.active_project = "Umum"
                self.expanded_projects.discard(project)
                self.expanded_projects.add(self.active_project)
                replacement = next(
                    (item for item in self.sessions if item.project == self.active_project),
                    None,
                )
                self.session = replacement or ChatSession.new(self.active_project)
                if replacement is None:
                    save_session(self.session)
                    self.sessions = list_sessions()
                self.selected_message_index = None
                self.editing_message_index = None
                self.input.text = ""
                self._render_cache.clear()
                self.status = f"Project {project} dan {deleted} chat di dalamnya telah dihapus."
                self.app.invalidate()
                return
            project = next(
                (name for name in self.projects if name.casefold() == args.casefold()),
                None,
            )
            if project is None:
                self.status = f"Project tidak ditemukan: {args}. Gunakan /project new <nama>."
                return
            self._select_project(project)
            return
        if cmd == "/file":
            try:
                args = shlex.split(text)
            except ValueError as exc:
                self.status = f"Format /file tidak valid: {exc}"
                return

            if len(args) < 2 or args[1] in ("--browse", "-b"):
                self.file_browser = FileBrowserState()
                self.file_browser_mode = "chat"
                self.file_browser_question_parts = args[2:] if len(args) > 1 else []
                self.status = "File browser aktif. Ketik nomor, .., /filter, atau q."
                self._request_scroll_to_bottom()
                return
            file_path = args[1]
            question_parts = args[2:]

            try:
                if self.cfg.provider in ("gemini", "ollama") and Path(file_path).suffix.lower() in IMAGE_EXTENSIONS:
                    message = build_image_message(file_path, " ".join(question_parts))
                    display_path = Path(file_path).expanduser()
                else:
                    document = load_document(file_path)
                    message = ChatMessage(
                        "user", build_document_prompt(document, " ".join(question_parts))
                    )
                    display_path = document.path
            except DocumentLoadError as exc:
                self.status = f"Error: {exc}"
                return
            self.session.messages.append(message)
            self._touch_session(
                title_from_message(f"File: {display_path.name}")
                if len(self.session.messages) == 1
                else None
            )
            self.status = f"Mengirim gambar asli: {display_path}" if message.images else f"Membaca file: {display_path}"
            self._request_scroll_to_bottom()
            await self._stream_reply()
            return
        if cmd == "/save":
            save_config(self.cfg)
            self.status = "Konfigurasi disimpan."
            return
        if cmd in ("/regen", "/regenerate", "/ulang"):
            self._regenerate_selected()
            return
        if cmd in ("/mouse", "/block", "/blok"):
            value = parts[1].lower() if len(parts) > 1 else "toggle"
            if value in ("on", "klik", "click", "true", "1"):
                self._set_mouse_mode(True)
            elif value in ("off", "block", "blok", "select", "false", "0"):
                self._set_mouse_mode(False)
            elif value == "toggle":
                self._toggle_mouse_mode()
            else:
                self.status = "Gunakan: /mouse on untuk klik, /mouse off untuk blok teks."
            return
        if cmd == "/theme":
            if len(parts) < 2:
                self.status = (
                    f"Tema aktif: {self.cfg.theme}. Tersedia: "
                    f"{', '.join(SUPPORTED_THEMES)}"
                )
                return
            try:
                self.cfg.theme = normalize_theme(parts[1])
            except ValueError as exc:
                self.status = str(exc)
                return
            self._apply_appearance()
            self.status = f"Tema tampilan: {self.cfg.theme}"
            return
        if cmd == "/accent":
            if len(parts) < 2:
                self.status = (
                    f"Aksen aktif: {self.cfg.accent}. Preset: "
                    f"{', '.join(ACCENT_COLORS)}; atau gunakan #RRGGBB."
                )
                return
            try:
                self.cfg.accent = normalize_accent(parts[1])
            except ValueError as exc:
                self.status = str(exc)
                return
            self._apply_appearance()
            self.status = f"Warna aksen: {self.cfg.accent}"
            return
        if cmd == "/thinking":
            if len(parts) < 2:
                self.cfg.show_thinking = not self.cfg.show_thinking
            else:
                value = parts[1].lower()
                if value in ("on", "true", "1", "yes", "ya"):
                    self.cfg.show_thinking = True
                elif value in ("off", "false", "0", "no", "tidak"):
                    self.cfg.show_thinking = False
                else:
                    self.status = "Gunakan: /thinking on atau /thinking off"
                    return
            save_config(self.cfg)
            self._render_cache.clear()
            state = "ditampilkan" if self.cfg.show_thinking else "disembunyikan"
            self.status = f"Proses berpikir {state}."
            return
        if cmd == "/models":
            await self._refresh_models()
            if self.models_error:
                return
            
            if len(parts) > 1 and parts[1].lower() == "all":
                model_list_text = "### Daftar Lengkap Model\n\n" + "\n".join(f"- `{m}`" for m in self.models)
                self.session.messages.append(ChatMessage("assistant", model_list_text))
                self.selected_message_index = len(self.session.messages) - 1
                self._request_scroll_to_bottom()
                self.status = "Daftar lengkap model ditambahkan ke layar chat."
                return

            current = f"aktif: {self.cfg.active_model}"
            shown = ", ".join(self.models[:5]) if self.models else "tidak ada model"
            more = f" (+{len(self.models) - 5} lagi)" if len(self.models) > 5 else ""
            self.status = f"Model tersedia ({current}): {shown}{more}. Gunakan /models all untuk daftar lengkap."
            return
        if cmd == "/model" and len(parts) >= 2:
            self._select_model(parts[1])
            self._render_cache.clear()
            return
        if cmd == "/provider" and len(parts) >= 2:
            try:
                self.cfg.set_provider(parts[1].lower())
                self.provider = self._make_provider()
                self.status = f"Provider diganti ke {self.cfg.provider}."
                self._render_cache.clear()
                await self._refresh_models()
            except ValueError as exc:
                self.status = f"Error: {exc}"
            return
        if cmd == "/apikey" and len(parts) >= 2:
            key = " ".join(parts[1:])
            if self.cfg.provider == "deepseek":
                self.cfg.deepseek_api_key = key
            elif self.cfg.provider == "gemini":
                self.cfg.gemini_api_key = key
            elif self.cfg.provider == "openai":
                self.cfg.openai_api_key = key
            elif self.cfg.provider == "localai":
                self.cfg.localai_api_key = key
            else:
                self.status = "Provider ini tidak mendukung API key."
                return
            self.provider = self._make_provider()
            save_config(self.cfg)
            self.status = f"API key untuk {self.cfg.provider} telah disimpan."
            self._render_cache.clear()
            await self._refresh_models()
            return
        if cmd == "/system":
            if len(parts) < 2 or (len(parts) == 2 and parts[1].lower() in ("show", "lihat", "active", "aktif")):
                self._show_system_prompt_message()
                return
            if len(parts) == 2 and parts[1].lower() in ("reset", "default"):
                self.cfg.system_prompt = DEFAULT_SYSTEM_PROMPT
                self.status = "System prompt dikembalikan ke default. Gunakan /save jika ingin permanen."
                self._render_cache.clear()
                return
            if len(parts) >= 3 and parts[1].lower() == "set":
                new_prompt = text[len("/system") :].strip()[4:].strip()
            else:
                new_prompt = text[len("/system") :].strip()
            if not new_prompt:
                self.status = "Gunakan: /system, /system reset, atau /system <prompt>"
                return
            self.cfg.system_prompt = new_prompt
            self.status = "System prompt aktif diperbarui. Gunakan /save jika ingin permanen."
            self._render_cache.clear()
            return
        if cmd == "/status":
            online = await self.provider.health_check()
            state = "online" if online else "offline"
            self.status = (
                f"{self.cfg.provider} {state} | "
                f"{self.cfg.active_model} | {len(self.session.messages)} pesan"
            )
            return
        self.status = "Command tidak dikenal. Ketik /help untuk daftar perintah."

    def _touch_session(
        self,
        title: str | None = None,
        *,
        manual_title: bool = False,
        reset_title: bool = False,
    ) -> None:
        self.session.touch(
            title,
            manual_title=manual_title,
            reset_title=reset_title,
        )
        save_session(self.session)
        self.sessions = list_sessions()
        if self.session.project not in self.projects:
            self.projects = list_projects()

    def _new_session(self) -> None:
        self._cancel_stream()
        self.expanded_projects.add(self.active_project)
        self.session = ChatSession.new(self.active_project)
        save_session(self.session)
        self.sessions = list_sessions()
        self.selected_message_index = None
        self.editing_message_index = None
        self.input.text = ""
        self._render_cache.clear()
        self.status = "Chat baru dibuat."
        self.app.invalidate()

    def _delete_current_session(self) -> None:
        self._cancel_stream()
        delete_session(self.session.id)
        self.sessions = list_sessions()
        project_sessions = [
            session for session in self.sessions if session.project == self.active_project
        ]
        if project_sessions:
            self.session = project_sessions[0]
        elif self.sessions:
            self.session = self.sessions[0]
        else:
            self.session = ChatSession.new(self.active_project)
        self.active_project = self.session.project
        self.expanded_projects.add(self.active_project)
        if not self.sessions:
            save_session(self.session)
            self.sessions = [self.session]
        self.selected_message_index = None
        self.editing_message_index = None
        self.input.text = ""
        self._render_cache.clear()
        self.status = "Chat dihapus."
        self.app.invalidate()

    def _load_session(self, session_id: str) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum pindah chat."
            self.app.invalidate()
            return
        session = load_session(session_id)
        if not session:
            self.status = "Chat tidak ditemukan."
            self.app.invalidate()
            return
        self.session = session
        self.active_project = session.project
        self.expanded_projects.add(session.project)
        self.selected_message_index = None
        self.editing_message_index = None
        self.input.text = ""
        self._render_cache.clear()
        self.status = f"Membuka chat: {session.title}"
        self.app.invalidate()

    def _select_project(self, project: str) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum pindah project."
            self.app.invalidate()
            return
        self.active_project = project
        self.expanded_projects.add(project)
        session = next(
            (item for item in self.sessions if item.project == project),
            None,
        )
        if session is None:
            self._new_session()
            self.status = f"Project dibuka: {project}. Chat baru dibuat."
            return
        self._load_session(session.id)
        self.status = f"Project dibuka: {project}"

    def _toggle_project(self, project: str) -> None:
        if project in self.expanded_projects:
            self.expanded_projects.remove(project)
            self.status = f"Folder diciutkan: {project}"
            self.app.invalidate()
            return
        if self.streaming and project != self.active_project:
            self.status = "Tunggu jawaban selesai sebelum pindah project."
            self.app.invalidate()
            return
        self.expanded_projects.add(project)
        if project != self.active_project:
            self._select_project(project)
        else:
            self.status = f"Folder dibuka: {project}"
            self.app.invalidate()

    def _new_project_prompt(self) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum membuat project."
            self.app.invalidate()
            return
        self.input.text = "/project new "
        self.input.buffer.cursor_position = len(self.input.text)
        self.app.layout.focus(self.input)
        self.status = "Ketik nama project lalu tekan Enter."
        self.app.invalidate()

    def _rename_project_prompt(self) -> None:
        if self.active_project == "Umum":
            self.status = "Project Umum tidak dapat diganti namanya."
            self.app.invalidate()
            return
        self.input.text = "/project rename "
        self.input.buffer.cursor_position = len(self.input.text)
        self.app.layout.focus(self.input)
        self.status = f"Ketik nama baru untuk Project {self.active_project}, lalu tekan Enter."
        self.app.invalidate()

    def _delete_project_prompt(self) -> None:
        if self.active_project == "Umum":
            self.status = "Project Umum tidak dapat dihapus."
            self.app.invalidate()
            return
        self.input.text = "/project delete "
        self.input.buffer.cursor_position = len(self.input.text)
        self.app.layout.focus(self.input)
        self.status = f"PERINGATAN: semua chat di {self.active_project} akan dihapus. Ketik confirm lalu Enter."
        self.app.invalidate()

    async def _refresh_models(self) -> None:
        self.models_error = None
        self.status = f"Mengambil model dari {self.cfg.provider}..."
        self.app.invalidate()
        try:
            self.models = await self.provider.list_models()
        except Exception as exc:
            self.models = []
            self.models_error = str(exc)
            self.status = f"Gagal mengambil model: {exc}"
        else:
            count = len(self.models)
            self.status = f"{count} model tersedia. Klik model di sidebar untuk memilih."
        finally:
            self.app.invalidate()

    def _select_model(self, model: str) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum mengganti model."
            self.app.invalidate()
            return
        self.cfg.set_model(model)
        self._render_cache.clear()
        self.status = f"Model aktif: {self.cfg.active_model}"
        self.app.invalidate()

    def _select_message(self, index: int) -> None:
        if index < len(self.session.messages):
            self.selected_message_index = index
            role = "pesan Anda" if self.session.messages[index].role == "user" else "jawaban"
            if self.session.messages[index].role == "assistant":
                self.status = f"Memilih {role}. Copy, Edit, atau Generate ulang."
            else:
                self.status = f"Memilih {role}. Copy atau Edit."
            self.app.invalidate()

    def _copy_message(self, index: int) -> None:
        self.selected_message_index = index
        self._copy_selected()

    def _edit_message(self, index: int) -> None:
        self.selected_message_index = index
        self._edit_selected()

    def _regenerate_message(self, index: int) -> None:
        self.selected_message_index = index
        self._regenerate_selected()

    def _selected_message(self) -> ChatMessage | None:
        if self.selected_message_index is None:
            return None
        if not 0 <= self.selected_message_index < len(self.session.messages):
            self.selected_message_index = None
            return None
        return self.session.messages[self.selected_message_index]

    def _copy_selected(self) -> None:
        message = self._selected_message()
        if message is None:
            self.status = "Pilih pesan dulu untuk disalin."
            self.app.invalidate()
            return
        content = (
            strip_think_tags(message.content, False)
            if message.role == "assistant"
            else message.content
        )
        get_app().clipboard.set_data(ClipboardData(content))
        copied_external = copy_to_system_clipboard(content)
        suffix = "desktop clipboard" if copied_external else "clipboard internal terminal"
        label = "Jawaban" if message.role == "assistant" else "Pesan"
        self.status = f"{label} tersalin ke {suffix}."
        self.app.invalidate()

    def _edit_system_prompt(self) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum mengubah system prompt."
            self.app.invalidate()
            return
        self.editing_message_index = None
        self.selected_message_index = None
        prompt_body = self.cfg.system_prompt.rstrip()
        self.input.text = f"/system {prompt_body}" if prompt_body else "/system "
        self.input.buffer.cursor_position = len(self.input.text)
        self.app.layout.focus(self.input)
        self.status = "Edit system prompt di input bawah lalu tekan Enter. Gunakan /save jika ingin permanen."
        self.app.invalidate()

    def _edit_project_system_prompt(self) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum mengubah system project."
            self.app.invalidate()
            return
        settings = get_project_settings(self.active_project)
        self.editing_message_index = None
        self.selected_message_index = None
        prompt_body = settings.system_prompt.rstrip()
        self.input.text = (
            f"/project system {prompt_body}" if prompt_body else "/project system "
        )
        self.input.buffer.cursor_position = len(self.input.text)
        self.app.layout.focus(self.input)
        self.status = f"Edit system khusus Project {self.active_project}, lalu tekan Enter."
        self.app.invalidate()

    def _pick_project_reference(self) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum menambah referensi project."
            self.app.invalidate()
            return
        self.file_browser = FileBrowserState()
        self.file_browser_mode = "project_reference"
        self.file_browser_question_parts = []
        self.status = f"Pilih file referensi untuk Project {self.active_project}."
        self._request_scroll_to_bottom()
        self.app.invalidate()

    def _add_project_reference(self, path_text: str) -> None:
        try:
            document = load_document(
                path_text,
                max_chars=MAX_PROJECT_REFERENCE_CHARS,
            )
            reference = add_project_reference(self.active_project, document)
        except (DocumentLoadError, ValueError) as exc:
            self.status = f"Gagal menambah referensi: {exc}"
        else:
            suffix = " (dipotong)" if reference.truncated else ""
            self.status = (
                f"Referensi Project {self.active_project} ditambahkan: "
                f"{reference.name}{suffix}"
            )
            self._render_cache.clear()
        self.app.invalidate()

    def _rename_session(self) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum mengganti judul chat."
            self.app.invalidate()
            return
        self.editing_message_index = None
        self.selected_message_index = None
        self.input.text = f"/rename {self.session.title}"
        self.input.buffer.cursor_position = len(self.input.text)
        self.app.layout.focus(self.input)
        self.status = "Ubah judul chat di input bawah lalu tekan Enter."
        self.app.invalidate()

    def _edit_selected(self) -> None:
        message = self._selected_message()
        if message is None:
            self.status = "Pilih pesan dulu untuk diedit."
            self.app.invalidate()
            return
        self.editing_message_index = self.selected_message_index
        self.input.text = message.content
        self.input.buffer.cursor_position = len(self.input.text)
        self.app.layout.focus(self.input)
        if message.role == "user":
            self.status = (
                "Edit pesan Anda lalu Enter. "
                "Jawaban setelahnya akan dibuat ulang."
            )
        else:
            self.status = "Edit jawaban lalu Enter untuk menyimpan teksnya."
        self.app.invalidate()

    def _regenerate_selected(self) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum generate ulang."
            self.app.invalidate()
            return

        index = self.selected_message_index
        if index is None:
            index = self._last_assistant_index()

        if index is None or index >= len(self.session.messages):
            self.status = "Belum ada jawaban untuk dibuat ulang."
            self.app.invalidate()
            return

        message = self.session.messages[index]
        self._render_cache.clear()
        if message.role == "user":
            del self.session.messages[index + 1 :]
            self.selected_message_index = index
        elif message.role == "assistant":
            del self.session.messages[index:]
            self.selected_message_index = index - 1 if index > 0 else None
        else:
            self.status = "Pilih pesan user atau jawaban asisten."
            self.app.invalidate()
            return

        if not self.session.messages or self.session.messages[-1].role != "user":
            self.status = "Generate ulang butuh pesan user sebelum jawaban."
            self.app.invalidate()
            return

        self.status = "Generate ulang jawaban..."
        self._request_scroll_to_bottom()
        self._stream_task = asyncio.create_task(self._stream_reply())
        self.app.invalidate()

    def _last_assistant_index(self) -> int | None:
        for index in range(len(self.session.messages) - 1, -1, -1):
            if self.session.messages[index].role == "assistant":
                return index
        return None

    def _toggle_mouse_mode(self) -> None:
        self._set_mouse_mode(not self.mouse_enabled)

    def _set_mouse_mode(self, enabled: bool) -> None:
        self.mouse_enabled = enabled
        if enabled:
            self.status = "Mode klik aktif. Tombol dan klik pesan bisa dipakai."
        else:
            self.status = "Mode blok teks aktif. Drag mouse untuk seleksi teks terminal, F2 untuk kembali."
        self.app.invalidate()

    def _apply_appearance(self) -> None:
        self.app.style = self._style()
        save_config(self.cfg)
        self._render_cache.clear()
        self.app.invalidate()

    def _theme_prompt(self) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum mengganti tema."
            self.app.invalidate()
            return
        self.input.text = "/theme "
        self.input.buffer.cursor_position = len(self.input.text)
        self.app.layout.focus(self.input)
        self.status = f"Pilih tema: {', '.join(SUPPORTED_THEMES)}"
        self.app.invalidate()

    def _accent_prompt(self) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum mengganti warna aksen."
            self.app.invalidate()
            return
        self.input.text = "/accent "
        self.input.buffer.cursor_position = len(self.input.text)
        self.app.layout.focus(self.input)
        self.status = "Pilih preset aksen atau masukkan warna HEX seperti #ff8800."
        self.app.invalidate()

    def _toggle_thinking(self, index: int) -> None:
        if index in self.expanded_thinking_indices:
            self.expanded_thinking_indices.remove(index)
        else:
            self.expanded_thinking_indices.add(index)
        self.app.invalidate()

    def _cancel_stream(self) -> None:
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            self.status = "Menghentikan jawaban AI..."
        elif self.streaming:
            self.status = "Menghentikan jawaban AI..."
        else:
            self.status = "Tidak ada jawaban AI yang sedang diproses."

    def _scroll_chat(self, delta: int) -> None:
        self.chat_pane.vertical_scroll = min(
            self._max_chat_scroll(),
            max(0, self.chat_pane.vertical_scroll + delta),
        )
        self.status = f"Scroll chat {self.chat_pane.vertical_scroll}/{self._max_chat_scroll()}"
        self.app.invalidate()

    def _scroll_chat_to_bottom(self) -> None:
        self.chat_pane.vertical_scroll = self._max_chat_scroll()

    def _request_scroll_to_bottom(self) -> None:
        self._scroll_to_bottom_pending = True

    def _apply_pending_scroll(self) -> None:
        if self._scroll_to_bottom_pending and hasattr(self, "chat_pane"):
            self._scroll_chat_to_bottom()
            self._scroll_to_bottom_pending = False

    def _max_chat_scroll(self) -> int:
        try:
            rows = self.app.output.get_size().rows
        except Exception:
            rows = 24
        visible_chat_rows = max(1, rows - 9)
        return max(0, self._chat_line_count - visible_chat_rows)

    def _chat_width(self) -> int:
        try:
            columns = self.app.output.get_size().columns
        except Exception:
            columns = 100
        if not self.mouse_enabled:
            return max(40, columns - 2)
        return max(40, columns - 34)

    def _set_hover_hint(self, hint: str | None) -> None:
        if self.hover_hint == hint:
            return
        self.hover_hint = hint
        self.app.invalidate()

    def _click(self, callback, hover_hint: str | None = None):
        def handler(mouse_event: MouseEvent) -> None:
            if mouse_event.event_type == MouseEventType.MOUSE_MOVE:
                self._set_hover_hint(hover_hint)
                return
            if mouse_event.event_type == MouseEventType.SCROLL_UP:
                self._set_hover_hint(None)
                self._scroll_chat(-3)
                return
            if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
                self._set_hover_hint(None)
                self._scroll_chat(3)
                return
            if mouse_event.event_type == MouseEventType.MOUSE_UP:
                self._set_hover_hint(None)
                callback()

        return handler

    def _pick_file_from_toolbar(self) -> None:
        if self.streaming:
            self.status = "Tunggu jawaban selesai sebelum membuka file."
            self.app.invalidate()
            return
        self._stream_task = asyncio.create_task(self._submit("/file"))

    def _click_file_browser_entry(self, value: str) -> None:
        if self.file_browser is None or self.streaming:
            return
        self._stream_task = asyncio.create_task(self._handle_file_browser_input(value))

    async def _handle_file_browser_input(self, text: str) -> None:
        if self.file_browser is None:
            return

        selected, error = handle_browser_input(self.file_browser, text)
        if error == "cancel":
            self.file_browser = None
            self.file_browser_mode = "chat"
            self.file_browser_question_parts = []
            self.status = "Pemilihan file dibatalkan."
            self.app.invalidate()
            return
        if error:
            self.status = error
            self.app.invalidate()
            return
        if selected is None:
            self.status = "File browser aktif. Ketik nomor, .., /filter, atau q."
            self._request_scroll_to_bottom()
            self.app.invalidate()
            return

        browser_mode = self.file_browser_mode
        question_parts = self.file_browser_question_parts
        self.file_browser = None
        self.file_browser_mode = "chat"
        self.file_browser_question_parts = []
        if browser_mode == "project_reference":
            self._add_project_reference(str(selected))
            return
        try:
            if self.cfg.provider in ("gemini", "ollama") and selected.suffix.lower() in IMAGE_EXTENSIONS:
                message = build_image_message(str(selected), " ".join(question_parts))
            else:
                document = load_document(str(selected))
                message = ChatMessage(
                    "user", build_document_prompt(document, " ".join(question_parts))
                )
        except DocumentLoadError as exc:
            self.status = f"Error: {exc}"
            self.app.invalidate()
            return

        self.session.messages.append(message)
        self._touch_session(
            title_from_message(f"File: {selected.name}")
            if len(self.session.messages) == 1
            else None
        )
        self.status = f"Mengirim gambar asli: {selected}" if message.images else f"Membaca file: {selected}"
        self._request_scroll_to_bottom()
        await self._stream_reply()

    def _render_header(self) -> AnyFormattedText:
        title = shorten(self.session.title, width=28, placeholder="...")
        state = "Menjawab" if self.streaming else "Siap"
        thinking = "thinking:on" if self.cfg.show_thinking else "thinking:off"
        mouse_mode = "klik" if self.mouse_enabled else "blok teks"
        return [
            ("class:header.title", "  DJ Chat Ai "),
            ("class:header.meta", " | "),
            ("class:header.value", state),
            ("class:header.meta", " | ui: "),
            (
                "class:header.value",
                f"{shorten(self.cfg.theme, width=10, placeholder='...')}/"
                f"{shorten(self.cfg.accent, width=10, placeholder='...')}",
            ),
            ("class:header.meta", " "),
            (
                "class:button.hot",
                " ◐ ",
                self._click(self._theme_prompt, "Ganti tema tampilan"),
            ),
            ("class:header.meta", " "),
            (
                "class:button.hot",
                " ◆ ",
                self._click(self._accent_prompt, "Ganti warna aksen"),
            ),
            ("class:header.meta", " | chat: "),
            ("class:header.value", title),
            ("class:header.meta", " | project: "),
            ("class:header.value", shorten(self.active_project, width=18, placeholder="...")),
            ("class:header.meta", " | provider: "),
            ("class:header.value", self.cfg.provider),
            ("class:header.meta", " | model: "),
            ("class:header.value", shorten(self.cfg.active_model, width=24, placeholder="...")),
            ("class:header.meta", " | "),
            ("class:header.value", thinking),
            ("class:header.meta", " | mouse: "),
            ("class:header.value", mouse_mode),
        ]

    def _render_status(self) -> AnyFormattedText:
        mode = "EDIT" if self.editing_message_index is not None else "CHAT"
        if self.streaming:
            mode = "STREAM"
        stats = self.resource_stats
        latest_usage = next(
            (
                message.token_usage
                for message in reversed(self.session.messages)
                if message.token_usage is not None
            ),
            None,
        )
        token_text = (
            f"token {latest_usage.total_tokens}"
            if latest_usage is not None
            else "token -"
        )
        help_text = (
            f"CPU {stats.cpu_percent:.1f}% | RAM {stats.memory_mb:.0f} MB "
            f"({stats.memory_percent:.1f}%) | {token_text} | Ctrl-Q keluar"
        )
        status_fragments: list[tuple] = [
            ("class:status.mode", f" {mode} "),
            ("class:status.help", f" {help_text}"),
        ]
        if self.hover_hint:
            status_fragments.extend(
                [
                    ("class:status.text", " | "),
                    ("class:status.tooltip", f"ⓘ {self.hover_hint}"),
                ]
            )
        else:
            status_fragments.append(("class:status.text", f" | {self.status}"))
        return status_fragments

    def _render_sidebar(self) -> AnyFormattedText:
        fragments = [("class:sidebar.title", "  DJ Chat Ai\n")]
        fragments.append(("class:sidebar.meta", "  Terminal AI assistant\n\n"))
        fragments.append(("class:sidebar.section", "  System global\n"))
        system_prompt_preview = " ".join(self.cfg.system_prompt.strip().split()) or "(kosong)"
        for line in wrap(system_prompt_preview, width=22)[:3]:
            fragments.append(("class:sidebar.meta", f"  {line}\n"))
        if len(system_prompt_preview) > 72:
            fragments.append(("class:sidebar.meta", "  ...\n"))
        fragments.append(("class:sidebar.meta", "  ──────────────────────\n  "))
        fragments.append(
            (
                "class:button.hot",
                " [⚙] ",
                self._click(self._edit_system_prompt, "Edit system global"),
            )
        )
        fragments.append(("class:sidebar.meta", "\n\n"))
        fragments.append(("class:sidebar.section", "  Projects & chats\n"))
        for project in self.projects:
            project_sessions = [
                session for session in self.sessions if session.project == project
            ]
            project_active = project == self.active_project
            project_expanded = project in self.expanded_projects
            project_style = "class:sidebar.active" if project_active else "class:sidebar.section"
            project_prefix = "▾" if project_expanded else "▸"
            fragments.append(
                (
                    project_style,
                    f" {project_prefix} ▣ {shorten(project, width=15, placeholder='...')}"
                    f" ({len(project_sessions)})\n",
                    self._click(lambda name=project: self._toggle_project(name)),
                )
            )
            if not project_expanded:
                continue
            for session in project_sessions[:8]:
                active = session.id == self.session.id
                style = "class:sidebar.active" if active else "class:sidebar.item"
                title = shorten(session.title, width=18, placeholder="...")
                updated = _format_time(session.updated_at)
                prefix = "●" if active else " "
                fragments.append(
                    (
                        style,
                        f"   {prefix} {title:<18}\n",
                        self._click(lambda sid=session.id: self._load_session(sid)),
                    )
                )
                fragments.append(
                    ("class:sidebar.meta", f"   {updated}  {len(session.messages)} pesan\n")
                )
            if len(project_sessions) > 8:
                fragments.append(
                    ("class:sidebar.meta", f"     +{len(project_sessions) - 8} chat lain\n")
                )

        project_settings = get_project_settings(self.active_project)
        project_prompt_preview = (
            " ".join(project_settings.system_prompt.strip().split())
            or "(mengikuti system global)"
        )
        fragments.append(("class:sidebar.section", "\n  System project\n"))
        fragments.append(
            (
                "class:sidebar.active",
                f"  {shorten(self.active_project, width=20, placeholder='...')}\n",
            )
        )
        for line in wrap(project_prompt_preview, width=22)[:2]:
            fragments.append(("class:sidebar.meta", f"  {line}\n"))
        reference_count = len(project_settings.references)
        fragments.append(
            (
                "class:sidebar.meta",
                f"  Referensi: {reference_count}/{MAX_PROJECT_REFERENCES}\n",
            )
        )
        for reference in project_settings.references[:2]:
            fragments.append(
                (
                    "class:sidebar.meta",
                    f"  • {shorten(reference.name, width=19, placeholder='...')}\n",
                )
            )
        if reference_count > 2:
            fragments.append(
                ("class:sidebar.meta", f"  +{reference_count - 2} file lain\n")
            )
        fragments.append(("class:sidebar.meta", "  ──────────────────────\n  "))
        fragments.append(
            (
                "class:button.hot",
                " ⚙ ",
                self._click(
                    self._edit_project_system_prompt,
                    "Edit system project",
                ),
            )
        )
        fragments.append(("class:sidebar.meta", " "))
        fragments.append(
            (
                "class:button.hot",
                " ⌑ ",
                self._click(
                    self._pick_project_reference,
                    "Tambah file referensi project",
                ),
            )
        )
        fragments.append(("class:sidebar.meta", "\n"))

        fragments.append(("class:sidebar.meta", "  ──────────────────────\n  "))
        fragments.append(
            (
                "class:button.hot",
                " ＋ ",
                self._click(self._new_project_prompt, "Buat project baru"),
            )
        )
        fragments.append(("class:sidebar.meta", " "))
        fragments.append(
            (
                "class:button",
                " ✎ ",
                self._click(self._rename_project_prompt, "Ganti nama project"),
            )
        )
        fragments.append(("class:sidebar.meta", " "))
        fragments.append(
            (
                "class:button.danger",
                " × ",
                self._click(self._delete_project_prompt, "Hapus project"),
            )
        )
        fragments.append(("class:sidebar.meta", " "))
        fragments.append(
            (
                "class:button.hot",
                " ✐ ",
                self._click(self._rename_session, "Ganti nama chat"),
            )
        )
        fragments.append(("class:sidebar.meta", "\n"))

        fragments.append(("class:sidebar.section", "\n  Models\n"))
        provider = shorten(self.cfg.provider, width=8, placeholder="...")
        fragments.append(("class:sidebar.meta", f"  {provider} | /models\n"))
        if self.models_error:
            fragments.append(("class:sidebar.meta", "  /models untuk refresh\n"))
            fragments.append(
                (
                    "class:sidebar.meta",
                    f"  {shorten(self.models_error, width=24, placeholder='...')}\n",
                )
            )
        elif not self.models:
            fragments.append(("class:sidebar.meta", "  mengambil model...\n"))
        else:
            for model in self.models[:12]:
                active = model == self.cfg.active_model
                style = "class:sidebar.model.active" if active else "class:sidebar.model"
                prefix = "●" if active else "○"
                label = shorten(model, width=20, placeholder="...")
                fragments.append(
                    (
                        style,
                        f" {prefix} {label:<20}\n",
                        self._click(lambda name=model: self._select_model(name)),
                    )
                )
            if len(self.models) > 12:
                fragments.append(
                    ("class:sidebar.meta", f"   +{len(self.models) - 12} models\n")
                )
        return fragments

    def _render_chat(self) -> AnyFormattedText:
        if not self.mouse_enabled and self.file_browser is None:
            fragments = self._render_selectable_chat()
            self._chat_line_count = _count_fragment_lines(fragments)
            self._apply_pending_scroll()
            return fragments

        if self.file_browser is not None:
            browser_title = (
                f"File referensi Project: {self.active_project}"
                if self.file_browser_mode == "project_reference"
                else "File browser"
            )
            fragments = [("", "\n")]
            fragments.extend(
                [
                    ("class:message.label.assistant", f"    {browser_title}\n"),
                    ("class:message.assistant", f"    Folder: {self.file_browser.cwd}\n"),
                    (
                        "class:message.assistant",
                        f"    Filter: {self.file_browser.filter_text or '-'}\n\n",
                    ),
                    (
                        "class:message.assistant",
                        "    Klik folder/file untuk membuka atau memilih. "
                        "Keyboard: .. naik, /teks filter, / clear, q batal.\n\n",
                    ),
                    (
                        "class:button",
                        "      0  [D] ../\n",
                        self._click(lambda: self._click_file_browser_entry("0")),
                    ),
                ]
            )

            entries = self.file_browser.entries()
            for index, entry in enumerate(entries[:40], start=1):
                icon = "[D]" if entry.is_dir else "[F]"
                fragments.append(
                    (
                        "class:button",
                        f"    {index:>3}  {icon} {entry.label}\n",
                        self._click(
                            lambda selected_index=index: self._click_file_browser_entry(
                                str(selected_index)
                            )
                        ),
                    )
                )

            remaining = len(entries) - 40
            if remaining > 0:
                fragments.append(
                    (
                        "class:message.assistant.dim",
                        f"    ... {remaining} item lain disembunyikan; gunakan filter.\n",
                    )
                )
            if not entries:
                fragments.append(("class:message.assistant.dim", "    (kosong)\n"))
            fragments.append(("", "\n"))
            self._chat_line_count = _count_fragment_lines(fragments)
            self._apply_pending_scroll()
            return fragments

        if not self.session.messages:
            fragments = self._render_welcome()
            self._chat_line_count = _count_fragment_lines(fragments)
            self._apply_pending_scroll()
            return fragments

        fragments = [("", "\n")]
        content_width = max(24, self._chat_width() - 6)
        for index, message in enumerate(self.session.messages):
            selected = index == self.selected_message_index
            is_waiting_reply = self.streaming and index == len(self.session.messages) - 1
            editing = self.editing_message_index == index

            cache_key = (
                "chat",
                self.session.id,
                index,
                message.role,
                message.content,
                content_width,
                selected,
                editing,
                is_waiting_reply,
                self.cfg.show_thinking,
                (index in self.expanded_thinking_indices),
                message.token_usage.total_tokens if message.token_usage else None,
            )

            if cache_key in self._render_cache and not is_waiting_reply:
                msg_fragments = self._render_cache[cache_key]
            else:
                msg_fragments = []
                base_style = (
                    "class:message.user"
                    if message.role == "user"
                    else "class:message.assistant"
                )
                style = "class:message.selected" if selected else base_style
                label = "Anda" if message.role == "user" else "Asisten"
                label_icon = "●" if message.role == "user" else "◆"
                label_style = (
                    "class:message.label.user"
                    if message.role == "user"
                    else "class:message.label.assistant"
                )
                text = message.content
                if message.role == "assistant":
                    plain_answer = strip_think_tags(text, False)
                    # Auto-wrap raw HTML in code block if model forgot to use markdown
                    if "```" not in plain_answer and (
                        "<html" in plain_answer.lower() or "<!doctype" in plain_answer.lower()
                    ):
                        text = text.replace(plain_answer, f"```html\n{plain_answer}\n```")

                msg_fragments.append((label_style, f"    {label_icon} {label}"))
                if editing:
                    msg_fragments.append(("class:message.label.edit", "  edit"))

                handler = self._click(lambda i=index: self._select_message(i))
                if message.role == "assistant":
                    if not text.strip() and is_waiting_reply:
                        msg_fragments.extend(
                            _render_plain_message(
                                self._thinking_indicator(),
                                "class:message.thinking",
                                handler,
                                content_width,
                            )
                        )
                    else:
                        toggle_handler = self._click(lambda i=index: self._toggle_thinking(i))
                        msg_fragments.extend(
                            _render_assistant_sections(
                                text or "...",
                                self.cfg.show_thinking,
                                handler,
                                content_width,
                                is_expanded=(index in self.expanded_thinking_indices),
                                toggle_handler=toggle_handler,
                            )
                        )
                        if message.token_usage:
                            usage = message.token_usage
                            marker = "~" if usage.estimated else ""
                            msg_fragments.append(
                                (
                                    "class:message.meta",
                                    f"    Token: masuk {marker}{usage.input_tokens} | "
                                    f"keluar {marker}{usage.output_tokens} | "
                                    f"total {marker}{usage.total_tokens}\n",
                                )
                            )
                        msg_fragments.extend(self._render_message_actions(index))
                else:
                    msg_fragments.extend(_render_plain_message(text or "...", style, handler, content_width))
                
                if not is_waiting_reply:
                    self._render_cache[cache_key] = msg_fragments

            if index > 0:
                fragments.append(("", "\n"))
            fragments.extend(msg_fragments)

        fragments.append(("", "\n\n\n"))
        self._chat_line_count = _count_fragment_lines(fragments)
        self._apply_pending_scroll()
        return fragments

    def _thinking_indicator(self) -> str:
        """Return a simple spinner text for the thinking indicator."""
        return "Asisten sedang menyusun jawaban..."

    def _render_selectable_chat(self) -> list[tuple]:
        width = max(24, self._chat_width() - 2)
        fragments: list[tuple] = [("class:message.meta", "\nMode blok teks. F2 kembali.\n\n")]

        if not self.session.messages:
            fragments.append(("class:welcome.text", "  Belum ada pesan. Tekan F2 untuk kembali lalu mulai chat.\n"))
            return fragments

        for index, message in enumerate(self.session.messages):
            is_waiting_reply = self.streaming and index == len(self.session.messages) - 1
            cache_key = (
                "selectable",
                self.session.id,
                index,
                message.role,
                message.content,
                width,
                self.cfg.show_thinking,
                message.token_usage.total_tokens if message.token_usage else None,
            )

            if cache_key in self._render_cache and not is_waiting_reply:
                msg_fragments = self._render_cache[cache_key]
            else:
                msg_fragments = []
                label = "Anda" if message.role == "user" else "Asisten"
                label_style = (
                    "class:message.label.user"
                    if message.role == "user"
                    else "class:message.label.assistant"
                )
                msg_fragments.append((label_style, f"{label}:\n"))
                content = (
                    strip_think_tags(message.content, self.cfg.show_thinking)
                    if message.role == "assistant"
                    else message.content
                )
                msg_fragments.extend(
                    _render_selectable_text(content or "...", "class:message.assistant", width)
                )
                if message.token_usage:
                    usage = message.token_usage
                    marker = "~" if usage.estimated else ""
                    msg_fragments.append(
                        (
                            "class:message.meta",
                            f"Token: masuk {marker}{usage.input_tokens} | "
                            f"keluar {marker}{usage.output_tokens} | "
                            f"total {marker}{usage.total_tokens}\n",
                        )
                    )
                if not is_waiting_reply:
                    self._render_cache[cache_key] = msg_fragments

            if index > 0:
                fragments.append(("", "\n"))
            fragments.extend(msg_fragments)

        fragments.append(("", "\n"))
        return fragments

    def _render_message_actions(self, index: int) -> list[tuple]:
        selected = index == self.selected_message_index
        action_style = "class:button.hot" if selected else "class:button"
        meta = " aktif" if selected else ""
        return [
            ("", "    "),
            (
                action_style,
                " [⧉] ",
                self._click(lambda i=index: self._copy_message(i), "Salin jawaban"),
            ),
            ("", " "),
            (
                action_style,
                " [✎] ",
                self._click(lambda i=index: self._edit_message(i), "Edit jawaban"),
            ),
            ("", " "),
            (
                action_style,
                " [↻] ",
                self._click(
                    lambda i=index: self._regenerate_message(i),
                    "Generate ulang jawaban",
                ),
            ),
            ("class:message.meta", f" jawaban{meta}\n"),
        ]

    def _render_welcome(self) -> list[tuple]:
        width = self._chat_width()
        logo = TUI_LOGO if width >= max(len(line) for line in TUI_LOGO) else ["DJ CHAT AI"]
        intro = [
            "Chat terminal untuk Ollama, LocalAI, OpenAI, Gemini, dan DeepSeek",
            "",
            "Mulai dengan mengetik pesan di bawah, atau gunakan /file untuk membaca dokumen.",
            "",
            "Fitur baru: pakai /rename untuk mengganti judul chat aktif.",
        ]
        shortcuts = [
            ("Right/Ctrl-F", "terima suggestion"),
            ("Enter", "kirim pesan"),
            ("Ctrl-N", "chat baru"),
            ("Ctrl-Y", "copy pesan terpilih"),
            ("Ctrl-E", "edit pesan terpilih"),
            ("Ctrl-R", "generate ulang jawaban"),
            ("Esc", "hentikan jawaban AI"),
            ("F2", "toggle blok teks / klik"),
            ("PgUp/PgDn", "scroll chat"),
            ("Ctrl-Q", "keluar"),
        ]
        commands = [
            *self._command_rows(),
        ]

        fragments: list[tuple] = []
        fragments.extend(_center_lines(["", ""], width, "class:welcome.text"))
        fragments.extend(_center_lines(logo, width, "class:welcome.logo"))
        fragments.extend(
            _center_lines(
                ["", intro[0], "", intro[2], "", intro[4], ""],
                width,
                "class:welcome.title",
            )
        )
        fragments.extend(
            _center_help_table(
                "Shortcut",
                shortcuts,
                width,
                "class:welcome.key",
            )
        )
        fragments.extend(_center_lines([""], width, "class:welcome.text"))
        fragments.extend(
            _center_help_table(
                "Command",
                commands,
                width,
                "class:welcome.command",
            )
        )
        fragments.extend(
            _center_lines(["", "Ketik prompt di bawah untuk mulai chat."], width, "class:welcome.text")
        )
        return fragments

    def _render_toolbar(self) -> AnyFormattedText:
        if not self.mouse_enabled:
            return [
                ("class:toolbar", " "),
                ("class:button.hot", " MODE BLOK TEKS "),
                ("class:message.meta", " drag seleksi | F2 mode klik"),
            ]

        if self.streaming:
            return [
                (
                    "class:button.danger",
                    " [■] ",
                    self._click(self._cancel_stream, "Hentikan jawaban AI"),
                ),
                ("", "   "),
                ("class:message.meta", "AI sedang menjawab | Esc untuk hentikan"),
            ]

        return [
            (
                "class:button.hot",
                " [⧉] ",
                self._click(self._copy_selected, "Salin pesan terpilih"),
            ),
            ("", " "),
            (
                "class:button.hot",
                " [✎] ",
                self._click(self._edit_selected, "Edit pesan terpilih"),
            ),
            ("", " "),
            (
                "class:button.hot",
                " [⚙] ",
                self._click(self._edit_system_prompt, "Edit system global"),
            ),
            ("", " "),
            (
                "class:button.hot",
                " [✐] ",
                self._click(self._rename_session, "Ganti nama chat"),
            ),
            ("", " "),
            (
                "class:button.hot",
                " [▣] ",
                self._click(self._new_project_prompt, "Buat project baru"),
            ),
            ("", " "),
            (
                "class:button.hot",
                " [↻] ",
                self._click(self._regenerate_selected, "Generate ulang jawaban"),
            ),
            ("", " "),
            (
                "class:button.hot",
                " [⌑] ",
                self._click(self._pick_file_from_toolbar, "Buka file"),
            ),
            ("", " "),
            (
                "class:button",
                " [▤] ",
                self._click(lambda: self._set_mouse_mode(False), "Mode blok teks"),
            ),
            ("", " "),
            (
                "class:button",
                " [＋] ",
                self._click(self._new_session, "Buat chat baru"),
            ),
            ("", " "),
            (
                "class:button.danger",
                " [×] ",
                self._click(self._delete_current_session, "Hapus chat aktif"),
            ),
            ("", "   "),
            (
                "class:message.meta",
                "Ikon aksi | F2 blok teks | /help keterangan",
            ),
        ]

    async def run(self) -> None:
        online = await self.provider.health_check()
        if not online:
            self.status = (
                f"Tidak terhubung ke {self.cfg.provider} di {self.cfg.active_base_url}. "
                "Cek layanan atau pakai /status."
            )
        else:
            await self._refresh_models()
        monitor_task = asyncio.create_task(self._monitor_resources())
        try:
            await self.app.run_async()
        finally:
            monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await monitor_task

    async def _monitor_resources(self) -> None:
        while True:
            self.resource_stats = self.resource_monitor.sample()
            self.app.invalidate()
            await asyncio.sleep(1.0)


def _format_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%d/%m %H:%M")
    except ValueError:
        return value[:14]


def _count_fragment_lines(fragments: list[tuple]) -> int:
    return max(1, sum(str(fragment[1]).count("\n") for fragment in fragments))


def _center_lines(lines: list[str], width: int, style: str) -> list[tuple]:
    fragments: list[tuple] = []
    for line in lines:
        fragments.append((style, f"{line.center(width)}\n"))
    return fragments


def _center_help_table(
    title: str,
    rows: list[tuple[str, str]],
    width: int,
    label_style: str,
) -> list[tuple]:
    label_width = min(max(len(label) for label, _ in rows), 24)
    description_width = min(max(len(description) for _, description in rows), 30)
    table_width = min(width, label_width + 3 + description_width)
    padding = " " * max(0, (width - table_width) // 2)
    rule = "─" * table_width

    fragments: list[tuple] = []
    fragments.append(("class:welcome.text", padding))
    fragments.append(("class:welcome.title", f"{title.center(table_width)}\n"))
    fragments.append(("class:welcome.text", padding))
    fragments.append(("class:welcome.rule", f"{rule}\n"))

    for label, description in rows:
        fragments.append(("class:welcome.text", padding))
        fragments.append((label_style, f"{label:<{label_width}}"))
        fragments.append(("class:welcome.text", "   "))
        fragments.append(("class:welcome.text", f"{description}\n"))

    return fragments


_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_INLINE_MARKDOWN = re.compile(r"`([^`]+)`|(\*\*|__)(.+?)\2")


def _render_plain_message(text: str, style: str, handler, width: int) -> list[tuple]:
    fragments: list[tuple] = []
    for raw_line in text.splitlines() or [""]:
        for line in _wrap_visual_line(raw_line, width):
            fragments.append((style, f"    {line}\n", handler))
    return fragments


def _render_selectable_text(text: str, style: str, width: int) -> list[tuple]:
    fragments: list[tuple] = []
    for raw_line in text.splitlines() or [""]:
        clean_line = _strip_inline_markdown(raw_line)
        for line in _wrap_visual_line(clean_line, width):
            fragments.append((style, f"{line}\n"))
    return fragments


def _render_markdown_message(text: str, handler, width: int) -> list[tuple]:
    fragments: list[tuple] = []
    lines = text.splitlines() or [""]
    index = 0

    while index < len(lines):
        line = lines[index]

        if line.strip().startswith("```"):
            language = line.strip()[3:].strip()
            block: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            fragments.extend(_render_code_block(block, language, handler, width))
            continue

        if _is_table_start(lines, index):
            table_lines = [lines[index], lines[index + 1]]
            index += 2
            while index < len(lines) and _looks_like_table_row(lines[index]):
                table_lines.append(lines[index])
                index += 1
            fragments.extend(_render_table(table_lines, handler, width))
            continue

        fragments.extend(_render_markdown_line(line, handler, width))
        index += 1

    return fragments


def _render_assistant_sections(
    text: str,
    show_thinking: bool,
    handler,
    width: int,
    is_expanded: bool = False,
    toggle_handler = None,
) -> list[tuple]:
    if not show_thinking:
        answer = strip_think_tags(text, False)
        return _render_answer_block(answer or "...", handler, width)

    sections = split_think_sections(text)
    fragments: list[tuple] = []
    answer_parts: list[str] = []
    has_thinking = False

    for kind, content in sections:
        content = content.strip()
        if not content:
            continue
        if kind == "thinking":
            content = sanitize_visible_thinking(content)
            if not content:
                continue
            has_thinking = True
            fragments.extend(_render_thinking_block(content, handler, width, is_expanded, toggle_handler))
        else:
            content = sanitize_assistant_output(content)
            if content:
                answer_parts.append(content)

    answer = "\n\n".join(answer_parts).strip()
    if answer:
        if has_thinking:
            fragments.extend(_render_section_divider(width, handler))
        fragments.extend(_render_answer_block(answer, handler, width, title="Jawaban utama" if has_thinking else "Jawaban"))

    if not fragments:
        fragments.extend(_render_answer_block("...", handler, width))
    return fragments


def _render_answer_block(
    text: str,
    handler,
    width: int,
    *,
    title: str = "Jawaban",
) -> list[tuple]:
    inner_width = max(24, width - 8)
    icon = "💡 " if title == "Jawaban utama" else ""
    title_text = f" {icon}{title} "
    title_len = len(title_text)
    rule_width = max(0, inner_width - title_len - 2)
    fragments: list[tuple] = [("", "\n")]
    fragments.append(("class:answer.border", "    ╔═", handler))
    fragments.append(("class:answer.title",  title_text, handler))
    fragments.append(("class:answer.border", f"{'═' * rule_width}╗\n", handler))
    fragments.extend(_render_markdown_message(text, handler, inner_width))
    fragments.append(("class:answer.border", f"    ╚═{'═' * inner_width}═╝\n", handler))
    return fragments


def _render_section_divider(width: int, handler) -> list[tuple]:
    """Render a visual separator between thinking and answer blocks."""
    inner_width = max(20, width - 8)
    sep_char = "╌"
    label = " ▼ "
    left_pad = max(0, (inner_width - len(label)) // 2)
    right_pad = max(0, inner_width - len(label) - left_pad)
    fragments: list[tuple] = [
        ("class:thinking.separator", f"    {sep_char * (left_pad + 2)}", handler),
        ("class:answer.title",       label,                               handler),
        ("class:answer.separator",   f"{sep_char * (right_pad + 2)}\n",  handler),
    ]
    return fragments


def _render_thinking_block(text: str, handler, width: int, is_expanded: bool = False, toggle_handler = None) -> list[tuple]:
    inner_width = max(20, width - 8)
    click_target = toggle_handler or handler

    if not is_expanded:
        title_label = " ▶ 🧠 Proses berpikir "
        title_len = len(" ▶ 🧠 Proses berpikir ")  # ambiguous width workaround
        right_dashes = max(0, inner_width - title_len)
        fragments: list[tuple] = [("", "\n")]
        fragments.append(("class:thinking.border", "    ╔═", click_target))
        fragments.append(("class:thinking.title",  title_label, click_target))
        fragments.append(("class:thinking.border", f"{'═' * right_dashes}╗\n", click_target))
        fragments.append(("class:thinking.border", f"    ╚═{'═' * inner_width}═╝\n", click_target))
        return fragments

    title_label = " ▼ 🧠 Proses berpikir "
    title_len = len(" ▼ 🧠 Proses berpikir ")  # ambiguous width workaround
    right_dashes = max(0, inner_width - title_len)
    fragments: list[tuple] = [("", "\n")]
    fragments.append(("class:thinking.border", "    ╔═", click_target))
    fragments.append(("class:thinking.title",  title_label, click_target))
    fragments.append(("class:thinking.border", f"{'═' * right_dashes}╗\n", click_target))

    lines: list[str] = []
    for raw_line in text.splitlines() or [text]:
        wrapped = _wrap_visual_line(raw_line.strip(), inner_width) or [""]
        lines.extend(wrapped)

    for line in lines:
        fragments.append(("class:thinking.border", "    ║ ", handler))
        fragments.append(("class:thinking.body", f"{line:<{inner_width}}", handler))
        fragments.append(("class:thinking.border", " ║\n", handler))

    fragments.append(("class:thinking.border", f"    ╚═{'═' * inner_width}═╝\n", click_target))
    return fragments


def _render_code_block(lines: list[str], language: str, handler, max_width: int = 120) -> list[tuple]:
    usable_width = max(20, max_width - 6)
    
    label_text = language
    if not language:
        # Heuristik sederhana untuk mendeteksi lirik lagu
        content_lower = "\n".join(lines[:5]).lower()
        if any(w in content_lower for w in ["judul lagu", "intro", "verse", "chorus", "reff", "kunci dasar"]):
            label_text = "lirik"
        else:
            label_text = "teks"
            
    label = f" {label_text} "

    # Wrap baris yang terlalu panjang
    wrapped_lines: list[str] = []
    for line in (lines or [""]):
        if len(line) <= usable_width:
            wrapped_lines.append(line)
        else:
            # Potong tiap usable_width karakter
            while len(line) > usable_width:
                wrapped_lines.append(line[:usable_width])
                line = line[usable_width:]
            if line:
                wrapped_lines.append(line)

    width = min(max(len(l) for l in wrapped_lines + [label, ""]) , usable_width)
    fragments: list[tuple] = []

    fragments.append(("class:answer.border", "    │ ", handler))
    fragments.append(("class:markdown.code.border", "┌─", handler))
    fragments.append(("class:markdown.code.lang", label, handler))
    fragments.append(("class:markdown.code.border", "─" * max(width - len(label), 0), handler))
    fragments.append(("class:markdown.code.border", "─┐\n", handler))

    for line in wrapped_lines:
        fragments.append(("class:answer.border", "    │ ", handler))
        fragments.append(("class:markdown.code.border", "│ ", handler))
        fragments.append(("class:markdown.code", f"{line:<{width}}", handler))
        fragments.append(("class:markdown.code.border", " │\n", handler))

    fragments.append(("class:answer.border", "    │ ", handler))
    fragments.append(("class:markdown.code.border", f"└─{'─' * width}─┘\n", handler))
    return fragments


def _render_table(lines: list[str], handler, width: int) -> list[tuple]:
    rows = [_split_table_row(line) for line in lines if _looks_like_table_row(line)]
    if len(rows) < 2:
        return _render_markdown_line(lines[0], handler, width)

    header = rows[0]
    separator = rows[1] if _is_table_separator_row(rows[1]) else []
    body = rows[2:] if separator else rows[1:]
    column_count = max(len(row) for row in [header, *body])
    header = _clean_table_row(_pad_row(header, column_count))
    separator = _pad_row(separator, column_count) if separator else []
    body = [_clean_table_row(_pad_row(row, column_count)) for row in body]
    widths = [
        max(len(row[column]) for row in [header, *body])
        for column in range(column_count)
    ]
    widths = _fit_table_width(widths, max(20, width - 1))
    alignments = [_table_alignment(cell) for cell in separator]
    if not alignments:
        alignments = ["left"] * column_count

    fragments: list[tuple] = []
    fragments.extend(_render_table_border("┌", "┬", "┐", widths, handler))
    fragments.extend(
        _render_table_row(
            header, widths, alignments, "class:markdown.table.header", handler
        )
    )
    fragments.extend(_render_table_border("├", "┼", "┤", widths, handler))
    for row in body:
        fragments.extend(
            _render_table_row(row, widths, alignments, "class:markdown.table", handler)
        )
    fragments.extend(_render_table_border("└", "┴", "┘", widths, handler))
    return fragments


def _clean_table_row(row: list[str]) -> list[str]:
    return [_strip_inline_markdown(cell) for cell in row]


def _render_table_border(
    left: str, join: str, right: str, widths: list[int], handler
) -> list[tuple]:
    cells = [("─" * (width + 2)) for width in widths]
    return [
        ("class:answer.border", "    │ ", handler),
        ("class:markdown.table.border", f"{left}{join.join(cells)}{right}\n", handler)
    ]


def _render_table_row(
    row: list[str],
    widths: list[int],
    alignments: list[str],
    style: str,
    handler,
) -> list[tuple]:
    wrapped_cells = [
        _wrap_visual_line(cell, width) for cell, width in zip(row, widths)
    ]
    row_height = max(len(cell_lines) for cell_lines in wrapped_cells)
    fragments: list[tuple] = []

    for line_index in range(row_height):
        fragments.extend(
            [
                ("class:answer.border", "    │ ", handler),
                ("class:markdown.table.border", "│", handler),
            ]
        )
        for cell_lines, width, alignment in zip(wrapped_cells, widths, alignments):
            cell = cell_lines[line_index] if line_index < len(cell_lines) else ""
            fragments.append(
                (style, f" {_align_table_cell(cell, width, alignment)} ", handler)
            )
            fragments.append(("class:markdown.table.border", "│", handler))
        fragments.append(("", "\n", handler))
    return fragments


def _render_markdown_line(line: str, handler, width: int) -> list[tuple]:
    stripped = line.strip()
    if not stripped:
        return [
            ("class:answer.border", "    │", handler),
            ("", "\n", handler),
        ]

    style = "class:message.assistant"
    prefix = "    │ "
    continuation_prefix = "    │ "
    content = line

    if stripped.startswith("#"):
        level = len(stripped) - len(stripped.lstrip("#"))
        if 1 <= level <= 6 and stripped[level : level + 1] == " ":
            style = "class:markdown.heading"
            content = stripped[level:].strip().upper() if level == 1 else stripped[level:].strip()
            prefix = "    │ "
            continuation_prefix = "    │ "
    elif stripped.startswith(">"):
        style = "class:markdown.quote"
        content = "│ " + stripped.lstrip(">").strip()
        continuation_prefix = "    │ │ "
    elif re.match(r"^[-*+]\s+", stripped):
        style = "class:markdown.list"
        content = stripped[2:].strip()
        continuation_prefix = "    │    "
    elif re.match(r"^\d+\.\s+", stripped):
        style = "class:markdown.list"
        content = stripped
        continuation_prefix = "    │    "

    fragments: list[tuple] = []
    visual_lines = _wrap_visual_line(content, max(12, width - len(prefix)))
    for line_index, visual_line in enumerate(visual_lines):
        line_prefix = prefix if line_index == 0 else continuation_prefix
        fragments.append(("class:answer.border", line_prefix[:6], handler))
        if re.match(r"^[-*+]\s+", stripped) and line_index == 0:
            fragments.append(("class:markdown.list.marker", "• ", handler))
        elif line_prefix[6:]:
            fragments.append((style, line_prefix[6:], handler))
        fragments.extend(_render_inline_markdown(visual_line, style, handler))
        fragments.append(("", "\n", handler))
    return fragments


def _fit_table_width(widths: list[int], max_width: int) -> list[int]:
    if not widths:
        return widths
    border_width = (3 * len(widths)) + 1
    available = max(6 * len(widths), max_width - border_width)
    fitted = [min(max(width, 4), 32) for width in widths]
    while sum(fitted) > available and max(fitted) > 6:
        largest = max(range(len(fitted)), key=fitted.__getitem__)
        fitted[largest] -= 1
    return fitted


def _table_alignment(separator_cell: str) -> str:
    cell = separator_cell.strip()
    if cell.startswith(":") and cell.endswith(":"):
        return "center"
    if cell.endswith(":"):
        return "right"
    return "left"


def _align_table_cell(text: str, width: int, alignment: str) -> str:
    if alignment == "right":
        return f"{text:>{width}}"
    if alignment == "center":
        return f"{text:^{width}}"
    return f"{text:<{width}}"


def _wrap_visual_line(text: str, width: int) -> list[str]:
    if not text:
        return [""]
    w = max(8, width)
    # Coba wrap normal dulu (pertahankan kata utuh)
    result = wrap(
        text,
        width=w,
        break_long_words=False,
        break_on_hyphens=False,
        replace_whitespace=False,
        drop_whitespace=True,
    )
    if result:
        # Jika ada baris yang masih terlalu panjang (mis. URL tanpa spasi),
        # paksa potong per-karakter
        final: list[str] = []
        for line in result:
            while len(line) > w:
                final.append(line[:w])
                line = line[w:]
            final.append(line)
        return final
    # Fallback: potong mentah per-karakter
    chunks: list[str] = []
    while len(text) > w:
        chunks.append(text[:w])
        text = text[w:]
    chunks.append(text)
    return chunks


def _render_inline_markdown(text: str, base_style: str, handler) -> list[tuple]:
    fragments: list[tuple] = []
    position = 0
    for match in _INLINE_MARKDOWN.finditer(text):
        if match.start() > position:
            fragments.append((base_style, text[position : match.start()], handler))
        if match.group(1) is not None:
            fragments.append(("class:markdown.inline_code", f" {match.group(1)} ", handler))
        else:
            fragments.append(("class:markdown.bold", match.group(3), handler))
        position = match.end()
    if position < len(text):
        fragments.append((base_style, text[position:], handler))
    return fragments


def _strip_inline_markdown(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        if match.group(1) is not None:
            return match.group(1)
        return match.group(3)

    return _INLINE_MARKDOWN.sub(replace, text)


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return _looks_like_table_row(lines[index]) and _TABLE_SEPARATOR.match(lines[index + 1]) is not None


def _looks_like_table_row(line: str) -> bool:
    return "|" in line and len(_split_table_row(line)) >= 2


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_separator_row(row: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in row)


def _pad_row(row: list[str], column_count: int) -> list[str]:
    return row + [""] * (column_count - len(row))
