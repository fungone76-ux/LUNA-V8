"""NPCMindManagerExt — extends NPCMindManager with guaranteed off-screen delivery.

Single change over the base class: _generate_goal() elevates off-screen events
with importance >= 0.6 to Priority 0, making them non-skippable by needs/emotions.

Priority order (new):
  0. Off-screen event with importance >= 0.6 and not told_to_player  (NEW)
  1. Burning unspoken (unchanged)
  2. Untold events with importance < 0.6 (unchanged)
  3. Goal templates (unchanged)
  4. Need-driven (unchanged)
  5. Emotion-driven (unchanged)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from luna.systems.npc_mind import NPCMind, NPCGoal, GoalType, NPCMindManager

logger = logging.getLogger(__name__)

_IMPORTANT_EVENT_THRESHOLD = 0.6


class NPCMindManagerExt(NPCMindManager):
    """NPCMindManager with guaranteed delivery of important off-screen events."""

    def _generate_goal(
        self,
        mind: NPCMind,
        game_state: Any,
        turn_number: int,
    ) -> Optional[NPCGoal]:
        # Priority 0: important off-screen event not yet told
        critical_events = [
            e for e in mind.off_screen_log
            if not e.told_to_player and e.importance >= _IMPORTANT_EVENT_THRESHOLD
        ]
        if critical_events:
            event = max(critical_events, key=lambda e: e.importance)
            logger.debug(
                "[NPCMindExt] %s: important off-screen event elevated to P0 (importance=%.2f): %s",
                mind.name, event.importance, event.description,
            )
            return NPCGoal(
                description=f"Deve raccontarti urgentemente: {event.description}",
                goal_type=GoalType.SOCIAL,
                target="player",
                urgency=min(1.0, event.importance + 0.1),
                context=f"Evento accaduto al turno {event.turn}",
                source="off_screen_priority0",
                created_at_turn=turn_number,
            )

        # Priority 1–5: delegate to base class
        return super()._generate_goal(mind, game_state, turn_number)
