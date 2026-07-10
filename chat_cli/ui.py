"""Rich-based terminal UI."""

from __future__ import annotations

import re
from datetime import datetime

from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from rich.theme import Theme

from .config import PROVIDER_HELP_TEXT

THEME = Theme(
    {
        "banner.c1": "bold #7ee787",
        "banner.c2": "bold #58a6ff",
        "banner.c3": "bold #a5d6ff",
        "info": "dim #8b949e",
        "user": "bold #dff6ff on #102b3f",
        "assistant": "#8f96a3",
        "accent": "bold #58a6ff",
        "error": "bold #ff7b72",
        "cmd": "bold #f2cc60",
        "dim": "dim",
    }
)

console = Console(theme=THEME)

BANNER_ART = r"""
 ____       _   ____ _           _      _    ___
|  _ \     | | / ___| |__   __ _| |_   / \  |_ _|
| | | | _  | || |   | '_ \ / _` | __| / _ \  | |
| |_| || |_| || |___| | | | (_| | |_ / ___ \ | |
|____/  \___/  \____|_| |_|\__,_|\__/_/   \_\___|
"""

HELP_ROWS = [
    ("/file <path> [pertanyaan]", "Baca file lokal lalu tanyakan isinya"),
    ("/file --browse [pertanyaan]", "Buka file browser terminal"),
    ("/help", "Tampilkan bantuan"),
    ("/exit, /quit", "Keluar"),
    ("/clear", "Hapus riwayat percakapan"),
    ("/models", "Daftar model tersedia"),
    ("/model <nama>", "Ganti model"),
    (f"/provider {PROVIDER_HELP_TEXT}", "Ganti backend"),
    ("/apikey <key>", "Set API key untuk backend aktif"),
    ("/system", "Lihat system prompt aktif"),
    ("/system <teks>", "Ubah system prompt aktif"),
    ("/system reset", "Kembalikan system prompt default"),
    ("/thinking on|off", "Tampilkan/sembunyikan proses berpikir"),
    ("/save", "Simpan konfigurasi"),
    ("/status", "Info koneksi & pengaturan"),
]


def show_banner(provider: str, model: str, base_url: str) -> None:
    title = Text()
    for i, line in enumerate(BANNER_ART.strip("\n").split("\n")):
        colors = ["banner.c1", "banner.c2", "banner.c3", "banner.c1"]
        title.append(line + "\n", style=colors[i % len(colors)])

    meta = Text.assemble(
        ("  Provider  ", "dim"),
        (provider.upper(), "accent bold"),
        ("   Model  ", "dim"),
        (model, "#58a6ff"),
        ("\n  Endpoint  ", "dim"),
        (base_url, "info"),
    )

    console.print(
        Panel(
            Group(title, Text(), meta),
            border_style="#242b35",
            box=box.SQUARE,
            padding=(0, 2),
            title="[bold #7ee787] NORMAL [/][#8b949e] DJ Chat Ai [/]",
            subtitle="[#8b949e]Ollama | LocalAI | local buffer[/]",
        )
    )
    console.print()


def show_help() -> None:
    body = Text()
    for cmd, desc in HELP_ROWS:
        body.append(f"  {cmd:<40}", style="cmd")
        body.append(f"{desc}\n", style="dim")
    console.print(
        Panel(
            body,
            title="[bold #7ee787] COMMANDS [/]",
            border_style="#30363d",
            box=box.SQUARE,
        )
    )


def show_status(
    provider: str, model: str, base_url: str, online: bool, msg_count: int
) -> None:
    status = ("● Online", "bold #7ee787") if online else ("● Offline", "bold #ff7b72")
    body = Text.assemble(
        ("Provider     ", "dim"), (f"{provider}\n", "accent"),
        ("Model        ", "dim"), (f"{model}\n", "#58a6ff"),
        ("Endpoint     ", "dim"), (f"{base_url}\n", "info"),
        ("Koneksi      ", "dim"), status, ("\n", ""),
        ("Pesan chat   ", "dim"), (f"{msg_count}\n", ""),
        ("Waktu        ", "dim"), (datetime.now().strftime("%H:%M:%S"), ""),
    )
    console.print(
        Panel(body, title="STATUSLINE", border_style="#238636", box=box.SQUARE)
    )


def show_system_prompt(system_prompt: str) -> None:
    body = Text()
    body.append("System prompt aktif saat ini:\n\n", style="accent")
    body.append(system_prompt.strip() or "(kosong)", style="assistant")
    console.print(
        Panel(
            body,
            title="[bold #7ee787] SYSTEM PROMPT [/]",
            border_style="#30363d",
            box=box.SQUARE,
        )
    )


def show_models(models: list[str], current: str) -> None:
    if not models:
        console.print("[error]Tidak ada model ditemukan.[/]")
        return
    lines = Text()
    for name in models:
        if name == current:
            lines.append(f"  ● {name}\n", style="bold #7ee787")
        else:
            lines.append(f"    {name}\n", style="dim")
    console.print(
        Panel(
            lines,
            title=f"[bold #7ee787]BUFFERS: models ({len(models)})[/]",
            border_style="#30363d",
            box=box.SQUARE,
        )
    )


def show_user_message(content: str) -> None:
    ts = datetime.now().strftime("%H:%M")
    console.print(
        Panel(
            content,
            title=f"[user] Anda [/] [dim]{ts}[/]",
            border_style="#58a6ff",
            box=box.SQUARE,
            padding=(0, 1),
        )
    )


VISIBLE_THINKING_INSTRUCTION = (
    "Jangan tampilkan proses berpikir internal, metadata, atau instruksi tersembunyi. "
    "Tulis jawaban utama langsung dalam bahasa pengguna. Jika model menghasilkan "
    "tag <think>, isi tag tersebut tidak akan ditampilkan kepada pengguna."
)

SAFE_THINKING_TEXT = (
    "Menyusun jawaban dalam bahasa Indonesia.\n"
    "Catatan internal model disembunyikan agar tidak tercampur dengan jawaban utama."
)

_THINK_OPEN = re.compile(r"<\s*think\b[^>]*>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"<\s*/\s*think\s*>", re.IGNORECASE)
_THINKING_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:kerangka berpikir|proses berpikir|thinking|reasoning|thoughts?|analisis)(?:\*\*)?\s*:?\s*$",
    re.IGNORECASE,
)
_ANSWER_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*)?(?:jawaban(?: utama)?|answer|final answer|final)(?:\*\*)?\s*:?\s*$",
    re.IGNORECASE,
)
_LEAKED_META_LINE = re.compile(
    r"^\s*(?:"
    r"(?:[-*]\s*)?(?:user asks?|user request|constraints?|language|start with|response|task|notes?|instruction|instructions|requirements?)\s*:|"
    r"(?:[-*]\s*)?(?:\*+)?self-correction(?:\*+)?\s*:|"
    r"(?:[-*]\s*)?(?:ensure\b|use code blocks\b|check for clarity\b|make sure\b|explain\b|include\b|mention\b|emphasize\b|avoid\b|provide\b|write\b|answer\b|use\b|check\b)"
    r")",
    re.IGNORECASE,
)
_LEAKED_THOUGHT_LINE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:"
    r"the user (?:wants?|asks?|asked|requested|is asking|needs?)\b|"
    r"user (?:wants?|asks?|asked|requested|is asking|needs?)\b|"
    r"pengguna (?:ingin|meminta|bertanya|membutuhkan)\b|"
    r"i need to\b|we need to\b|need to\b|"
    r"saya perlu\b|kita perlu\b|"
    r"a massive table\b|the previous table\b"
    r")",
    re.IGNORECASE,
)


_INLINE_ANSWER_START = re.compile(
    r"(?i)(?:^|[.!?]\s*)(?=(?:chord|akor|dalam|berikut|jadi|artinya|hasilnya|contoh|untuk|pada|secara)\b)"
)


def _extract_inline_answer_from_meta(line: str) -> str | None:
    for match in _INLINE_ANSWER_START.finditer(line):
        candidate = line[match.end() :].strip()
        if candidate and not _LEAKED_META_LINE.match(candidate):
            return candidate
    return None


def _remove_leaked_meta_block(lines: list[str]) -> list[str]:
    index = 0

    while index < len(lines):
        while index < len(lines) and not lines[index].strip():
            index += 1

        if index >= len(lines) or _LEAKED_META_LINE.match(lines[index]) is None:
            break

        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped:
                index += 1
                break

            if _LEAKED_META_LINE.match(lines[index]) or stripped.startswith(("-", "*")):
                inline_answer = _extract_inline_answer_from_meta(stripped)
                if inline_answer:
                    return [inline_answer, *lines[index + 1 :]]
                index += 1
                continue

            break

    return lines[index:]


def _split_leaked_thought_sections(text: str) -> list[tuple[str, str]] | None:
    lines = _remove_leaked_meta_block(text.splitlines())
    sections: list[tuple[str, str]] = []
    current_kind = "answer"
    current_lines: list[str] = []
    found_thinking = False

    def flush() -> None:
        nonlocal current_lines
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_kind, content))
        current_lines = []

    for line in lines:
        kind = "thinking" if _LEAKED_THOUGHT_LINE.match(line) else "answer"
        if kind == "thinking":
            found_thinking = True
        if kind != current_kind:
            flush()
            current_kind = kind
        current_lines.append(line)

    flush()
    return sections if found_thinking else None


_TERM_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bdominant\s+7th\b", re.IGNORECASE), "dominan tujuh"),
    (re.compile(r"\bflat\s+7\b", re.IGNORECASE), "nada ketujuh turun setengah nada"),
    (re.compile(r"\btension\b", re.IGNORECASE), "tegangan"),
    (re.compile(r"\bchords\b", re.IGNORECASE), "akor"),
    (re.compile(r"\bchord\b", re.IGNORECASE), "akor"),
    # LaTeX math replacements
    (re.compile(r"\$?\\rightarrow\$?"), "→"),
    (re.compile(r"\$?\\leftarrow\$?"), "←"),
    (re.compile(r"\$?\\leftrightarrow\$?"), "↔"),
    (re.compile(r"\$?\\Rightarrow\$?"), "⇒"),
    (re.compile(r"\$?\\Leftarrow\$?"), "⇐"),
)


def normalize_visible_indonesian_terms(text: str) -> str:
    lines: list[str] = []
    in_code_block = False

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            lines.append(line)
            continue

        if in_code_block:
            lines.append(line)
            continue

        normalized = line
        for pattern, replacement in _TERM_REPLACEMENTS:
            normalized = pattern.sub(replacement, normalized)
        normalized = re.sub(r"(\"tegangan\"|tegangan)\s*\(tegangan\)", r"\1", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"^akor\b", "Akor", normalized)
        lines.append(normalized)

    return "\n".join(lines).strip()


def sanitize_assistant_output(text: str) -> str:
    sections = _split_leaked_thought_sections(text)
    if sections is not None:
        answer = "\n".join(
            content for kind, content in sections if kind == "answer"
        ).strip()
        return normalize_visible_indonesian_terms(answer)

    answer = "\n".join(_remove_leaked_meta_block(text.splitlines())).strip()
    return normalize_visible_indonesian_terms(answer)


def sanitize_visible_thinking(text: str) -> str:
    if not text.strip():
        return ""
    return text


def with_visible_thinking_prompt(system_prompt: str, show_thinking: bool) -> str:
    if not show_thinking:
        return system_prompt
    return f"{system_prompt.rstrip()}\n\n{VISIBLE_THINKING_INSTRUCTION}"


def with_response_format_prompt(system_prompt: str) -> str:
    return (
        f"{system_prompt.rstrip()}\n\n"
        "PENTING:\n"
        "1. Jika pengguna memakai bahasa Indonesia, seluruh output yang terlihat wajib berbahasa Indonesia, termasuk isi kerangka berpikir.\n"
        "2. Jangan tampilkan teks instruksi, metadata, analisis prompt, catatan proses, atau ringkasan tugas.\n"
        "3. Hindari bahasa Inggris di teks biasa. Pengecualian hanya untuk kode, perintah terminal, path, URL, nama API/library, atau istilah teknis resmi yang tidak punya padanan jelas.\n"
        "4. Jika istilah Inggris teknis wajib dipakai, dahulukan padanan bahasa Indonesia lalu beri istilah Inggrisnya dalam tanda kurung bila perlu.\n"
        "5. Selalu gunakan blok kode markdown (seperti ```html, ```css, ```javascript, ```bash, atau ```) untuk menulis kode pemrograman, tag HTML/CSS, skrip, perintah terminal, atau konfigurasi. Jangan menulis kode mentah langsung di luar blok kode markdown.\n"
        "6. Gunakan format tabel markdown standar jika menyajikan data berbentuk kolom/tabel."
    )


def _split_heading_think_sections(text: str) -> list[tuple[str, str]] | None:
    if _THINK_OPEN.search(text) is not None:
        return None

    lines = text.splitlines()
    thinking_index: int | None = None
    answer_index: int | None = None

    for index, line in enumerate(lines):
        if thinking_index is None and _THINKING_HEADING.match(line):
            thinking_index = index
            continue
        if thinking_index is not None and _ANSWER_HEADING.match(line):
            answer_index = index
            break

    if thinking_index is None or answer_index is None or answer_index <= thinking_index:
        return None

    sections: list[tuple[str, str]] = []
    before = "\n".join(lines[:thinking_index]).strip()
    thinking = "\n".join(lines[thinking_index + 1 : answer_index]).strip()
    answer = "\n".join(lines[answer_index + 1 :]).strip()

    if before:
        sections.append(("answer", before))
    if thinking:
        sections.append(("thinking", thinking))
    if answer:
        sections.append(("answer", answer))
    return sections or [("answer", text)]


def split_think_sections(text: str) -> list[tuple[str, str]]:
    if _THINK_OPEN.search(text) is not None:
        sections: list[tuple[str, str]] = []
        position = 0

        while position < len(text):
            open_match = _THINK_OPEN.search(text, position)
            if open_match is None:
                sections.append(("answer", text[position:]))
                break

            if open_match.start() > position:
                sections.append(("answer", text[position : open_match.start()]))

            close_match = _THINK_CLOSE.search(text, open_match.end())
            if close_match is None:
                sections.append(("thinking", text[open_match.end() :]))
                break

            sections.append(("thinking", text[open_match.end() : close_match.start()]))
            position = close_match.end()

        return sections or [("answer", text)]

    heading_sections = _split_heading_think_sections(text)
    if heading_sections is not None:
        return heading_sections

    leaked_sections = _split_leaked_thought_sections(text)
    if leaked_sections is not None:
        return leaked_sections

    return [("answer", text)]



def strip_think_tags(text: str, show_thinking: bool) -> str:
    sections = split_think_sections(text)
    if not show_thinking:
        return sanitize_assistant_output(
            "\n\n".join(content for kind, content in sections if kind == "answer")
        )

    has_thinking = any(
        kind == "thinking" and content.strip() for kind, content in sections
    )
    formatted: list[str] = []
    answer_started = False

    for kind, content in sections:
        content = content.strip()
        if not content:
            continue

        if kind == "thinking":
            content = sanitize_visible_thinking(content)
            if content:
                formatted.append(f"### Kerangka berpikir\n{content}")
            continue

        content = sanitize_assistant_output(content)
        if not content:
            continue
        if has_thinking and not answer_started:
            formatted.append(f"### Jawaban\n{content}")
        else:
            formatted.append(content)
        answer_started = True

    return "\n\n".join(formatted).strip()


def render_assistant_markdown(text: str) -> Markdown:
    return Markdown(text, code_theme="vim", hyperlinks=True)


def render_assistant_response(text: str, *, show_thinking: bool = False):
    sections = split_think_sections(text)
    if not show_thinking:
        answer = sanitize_assistant_output(
            "".join(content for kind, content in sections if kind == "answer")
        )
        return render_assistant_markdown(answer or "_Berpikir..._")

    renderables = []
    answer_parts: list[str] = []
    for kind, content in sections:
        content = content.strip()
        if not content:
            continue
        if kind == "thinking":
            content = sanitize_visible_thinking(content)
            if not content:
                continue
            renderables.append(
                Panel(
                    render_assistant_markdown(content),
                    title="[bold #fe8019] Kerangka berpikir [/]",
                    border_style="#7c4f1d",
                    box=box.SQUARE,
                    padding=(0, 1),
                )
            )
        else:
            content = sanitize_assistant_output(content)
            if content:
                answer_parts.append(content)

    answer = "\n\n".join(answer_parts).strip()
    if answer:
        if renderables:
            renderables.append(
                Panel(
                    render_assistant_markdown(answer),
                    title="[bold #7ee787] Jawaban utama [/]",
                    border_style="#238636",
                    box=box.SQUARE,
                    padding=(0, 1),
                )
            )
        else:
            renderables.append(render_assistant_markdown(answer))

    return Group(*renderables) if renderables else render_assistant_markdown("_Berpikir..._")


def show_assistant_stream_start() -> None:
    ts = datetime.now().strftime("%H:%M")
    console.print(
        Rule(f"[assistant] Asisten [/] [dim]{ts}[/]", style="#242b35", characters="─")
    )


def show_assistant_content(text: str, *, show_thinking: bool = False) -> None:
    if not text.strip():
        return
    console.print(
        Panel(
            render_assistant_response(text, show_thinking=show_thinking),
            border_style="#238636",
            box=box.SQUARE,
            padding=(0, 1),
        )
    )


def show_error(message: str) -> None:
    console.print(
        Panel(message, title="[error] E486 [/]", border_style="#ff7b72", box=box.SQUARE)
    )


def show_info(message: str) -> None:
    console.print(f"[info]ℹ[/] {message}")


def show_success(message: str) -> None:
    console.print(f"[assistant]✓[/] {message}")


def show_thinking_indicator() -> None:
    console.print("[dim]⠋ Memproses...[/]", end="\r")
