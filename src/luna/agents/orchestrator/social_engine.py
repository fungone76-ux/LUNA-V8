"""Luna RPG — Social Engine Mixin.

Step 5.5 del turno: gestisce le scene multi-companion.

_run_home_scene — 2+ companion a casa del giocatore (4 casi).
_run_multi_npc  — NPC casuali/non-companion che entrano nella scena.
"""
from __future__ import annotations

import logging

from luna.core.models import NarrativeOutput

from .turn_context import MultiNPCResult, TurnContext

logger = logging.getLogger(__name__)
_SOLO_COMPANION = "_solo_"


class SocialEngineMixin:

    async def _run_home_scene(self, ctx: TurnContext) -> MultiNPCResult:
        """Gestisce il turno quando 2+ companion sono a casa.

        Caso 1 — player nomina una companion non-attiva → risponde quella, l'altra reagisce.
        Caso 2 — player si rivolge a tutte → tutte rispondono in sequenza.
        Caso 3 — input generico → risponde l'attiva (flusso normale) + reazioni post.
        Caso 4 — inter-NPC → companion si parlano tra loro.

        Ogni risposta viene mostrata come bolla separata via _ui_intermediate_message_callback.
        """
        from luna.systems.home_scene_orchestrator import HomeSceneOrchestrator
        from luna.systems.multi_npc.dialogue_sequence import SpeakerType

        game_state = ctx.game_state
        home_mgr = self.engine.home_guest_manager
        result = MultiNPCResult()

        guests = home_mgr.get_active_guests()
        active = game_state.active_companion
        all_present = [active] + [g for g in guests if g != active]

        if len(all_present) < 2:
            return result

        # If the player just sent an invitation to the active companion (companion
        # switch + newly invited this turn), the message is directed at THEM alone.
        # Existing guests must not react to what is essentially a private message.
        if ctx.switched and active in ctx.home_invited:
            return result  # skip_standard_llm=False → active responds normally via Step 6

        home_orch = HomeSceneOrchestrator(engine=self.engine)
        addressed_npc, all_addressed = home_orch.detect_addressed_npc(
            ctx.text, all_present, active
        )

        def _make_turn(speaker, text, visual_en="", tags_en=None):
            class _Turn:
                pass
            t = _Turn()
            t.speaker = speaker
            t.text = text
            t.visual_en = visual_en
            t.tags_en = tags_en or []
            t.speaker_type = SpeakerType.ACTIVE_NPC
            return t

        async def _push(speaker, text, visual_en="", tags_en=None):
            """Aggiunge il turno a result E mostra la bolla in UI."""
            turn = _make_turn(speaker, text, visual_en, tags_en)
            result.completed_turns.append(turn)
            if hasattr(self.engine, "_ui_intermediate_message_callback"):
                try:
                    await self.engine._ui_intermediate_message_callback(
                        text=text,
                        speaker=speaker,
                        turn_number=game_state.turn_count,
                        visual_en=visual_en or "",
                        tags_en=tags_en or [],
                    )
                except Exception as _cb_err:
                    logger.debug("[HomeScene] UI callback failed: %s", _cb_err)

        def _extract_text(resp) -> str:
            if resp and hasattr(resp, "text"):
                return resp.text or ""
            return resp if isinstance(resp, str) else ""

        async def _gen_image_for_current_npc(narrative_out, npc_name: str) -> None:
            if self.engine.no_media or not self.engine.media_pipeline:
                return
            try:
                lora_on = (
                    self.engine.lora_mapping.is_enabled()
                    if self.engine.lora_mapping is not None else False
                )
                v_out = self._visual.build(
                    narrative=narrative_out,
                    game_state=game_state,
                    lora_enabled=lora_on,
                )
                img = await self._generate_media(game_state, narrative_out, v_out)
                if img and img.get("image_path") and hasattr(self.engine, "_ui_image_callback"):
                    self.engine._ui_image_callback(img["image_path"])
            except Exception as _ie:
                logger.warning("[HomeScene] Inline image failed for %s: %s", npc_name, _ie)

        def _apply_narrative_outfit(npc_name: str, narrative_visual_en: str) -> None:
            if not narrative_visual_en:
                return
            try:
                outfit = game_state.get_outfit()
                outfit.style = "home_scene_auto"
                outfit.description = narrative_visual_en
                outfit.base_sd_prompt = narrative_visual_en
                outfit.components.clear()
                outfit.modifications.clear()
                game_state.set_outfit(outfit)
                logger.info("[HomeScene] %s: outfit estratto da visual_en", npc_name)
            except Exception as _oe:
                logger.warning("[HomeScene] Outfit update failed for %s: %s", npc_name, _oe)

        # ── CASO 1: player si rivolge a companion non-attiva ─────────────────
        if addressed_npc and addressed_npc != active:
            old_active = game_state.active_companion
            game_state.active_companion = addressed_npc
            try:
                companion_narrative = await self._narrative.generate(
                    user_input=ctx.text,
                    game_state=game_state,
                    llm_manager=self.engine.llm_manager,
                    context=ctx.context,
                )
            except Exception as e:
                logger.warning("[HomeScene] Case1 narrative failed: %s", e)
                game_state.active_companion = old_active
                return result
            if companion_narrative and companion_narrative.text:
                _apply_narrative_outfit(addressed_npc, companion_narrative.visual_en)
            game_state.active_companion = old_active

            if companion_narrative and companion_narrative.text:
                await _push(addressed_npc, companion_narrative.text,
                            companion_narrative.visual_en, companion_narrative.tags_en)
                game_state.active_companion = addressed_npc
                await _gen_image_for_current_npc(companion_narrative, addressed_npc)
                game_state.active_companion = old_active
                ctx.home_scene_media_done = True
                reaction_prompt = home_orch.build_reaction_prompt(
                    reacting_npc=old_active,
                    primary_text=companion_narrative.text,
                    primary_speaker=addressed_npc,
                    player_input=ctx.text,
                    game_state=game_state,
                    context=ctx.context,
                )
                try:
                    r_resp, _ = await self.engine.llm_manager.generate(
                        system_prompt=reaction_prompt, user_input="",
                        history=[], json_mode=False, companion_name=old_active,
                    )
                    r_text = _extract_text(r_resp)
                    if r_text:
                        await _push(old_active, r_text)
                except Exception as e:
                    logger.warning("[HomeScene] Case1 reaction failed: %s", e)

                result.skip_standard_llm = True
                result.narrative = companion_narrative
            return result

        # ── CASO 2: player si rivolge a tutte ────────────────────────────────
        if all_addressed:
            prev_text = ""
            for npc in all_present:
                old_active = game_state.active_companion
                game_state.active_companion = npc
                try:
                    enriched = dict(ctx.context)
                    if prev_text:
                        enriched["previous_home_turn"] = f"[{old_active} just said: {prev_text[:100]}]"
                    other_names = ", ".join(n for n in all_present if n != npc)
                    enriched["home_scene_context"] = (
                        f"GROUP SCENE — YOUR TURN: {npc}\n"
                        f"Also present: {other_names}\n"
                        f"Write ONLY {npc}'s response (one short paragraph or a few sentences).\n"
                        f"Do NOT write {other_names}'s dialogue or actions — they will respond separately."
                    )
                    npc_narrative = await self._narrative.generate(
                        user_input=ctx.text,
                        game_state=game_state,
                        llm_manager=self.engine.llm_manager,
                        context=enriched,
                    )
                    if npc_narrative and npc_narrative.text:
                        _apply_narrative_outfit(npc, npc_narrative.visual_en)
                        await _push(npc, npc_narrative.text,
                                    npc_narrative.visual_en, npc_narrative.tags_en)
                        await _gen_image_for_current_npc(npc_narrative, npc)
                        prev_text = npc_narrative.text
                except Exception as e:
                    logger.warning("[HomeScene] Case2 turn failed for %s: %s", npc, e)
                finally:
                    game_state.active_companion = old_active

            if result.completed_turns:
                result.skip_standard_llm = True
                ctx.home_scene_media_done = True
                last = result.completed_turns[-1]
                result.narrative = NarrativeOutput(
                    text=last.text,
                    visual_en=last.visual_en or "",
                    tags_en=last.tags_en or [],
                    provider_used="home-scene",
                )
            return result

        # ── CASO 4: inter-NPC ─────────────────────────────────────────────────
        if home_orch.is_inter_npc_request(ctx.text) and len(all_present) >= 2:
            speaker, listener = all_present[0], all_present[1]
            context_text = f"You are at the player's home with {listener}. The player is watching."
            if ctx.text.strip():
                context_text += f"\nThe player said: '{ctx.text}'"
            prompt_a = home_orch.build_inter_npc_prompt(speaker, listener, context_text, game_state)
            try:
                resp_a, _ = await self.engine.llm_manager.generate(
                    system_prompt=prompt_a, user_input="",
                    history=[], json_mode=False, companion_name=speaker,
                )
                text_a = _extract_text(resp_a)
            except Exception as e:
                logger.warning("[HomeScene] Case4 speaker failed: %s", e)
                text_a = ""

            if text_a:
                await _push(speaker, text_a)
                ctx_b = f"{context_text}\n{speaker} just said to you: \"{text_a}\""
                prompt_b = home_orch.build_inter_npc_prompt(listener, speaker, ctx_b, game_state)
                try:
                    resp_b, _ = await self.engine.llm_manager.generate(
                        system_prompt=prompt_b, user_input="",
                        history=[], json_mode=False, companion_name=listener,
                    )
                    text_b = _extract_text(resp_b)
                    if text_b:
                        await _push(listener, text_b)
                except Exception as e:
                    logger.warning("[HomeScene] Case4 listener failed: %s", e)

                if result.completed_turns:
                    result.skip_standard_llm = True
                    result.narrative = NarrativeOutput(
                        text=result.completed_turns[-1].text,
                        visual_en="",
                        tags_en=[],
                        provider_used="home-scene-inter-npc",
                    )
            return result

        # ── CASO 3: input generico → flusso normale, reazioni post-narrativa ─
        ctx.home_mode_secondary = [g for g in guests if g != active]
        return result

    async def _run_multi_npc(self, ctx: TurnContext) -> MultiNPCResult:
        """Step 5.5 — MultiNPC expanded.

        Restituisce MultiNPCResult con completed_turns, image_paths,
        was_interrupted, skip_standard_llm, narrative.
        """
        result = MultiNPCResult()
        game_state = ctx.game_state
        text = ctx.text

        # ── HOME SCENE MODE: 2+ companion a casa ─────────────────────────────
        home_mgr = getattr(self.engine, "home_guest_manager", None)
        if home_mgr and home_mgr.has_guests() and game_state.current_location == "player_home":
            if game_state.active_companion != _SOLO_COMPANION:
                home_result = await self._run_home_scene(ctx)
                if home_result.skip_standard_llm:
                    return home_result
            return result

        # Non interrompere con NPC casuali durante missioni foreground attive
        _has_foreground_quest = bool(game_state.active_quests) and not game_state.flags.get("_secondary_npc")
        if not (
            self.engine.multi_npc_manager
            and not getattr(self.engine.state_manager.current, "is_temporary", False)
            and game_state.active_companion != _SOLO_COMPANION
            and not _has_foreground_quest
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

        # ── Aggiorna location di tutti gli NPC partecipanti alla scena ──────
        player_loc = game_state.current_location

        _name_to_id: dict = {}
        if self.engine.world:
            for _id, _def in self.engine.world.npc_templates.items():
                _n = _def.get("name", _id) if isinstance(_def, dict) else getattr(_def, "name", _id)
                _name_to_id[_n] = _id
                _name_to_id[_id] = _id
            for _id, _def in self.engine.world.companions.items():
                _n = getattr(_def, "name", _id)
                _name_to_id[_n] = _id
                _name_to_id[_id] = _id

        for turn in multi_npc_sequence.turns:
            speaker_raw = getattr(turn, "speaker", None) or getattr(turn, "npc_id", None)
            if not speaker_raw:
                continue
            npc_id = (
                _name_to_id.get(speaker_raw)
                or _name_to_id.get(speaker_raw.lower())
                or speaker_raw.lower()
            )
            current_loc = game_state.npc_locations.get(npc_id)
            if current_loc != player_loc:
                game_state.set_npc_location(npc_id, player_loc)
                logger.info(
                    "[MultiNPC] %s (%s) si sposta in %s (era: %s)",
                    speaker_raw, npc_id, player_loc, current_loc or "sconosciuta"
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
                    _npc_def = (
                        self.engine.world.companions.get(completed_turn.speaker)
                        or self.engine.world.npc_templates.get(completed_turn.speaker)
                    )
                    _gender = getattr(_npc_def, "gender", "female") if _npc_def else "female"
                    _adj = "assorto" if _gender == "male" else "assorta"
                    completed_turn.text = f"*{completed_turn.speaker} sembra {_adj} nei propri pensieri*"

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
            _seq_speakers = list({t.speaker for t in result.completed_turns})
            _secondary = [s for s in _seq_speakers if s != game_state.active_companion]
            result.narrative = NarrativeOutput(
                text=final_turn.text,
                visual_en=final_turn.visual_en,
                tags_en=final_turn.tags_en,
                secondary_characters=_secondary,
                provider_used="gemini/multi-npc",
            )
            result.skip_standard_llm = True
            logger.info(
                "[Orchestrator] MultiNPC completed: %d messages", len(result.completed_turns)
            )

        return result
