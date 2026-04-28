"""Luna RPG — Turn Pipeline Mixin.

Orchestrazione ad alto livello del turno di gioco (il "cervello").

Le 5 fasi + _build_result coordinano il flusso chiamando gli helper
specializzati negli altri mixin (agenda_handler, social_engine,
narrative_processor, time_manager).

Pipeline:
  execute()
    → _phase_pre_turn      Steps 0, 0.3, 0.35, 0.5, 0.7, 1, 2
    → _phase_world_state   Steps 2.5, 2.7, 2.9, 2.8, 3
    → _phase_context       Steps 0.4, 0.5, 4, 5
    → _phase_narrative     Steps 5.5, 6, 6c, 7, 7.2, 7.5
    → _phase_finalize      Steps 8, 9, 9.5, 10, 11
    → _build_result        Step 12
"""
from __future__ import annotations

import logging

from luna.core.models import IntentType, NarrativeOutput, TurnResult

from .turn_context import TurnContext

logger = logging.getLogger(__name__)
_SOLO_COMPANION = "_solo_"


class TurnPipelineMixin:
    """Mixin con le 5 fasi del turno + _build_result.

    Accede a self.engine, self._narrative, self._guardian, ecc.
    impostati da TurnOrchestrator.__init__().
    """

    # =========================================================================
    # Fase 1: Pre-turn  (Steps 0, 0.3, 0.35, 0.5, 0.7, 1, 2)
    # =========================================================================

    async def _phase_pre_turn(self, ctx: TurnContext) -> TurnContext:
        game_state = ctx.game_state
        text = ctx.text

        # ── Step 0: Intent classification ────────────────────────────────────
        has_event = bool(
            (self.engine.event_manager and self.engine.event_manager.has_pending_event())
            or (self.engine.gameplay_manager and self.engine.gameplay_manager.has_pending_event())
        )
        ctx.intent = self._intent_router.analyze(text, game_state, has_event)
        logger.debug("[Orchestrator] Intent: %s", ctx.intent.primary)

        # ── Step 0.3: NPC Location Router ─────────────────────────────────────
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
                    if ctx.intent.primary != IntentType.MOVEMENT:
                        ctx.intent.primary = IntentType.MOVEMENT
                        ctx.intent.target_location = route_result.location_id
            except Exception as e:
                logger.warning("[Orchestrator] NPC Location Router failed: %s", e)

        # ── Step 0.35: HomeGuestManager — rileva inviti/congedi a casa ──────
        home_mgr = getattr(self.engine, "home_guest_manager", None)
        if home_mgr:
            active = game_state.active_companion
            multi_invite = home_mgr.detect_invite_multiple(text)
            if multi_invite:
                for npc_name in multi_invite:
                    if home_mgr.invite(npc_name, game_state.turn_count):
                        game_state.set_npc_location(npc_name, game_state.current_location)
                        ctx.home_invited.append(npc_name)
                logger.info("[Orchestrator] Home multi-invite: %s", multi_invite)
            elif active and home_mgr.detect_invite_intent(text, active):
                if home_mgr.invite(active, game_state.turn_count):
                    game_state.set_npc_location(active, game_state.current_location)
                    ctx.home_invited.append(active)
                    logger.info("[Orchestrator] Home invite: %s", active)
            elif active and home_mgr.is_guest(active) and home_mgr.detect_dismiss_intent(text):
                home_mgr.dismiss(active)
                game_state.mark_npc_departed(active)
                ctx.home_dismissed = active
                logger.info("[Orchestrator] Home dismiss: %s", active)
            if (
                ctx.intent is not None
                and ctx.intent.primary == IntentType.MOVEMENT
                and game_state.current_location == "player_home"
                and getattr(ctx.intent, "target_location", None) != "player_home"
                and home_mgr.has_guests()
            ):
                home_mgr.dismiss_all()
                logger.info("[Orchestrator] Player leaving home — all guests dismissed")

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

        # ── Aggiorna location ex-companion dopo switch ────────────────────────
        if ctx.switched and ctx.old_companion:
            old_comp = ctx.old_companion
            player_loc = game_state.current_location
            if game_state.active_companion == _SOLO_COMPANION:
                game_state.mark_npc_departed(old_comp)
                logger.debug("[Orchestrator] %s departed (player went solo)", old_comp)
            else:
                existing = game_state.npc_locations.get(old_comp)
                if existing != player_loc:
                    game_state.set_npc_location(old_comp, player_loc)
                    logger.debug(
                        "[Orchestrator] Ex-companion %s aggiornato a %s",
                        old_comp, player_loc
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
            # B5: setta flag per companion_initiative activation_type
            if ctx.directive.driver.value == "npc":
                game_state.flags["_npc_initiative_active"] = game_state.active_companion
            else:
                game_state.flags.pop("_npc_initiative_active", None)

        # ── Step 2.7: TensionTracker tick ─────────────────────────────────────
        if self.engine.tension_tracker and not game_state.active_quests:
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
                    ctx.new_global_events = new_events
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
    # Fase 3: Context building  (Steps 0.4, 0.5, 4, 5)
    # =========================================================================

    async def _phase_context(self, ctx: TurnContext) -> TurnContext:
        game_state = ctx.game_state

        # ── Step 0.4: PresenceTracker ─────────────────────────────────────────
        present_npcs: list = []
        if self.engine.multi_npc_manager and not game_state.active_quests:
            try:
                present_npcs = self.engine.multi_npc_manager.get_present_npcs(
                    game_state.active_companion, game_state
                )
                _hm = getattr(self.engine, "home_guest_manager", None)
                if (_hm and _hm.has_guests()
                        and game_state.current_location == "player_home"):
                    _invited = set(_hm.get_active_guests())
                    present_npcs = [n for n in present_npcs if n in _invited]
                ctx.present_npcs = present_npcs
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

        # Refresh journal snapshot AFTER quest_engine.update() ran inside _build_context.
        if ctx.narrative_compass is not None:
            try:
                from luna.systems.quest_engine_sequential import SequentialQuestEngine
                if isinstance(self.engine.quest_engine, SequentialQuestEngine):
                    snap = self.engine.quest_engine.get_journal_snapshot(game_state)
                    ctx.narrative_compass.active_quest_title = snap.active_quest_title
                    ctx.narrative_compass.active_stage_title = snap.active_stage_title
                    ctx.narrative_compass.active_stage_hint  = snap.active_stage_hint
                    ctx.narrative_compass.next_quest_title   = snap.next_quest_title
                    ctx.narrative_compass.is_hidden          = snap.is_hidden
            except Exception as _qe:
                logger.debug("[Orchestrator] Post-quest journal refresh failed: %s", _qe)

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

        # ── Inject active authority scene context ─────────────────────────────
        active_auth = getattr(self.engine, '_active_authority_scene', None)
        if active_auth:
            npc_id     = active_auth["npc_id"]
            expires_at = active_auth.get("expires_at_turn", 0)
            still_active = game_state.turn_count <= expires_at

            if still_active:
                presence = (
                    "ERA PRESENTE poco fa e ha appena lasciato la stanza"
                )
                loc_desc = active_auth.get("npc_location_desc", "")
                ctx.context["active_authority_scene"] = (
                    f"CONTESTO SCENA RECENTE — {active_auth['npc_display_name']} {presence}. "
                    f"Ecco il dialogo avvenuto:\n"
                    f"{active_auth['dialogue']}\n"
                    f"Il companion DEVE rispondere tenendo conto di questo contesto. "
                    f"Non ignorare quanto appena accaduto."
                )
                if loc_desc:
                    ctx.context["active_authority_npc_location"] = loc_desc
                logger.debug(
                    "[Orchestrator] Authority scene context injected: %s (active=%s, expires=%d)",
                    npc_id, still_active, expires_at,
                )
            else:
                self.engine._active_authority_scene = None

        # Persist player input per quest engine action conditions
        game_state.flags["_last_player_input"] = ctx.text

        # ── Step 5: Enrich context ────────────────────────────────────────────
        ctx.context = await self._enrich_context(ctx.context, game_state, ctx.text)

        return ctx

    # =========================================================================
    # Fase 5: Finalize  (Steps 8, 9, 9.5, 10, 11)
    # =========================================================================

    async def _phase_finalize(self, ctx: TurnContext) -> TurnContext:
        game_state = ctx.game_state

        # ── Step 8: Advance turn + phase clock ───────────────────────────────
        game_state.turn_count += 1
        ctx = await self._run_phase_clock(ctx)

        # ── Step 9: Save state + memory ───────────────────────────────────────
        await self._save(game_state, ctx.text, ctx.narrative, ctx.changes)

        # ── Step 9.5: Witness check (Metodo 3: Reazioni a Catena) ─────────────
        try:
            witness_sys = getattr(self.engine, 'witness_system', None)
            if witness_sys and ctx.narrative and ctx.narrative.text:
                narrative_lower = ctx.narrative.text.lower()
                event_type = None
                if any(w in narrative_lower for w in [
                    "vicini", "mano", "abbracci", "baci", "intimi",
                    "sfiorat", "toccat", "stretti", "abbracciati"
                ]):
                    event_type = "intimate_moment"
                elif any(w in narrative_lower for w in [
                    "litigat", "arrabbiat", "urla", "sgridat", "discussione"
                ]):
                    event_type = "argument"
                elif any(w in narrative_lower for w in [
                    "piange", "lacrime", "vulnerabile", "sola", "triste", "singhiozz"
                ]):
                    event_type = "emotional_moment"

                if event_type:
                    witness_event = witness_sys.check_maria_witnesses(
                        event_type=event_type,
                        subject_npc=game_state.active_companion,
                        location=game_state.current_location,
                        game_state=game_state,
                    )
                    if witness_event:
                        action = witness_sys.maria_decides_action(witness_event, game_state)
                        witness_sys.propagate_gossip(witness_event, action, game_state)
                        logger.info(
                            "[WitnessSystem] Maria witnessed '%s' → action: %s",
                            event_type, action
                        )
        except Exception as e:
            logger.warning("[WitnessSystem] Check failed: %s", e)

        # ── Update active authority scene (normal turns with authority NPC) ───
        npc_def = self.engine.world.npc_templates.get(game_state.active_companion)
        if npc_def:
            style = (
                npc_def.get("initiative_style", "") if isinstance(npc_def, dict)
                else getattr(npc_def, "initiative_style", "")
            )
            if style in ("authority", "official_summons") and ctx.narrative and ctx.narrative.text:
                prev = getattr(self.engine, "_active_authority_scene", None) or {}
                prev_dialogue = prev.get("dialogue", "")
                npc_name = (
                    npc_def.get("name", game_state.active_companion)
                    if isinstance(npc_def, dict)
                    else getattr(npc_def, "name", game_state.active_companion)
                )
                spawn_locs = (
                    npc_def.get("spawn_locations", []) if isinstance(npc_def, dict)
                    else getattr(npc_def, "spawn_locations", [])
                )
                npc_location_desc = prev.get("npc_location_desc", "")
                if not npc_location_desc and spawn_locs:
                    loc_id = spawn_locs[0]
                    world_loc = (self.engine.world.locations or {}).get(loc_id)
                    if world_loc:
                        npc_location_desc = getattr(world_loc, "name", loc_id)
                    else:
                        npc_location_desc = loc_id.replace("_", " ").title()
                if not npc_location_desc:
                    npc_location_desc = "ufficio"
                new_exchange = (
                    (f"Giocatore: {ctx.text}\n" if ctx.text else "")
                    + f"{npc_name}: {ctx.narrative.text}"
                )
                self.engine._active_authority_scene = {
                    "npc_id":              game_state.active_companion,
                    "npc_display_name":    npc_name,
                    "npc_location_desc":   npc_location_desc,
                    "dialogue":            (prev_dialogue + "\n" + new_exchange).strip(),
                    "expires_at_turn":     game_state.turn_count + 28,
                }
                logger.debug("[Orchestrator] Authority scene context updated: %s @ %s",
                             game_state.active_companion, npc_location_desc)

        # ── Step 10: VisualDirector ───────────────────────────────────────────
        active_is_npc_template = (
            self.engine.world.npc_templates.get(game_state.active_companion) is not None
            and self.engine.world.companions.get(game_state.active_companion) is None
        )
        if active_is_npc_template and ctx.narrative and not ctx.narrative.secondary_characters:
            companions_present = [
                npc for npc in ctx.present_npcs
                if self.engine.world.companions.get(npc)
            ]
            if companions_present:
                ctx.narrative.secondary_characters = companions_present

        ctx.narrative._user_input = ctx.text
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
        if ctx.home_scene_media_done:
            ctx.media = None
        else:
            ctx.media = await self._generate_media(game_state, ctx.narrative, ctx.visual_output)

        # ── Step 11.5: Mention reaction sequence ─────────────────────────────
        # Ordine garantito: 1) testo Luna  2) immagine Luna
        #                   3) testo Stella 4) immagine Stella
        # Tutto via callback intermedi; TurnResult.text/image svuotati dopo.
        if ctx.mention_reaction_npc and ctx.narrative and ctx.narrative.text:
            mention_npc = ctx.mention_reaction_npc
            active = game_state.active_companion

            active_def = self.engine.world.companions.get(active)
            active_name = getattr(active_def, "name", active) if active_def else active
            npc_def = (
                self.engine.world.companions.get(mention_npc)
                or self.engine.world.npc_templates.get(mention_npc)
            )
            npc_name = getattr(npc_def, "name", mention_npc) if npc_def else mention_npc

            # 1. Testo di Luna via callback
            if hasattr(self.engine, "_ui_intermediate_message_callback"):
                try:
                    await self.engine._ui_intermediate_message_callback(
                        text=ctx.narrative.text,
                        speaker=active,
                        turn_number=game_state.turn_count,
                        visual_en=ctx.narrative.visual_en or "",
                        tags_en=ctx.narrative.tags_en or [],
                    )
                except Exception as e:
                    logger.warning("[MentionReaction] Luna text callback failed: %s", e)

            # 2. Immagine di Luna via callback (già generata in Step 11)
            luna_image = ctx.media.get("image_path") if ctx.media else None
            if luna_image and hasattr(self.engine, "_ui_image_callback"):
                try:
                    self.engine._ui_image_callback(luna_image)
                except Exception as e:
                    logger.warning("[MentionReaction] Luna image callback failed: %s", e)

            # 3. Testo di Stella via LLM + callback
            reaction_text = ""
            reaction_prompt = (
                f"You are {npc_name}, present in the scene.\n"
                f"{active_name} just said: \"{ctx.narrative.text}\"\n"
                f"You were mentioned by name. React in 1-2 sentences, "
                f"staying in character. Do not start a new topic."
            )
            try:
                reaction_resp, _ = await self.engine.llm_manager.generate(
                    system_prompt=reaction_prompt,
                    user_input="",
                    history=[],
                    json_mode=False,
                    companion_name=mention_npc,
                )
                reaction_text = (
                    reaction_resp.text if reaction_resp and hasattr(reaction_resp, "text")
                    else (reaction_resp if isinstance(reaction_resp, str) else "")
                )
                if reaction_text and hasattr(self.engine, "_ui_intermediate_message_callback"):
                    await self.engine._ui_intermediate_message_callback(
                        text=reaction_text,
                        speaker=mention_npc,
                        turn_number=game_state.turn_count,
                        visual_en="",
                        tags_en=[],
                    )
            except Exception as e:
                logger.warning("[MentionReaction] Stella text failed for %s: %s", mention_npc, e)

            # 4. Immagine di Stella via swap temporaneo active_companion
            if reaction_text and not self.engine.no_media and self.engine.media_pipeline:
                old_active = game_state.active_companion
                try:
                    game_state.active_companion = mention_npc
                    lora_on = (
                        self.engine.lora_mapping.is_enabled()
                        if self.engine.lora_mapping is not None else False
                    )
                    _react_narr = NarrativeOutput(
                        text=reaction_text,
                        visual_en="",
                        tags_en=[],
                        provider_used="mention-reaction",
                    )
                    v_out = self._visual.build(
                        narrative=_react_narr,
                        game_state=game_state,
                        lora_enabled=lora_on,
                    )
                    img = await self._generate_media(game_state, _react_narr, v_out)
                    if img and img.get("image_path") and hasattr(self.engine, "_ui_image_callback"):
                        self.engine._ui_image_callback(img["image_path"])
                except Exception as e:
                    logger.warning("[MentionReaction] Stella image failed for %s: %s", mention_npc, e)
                finally:
                    game_state.active_companion = old_active

            # Svuota media e segna done → _build_result sopprime testo/immagine duplicati
            ctx.media = {}
            ctx.mention_reaction_done = True
            logger.info("[MentionReaction] Sequence done: %s → %s", active, mention_npc)

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

        # Se la sequenza mention_reaction ha già mostrato tutto via callback,
        # svuota testo e immagine per evitare duplicati nell'UI.
        if ctx.mention_reaction_done:
            narrative_text = ""
        else:
            narrative_text = ctx.narrative.text if ctx.narrative else ""
        provider_used = ctx.narrative.provider_used if ctx.narrative else "system"

        _game_state = ctx.game_state
        _departed = set(getattr(_game_state, "npc_departures", []))
        _present_raw = _game_state.flags.get("present_npcs", [])
        _present_chars = [n for n in _present_raw if n not in _departed]

        result = TurnResult(
            text=narrative_text,
            user_input=ctx.text,
            image_path=ctx.media.get("image_path") if ctx.media else None,
            audio_path=ctx.media.get("audio_path") if ctx.media else None,
            video_path=ctx.media.get("video_path") if ctx.media else None,
            affinity_changes=ctx.changes.get("affinity_changes", {}),
            new_quests=ctx.changes.get("quests_started", []),
            completed_quests=(
                ctx.changes.get("quests_completed", [])
                + ctx.game_state.flags.pop("_quests_completed_this_turn", [])
            ),
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
            present_characters=_present_chars,
        )

        # ── Home guests ───────────────────────────────────────────────────────
        _home_mgr = getattr(self.engine, "home_guest_manager", None)
        if _home_mgr:
            result.home_guests = _home_mgr.get_active_guests()

        # ── GlobalEvent payload ───────────────────────────────────────────────
        if self.engine.event_manager:
            primary = self.engine.event_manager.get_primary_event()
            if primary:
                result.active_event = primary.to_dict()
                result.new_event_started = bool(ctx.new_global_events)
                choices = primary.effects.get('choices')
                if choices:
                    result.dynamic_event = {
                        'event_id': primary.event_id,
                        'narrative': primary.description or primary.narrative_prompt,
                        'choices': choices,
                    }

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
