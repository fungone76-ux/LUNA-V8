"""Luna RPG - Output Models.

Turn results, agent outputs, and narrative compass data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field, field_validator

from .base import LunaBaseModel
from .enums import IntentType


@dataclass
class NpcMovement:
    """Singolo spostamento NPC al cambio fase (manual phase advance).

    Usato da PhasePreview per mostrare alla UI chi si sposta dove
    prima che il player confermi l'avanzamento.
    """
    npc_name: str
    from_location: str
    to_location: str
    is_active_companion: bool   # True → companion attivo, genera farewell


@dataclass
class PhasePreview:
    """Preview sincrono del prossimo cambio fase — nessuna LLM call.

    Restituito da GameEngine.preview_phase_advance() e usato dalla UI
    per mostrare il warning prima che il player confermi.
    """
    current_phase: Any   # TimeOfDay
    next_phase: Any      # TimeOfDay
    movements: List[NpcMovement]   # solo NPC che cambiano location
    active_companion_leaves: bool  # shortcut per la UI


@dataclass
class NarrativeCompassData:
    """Snapshot of narrative state for the Compass UI widget.

    Populated each turn by the orchestrator and passed back in TurnResult.
    The UI reads this to update arc phase labels, tension bar, and climate text.
    """
    arc_phases: Dict[str, str]   # companion_name → phase label (ARMOR, CRACKS…)
    arc_threads: Dict[str, str]  # companion_name → short thread description
    active_tension_axis: str     # name of the hottest tension axis
    tension_phase: str           # calm / foreshadowing / buildup / trigger
    tension_level: float         # 0.0–1.0
    climate_text: str            # short whisper sentence for UI (≤80 chars)
    trend: str = ""              # "^" rising / "v" falling / "=" stable (computed by orchestrator)
    climate_ttl: int = 3         # UI refresh interval in turns (from TensionTracker)
    # Quest Journal (populated by SequentialQuestEngine.get_journal_snapshot)
    active_quest_title: str = ""
    active_stage_title: str = ""  # title of current stage
    active_stage_hint: str = ""   # player_hint of current stage
    next_quest_title: str = ""
    is_hidden: bool = False        # if True, don't show quest title in compass


@dataclass
class TurnResult:
    """Result of a complete game turn returned to the UI."""
    text: str
    user_input: str = ""
    image_path: Optional[str] = None
    audio_path: Optional[str] = None
    video_path: Optional[str] = None

    affinity_changes: Dict[str, int] = field(default_factory=dict)
    new_quests: List[str] = field(default_factory=list)
    completed_quests: List[str] = field(default_factory=list)

    available_actions: List[Dict[str, Any]] = field(default_factory=list)
    active_event: Optional[Dict[str, Any]] = None
    new_event_started: bool = False

    new_location_id: Optional[str] = None
    switched_companion: bool = False
    previous_companion: Optional[str] = None
    current_companion: Optional[str] = None
    is_temporary_companion: bool = False

    multi_npc_sequence: Optional[Any] = None
    multi_npc_image_paths: Optional[List[str]] = None  # Image paths for each MultiNPC turn
    secondary_characters: Optional[List[str]] = None

    is_photo: bool = False
    dynamic_event: Optional[Dict[str, Any]] = None

    # V5: phase change info
    phase_changed: bool = False
    companion_left_due_to_phase: bool = False
    needs_location_refresh: bool = False

    # V5: SD prompt used (for debugging)
    sd_prompt: Optional[str] = None

    # Telemetry
    initiative_event: Optional[Dict[str, Any]] = None
    turn_directive_summary: Optional[Dict[str, Any]] = None

    turn_number: int = 0
    provider_used: str = ""
    error: Optional[str] = None

    # v7: Narrative Compass data (GM Agenda Milestone 1)
    narrative_compass: Optional[Any] = None

    # v7: resolved promise id for debug UI (populated from guardian changes)
    resolved_promise: Optional[str] = None

    # v7.5: MultiNPC expanded - sequenza messaggi separati
    was_interrupted: bool = False  # True se l'utente ha interrotto la sequenza MultiNPC


class IntentBundle(LunaBaseModel):
    """Classified player intent from IntentRouter."""
    model_config = ConfigDict(strict=False, extra="ignore")
    primary:             IntentType    = IntentType.STANDARD
    target_npc:          Optional[str] = None
    target_location:     Optional[str] = None
    movement_text:       str  = ""
    freeze_action:       str  = ""
    arrival_time:        str  = ""
    comm_type:           str  = "message"
    intimate_intensity:  str  = ""
    outfit_description:  str  = ""
    event_choice_index:  int  = 0
    raw_input:           str  = ""


class NarrativeOutput(LunaBaseModel):
    """Narrative text and state updates from NarrativeEngine."""
    model_config = ConfigDict(strict=False, extra="ignore")
    text:                 str            = Field(description="Narrative text in Italian")
    visual_en:            str            = Field(default="")
    tags_en:              List[str]      = Field(default_factory=list)
    body_focus:           Optional[str]  = Field(default=None)
    aspect_ratio:         str            = Field(default="portrait")
    dop_reasoning:        str            = Field(default="")
    composition:          Optional[str]  = Field(default=None)
    secondary_characters: List[str]      = Field(default_factory=list)
    affinity_change:      Dict[str, int] = Field(default_factory=dict)
    outfit_update:        Optional[Dict[str, Any]] = Field(default=None)
    set_flags:            Dict[str, Any] = Field(default_factory=dict)
    new_quests:           List[str]      = Field(default_factory=list)
    complete_quests:      List[str]      = Field(default_factory=list)
    new_fact:             Optional[str]  = Field(default=None)
    # v7: GM Agenda — narrative promises
    new_promise:          Optional[str]   = Field(default=None)
    resolve_promise:      Optional[str]   = Field(default=None)
    promise_weight:       Optional[float] = Field(default=None)  # 0.0–1.0
    invite_accepted:      bool           = Field(default=False)
    photo_requested:      bool           = Field(default=False)
    photo_outfit:         Optional[str]  = Field(default=None)
    npc_emotion:          Optional[str]  = Field(default=None)
    provider_used:        str            = ""
    raw_response:         Optional[str]  = Field(default=None, exclude=True)

    @field_validator("affinity_change", mode="before")
    @classmethod
    def validate_affinity(cls, v: Any) -> Dict[str, int]:
        if not isinstance(v, dict):
            return {}
        return {k: max(-5, min(5, int(val))) for k, val in v.items() if isinstance(val, (int, float))}


class VisualOutput(LunaBaseModel):
    """Visual generation output from VisualDirector."""
    model_config = ConfigDict(strict=False, extra="ignore")
    positive:      str
    negative:      str       = ""
    loras:         List[str] = Field(default_factory=list)
    aspect_ratio:  str       = "portrait"
    composition:   str       = "cowboy_shot"
    width:         int       = Field(default=896,  ge=512, le=2048)
    height:        int       = Field(default=1152, ge=512, le=2048)
    dop_reasoning: str       = ""
