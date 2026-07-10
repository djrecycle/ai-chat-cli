"""DeepSeek API provider."""

from .localai import LocalAIProvider

class DeepSeekProvider(LocalAIProvider):
    """
    DeepSeek Provider is essentially identical to LocalAIProvider,
    as DeepSeek API is OpenAI-compatible.
    """
    pass
