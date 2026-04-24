"""Luna RPG - Companion Models.

Companion definitions, wardrobe, and emotional states.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from .base import LunaBaseModel
from .location_models import ScheduleEntry
from .personality_models import Impression


class WardrobeDefinition(LunaBaseModel):
    """Single outfit definition."""
    description: str = ""
    sd_prompt: str = ""
    special: bool = False


class EmotionalStateDefinition(LunaBaseModel):
    """Emotional state configuration."""
    description: str = ""
    dialogue_tone: str = ""
    trigger_flags: List[str] = Field(default_factory=list)


class CompanionDefinition(LunaBaseModel):
    """Complete companion character definition from YAML."""
    name: str
    role: str = ""
    age: int = Field(default=21, ge=16)
    base_personality: str = ""
    base_prompt: str = ""                   # LoRA trigger words - DO NOT MODIFY
    physical_description: str = ""
    default_outfit: str = "default"
    visual_tags: List[str] = Field(default_factory=list)
    wardrobe: Dict[str, Any] = Field(default_factory=dict)
    emotional_states: Dict[str, Any] = Field(default_factory=dict)
    affinity_tiers: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    background: str = ""
    relationship_to_player: str = ""
    aliases: List[str] = Field(default_factory=list)
    starting_impression: Optional[Impression] = None
    dialogue_tone: Dict[str, Any] = Field(default_factory=dict)
    schedule: Dict[str, ScheduleEntry] = Field(default_factory=dict)
    relations: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    is_temporary: bool = False
    gender: str = Field(default="female")
    allow_multi_npc_interrupts: bool = Field(default=True)
    spawn_locations: List[str] = Field(default_factory=list)

    # v7: NPC mind system fields (optional, loaded from YAML)
    npc_relationships: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    goal_templates: List[Dict[str, Any]] = Field(default_factory=list)
    needs_profile: Dict[str, Any] = Field(default_factory=dict)

    # v8: Character Realism System fields
    auto_states: List[Dict[str, Any]] = Field(default_factory=list)
    avoid_topics_unless_asked: List[str] = Field(default_factory=list)
    behavior_responses: Dict[str, str] = Field(default_factory=dict)
    location_voice: Dict[str, Any] = Field(default_factory=dict)
