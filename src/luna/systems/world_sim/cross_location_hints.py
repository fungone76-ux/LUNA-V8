"""Cross-location hint generator — Fix 3 of NPC Initiative System.

When a non-active NPC has a critical goal or an important off-screen event,
injects a short diegetic hint into the LLM prompt so the player knows
something is happening elsewhere, without forcing a scene change.

Hint types (chosen deterministically by NPC name hash for stability):
  - Phone/SMS message
  - Note slipped under the door
  - Someone passing by and relaying the message

Cooldown: the hint consumes the NPC's initiative slot immediately
(turns_since_last_initiative reset to 0 inside this function).

Priority (mirrors NPCMindManagerExt.generate_goal):
  1. Off-screen event with importance >= 0.6 (not yet told to player)
  2. Critical goal (urgency >= 0.9) with source != off_screen_priority0

See docs/NPC_INITIATIVE_SPEC.md — Fix 3.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luna.systems.npc_mind_ext import NPCMindManagerExt

logger = logging.getLogger(__name__)

_IMPORTANT_EVENT_THRESHOLD = 0.6
_CRITICAL_URGENCY = 0.9

# Diegetic hint templates keyed by delivery type
_TEMPLATES: dict[str, str] = {
    "phone": (
        "[Il tuo telefono vibra — messaggio da {name}]\n"
        '"{content}"'
    ),
    "note": (
        "[Trovi un biglietto lasciato da {name}]\n"
        '"{content}"'
    ),
    "relay": (
        "[Qualcuno ti raggiunge]\n"
        '"{name} vuole che tu sappia: {content}"'
    ),
}

_DELIVERY_TYPES = list(_TEMPLATES.keys())


def _delivery_for(npc_id: str) -> str:
    """Pick a stable delivery type for this NPC (based on name hash)."""
    return _DELIVERY_TYPES[hash(npc_id) % len(_DELIVERY_TYPES)]


def get_cross_location_hint(
    mind_manager: "NPCMindManagerExt",
    active_companion: str,
    cooldown: int,
) -> str:
    """Return a diegetic hint from the most urgent non-active NPC, or "" if none.

    Side effect: resets `turns_since_last_initiative = 0` on the chosen NPCMind,
    consuming its initiative slot immediately.

    Args:
        mind_manager:      NPCMindManagerExt instance (has .minds dict)
        active_companion:  npc_id of the currently active companion (excluded)
        cooldown:          minimum turns_since_last_initiative required

    Returns:
        A non-empty string to inject into the LLM prompt, or "" if no hint.
    """
    best_mind = None
    best_content: str = ""
    best_score: float = 0.0

    for npc_id, mind in mind_manager.minds.items():
        if npc_id == active_companion:
            continue
        if mind.turns_since_last_initiative < cooldown:
            continue

        # Priority 1: off-screen event with importance >= threshold
        critical_events = [
            e for e in mind.off_screen_log
            if not e.told_to_player and e.importance >= _IMPORTANT_EVENT_THRESHOLD
        ]
        if critical_events:
            event = max(critical_events, key=lambda e: e.importance)
            score = event.importance + 0.2  # bump over goal-only candidates
            if score > best_score:
                best_score = score
                best_mind = mind
                best_content = event.description

        # Priority 2: critical goal not from off_screen
        elif (
            mind.current_goal
            and mind.current_goal.urgency >= _CRITICAL_URGENCY
            and getattr(mind.current_goal, "source", "") != "off_screen_priority0"
        ):
            score = mind.current_goal.urgency
            if score > best_score:
                best_score = score
                best_mind = mind
                best_content = mind.current_goal.description

    if best_mind is None:
        return ""

    delivery = _delivery_for(best_mind.npc_id)
    hint = _TEMPLATES[delivery].format(name=best_mind.name, content=best_content)

    # Consume initiative slot now
    best_mind.turns_since_last_initiative = 0

    logger.debug(
        "[CrossLocationHint] %s → %s (score=%.2f, delivery=%s)",
        best_mind.name, best_content[:60], best_score, delivery,
    )
    return hint
