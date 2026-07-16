"""Click CLI for DJ Chat Ai."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from . import __version__
from . import ui
from .app import ChatApp
from .config import (
    CONFIG_DIR,
    CONFIG_FILE,
    AppConfig,
    SUPPORTED_PROVIDERS,
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
from .tui import TuiChatApp


def _apply_options(
    cfg: AppConfig,
    *,
    model: str | None,
    provider: str | None,
    temperature: float | None,
    system_prompt: str | None,
    show_thinking: bool | None,
) -> AppConfig:
    if model:
        cfg.set_model(model)
    if provider:
        try:
            cfg.set_provider(provider)
        except ValueError as exc:
            raise click.BadParameter(str(exc)) from exc
    if temperature is not None:
        cfg.temperature = temperature
    if system_prompt:
        cfg.system_prompt = system_prompt
    if show_thinking is not None:
        cfg.show_thinking = show_thinking
    return cfg


def _run_chat(cfg: AppConfig) -> None:
    try:
        asyncio.run(TuiChatApp(cfg).run())
    except KeyboardInterrupt:
        pass


async def _list_models(cfg: AppConfig) -> None:
    app = ChatApp(cfg)
    try:
        models = await app.provider.list_models()
        ui.show_models(models, cfg.active_model)
    except Exception as exc:
        ui.show_error(f"Gagal mengambil model: {exc}")
        raise SystemExit(1) from exc


async def _show_status(cfg: AppConfig) -> None:
    app = ChatApp(cfg)
    online = await app.provider.health_check()
    ui.show_status(
        cfg.provider,
        cfg.active_model,
        cfg.active_base_url,
        online,
        0,
    )
    if not online:
        raise SystemExit(1)


async def _ask_once(cfg: AppConfig, prompt: str, file_path: str | None = None) -> None:
    from .providers import ChatMessage

    app = ChatApp(cfg)
    online = await app.provider.health_check()
    if not online:
        ui.show_error(
            f"Tidak dapat terhubung ke {cfg.provider} di {cfg.active_base_url}."
        )
        raise SystemExit(1)

    if file_path:
        try:
            if cfg.provider in ("gemini", "ollama") and Path(file_path).suffix.lower() in IMAGE_EXTENSIONS:
                message = build_image_message(file_path, prompt)
                display_path = Path(file_path).expanduser()
                prompt = message.content
            else:
                document = load_document(file_path)
                prompt = build_document_prompt(document, prompt)
                message = ChatMessage("user", prompt)
                display_path = document.path
        except DocumentLoadError as exc:
            ui.show_error(str(exc))
            raise SystemExit(1) from exc
        ui.show_user_message(f"[file: {display_path}]\n{prompt.splitlines()[-1]}")
    else:
        ui.show_user_message(prompt)
        message = ChatMessage("user", prompt)
    app.history = [message]
    try:
        ui.show_assistant_stream_start()
        reply = await app._stream_reply()
        app._show_token_usage(app._reply_usage(reply))
    except Exception as exc:
        ui.show_error(str(exc))
        raise SystemExit(1) from exc
    finally:
        ui.console.print()


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.version_option(version=__version__, prog_name="DJ Chat Ai")
@click.option("-m", "--model", help="Model AI yang dipakai.")
@click.option(
    "-p",
    "--provider",
    type=click.Choice(SUPPORTED_PROVIDERS, case_sensitive=False),
    help="Backend AI (ollama, localai, openai, gemini, atau deepseek).",
)
@click.option("-t", "--temperature", type=float, help="Suhu sampling (0.0–2.0).")
@click.option("--system-prompt", help="System prompt untuk sesi ini.")
@click.option(
    "--show-thinking/--hide-thinking",
    default=None,
    help="Tampilkan blok thinking dari model.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    model: str | None,
    provider: str | None,
    temperature: float | None,
    system_prompt: str | None,
    show_thinking: bool | None,
) -> None:
    """DJ Chat Ai — chat AI multi-provider di terminal."""
    cfg = _apply_options(
        load_config(),
        model=model,
        provider=provider,
        temperature=temperature,
        system_prompt=system_prompt,
        show_thinking=show_thinking,
    )
    ctx.obj = cfg

    if ctx.invoked_subcommand is None:
        _run_chat(cfg)


@cli.command()
@click.pass_context
def chat(ctx: click.Context) -> None:
    """Mulai sesi chat interaktif."""
    _run_chat(ctx.obj)


@cli.command()
@click.option("--file", "file_path", type=click.Path(exists=True, dir_okay=False), help="Baca file lokal sebagai konteks pertanyaan.")
@click.argument("prompt")
@click.pass_context
def ask(ctx: click.Context, prompt: str, file_path: str | None) -> None:
    """Kirim satu pertanyaan tanpa mode interaktif."""
    try:
        asyncio.run(_ask_once(ctx.obj, prompt, file_path))
    except KeyboardInterrupt:
        pass


@cli.command("models")
@click.pass_context
def list_models(ctx: click.Context) -> None:
    """Tampilkan daftar model dari provider aktif."""
    asyncio.run(_list_models(ctx.obj))


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Cek koneksi ke provider dan pengaturan aktif."""
    asyncio.run(_show_status(ctx.obj))


@cli.command()
@click.option("--save", is_flag=True, help="Simpan path config default jika belum ada.")
@click.pass_context
def config(ctx: click.Context, save: bool) -> None:
    """Tampilkan lokasi file konfigurasi."""
    cfg: AppConfig = ctx.obj
    ui.console.print(f"Config dir : [cyan]{CONFIG_DIR}[/]")
    ui.console.print(f"Config file: [cyan]{CONFIG_FILE}[/]")
    if save:
        save_config(cfg)
        ui.show_success(f"Konfigurasi disimpan → {CONFIG_FILE}")


def main() -> None:
    try:
        cli(prog_name="aichat")
    except click.ClickException as exc:
        ui.show_error(str(exc))
        sys.exit(exc.exit_code)


if __name__ == "__main__":
    main()
