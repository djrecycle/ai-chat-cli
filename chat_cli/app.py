"""Main chat application loop."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from rich.live import Live
from rich.text import Text

from .config import (
    CONFIG_DIR,
    AppConfig,
    DEFAULT_SYSTEM_PROMPT,
    PROVIDER_HELP_TEXT,
    load_config,
    save_config,
)
from .document_loader import (
    IMAGE_EXTENSIONS,
    DocumentLoadError,
    build_document_prompt,
    build_image_message,
    load_document,
)
from .providers import ChatMessage, DeepSeekProvider, GeminiProvider, LocalAIProvider, OllamaProvider, OpenAIProvider, TokenUsage, estimate_token_usage
from .providers.base import ChatProvider
from .suggestions import ChatAutoSuggest
from .terminal_file_browser import FileBrowserState, handle_browser_input, render_browser_lines
from . import ui


class ChatApp:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.history: list[ChatMessage] = []
        self.provider = self._make_provider()
        history_path = CONFIG_DIR / "input_history"
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.session = PromptSession(
            history=FileHistory(str(history_path)),
            auto_suggest=ChatAutoSuggest(),
            multiline=False,
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

    def _rebuild_provider(self) -> None:
        self.provider = self._make_provider()

    def _api_messages(self) -> list[ChatMessage]:
        system_prompt = ui.with_response_format_prompt(
            ui.with_visible_thinking_prompt(
                self.cfg.system_prompt,
                self.cfg.show_thinking,
            )
        )
        msgs = [ChatMessage("system", system_prompt)]
        msgs.extend(
            ChatMessage(
                message.role,
                ui.strip_think_tags(message.content, False)
                if message.role == "assistant"
                else message.content,
                images=message.images,
            )
            for message in self.history
        )
        return msgs

    async def _stream_reply(self) -> str:
        from rich.box import SQUARE
        from rich.panel import Panel

        full = ""

        def render_panel() -> Panel:
            body = ui.render_assistant_response(full, show_thinking=self.cfg.show_thinking)
            return Panel(
                body,
                title="[bold #5eead4] Asisten [/]",
                border_style="#1f6f5b",
                box=SQUARE,
                padding=(0, 1),
            )

        with Live(
            render_panel(),
            console=ui.console,
            refresh_per_second=12,
            transient=False,
        ) as live:
            async for chunk in self.provider.chat_stream(
                self._api_messages(),
                model=self.cfg.active_model,
                temperature=self.cfg.temperature,
            ):
                full += chunk
                live.update(render_panel())

        return full

    def _reply_usage(self, reply: str) -> TokenUsage:
        return self.provider.last_usage or estimate_token_usage(
            self._api_messages(), reply
        )

    @staticmethod
    def _show_token_usage(usage: TokenUsage) -> None:
        marker = "~" if usage.estimated else ""
        ui.show_info(
            f"Token: masuk {marker}{usage.input_tokens} | "
            f"keluar {marker}{usage.output_tokens} | "
            f"total {marker}{usage.total_tokens}"
        )

    async def handle_message(self, user_input: str) -> bool:
        """Process user input. Returns False to exit."""
        text = user_input.strip()
        if not text:
            return True

        if text.startswith("/"):
            return await self._handle_command(text)

        ui.show_user_message(text)
        self.history.append(ChatMessage("user", text))

        try:
            ui.show_assistant_stream_start()
            reply = await self._stream_reply()
            usage = self._reply_usage(reply)
            self.history.append(ChatMessage("assistant", reply, token_usage=usage))
            self._show_token_usage(usage)
        except Exception as exc:
            ui.show_error(str(exc))
            self.history.pop()
        finally:
            ui.console.print()

        return True

    async def _handle_command(self, text: str) -> bool:
        parts = text.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd in ("/exit", "/quit", "/q"):
            ui.show_info("Sampai jumpa!")
            return False

        if cmd == "/help":
            ui.show_help()
            return True

        if cmd == "/clear":
            self.history.clear()
            ui.show_success("Riwayat percakapan dihapus.")
            return True

        if cmd == "/file":
            try:
                args = shlex.split(text)
            except ValueError as exc:
                ui.show_error(f"Format /file tidak valid: {exc}")
                return True

            if len(args) < 2 or args[1] in ("--browse", "-b"):
                selected_path = await self._pick_file_in_terminal()
                if selected_path is None:
                    ui.show_info("Pemilihan file dibatalkan.")
                    return True
                file_path = str(selected_path)
                question_parts = args[2:] if len(args) > 1 else []
            else:
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
                ui.show_error(str(exc))
                return True
            ui.show_user_message(f"/file {display_path}")
            self.history.append(message)
            try:
                ui.show_assistant_stream_start()
                reply = await self._stream_reply()
                usage = self._reply_usage(reply)
                self.history.append(ChatMessage("assistant", reply, token_usage=usage))
                self._show_token_usage(usage)
            except Exception as exc:
                ui.show_error(str(exc))
                self.history.pop()
            finally:
                ui.console.print()
            return True

        if cmd == "/models":
            try:
                models = await self.provider.list_models()
                ui.show_models(models, self.cfg.active_model)
            except Exception as exc:
                ui.show_error(f"Gagal mengambil model: {exc}")
            return True

        if cmd == "/model":
            if len(parts) < 2:
                ui.show_error("Gunakan: /model <nama>")
                return True
            self.cfg.set_model(parts[1])
            ui.show_success(f"Model → {self.cfg.active_model}")
            return True

        if cmd == "/provider":
            if len(parts) < 2:
                ui.show_error(f"Gunakan: /provider {PROVIDER_HELP_TEXT}")
                return True
            try:
                self.cfg.set_provider(parts[1].lower())
                self.provider = self._make_provider()
                ui.show_system(f"Provider aktif: {self.cfg.provider}")
            except ValueError as e:
                ui.show_error(str(e))
            return True

        if cmd == "/apikey":
            if len(parts) < 2:
                ui.show_error("Gunakan: /apikey <key>")
                return True
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
                ui.show_error("Provider ini tidak mendukung API key.")
                return True
            self.provider = self._make_provider()
            save_config(self.cfg)
            ui.show_system(f"API Key untuk {self.cfg.provider} telah disimpan.")
            return True

        if cmd == "/system":
            if len(parts) < 2 or (len(parts) == 2 and parts[1].lower() in ("show", "lihat", "active", "aktif")):
                ui.show_system_prompt(self.cfg.system_prompt)
                return True
            if len(parts) == 2 and parts[1].lower() in ("reset", "default"):
                self.cfg.system_prompt = DEFAULT_SYSTEM_PROMPT
                ui.show_success("System prompt dikembalikan ke default. Gunakan /save jika ingin permanen.")
                return True
            if len(parts) >= 3 and parts[1].lower() == "set":
                new_prompt = text[len("/system") :].strip()[4:].strip()
            else:
                new_prompt = text[len("/system"):].strip()
            if not new_prompt:
                ui.show_error("Gunakan: /system, /system reset, atau /system <prompt>")
                return True
            self.cfg.system_prompt = new_prompt
            ui.show_success("System prompt aktif diperbarui. Gunakan /save jika ingin permanen.")
            return True

        if cmd == "/save":
            save_config(self.cfg)
            ui.show_success(f"Konfigurasi disimpan → {CONFIG_DIR / 'config.json'}")
            return True

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
                    ui.show_error("Gunakan: /thinking on atau /thinking off")
                    return True
            save_config(self.cfg)
            state = "ditampilkan" if self.cfg.show_thinking else "disembunyikan"
            ui.show_success(f"Kerangka berpikir {state}.")
            return True

        if cmd == "/status":
            online = await self.provider.health_check()
            ui.show_status(
                self.cfg.provider,
                self.cfg.active_model,
                self.cfg.active_base_url,
                online,
                len(self.history),
            )
            return True

        ui.show_error(f"Perintah tidak dikenal: {cmd}. Ketik /help")
        return True

    async def _pick_file_in_terminal(self):
        state = FileBrowserState()
        while True:
            ui.console.print()
            for line in render_browser_lines(state):
                ui.console.print(line)
            try:
                choice = await self.session.prompt_async(
                    HTML('<style fg="#5eead4"> file </style><style fg="#c9d1d9">> </style>')
                )
            except (EOFError, KeyboardInterrupt):
                ui.console.print()
                return None

            selected, error = handle_browser_input(state, choice)
            if error == "cancel":
                return None
            if error:
                ui.show_error(error)
                continue
            if selected is not None:
                return selected

    async def run(self) -> None:
        online = await self.provider.health_check()
        if not online:
            ui.show_error(
                f"Tidak dapat terhubung ke {self.cfg.provider} di {self.cfg.active_base_url}.\n"
                "Pastikan layanan berjalan, lalu coba /status."
            )

        ui.show_banner(self.cfg.provider, self.cfg.active_model, self.cfg.active_base_url)
        ui.show_help()
        ui.show_info("Fitur baru: gunakan /system untuk melihat, mengubah, atau reset system prompt aktif.")
        ui.console.print()

        while True:
            try:
                user_input = await self.session.prompt_async(
                    HTML(
                        '<style fg="#676f80"> :chat </style> '
                        '<style fg="#c9d1d9"> </style>'
                    ),
                )
            except (EOFError, KeyboardInterrupt):
                ui.console.print()
                ui.show_info("Sampai jumpa!")
                break

            if not await self.handle_message(user_input):
                break


def main() -> None:
    from .cli import main as cli_main

    cli_main()
