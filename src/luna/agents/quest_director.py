"""Luna RPG v6 - QuestDirector Agent.

Enhances the base QuestEngine with:

1. IMPRESSION-BASED BRANCHING
   Each quest stage can have variants triggered by T/A/F/C impression values.
   The same stage plays out differently depending on relationship state.

2. PERSISTENT CONSEQUENCES
   Completed quests leave flags that affect future quest narratives.
   Luna remembers what happened between you.

3. BEHAVIOR-REACTIVE ACTIVATION
   Some quests activate not on affinity alone, but on behavior patterns
   (e.g. 5 respectful turns → unlock different confidences).

4. CONTEXTUAL EVENTS
   Global events (Blackout, Rainstorm) are filtered by location and
   can trigger outfit changes or special narrative conditions.

The QuestDirector sits between the QuestEngine and the NarrativeEngine —
it enriches the quest_context that Gemini receives.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from luna.core.models import GameState, Impression, WorldDefinition

if TYPE_CHECKING:
    from luna.systems.personality import PersonalityEngine
    from luna.systems.quest_engine import QuestEngine

logger = logging.getLogger(__name__)


# =============================================================================
# Stage variant — impression-based branching
# =============================================================================

@dataclass
class StageVariant:
    """A variant of a quest stage triggered by impression thresholds."""
    variant_id:      str
    narrative_hint:  str        # injected into NarrativeEngine context
    min_trust:       int = -100
    min_attraction:  int = -100
    max_fear:        int =  100
    min_curiosity:   int = -100
    requires_flag:   Optional[str] = None
    priority:        int = 0    # higher = checked first


@dataclass
class QuestVariantConfig:
    """Variant definitions for a specific quest stage."""
    quest_id:  str
    stage_id:  str
    variants:  List[StageVariant] = field(default_factory=list)


# =============================================================================
# Built-in variant definitions for school_life_complete
# =============================================================================

_BUILTIN_VARIANTS: List[QuestVariantConfig] = [

    # ── luna_private_lesson ───────────────────────────────────────────────────
    QuestVariantConfig(
        quest_id="luna_private_lesson",
        stage_id="the_lesson",
        variants=[
            StageVariant(
                variant_id="vulnerable",
                narrative_hint=(
                    "[Quest variant: VULNERABLE] Luna's defenses are low. "
                    "She is nervous and candid. The lesson becomes an intimate confession. "
                    "She may let something personal slip. Play this as raw and unguarded."
                ),
                min_trust=60,
                max_fear=20,
                priority=10,
            ),
            StageVariant(
                variant_id="seductive",
                narrative_hint=(
                    "[Quest variant: SEDUCTIVE] Luna is fully aware of the tension. "
                    "She uses it deliberately. Professional facade slips intentionally. "
                    "Every gesture is calculated. She is testing how far you will go."
                ),
                min_attraction=55,
                max_fear=30,
                priority=9,
            ),
            StageVariant(
                variant_id="conflicted",
                narrative_hint=(
                    "[Quest variant: CONFLICTED] Luna is torn. She wants this but "
                    "her professional conscience is fighting back. She may stop and "
                    "restart. This tension is the scene — do not resolve it easily."
                ),
                min_trust=30,
                min_attraction=30,
                priority=5,
            ),
            StageVariant(
                variant_id="resistant",
                narrative_hint=(
                    "[Quest variant: RESISTANT] Luna regrets inviting you. "
                    "She keeps distance, speaks formally, looks for an excuse to end this. "
                    "The player must work hard to maintain the scene."
                ),
                max_fear=100,
                min_trust=-100,
                priority=2,
            ),
        ],
    ),

    # ── luna_divorce ──────────────────────────────────────────────────────────
    QuestVariantConfig(
        quest_id="luna_divorce",
        stage_id="confession",
        variants=[
            StageVariant(
                variant_id="deep_trust",
                narrative_hint=(
                    "[Quest variant: DEEP TRUST] Luna tells you everything about the divorce. "
                    "Names, dates, reasons. She cries. She hasn't told anyone else. "
                    "This is the most vulnerable she has ever been with you."
                ),
                min_trust=70,
                requires_flag="luna_private_lesson_done",
                priority=10,
            ),
            StageVariant(
                variant_id="guarded",
                narrative_hint=(
                    "[Quest variant: GUARDED] Luna hints at the divorce but never says it directly. "
                    "She deflects, uses metaphors, stops herself mid-sentence. "
                    "Something is there but she is not ready. Leave the door open."
                ),
                priority=1,
            ),
        ],
    ),

    # ── luna_gym ─────────────────────────────────────────────────────────────
    QuestVariantConfig(
        quest_id="luna_gym",
        stage_id="the_class",
        variants=[
            StageVariant(
                variant_id="playful",
                narrative_hint=(
                    "[Quest variant: PLAYFUL] Outside the classroom Luna is different. "
                    "She teases, laughs, is competitive. The power dynamic is more equal here. "
                    "She may challenge you physically. Enjoy the shift."
                ),
                min_attraction=40,
                max_fear=25,
                priority=8,
            ),
            StageVariant(
                variant_id="professional",
                narrative_hint=(
                    "[Quest variant: PROFESSIONAL] Luna treats this exactly like a lesson. "
                    "Strict, measured, no exceptions. The gym is still her territory. "
                    "She will not let the usual tension enter here."
                ),
                priority=1,
            ),
        ],
    ),
]


# =============================================================================
# Behavior pattern tracker
# =============================================================================

@dataclass
class BehaviorPattern:
    """Tracks consecutive behavior patterns for reactive quest activation."""
    respectful_streak:   int = 0
    aggressive_streak:   int = 0
    romantic_streak:     int = 0
    last_behavior:       str = ""


# =============================================================================
# QuestDirector
# =============================================================================

class QuestDirector:
    """Enriches quest context with impression-based variants and consequences.

    Called by TurnOrchestrator in Step 4 (_enrich_context).
    Does NOT replace QuestEngine — it works alongside it.
    """

    def __init__(
        self,
        world: WorldDefinition,
        quest_engine: "QuestEngine",
        personality_engine: Optional["PersonalityEngine"] = None,
    ) -> None:
        self.world             = world
        self.quest_engine      = quest_engine
        self.personality_engine = personality_engine

        # Load variant configs
        self._variants: Dict[Tuple[str, str], QuestVariantConfig] = {}
        for cfg in _BUILTIN_VARIANTS:
            self._variants[(cfg.quest_id, cfg.stage_id)] = cfg

        # Behavior pattern per companion
        self._patterns: Dict[str, BehaviorPattern] = {}

        # Consequence flags (persistent between quests)
        self._consequence_cache: Dict[str, bool] = {}

    # =========================================================================
    # Main entry — called every turn
    # =========================================================================

    def get_enriched_context(
        self,
        game_state: GameState,
        user_input: str,
        base_quest_context: str,
    ) -> str:
        """Return enriched quest context for NarrativeEngine.

        Adds variant hints, consequence notes, and behavior observations.
        """
        parts = []

        if base_quest_context:
            parts.append(base_quest_context)

        # 1. Impression-based stage variant
        variant_hint = self._get_stage_variant_hint(game_state)
        if variant_hint:
            parts.append(variant_hint)

        # 2. Consequence context from past quests
        consequence = self._get_consequence_context(game_state)
        if consequence:
            parts.append(consequence)

        # 3. Behavior pattern observation
        pattern_hint = self._get_behavior_hint(game_state, user_input)
        if pattern_hint:
            parts.append(pattern_hint)

        return "\n".join(parts)

    # =========================================================================
    # 1. Impression-based variant selection
    # =========================================================================

    def _get_stage_variant_hint(self, game_state: GameState) -> str:
        """Select the best variant for current active quest stage."""
        companion = game_state.active_companion
        if not companion or companion == "_solo_":
            return ""

        # Get impression
        imp = self._get_impression(companion)
        if not imp:
            return ""

        # Find active quest for this companion
        for quest_id in game_state.active_quests:
            quest_def = self.world.quests.get(quest_id)
            if not quest_def:
                continue
            if quest_def.character != companion:
                continue

            instance = self.quest_engine._instances.get(quest_id)
            if not instance:
                continue

            stage_id = instance.current_stage_id or quest_def.start_stage
            cfg = self._variants.get((quest_id, stage_id))
            if not cfg:
                continue

            variant = self._select_variant(cfg.variants, imp, game_state)
            if variant:
                logger.debug(
                    "[QuestDirector] Variant '%s' for %s/%s",
                    variant.variant_id, quest_id, stage_id
                )
                return variant.narrative_hint

        return ""

    def _select_variant(
        self,
        variants: List[StageVariant],
        imp: Impression,
        game_state: GameState,
    ) -> Optional[StageVariant]:
        """Select highest priority matching variant."""
        candidates = []
        for v in variants:
            # Check flag requirement
            if v.requires_flag and not game_state.flags.get(v.requires_flag):
                continue
            # Check impression thresholds
            if imp.trust < v.min_trust:
                continue
            if imp.attraction < v.min_attraction:
                continue
            if imp.fear > v.max_fear:
                continue
            if imp.curiosity < v.min_curiosity:
                continue
            candidates.append(v)

        if not candidates:
            return None
        return max(candidates, key=lambda v: v.priority)

    # =========================================================================
    # 2. Consequence context
    # =========================================================================

    def _get_consequence_context(self, game_state: GameState) -> str:
        """Build context from completed quests that affect current situation."""
        companion = game_state.active_companion
        if not companion or companion == "_solo_":
            return ""

        notes = []

        # Map completed quest → consequence note
        consequence_map = {
            "luna_private_lesson": (
                "luna_private_lesson_done",
                "[History] You and Luna have already crossed professional boundaries. "
                "She knows it. The tension carries that weight."
            ),
            "luna_divorce": (
                "luna_divorce_revealed",
                "[History] Luna has told you about her divorce. "
                "She is more vulnerable with you than with anyone else."
            ),
            "luna_gym": (
                "luna_gym_done",
                "[History] You have seen Luna outside the classroom. "
                "The dynamic between you is more equal now."
            ),
            "luna_final_choice": (
                "luna_ending_reached",
                "[History] Luna has made her choice. Whatever happens now "
                "carries the full weight of that decision."
            ),
        }

        for quest_id, (flag_key, note) in consequence_map.items():
            if quest_id in game_state.completed_quests:
                # Set persistent flag
                if not game_state.flags.get(flag_key):
                    game_state.flags[flag_key] = True
                notes.append(note)

        return "\n".join(notes)

    # =========================================================================
    # 3. Behavior pattern tracking
    # =========================================================================

    def update_behavior_pattern(
        self,
        companion: str,
        user_input: str,
        detected_traits: List[str],
    ) -> None:
        """Update behavior streak tracking."""
        if companion not in self._patterns:
            self._patterns[companion] = BehaviorPattern()

        p = self._patterns[companion]

        if "submissive" in detected_traits or "respectful" in detected_traits:
            p.respectful_streak += 1
            p.aggressive_streak = 0
            p.romantic_streak = 0
        elif "aggressive" in detected_traits or "dominant" in detected_traits:
            p.aggressive_streak += 1
            p.respectful_streak = 0
            p.romantic_streak = 0
        elif "romantic" in detected_traits or "teasing" in detected_traits:
            p.romantic_streak += 1
            p.aggressive_streak = 0

    def _get_behavior_hint(
        self, game_state: GameState, user_input: str
    ) -> str:
        """Return a behavioral observation for the NarrativeEngine."""
        companion = game_state.active_companion
        if not companion or companion == "_solo_":
            return ""

        p = self._patterns.get(companion)
        if not p:
            return ""

        if p.respectful_streak >= 5:
            return (
                ""
                f"{companion} is noticing. She may lower her guard slightly."
            )
        if p.aggressive_streak >= 4:
            return (
                ""
                f"{companion} is feeling the pressure. She may push back or shut down."
            )
        if p.romantic_streak >= 4:
            return (
                ""
                f"{companion} cannot fully ignore it anymore."
            )
        return ""

    # =========================================================================
    # Contextual event filtering
    # =========================================================================

    def filter_event_for_context(
        self,
        event: Any,
        game_state: GameState,
    ) -> Optional[str]:
        """Return event narrative_prompt only if event is contextually valid."""
        if not event:
            return None

        event_id = getattr(event, "event_id", "")
        current_loc = game_state.current_location or ""

        # Location filters
        location_filters = {
            "blackout": lambda loc: "school" in loc,
            "rainstorm": lambda loc: True,  # anywhere
        }

        loc_filter = location_filters.get(event_id)
        if loc_filter and not loc_filter(current_loc):
            logger.debug(
                "[QuestDirector] Event '%s' filtered out for location '%s'",
                event_id, current_loc
            )
            return None

        # Return narrative prompt with companion substituted
        companion = game_state.active_companion or "your companion"
        prompt = getattr(event, "narrative_prompt", "") or ""
        return prompt.replace("{current_companion}", companion)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_impression(self, companion: str) -> Optional[Impression]:
        """Get current impression for companion."""
        if not self.personality_engine:
            return None
        try:
            state = self.personality_engine._states.get(companion)
            return state.impression if state else None
        except Exception:
            return None

    def set_personality_engine(self, engine: "PersonalityEngine") -> None:
        self.personality_engine = engine
