"""Base provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass
class ImageAttachment:
    name: str
    mime_type: str
    data: str


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False

    def __post_init__(self) -> None:
        if not self.total_tokens:
            self.total_tokens = self.input_tokens + self.output_tokens


def estimate_token_usage(
    messages: list[ChatMessage], response: str
) -> TokenUsage:
    input_chars = sum(len(message.content) for message in messages)
    image_tokens = sum(len(message.images) * 258 for message in messages)
    input_tokens = max(1, (input_chars + 3) // 4) + image_tokens
    output_tokens = max(1, (len(response) + 3) // 4)
    return TokenUsage(input_tokens, output_tokens, estimated=True)


@dataclass
class ChatMessage:
    role: str
    content: str
    images: list[ImageAttachment] = field(default_factory=list)
    token_usage: TokenUsage | None = None


class ChatProvider(ABC):
    @property
    def last_usage(self) -> TokenUsage | None:
        return getattr(self, "_last_usage", None)

    def reset_usage(self) -> None:
        self._last_usage = None

    def set_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int = 0,
    ) -> None:
        self._last_usage = TokenUsage(input_tokens, output_tokens, total_tokens)
    @abstractmethod
    async def list_models(self) -> list[str]:
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float,
    ) -> AsyncIterator[str]:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...
