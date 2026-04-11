"""Luna RPG v8 — EmotionalStateEngine.

Gestisce la transizione automatica degli stati emotivi tra le quest.

Priorità:
  1. Quest-forced state (set via QuestEngine.set_emotional_state con forced=True)
  2. Auto-state calcolato da EmotionalStateEngine (da auto_states YAML)
  3. "default" come fallback

I quest-forced states durano QUEST_FORCED_TTL turni, poi cedono
il controllo all'auto-state.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from luna.core.models import CompanionDefinition, GameState, NPCState

logger = logging.getLogger(__name__)

# Turni in cui un quest-forced state rimane attivo prima che
# EmotionalStateEngine lo possa sovrascrivere
QUEST_FORCED_TTL = 20
_FORCED_FLAG     = "emotional_state_forced_{name}"
_FORCED_TURN_FLAG = "emotional_state_forced_turn_{name}"


class EmotionalStateEngine:
    """Calcola e applica gli stati emotivi automatici.

    Chiamato in TurnOrchestrator Step 0.5, dopo PresenceTracker.
    """

    def apply(
        self,
        companion: "CompanionDefinition",
        game_state: "GameState",
        present_npcs: List[str],
    ) -> Optional[str]:
        """Calcola e scrive npc_states[companion.name].emotional_state.

        Returns:
            Nome del nuovo stato se cambiato, None altrimenti.
        """
        name = companion.name

        # Controlla se uno stato è quest-forced e ancora valido
        forced_flag = _FORCED_FLAG.format(name=name)
        forced_turn_flag = _FORCED_TURN_FLAG.format(name=name)

        if game_state.flags.get(forced_flag):
            forced_at = game_state.flags.get(forced_turn_flag, 0)
            if (game_state.turn_count - forced_at) < QUEST_FORCED_TTL:
                # Stato ancora sotto controllo quest — non intervenire
                logger.debug(
                    "[EmotionalState] %s: quest-forced, skip (%d turni rimanenti)",
                    name,
                    QUEST_FORCED_TTL - (game_state.turn_count - forced_at),
                )
                return None
            else:
                # TTL scaduto — rilascia il controllo
                game_state.flags.pop(forced_flag, None)
                game_state.flags.pop(forced_turn_flag, None)
                logger.debug("[EmotionalState] %s: quest-forced TTL scaduto", name)

        # Calcola il nuovo stato
        new_state = self._compute_state(companion, game_state, present_npcs)
        
        # M3: Verify state exists in companion's emotional_states
        if companion.emotional_states and new_state not in companion.emotional_states:
            available = list(companion.emotional_states.keys())
            if available:
                logger.warning(
                    "[EmotionalStateEngine] State '%s' not found for %s, using '%s'",
                    new_state, companion.name, available[0]
                )
                new_state = available[0]
            else:
                logger.warning(
                    "[EmotionalStateEngine] No emotional_states defined for %s",
                    companion.name
                )
                return None

        # Leggi lo stato corrente
        from luna.core.models import NPCState
        if name not in game_state.npc_states:
            game_state.npc_states[name] = NPCState(name=name)

        npc = game_state.npc_states[name]
        current_state = npc.emotional_state

        if new_state == current_state:
            return None

        # Aggiorna
        game_state.npc_states[name] = npc.model_copy(
            update={"emotional_state": new_state}
        )
        # Mantieni backward-compat flag
        game_state.flags[f"emotional_state_{name}"] = new_state

        logger.info(
            "[EmotionalState] %s: %s → %s (affinità %d, presenti: %s)",
            name,
            current_state,
            new_state,
            game_state.affinity.get(name, 0),
            present_npcs,
        )
        return new_state

    def _compute_state(
        self,
        companion: "CompanionDefinition",
        game_state: "GameState",
        present_npcs: List[str],
    ) -> str:
        """Valuta gli auto_states YAML e restituisce il nome dello stato da applicare.

        Sceglie la regola con priorità più alta tra quelle con condizioni soddisfatte.
        """
        auto_states = companion.auto_states
        if not auto_states:
            return "default"

        affinity = game_state.affinity.get(companion.name, 0)
        best_priority = -1
        best_state    = "default"

        for rule in auto_states:
            state    = rule.get("state", "default")
            priority = rule.get("priority", 0)
            conds    = rule.get("conditions", {})

            if priority <= best_priority:
                continue

            if self._evaluate_conditions(conds, affinity, game_state, present_npcs):
                best_priority = priority
                best_state    = state

        return best_state

    def _evaluate_conditions(
        self,
        conds: dict,
        affinity: int,
        game_state: "GameState",
        present_npcs: List[str],
    ) -> bool:
        """Valuta un dizionario di condizioni. Tutte devono essere soddisfatte (AND)."""
        if not conds:
            return True  # regola default, sempre vera

        # affinity_gte
        if "affinity_gte" in conds:
            if affinity < conds["affinity_gte"]:
                return False

        # affinity_lt
        if "affinity_lt" in conds:
            if affinity >= conds["affinity_lt"]:
                return False

        # flag — deve essere True in game_state.flags
        if "flag" in conds:
            if not game_state.flags.get(conds["flag"]):
                return False

        # flags_not — lista di flag che NON devono essere True
        for flag_name in conds.get("flags_not", []):
            if game_state.flags.get(flag_name):
                return False

        # presence — NPC deve essere in scena
        if "presence" in conds:
            required_npc = conds["presence"]
            if required_npc not in present_npcs:
                return False

        return True
