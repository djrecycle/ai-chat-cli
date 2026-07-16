"""Input auto suggestions for chat prompts."""

from __future__ import annotations

from prompt_toolkit.auto_suggest import AutoSuggest, AutoSuggestFromHistory, Suggestion
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document


COMMAND_SUGGESTIONS = [
    "/file",
    "/file --browse jelaskan poin pentingnya",
    "/file ./README.md ringkas isi dokumen ini",
    "/file ./laporan.docx ambil poin penting",
    "/file ./kontrak.pdf jelaskan risiko utama",
    "/file ./gambar.jpg baca teks pada gambar",
    "/help",
    "/new",
    "/delete",
    "/rename Judul chat saya",
    "/project",
    "/project new Nama project",
    "/project move Nama project",
    "/project rename Nama project baru",
    "/project delete confirm",
    "/models",
    "/models all",
    "/model qwen2.5:1.5b",
    "/provider ollama",
    "/provider localai",
    "/provider openai",
    "/provider gemini",
    "/provider deepseek",
    "/apikey ",
    "/clear",
    "/regen",
    "/stop",
    "/mouse on",
    "/mouse off",
    "/system",
    "/system show",
    "/system reset",
    "/system Kamu adalah asisten AI yang ramah dan membantu.",
    "/thinking on",
    "/thinking off",
    "/status",
    "/save",
    "/exit",
]


class ChatAutoSuggest(AutoSuggest):
    """Suggest slash commands first, then fall back to prompt history."""

    def __init__(self) -> None:
        self._history = AutoSuggestFromHistory()

    def get_suggestion(self, buffer: Buffer, document: Document) -> Suggestion | None:
        text = document.text_before_cursor
        if "\n" in text:
            return None

        stripped = text.lstrip()
        leading_spaces = len(text) - len(stripped)
        if stripped.startswith("/"):
            command_suggestion = _match_command(stripped)
            if command_suggestion:
                suggestion_text = command_suggestion[len(stripped) :]
                if suggestion_text:
                    return Suggestion(suggestion_text)
            if leading_spaces:
                return None

        return self._history.get_suggestion(buffer, document)


def _match_command(text: str) -> str | None:
    lowered = text.lower()
    for command in COMMAND_SUGGESTIONS:
        if command.lower().startswith(lowered) and command != text:
            return command
    return None
