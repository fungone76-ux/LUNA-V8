"""Luna RPG - Quest System Models.

Quest definitions, instances, conditions, and actions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Field

from .base import LunaBaseModel
from .enums import QuestStatus


class QuestCondition(LunaBaseModel):
    """Typed condition - no eval(), explicit operators only."""
    type: Literal[
        "affinity", "location", "time", "flag", "turn_count",
        "inventory", "companion", "quest_status", "action", "player_action",
        "days_since_flag"
    ]
    target: Optional[str] = None
    operator: Literal["eq", "gt", "lt", "gte", "lte", "contains", "not_eq"] = "eq"
    value: Any = None
    pattern: Optional[str] = None  # regex for action matching
    flag: Optional[str] = None     # flag name for days_since_flag condition
    days: Optional[int] = None     # threshold for days_since_flag condition


class QuestAction(LunaBaseModel):
    """Action to execute when quest stage changes."""
    action: Literal[
        "set_location", "set_outfit", "set_flag", "add_flag",
        "change_affinity", "increment_stat", "set_emotional_state",
        "set_time", "start_quest", "complete_quest", "fail_quest",
        "time_advance", "set_secondary_npc", "clear_secondary_npc"
    ]
    character: Optional[str] = None
    target: Optional[str] = None
    key: Optional[str] = None
    value: Any = None
    outfit: Optional[str] = None
    stat: Optional[str] = None
    quest_id: Optional[str] = None


class QuestStage(LunaBaseModel):
    """Single stage within a quest."""
    title: str
    description: str = ""
    narrative_prompt: str = ""
    # What the companion knows about their own current situation during this stage.
    # Overrides the schedule-based activity_context in the LLM prompt so the NPC
    # is self-aware of quest-driven role changes (e.g. gym substitute, off-site meeting).
    companion_situation: str = ""
    # Shown in the Quest Journal UI — what the player should do to advance.
    # Separate from narrative_prompt (that goes to the LLM, this goes to the UI).
    player_hint: str = ""
    llm_context: Dict[str, Any] = Field(default_factory=dict)
    on_enter: List[QuestAction] = Field(default_factory=list)
    on_exit: List[QuestAction] = Field(default_factory=list)
    on_fail: List[QuestAction] = Field(default_factory=list)
    exit_conditions: List[QuestCondition] = Field(default_factory=list)
    # Evaluated before exit_conditions each turn. If met → quest FAILED immediately.
    fail_conditions: List[QuestCondition] = Field(default_factory=list)
    transitions: List[Any] = Field(default_factory=list)
    max_turns: Optional[int] = None  # stage timeout


class QuestRewards(LunaBaseModel):
    """Rewards granted upon quest completion."""
    affinity: Dict[str, int] = Field(default_factory=dict)
    items: List[str] = Field(default_factory=list)
    flags: Dict[str, Any] = Field(default_factory=dict)
    unlock_quests: List[str] = Field(default_factory=list)


class QuestDefinition(LunaBaseModel):
    """Complete quest definition from YAML."""
    id: str
    title: str
    description: str = ""
    character: Optional[str] = None

    # Activation
    activation_type: Literal[
        "auto", "manual", "trigger", "choice",
        "event", "random", "time_since_flag", "companion_initiative", "location_pass"
    ] = "auto"
    activation_conditions: List[QuestCondition] = Field(default_factory=list)
    trigger_event: Optional[str] = None
    hidden: bool = False

    # V5: quest priority (lower = checked first when multiple eligible)
    priority: int = Field(default=5, ge=1, le=10)

    # V5: mutual exclusion group (only one quest per group can be active)
    mutex_group: Optional[str] = Field(default=None)

    # V5: required quests that must be completed first
    required_quests: List[str] = Field(default_factory=list)

    # Choice configuration
    requires_player_choice: bool = False
    choice_title: str = ""
    choice_description: str = ""
    accept_button_text: str = "Accetta"
    decline_button_text: str = "Rifiuta"

    # V5: pending_choice timeout (turns before auto-decline)
    choice_timeout_turns: Optional[int] = Field(default=None)

    # Stages
    stages: Dict[str, QuestStage] = Field(default_factory=dict)
    start_stage: str = "start"

    rewards: QuestRewards = Field(default_factory=QuestRewards)
    on_complete: List[QuestAction] = Field(default_factory=list)


class QuestInstance(LunaBaseModel):
    """Runtime instance of a quest."""
    quest_id: str
    status: QuestStatus = QuestStatus.NOT_STARTED
    current_stage_id: Optional[str] = None
    stage_data: Dict[str, Any] = Field(default_factory=dict)
    started_at: int = Field(default=0, ge=0)
    completed_at: Optional[int] = None

    # V5: track turns in pending_choice state for timeout
    pending_since_turn: Optional[int] = Field(default=None)

    # V5: track turns in current stage for stage timeout
    stage_entered_at: int = Field(default=0, ge=0)

    custom_data: Dict[str, Any] = Field(default_factory=dict)


class QuestTransition(LunaBaseModel):
    """Transition between quest stages."""
    target_stage: str = ""
    conditions: List[Any] = Field(default_factory=list)
    condition: Any = None
    label: str = ""
