"""Luna RPG - Data Models Package.

All game data structures. Models are now organized in submodules
but re-exported here for backward compatibility.

Original monolithic models.py has been refactored into:
- enums.py: All enumeration types
- base.py: LunaBaseModel base class
- state_models.py: GameState, PlayerState, NPCState, OutfitState
- updates.py: OutfitUpdate, StateUpdate, LLMResponse
- quest_models.py: Quest system models
- location_models.py: Location and movement models
- companion_models.py: Companion definitions
- story_models.py: Story beats and narrative arcs
- world_models.py: WorldDefinition and global events
- media_models.py: Image/video generation models
- memory_models.py: Memory and conversation models
- personality_models.py: Personality system models
- config_models.py: Application configuration
- output_models.py: Turn results and agent outputs
"""
from __future__ import annotations

# Base
from .base import LunaBaseModel

# Enums
from .enums import (
    BehaviorType,
    CompositionType,
    IntentType,
    LocationState,
    OutfitComponent,
    QuestStatus,
    TimeOfDay,
    TraitIntensity,
)

# State Models
from .state_models import (
    GameState,
    NPCState,
    OutfitModification,
    OutfitState,
    PlayerState,
)

# Update Models
from .updates import (
    LLMResponse,
    OutfitUpdate,
    StateUpdate,
)

# Quest Models
from .quest_models import (
    QuestAction,
    QuestCondition,
    QuestDefinition,
    QuestInstance,
    QuestRewards,
    QuestStage,
    QuestTransition,
)

# Location Models
from .location_models import (
    Location,
    LocationInstance,
    LocationTransition,
    MovementRequest,
    MovementResponse,
    ScheduleEntry,
)

# Companion Models
from .companion_models import (
    CompanionDefinition,
    EmotionalStateDefinition,
    WardrobeDefinition,
)

# Story Models
from .story_models import (
    BeatExecution,
    NarrativeArc,
    StoryBeat,
)

# World Models
from .world_models import (
    EndgameCondition,
    EndgameDefinition,
    GlobalEventDefinition,
    GlobalEventEffect,
    MilestoneDefinition,
    TimeSlot,
    WorldDefinition,
)

# Media Models
from .media_models import (
    ImagePrompt,
    SceneAnalysis,
    VideoPrompt,
)

# Memory Models
from .memory_models import (
    ConversationMessage,
    MemoryEntry,
)

# Personality Models
from .personality_models import (
    BehavioralMemory,
    Impression,
    NPCLink,
    PersonalityState,
)

# Config Models
from .config_models import (
    AppConfig,
    DetectedTrait,
    PersonalityAnalysisResponse,
)

# Output Models
from .output_models import (
    IntentBundle,
    NarrativeCompassData,
    NarrativeOutput,
    TurnResult,
    VisualOutput,
)

# Re-export all for backward compatibility
__all__ = [
    # Base
    "LunaBaseModel",
    # Enums
    "BehaviorType",
    "CompositionType",
    "IntentType",
    "LocationState",
    "OutfitComponent",
    "QuestStatus",
    "TimeOfDay",
    "TraitIntensity",
    # State Models
    "GameState",
    "NPCState",
    "OutfitModification",
    "OutfitState",
    "PlayerState",
    # Update Models
    "LLMResponse",
    "OutfitUpdate",
    "StateUpdate",
    # Quest Models
    "QuestAction",
    "QuestCondition",
    "QuestDefinition",
    "QuestInstance",
    "QuestRewards",
    "QuestStage",
    "QuestTransition",
    # Location Models
    "Location",
    "LocationInstance",
    "LocationTransition",
    "MovementRequest",
    "MovementResponse",
    "ScheduleEntry",
    # Companion Models
    "CompanionDefinition",
    "EmotionalStateDefinition",
    "WardrobeDefinition",
    # Story Models
    "BeatExecution",
    "NarrativeArc",
    "StoryBeat",
    # World Models
    "EndgameCondition",
    "EndgameDefinition",
    "GlobalEventDefinition",
    "GlobalEventEffect",
    "MilestoneDefinition",
    "TimeSlot",
    "WorldDefinition",
    # Media Models
    "ImagePrompt",
    "SceneAnalysis",
    "VideoPrompt",
    # Memory Models
    "ConversationMessage",
    "MemoryEntry",
    # Personality Models
    "BehavioralMemory",
    "Impression",
    "NPCLink",
    "PersonalityState",
    # Config Models
    "AppConfig",
    "DetectedTrait",
    "PersonalityAnalysisResponse",
    # Output Models
    "IntentBundle",
    "NarrativeCompassData",
    "NarrativeOutput",
    "TurnResult",
    "VisualOutput",
]
