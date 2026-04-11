"""Luna RPG - Phase Handlers Mixin.

Le 5 fasi del turno + helper privati estratti da execute().

Pipeline:
  execute()
    → _phase_pre_turn      Steps 0, 0.5, 0.7, 1, 2
    → _phase_world_state   Steps 2.5, 2.7, 2.9, 2.8, 3
    → _phase_context       Steps 4, 5
    → _phase_narrative     Steps 5.5, 6, 6c, 7, 7.5
    → _phase_finalize      Steps 8, 9, 10
    → _build_result        Step 11

I tre blocchi "mostro" estratti come helper:
  _run_gm_agenda     144 righe originali (Step 2.9)
  _run_multi_npc     200 righe originali (Step 5.5)
  _run_phase_clock    74 righe originali (Step 8 phase logic)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from luna.core.models import IntentType, NarrativeOutput, TurnResult

from .turn_context import MultiNPCResult, TurnContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_SOLO_COMPANION = "_solo_"


class PhaseHandlersMixin:
    """Mixin con le 5 fasi del turno + _build_result.

    Accede a self.engine, self._narrative, self._guardian, ecc.
    impostati da TurnOrchestrator.__init__().
    """

    # =========================================================================
    # Fase 1: Pre-turn  (Steps 0, 0.5, 0.7, 1, 2)
    # =========================================================================

    async def _phase_pre_turn(self, ctx: TurnContext) -> TurnContext:
        game_state = ctx.game_state
        text = ctx.text

        # ── Step 0: Intent classification ────────────────────────────────────
        has_event = bool(
            self.engine.event_manager
            and self.engine.event_manager.has_pending_event()
        )
        ctx.intent = self._intent_router.analyze(text, game_state, has_event)
        logger.debug("[Orchestrator] Intent: %s", ctx.intent.primary)

        # ── Step 0.3: NPC Location Router ─────────────────────────────────────
        # Check if player wants to visit a specific NPC (e.g., "vado da Maria")
        if self.engine.npc_location_router:
            try:
                route_result = self.engine.npc_location_router.resolve(text, game_state)
                if route_result:
                    logger.info(
                        "[Orchestrator] NPC Location Router: %s -> %s",
                        route_result.npc_display_name,
                        route_result.location_id,
                    )
                    ctx.npc_route_target = route_result
                    # Override intent to MOVEMENT for special handling
                    from luna.core.models import IntentType
                    if ctx.intent.primary != IntentType.MOVEMENT:
                        ctx.intent.primary = IntentType.MOVEMENT
                        ctx.intent.target_location = route_result.location_id
            except Exception as e:
                logger.warning("[Orchestrator] NPC Location Router failed: %s", e)

        # ── Step 0.5: Situational interventions ──────────────────────────────
        skip_situational = False
        if self.engine.multi_npc_manager and self.engine.multi_npc_manager.enabled:
            present_npcs = self.engine.multi_npc_manager.get_present_npcs(
                game_state.active_companion, game_state
            )
            text_lower = text.lower()
            for npc in present_npcs:
                if npc.lower() in text_lower:
                    skip_situational = True
                    logger.info(
                        "[Orchestrator] Skipping situational intervention - %s mentioned for MultiNPC",
                        npc,
                    )
                    break

        if not skip_situational and self.engine.situational_intervention:
            try:
                sit_result = await self.engine.situational_intervention.check_and_intervene(
                    text, game_state
                )
                if sit_result is not None:
                    logger.info("[Orchestrator] Situational intervention triggered")
                    ctx.early_return = sit_result
                    return ctx
            except Exception as e:
                logger.warning("[Orchestrator] Situational intervention failed: %s", e)

        # ── Step 0.6: NPC Goal Evaluator ──────────────────────────────────────
        # Evaluate NPC goals and generate action hints for the UI widget
        if self.engine.npc_goal_evaluator:
            try:
                # Check for completed goals first
                completed = self.engine.npc_goal_evaluator.check_completions(game_state)
                for npc_id in completed:
                    logger.info("[Orchestrator] NPC goal completed: %s", npc_id)

                # Evaluate new goals (max 1 hint per turn)
                goal_hint = self.engine.npc_goal_evaluator.evaluate(game_state)
                if goal_hint:
                    logger.info(
                        "[Orchestrator] NPC Goal: %s (%s, urgency=%.1f)",
                        goal_hint.npc_display_name,
                        goal_hint.initiative_style,
                        goal_hint.urgency,
                    )
                    ctx.npc_goal_hint = goal_hint

                    # Add to active actions set
                    if goal_hint.npc_id not in game_state.active_npc_actions:
                        game_state.active_npc_actions.add(goal_hint.npc_id)

                    # Queue for autonomous initiative turn (timer fires in ~15s)
                    # Max queue depth = 1 to avoid overwhelming the player
                    # secret_keeper NPCs are pull-only: they activate when the player visits them
                    pending = getattr(self.engine, '_pending_initiatives', None)
                    if pending is not None and len(pending) == 0:
                        if goal_hint.initiative_style != 'secret_keeper':
                            pending.append(goal_hint)
                            logger.info("[Orchestrator] Initiative queued for %s", goal_hint.npc_id)
                        else:
                            logger.info("[Orchestrator] secret_keeper %s: pull-only, not queued", goal_hint.npc_id)
            except Exception as e:
                logger.warning("[Orchestrator] NPC Goal Evaluator failed: %s", e)

        # ── Step 0.7: InitiativeAgent ─────────────────────────────────────────
        if self._initiative_agent:
            try:
                ctx.initiative_context = (
                    self._initiative_agent.check_and_get_context(game_state, text) or ""
                )
                latest_event = self._initiative_agent.consume_latest_event()
                if latest_event:
                    ctx.initiative_event_payload = latest_event.to_dict()
                if ctx.initiative_context:
                    logger.info("[Orchestrator] Initiative active")
            except Exception as e:
                logger.warning("[Orchestrator] InitiativeAgent failed: %s", e)

        # ── Step 1: Handle special intents ────────────────────────────────────
        special = await self._handle_special_intents(ctx.intent, game_state, text)
        if special is not None:
            ctx.early_return = special
            return ctx

        # ── Step 2: Companion switch ──────────────────────────────────────────
        ctx.switched, ctx.old_companion, ctx.is_temporary = (
            await self._handle_companion_switch(ctx.intent, game_state, text)
        )

        return ctx

    # =========================================================================
    # Fase 2: World state  (Steps 2.5, 2.7, 2.9, 2.8, 3)
    # =========================================================================

    async def _phase_world_state(self, ctx: TurnContext) -> TurnContext:
        game_state = ctx.game_state

        # ── Step 2.5: WorldSimulator tick ─────────────────────────────────────
        if self.engine.world_simulator:
            try:
                ctx.directive = self.engine.world_simulator.tick(
                    player_input=ctx.text,
                    intent=ctx.intent,
                    game_state=game_state,
                )
                logger.debug(
                    "[Orchestrator] WorldSim: driver=%s, npcs=%d, ambient=%d",
                    ctx.directive.driver.value,
                    len(ctx.directive.npcs_in_scene),
                    len(ctx.directive.ambient),
                )
            except Exception as e:
                logger.warning("[Orchestrator] WorldSimulator failed: %s", e)

        if ctx.directive:
            if ctx.initiative_event_payload and not ctx.directive.initiative_event:
                ctx.directive.initiative_event = ctx.initiative_event_payload
            ctx.directive_summary = ctx.directive.to_summary()

        # ── Step 2.7: TensionTracker tick ─────────────────────────────────────
        if self.engine.tension_tracker:
            try:
                triggered_events = self.engine.tension_tracker.tick(
                    game_state, game_state.turn_count
                )
                if triggered_events and self.engine.event_manager:
                    for event_id in triggered_events:
                        self.engine.event_manager.force_activate_event(event_id)
                        logger.info(
                            "[Orchestrator] TensionTracker triggered event: %s", event_id
                        )
            except Exception as e:
                logger.warning("[Orchestrator] TensionTracker failed: %s", e)

        # ── Step 2.9: GM Agenda ───────────────────────────────────────────────
        ctx = await self._run_gm_agenda(ctx)

        # ── Step 2.8: Global Events check ─────────────────────────────────────
        # (numerato 2.8 per ragioni storiche, eseguito dopo 2.9)
        if self.engine.event_manager:
            try:
                new_events = self.engine.event_manager.check_and_activate_events(game_state)
                if new_events:
                    for evt in new_events:
                        logger.info("[Orchestrator] GlobalEvent activated: %s", evt.name)
            except Exception as e:
                logger.warning("[Orchestrator] GlobalEventManager failed: %s", e)

        # ── Step 3: DirectorAgent ─────────────────────────────────────────────
        if ctx.directive and ctx.directive.needs_director:
            try:
                ctx.scene_direction = await self._director.direct(
                    directive=ctx.directive,
                    game_state=game_state,
                    llm_manager=self.engine.llm_manager,
                    context={},
                )
                if ctx.scene_direction:
                    logger.info(
                        "[Orchestrator] DirectorAgent produced %d beats",
                        len(ctx.scene_direction.beats),
                    )
            except Exception as e:
                logger.warning("[Orchestrator] DirectorAgent failed: %s", e)

        return ctx

    # =========================================================================
    # Fase 3: Context building  (Steps 4, 5)
    # =========================================================================

    async def _phase_context(self, ctx: TurnContext) -> TurnContext:
        game_state = ctx.game_state

        # ── Step 0.4: PresenceTracker ─────────────────────────────────────────
        present_npcs: list = []
        if self.engine.multi_npc_manager:
            try:
                present_npcs = self.engine.multi_npc_manager.get_present_npcs(
                    game_state.active_companion, game_state
                )
            except Exception as e:
                logger.warning("[Orchestrator] PresenceTracker get_present_npcs failed: %s", e)

        if self.engine.presence_tracker:
            try:
                self.engine.presence_tracker.update(
                    game_state=game_state,
                    present_npcs=present_npcs,
                    active_npc=game_state.active_companion,
                )
            except Exception as e:
                logger.warning("[Orchestrator] PresenceTracker.update failed: %s", e)

        # ── Step 0.5: EmotionalStateEngine ───────────────────────────────────
        if self.engine.emotional_state_engine:
            companion_def = self.engine.world.companions.get(game_state.active_companion)
            if companion_def:
                try:
                    self.engine.emotional_state_engine.apply(
                        companion=companion_def,
                        game_state=game_state,
                        present_npcs=present_npcs,
                    )
                except Exception as e:
                    logger.warning("[Orchestrator] EmotionalStateEngine.apply failed: %s", e)

        # ── Step 4: Build context ─────────────────────────────────────────────
        ctx.context = await self._build_context(
            ctx.text, game_state, ctx.switched, ctx.old_companion, ctx.is_temporary
        )

        # Inject InitiativeAgent context (Step 0.7 → Step 4)
        if ctx.initiative_context:
            ctx.context["initiative_context"] = ctx.initiative_context

        # Inject WorldSimulator context
        if ctx.directive:
            ctx.context["world_directive_context"] = ctx.directive.build_context()
            ctx.context["turn_driver"] = ctx.directive.driver.value
        if ctx.scene_direction:
            ctx.context["scene_direction_context"] = ctx.scene_direction.to_prompt()

        # Inject GM Agenda context
        if ctx.gm_agenda_context:
            ctx.context["gm_agenda_context"] = ctx.gm_agenda_context

        # Inject NPC secret hint — if an NPC has a pending secret and player is there
        if getattr(ctx, "npc_goal_hint", None):
            h = ctx.npc_goal_hint
            if h.initiative_style == "secret_keeper" and h.secret_subject:
                ctx.context["npc_secret_hint"] = (
                    f"NOTA NARRATORE: {h.npc_display_name} ha un segreto da rivelare. "
                    f"Tema: {h.secret_subject}. "
                    f"Se il giocatore chiede o l'occasione si presenta, "
                    f"inventa un segreto specifico, esplicito e molto compromettente "
                    f"coerente con il tema. Stile adult hard, nessuna censura."
                )
            elif h.initiative_style in ("friendly", "authority"):
                ctx.context["npc_secret_hint"] = (
                    f"NOTA NARRATORE: {h.npc_display_name} vuole {h.goal_text}."
                )

        # ── Inject active authority scene context ─────────────────────────────
        # After an authority NPC initiative turn OR a normal turn with the NPC,
        # the narrative engine must know the NPC was/is present.
        # Context persists until 2 turns after the NPC leaves active_npc_actions.
        active_auth = getattr(self.engine, '_active_authority_scene', None)
        if active_auth:
            npc_id       = active_auth["npc_id"]
            expires_at   = active_auth.get("expires_at_turn", 0)
            still_active = npc_id in game_state.active_npc_actions

            if still_active or game_state.turn_count <= expires_at:
                presence = (
                    "È FISICAMENTE PRESENTE nella stanza"
                    if still_active
                    else "ERA PRESENTE poco fa e ha appena lasciato la stanza"
                )
                ctx.context["active_authority_scene"] = (
                    f"CONTESTO SCENA RECENTE — {active_auth['npc_display_name']} {presence}. "
                    f"Ecco il dialogo avvenuto:\n"
                    f"{active_auth['dialogue']}\n"
                    f"Il companion DEVE rispondere tenendo conto di questo contesto. "
                    f"Non ignorare quanto appena accaduto."
                )
                logger.debug(
                    "[Orchestrator] Authority scene context injected: %s (active=%s, expires=%d)",
                    npc_id, still_active, expires_at,
                )
            else:
                # Scaduto — pulisci
                self.engine._active_authority_scene = None

        # Persist player input per quest engine action conditions
        game_state.flags["_last_player_input"] = ctx.text

        # ── Step 5: Enrich context ────────────────────────────────────────────
        ctx.context = await self._enrich_context(ctx.context, game_state, ctx.text)

        return ctx

    # =========================================================================
    # Fase 4: Narrative  (Steps 5.5, 6, 6c, 7, 7.5)
    # =========================================================================

    async def _phase_narrative(self, ctx: TurnContext) -> TurnContext:
        game_state = ctx.game_state

        # ── Step 5.5: MultiNPC expanded ───────────────────────────────────────
        ctx.multi_npc = await self._run_multi_npc(ctx)

        # ── Step 6: NarrativeEngine LLM call ─────────────────────────────────
        if not ctx.multi_npc.skip_standard_llm:
            ctx.narrative = await self._narrative.generate(
                user_input=ctx.text,
                game_state=game_state,
                llm_manager=self.engine.llm_manager,
                context=ctx.context,
            )
        else:
            ctx.narrative = ctx.multi_npc.narrative

        # Persist narrative text per quest engine action conditions
        if ctx.narrative and ctx.narrative.text:
            game_state.flags["_last_narrative_text"] = ctx.narrative.text

        # ── Step 7: StateGuardian — validate + apply ──────────────────────────
        if not self._guardian.validate_narrative(ctx.narrative):
            ctx.narrative = self._minimal_narrative(game_state)

        allow_invite = ctx.intent.primary == IntentType.INVITATION
        ctx.changes = self._guardian.apply(
            narrative=ctx.narrative,
            game_state=game_state,
            outfit_engine=self.engine.outfit_engine,
            allow_invite=allow_invite,
        )

        # ── Step 6c: Stall counter + commit GM move ───────────────────────────
        if ctx.changes.get("affinity_changes"):
            game_state.flags["_gm_stall_count"] = 0
        else:
            game_state.flags["_gm_stall_count"] = (
                game_state.flags.get("_gm_stall_count", 0) + 1
            )
        if ctx.gm_move_name:
            game_state.flags["_last_gm_move"] = ctx.gm_move_name

        # ── Step 7.5: WorldSimulator post-turn update ─────────────────────────
        if self.engine.world_simulator:
            try:
                self.engine.world_simulator.post_turn_update(
                    active_npc=game_state.active_companion,
                    player_input=ctx.text,
                    narrative_text=ctx.narrative.text,
                    game_state=game_state,
                    driver=ctx.directive.driver.value if ctx.directive else "player",
                )
            except Exception as e:
                logger.warning("[Orchestrator] WorldSim post_turn failed: %s", e)

        return ctx

    # =========================================================================
    # Fase 5: Finalize  (Steps 8, 9, 10)
    # =========================================================================

    async def _phase_finalize(self, ctx: TurnContext) -> TurnContext:
        game_state = ctx.game_state

        # ── Step 8: Advance turn + phase clock ───────────────────────────────
        game_state.turn_count += 1
        ctx = await self._run_phase_clock(ctx)

        # ── Step 9: Save state + memory ───────────────────────────────────────
        await self._save(game_state, ctx.text, ctx.narrative, ctx.changes)

        # ── Update active authority scene (normal turns with authority NPC) ───
        # When the active companion is an authority NPC, keep _active_authority_scene
        # current so the next turn (typically back to Luna) has full scene context.
        npc_def = self.engine.world.npc_templates.get(game_state.active_companion)
        if npc_def:
            style = (
                npc_def.get("initiative_style", "") if isinstance(npc_def, dict)
                else getattr(npc_def, "initiative_style", "")
            )
            if style == "authority" and ctx.narrative and ctx.narrative.text:
                prev = getattr(self.engine, "_active_authority_scene", None) or {}
                prev_dialogue = prev.get("dialogue", "")
                npc_name = (
                    npc_def.get("name", game_state.active_companion)
                    if isinstance(npc_def, dict)
                    else getattr(npc_def, "name", game_state.active_companion)
                )
                new_exchange = (
                    (f"Giocatore: {ctx.text}\n" if ctx.text else "")
                    + f"{npc_name}: {ctx.narrative.text}"
                )
                self.engine._active_authority_scene = {
                    "npc_id":           game_state.active_companion,
                    "npc_display_name": npc_name,
                    "dialogue":         (prev_dialogue + "\n" + new_exchange).strip(),
                    "expires_at_turn":  game_state.turn_count + 2,
                }
                logger.debug("[Orchestrator] Authority scene context updated: %s", game_state.active_companion)

        # ── Step 10: VisualDirector ───────────────────────────────────────────
        ctx.narrative._user_input = ctx.text   # tag extraction per VisualDirector
        lora_enabled = (
            self.engine.lora_mapping.is_enabled()
            if self.engine.lora_mapping is not None
            else False
        )
        ctx.visual_output = self._visual.build(
            narrative=ctx.narrative,
            game_state=game_state,
            lora_enabled=lora_enabled,
        )

        # ── Step 11: Media generation ─────────────────────────────────────────
        ctx.media = await self._generate_media(game_state, ctx.narrative, ctx.visual_output)

        return ctx

    # =========================================================================
    # Build TurnResult  (Step 12)
    # =========================================================================

    def _build_result(self, ctx: TurnContext) -> TurnResult:
        """Costruisce TurnResult da TurnContext e chiude il turn_logger."""
        # ── Early return path ─────────────────────────────────────────────────
        if ctx.early_return is not None:
            result = ctx.early_return
            if ctx.initiative_event_payload and not result.initiative_event:
                result.initiative_event = ctx.initiative_event_payload
            if ctx.directive_summary and not result.turn_directive_summary:
                result.turn_directive_summary = ctx.directive_summary
            self._close_turn_logger(ctx)
            return result

        # ── Normal path ───────────────────────────────────────────────────────
        multi_npc_data = None
        if ctx.multi_npc and ctx.multi_npc.completed_turns:
            multi_npc_data = [
                {
                    "speaker": t.speaker,
                    "text": t.text,
                    "visual_en": t.visual_en,
                    "tags_en": t.tags_en,
                    "speaker_type": (
                        t.speaker_type.value
                        if hasattr(t.speaker_type, "value")
                        else str(t.speaker_type)
                    ),
                }
                for t in ctx.multi_npc.completed_turns
            ]

        multi_npc_image_paths = ctx.multi_npc.image_paths if ctx.multi_npc else None
        was_interrupted = ctx.multi_npc.was_interrupted if ctx.multi_npc else False

        # Handle manual phase advance with no farewell (ctx.narrative is None)
        narrative_text = ctx.narrative.text if ctx.narrative else ""
        provider_used = ctx.narrative.provider_used if ctx.narrative else "system"
        
        result = TurnResult(
            text=narrative_text,
            user_input=ctx.text,
            image_path=ctx.media.get("image_path") if ctx.media else None,
            audio_path=ctx.media.get("audio_path") if ctx.media else None,
            video_path=ctx.media.get("video_path") if ctx.media else None,
            affinity_changes=ctx.changes.get("affinity_changes", {}),
            new_quests=ctx.changes.get("quests_started", []),
            completed_quests=ctx.changes.get("quests_completed", []),
            switched_companion=ctx.switched,
            previous_companion=ctx.old_companion if ctx.switched else None,
            current_companion=ctx.game_state.active_companion,
            is_temporary_companion=ctx.is_temporary,
            phase_changed=ctx.phase_changed,
            sd_prompt=ctx.visual_output.positive if ctx.visual_output else None,
            initiative_event=ctx.initiative_event_payload,
            turn_directive_summary=ctx.directive_summary,
            turn_number=ctx.game_state.turn_count,
            provider_used=provider_used,
            narrative_compass=ctx.narrative_compass,
            resolved_promise=ctx.changes.get("resolved_promise"),
            multi_npc_sequence=multi_npc_data,
            multi_npc_image_paths=multi_npc_image_paths,
            was_interrupted=was_interrupted,
            npc_action=self.engine.npc_goal_evaluator.create_npc_action(ctx.npc_goal_hint)
                if getattr(ctx, "npc_goal_hint", None) and self.engine.npc_goal_evaluator
                else None,
        )

        # ── TurnLogger ────────────────────────────────────────────────────────
        if ctx.turn_logger:
            try:
                if ctx.initiative_event_payload:
                    ctx.turn_logger.log_initiative_event(ctx.initiative_event_payload)
                if ctx.directive_summary:
                    ctx.turn_logger.log_turn_directive(ctx.directive_summary)
            except Exception as log_err:
                logger.warning("[TurnLogger] log failed: %s", log_err)
        self._close_turn_logger(ctx)

        return result

    def _close_turn_logger(self, ctx: TurnContext) -> None:
        if ctx.turn_logger:
            try:
                ctx.turn_logger.end_turn()
            except Exception as end_err:
                logger.warning("[TurnLogger] end failed: %s", end_err)
            finally:
                ctx.turn_logger = None

    # =========================================================================
    # Helper privati: i 3 blocchi "mostro" estratti
    # =========================================================================

    async def _run_gm_agenda(self, ctx: TurnContext) -> TurnContext:
        """Step 2.9 — GM Agenda (144 righe originali).

        Popola ctx.gm_agenda_context, ctx.gm_move_name, ctx.narrative_compass.
        """
        game_state = ctx.game_state
        active = game_state.active_companion
        if not (self.engine.tension_tracker and active and active != _SOLO_COMPANION):
            return ctx

        try:
            from luna.systems.gm_agenda import (  # lazy: dipendenza opzionale
                GroupContext,
                NPCMindSnapshot,
                build_gm_agenda_context,
                load_promises,
                resolve_arc_phase_and_thread,
            )
            from luna.core.models import NarrativeCompassData

            affinity   = game_state.affinity.get(active, 0)
            last_move  = game_state.flags.get("_last_gm_move")
            stall_count = game_state.flags.get("_gm_stall_count", 0)

            # ── NPCMind snapshot ─────────────────────────────────────────────
            mind_snapshot: Optional[NPCMindSnapshot] = None
            if self.engine.world_simulator:
                try:
                    raw_mind = self.engine.world_simulator.mind_manager.get(active)
                    if raw_mind:
                        dom_need, need_val = raw_mind.dominant_need
                        burning  = [u for u in raw_mind.unspoken if u.is_burning]
                        dom_emo  = raw_mind.dominant_emotion
                        mind_snapshot = NPCMindSnapshot(
                            dominant_need=dom_need,
                            need_value=need_val,
                            has_burning_unspoken=bool(burning),
                            burning_unspoken_weight=burning[0].emotional_weight if burning else 0.0,
                            burning_unspoken_hint=burning[0].content if burning else "",
                            has_untold_events=bool(raw_mind.untold_events),
                            dominant_emotion=dom_emo.emotion.value if dom_emo else "",
                            emotion_intensity=dom_emo.intensity if dom_emo else 0.0,
                        )
                except Exception as mind_err:
                    logger.debug("[Orchestrator] NPCMind snapshot failed: %s", mind_err)

            # ── Promises + compass ───────────────────────────────────────────
            active_promises  = load_promises(game_state.flags, game_state.turn_count)
            gm_agenda_config = dict(getattr(self.engine.world, "gm_agenda", {}) or {})
            default_climate  = gm_agenda_config.get("default_climate", "")
            compass = self.engine.tension_tracker.get_compass_data(
                default_climate=default_climate
            )

            # ── GroupContext (secondary companions) ──────────────────────────
            group_ctx: Optional[GroupContext] = None
            if self.engine.world_simulator:
                secondary_minds: dict = {}
                for cname, caff in game_state.affinity.items():
                    if cname == active or caff <= 0:
                        continue
                    try:
                        raw_sec = self.engine.world_simulator.mind_manager.get(cname)
                        if raw_sec:
                            sec_need, sec_val = raw_sec.dominant_need
                            sec_emo = raw_sec.dominant_emotion
                            secondary_minds[cname] = NPCMindSnapshot(
                                dominant_need=sec_need,
                                need_value=sec_val,
                                has_burning_unspoken=False,
                                burning_unspoken_weight=0.0,
                                burning_unspoken_hint="",
                                has_untold_events=False,
                                dominant_emotion=sec_emo.emotion.value if sec_emo else "",
                                emotion_intensity=sec_emo.intensity if sec_emo else 0.0,
                            )
                    except Exception:
                        pass
                if secondary_minds:
                    rel_tensions = {
                        k[len("_rel_tension_"):]: v
                        for k, v in game_state.flags.items()
                        if k.startswith("_rel_tension_")
                    }
                    group_ctx = GroupContext(
                        secondary_minds=secondary_minds,
                        relationship_tensions=rel_tensions,
                    )

            # ── Build agenda ─────────────────────────────────────────────────
            ctx.gm_agenda_context, ctx.gm_move_name = build_gm_agenda_context(
                companion_name=active,
                affinity=affinity,
                tension_phase=compass["tension_phase"],
                tension_axis=compass.get("active_axis") or "",
                tension_level=compass.get("tension_level", 0.0),
                turn=game_state.turn_count,
                flags=game_state.flags,
                last_move=last_move,
                mind=mind_snapshot,
                stall_count=stall_count,
                promises=active_promises,
                gm_agenda_config=gm_agenda_config,
                group_ctx=group_ctx,
            )

            # ── Arc phases per tutti i companion ─────────────────────────────
            arc_phases: dict = {}
            arc_threads: dict = {}
            for cname, caff in game_state.affinity.items():
                phase, thread = resolve_arc_phase_and_thread(
                    cname, caff, game_state.flags, gm_agenda_config
                )
                arc_phases[cname]  = phase
                arc_threads[cname] = thread

            # ── Compass data ─────────────────────────────────────────────────
            climate_text = compass.get("climate_text", "")
            if not climate_text and mind_snapshot and mind_snapshot.burning_unspoken_hint:
                climate_text = mind_snapshot.burning_unspoken_hint

            current_level = compass.get("tension_level", 0.0)
            prev_level    = float(game_state.flags.get("_last_tension_level", current_level))
            delta = current_level - prev_level
            trend = "^" if delta > 0.02 else ("v" if delta < -0.02 else "=")
            game_state.flags["_last_tension_level"] = current_level

            # Quest Journal snapshot
            quest_title, stage_title, stage_hint, next_title, is_hidden = "", "", "", "", False
            try:
                from luna.systems.quest_engine_sequential import SequentialQuestEngine
                if isinstance(self.engine.quest_engine, SequentialQuestEngine):
                    snap = self.engine.quest_engine.get_journal_snapshot(game_state)
                    quest_title = snap.active_quest_title
                    stage_title = snap.active_stage_title
                    stage_hint  = snap.active_stage_hint
                    next_title  = snap.next_quest_title
                    is_hidden   = snap.is_hidden
            except Exception as qe:
                logger.debug("[Orchestrator] QuestJournal snapshot failed: %s", qe)

            ctx.narrative_compass = NarrativeCompassData(
                arc_phases=arc_phases,
                arc_threads=arc_threads,
                active_tension_axis=compass.get("active_axis") or "",
                tension_phase=compass["tension_phase"],
                tension_level=current_level,
                climate_text=climate_text,
                trend=trend,
                climate_ttl=compass.get("climate_ttl", 3),
                active_quest_title=quest_title,
                active_stage_title=stage_title,
                active_stage_hint=stage_hint,
                next_quest_title=next_title,
                is_hidden=is_hidden,
            )

        except Exception as e:
            logger.warning("[Orchestrator] GM Agenda failed: %s", e)

        return ctx

    async def _run_multi_npc(self, ctx: TurnContext) -> MultiNPCResult:
        """Step 5.5 — MultiNPC expanded (200 righe originali).

        Restituisce MultiNPCResult con completed_turns, image_paths,
        was_interrupted, skip_standard_llm, narrative.
        """
        result = MultiNPCResult()
        game_state = ctx.game_state
        text = ctx.text

        if not (
            self.engine.multi_npc_manager
            and not getattr(self.engine.state_manager.current, "is_temporary", False)
            and game_state.active_companion != _SOLO_COMPANION
        ):
            return result

        logger.info(
            "[DEBUG ORCH] Calling process_turn with text='%s...', active=%s",
            text[:50],
            game_state.active_companion,
        )
        multi_npc_sequence = self.engine.multi_npc_manager.process_turn(
            player_input=text,
            active_npc=game_state.active_companion,
            game_state=game_state,
        )
        logger.info("[DEBUG ORCH] process_turn returned: %s", multi_npc_sequence)

        if multi_npc_sequence:
            logger.info("[DEBUG ORCH] Sequence has %d turns", len(multi_npc_sequence.turns))
            for i, t in enumerate(multi_npc_sequence.turns):
                logger.info("[DEBUG ORCH]   Turn %d: %s (%s)", i, t.speaker, t.speaker_type)
        else:
            logger.info("[DEBUG ORCH] process_turn returned None!")

        if not (multi_npc_sequence and len(multi_npc_sequence.turns) > 1):
            return result

        logger.info(
            "[Orchestrator] MultiNPC expanded: %d turns", len(multi_npc_sequence.turns)
        )

        if hasattr(self.engine, "_show_interrupt_callback"):
            try:
                self.engine._show_interrupt_callback(True)
            except Exception as e:
                logger.debug("[Orchestrator] Could not show interrupt button: %s", e)

        game_state.flags["_multi_npc_in_progress"] = True

        _present_npcs = self.engine.multi_npc_manager.get_present_npcs(
            game_state.active_companion, game_state
        )
        all_present_npcs = _present_npcs + [game_state.active_companion]
        outfit_data = {
            npc: game_state.get_outfit(npc)
            for npc in all_present_npcs
            if npc and npc != _SOLO_COMPANION
        }

        _mc_builder = None

        for i, turn in enumerate(multi_npc_sequence.turns):
            logger.debug(
                "[Orchestrator] MultiNPC turn %d/%d: %s",
                i + 1,
                len(multi_npc_sequence.turns),
                turn.speaker,
            )
            try:
                # 1. Genera testo
                completed_turn = await self.engine.multi_npc_manager.generate_single_turn(
                    turn=turn,
                    previous_turns=result.completed_turns,
                    player_input=text,
                    game_state=game_state,
                    llm_manager=self.engine.llm_manager,
                )

                # 2. Passa per Guardian
                narrative_temp = NarrativeOutput(
                    text=completed_turn.text,
                    visual_en=completed_turn.visual_en,
                    tags_en=completed_turn.tags_en,
                    provider_used="gemini/multi-npc",
                )
                if self._guardian.validate_narrative(narrative_temp):
                    changes_temp = self._guardian.apply(
                        narrative=narrative_temp,
                        game_state=game_state,
                        outfit_engine=self.engine.outfit_engine,
                        allow_invite=False,
                    )
                    if changes_temp.get("affinity_changes"):
                        game_state.flags["_gm_stall_count"] = 0
                else:
                    logger.warning(
                        "[Orchestrator] Guardian rejected turn from %s", turn.speaker
                    )
                    completed_turn.text = f"*{completed_turn.speaker} sembra assorta nei propri pensieri*"

                # 3. Salva nel database
                if self.engine.memory_manager:
                    try:
                        await self.engine.memory_manager.add_message(
                            role="assistant",
                            content=f"{completed_turn.speaker}: {completed_turn.text}",
                            turn_number=game_state.turn_count,
                            visual_en=completed_turn.visual_en,
                            tags_en=completed_turn.tags_en,
                            companion_name=completed_turn.speaker,
                        )
                    except Exception as e:
                        logger.warning(
                            "[Orchestrator] Failed to save intermediate message: %s", e
                        )

                # 4. Accumula
                result.completed_turns.append(completed_turn)

                # 5. Mostra testo in UI
                if hasattr(self.engine, "_ui_intermediate_message_callback"):
                    try:
                        await self.engine._ui_intermediate_message_callback(
                            text=completed_turn.text,
                            speaker=completed_turn.speaker,
                            turn_number=game_state.turn_count,
                            visual_en=completed_turn.visual_en,
                            tags_en=completed_turn.tags_en,
                        )
                    except Exception as e:
                        logger.warning("[Orchestrator] UI text callback failed: %s", e)

                # 6. Genera immagine multi-personaggio
                turn_image_path = None
                if (
                    self.engine.media_pipeline
                    and not self.engine.no_media
                    and completed_turn.visual_en
                ):
                    try:
                        from luna.media.builders.character_builders import (  # lazy
                            MultiCharacterBuilder,
                        )
                        if _mc_builder is None:
                            _mc_builder = MultiCharacterBuilder()
                        characters = self.engine.multi_npc_manager.prepare_characters_for_builder(
                            turn=completed_turn,
                            all_present_npcs=all_present_npcs,
                            outfit_data=outfit_data,
                            visual_description=completed_turn.visual_en,
                        )
                        mc_prompt = _mc_builder.build_prompt(
                            visual_description=completed_turn.visual_en,
                            tags=completed_turn.tags_en,
                            characters=characters,
                        )
                        media_result = await self.engine.media_pipeline.generate_all(
                            text=completed_turn.text,
                            visual_en=completed_turn.visual_en,
                            tags=completed_turn.tags_en,
                            companion_name=completed_turn.speaker,
                            sd_positive=mc_prompt.positive,
                            sd_negative=mc_prompt.negative,
                        )
                        turn_image_path = media_result.image_path if media_result else None
                        logger.debug(
                            "[Orchestrator] MultiNPC image %d ready: %s", i + 1, turn_image_path
                        )
                    except Exception as e:
                        logger.warning("[Orchestrator] MultiNPC image %d failed: %s", i + 1, e)

                result.image_paths.append(turn_image_path)

                # 7. Mostra immagine in UI
                if turn_image_path and hasattr(self.engine, "_ui_image_callback"):
                    try:
                        self.engine._ui_image_callback(turn_image_path)
                    except Exception as e:
                        logger.warning("[Orchestrator] UI image callback failed: %s", e)

                # 8. Check interruzione utente
                if self.engine.multi_npc_manager.check_interruption(game_state):
                    logger.info("[Orchestrator] MultiNPC interrupted by user")
                    result.was_interrupted = True
                    self.engine.multi_npc_manager.clear_interruption_flag(game_state)
                    break

            except Exception as e:
                logger.error("[Orchestrator] Error processing MultiNPC turn %d: %s", i, e)
                continue

        if hasattr(self.engine, "_show_interrupt_callback"):
            try:
                self.engine._show_interrupt_callback(False)
            except Exception as e:
                logger.debug("[Orchestrator] Could not hide interrupt button: %s", e)

        game_state.flags.pop("_multi_npc_in_progress", None)

        if result.completed_turns:
            final_turn = result.completed_turns[-1]
            result.narrative = NarrativeOutput(
                text=final_turn.text,
                visual_en=final_turn.visual_en,
                tags_en=final_turn.tags_en,
                provider_used="gemini/multi-npc",
            )
            result.skip_standard_llm = True
            logger.info(
                "[Orchestrator] MultiNPC completed: %d messages", len(result.completed_turns)
            )

        return result

    async def _apply_phase_event(
        self,
        ctx: TurnContext,
        phase_event: Any,
        transition_event: Any = None,
    ) -> TurnContext:
        """Applica un PhaseChangeEvent: aggiorna time_of_day, riposiziona NPC,
        genera farewell se il companion attivo si sposta.

        Chiamato da:
        - _run_phase_clock (path automatico, transition_event da ScheduleAgent)
        - execute_phase_advance (path manuale, transition_event=None)
        """
        game_state = ctx.game_state
        game_state.time_of_day = phase_event.new_phase
        ctx.phase_changed = True

        if self._schedule_agent and not ctx.is_manual_phase_advance:
            self._schedule_agent.reset_phase()

        logger.info("[Orchestrator] Phase changed to %s", phase_event.new_phase)

        if not self.engine.schedule_manager:
            return ctx

        # ── Riposiziona tutti gli NPC al nuovo orario ─────────────────────────
        staying = getattr(game_state, "companion_staying_with_player", False)
        active = game_state.active_companion
        for npc_name in list(game_state.npc_locations.keys()):
            if staying and npc_name == active:
                continue
            new_loc = self.engine.schedule_manager.get_npc_location(
                npc_name, phase_event.new_phase
            )
            if new_loc:
                old_loc = game_state.get_npc_location(npc_name)
                if old_loc != new_loc:
                    game_state.set_npc_location(npc_name, new_loc)
                    logger.info(
                        "[PhaseChange] %s: %s → %s", npc_name, old_loc, new_loc
                    )

        # ── Se il companion attivo si sposta → farewell + switch to solo ─
        if not staying and active and active not in (_SOLO_COMPANION, None):
            new_companion_loc = self.engine.schedule_manager.get_npc_location(
                active, phase_event.new_phase
            )
            if new_companion_loc and new_companion_loc != game_state.current_location:
                farewell_narrative = await self._generate_farewell(
                    companion_name=active,
                    new_phase=phase_event.new_phase,
                    new_location=new_companion_loc,
                    game_state=game_state,
                    transition_event=transition_event,
                )
                if farewell_narrative:
                    ctx.narrative = farewell_narrative
                await self.engine.state_manager.switch_to_solo(game_state)
                logger.info("[PhaseChange] %s farewell + switch to solo", active)

        return ctx

    async def _run_phase_clock(self, ctx: TurnContext) -> TurnContext:
        """Step 8 — Phase clock automatico (path originale).

        Usa tick() per avanzamento automatico ogni N turni.
        Se manual_mode è attivo, tick() ritorna None e non succede nulla.
        """
        game_state = ctx.game_state
        if not self.engine.phase_clock:
            return ctx

        # ── ScheduleAgent tick (prima del clock tick) ────────────────────────
        transition_event = None
        if self._schedule_agent:
            try:
                phase_clock = self.engine.phase_clock
                turn_in_phase = phase_clock.turns_in_phase
                next_phase = phase_clock._next_phase()
                sched_result = self._schedule_agent.tick(
                    game_state=game_state,
                    turn_in_phase=turn_in_phase,
                    current_phase=game_state.time_of_day,
                    next_phase=next_phase,
                )
                transition_event = sched_result.get("transition_event")
                if transition_event:
                    logger.info(
                        "[ScheduleAgent] %s event: %s urgency=%s",
                        "Warning" if transition_event.is_warning else "Departure",
                        transition_event.companion_name,
                        transition_event.urgency,
                    )
            except Exception as e:
                logger.warning("[Orchestrator] ScheduleAgent tick failed: %s", e)

        phase_event = self.engine.phase_clock.tick(game_state.turn_count)
        if not phase_event:
            return ctx

        return await self._apply_phase_event(ctx, phase_event, transition_event)

    async def execute_phase_advance(self) -> TurnResult:
        """Entry point per il pulsante UI 'Avanza Fase'.

        Salta tutte le fasi normali (intent, LLM, guardian, media).
        Esegue solo: force_advance → _apply_phase_event → save → build_result.
        """
        from luna.systems.phase_clock import PhaseAdvanceReason

        ctx = TurnContext(
            user_input="",
            game_state=self.engine.state,
            text="",
            is_manual_phase_advance=True,
        )

        if not self.engine.phase_clock:
            logger.warning("[Orchestrator] execute_phase_advance: no phase_clock")
            return TurnResult(
                text="", turn_number=self.engine.state.turn_count, provider_used="system"
            )

        phase_event = self.engine.phase_clock.force_advance(
            PhaseAdvanceReason.FORCED, self.engine.state.turn_count
        )
        if not phase_event:
            logger.warning("[Orchestrator] execute_phase_advance: force_advance returned None")
            return TurnResult(
                text="", turn_number=self.engine.state.turn_count, provider_used="system"
            )

        ctx = await self._apply_phase_event(ctx, phase_event, transition_event=None)

        # Salva solo se c'è un farewell da persistere
        if ctx.narrative:
            await self._save(ctx.game_state, "", ctx.narrative, {})

        return self._build_result(ctx)
