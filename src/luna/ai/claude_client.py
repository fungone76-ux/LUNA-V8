"""Luna RPG v6 - Anthropic Claude LLM Client.

Uses Tool Use (forced tool_choice) for structured output — eliminates JSON
parsing errors by having Claude fill a typed schema instead of free-form text.
Falls back to text + json_repair if tool use fails.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from luna.ai.base import BaseLLMClient
from luna.ai.json_repair import repair_json
from luna.core.models import LLMResponse, StateUpdate

logger = logging.getLogger(__name__)

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Tool schema — maps exactly to LLMResponse + StateUpdate fields
# ---------------------------------------------------------------------------

_RESPONSE_TOOL: Dict[str, Any] = {
    "name": "generate_response",
    "description": (
        "Generate the narrative turn response. "
        "Fill every field according to the system prompt instructions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Narrative response in Italian",
            },
            "visual_en": {
                "type": "string",
                "description": "Visual description in English for image generation",
            },
            "tags_en": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Stable Diffusion tags in English",
            },
            "body_focus": {
                "type": "string",
                "description": "Body area in focus for the image (optional)",
            },
            "aspect_ratio": {
                "type": "string",
                "enum": ["portrait", "landscape", "square"],
                "description": "Image aspect ratio",
            },
            "dop_reasoning": {
                "type": "string",
                "description": "Director of Photography reasoning for the composition",
            },
            "composition": {
                "type": "string",
                "description": "Shot composition (close_up, medium_shot, cowboy_shot, wide_shot…)",
            },
            "secondary_characters": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Other characters visible in the scene",
            },
            "updates": {
                "type": "object",
                "description": "State changes to apply after this turn",
                "properties": {
                    "affinity_change": {
                        "type": "object",
                        "additionalProperties": {"type": "integer"},
                        "description": "Affinity delta per character, values -5 to +5",
                    },
                    "new_fact": {
                        "type": "string",
                        "description": "New fact to store in semantic memory",
                    },
                    "npc_emotion": {
                        "type": "string",
                        "description": "Current NPC emotional state",
                    },
                    "new_promise": {
                        "type": "string",
                        "description": "New narrative promise id (snake_case)",
                    },
                    "resolve_promise": {
                        "type": "string",
                        "description": "Promise id being fulfilled this turn",
                    },
                    "promise_weight": {
                        "type": "number",
                        "description": "Emotional weight of new_promise (0.0–1.0)",
                    },
                    "invite_accepted": {"type": "boolean"},
                    "photo_requested": {"type": "boolean"},
                    "photo_outfit": {"type": "string"},
                },
            },
        },
        "required": ["text"],
    },
}


class ClaudeClient(BaseLLMClient):
    """Anthropic Claude provider.

    Primary LLM for Luna RPG v6 when LLM_PROVIDER=claude.
    Uses Tool Use for structured output — no JSON parsing errors.
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"
    TEMPERATURE   = 0.85
    MAX_TOKENS    = 1500

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
        self._client: Optional[Any] = None
        self._init_client()

    @property
    def provider_name(self) -> str:
        return "claude"

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def _init_client(self) -> None:
        if not ANTHROPIC_AVAILABLE:
            logger.error("[Claude] anthropic not installed: pip install anthropic")
            return
        if not self.api_key:
            logger.warning("[Claude] No API key provided")
            return
        try:
            self._client = anthropic.Anthropic(api_key=self.api_key)
            self._initialized = True
            logger.info("[Claude] Initialized — model: %s", self.model)
        except Exception as e:
            logger.error("[Claude] Init failed: %s", e)

    # -------------------------------------------------------------------------
    # Health check
    # -------------------------------------------------------------------------

    async def health_check(self) -> bool:
        if not self._initialized or not self._client:
            return False
        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return bool(resp.content)
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
            return self._create_error_response("Claude client not initialized")

        messages = self._build_messages("", user_input, history)

        # Claude rejects messages with empty content
        messages = [m for m in messages if m.get("content", "").strip()]
        if not messages:
            messages = [{"role": "user", "content": "(continua)"}]
        if messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": user_input.strip() or "(continua)"})

        if json_mode:
            return await self._generate_structured(system_prompt, messages)
        else:
            return await self._generate_text(system_prompt, messages)

    async def _generate_structured(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
    ) -> LLMResponse:
        """Generate using Tool Use — output is a typed dict, no JSON parsing."""
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt,
                messages=messages,
                tools=[_RESPONSE_TOOL],
                tool_choice={"type": "tool", "name": "generate_response"},
            )

            # Extract tool input — already a Python dict, schema-validated by Claude
            for block in response.content:
                if getattr(block, "type", None) == "tool_use" and block.name == "generate_response":
                    logger.debug("[Claude] Structured output received via tool use")
                    return self._build_response(block.input, self.model)

            # If no tool_use block (shouldn't happen with forced tool_choice), fallback
            logger.warning("[Claude] No tool_use block in response, falling back to text")
            raw = next(
                (b.text for b in response.content if getattr(b, "type", None) == "text"),
                "",
            )
            return self._parse_text(raw, self.model)

        except Exception as e:
            logger.warning("[Claude] Structured generation failed: %s — falling back to text", e)
            return await self._generate_text(system_prompt, messages)

    async def _generate_text(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
    ) -> LLMResponse:
        """Fallback: free-form text generation + json_repair pipeline."""
        effective_system = (
            system_prompt
            + "\n\nIMPORTANT: Respond with a single valid JSON object only. "
            "No markdown fences, no preamble, no text outside the JSON. "
            "Start with { and end with }."
        )
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=effective_system,
                messages=messages,
            )
            raw = response.content[0].text if response.content else ""
            if not raw:
                return self._create_error_response("Empty response from Claude")
            return self._parse_text(raw, self.model)
        except Exception as e:
            logger.warning("[Claude] Text generation failed: %s", e)
            return self._create_error_response(str(e))

    # -------------------------------------------------------------------------
    # Response builders
    # -------------------------------------------------------------------------

    def _build_response(self, data: Dict[str, Any], model: str) -> LLMResponse:
        """Build LLMResponse from a validated dict (tool use input)."""
        updates_data = data.get("updates", {}) or {}
        try:
            updates = StateUpdate(**updates_data) if updates_data else StateUpdate()
        except Exception as e:
            logger.debug("[Claude] StateUpdate validation: %s", e)
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
            provider=f"claude/{model}",
        )

    def _parse_text(self, raw: str, model: str) -> LLMResponse:
        """Parse free-form text output using the repair pipeline."""
        result = repair_json(raw)

        if result.data is None or not result.data.get("text"):
            logger.warning("[Claude] JSON repair failed: %s", result.error_message)
            return self._create_error_response(result.error_message)

        if result.was_repaired:
            logger.debug("[Claude] JSON was repaired (text fallback)")

        return self._build_response(result.data, model)
