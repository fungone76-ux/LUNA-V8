"""Luna RPG — Agenda Handler Mixin.

Step 2.9 del turno: seleziona e inietta la mossa GM.
Popola ctx.gm_agenda_context, ctx.gm_move_name, ctx.narrative_compass.
"""
from __future__ import annotations

import logging
from typing import Optional

from .turn_context import TurnContext

logger = logging.getLogger(__name__)
_SOLO_COMPANION = "_solo_"


class AgendaHandlerMixin:

    async def _run_gm_agenda(self, ctx: TurnContext) -> TurnContext:
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

            affinity    = game_state.affinity.get(active, 0)
            last_move   = game_state.flags.get("_last_gm_move")
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
