"""Luna RPG - Orchestrator Support Methods Mixin.

Support methods for farewell generation, media generation, and minimal narratives.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from luna.core.models import GameState, NarrativeOutput

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SupportMethodsMixin:
    """Mixin providing support methods for TurnOrchestrator.
    
    Contains helper methods for farewells, media generation, and minimal narratives.
    """

    async def _generate_farewell(
        self,
        companion_name: str,
        new_phase: Any,
        new_location: str,
        game_state: Any,
        transition_event: Any,
    ) -> Optional[Any]:
        """Generate farewell narrative when companion leaves due to phase change."""
        try:
            comp_def = self.engine.world.companions.get(companion_name)
            if not comp_def:
                return None

            phase_key = new_phase.value if hasattr(new_phase, "value") else str(new_phase)
            loc_def   = self.engine.world.locations.get(new_location)
            loc_name  = loc_def.name if loc_def else new_location

            farewell_reasons = {
                "afternoon": "I have to go. Papers to correct.",
                "evening":   "It is getting late. I need to prepare for tomorrow.",
                "night":     "Time to go home.",
                "morning":   "Class is about to start.",
            }
            reason = farewell_reasons.get(phase_key, "I have somewhere to be.")

            urgency = getattr(transition_event, "urgency", "medium") if transition_event else "medium"
            urgency_instruction = {
                "high":   "She leaves immediately. Short and direct.",
                "medium": "She lingers a moment. Gives the player a beat to react.",
                "low":    "She seems reluctant. Pauses at the door.",
            }.get(urgency, "She leaves.")

            farewell_prompt = (
                "FAREWELL SCENE - " + companion_name + " must now leave. "
                "Reason: " + reason + " "
                "Destination: " + loc_name + ". "
                "Tone: " + urgency_instruction + " "
                "ONE action beat + ONE spoken line. MAX 2 sentences. "
                "Italian. Stay in character."
            )

            farewell_context = {
                "user_input":           "[phase change]",
                "quest_context":        "",
                "story_context":        farewell_prompt,
                "memory_context":       "",
                "conversation_history": "",
                "activity_context":     "",
                "personality_context":  "",
                "schedule_context":     "",
                "forced_poses":         "",
                "event_context":        "",
                "initiative_context":   "",
                "initiative_switch":    None,
                "multi_npc_context":    "",
                "switched_from":        None,
                "is_temporary":         False,
                "in_remote_comm":       False,
                "remote_target":        None,
                "affinity_multiplier":  1.0,
            }

            result = await self._narrative.generate(
                user_input="[companion farewell]",
                game_state=game_state,
                llm_manager=self.engine.llm_manager,
                context=farewell_context,
            )
            logger.info("[Orchestrator] Farewell generated for %s", companion_name)
            return result
        except Exception as e:
            logger.warning("[Orchestrator] Farewell generation failed: %s", e)
            return None

    # =========================================================================
    # Step 8: Save
    # =========================================================================

    async def _generate_media(
        self,
        game_state: GameState,
        narrative: NarrativeOutput,
        visual_output: Any,
    ) -> Optional[Dict[str, Any]]:
        if self.engine.no_media or not self.engine.media_pipeline:
            return None

        try:
            comp_def = self.engine.world.companions.get(game_state.active_companion)
            # For solo mode or template NPCs, use base_prompt from comp_def if available
            base_prompt = comp_def.base_prompt if comp_def else ""
            companion_name = game_state.active_companion
            result   = await self.engine.media_pipeline.generate_all(
                text=narrative.text,
                visual_en=visual_output.positive,
                tags=narrative.tags_en,
                companion_name=companion_name,
                base_prompt=base_prompt,
                location_id=game_state.current_location,
                composition=visual_output.composition,
                aspect_ratio=visual_output.aspect_ratio,
                # Always pass VisualDirector prompt — it handles solo mode correctly
                # (solo prompt already contains "no humans, empty scene")
                sd_positive=visual_output.positive if visual_output else None,
                sd_negative=visual_output.negative if visual_output else None,
                extra_loras=visual_output.loras if visual_output else None,
            )
            if not result:
                return None
            return {
                "image_path": getattr(result, "image_path", None),
                "audio_path": getattr(result, "audio_path", None),
                "video_path": getattr(result, "video_path", None),
            }
        except Exception as e:
            logger.warning("[Orchestrator] Media generation failed: %s", e)
            return None

    # =========================================================================
    # Fallback narrative
    # =========================================================================

    def _minimal_narrative(self, game_state: GameState) -> NarrativeOutput:
        """Always-valid fallback when NarrativeEngine produces invalid output."""
        comp  = self.engine.world.companions.get(game_state.active_companion)
        name  = comp.name if comp else game_state.active_companion
        loc   = game_state.current_location

        return NarrativeOutput(
            text=f"*{name} ti guarda in silenzio.* \"Un momento...\"",
            visual_en=f"{name} standing, neutral expression, {loc}",
            tags_en=["1girl", "standing", "neutral_expression", "looking_at_viewer"],
            aspect_ratio="portrait",
            provider_used="fallback_minimal",
        )

