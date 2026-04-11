"""Luna RPG v6 - Schedule Agent.

Manages the daily rhythm of companions:
- Tracks turns and phases
- Generates narrative transition warnings (1 turn before phase change)
- Handles companion departure with urgency levels
- Injects atmosphere context into NarrativeEngine
- Manages soft relocation (narrative, not hard block)

Urgency levels (defined per companion/phase in YAML):
  high   → companion leaves immediately, no negotiation
  medium → 1-turn warning, player can follow
  low    → companion mentions plans but stays 1-2 more turns if engaged

Atmosphere per phase injects mood into NarrativeEngine context.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from luna.core.models import GameState, TimeOfDay, WorldDefinition

if TYPE_CHECKING:
    from luna.systems.schedule_manager import ScheduleManager

logger = logging.getLogger(__name__)


# =============================================================================
# Phase atmosphere — injected into NarrativeEngine every turn
# =============================================================================

_PHASE_ATMOSPHERE: Dict[str, Dict[str, str]] = {
    "morning": {
        "mood":         "The school day has just begun. Routines are strict, energy is high.",
        "light":        "Bright morning light, crisp and clear.",
        "social_vibe":  "Professional and formal. People are focused on duties.",
        "opportunity":  "Good time for first impressions and direct interactions.",
    },
    "afternoon": {
        "mood":         "Lessons are over. The school is quieter. Guards come down.",
        "light":        "Warm golden light slanting through dusty windows.",
        "social_vibe":  "More relaxed. People are tired but open to conversation.",
        "opportunity":  "Easier to catch someone off-guard. Confidences flow more naturally.",
    },
    "evening": {
        "mood":         "The school is almost empty. Whoever is still here chose to stay.",
        "light":        "Orange and fading. Shadows lengthen.",
        "social_vibe":  "Intimate. The usual rules feel distant. Rare confessions happen here.",
        "opportunity":  "The best time for real conversations. Walls are lowest.",
    },
    "night": {
        "mood":         "The school is dark and silent. Being here is unusual — even transgressive.",
        "light":        "Only emergency lighting, moonlight through windows.",
        "social_vibe":  "Everything feels closer, more charged, slightly forbidden.",
        "opportunity":  "Exceptional moments happen at night. Affinity matters much more.",
    },
}

# Affinity multiplier per phase
_PHASE_AFFINITY_MULT: Dict[str, float] = {
    "morning":   1.0,
    "afternoon": 1.2,
    "evening":   1.5,
    "night":     2.0,
}

# =============================================================================
# Transition messages — used when companion is about to leave
# =============================================================================

_WARNING_MESSAGES: Dict[str, List[str]] = {
    "medium": [
        "{name} glances at the clock on the wall.",
        "{name} starts gathering her things slowly.",
        "{name} checks her watch with a slight frown.",
        "{name} pauses, as if remembering something she needs to do.",
    ],
    "low": [
        "{name} mentions she'll need to leave soon.",
        "{name} says she has something to attend to later.",
        "{name} glances toward the door, distracted.",
    ],
}

_DEPARTURE_MESSAGES: Dict[str, List[str]] = {
    "high": [
        "{name} closes her register firmly. «{reason}» She does not wait for a reply.",
        "{name} stands abruptly. «{reason}» She is already moving toward the door.",
        "«{reason}» {name} says, collecting her things with practiced efficiency.",
    ],
    "medium": [
        "{name} rises, unhurried. «{reason}» She pauses at the door for just a moment.",
        "«{reason}» {name} says softly, as if giving you a chance to stop her.",
        "{name} gathers her bag. «{reason}» Her eyes meet yours briefly before she leaves.",
    ],
    "low": [
        "{name} stands slowly. «{reason}» She seems reluctant to go.",
        "«{reason}» {name} says, leaving the door open behind her.",
        "{name} hesitates. «{reason}» But she goes.",
    ],
}

# Per-companion departure reasons per destination phase
_DEPARTURE_REASONS: Dict[str, Dict[str, str]] = {
    "Luna": {
        "afternoon": "I have papers to correct.",
        "evening":   "I need to prepare tomorrow's lessons.",
        "night":     "It is time to go home.",
        "morning":   "Class starts in five minutes.",
    },
    "Stella": {
        "afternoon": "Basketball practice. Can't miss it.",
        "evening":   "Going to meet some friends at the bar.",
        "night":     "I should get home before it's too late.",
        "morning":   "Class is starting.",
    },
    "Maria": {
        "afternoon": "Still have the gym to clean.",
        "evening":   "Almost done for today.",
        "night":     "My shift is over.",
        "morning":   "Lots to clean before the students arrive.",
    },
}


# =============================================================================
# ScheduleAgent
# =============================================================================

@dataclass
class TransitionEvent:
    """Fired one turn before a phase change (warning) or at phase change."""
    is_warning:       bool           # True = 1 turn before, False = actual change
    old_phase:        TimeOfDay
    new_phase:        TimeOfDay
    companion_name:   str
    urgency:          str            # high / medium / low
    narrative_hint:   str            # text to inject into NarrativeEngine context
    companion_leaves: bool           # True = companion departs this turn
    follow_possible:  bool           # True = player can follow companion


class ScheduleAgent:
    """Manages daily rhythm, atmosphere and companion transitions.

    Called by TurnOrchestrator at Steps 3-4 (context building).
    Does NOT call the LLM — only prepares context strings.
    """

    def __init__(
        self,
        world: WorldDefinition,
        schedule_manager: "ScheduleManager",
        turns_per_phase: int = 8,
    ) -> None:
        self.world            = world
        self.schedule_manager = schedule_manager
        self.turns_per_phase  = turns_per_phase

        # Warning already sent this phase (avoid repeating)
        self._warning_sent: Dict[str, bool] = {}

        # Track if companion is in "soft departure" state
        # (medium/low urgency — player has one more turn)
        self._pending_departure: Dict[str, bool] = {}

    # =========================================================================
    # Main entry — called every turn
    # =========================================================================

    def tick(
        self,
        game_state: GameState,
        turn_in_phase: int,
        current_phase: TimeOfDay,
        next_phase: TimeOfDay,
    ) -> Dict[str, Any]:
        """Compute schedule context for this turn.

        Returns a dict with keys:
          atmosphere_context  — injected into NarrativeEngine
          transition_event    — Optional[TransitionEvent]
          affinity_multiplier — float for Guardian to apply
        """
        phase_key  = current_phase.value if hasattr(current_phase, "value") else str(current_phase)
        companion  = game_state.active_companion

        result: Dict[str, Any] = {
            "atmosphere_context":  self._build_atmosphere(phase_key, companion, game_state),
            "transition_event":    None,
            "affinity_multiplier": _PHASE_AFFINITY_MULT.get(phase_key, 1.0),
        }

        # No transitions for solo or temporary companions
        if companion in ("_solo_", None):
            return result
        comp_def = self.world.companions.get(companion)
        if getattr(comp_def, "is_temporary", False):
            return result

        # Turns until phase ends
        turns_left = self.turns_per_phase - turn_in_phase

        # --- Warning (1 turn before change) ---
        turns_per_phase = self.turns_per_phase  # expose for departure check
        warning_key = f"{companion}_{phase_key}"
        if turns_left == 1 and not self._warning_sent.get(warning_key):
            urgency = self._get_urgency(companion, next_phase)
            if urgency in ("medium", "low"):
                hint = self._build_warning(companion, urgency)
                result["transition_event"] = TransitionEvent(
                    is_warning=True,
                    old_phase=current_phase,
                    new_phase=next_phase,
                    companion_name=companion,
                    urgency=urgency,
                    narrative_hint=hint,
                    companion_leaves=False,
                    follow_possible=True,
                )
                self._warning_sent[warning_key] = True
                self._pending_departure[companion] = True
                logger.debug("[ScheduleAgent] Warning: %s urgency=%s", companion, urgency)

        # --- Actual departure (first turn of new phase) ---
        # Fire if pending departure OR if urgency is high (no warning needed)
        urgency_next = self._get_urgency(companion, next_phase)
        should_depart = (
            self._pending_departure.get(companion) or
            (turn_in_phase == turns_per_phase - 1 and urgency_next == "high")
        )
        if turn_in_phase == 0 and should_depart:
            urgency = self._get_urgency(companion, current_phase)
            hint    = self._build_departure(companion, current_phase, urgency)
            follow  = urgency in ("medium", "low")
            result["transition_event"] = TransitionEvent(
                is_warning=False,
                old_phase=next_phase,
                new_phase=current_phase,
                companion_name=companion,
                urgency=urgency,
                narrative_hint=hint,
                companion_leaves=True,
                follow_possible=follow,
            )
            self._pending_departure[companion] = False
            self._warning_sent = {}
            logger.info("[ScheduleAgent] Departure: %s urgency=%s", companion, urgency)

        return result

    # =========================================================================
    # Atmosphere context
    # =========================================================================

    def _build_atmosphere(
        self,
        phase_key: str,
        companion: str,
        game_state: GameState,
    ) -> str:
        atm = _PHASE_ATMOSPHERE.get(phase_key, {})
        if not atm:
            return ""

        activity = ""
        if companion and companion != "_solo_":
            activity = self.schedule_manager.get_npc_activity(
                companion,
                game_state.time_of_day,
            ) or ""

        lines = [
            f"=== TIME OF DAY: {phase_key.upper()} ===",
            f"Mood: {atm.get('mood', '')}",
            f"Light: {atm.get('light', '')}",
            f"Social vibe: {atm.get('social_vibe', '')}",
            f"Opportunity: {atm.get('opportunity', '')}",
        ]
        if activity:
            lines.append(f"Companion current activity: {activity}")

        return "\n".join(lines)

    # =========================================================================
    # Urgency
    # =========================================================================

    def _get_urgency(self, companion: str, target_phase: TimeOfDay) -> str:
        """Get urgency for companion moving into target_phase."""
        phase_key = target_phase.value if hasattr(target_phase, "value") else str(target_phase)
        try:
            entry = self.schedule_manager.get_entry(companion, target_phase)
            if entry and hasattr(entry, "urgency"):
                return entry.urgency or "medium"
        except Exception:
            pass

        # Defaults by phase
        defaults = {
            "morning":   "high",    # class starts — no negotiation
            "afternoon": "medium",  # papers to correct — can follow
            "evening":   "low",     # optional — may stay
            "night":     "high",    # going home — no negotiation
        }
        return defaults.get(phase_key, "medium")

    # =========================================================================
    # Narrative hints
    # =========================================================================

    def _build_warning(self, companion: str, urgency: str) -> str:
        templates = _WARNING_MESSAGES.get(urgency, _WARNING_MESSAGES["medium"])
        text = random.choice(templates).format(name=companion)
        return f"[Schedule hint — include naturally in narrative]: {text}"

    def _build_departure(
        self,
        companion: str,
        new_phase: TimeOfDay,
        urgency: str,
    ) -> str:
        phase_key = new_phase.value if hasattr(new_phase, "value") else str(new_phase)
        reason    = _DEPARTURE_REASONS.get(companion, {}).get(
            phase_key, "She has somewhere to be."
        )
        templates = _DEPARTURE_MESSAGES.get(urgency, _DEPARTURE_MESSAGES["medium"])
        text      = random.choice(templates).format(name=companion, reason=reason)

        follow_hint = ""
        if urgency in ("medium", "low"):
            follow_hint = " [Player can offer to follow her.]"

        return f"[Schedule departure — {urgency} urgency]: {text}{follow_hint}"

    # =========================================================================
    # Phase atmosphere for standalone use
    # =========================================================================

    def get_atmosphere(self, phase: TimeOfDay) -> Dict[str, str]:
        phase_key = phase.value if hasattr(phase, "value") else str(phase)
        return _PHASE_ATMOSPHERE.get(phase_key, {})

    def get_affinity_multiplier(self, phase: TimeOfDay) -> float:
        phase_key = phase.value if hasattr(phase, "value") else str(phase)
        return _PHASE_AFFINITY_MULT.get(phase_key, 1.0)

    def reset_phase(self) -> None:
        """Call when a new phase begins to reset warning state.
        NOTE: We keep _pending_departure so departure fires next turn.
        """
        self._warning_sent.clear()
        # Do NOT clear _pending_departure here — departure fires on next turn
