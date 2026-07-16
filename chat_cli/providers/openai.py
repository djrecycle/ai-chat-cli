"""OpenAI official API provider (stdlib HTTP)."""

from .localai import LocalAIProvider

class OpenAIProvider(LocalAIProvider):
    """
    OpenAI Provider is essentially identical to LocalAIProvider,
    as LocalAI is OpenAI-compatible. We just use this for clear typing/naming.
    """
    request_stream_usage = True
