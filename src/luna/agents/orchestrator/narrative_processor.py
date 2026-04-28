"""Luna RPG — Narrative Processor Mixin.

Step 5.5 → 7.5 del turno: chiamata LLM, validazione Guardian, reazioni home scene,
aggiornamento stall counter, post-turn WorldSimulator update.
"""
from __future__ import annotations

import logging

from luna.core.models import IntentType

from .turn_context import TurnContext

logger = logging.getLogger(__name__)


class NarrativeProcessorMixin:

    async def _phase_narrative(self, ctx: TurnContext) -> TurnContext:
        game_state = ctx.game_state

        # ── Step 5.5: MultiNPC expanded ───────────────────────────────────────
        ctx.multi_npc = await self._run_multi_npc(ctx)

        # ── Step 6: NarrativeEngine LLM call ─────────────────────────────────
        if game_state.flags.pop("_quest_auto_open", False):
            ctx.text = "[Scene begins. The companion speaks first, unprompted, setting the scene and mood.]"
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

        # ── Step 7.2: Home scene secondary reactions ──────────────────────────
        # Usa il callback diretto — NON aggiunge a ctx.multi_npc per non svuotare
        # la visualizzazione di result.text (che è la risposta principale dell'attiva).
        home_secondary = getattr(ctx, "home_mode_secondary", [])
        if home_secondary and ctx.narrative and ctx.narrative.text:
            from luna.systems.home_scene_orchestrator import HomeSceneOrchestrator
            home_orch = HomeSceneOrchestrator(engine=self.engine)
            for secondary_npc in home_secondary[:1]:  # max 1 reazione per turno
                primary_text = ctx.narrative.text
                primary_speaker = game_state.active_companion
                # Se la companion primaria ha nominato esplicitamente quella secondaria,
                # genera una risposta sostanziale (2-3 frasi) invece del one-liner.
                secondary_directly_addressed = secondary_npc.lower() in primary_text.lower()
                if secondary_directly_addressed:
                    reaction_prompt = home_orch.build_addressed_response_prompt(
                        responding_npc=secondary_npc,
                        addressing_npc=primary_speaker,
                        addressing_text=primary_text,
                        player_input=ctx.text,
                        game_state=game_state,
                        context=ctx.context,
                    )
                else:
                    reaction_prompt = home_orch.build_reaction_prompt(
                        reacting_npc=secondary_npc,
                        primary_text=primary_text,
                        primary_speaker=primary_speaker,
                        player_input=ctx.text,
                        game_state=game_state,
                        context=ctx.context,
                    )
                try:
                    reaction_resp, _ = await self.engine.llm_manager.generate(
                        system_prompt=reaction_prompt,
                        user_input="",
                        history=[],
                        json_mode=False,
                        companion_name=secondary_npc,
                    )
                    reaction_text = (
                        reaction_resp.text if reaction_resp and hasattr(reaction_resp, "text")
                        else (reaction_resp if isinstance(reaction_resp, str) else "")
                    )
                    if reaction_text and hasattr(self.engine, "_ui_intermediate_message_callback"):
                        await self.engine._ui_intermediate_message_callback(
                            text=reaction_text,
                            speaker=secondary_npc,
                            turn_number=game_state.turn_count,
                            visual_en="",
                            tags_en=[],
                        )
                except Exception as e:
                    logger.warning("[HomeScene] Secondary reaction failed for %s: %s", secondary_npc, e)

        # ── Step 7.3: Detect mention reaction candidate ───────────────────────
        # Rileva se un companion presente è nominato nel testo di Luna.
        # L'esecuzione effettiva (testo + immagini nell'ordine corretto) avviene
        # in Step 11.5 di _phase_finalize, dopo che l'immagine di Luna è pronta.
        if (
            ctx.narrative
            and ctx.narrative.text
            and not home_secondary
            and not (ctx.multi_npc and ctx.multi_npc.skip_standard_llm)
            and ctx.present_npcs
        ):
            narrative_lower = ctx.narrative.text.lower()
            active = game_state.active_companion
            for present_npc in ctx.present_npcs:
                if present_npc == active:
                    continue
                npc_def = (
                    self.engine.world.companions.get(present_npc)
                    or self.engine.world.npc_templates.get(present_npc)
                )
                npc_name = getattr(npc_def, "name", present_npc) if npc_def else present_npc
                npc_name_lower = npc_name.lower()
                npc_id_lower = present_npc.lower()
                if npc_name_lower not in narrative_lower and npc_id_lower not in narrative_lower:
                    continue
                # Skip if LLM already wrote the companion inline (e.g. *Stella si ricompone*)
                # — that means the scene already contains their action/dialogue.
                if (
                    f"*{npc_name_lower}" in narrative_lower
                    or f"* {npc_name_lower}" in narrative_lower
                    or f"*{npc_id_lower}" in narrative_lower
                    or f"* {npc_id_lower}" in narrative_lower
                    or f'"{npc_name_lower}' in narrative_lower
                    or f'«{npc_name_lower}' in narrative_lower
                ):
                    continue
                ctx.mention_reaction_npc = present_npc
                break  # max 1 companion per turno

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
