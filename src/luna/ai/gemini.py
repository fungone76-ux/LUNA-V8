"""Luna RPG v8 - Google Gemini LLM Client (Vertex AI).

Modelli Vertex AI aggiornati ad aprile 2026:
  - gemini-2.5-flash       → PRIMARY  (GA, veloce, ottimo equilibrio qualità/costo)
  - gemini-2.5-pro         → FALLBACK (GA, più potente, contesto 1M token)
  - gemini-2.5-flash-lite  → FALLBACK (GA, più economico, alta velocità)

NOTA: gemini-2.0-flash-001 e gemini-1.5-* sono DEPRECATI e verranno spenti
      il 1 giugno 2026. Rimosse dalle fallback per evitare 404.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from luna.ai.base import BaseLLMClient
from luna.ai.json_repair import RepairErrorType, repair_json
from luna.core.models import LLMResponse, StateUpdate

logger = logging.getLogger(__name__)

try:
    import vertexai
    from vertexai.generative_models import (
        GenerativeModel,
        Part,
        Content,
        SafetySetting,
        HarmCategory,
        HarmBlockThreshold,
    )
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Response schema
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
    """Google Gemini provider via Vertex AI.

    Modelli in uso (aggiornati aprile 2026, tutti GA su Vertex AI):

    PRIMARY:
        gemini-2.5-flash      — Veloce, bilanciato, ideale per RPG real-time.
                                Contesto 1M token. Retirement: ottobre 2026.

    FALLBACK 1:
        gemini-2.5-pro        — Più potente, per scene complesse o contesti lunghi.
                                Contesto 1M token. Retirement: ottobre 2026.

    FALLBACK 2:
        gemini-2.5-flash-lite — Più economico e veloce. Per turni semplici.
                                Retirement: ottobre 2026.

    MODELLI RIMOSSI (deprecati/spenti):
        gemini-2.0-flash-001  -> SPENTO 1 giugno 2026
        gemini-1.5-pro/flash  -> GIA SPENTI (404)
        gemini-1.0-*          -> GIA SPENTI (404)
    """

    DEFAULT_MODEL   = "gemini-2.5-flash"
    FALLBACK_MODELS = [
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
    ]

    TEMPERATURE  = 0.95
    MAX_TOKENS   = 4096

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        primary, fallbacks = self._load_model_config()
        super().__init__(model or primary, **kwargs)
        self.temperature  = temperature if temperature is not None else self.TEMPERATURE
        self.max_tokens   = max_tokens  if max_tokens  is not None else self.MAX_TOKENS
        self._fallbacks   = fallbacks
        self._init_client()

    @property
    def provider_name(self) -> str:
        return "gemini"

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def _load_model_config(self):
        try:
            from luna.config import get_model_config
            cfg = get_model_config()
            return cfg.gemini_primary, cfg.gemini_fallbacks
        except Exception:
            return self.DEFAULT_MODEL, self.FALLBACK_MODELS

    def _init_client(self) -> None:
        if not GEMINI_AVAILABLE:
            logger.error(
                "[Gemini] google-cloud-aiplatform not installed. "
                "Run: pip install google-cloud-aiplatform"
            )
            return
        try:
            vertexai.init(project='gen-lang-client-0617760675', location='us-central1')
            self._initialized = True
            logger.info(
                "[Gemini] Vertex AI initialized — primary: %s, fallbacks: %s",
                self.model, self._fallbacks
            )
        except Exception as e:
            logger.error("[Gemini] Init failed: %s", e)

    # -------------------------------------------------------------------------
    # Health check
    # -------------------------------------------------------------------------

    async def health_check(self) -> bool:
        if not self._initialized:
            return False
        try:
            model = GenerativeModel(self.model)
            resp = await model.generate_content_async("ping")
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
        companion_name: Optional[str] = None,
    ) -> LLMResponse:
        if not self._initialized:
            return self._create_error_response("Vertex AI client not initialized")

        contents = self._build_gemini_contents(history, user_input)
        models_to_try = [self.model] + self._fallbacks

        last_error = ""
        for model_name in models_to_try:
            try:
                result = await self._generate_with_model(
                    model_name, system_prompt, contents, json_mode
                )
                if result:
                    return result
                logger.warning("[Gemini] %s returned empty — trying next", model_name)
            except Exception as e:
                last_error = str(e)
                logger.warning("[Gemini] %s failed: %s", model_name, e)
                continue

        logger.error("[Gemini] All models failed. Last error: %s", last_error)
        return self._create_error_response("All Gemini models failed")

    async def _generate_with_model(
        self,
        model_name: str,
        system_prompt: str,
        contents: Any,
        json_mode: bool,
    ) -> Optional[LLMResponse]:
        safety_settings = [
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=HarmBlockThreshold.BLOCK_NONE,
            ),
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=HarmBlockThreshold.BLOCK_NONE,
            ),
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=HarmBlockThreshold.BLOCK_NONE,
            ),
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=HarmBlockThreshold.BLOCK_NONE,
            ),
        ]

        generation_config: Dict[str, Any] = {
            "temperature":       self.temperature,
            "top_p":             0.98,
            "top_k":             40,
            "max_output_tokens": self.max_tokens,
        }

        if json_mode:
            generation_config["response_mime_type"] = "application/json"

        model_instance = GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
        )

        response = await model_instance.generate_content_async(
            contents=contents,
            generation_config=generation_config,
            safety_settings=safety_settings,
        )

        raw = response.text
        if not raw:
            logger.warning("[Gemini] %s returned empty response", model_name)
            return None

        logger.debug("[Gemini] %s OK (%d chars)", model_name, len(raw))
        return self._parse(raw, model_name)

    def _parse(self, raw: str, model: str) -> Optional[LLMResponse]:
        result = repair_json(raw)

        if result.error_type == RepairErrorType.EMPTY:
            return None

        if result.data is None:
            logger.warning("[Gemini] JSON repair failed: %s", result.error_message)
            return None

        data = result.data
        if not data.get("text"):
            logger.debug("[Gemini] No 'text' field — passing raw JSON to caller")
            data["text"] = raw

        if result.was_repaired:
            logger.debug("[Gemini] JSON repaired for model %s", model)

        return self._build_response(data, model)

    def _build_response(self, data: Dict[str, Any], model: str) -> LLMResponse:
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
        contents = []
        for msg in history:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append(
                Content(
                    role=role,
                    parts=[Part.from_text(msg.get("content", ""))],
                )
            )
        contents.append(
            Content(
                role="user",
                parts=[Part.from_text(user_input)],
            )
        )
        return contents
