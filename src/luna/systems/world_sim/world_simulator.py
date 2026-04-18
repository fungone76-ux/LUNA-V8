"""World Simulator — coordinator. Orchestrates turn simulation."""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from luna.systems.npc_mind import (
    EmotionType, GoalType, NPCGoal, NPCMindManager,
    NeedProfile, GoalTemplate, NPCRelationship,
)
from luna.systems.world_sim.models import (
    AmbientDetail, NPCScenePresence, TurnDirective,
)
from luna.systems.world_sim.turn_director import TurnDirector
from luna.systems.world_sim.ambient_engine import AmbientEngine

if TYPE_CHECKING:
    from luna.core.models import GameState, WorldDefinition
    from luna.systems.tension_tracker import TensionTracker

logger = logging.getLogger(__name__)


class WorldSimulator:
    """Simulates the world each turn. Produces TurnDirective."""

    AMBIENT_INTERVAL = 3
    OFF_SCREEN_CHANCE = 0.25
    NPC_APPEARANCE_CHANCE = 0.12

    def __init__(
        self,
        mind_manager: NPCMindManager,
        world: Optional["WorldDefinition"] = None,
        tension_tracker: Optional["TensionTracker"] = None,
        story_director: Optional[Any] = None,
    ) -> None:
        self.mind_manager = mind_manager
        self.world = world
        self.tension_tracker = tension_tracker
        self.story_director = story_director
        self._last_ambient_turn = 0
        self._turn_director = TurnDirector(mind_manager)
        self._ambient_engine = AmbientEngine(world)

    # Backward-compat properties (engine.py accesses these directly)
    @property
    def _turns_since_event(self) -> int:
        return self._turn_director._turns_since_event

    @_turns_since_event.setter
    def _turns_since_event(self, value: int) -> None:
        self._turn_director._turns_since_event = value

    # =========================================================================
    # Main tick
    # =========================================================================

    def tick(
        self,
        player_input: str,
        intent: Any,
        game_state: "GameState",
    ) -> TurnDirective:
        turn = game_state.turn_count
        active = game_state.active_companion
        directive = TurnDirective()

        # 1. Tick all NPC minds
        self.mind_manager.tick_all(active, game_state, turn)

        # 1b. v8: Emotional state TTL — decay forced states back to "default"
        self._tick_emotional_state_ttl(game_state, turn)

        # 2. Simulate off-screen NPC↔NPC interactions
        self._simulate_off_screen(game_state, turn)

        # 3. Scene presence
        directive.npcs_in_scene = self._build_scene_presence(game_state)

        # 4. Tension tracker narrative pressure
        if self.tension_tracker:
            directive.narrative_pressure = self.tension_tracker.get_pressure_hint(game_state, turn)

        # 5. Ambient details
        if turn - self._last_ambient_turn >= self.AMBIENT_INTERVAL:
            directive.ambient = self._ambient_engine.generate(game_state, turn, self.mind_manager)
            if directive.ambient:
                self._last_ambient_turn = turn

        # 5.5 Story beats → NPC goals
        if self.story_director:
            self._process_story_beats(game_state, turn)

        # 6. Decide who drives the turn
        directive.driver, directive.npc_initiative = self._turn_director.decide(
            player_input, intent, game_state, turn
        )
        self._turn_director.increment_event_counter()

        # 7. Inject active NPC mind context
        active_mind = self.mind_manager.get(active)
        if active_mind:
            mind_ctx = active_mind.get_context_for_llm()
            if mind_ctx:
                directive.injected_context = mind_ctx

        # 8. Director needed?
        directive.needs_director = self._turn_director.should_use_director(directive)

        return directive

    # =========================================================================
    # v8: Emotional state TTL
    # =========================================================================

    # How many turns each forced emotional state lasts before reverting to "default".
    # "default" itself never expires (TTL = 0 means permanent).
    _EMOTIONAL_STATE_TTL: Dict[str, int] = {
        "default":    0,    # permanent
        "intimate":   8,
        "seductive":  10,
        "vulnerable": 6,
        "angry":      5,
        "sad":        12,
        "excited":    6,
        "cold":       10,
        "nervous":    7,
        "playful":    8,
    }

    def _tick_emotional_state_ttl(self, game_state: Any, turn: int) -> None:
        """Revert forced emotional states to 'default' after their TTL expires."""
        for npc_id, npc_state in game_state.npc_states.items():
            state = npc_state.emotional_state
            if state == "default":
                continue
            ttl = self._EMOTIONAL_STATE_TTL.get(state, 8)  # unknown states: 8 turns
            if ttl == 0:
                continue  # permanent
            age = turn - npc_state.emotional_state_set_turn
            if age >= ttl:
                logger.debug(
                    "[WorldSim] %s emotional_state '%s' expired (age %d ≥ ttl %d) → default",
                    npc_id, state, age, ttl,
                )
                game_state.npc_states[npc_id] = npc_state.model_copy(
                    update={"emotional_state": "default", "emotional_state_set_turn": 0}
                )

    # =========================================================================
    # Post-turn update
    # =========================================================================

    def post_turn_update(
        self,
        active_npc: str,
        player_input: str,
        narrative_text: str,
        game_state: Any,
        driver: str = "player",
    ) -> None:
        mind = self.mind_manager.get(active_npc)
        if not mind:
            return

        # Mark off-screen events as told if they appeared in narrative
        for event in mind.off_screen_log:
            if not event.told_to_player and event.description:
                keywords = event.description.lower().split()[:3]
                if any(kw in narrative_text.lower() for kw in keywords if len(kw) > 3):
                    event.told_to_player = True

        if driver in ("npc", "world_event"):
            mind.turns_since_last_initiative = 0
            if mind.current_goal:
                mind.current_goal.urgency = max(0.0, mind.current_goal.urgency - 0.3)
                if mind.current_goal.urgency < 0.1:
                    mind.goal_history.append(mind.current_goal.description)
                    mind.current_goal = None
        else:
            mind.turns_since_last_initiative += 1

    # =========================================================================
    # Off-screen simulation
    # =========================================================================

    def _simulate_off_screen(self, game_state: Any, turn: int) -> None:
        active = game_state.active_companion
        player_loc = game_state.current_location
        npc_locations: Dict[str, List[str]] = {}
        for npc_id, mind in self.mind_manager.minds.items():
            if npc_id == active:
                continue
            npc_loc = game_state.npc_locations.get(npc_id, "unknown")

            # Metodo 7: aggiorna mood e simula attività off-screen per ogni NPC
            self._update_npc_mood_from_needs(npc_id, mind, game_state, turn)
            if turn % 3 == 0:  # ogni 3 turni per non saturare l'off_screen_log
                self._simulate_npc_activity(npc_id, mind, npc_loc, game_state, turn)

            if npc_loc == player_loc:
                continue
            npc_locations.setdefault(npc_loc, []).append(npc_id)

        for loc, npcs in npc_locations.items():
            if len(npcs) < 2:
                continue
            for i, npc_a in enumerate(npcs):
                for npc_b in npcs[i + 1:]:
                    if random.random() > self.OFF_SCREEN_CHANCE:
                        continue
                    self._npc_interaction(npc_a, npc_b, turn)

    def _update_npc_mood_from_needs(
        self,
        npc_id: str,
        mind: Any,
        game_state: Any,
        turn: int,
    ) -> None:
        """Metodo 7: aggiorna emotional_state NPC in base ai needs accumulati.

        Viene chiamato ogni turno per tutti gli NPC non attivi.
        Non sovrascrive stati forzati dalla narrativa (es. "seductive").
        """
        npc_state = game_state.npc_states.get(npc_id)
        if not npc_state:
            return

        current_state = npc_state.emotional_state
        # Non sovrascrivere stati forzati/narrativi significativi
        _PROTECTED_STATES = {
            "seductive", "nervous_but_happy", "flustered",
            "grateful", "devoted", "surprised",
        }
        if current_state in _PROTECTED_STATES:
            return

        social_need  = mind.needs.get("social", 0.0)
        rest_need    = mind.needs.get("rest", 0.0)
        intimacy_need = mind.needs.get("intimacy", 0.0)

        # Determina nuovo stato in base al need dominante
        new_state = None
        if social_need > 0.75 and npc_id in ("luna", "stella", "maria"):
            new_state = "lonely"
        elif rest_need > 0.80:
            new_state = "tired"
        elif intimacy_need > 0.75 and npc_id in ("luna", "maria"):
            new_state = "vulnerable"

        if new_state and new_state != current_state:
            game_state.npc_states[npc_id] = npc_state.model_copy(
                update={"emotional_state": new_state, "emotional_state_set_turn": turn}
            )
            logger.debug(
                "[WorldSim] %s mood → '%s' (social=%.2f rest=%.2f intimacy=%.2f)",
                npc_id, new_state, social_need, rest_need, intimacy_need
            )

    def _simulate_npc_activity(
        self,
        npc_id: str,
        mind: Any,
        location: str,
        game_state: Any,
        turn: int,
    ) -> None:
        """Metodo 7: simula attività specifica dell'NPC off-screen.

        Aggiunge voci all'off_screen_log che l'LLM userà per costruire
        risposte organiche quando il giocatore visita l'NPC.
        """
        time_str = (
            game_state.time_of_day.value
            if hasattr(game_state.time_of_day, "value")
            else str(game_state.time_of_day)
        )

        if npc_id == "luna":
            activity_map = {
                "Morning":   "stava preparando la lezione",
                "Afternoon": "correggeva compiti dei suoi studenti",
                "Evening":   "era ancora in ufficio da sola, correggendo compiti",
                "Night":     "stava finalmente tornando a casa",
            }
            activity = activity_map.get(time_str)
            if activity:
                # Importanza alta la sera (scena emotiva potenziale)
                importance = 0.6 if time_str == "Evening" else 0.25
                mind.add_off_screen(activity, turn, importance=importance)

        elif npc_id == "stella":
            activity_map = {
                "Morning":   "era già in classe, in anticipo per una volta",
                "Afternoon": "stava studiando in biblioteca con le cuffie",
                "Evening":   "girava per la scuola dopo le lezioni",
                "Night":     "mandava messaggi alle amiche",
            }
            activity = activity_map.get(time_str)
            if activity:
                mind.add_off_screen(activity, turn, importance=0.2)

        elif npc_id == "maria":
            area_map = {
                "Morning":   "puliva l'atrio e i corridoi del piano terra",
                "Afternoon": "riordinava le aule dopo le lezioni",
                "Evening":   "passava lo straccio negli uffici dei professori",
                "Night":     "finiva il turno, stanca",
            }
            area = area_map.get(time_str)
            if area:
                mind.add_off_screen(area, turn, importance=0.2)

    def _npc_interaction(self, npc_a: str, npc_b: str, turn: int) -> None:
        mind_a = self.mind_manager.get(npc_a)
        mind_b = self.mind_manager.get(npc_b)
        if not mind_a or not mind_b:
            return
        rel_a = mind_a.relationships.get(npc_b)
        rel_b = mind_b.relationships.get(npc_a)
        if not rel_a and not rel_b:
            return
        tension = max(
            rel_a.tension if rel_a else 0,
            rel_b.tension if rel_b else 0,
        )
        if tension > 0.6 and random.random() < 0.4:
            mind_a.add_off_screen(f"ha avuto uno scambio teso con {mind_b.name}", turn,
                                  importance=0.6, related_npc=npc_b, emotional_impact="frustrated")
            mind_b.add_off_screen(f"ha avuto uno scambio teso con {mind_a.name}", turn,
                                  importance=0.5, related_npc=npc_a, emotional_impact="frustrated")
        elif tension > 0.3 and random.random() < 0.3:
            mind_a.add_off_screen(f"ha chiacchierato con {mind_b.name}", turn,
                                  importance=0.3, related_npc=npc_b)
        elif random.random() < 0.15:
            mind_a.add_off_screen(f"ha incrociato {mind_b.name} in corridoio", turn,
                                  importance=0.1, related_npc=npc_b)
        logger.debug("[WorldSim] Off-screen: %s ↔ %s (tension=%.1f)", npc_a, npc_b, tension)

    # =========================================================================
    # Scene presence
    # =========================================================================

    def _build_scene_presence(self, game_state: Any) -> List[NPCScenePresence]:
        result = []
        player_loc = game_state.current_location
        active = game_state.active_companion
        active_mind = self.mind_manager.get(active)
        if active_mind:
            result.append(NPCScenePresence(npc_id=active, npc_name=active_mind.name, role="active"))

        for npc_id, mind in self.mind_manager.minds.items():
            if npc_id == active:
                continue
            npc_loc = game_state.npc_locations.get(npc_id)
            if npc_loc == player_loc:
                result.append(NPCScenePresence(npc_id=npc_id, npc_name=mind.name, role="present"))

        if self.world and self.world.npc_templates:
            time_str = (
                game_state.time_of_day.value
                if hasattr(game_state.time_of_day, "value")
                else str(game_state.time_of_day)
            )
            for tmpl_id, tmpl_data in self.world.npc_templates.items():
                if not isinstance(tmpl_data, dict):
                    continue
                if tmpl_id in [n.npc_id for n in result]:
                    continue
                spawn_locs = tmpl_data.get("spawn_locations", [])
                if player_loc not in spawn_locs:
                    continue
                tmpl_schedule = tmpl_data.get("schedule", {})
                if tmpl_schedule and time_str not in tmpl_schedule:
                    continue
                tmpl_mind = self.mind_manager.get(tmpl_id)
                has_goal = (
                    tmpl_mind and tmpl_mind.current_goal
                    and tmpl_mind.current_goal.urgency >= 0.5
                )
                if has_goal or random.random() < self.NPC_APPEARANCE_CHANCE:
                    name = tmpl_data.get("name", tmpl_id)
                    doing = tmpl_schedule.get(time_str, "")
                    result.append(NPCScenePresence(
                        npc_id=tmpl_id, npc_name=name,
                        role="passing_by" if not has_goal else "present",
                        doing=doing,
                    ))
        return result

    # =========================================================================
    # Story beats integration
    # =========================================================================

    def _process_story_beats(self, game_state: "GameState", turn: int) -> None:
        if not self.story_director:
            return
        active_npc = game_state.active_companion
        if not active_npc:
            return
        mind = self.mind_manager.get(active_npc)
        if not mind:
            return
        beat_result = self.story_director.get_active_instruction(game_state)
        if not beat_result:
            return
        beat, instruction = beat_result
        if not beat:
            return
        beat_goal_id = f"beat_{beat.id}"
        if mind.current_goal and mind.current_goal.source == beat_goal_id:
            return
        if beat.id in self.story_director._completed_beats:
            return
        goal_type = GoalType.EMOTIONAL
        if beat.tone and "confront" in beat.tone.lower():
            goal_type = GoalType.CONFRONTATION
        elif beat.tone and "passionate" in beat.tone.lower():
            goal_type = GoalType.PROPOSAL
        beat_goal = NPCGoal(
            description=beat.description,
            goal_type=goal_type,
            target="player",
            urgency=0.8,
            max_urgency=1.0,
            growth_rate=0.1,
            created_at_turn=turn,
            context=(
                f"Story beat: {beat.id}. "
                f"Required elements: {', '.join(beat.required_elements) if beat.required_elements else 'narrative progression'}. "
                f"Tone: {beat.tone}"
            ),
            source=beat_goal_id,
        )
        if beat.tone:
            tone = beat.tone.lower()
            if "vulnerable" in tone:
                mind.add_emotion(EmotionType.VULNERABLE, intensity=0.7, cause=beat.description, turn=turn)
            elif "passionate" in tone:
                mind.add_emotion(EmotionType.FLIRTY, intensity=0.8, cause=beat.description, turn=turn)
            elif "dramatic" in tone:
                mind.add_emotion(EmotionType.NERVOUS, intensity=0.6, cause=beat.description, turn=turn)
            elif "conflicted" in tone:
                mind.add_emotion(EmotionType.FRUSTRATED, intensity=0.5, cause=beat.description, turn=turn)
        if not mind.current_goal or mind.current_goal.urgency < 0.6:
            mind.current_goal = beat_goal
            logger.info("[WorldSim] Story beat '%s' → goal for %s: %s",
                        beat.id, active_npc, beat.description[:50])
        else:
            mind.add_unspoken(
                content=f"Deve affrontare: {beat.description}",
                turn=turn, weight=0.6, trigger="when the moment is right",
            )

    # =========================================================================
    # World initialization
    # =========================================================================

    def initialize_from_world(self, world: "WorldDefinition", game_state: "GameState") -> None:
        self.world = world
        self._ambient_engine.world = world

        for comp_name, comp_def in world.companions.items():
            if comp_name == "_solo_":
                continue
            mind = self.mind_manager.get_or_create(comp_name, name=comp_name, is_companion=True)
            if hasattr(comp_def, "needs_profile") and comp_def.needs_profile:
                profile = comp_def.needs_profile
                if isinstance(profile, dict):
                    mind.need_profile = NeedProfile(
                        social=profile.get("social", {}).get("base_rate", 0.03),
                        recognition=profile.get("recognition", {}).get("base_rate", 0.02),
                        intimacy=profile.get("intimacy", {}).get("base_rate", 0.02),
                        safety=profile.get("safety", {}).get("base_rate", 0.01),
                        rest=profile.get("rest", {}).get("base_rate", 0.015),
                        purpose=profile.get("purpose", {}).get("base_rate", 0.02),
                    )
            if hasattr(comp_def, "goal_templates") and comp_def.goal_templates:
                for tmpl in comp_def.goal_templates:
                    if isinstance(tmpl, dict):
                        mind.goal_templates.append(GoalTemplate(
                            goal_id=tmpl.get("id", ""),
                            description=tmpl.get("goal", ""),
                            goal_type=GoalType(tmpl.get("goal_type", "social")),
                            target=tmpl.get("target", "player"),
                            urgency_start=tmpl.get("urgency_start", 0.3),
                            growth_rate=tmpl.get("growth_rate", 0.05),
                            context=tmpl.get("context", ""),
                            conditions=tmpl.get("conditions", {}),
                        ))
            if hasattr(comp_def, "npc_relationships") and comp_def.npc_relationships:
                for target_npc, rel_data in comp_def.npc_relationships.items():
                    if isinstance(rel_data, dict):
                        mind.relationships[target_npc] = NPCRelationship(
                            target_npc=target_npc,
                            rel_type=rel_data.get("type", ""),
                            description=rel_data.get("description", ""),
                            tension=rel_data.get("base_tension", 0.0),
                            base_tension=rel_data.get("base_tension", 0.0),
                        )

        if world.npc_templates:
            for tmpl_id, tmpl_data in world.npc_templates.items():
                if not isinstance(tmpl_data, dict):
                    continue
                if not tmpl_data.get("recurring", False):
                    continue
                mind = self.mind_manager.get_or_create(
                    tmpl_id, name=tmpl_data.get("name", tmpl_id), is_companion=False,
                )
                mind.needs = {"social": 0.1, "purpose": 0.3}
                mind.need_profile = NeedProfile(
                    social=0.01, recognition=0.0, intimacy=0.0,
                    safety=0.0, rest=0.0, purpose=0.015,
                )
                if "npc_relationships" in tmpl_data:
                    for target_npc, rel_data in tmpl_data["npc_relationships"].items():
                        if isinstance(rel_data, dict):
                            mind.relationships[target_npc] = NPCRelationship(
                                target_npc=target_npc,
                                rel_type=rel_data.get("type", ""),
                                description=rel_data.get("description_it", ""),
                                tension=rel_data.get("base_tension", 0.0),
                                base_tension=rel_data.get("base_tension", 0.0),
                            )

        logger.info("[WorldSimulator] Initialized %d minds (%d companions, %d templates)",
                    len(self.mind_manager.minds),
                    sum(1 for m in self.mind_manager.minds.values() if m.is_companion),
                    sum(1 for m in self.mind_manager.minds.values() if not m.is_companion))

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        return {
            "minds": self.mind_manager.to_dict(),
            "turns_since_event": self._turn_director._turns_since_event,
            "last_ambient_turn": self._last_ambient_turn,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        self.mind_manager.from_dict(data.get("minds", {}))
        self._turn_director._turns_since_event = data.get("turns_since_event", 0)
        self._last_ambient_turn = data.get("last_ambient_turn", 0)
