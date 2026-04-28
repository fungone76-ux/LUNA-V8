"""Luna RPG — Time Manager Mixin.

Gestione deterministica dell'orologio di gioco e delle fasi del giorno.

_apply_phase_event    — applica un cambio di fase: riposiziona NPC, genera farewell.
_run_phase_clock      — Step 8: tick automatico del clock ogni N turni.
execute_phase_advance — Entry point UI "Avanza Fase" (salta LLM e media).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from luna.core.models import TurnResult

from .turn_context import TurnContext

logger = logging.getLogger(__name__)
_SOLO_COMPANION = "_solo_"


class TimeManagerMixin:

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
        game_state.clear_departures()  # reset departures: new phase, new presence

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

        # ── Se il companion attivo si sposta → farewell + switch to solo ──────
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
        """Step 8 — Phase clock automatico.

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

        if ctx.narrative:
            await self._save(ctx.game_state, "", ctx.narrative, {})

        return self._build_result(ctx)
