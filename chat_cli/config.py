"""Configuration for DJ Chat Ai."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "ai-chat-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "ollama",
    "ollama": {
        "base_url": "http://127.0.0.1:11434",
        "model": "qwen2.5:1.5b",
    },
    "localai": {
        "base_url": "http://127.0.0.1:8080",
        "model": "gpt-3.5-turbo",
        "api_key": "",
    },
    "openai": {
        "base_url": "https://api.openai.com",
        "model": "gpt-4o",
        "api_key": "",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-1.5-flash",
        "api_key": "",
    },
    "system_prompt": "Kamu adalah asisten AI yang ramah dan membantu. Jawab dengan jelas dalam bahasa yang dipakai pengguna.",
    "temperature": 0.7,
    "show_thinking": True,
}


@dataclass
class AppConfig:
    provider: str = "ollama"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:1.5b"
    localai_base_url: str = "http://127.0.0.1:8080"
    localai_model: str = "gpt-3.5-turbo"
    localai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com"
    openai_model: str = "gpt-4o"
    openai_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-1.5-flash"
    gemini_api_key: str = ""
    system_prompt: str = DEFAULT_CONFIG["system_prompt"]
    temperature: float = 0.7
    show_thinking: bool = True

    @property
    def active_base_url(self) -> str:
        if self.provider == "gemini":
            return self.gemini_base_url.rstrip("/")
        if self.provider == "openai":
            return self.openai_base_url.rstrip("/")
        if self.provider == "localai":
            return self.localai_base_url.rstrip("/")
        return self.ollama_base_url.rstrip("/")

    @property
    def active_model(self) -> str:
        if self.provider == "gemini":
            return self.gemini_model
        if self.provider == "openai":
            return self.openai_model
        if self.provider == "localai":
            return self.localai_model
        return self.ollama_model

    def set_model(self, model: str) -> None:
        if self.provider == "gemini":
            self.gemini_model = model
        elif self.provider == "openai":
            self.openai_model = model
        elif self.provider == "localai":
            self.localai_model = model
        else:
            self.ollama_model = model

    def set_provider(self, provider: str) -> None:
        if provider not in ("ollama", "localai", "openai", "gemini"):
            raise ValueError(f"Provider tidak dikenal: {provider}")
        self.provider = provider


def load_config() -> AppConfig:
    data = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open(encoding="utf-8") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update(loaded)

    env_provider = os.environ.get("AI_CHAT_PROVIDER")
    if env_provider:
        data["provider"] = env_provider

    ollama = data.get("ollama") or {}
    localai = data.get("localai") or {}
    openai = data.get("openai") or {}
    gemini = data.get("gemini") or {}

    return AppConfig(
        provider=str(data.get("provider", "ollama")),
        ollama_base_url=str(ollama.get("base_url", DEFAULT_CONFIG["ollama"]["base_url"])),
        ollama_model=str(ollama.get("model", DEFAULT_CONFIG["ollama"]["model"])),
        localai_base_url=str(localai.get("base_url", DEFAULT_CONFIG["localai"]["base_url"])),
        localai_model=str(localai.get("model", DEFAULT_CONFIG["localai"]["model"])),
        localai_api_key=str(localai.get("api_key", "")),
        openai_base_url=str(openai.get("base_url", DEFAULT_CONFIG["openai"]["base_url"])),
        openai_model=str(openai.get("model", DEFAULT_CONFIG["openai"]["model"])),
        openai_api_key=str(openai.get("api_key", "")),
        gemini_base_url=str(gemini.get("base_url", DEFAULT_CONFIG["gemini"]["base_url"])),
        gemini_model=str(gemini.get("model", DEFAULT_CONFIG["gemini"]["model"])),
        gemini_api_key=str(gemini.get("api_key", "")),
        system_prompt=str(data.get("system_prompt", DEFAULT_CONFIG["system_prompt"])),
        temperature=float(data.get("temperature", 0.7)),
        show_thinking=bool(data.get("show_thinking", DEFAULT_CONFIG["show_thinking"])),
    )


def save_config(cfg: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": cfg.provider,
        "ollama": {
            "base_url": cfg.ollama_base_url,
            "model": cfg.ollama_model,
        },
        "localai": {
            "base_url": cfg.localai_base_url,
            "model": cfg.localai_model,
            "api_key": cfg.localai_api_key,
        },
        "openai": {
            "base_url": cfg.openai_base_url,
            "model": cfg.openai_model,
            "api_key": cfg.openai_api_key,
        },
        "gemini": {
            "base_url": cfg.gemini_base_url,
            "model": cfg.gemini_model,
            "api_key": cfg.gemini_api_key,
        },
        "system_prompt": cfg.system_prompt,
        "temperature": cfg.temperature,
        "show_thinking": cfg.show_thinking,
    }
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
