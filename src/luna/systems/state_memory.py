"""Luna RPG V5 - State Memory Manager.

Unified persistence coordinator. Single save_all() replaces 30+ lines
of scattered save calls in the engine.

Includes phase_clock state serialization (V5 new).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from luna.core.database import DatabaseManager
    from luna.core.state import StateManager
    from luna.systems.memory import MemoryManager
    from luna.systems.quest_engine import QuestEngine
    from luna.systems.global_events import GlobalEventManager
    from luna.core.story_director import StoryDirector
    from luna.systems.personality import PersonalityEngine
    from luna.systems.phase_clock import PhaseClock

logger = logging.getLogger(__name__)

# Keys that are reconstructed each turn — safe to prune before saving
_TRANSIENT_FLAG_KEYS = {
    "_last_player_input",
    "_last_narrative_text",
    "_last_sd_prompt",
    "_last_visual_context",
}


class StateMemoryManager:
    """Coordinates all save operations in a single transaction."""

    def __init__(
        self,
        db: "DatabaseManager",
        session_id: int,
        state_manager: "StateManager",
        memory_manager: Optional["MemoryManager"] = None,
        quest_engine: Optional["QuestEngine"] = None,
        event_manager: Optional["GlobalEventManager"] = None,
        story_director: Optional["StoryDirector"] = None,
        personality_engine: Optional["PersonalityEngine"] = None,
        phase_clock: Optional["PhaseClock"] = None,
        world_simulator: Optional[Any] = None,
        tension_tracker: Optional[Any] = None,
        dynamic_event_manager: Optional[Any] = None,
        invitation_manager: Optional[Any] = None,
        npc_mind_manager: Optional[Any] = None,
    ) -> None:
        self.db = db
        self.session_id = session_id
        self.state_manager = state_manager
        self.memory_manager = memory_manager
        self.quest_engine = quest_engine
        self.event_manager = event_manager
        self.story_director = story_director
        self.personality_engine = personality_engine
        self.phase_clock = phase_clock
        self.world_simulator = world_simulator
        self.tension_tracker = tension_tracker
        self.dynamic_event_manager = dynamic_event_manager
        self.invitation_manager = invitation_manager
        self.npc_mind_manager = npc_mind_manager

    def _prune_transient_flags(self, flags: dict) -> dict:
        """Remove transient per-turn flags before saving to DB."""
        return {k: v for k, v in flags.items() if k not in _TRANSIENT_FLAG_KEYS}

    async def save_all(self, companion_location: Optional[str] = None, save_name: Optional[str] = None) -> None:
        """Save all subsystem states in a single DB transaction.
        
        Note: GameState fields (active_quests, completed_quests, failed_quests, etc.)
        are automatically serialized by Pydantic model_dump_json() in StateManager.save().
        No additional handling needed for quest lists.
        """
        async with self.db.session() as db_session:

            # 1. Core game state
            # Persist phase_clock state inside flags before saving
            if self.phase_clock:
                state = self.state_manager.current
                state.flags["_phase_clock_state"] = self.phase_clock.to_dict()

            # v7: Persist WorldSimulator (NPC minds) and TensionTracker in flags
            if self.world_simulator:
                try:
                    state = self.state_manager.current
                    sim_data = self.world_simulator.to_dict()
                    state.flags["_npc_minds_state"] = sim_data.get("minds", {})
                    state.flags["_world_sim_meta"] = {
                        "turns_since_event": sim_data.get("turns_since_event", 0),
                        "last_ambient_turn": sim_data.get("last_ambient_turn", 0),
                    }
                except Exception as e:
                    logger.warning("Could not serialize WorldSimulator: %s", e)

            if self.tension_tracker:
                try:
                    state = self.state_manager.current
                    state.flags["_tension_tracker_state"] = self.tension_tracker.to_dict()
                except Exception as e:
                    logger.warning("Could not serialize TensionTracker: %s", e)

            if self.dynamic_event_manager:
                try:
                    state = self.state_manager.current
                    state.flags["_dynamic_events_state"] = self.dynamic_event_manager.to_dict()
                except Exception as e:
                    logger.warning("Could not serialize DynamicEventManager: %s", e)

            if self.invitation_manager:
                try:
                    state = self.state_manager.current
                    state.flags["_invitation_state"] = self.invitation_manager.to_dict()
                except Exception as e:
                    logger.warning("Could not serialize InvitationManager: %s", e)

            # Prune transient per-turn flags before persisting
            state = self.state_manager.current
            state.flags = self._prune_transient_flags(state.flags)

            await self.state_manager.save(db_session, companion_location=companion_location, save_name=save_name)

            # 2. Quest states
            if self.quest_engine:
                for quest_id, instance in self.quest_engine.get_all_instances().items():
                    status_val = (
                        instance.status.value
                        if hasattr(instance.status, "value")
                        else str(instance.status)
                    )
                    import json as _json
                    _stage_data = instance.stage_data
                    if isinstance(_stage_data, dict):
                        _stage_data = _json.dumps(_stage_data)
                    await self.db.save_quest_state(
                        db_session,
                        self.session_id,
                        quest_id=quest_id,
                        status=status_val,
                        current_stage_id=instance.current_stage_id,
                        stage_data=_stage_data,
                        started_at=instance.started_at,
                        completed_at=instance.completed_at,
                        pending_since_turn=instance.pending_since_turn,
                        stage_entered_at=instance.stage_entered_at,
                    )

            # 3. Global event states
            if self.event_manager:
                try:
                    events_data = self.event_manager.to_dict().get("active_events", {})
                    await self.db.save_global_event_states(
                        db_session, self.session_id, list(events_data.values())
                    )
                except Exception as e:
                    logger.warning("Could not save global event states: %s", e)

            # 4. StoryDirector state
            if self.story_director:
                try:
                    sd_data = self.story_director.to_dict()
                    await self.db.save_story_director_state(
                        db_session,
                        self.session_id,
                        completed_beats=sd_data.get("completed_beats", []),
                        beat_history=sd_data.get("beat_history", []),
                    )
                except Exception as e:
                    logger.warning("Could not save story director state: %s", e)

            # 5. Personality states
            if self.personality_engine:
                try:
                    states = self.personality_engine.get_all_states()
                    personality_data = {"states": [s.model_dump() for s in states]}
                    await self.db.update_session(
                        db_session, self.session_id, personality_state=personality_data
                    )
                except Exception as e:
                    logger.warning("Could not save personality states: %s", e)

            # 6. NPC mind states (dedicated table — enables offline time simulation)
            if self.npc_mind_manager:
                try:
                    minds_dict = self.npc_mind_manager.to_dict()
                    await self.db.save_npc_minds(db_session, self.session_id, minds_dict)
                except Exception as e:
                    logger.warning("Could not save NPC mind states: %s", e)

        logger.debug("save_all() complete for session %d", self.session_id)

    async def add_message(
        self,
        role: str,
        content: str,
        turn_number: int,
        session_id: int,
        companion: str = "",
        visual_en: str = "",
        tags_en: Optional[List[str]] = None,
    ) -> None:
        """Add a conversation message to the DB and sync the MemoryManager cache."""
        async with self.db.session() as db_session:
            await self.db.add_message(
                db_session,
                session_id=session_id,
                role=role,
                content=content,
                turn_number=turn_number,
                visual_en=visual_en,
                tags_en=tags_en or [],
                companion=companion,
            )
        if self.memory_manager:
            await self.memory_manager.add_message(
                role=role,
                content=content,
                turn_number=turn_number,
                companion_name=companion or None,
                visual_en=visual_en,
                tags_en=tags_en,
            )
