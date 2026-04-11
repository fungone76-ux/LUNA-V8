"""Luna RPG - World Models.

World definition, global events, and endgame models.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from .base import LunaBaseModel
from .companion_models import CompanionDefinition
from .enums import TimeOfDay
from .location_models import Location
from .quest_models import QuestDefinition
from .story_models import NarrativeArc


class GlobalEventEffect(LunaBaseModel):
    """Effects of a global event."""
    duration: int = Field(default=3, ge=1)
    location_modifiers: List[Dict[str, Any]] = Field(default_factory=list)
    visual_tags: List[str] = Field(default_factory=list)
    atmosphere_change: str = ""
    affinity_multiplier: float = Field(default=1.0, ge=0.0)
    on_start: List[Dict[str, Any]] = Field(default_factory=list)
    on_end: List[Dict[str, Any]] = Field(default_factory=list)


class GlobalEventDefinition(LunaBaseModel):
    """Global event definition."""
    id: str
    title: str = ""
    description: str = ""
    trigger_type: str = "random"
    trigger_chance: float = Field(default=0.1, ge=0.0, le=1.0)
    trigger_conditions: List[Dict[str, Any]] = Field(default_factory=list)
    allowed_times: List[str] = Field(default_factory=list)
    allowed_locations: List[str] = Field(default_factory=list)
    min_turn: int = 0
    repeatable: bool = True
    effects: GlobalEventEffect = Field(default_factory=GlobalEventEffect)
    narrative_prompt: str = ""
    narrative: str = ""  # Full narrative text with choices
    choices: List[Dict[str, Any]] = Field(default_factory=list)
    type: str = "random"  # Event type (tension, mystery, etc.)


class TimeSlot(LunaBaseModel):
    """Time of day configuration."""
    time_of_day: TimeOfDay
    lighting: str = ""
    ambient_description: str = ""


class MilestoneDefinition(LunaBaseModel):
    """Milestone achievement definition."""
    id: str = ""
    name: str = ""
    description: str = ""
    icon: str = ""
    condition: Dict[str, Any] = Field(default_factory=dict)


class EndgameCondition(LunaBaseModel):
    """Victory condition for endgame."""
    type: str = ""
    target: str = ""
    value: Any = None
    description: str = ""
    requires: Any = None


class EndgameDefinition(LunaBaseModel):
    """Endgame victory conditions."""
    description: str = ""
    victory_conditions: List[EndgameCondition] = Field(default_factory=list)


class WorldDefinition(LunaBaseModel):
    """Complete world definition loaded from YAML files.

    The engine is world-agnostic: it reads whatever world is passed here.
    No hardcoded world IDs anywhere in the engine code.
    """
    id: str
    name: str
    genre: str = "Visual Novel"
    description: str = ""
    lore: str = ""

    locations: Dict[str, Location] = Field(default_factory=dict)
    companions: Dict[str, CompanionDefinition] = Field(default_factory=dict)
    time_slots: Dict[str, Any] = Field(default_factory=dict)
    quests: Dict[str, QuestDefinition] = Field(default_factory=dict)
    narrative_arc: NarrativeArc = Field(default_factory=NarrativeArc)
    gameplay_systems: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    # NPC detection hints (world-specific vocabulary)
    female_hints: List[str] = Field(default_factory=list)
    male_hints: List[str] = Field(default_factory=list)

    milestones: Dict[str, Any] = Field(default_factory=dict)
    endgame: Optional[Any] = None
    global_events: Dict[str, GlobalEventDefinition] = Field(default_factory=dict)
    random_events: Dict[str, Any] = Field(default_factory=dict)
    daily_events: Dict[str, Any] = Field(default_factory=dict)
    npc_templates: Dict[str, Any] = Field(default_factory=dict)
    npc_schedules: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    player_character: Dict[str, Any] = Field(default_factory=dict)
    story_beats: Dict[str, Any] = Field(default_factory=dict)

    # v7: Tension tracker config
    tension_config: Dict[str, Any] = Field(default_factory=dict)

    # v7: GM Agenda config (agenda, principles, arc_threads per companion)
    gm_agenda: Dict[str, Any] = Field(default_factory=dict)
