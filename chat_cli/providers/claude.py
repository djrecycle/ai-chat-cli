"""Claude API pribadi (server claude-api di VPS, token dari panel Token API).

Server ini kompatibel OpenAI: /v1/models dan /v1/chat/completions dengan
header `Authorization: Bearer <token>`.
"""

from .localai import LocalAIProvider


class ClaudeProvider(LocalAIProvider):
    request_stream_usage = True
