"""Luna RPG v6 - Moonshot AI (Kimi) LLM Client."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from luna.ai.base import BaseLLMClient
from luna.ai.json_repair import repair_json
from luna.core.models import LLMResponse, StateUpdate

logger = logging.getLogger(__name__)


class MoonshotClient(BaseLLMClient):
    """Moonshot AI (Kimi) provider.

    Third-level fallback. OpenAI-compatible API.
    """

    DEFAULT_MODEL = "kimi-k2.5"
    BASE_URL      = "https://api.moonshot.cn/v1"
    TEMPERATURE   = 0.95
    MAX_TOKENS    = 2048
    TIMEOUT       = 60.0

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model or self.DEFAULT_MODEL, **kwargs)
        self.api_key     = api_key
        self.temperature = temperature if temperature is not None else self.TEMPERATURE
        self.max_tokens  = max_tokens  if max_tokens  is not None else self.MAX_TOKENS
        self._client: Optional[httpx.AsyncClient] = None
        self._init_client()

    @property
    def provider_name(self) -> str:
        return "moonshot"

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def _init_client(self) -> None:
        if not self.api_key:
            logger.warning("[Moonshot] No API key provided")
            return
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type":  "application/json",
            },
            timeout=self.TIMEOUT,
        )
        self._initialized = True
        logger.info("[Moonshot] Initialized — model: %s", self.model)

    # -------------------------------------------------------------------------
    # Health check
    # -------------------------------------------------------------------------

    async def health_check(self) -> bool:
        if not self._client:
            return False
        try:
            resp = await self._client.get("/models")
            return resp.status_code == 200
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Generation
    # -------------------------------------------------------------------------

    async def generate(
        self,
        system_prompt: str,
        user_input: str,
        history: List[Dict[str, str]],
        json_mode: bool = True,
    ) -> LLMResponse:
        if not self._client:
            return self._create_error_response("Moonshot client not initialized")

        messages = self._build_messages(system_prompt, user_input, history)

        payload: Dict[str, Any] = {
            "model":       self.model,
            "messages":    messages,
            "temperature": self.temperature,
            "max_tokens":  self.max_tokens,
        }

        # JSON schema mode
        if json_mode:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name":   "luna_response",
                    "schema": self._response_schema(),
                },
            }

        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data    = resp.json()
            content = data["choices"][0]["message"]["content"]
            return self._parse(content, self.model)
        except httpx.HTTPStatusError as e:
            logger.warning("[Moonshot] HTTP error: %s", e)
            raise
        except Exception as e:
            logger.warning("[Moonshot] Generation failed: %s", e)
            return self._create_error_response(str(e))

    # -------------------------------------------------------------------------
    # Parsing
    # -------------------------------------------------------------------------

    def _parse(self, raw: str, model: str) -> LLMResponse:
        result = repair_json(raw)

        if result.data is None:
            logger.warning("[Moonshot] JSON repair failed: %s", result.error_message)
            return self._create_error_response(result.error_message)

        data = result.data
        if not data.get("text"):
            # Some callers (e.g. NPC authority turns) return "dialogue" or "note"
            # instead of "text". Pass the raw JSON as text so the caller can re-parse it.
            logger.debug("[Moonshot] Response has no text field — passing raw JSON to caller")
            data["text"] = raw
        updates_data = data.get("updates", {})
        try:
            updates = StateUpdate(**updates_data) if updates_data else StateUpdate()
        except Exception as e:
            logger.debug("[Moonshot] StateUpdate validation: %s", e)
            updates = StateUpdate()

        return LLMResponse(
            text=data.get("text", ""),
            visual_en=data.get("visual_en", ""),
            tags_en=data.get("tags_en", []),
            body_focus=data.get("body_focus"),
            aspect_ratio=data.get("aspect_ratio", "portrait"),
            dop_reasoning=data.get("dop_reasoning", ""),
            composition=data.get("composition"),
            secondary_characters=data.get("secondary_characters", []),
            approach_used=data.get("approach_used", "standard"),
            updates=updates,
            raw_response=raw,
            provider=f"moonshot/{model}",
        )

    # -------------------------------------------------------------------------
    # Schema
    # -------------------------------------------------------------------------

    @staticmethod
    def _response_schema() -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text":        {"type": "string"},
                "visual_en":   {"type": "string"},
                "tags_en":     {"type": "array", "items": {"type": "string"}},
                "body_focus":  {"type": "string"},
                "aspect_ratio": {"type": "string", "enum": ["portrait", "landscape", "square"]},
                "composition": {"type": "string"},
                "dop_reasoning": {"type": "string"},
                "updates": {
                    "type": "object",
                    "properties": {
                        "affinity_change": {"type": "object"},
                        "outfit_update":   {"type": "object"},
                        "set_flags":       {"type": "object"},
                        "new_fact":        {"type": "string"},
                        "invite_accepted": {"type": "boolean"},
                        "photo_requested": {"type": "boolean"},
                    },
                },
            },
            "required": ["text"],
        }

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
