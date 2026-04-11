"""Luna RPG - Personality System Models.

Behavioral memory, impressions, and NPC relationships.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import Field, field_validator

from .base import LunaBaseModel
from .enums import BehaviorType, TraitIntensity


class BehavioralMemory(LunaBaseModel):
    """Tracked behavioral trait with intensity."""
    trait: BehaviorType
    occurrences: int = Field(default=0, ge=0)
    last_turn: int = Field(default=0, ge=0)
    intensity: TraitIntensity = TraitIntensity.SUBTLE

    @field_validator("trait", mode="before")
    @classmethod
    def validate_trait(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return BehaviorType(v.lower())
            except ValueError:
                return BehaviorType(v.upper())
        return v

    def update(self, turn: int) -> None:
        self.occurrences += 1
        self.last_turn = turn
        if self.occurrences > 5:
            self.intensity = TraitIntensity.STRONG
        elif self.occurrences > 2:
            self.intensity = TraitIntensity.MODERATE


class Impression(LunaBaseModel):
    """NPC's emotional impression of the player."""
    trust: int = Field(default=0, ge=-100, le=100)
    attraction: int = Field(default=0, ge=-100, le=100)
    fear: int = Field(default=0, ge=-100, le=100)
    curiosity: int = Field(default=0, ge=-100, le=100)
    dominance_balance: int = Field(default=0, ge=-100, le=100)

    def get_dominant_emotion(self) -> str:
        values = {
            "trust": self.trust, "attraction": self.attraction,
            "fear": self.fear, "curiosity": self.curiosity,
        }
        return max(values, key=values.get)


class NPCLink(LunaBaseModel):
    """Relationship between two NPCs."""
    target_npc: str
    rapport: int = Field(default=0, ge=-100, le=100)
    jealousy_sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    awareness_of_player: int = Field(default=0, ge=0, le=100)


class PersonalityState(LunaBaseModel):
    """Complete personality state for a character."""
    character_name: str
    behavioral_memory: Dict[str, BehavioralMemory] = Field(default_factory=dict)
    impression: Impression = Field(default_factory=Impression)
    npc_links: Dict[str, NPCLink] = Field(default_factory=dict)
    detected_archetype: Optional[str] = None
    archetype_cache_turn: int = Field(default=-1, ge=-1)
