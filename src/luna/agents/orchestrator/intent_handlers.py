"""Luna RPG - Orchestrator Intent Handlers Mixin.

All intent handling methods for special player actions.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Optional

from luna.core.models import GameState, IntentType, NarrativeOutput, TurnResult
from luna.systems.mini_games.poker import PokerGame

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_SOLO_COMPANION = "_solo_"


class IntentHandlersMixin:
    """Mixin providing intent handling methods for TurnOrchestrator.
    
    Contains all _handle_* methods for special intents like movement,
    farewell, rest, combat, etc.
    """

    async def _handle_special_intents(
        self, intent: Any, game_state: GameState, raw_input: str
    ) -> Optional[TurnResult]:

        if intent.primary == IntentType.EVENT_CHOICE:
            return await self._handle_event_choice(intent, game_state, raw_input)

        if intent.primary == IntentType.MOVEMENT:
            return await self._handle_movement(intent, game_state, raw_input)

        if intent.primary == IntentType.FAREWELL:
            return await self._handle_farewell(game_state, raw_input)

        if intent.primary == IntentType.REST:
            return await self._handle_rest(intent, game_state, raw_input)

        if intent.primary == IntentType.FREEZE:
            return self._handle_freeze(intent, game_state, raw_input)

        if intent.primary == IntentType.SCHEDULE_QUERY:
            return self._handle_schedule_query(intent, game_state, raw_input)

        if intent.primary == IntentType.REMOTE_COMM:
            return await self._handle_remote_comm(intent, game_state, raw_input)

        if intent.primary == IntentType.SUMMON:
            await self._handle_summon(intent, game_state)
            return None  # continue to LLM

        if intent.primary == IntentType.INTIMATE_SCENE:
            self._handle_intimate_scene(intent, game_state)
            return None  # continue to LLM

        if intent.primary == IntentType.OUTFIT_MAJOR:
            await self._handle_outfit_major(intent, game_state)
            return None  # continue to LLM

        if intent.primary == IntentType.INVITATION:
            await self._handle_invitation(intent, game_state)
            return None  # continue to LLM

        if intent.primary == IntentType.POKER_GAME:
            return await self._handle_poker_game(raw_input, game_state)

        return None  # STANDARD → LLM

    # -------------------------------------------------------------------------

    def _detect_npc_template(self, text: str) -> Optional[str]:
        """Detect NPC template mention in player input.

        Only triggers when:
        - Player explicitly names an NPC (not self-description)
        - The NPC is in the current location (spawn_locations)
        - The NPC has a different role from the active companion
        """
        if not self.engine.world.npc_templates:
            return None
        import re
        text_lower = text.lower()

        # Skip if player is describing themselves
        if re.search(r"sono\s+(un|uno|una|il|la|nuovo|nuova)", text_lower):
            return None
        if re.search(r"mi\s+chiamo", text_lower):
            return None

        # Get active companion info
        game_state = self.engine.state
        active = game_state.active_companion if game_state else None
        active_comp = self.engine.world.companions.get(active) if active else None
        active_role = getattr(active_comp, "role", "").lower() if active_comp else ""
        current_location = game_state.current_location if game_state else ""
        active_name = getattr(active_comp, "name", "").lower() if active_comp else ""

        # Generic teacher words — skip when active companion IS a teacher
        teacher_words = ["professoressa", "professore", "insegnante", "teacher", "prof"]
        active_is_teacher = any(
            r in active_role for r in ["insegnante", "teacher", "professor", "docente"]
        )

        for template_id, template_data in self.engine.world.npc_templates.items():
            if not isinstance(template_data, dict):
                continue

            # Location check — soft hint, not a hard block
            # If NPC is outside their normal location, add a note to context
            spawn_locs = template_data.get("spawn_locations", [])
            out_of_location = bool(
                spawn_locs and current_location and current_location not in spawn_locs
            )
            # Store for context enrichment — don't block activation

            aliases = template_data.get("aliases", [])
            name = template_data.get("name", "").lower()
            npc_role = template_data.get("role", "").lower()
            all_names = [name] + [a.lower() for a in aliases]

            for alias in all_names:
                if alias not in text_lower:
                    continue
                # Skip if this is just a generic teacher word while talking to a teacher
                if alias in teacher_words and active_is_teacher:
                    continue
                # Skip if same role as active companion
                if npc_role and active_role and (
                    npc_role in active_role or active_role in npc_role
                ):
                    continue
                # Skip active companion's own name
                if alias == active_name:
                    continue
                # Skip if player is self-describing: "sono [anything] <alias>"
                # Covers "sono Andrea il nuovo studente", "sono uno studente", etc.
                if re.search(r"\bsono\b[^.!?]*\b" + re.escape(alias) + r"\b", text_lower):
                    continue
                # If out of normal location, store hint for narrative context
                if out_of_location:
                    npc_name = template_data.get("name", template_id)
                    spawn_names = ", ".join(spawn_locs)
                    self._npc_location_hint = f"[Nota: {npc_name} normalmente si trova in {spawn_names}, ora è qui su richiesta del player]"
                else:
                    self._npc_location_hint = None
                return template_id
        return None


    async def _activate_npc_template(self, template_id: str, game_state: GameState) -> None:
        """Create a temporary companion from NPC template and switch to it."""
        from luna.core.models import CompanionDefinition
        template_data = self.engine.world.npc_templates.get(template_id, {})
        if not isinstance(template_data, dict):
            return

        # Create CompanionDefinition from template
        try:
            # Build rich personality from template fields
            personality_parts = []
            if template_data.get("base_personality"):
                personality_parts.append(template_data["base_personality"])
            elif template_data.get("personality"):
                personality_parts.append(template_data["personality"])
            if template_data.get("voice_tone"):
                personality_parts.append(f"Voice/tone: {template_data['voice_tone']}")

            comp_def = CompanionDefinition(
                name=template_data.get("name", template_id),
                role=template_data.get("role", ""),
                base_prompt=template_data.get("base_prompt", ""),
                base_personality="\n".join(personality_parts),
                background=template_data.get("background", ""),
                relationship_to_player=template_data.get("relationship_to_player", ""),
                visual_tags=template_data.get("visual_tags", []),
                is_temporary=True,
            )
            # Register temporarily in world companions
            self.engine.world.companions[template_id] = comp_def
            # Switch to this companion
            await self.engine.state_manager.switch_companion(template_id, game_state)
            logger.info("[Orchestrator] Activated NPC template: %s", template_id)
        except Exception as e:
            logger.warning("[Orchestrator] NPC template activation failed: %s", e)

    async def _handle_event_choice(self, intent, game_state, raw_input) -> TurnResult:
        if self.engine.gameplay_manager:
            result = self.engine.gameplay_manager.process_event_choice(
                intent.event_choice_index, game_state
            )
            text = getattr(result, "narrative", "") or getattr(result, "message", "")
        else:
            text = "Scelta registrata."
        return TurnResult(
            text=text, user_input=raw_input,
            turn_number=game_state.turn_count, provider_used="system",
        )

    async def _handle_movement(self, intent, game_state, raw_input) -> Optional[TurnResult]:
        if not self.engine.movement_handler:
            return None
        # v5 movement_handler expects raw text string, not MovementRequest
        result = await self.engine.movement_handler.handle_movement(intent.movement_text or intent.raw_input)

        if result is None:
            return None  # No movement detected, continue to LLM

        if not result.success:
            return TurnResult(
                text=result.error_message or "Non puoi andare lì.",
                user_input=raw_input,
                turn_number=game_state.turn_count,
                provider_used="system",
            )

        old_companion = game_state.active_companion
        # v5 MovementResult uses target_location_id not new_location
        new_loc = getattr(result, "target_location_id", None) or getattr(result, "new_location", None)
        game_state.current_location = new_loc

        await self.engine.state_manager.switch_to_solo(game_state)

        # Auto-switch to companion in new location — only real companions, not NPC templates
        new_companion = None
        if self.engine.schedule_manager:
            candidate = self.engine.schedule_manager.who_is_here(
                new_loc, game_state.time_of_day
            )
            # Only switch if candidate is a proper companion (not an npc_template entry)
            if candidate and candidate in self.engine.world.companions:
                new_companion = candidate
        if new_companion:
            await self.engine.state_manager.switch_companion(new_companion, game_state)
            comp_def = self.engine.world.companions.get(new_companion)
            if comp_def and self.engine.outfit_engine and self.engine.schedule_manager:
                entry = self.engine.schedule_manager.get_entry(
                    new_companion, game_state.time_of_day
                )
                if entry:
                    self.engine.outfit_engine.apply_schedule_outfit(
                        entry.outfit, comp_def, game_state, game_state.turn_count
                    )

        game_state.turn_count += 1
        if self.engine.phase_clock:
            ev = self.engine.phase_clock.tick(game_state.turn_count)
            if ev:
                game_state.time_of_day = ev.new_phase

        await self.engine.state_memory.save_all()

        # Location image
        media_path = None
        if not self.engine.no_media and self.engine.media_pipeline:
            loc_def  = self.engine.world.locations.get(new_loc)
            loc_vis  = loc_def.visual_style if loc_def else ""
            loc_desc = loc_def.description  if loc_def else new_loc
            m = await self.engine.media_pipeline.generate_all(
                text="", visual_en=loc_vis or loc_desc, tags=[],
                location_id=new_loc,
            )
            if m:
                media_path = m.image_path

        text = result.transition_text or f"Ti sposti verso {new_loc}."
        if new_companion:
            text += f"\n\n*Qui trovi {new_companion}.*"

        return TurnResult(
            text=text, user_input=raw_input,
            image_path=media_path,
            new_location_id=new_loc,
            switched_companion=game_state.active_companion != old_companion,
            previous_companion=old_companion,
            current_companion=game_state.active_companion,
            turn_number=game_state.turn_count,
            provider_used="system",
        )

    async def _handle_farewell(self, game_state, raw_input) -> TurnResult:
        dismissed = game_state.active_companion
        comp_def  = self.engine.world.companions.get(dismissed)
        gender    = getattr(comp_def, "gender", "female") if comp_def else "female"
        art  = "la" if gender == "female" else "il"
        gone = "andata" if gender == "female" else "andato"

        text = f'*{dismissed} annuisce.* "Ci vediamo dopo."'

        if self.engine.schedule_manager:
            next_loc = self.engine.schedule_manager.get_npc_location(
                dismissed, game_state.time_of_day
            )
            if next_loc and next_loc != game_state.current_location:
                loc_def  = self.engine.world.locations.get(next_loc)
                loc_name = loc_def.name if loc_def else next_loc
                text += f"\n\n[{art.capitalize()} {dismissed} se n'è {gone} verso {loc_name}]"
                game_state.set_npc_location(dismissed, next_loc)
            else:
                text += f"\n\n[{art.capitalize()} {dismissed} se n'è {gone}]"

        game_state.companion_staying_with_player = False
        game_state.companion_invited_to_location = None
        await self.engine.state_manager.switch_to_solo(game_state)
        game_state.turn_count += 1
        await self.engine.state_memory.save_all()

        return TurnResult(
            text=text, user_input=raw_input,
            switched_companion=True,
            previous_companion=dismissed,
            current_companion=game_state.active_companion,
            turn_number=game_state.turn_count,
            provider_used="system",
        )

    async def _handle_rest(self, intent, game_state, raw_input) -> TurnResult:
        from luna.systems.phase_clock import PhaseAdvanceReason
        ev = self.engine.phase_clock.force_advance(
            PhaseAdvanceReason.REST, game_state.turn_count
        )
        game_state.time_of_day = ev.new_phase
        game_state.turn_count += 1
        await self.engine.state_memory.save_all()
        return TurnResult(
            text=f"*Ti riposi.* {ev.message}",
            user_input=raw_input,
            phase_changed=True,
            turn_number=game_state.turn_count,
            provider_used="system",
        )

    def _handle_freeze(self, intent, game_state, raw_input) -> TurnResult:
        if intent.freeze_action == "unfreeze":
            self.engine.phase_clock.unfreeze()
            msg = "▶️ Tempo sbloccato."
        else:
            self.engine.phase_clock.freeze(reason="manual", manual=True)
            msg = "⏸️ Tempo bloccato. Il turno non avanza."
        return TurnResult(
            text=msg, user_input=raw_input,
            turn_number=game_state.turn_count, provider_used="system",
        )

    def _handle_schedule_query(self, intent, game_state, raw_input) -> TurnResult:
        npc  = intent.target_npc or game_state.active_companion
        loc  = self.engine.schedule_manager.get_npc_location(npc, game_state.time_of_day) \
               if self.engine.schedule_manager else None
        entry = self.engine.schedule_manager.get_entry(npc, game_state.time_of_day) \
                if self.engine.schedule_manager else None
        activity = entry.activity if entry else ""
        loc_def  = self.engine.world.locations.get(loc or "")
        loc_name = loc_def.name if loc_def else (loc or "posizione sconosciuta")
        return TurnResult(
            text=f"📍 {npc} è a {loc_name}. {activity}".strip(),
            user_input=raw_input,
            turn_number=game_state.turn_count,
            provider_used="system",
        )

    async def _handle_remote_comm(self, intent, game_state, raw_input) -> Optional[TurnResult]:
        target = intent.target_npc
        if target:
            await self.engine.state_manager.switch_companion(target, game_state)
            self._in_remote_comm  = True
            self._remote_target   = target
        return None  # continue to LLM

    async def _handle_summon(self, intent, game_state) -> None:
        npc = intent.target_npc
        if not npc:
            return
        game_state.set_npc_location(npc, game_state.current_location)
        game_state.companion_staying_with_player = True
        game_state.companion_invited_to_location = game_state.current_location
        await self.engine.state_manager.switch_companion(npc, game_state)
        comp_def = self.engine.world.companions.get(npc)
        if comp_def and self.engine.outfit_engine and self.engine.schedule_manager:
            entry = self.engine.schedule_manager.get_entry(npc, game_state.time_of_day)
            if entry:
                # respect_modifications=True: summon doesn't override existing outfit state
                self.engine.outfit_engine.apply_schedule_outfit(
                    entry.outfit, comp_def, game_state, game_state.turn_count,
                    respect_modifications=True,
                )

    def _handle_intimate_scene(self, intent, game_state) -> None:
        if self.engine.phase_clock:
            self.engine.phase_clock.freeze(reason="intimate_scene", manual=False)
        game_state.companion_staying_with_player = True
        game_state.companion_invited_to_location = game_state.current_location
        logger.info(
            "[Orchestrator] Intimate scene (intensity=%s) — time frozen",
            intent.intimate_intensity,
        )

    async def _handle_outfit_major(self, intent, game_state) -> None:
        if self.engine.outfit_modifier:
            try:
                # FIX: Use intent.description (not outfit_description)
                outfit_desc = getattr(intent, 'description', None) or getattr(intent, 'outfit_description', '')
                modified, is_major, desc = self.engine.outfit_modifier.process_turn(
                    outfit_desc, game_state,
                    self.engine.world.companions.get(game_state.active_companion),
                )
                if is_major and desc:
                    await self.engine.outfit_modifier.apply_major_change(
                        game_state, desc, self.engine.llm_manager
                    )
            except Exception as e:
                logger.warning("[Orchestrator] Outfit major failed: %s", e)

    async def _handle_invitation(self, intent, game_state) -> None:
        if self.engine.invitation_manager:
            try:
                self.engine.invitation_manager.register_invitation(
                    npc_name=intent.target_npc or game_state.active_companion,
                    target_location=intent.target_location or game_state.current_location,
                    arrival_time=intent.arrival_time,
                    game_state=game_state,
                )
            except Exception as e:
                logger.warning("[Orchestrator] Invitation failed: %s", e)

    async def _handle_poker_game(self, text: str, game_state: GameState) -> TurnResult:
        """Handle poker mini-game intent."""
        logger.info("[Orchestrator] Handling POKER_GAME intent")

        # Check if poker is already active
        if game_state.flags.get("poker_active"):
            # Reuse the live PokerGame instance stored on the engine.
            # from_dict() rebuilds stacks but loses the current hand state
            # (hole cards, board, pots, street) — so we NEVER recreate mid-game.
            poker: PokerGame = getattr(self.engine, "_active_poker_game", None)
            if poker is None:
                # Session was loaded from disk — reconstruct best-effort
                poker_data = game_state.flags.get("poker_game", {})
                poker = PokerGame.from_dict(poker_data, self.engine)
                self.engine._active_poker_game = poker
                logger.warning("[Poker] Live instance missing — reconstructed from dict")

            return await poker.process_action(text, game_state)

        else:
            # Start new game — determine which companions to include
            available_companions = ["Luna", "Maria", "Stella"]
            requested_companions = []

            for comp in available_companions:
                if comp.lower() in text.lower():
                    requested_companions.append(comp)

            # If no specific companion mentioned, use active companion
            if not requested_companions:
                requested_companions = [game_state.active_companion]

            poker = PokerGame(
                engine=self.engine,
                companion_names=requested_companions,
                initial_stack=1000,
            )

            # Store live instance — reused every turn without rebuilding
            self.engine._active_poker_game = poker

            return await poker.start_game(game_state)

    # =========================================================================
    # Step 2: Companion switch
    # =========================================================================

    async def _handle_companion_switch(
        self, intent: Any, game_state: GameState, text: str
    ) -> Tuple[bool, Optional[str], bool]:
        """Returns (switched, old_companion, is_temporary)."""
        old = game_state.active_companion

        # End remote comm on farewell
        if self._in_remote_comm and intent.primary == IntentType.FAREWELL:
            await self.engine.state_manager.switch_to_solo(game_state)
            self._in_remote_comm = False
            self._remote_target  = None
            return True, old, False

        # Auto-detect NPC mention (v7: more conservative)
        # Only switch if user explicitly wants to interact, not just mentions NPC
        if self.engine.npc_detector:
            mentioned = self.engine.npc_detector.detect(text, game_state)
            if mentioned and mentioned != old:
                # Check if this is a real switch intent or just narrative mention
                lower = text.lower().strip()
                word_count = len(lower.split())
                
                # Skip if roleplay text (* or " at start)
                is_roleplay = lower.startswith('*') or lower.startswith('"')
                
                # Skip if too long (likely narrative, not command)
                is_too_long = word_count > 10
                
                # Skip if passive observation words present
                passive_words = ['vedo', 'noto', 'osservo', 'guardando', 'vedendo',
                                'watch', 'look', 'see', 'observing']
                has_passive = any(w in lower for w in passive_words)

                # Require active approach/interaction words for short commands
                active_words = ['vado', 'parlo', 'approccio', 'incontro', 'cerco', 'chiamo',
                               'ascolto', 'sento', 'chiedo', 'rispondo', 'guardo',
                               'go', 'talk', 'approach', 'meet', 'find', 'call', 'listen', 'ask']
                has_active = any(w in lower for w in active_words)

                # Se l'active è un NPC temporaneo e si menziona un companion,
                # ignora i limiti di lunghezza e passività — switch sempre permesso
                in_solo = (old == _SOLO_COMPANION)
                old_is_npc = (
                    self.engine.world.npc_templates.get(old) is not None
                    and self.engine.world.companions.get(old) is None
                )

                if old_is_npc:
                    # Con NPC attivo: basta che il companion sia menzionato
                    should_switch = not is_roleplay
                else:
                    # Logica conservativa standard
                    should_switch = not is_roleplay and not is_too_long and not has_passive
                    if word_count <= 5 and not has_active and not in_solo:
                        should_switch = False
                
                if should_switch:
                    comp_def = self.engine.world.companions.get(mentioned)
                    is_temp  = getattr(comp_def, "is_temporary", False) if comp_def else False
                    await self.engine.state_manager.switch_companion(mentioned, game_state)
                    if comp_def and not is_temp and self.engine.outfit_engine and self.engine.schedule_manager:
                        entry = self.engine.schedule_manager.get_entry(
                            mentioned, game_state.time_of_day
                        )
                        if entry:
                            # respect_modifications=True: don't reset nakedness/LLM changes on re-focus
                            self.engine.outfit_engine.apply_schedule_outfit(
                                entry.outfit, comp_def, game_state, game_state.turn_count,
                                respect_modifications=True,
                            )
                    return True, old, is_temp
                else:
                    # Log why we skipped (for debugging)
                    logger.debug("[CompanionSwitch] Skipped auto-switch to %s: roleplay=%s, long=%s, passive=%s",
                                mentioned, is_roleplay, is_too_long, has_passive)

        # Check NPC templates (segretaria, preside, bidello, etc.)
        npc_template = self._detect_npc_template(text)
        if npc_template and npc_template != old:
            await self._activate_npc_template(npc_template, game_state)
            return True, old, True  # is_temporary=True for template NPCs

        comp_def = self.engine.world.companions.get(game_state.active_companion)
        is_temp  = getattr(comp_def, "is_temporary", False) if comp_def else False
        return False, old, is_temp

    # =========================================================================
    # Step 3+4: Context building
    # =========================================================================

