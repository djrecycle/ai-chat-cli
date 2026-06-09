"""Ollama API provider (stdlib HTTP)."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import AsyncIterator, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ChatMessage, ChatProvider


class OllamaProvider(ChatProvider):
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _get_json(self, path: str) -> dict:
        req = Request(f"{self.base_url}{path}", method="GET")
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    async def health_check(self) -> bool:
        try:
            await asyncio.to_thread(self._get_json, "/api/tags")
            return True
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return False

    async def list_models(self) -> list[str]:
        data = await asyncio.to_thread(self._get_json, "/api/tags")
        return [m["name"] for m in data.get("models", [])]

    def _stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float,
    ) -> Iterator[str]:
        payload = json.dumps(
            {
                "model": model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "stream": True,
                "options": {"temperature": temperature},
            }
        ).encode()
        req = Request(
            f"{self.base_url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=None) as resp:
            for raw in resp:
                line = raw.decode().strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = chunk.get("message") or {}
                content = msg.get("content", "")
                if content:
                    yield content
                if chunk.get("done"):
                    break

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float,
    ) -> AsyncIterator[str]:
        sync_q: queue.Queue[str | Exception | None] = queue.Queue()

        def worker() -> None:
            try:
                for piece in self._stream_chat(
                    messages, model=model, temperature=temperature
                ):
                    sync_q.put(piece)
            except HTTPError as e:
                try:
                    body = e.read().decode()
                    data = json.loads(body)
                    msg = data.get("error", {}).get("message", body)
                    sync_q.put(Exception(f"HTTP {e.code}: {msg}"))
                except Exception:
                    sync_q.put(e)
            except Exception as e:
                sync_q.put(e)
            finally:
                sync_q.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = await asyncio.to_thread(sync_q.get)
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item
