"""Luna RPG - Orchestrator Context Builder Mixin.

Context building and enrichment methods for LLM prompts.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

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

        ctx["cross_npc_hint"] = ""

        # Metodo 7: NPC presence context — stato accumulato off-screen
        # Informa l'LLM di quanto tempo l'NPC è rimasto solo, in che umore è,
        # cosa stava facendo. Rende la scena organica invece che scriptata.
        ctx["npc_presence_context"] = ""
        try:
            ws = getattr(self.engine, "world_simulator", None)
            if ws is not None:
                presence = self._build_npc_presence_context(
                    game_state.active_companion, game_state, ws
                )
                if presence:
                    ctx["npc_presence_context"] = presence
                    logger.debug(
                        "[ContextBuilder] npc_presence_context injected (%d chars)", len(presence)
                    )
        except Exception as e:
            logger.warning("[ContextBuilder] npc_presence_context failed: %s", e)

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

                # Propagate active NPC speaker flag so narrative/media can swap character
                active_npc_speaker = game_state.flags.get("_active_npc_speaker")
                if active_npc_speaker:
                    ctx["active_npc_speaker"] = active_npc_speaker

                # Consume pending mission memory entries written by on_complete_memory
                await self._flush_pending_npc_memories(game_state)

            except Exception as e:
                logger.warning("[Orchestrator] QuestEngine failed: %s", e)

        # MultiNPC - skip in context builder, will be handled by orchestrator
        # Don't call process_turn here to avoid double-processing and cooldown issues
        # The orchestrator will handle MultiNPC in Step 5.5
        pass

        return ctx

    async def _flush_pending_npc_memories(self, game_state: GameState) -> None:
        """Consume _pending_npc_memory_* flags written by quest on_complete_memory.

        For each pending flag found, stores the entry as a high-importance fact
        in MemoryManager so it survives history compression and appears in future
        LLM context. The flag is cleared after processing.
        """
        if not self.engine.memory_manager:
            return

        prefix = "_pending_npc_memory_"
        keys_to_flush = [k for k in game_state.flags if k.startswith(prefix)]
        if not keys_to_flush:
            return

        for key in keys_to_flush:
            data = game_state.flags.pop(key)
            if not isinstance(data, dict):
                continue

            character = key[len(prefix):]
            entry = data.get("entry", "")
            emotional_impact = data.get("emotional_impact", "neutral")
            if not entry:
                continue

            content = f"[{character}] {entry}"
            if emotional_impact and emotional_impact != "neutral":
                content += f" (emotional impact: {emotional_impact})"

            try:
                await self.engine.memory_manager.add_fact(
                    content=content,
                    turn_number=game_state.turn_count,
                    importance=8,
                    associated_npc=character,
                    context_tags=["mission_memory", emotional_impact],
                )
                logger.info(
                    "[Memory] Mission memory stored for '%s': %s...",
                    character, entry[:60],
                )
            except Exception as e:
                logger.warning("[Memory] Failed to store mission memory for '%s': %s", character, e)

    def _build_npc_presence_context(
        self,
        npc_id: str,
        game_state: Any,
        world_simulator: Any,
    ) -> str:
        """Metodo 7: costruisce il contesto presenza NPC per l'LLM.

        Descrive quante tempo l'NPC è rimasto solo, in che stato emotivo è,
        cosa stava facendo off-screen. L'LLM usa questo per calibrare
        organicamente il comportamento dell'NPC senza trigger meccanici.
        """
        mind = world_simulator.mind_manager.get(npc_id)
        if not mind:
            return ""

        npc_state = game_state.npc_states.get(npc_id)
        parts: list[str] = []

        # Quanto tempo l'NPC è rimasto senza contatto con il giocatore
        turns_alone = mind.turns_since_player_contact
        if turns_alone >= 15:
            parts.append(
                f"[{npc_id.upper()} STATO ACCUMULATO] "
                f"Non vede il giocatore da {turns_alone} turni. "
                "Si sente sola. Lo si nota dalla postura, dallo sguardo."
            )
        elif turns_alone >= 7:
            parts.append(
                f"[{npc_id.upper()} STATO ACCUMULATO] "
                f"Non vede il giocatore da {turns_alone} turni. "
                "Ha avuto tempo per pensare."
            )
        elif turns_alone >= 3:
            parts.append(
                f"[{npc_id.upper()} STATO ACCUMULATO] "
                "Il giocatore non c'era da un po'."
            )

        # Stato emotivo accumulato (diverso dal default)
        if npc_state:
            emotional_state = npc_state.emotional_state
            state_desc = {
                "lonely":     "Si sente sola. Non lo dirà direttamente, ma traspare.",
                "tired":      "È stanca. Movimenti lenti, voce bassa.",
                "vulnerable": "È in un momento di vulnerabilità emotiva.",
                "anxious":    "È in ansia per qualcosa. Agitata.",
                "happy":      "È di buonumore. Si vede dalla leggerezza.",
                "conflicted": "Ha qualcosa che la tormenta interiormente.",
            }
            desc = state_desc.get(emotional_state)
            if desc:
                parts.append(desc)

        # Needs dominanti (senza mostrare numeri al LLM)
        social_need   = mind.needs.get("social", 0.0)
        intimacy_need = mind.needs.get("intimacy", 0.0)
        if social_need > 0.70:
            parts.append("Ha bisogno di compagnia. Non lo chiederà esplicitamente.")
        elif intimacy_need > 0.70:
            parts.append("Ha bisogno di connessione emotiva più profonda.")

        # Off-screen log recente: cosa stava facendo
        recent = [
            e for e in (mind.off_screen_log or [])
            if not e.told_to_player and e.importance >= 0.2
        ]
        if recent:
            latest = recent[-1]
            parts.append(f"Poco prima che arrivassi: {latest.description}.")

        # Gossip / knowledge accumulata su altri NPC
        knowledge_key = f"_knowledge_{npc_id}"
        known_events = game_state.flags.get(knowledge_key, [])
        current_turn = game_state.turn_count
        fresh = [
            k for k in known_events
            if current_turn - k.get("turn", 0) <= 8
            and not k.get("acknowledged")
        ]
        if fresh:
            latest_k = fresh[-1]
            subj = latest_k.get("subject", "qualcuno")
            certainty = latest_k.get("certainty", 0.5)
            covered = latest_k.get("covered", False)
            if covered:
                parts.append(
                    f"Sa qualcosa su {subj} e il giocatore. Ha deciso di non dire niente. "
                    "Ma lo ricorda."
                )
            elif certainty >= 0.6:
                parts.append(
                    f"Ha visto qualcosa che riguarda {subj} e il giocatore. "
                    "Potrebbe portarlo fuori durante la conversazione."
                )
            else:
                parts.append(
                    f"Ha sentito voci su {subj} e il giocatore. Non è sicura."
                )

        return " ".join(parts) if parts else ""

    # =========================================================================
    # Farewell generation
    # =========================================================================

