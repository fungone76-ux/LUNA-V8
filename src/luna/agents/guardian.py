"""Luna RPG v6 - State Guardian Agent.

Validates and applies all state updates proposed by NarrativeEngine.
NO LLM calls — pure deterministic Python.

This is the gatekeeper: nothing touches GameState without
passing through here first.

Responsibilities:
- Validate affinity changes (clamp, sanity check)
- Apply outfit updates (coherence rules)
- Apply flag changes
- Apply quest updates
- Apply NPC emotion/location changes
- Save memory facts
- Log all changes for debugging
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from luna.core.models import (
    GameState, NarrativeOutput, OutfitUpdate, WorldDefinition,
)

logger = logging.getLogger(__name__)

# Maximum affinity delta per turn (prevents LLM cheating)
_MAX_AFFINITY_DELTA = 5
_MIN_AFFINITY_DELTA = -5


class StateGuardian:
    """Validates and applies state updates from NarrativeEngine.

    All mutations to GameState pass through here.
    Returns a dict of what actually changed (for TurnResult).
    """

    def __init__(self, world: WorldDefinition) -> None:
        self.world = world

    def apply(
        self,
        narrative: NarrativeOutput,
        game_state: GameState,
        outfit_engine: Optional[Any] = None,
        allow_invite: bool = False,
    ) -> Dict[str, Any]:
        """Apply all updates from NarrativeOutput to GameState.

        Args:
            narrative:     Output from NarrativeEngine
            game_state:    Current game state (mutated in place)
            outfit_engine: OutfitEngine instance for outfit updates

        Returns:
            Dict of applied changes:
            {
                "affinity_changes": {"Luna": 2},
                "flags_set": {"flag_name": value},
                "quests_started": [...],
                "quests_completed": [...],
                "outfit_changed": bool,
                "npc_emotion": str|None,
                "new_fact": str|None,
            }
        """
        changes: Dict[str, Any] = {
            "affinity_changes": {},
            "flags_set":        {},
            "quests_started":   [],
            "quests_completed": [],
            "outfit_changed":   False,
            "npc_emotion":      None,
            "new_fact":         None,
        }

        # Apply in order: affinity → outfit → flags → quests → npc → facts → promises
        self._apply_affinity(narrative, game_state, changes)
        self._apply_outfit(narrative, game_state, outfit_engine, changes)
        self._apply_flags(narrative, game_state, changes)
        self._apply_quests(narrative, game_state, changes)
        self._apply_npc_state(narrative, game_state, changes, allow_invite=allow_invite)
        self._apply_fact(narrative, changes)
        self._apply_promises(narrative, game_state, changes)

        return changes

    # -------------------------------------------------------------------------
    # Affinity
    # -------------------------------------------------------------------------

    def _apply_affinity(
        self,
        narrative: NarrativeOutput,
        game_state: GameState,
        changes: Dict[str, Any],
    ) -> None:
        """Apply affinity changes with clamping."""
        if not narrative.affinity_change:
            return

        for character, delta in narrative.affinity_change.items():
            # Validate character exists in world
            if character not in self.world.companions:
                logger.debug(
                    "[Guardian] Ignoring affinity for unknown character: %s", character
                )
                continue

            # Clamp delta
            clamped = max(_MIN_AFFINITY_DELTA, min(_MAX_AFFINITY_DELTA, int(delta)))
            if clamped != delta:
                logger.debug(
                    "[Guardian] Affinity delta clamped: %s %+d → %+d",
                    character, delta, clamped,
                )

            # Apply
            old_val = game_state.affinity.get(character, 0)
            new_val = max(0, min(100, old_val + clamped))
            game_state.affinity[character] = new_val

            if clamped != 0:
                changes["affinity_changes"][character] = clamped
                logger.debug(
                    "[Guardian] Affinity %s: %d → %d (%+d)",
                    character, old_val, new_val, clamped,
                )

    # -------------------------------------------------------------------------
    # Outfit
    # -------------------------------------------------------------------------

    def _apply_outfit(
        self,
        narrative: NarrativeOutput,
        game_state: GameState,
        outfit_engine: Optional[Any],
        changes: Dict[str, Any],
    ) -> None:
        """Apply outfit update if proposed and valid."""
        if not narrative.outfit_update:
            return

        companion_name = game_state.active_companion
        comp_def = self.world.companions.get(companion_name)
        if not comp_def:
            return

        try:
            update_data = narrative.outfit_update
            if isinstance(update_data, dict):
                outfit_update = OutfitUpdate(**update_data)
            else:
                outfit_update = update_data

            if outfit_engine:
                outfit_engine.apply_llm_update(
                    outfit_update, game_state, comp_def, game_state.turn_count
                )
            else:
                # Fallback: apply modify_components directly
                outfit = game_state.get_outfit(companion_name)
                if outfit_update.modify_components:
                    for component, value in outfit_update.modify_components.items():
                        outfit.set_component(component, value)
                        logger.debug(
                            "[Guardian] Outfit %s.%s = %s",
                            companion_name, component, value,
                        )

            changes["outfit_changed"] = True
            logger.info("[Guardian] Outfit updated for %s", companion_name)

        except Exception as e:
            logger.warning("[Guardian] Outfit update failed: %s", e)

    # -------------------------------------------------------------------------
    # Flags
    # -------------------------------------------------------------------------

    def _apply_flags(
        self,
        narrative: NarrativeOutput,
        game_state: GameState,
        changes: Dict[str, Any],
    ) -> None:
        """Apply game flags."""
        if not narrative.set_flags:
            return

        for key, value in narrative.set_flags.items():
            if not isinstance(key, str):
                continue
            old_val = game_state.flags.get(key)
            game_state.flags[key] = value
            if old_val != value:
                changes["flags_set"][key] = value
                logger.debug("[Guardian] Flag set: %s = %r", key, value)

    # -------------------------------------------------------------------------
    # Quests
    # -------------------------------------------------------------------------

    def _apply_quests(
        self,
        narrative: NarrativeOutput,
        game_state: GameState,
        changes: Dict[str, Any],
    ) -> None:
        """Apply quest activations and completions."""
        # New quests
        for quest_id in (narrative.new_quests or []):
            if quest_id not in self.world.quests:
                logger.debug("[Guardian] Unknown quest: %s", quest_id)
                continue
            if quest_id not in game_state.active_quests:
                game_state.active_quests.append(quest_id)
                changes["quests_started"].append(quest_id)
                logger.info("[Guardian] Quest started: %s", quest_id)

        # Completed quests
        for quest_id in (narrative.complete_quests or []):
            if quest_id in game_state.active_quests:
                game_state.active_quests.remove(quest_id)
            if quest_id not in game_state.completed_quests:
                game_state.completed_quests.append(quest_id)
                changes["quests_completed"].append(quest_id)
                logger.info("[Guardian] Quest completed: %s", quest_id)

    # -------------------------------------------------------------------------
    # NPC state
    # -------------------------------------------------------------------------

    def _apply_npc_state(
        self,
        narrative: NarrativeOutput,
        game_state: GameState,
        changes: Dict[str, Any],
        allow_invite: bool = False,
    ) -> None:
        """Apply NPC emotion and location changes."""
        companion_name = game_state.active_companion

        # Emotion
        if narrative.npc_emotion:
            from luna.core.models import NPCState
            # Create NPCState if it doesn't exist yet (npc_states starts empty)
            if companion_name not in game_state.npc_states:
                game_state.npc_states[companion_name] = NPCState(name=companion_name)
            npc = game_state.npc_states[companion_name]
            old_emotion = npc.emotional_state
            # v8: record the turn so WorldSimulator can apply TTL decay
            game_state.npc_states[companion_name] = npc.model_copy(
                update={
                    "emotional_state": narrative.npc_emotion,
                    "emotional_state_set_turn": game_state.turn_count,
                }
            )
            changes["npc_emotion"] = narrative.npc_emotion
            logger.debug(
                "[Guardian] NPC emotion %s: %s → %s (turn %d)",
                companion_name, old_emotion, narrative.npc_emotion, game_state.turn_count,
            )

        # Invite accepted - only apply if it was an explicit invitation turn
        if narrative.invite_accepted and allow_invite:
            game_state.companion_staying_with_player = True
            game_state.companion_invited_to_location = game_state.current_location
            logger.info("[Guardian] Companion %s accepted invitation", companion_name)
        elif narrative.invite_accepted and not allow_invite:
            logger.debug("[Guardian] Ignoring invite_accepted=True (no explicit invitation intent)")

    # -------------------------------------------------------------------------
    # Memory facts
    # -------------------------------------------------------------------------

    def _apply_fact(
        self,
        narrative: NarrativeOutput,
        changes: Dict[str, Any],
    ) -> None:
        """Record new fact in changes dict for MemoryManager to persist."""
        if narrative.new_fact and isinstance(narrative.new_fact, str):
            fact = narrative.new_fact.strip()
            if fact:
                changes["new_fact"] = fact
                logger.debug("[Guardian] New fact recorded: %s", fact[:60])

    # -------------------------------------------------------------------------
    # Promises (v7 GM Agenda)
    # -------------------------------------------------------------------------

    def _apply_promises(
        self,
        narrative: NarrativeOutput,
        game_state: GameState,
        changes: Dict[str, Any],
    ) -> None:
        """Register new promises and resolve closed ones declared by the LLM."""
        from luna.systems.gm_agenda import add_promise, remove_promise

        if narrative.new_promise:
            promise_id = narrative.new_promise.strip()
            # Basic validation: snake_case, not internal flag, max 60 chars
            if (promise_id
                    and not promise_id.startswith("_")
                    and len(promise_id) <= 60
                    and promise_id.replace("_", "").isalnum()):
                weight = float(narrative.promise_weight) if narrative.promise_weight is not None else 0.5
                weight = max(0.0, min(1.0, weight))
                add_promise(promise_id, game_state.turn_count, game_state.flags,
                            emotional_weight=weight)
                changes["new_promise"] = promise_id

        if narrative.resolve_promise:
            promise_id = narrative.resolve_promise.strip()
            if promise_id:
                remove_promise(promise_id, game_state.flags)
                changes["resolved_promise"] = promise_id

    # -------------------------------------------------------------------------
    # Validation helpers (used by Orchestrator before calling apply)
    # -------------------------------------------------------------------------

    def validate_narrative(self, narrative: NarrativeOutput) -> bool:
        """Quick sanity check before applying updates.

        Returns True if narrative is valid enough to use.
        """
        if not narrative.text or not narrative.text.strip():
            logger.warning("[Guardian] Narrative has empty text")
            return False
        if len(narrative.text) < 5:
            logger.warning("[Guardian] Narrative text too short: %r", narrative.text)
            return False
        return True
