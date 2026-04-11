"""World Simulator — turn driver decision logic."""
from __future__ import annotations

import logging
import random
import re
from typing import Any, Optional, Tuple, TYPE_CHECKING

from luna.systems.npc_mind import GoalType, NPCGoal, NPCMind, TurnDriver
from luna.systems.world_sim.models import NPCInitiative, TurnDirective

if TYPE_CHECKING:
    from luna.systems.npc_mind import NPCMindManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Low-energy input detection
# ---------------------------------------------------------------------------

_LOW_ENERGY_PATTERNS = [
    r"^(ok|okay|va bene|bene|sì|si|no|mh|hmm|ah|oh|eh|già|davvero|capisco)[\.\!\?]*$",
    r"^(continua|prosegui|avanti|e poi|dimmi|racconta|vai)[\.\!\?]*$",
    r"^(ciao|salve|hey|ehi)[\.\!\?]*$",
    r"^\.+$",
    r"^\s*$",
]
_LOW_ENERGY_RE = [re.compile(p, re.IGNORECASE) for p in _LOW_ENERGY_PATTERNS]


def is_low_energy_input(text: str) -> bool:
    """Check if player input is generic/low-effort."""
    stripped = text.strip()
    if len(stripped) <= 3:
        return True
    return any(r.match(stripped) for r in _LOW_ENERGY_RE)


# ---------------------------------------------------------------------------
# TurnDirector
# ---------------------------------------------------------------------------

_SPECIFIC_INTENT_NAMES = {
    "movement", "invitation", "outfit_major",
    "summon", "intimate_scene", "rest",
    "farewell", "remote_comm",
}
_INITIATIVE_COOLDOWN = 3


class TurnDirector:
    """Decides who drives the turn and builds NPCInitiative."""

    def __init__(self, mind_manager: "NPCMindManager", cooldown: int = _INITIATIVE_COOLDOWN) -> None:
        self.mind_manager = mind_manager
        self.cooldown = cooldown
        self._turns_since_event: int = 0

    def decide(
        self,
        player_input: str,
        intent: Any,
        game_state: Any,
        turn: int,
    ) -> Tuple[TurnDriver, Optional[NPCInitiative]]:
        """Decide who drives the turn. Returns (TurnDriver, Optional[NPCInitiative])."""

        # 1. Specific player intents → player drives
        intent_name = ""
        if hasattr(intent, "primary"):
            p = intent.primary
            intent_name = p.value if hasattr(p, "value") else str(p)
        if intent_name.lower() in _SPECIFIC_INTENT_NAMES:
            return TurnDriver.PLAYER, None

        # 2. Substantial player input → player drives
        if not is_low_energy_input(player_input) and len(player_input.strip()) > 15:
            return TurnDriver.PLAYER, None

        active = game_state.active_companion
        active_mind = self.mind_manager.get(active)

        # 3. Active NPC has urgent goal
        if active_mind and active_mind.current_goal:
            goal = active_mind.current_goal
            cooldown_ok = active_mind.turns_since_last_initiative >= self.cooldown
            if goal.is_critical and cooldown_ok:
                # urgency >= 0.9 → always interrupt, regardless of player input
                return TurnDriver.NPC, self._make_initiative(active_mind, goal)
            if goal.is_urgent and cooldown_ok:
                # urgency >= 0.7 → 40% chance even on normal input, 100% on low energy
                if is_low_energy_input(player_input) or random.random() < 0.4:
                    return TurnDriver.NPC, self._make_initiative(active_mind, goal)
            if goal.urgency >= 0.5 and is_low_energy_input(player_input) and cooldown_ok:
                if random.random() < 0.5:
                    return TurnDriver.NPC, self._make_initiative(active_mind, goal)

        # 4. Burning unspoken items
        if active_mind and active_mind.has_burning_unspoken:
            cooldown_ok = active_mind.turns_since_last_initiative >= self.cooldown
            if cooldown_ok and is_low_energy_input(player_input):
                burning = [u for u in active_mind.unspoken if u.is_burning][0]
                goal = NPCGoal(
                    description=f"Deve parlarti di: {burning.content}",
                    goal_type=GoalType.CONFRONTATION,
                    target="player",
                    urgency=burning.emotional_weight,
                    source="burning_unspoken",
                    created_at_turn=turn,
                )
                return TurnDriver.NPC, self._make_initiative(active_mind, goal)

        # 5. Many turns without events → ambient enrichment
        if self._turns_since_event > 5 and is_low_energy_input(player_input):
            return TurnDriver.AMBIENT, None

        return TurnDriver.PLAYER, None

    def _make_initiative(self, mind: NPCMind, goal: NPCGoal) -> NPCInitiative:
        dom_emo = mind.dominant_emotion
        emo_str = dom_emo.emotion.value if dom_emo else "neutral"
        if goal.urgency >= 0.9:
            urgency = "critical"
        elif goal.urgency >= 0.7:
            urgency = "high"
        elif goal.urgency >= 0.4:
            urgency = "medium"
        else:
            urgency = "low"
        return NPCInitiative(
            npc_id=mind.npc_id,
            npc_name=mind.name,
            action=goal.description,
            goal_context=goal.context,
            emotional_state=emo_str,
            urgency=urgency,
            goal_type=goal.goal_type.value,
        )

    def should_use_director(self, directive: TurnDirective) -> bool:
        """Decide if the DirectorAgent should be called this turn.

        v8: expanded conditions — Director is now called for any NPC-driven turn,
        not just extreme cases. This makes NPC initiative much more coherent.
        """
        # Multi-NPC scene always needs direction
        if len(directive.npcs_in_scene) >= 3:
            return True
        # v8: ANY NPC initiative turn gets DirectorAgent (was only high/critical)
        if directive.npc_initiative:
            return True
        # High tension always needs direction
        if directive.narrative_pressure and directive.narrative_pressure.pressure_level >= 0.65:
            return True
        return False

    def increment_event_counter(self) -> None:
        self._turns_since_event += 1

    def reset_event_counter(self) -> None:
        self._turns_since_event = 0
