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
    rows = [
        ("/file <path> [pertanyaan]", "Baca file lokal lalu tanyakan isinya"),
        ("/help", "Tampilkan bantuan"),
        ("/exit, /quit", "Keluar"),
        ("/clear", "Hapus riwayat percakapan"),
        ("/models", "Daftar model tersedia"),
        ("/model <nama>", "Ganti model"),
        ("/provider ollama|localai|openai|gemini", "Ganti backend"),
        ("/apikey <key>", "Set API key untuk backend aktif"),
        ("/system <teks>", "Ubah system prompt"),
        ("/thinking on|off", "Tampilkan/sembunyikan proses berpikir"),
        ("/save", "Simpan konfigurasi"),
        ("/status", "Info koneksi & pengaturan"),
    ]
    body = Text()
    for cmd, desc in rows:
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
    "Untuk setiap jawaban, awali dengan tag <think> berisi 2-4 poin singkat "
    "tentang proses menyusun jawaban yang aman ditampilkan. Jangan tulis "
    "penalaran internal panjang. Setelah </think>, lanjutkan jawaban utama."
)

_THINK_OPEN = re.compile(r"<\s*think\b[^>]*>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"<\s*/\s*think\s*>", re.IGNORECASE)


def with_visible_thinking_prompt(system_prompt: str, show_thinking: bool) -> str:
    if not show_thinking:
        return system_prompt
    return f"{system_prompt.rstrip()}\n\n{VISIBLE_THINKING_INSTRUCTION}"


def split_think_sections(text: str) -> list[tuple[str, str]]:
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


def strip_think_tags(text: str, show_thinking: bool) -> str:
    sections = split_think_sections(text)
    if not show_thinking:
        return "".join(content for kind, content in sections if kind == "answer").strip()

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
            formatted.append(f"### Proses berpikir\n{content}")
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
        answer = "".join(
            content for kind, content in sections if kind == "answer"
        ).strip()
        return render_assistant_markdown(answer or "_Berpikir..._")

    renderables = []
    answer_parts: list[str] = []
    for kind, content in sections:
        content = content.strip()
        if not content:
            continue
        if kind == "thinking":
            renderables.append(
                Panel(
                    render_assistant_markdown(content),
                    title="[bold #fe8019] Proses berpikir [/]",
                    border_style="#7c4f1d",
                    box=box.SQUARE,
                    padding=(0, 1),
                )
            )
        else:
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
