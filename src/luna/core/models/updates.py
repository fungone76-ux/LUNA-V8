"""Luna RPG - Update and Response Models.

Models for LLM-proposed state changes and responses.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field, field_validator

from .base import LunaBaseModel
from .enums import TimeOfDay


class OutfitUpdate(LunaBaseModel):
    """Outfit change proposed by LLM response."""
    style: Optional[str] = None
    description: Optional[str] = None
    modify_components: Dict[str, str] = Field(default_factory=dict)
    is_special: Optional[bool] = None


class StateUpdate(LunaBaseModel):
    """State changes proposed by LLM (validated by engine before applying)."""
    location: Optional[str] = None
    time_of_day: Optional[TimeOfDay] = None
    outfit_update: Optional[OutfitUpdate] = None

    affinity_change: Dict[str, int] = Field(default_factory=dict)
    set_flags: Dict[str, Any] = Field(default_factory=dict)
    new_quests: List[str] = Field(default_factory=list)
    complete_quests: List[str] = Field(default_factory=list)

    npc_location: Optional[str] = None
    npc_outfit: Optional[str] = None
    npc_emotion: Optional[str] = None

    new_fact: Optional[str] = None

    # v7: GM Agenda — narrative promises declared by the LLM
    new_promise: Optional[str] = None      # snake_case id of a new narrative hook
    resolve_promise: Optional[str] = None  # id of a promise being honored this turn
    promise_weight: Optional[float] = None # emotional weight of new_promise (0.0–1.0)

    # Remote NPC interaction
    invite_accepted: bool = Field(default=False)
    photo_requested: bool = Field(default=False)
    photo_outfit: Optional[str] = Field(default=None)

    @field_validator("affinity_change", mode="before")
    @classmethod
    def validate_affinity_change(cls, v: Any) -> Dict[str, int]:
        if isinstance(v, int):
            return {}
        if not isinstance(v, dict):
            return {}
        return {k: max(-5, min(5, val)) for k, val in v.items() if isinstance(val, int)}


class LLMResponse(LunaBaseModel):
    """Structured response from LLM provider."""
    model_config = ConfigDict(strict=False, validate_assignment=True, extra="ignore", use_enum_values=True)

    # Narrative (Italian)
    text: str = Field(description="Narrative text in Italian")

    # Visual generation (English)
    visual_en: str = Field(default="")
    tags_en: List[str] = Field(default_factory=list)
    body_focus: Optional[str] = Field(default=None)

    # Director of Photography
    aspect_ratio: str = Field(default="square")
    dop_reasoning: str = Field(default="")
    composition: Optional[str] = Field(default=None)

    # Multi-character
    secondary_characters: List[str] = Field(default_factory=list)
    approach_used: str = Field(default="standard")

    # State updates
    updates: StateUpdate = Field(default_factory=StateUpdate)

    # Metadata (excluded from serialization)
    raw_response: Optional[str] = Field(default=None, exclude=True)
    provider: Optional[str] = Field(default=None, exclude=True)

    # V5: schema version for pipeline validation
    response_schema_version: str = Field(default="5.0")

    @property
    def is_multi_character(self) -> bool:
        return len(self.secondary_characters) > 0

    @field_validator("composition", mode="before")
    @classmethod
    def normalize_composition(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if not normalized:
            return None
        replacements = {
            "close up": "close_up", "close-up": "close_up",
            "medium shot": "medium_shot", "cowboy shot": "cowboy_shot",
            "wide shot": "wide_shot", "from below": "from_below",
            "from above": "from_above", "dutch angle": "dutch_angle",
            "full body": "full_body", "eye level": "eye_level",
            "over the shoulder": "over_shoulder",
            "over-the-shoulder": "over_shoulder",
            "over shoulder": "over_shoulder",
        }
        return replacements.get(normalized, normalized.replace("-", "_").replace(" ", "_"))

    @field_validator("aspect_ratio", mode="before")
    @classmethod
    def normalize_aspect_ratio(cls, value: Any) -> str:
        if value is None:
            return "square"
        normalized = str(value).strip().lower()
        return normalized if normalized in {"landscape", "portrait", "square"} else "square"
