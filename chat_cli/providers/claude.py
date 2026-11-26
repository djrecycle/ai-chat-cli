"""Claude API pribadi (server claude-api di VPS, token dari panel Token API).

Server ini kompatibel OpenAI: /v1/models dan /v1/chat/completions dengan
header `Authorization: Bearer <token>`. Streaming belum didukung server, jadi
jawaban diminta utuh (`"stream": false`) lalu dikirim ke UI sebagai satu potongan.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from urllib.request import Request, urlopen

from .base import ChatMessage
from .localai import LocalAIProvider


class ClaudeProvider(LocalAIProvider):
    def _stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float,
    ) -> Iterator[str]:
        self.reset_usage()
        payload = json.dumps(
            {
                "model": model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "stream": False,
                "temperature": temperature,
            }
        ).encode()
        req = Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            method="POST",
            headers=self._headers(),
        )
        with urlopen(req, timeout=None) as resp:
            data = json.loads(resp.read().decode())

        usage = data.get("usage") or {}
        if usage:
            self.set_usage(
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)),
                int(usage.get("total_tokens", 0)),
            )
        choices = data.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        content = message.get("content") or ""
        if isinstance(content, list):  # beberapa server mengirim blok konten
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if content:
            yield content
