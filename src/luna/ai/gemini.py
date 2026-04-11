"""Luna RPG v6 - Google Gemini LLM Client."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from luna.ai.base import BaseLLMClient
from luna.ai.json_repair import RepairErrorType, repair_json
from luna.core.models import LLMResponse, StateUpdate

logger = logging.getLogger(__name__)

try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Response schema — used by Gemini response_schema for structured output
# ---------------------------------------------------------------------------

class _UpdatesSchema(BaseModel):
    affinity_change: Optional[Dict[str, int]] = None
    new_fact: Optional[str] = None
    npc_emotion: Optional[str] = None
    new_promise: Optional[str] = None
    resolve_promise: Optional[str] = None
    promise_weight: Optional[float] = None
    invite_accepted: Optional[bool] = None
    photo_requested: Optional[bool] = None
    photo_outfit: Optional[str] = None


class _ResponseSchema(BaseModel):
    text: str
    visual_en: Optional[str] = None
    tags_en: Optional[List[str]] = None
    body_focus: Optional[str] = None
    aspect_ratio: Optional[str] = None
    dop_reasoning: Optional[str] = None
    composition: Optional[str] = None
    secondary_characters: Optional[List[str]] = None
    updates: Optional[_UpdatesSchema] = None


class GeminiClient(BaseLLMClient):
    """Google Gemini provider.

    Primary LLM for Luna RPG v6.
    Loads model list from config/models.yaml.
    """

    # Modelli Gemini disponibili (da lista API aggiornata):
    # ✅ Per generateContent (testo): gemini-2.5-flash, gemini-2.5-pro, gemini-2.0-flash
    # ❌ Non supportati: gemini-3-*, gemini-*-tts, imagen-*, veo-*, embedding-*, lyria-*, aqa
    DEFAULT_MODEL    = "gemini-2.5-flash"           # Miglior rapporto qualità/velocità
    FALLBACK_MODELS  = [
        "gemini-2.5-pro",                           # Più potente, più lento
        "gemini-2.0-flash",                         # Veloce e affidabile
        "gemini-flash-latest",                      # Alias sempre aggiornato
    ]
    TEMPERATURE      = 0.95
    MAX_TOKENS       = 2048

    # Safety: allow all categories (content filtered by game logic)
    SAFETY_SETTINGS = [
        {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        # Try to load from models.yaml, fall back to defaults
        primary, fallbacks = self._load_model_config()

        super().__init__(model or primary, **kwargs)
        self.api_key      = api_key
        self.temperature  = temperature if temperature is not None else self.TEMPERATURE
        self.max_tokens   = max_tokens  if max_tokens  is not None else self.MAX_TOKENS
        self._fallbacks   = fallbacks
        self._client: Optional[Any] = None
        self._init_client()

    @property
    def provider_name(self) -> str:
        return "gemini"

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def _load_model_config(self):
        """Load model config from models.yaml if available."""
        try:
            from luna.config import get_model_config
            cfg = get_model_config()
            return cfg.gemini_primary, cfg.gemini_fallbacks
        except Exception:
            return self.DEFAULT_MODEL, self.FALLBACK_MODELS

    def _init_client(self) -> None:
        if not GEMINI_AVAILABLE:
            logger.error("[Gemini] google-genai not installed: pip install google-genai")
            return
        if not self.api_key:
            logger.warning("[Gemini] No API key provided")
            return
        try:
            self._client = genai.Client(api_key=self.api_key)
            self._initialized = True
            logger.info("[Gemini] Initialized — model: %s", self.model)
        except Exception as e:
            logger.error("[Gemini] Init failed: %s", e)

    # -------------------------------------------------------------------------
    # Health check
    # -------------------------------------------------------------------------

    async def health_check(self) -> bool:
        if not self._initialized or not self._client:
            return False
        try:
            resp = self._client.models.generate_content(
                model=self.model,
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=5),
            )
            return resp.text is not None
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
            return self._create_error_response("Gemini client not initialized")

        contents = self._build_gemini_contents(history, user_input)
        models_to_try = [self.model] + self._fallbacks

        for model in models_to_try:
            try:
                result = await self._generate_with_model(
                    model, system_prompt, contents, json_mode
                )
                if result:
                    return result
            except Exception as e:
                logger.warning("[Gemini] %s failed: %s", model, e)
                continue

        logger.error("[Gemini] All models failed")
        return self._create_error_response("All Gemini models failed")

    async def _generate_with_model(
        self,
        model: str,
        system_prompt: str,
        contents: Any,
        json_mode: bool,
    ) -> Optional[LLMResponse]:
        """Try generation with a specific model."""
        safety = [
            types.SafetySetting(category=s["category"], threshold=s["threshold"])
            for s in self.SAFETY_SETTINGS
        ]
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=self.temperature,
            top_p=0.98,
            top_k=40,
            max_output_tokens=self.max_tokens,
            safety_settings=safety,
        )
        if json_mode:
            config.response_mime_type = "application/json"

        response = self._client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        raw = response.text
        if not raw:
            logger.warning("[Gemini] %s returned empty response", model)
            return None

        return self._parse(raw, model)

    def _parse(self, raw: str, model: str) -> Optional[LLMResponse]:
        """Parse raw LLM output into LLMResponse using repair pipeline."""
        result = repair_json(raw)

        if result.error_type == RepairErrorType.EMPTY:
            return None

        if result.data is None:
            logger.warning("[Gemini] JSON repair failed: %s", result.error_message)
            return None

        data = result.data
        if not data.get("text"):
            # Some callers (e.g. NPC authority turns) return "dialogue" or "note"
            # instead of "text". Pass the raw JSON as text so the caller can parse it.
            logger.debug("[Gemini] Response has no text field — passing raw JSON to caller")
            data["text"] = raw

        if result.was_repaired:
            logger.debug("[Gemini] JSON was repaired for model %s", model)

        return self._build_response(data, model)

    def _build_response(self, data: Dict[str, Any], model: str) -> LLMResponse:
        """Build LLMResponse from validated dict."""
        updates_data = data.get("updates", {})
        try:
            updates = StateUpdate(**updates_data) if updates_data else StateUpdate()
        except Exception as e:
            logger.debug("[Gemini] StateUpdate validation: %s", e)
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
            raw_response=data.get("_raw", ""),
            provider=f"gemini/{model}",
        )

    def _build_gemini_contents(
        self,
        history: List[Dict[str, str]],
        user_input: str,
    ) -> List[Any]:
        """Build Gemini-format content list."""
        contents = []
        for msg in history:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg.get("content", ""))],
                )
            )
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_input)],
            )
        )
        return contents
