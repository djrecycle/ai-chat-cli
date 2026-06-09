"""Gemini API provider (stdlib HTTP)."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import AsyncIterator, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import ChatMessage, ChatProvider


class GeminiProvider(ChatProvider):
    def __init__(self, base_url: str, api_key: str = "") -> None:
        # For Gemini, base_url is usually https://generativelanguage.googleapis.com/v1beta
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _get_json(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        if "?" in url:
            url += f"&key={self.api_key}"
        else:
            url += f"?key={self.api_key}"
        req = Request(url, method="GET")
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    async def health_check(self) -> bool:
        try:
            await asyncio.to_thread(self._get_json, "/models")
            return True
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return False

    async def list_models(self) -> list[str]:
        data = await asyncio.to_thread(self._get_json, "/models")
        # Filter only models that support generateContent
        models = [
            m["name"].replace("models/", "")
            for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        return models

    def _stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float,
    ) -> Iterator[str]:
        contents = []
        system_instruction = None

        for m in messages:
            if m.role == "system":
                system_instruction = {"parts": [{"text": m.content}]}
            else:
                role = "model" if m.role == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": m.content}]})

        # API expects model prefixed with 'models/' if not already
        model_id = model if model.startswith("models/") else f"models/{model}"
        url = f"{self.base_url}/{model_id}:streamGenerateContent?alt=sse&key={self.api_key}"

        payload_dict = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }
        if system_instruction:
            payload_dict["systemInstruction"] = system_instruction

        payload = json.dumps(payload_dict).encode()
        req = Request(
            url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        with urlopen(req, timeout=None) as resp:
            for raw in resp:
                line = raw.decode().strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]" or not data:
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                
                candidates = chunk.get("candidates") or []
                if not candidates:
                    continue
                content_parts = candidates[0].get("content", {}).get("parts", [])
                for part in content_parts:
                    text = part.get("text", "")
                    if text:
                        yield text

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
