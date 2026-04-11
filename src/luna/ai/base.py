"""Luna RPG v6 - Base LLM Client.

Abstract interface that all LLM providers must implement.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from luna.core.models import LLMResponse


class BaseLLMClient(ABC):
    """Abstract base class for LLM providers.

    All clients must implement:
    - generate(): main generation method
    - health_check(): verify client is ready
    - provider_name: string identifier
    """

    def __init__(self, model: Optional[str] = None, **kwargs: Any) -> None:
        self.model = model
        self.config = kwargs
        self._initialized = False

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return provider name e.g. 'gemini', 'claude', 'moonshot'."""
        ...

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_input: str,
        history: List[Dict[str, str]],
        json_mode: bool = True,
    ) -> LLMResponse:
        """Generate LLM response.

        Args:
            system_prompt: System instructions
            user_input:    Current user message
            history:       Previous messages [{"role": "user|assistant", "content": "..."}]
            json_mode:     Whether to request JSON output

        Returns:
            Structured LLMResponse
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if client is properly configured and ready."""
        ...

    def _build_messages(
        self,
        system_prompt: str,
        user_input: str,
        history: List[Dict[str, str]],
    ) -> List[Dict[str, str]]:
        """Build message list for API calls (OpenAI format)."""
        messages: List[Dict[str, str]] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        for msg in history:
            messages.append({
                "role":    msg.get("role", "user"),
                "content": msg.get("content", ""),
            })

        messages.append({"role": "user", "content": user_input})
        return messages

    def _create_error_response(self, error_msg: str) -> LLMResponse:
        """Create a minimal valid error response."""
        return LLMResponse(
            text=f"[Error: {error_msg}]",
            visual_en="",
            tags_en=[],
            raw_response=error_msg,
            provider=self.provider_name,
        )

    def _create_fallback_response(self, companion_name: str = "NPC") -> LLMResponse:
        """Create a minimal narrative fallback when all parsing fails.

        This is always valid — never empty, never a crash.
        The player sees a natural response, not a technical error.
        """
        return LLMResponse(
            text=(
                f"*{companion_name} ti guarda in silenzio per un momento.* "
                f"\"Cosa stavi dicendo?\""
            ),
            visual_en=f"{companion_name} standing, neutral expression, looking at viewer",
            tags_en=["1girl", "standing", "neutral_expression", "looking_at_viewer"],
            provider=f"{self.provider_name}/fallback",
        )
