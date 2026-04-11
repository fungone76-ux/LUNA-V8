"""Luna RPG - Orchestrator Context Builder Mixin.

Context building and enrichment methods for LLM prompts.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List

from luna.core.models import GameState

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ContextBuilderMixin:
    """Mixin providing context building methods for TurnOrchestrator.
    
    Contains _build_context and _enrich_context for preparing LLM prompts.
    """

    async def _build_context(
        self,
        text: str,
        game_state: GameState,
        switched: bool,
        old_companion: Optional[str],
        is_temporary: bool,
    ) -> Dict[str, Any]:
        """Build the context dict passed to NarrativeEngine."""
        # Schedule agent atmosphere (read-only, no transition logic here)
        schedule_ctx  = ""
        affinity_mult = 1.0
        if self._schedule_agent:
            try:
                atm = self._schedule_agent.get_atmosphere(game_state.time_of_day)
                schedule_ctx = "\n".join([
                    f"=== TIME OF DAY: {game_state.time_of_day.value.upper() if hasattr(game_state.time_of_day, 'value') else str(game_state.time_of_day).upper()} ===",
                    f"Mood: {atm.get('mood', '')}",
                    f"Light: {atm.get('light', '')}",
                    f"Social vibe: {atm.get('social_vibe', '')}",
                    f"Opportunity: {atm.get('opportunity', '')}",
                ]) if atm else ""
                affinity_mult = self._schedule_agent.get_affinity_multiplier(game_state.time_of_day)
            except Exception as e:
                logger.warning("[Orchestrator] ScheduleAgent atmosphere failed: %s", e)

        _activity = self._npc_location_hint or ""

        ctx: Dict[str, Any] = {
            "user_input":          text,
            "switched_from":       old_companion if switched else None,
            "is_temporary":        is_temporary,
            "in_remote_comm":      self._in_remote_comm,
            "remote_target":       self._remote_target,
            "memory_context":      "",
            "conversation_history": "",
            "quest_context":       "",
            "story_context":       "",
            "activity_context":    _activity,
            "initiative_context":  "",
            "multi_npc_context":   "",
            "personality_context": "",
            "event_context":       "",
            "forced_poses":        "",
            "schedule_context":    schedule_ctx,
            "affinity_multiplier": affinity_mult,
        }

        # Memory
        if self.engine.memory_manager:
            try:
                mm = self.engine.memory_manager
                if not mm._loaded:
                    await mm.load(active_companion=game_state.active_companion)
                ctx["memory_context"] = mm.get_memory_context(
                    companion_filter=game_state.active_companion
                )
                messages = mm.get_recent_history(
                    limit=10, companion_filter=game_state.active_companion
                )
                lines = []
                for msg in messages:
                    role = "Player" if msg.role == "user" else game_state.active_companion
                    lines.append(f"{role}: {msg.content}")
                ctx["conversation_history"] = "\n".join(lines)
            except Exception as e:
                logger.warning("[Orchestrator] Memory context failed: %s", e)

        # Personality
        if self.engine.personality_engine:
            try:
                self.engine.personality_engine.analyze_player_action(
                    game_state.active_companion, text, game_state.turn_count,
                    is_temporary=is_temporary,
                )
                # LLM deep analysis every 3 turns
                if (self.engine.personality_engine._use_llm and
                    game_state.turn_count % self.engine.personality_engine._llm_interval == 0):
                    try:
                        await self.engine.personality_engine.analyze_with_llm(
                            companion_name=game_state.active_companion,
                            user_input=text,
                            turn_count=game_state.turn_count,
                            llm_manager=self.engine.llm_manager,
                        )
                    except Exception as e:
                        logger.debug("[Orchestrator] LLM personality analysis failed: %s", e)
                # v8: CharacterVoiceBuilder sostituisce il personality_context generico
                if self.engine.character_voice_builder:
                    companion_def = self.engine.world.companions.get(
                        game_state.active_companion
                    )
                    present_npcs = list(
                        game_state.flags.get("present_npcs", [])
                    )
                    if companion_def:
                        ctx["personality_context"] = (
                            self.engine.character_voice_builder.build(
                                companion=companion_def,
                                personality_engine=self.engine.personality_engine,
                                game_state=game_state,
                                present_npcs=present_npcs,
                                presence_tracker=self.engine.presence_tracker,
                            ) or ""
                        )
                else:
                    ctx["personality_context"] = self.engine.personality_engine\
                        .get_psychological_context(
                            game_state.active_companion,
                            include_behavioral=True,
                            include_impressions=True,
                        ) or ""
            except Exception as e:
                logger.warning("[Orchestrator] Personality context failed: %s", e)

        # Outfit modifier
        if self.engine.outfit_modifier and self.engine.outfit_engine:
            try:
                modified, is_major, desc = self.engine.outfit_modifier.process_turn(
                    text, game_state,
                    self.engine.world.companions.get(game_state.active_companion),
                )
                if is_major and desc:
                    await self.engine.outfit_modifier.apply_major_change(
                        game_state, desc, self.engine.llm_manager
                    )
            except Exception as e:
                logger.warning("[Orchestrator] Outfit modifier failed: %s", e)

        # Pose extraction
        if self.engine.pose_extractor:
            try:
                if self.engine.pose_extractor.has_explicit_pose(text):
                    ctx["forced_poses"] = self.engine.pose_extractor\
                        .get_forced_visual_description(text) or ""
            except Exception as e:
                logger.warning("[Orchestrator] Pose extractor failed: %s", e)

        # Activity context — read from ScheduleManager (v8: replaced ActivitySystem)
        if self.engine.schedule_manager and not ctx.get("activity_context"):
            try:
                activity = self.engine.schedule_manager.get_npc_activity(
                    game_state.active_companion
                )
                if activity:
                    ctx["activity_context"] = activity
            except Exception as e:
                logger.warning("[Orchestrator] Schedule activity failed: %s", e)

        # Legacy initiative_system intentionally removed — InitiativeAgent
        # (step 0.7 in execute()) propagates initiative_context directly into
        # the context dict after _build_context() returns. Using both would
        # cause the legacy system to silently overwrite the agent's output.

        # Fix 3: cross-location hint from non-active NPC
        ctx["cross_npc_hint"] = ""
        try:
            ws = getattr(self.engine, "world_simulator", None)
            if ws is not None:
                from luna.systems.world_sim.cross_location_hints import get_cross_location_hint
                from luna.systems.world_sim.turn_director import _INITIATIVE_COOLDOWN
                hint = get_cross_location_hint(
                    ws.mind_manager,
                    game_state.active_companion,
                    cooldown=_INITIATIVE_COOLDOWN,
                )
                if hint:
                    ctx["cross_npc_hint"] = hint
                    logger.debug("[ContextBuilder] cross_npc_hint injected (%d chars)", len(hint))
        except Exception as e:
            logger.warning("[ContextBuilder] cross_location_hint failed: %s", e)

        return ctx

    async def _enrich_context(
        self, ctx: Dict[str, Any], game_state: GameState, text: str
    ) -> Dict[str, Any]:
        """Add StoryDirector, QuestEngine, MultiNPC, Events context."""

        # Global events
        if self.engine.event_manager:
            try:
                self.engine.event_manager.check_and_activate_events(game_state)
                # Build event context via event_context_builder if available
                if hasattr(self.engine, "event_context_builder"):
                    active = self.engine.event_manager.get_all_active_events()
                    if active:
                        if self._quest_director:
                            filtered = [
                                self._quest_director.filter_event_for_context(e, game_state)
                                for e in active
                            ]
                            event_texts = [t for t in filtered if t]
                            ctx["event_context"] = "\n".join(event_texts) if event_texts else ""
                        else:
                            ctx["event_context"] = self.engine.event_context_builder\
                                .build_combined_context(active, game_state) or ""
            except Exception as e:
                logger.warning("[Orchestrator] Event manager failed: %s", e)

        # StoryDirector
        if self.engine.story_director:
            try:
                beat = self.engine.story_director.get_active_instruction(game_state)
                if beat:
                    ctx["story_context"] = beat[1] if isinstance(beat, tuple) else str(beat)
            except Exception as e:
                logger.warning("[Orchestrator] StoryDirector failed: %s", e)

        # QuestEngine
        if self.engine.quest_engine:
            try:
                quest_ctx, new_activations, stage_updates, situation_override = self.engine.quest_engine.update(game_state, text)
                # If the active quest stage defines companion_situation, override the
                # schedule-based activity so the NPC is self-aware of their current role.
                if situation_override:
                    ctx["activity_context"] = situation_override
                # Collect action hints from stage transitions
                all_hints = []
                for upd in stage_updates:
                    if upd.stage_changed:
                        logger.info("[QuestEngine] Stage change: %s → %s", upd.old_stage, upd.new_stage)
                    if getattr(upd, "action_hints", None):
                        all_hints.extend(upd.action_hints)
                # Enrich with QuestDirector (impression variants + consequences)
                if self._quest_director:
                    try:
                        if self.engine.personality_engine:
                            state = self.engine.personality_engine._states.get(
                                game_state.active_companion
                            )
                            if state and getattr(state, "behavioral_memories", None):
                                traits = [str(getattr(b, "type", "")) for b in state.behavioral_memories[-3:]]
                                self._quest_director.update_behavior_pattern(
                                    game_state.active_companion, text, traits
                                )
                        quest_ctx = self._quest_director.get_enriched_context(
                            game_state, text, quest_ctx or ""
                        )
                    except Exception as e:
                        logger.warning("[Orchestrator] QuestDirector failed: %s", e)
                if all_hints:
                    quest_ctx = (quest_ctx + "\n" + "\n".join(all_hints)).strip() if quest_ctx else "\n".join(all_hints)
                ctx["quest_context"] = quest_ctx or ""
            except Exception as e:
                logger.warning("[Orchestrator] QuestEngine failed: %s", e)

        # MultiNPC - skip in context builder, will be handled by orchestrator
        # Don't call process_turn here to avoid double-processing and cooldown issues
        # The orchestrator will handle MultiNPC in Step 5.5
        pass

        return ctx

    # =========================================================================
    # Farewell generation
    # =========================================================================

