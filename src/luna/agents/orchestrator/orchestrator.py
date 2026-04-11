"""Luna RPG v7 - Turn Orchestrator.

Coordinates 6 agents for each game turn:

Step 0:   IntentRouter — classify player input
Step 0.5: Situational interventions
Step 1:   Handle special intents (movement, farewell, rest, etc.)
Step 2:   Companion switch
Step 2.5: WorldSimulator.tick() — NPC minds, off-screen, tension ← NEW
Step 3:   DirectorAgent (if needed) — decide scene beats ← NEW
Step 4:   Pre-turn systems (personality, outfit modifier)
Step 5:   StoryDirector + QuestEngine + MultiNPC context
Step 6:   NarrativeEngine — generate text (LLM call) — enriched with directive
Step 7:   StateGuardian — validate + apply updates
Step 7.5: WorldSimulator.post_turn_update() ← NEW
Step 8:   Advance turn + phase clock
Step 9:   Save state + memory
Step 10:  VisualDirector — build SD prompt
Step 11:  MediaPipeline — generate image/audio
Step 12:  Build TurnResult

The orchestrator owns the flow. Agents do not call each other.

REFACTORED: Main class now inherits from mixins for better organization:
- IntentHandlersMixin: All _handle_* methods
- ContextBuilderMixin: _build_context, _enrich_context
- SupportMethodsMixin: _generate_farewell, _generate_media, _minimal_narrative
- StateManagerMixin: _save
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from luna.agents.guardian import StateGuardian
from luna.agents.intent_router import IntentRouter
from luna.agents.narrative import NarrativeEngine
from luna.agents.visual import VisualDirector
from luna.agents.director import DirectorAgent
from luna.core.models import (
    GameState, IntentType, NarrativeOutput,
    TurnResult, WorldDefinition,
)

# Import mixins
from .intent_handlers import IntentHandlersMixin
from .context_builder import ContextBuilderMixin
from .support import SupportMethodsMixin
from .state_manager import StateManagerMixin
from .phase_handlers import PhaseHandlersMixin
from .turn_context import TurnContext

if TYPE_CHECKING:
    from luna.core.engine import GameEngine

logger = logging.getLogger(__name__)

_SOLO_COMPANION = "_solo_"


class TurnOrchestrator(
    PhaseHandlersMixin,
    IntentHandlersMixin,
    ContextBuilderMixin,
    SupportMethodsMixin,
    StateManagerMixin,
):
    """Executes the complete game turn loop.

    Receives GameEngine reference for access to all subsystems.
    Owns the control flow — delegates work to agents and systems.

    v7: Added WorldSimulator (step 2.5) and DirectorAgent (step 3).

    REFACTORED: execute() è una pipeline di 5 fasi definite in phase_handlers.py.
    I tre blocchi "mostro" (GM Agenda, MultiNPC, PhaseClock) sono helper privati.
    Lo stato del turno viaggia esplicito in TurnContext (turn_context.py).
    """

    def __init__(self, engine: "GameEngine") -> None:
        self.engine  = engine
        self._intent_router   = IntentRouter(engine.world)
        self._narrative       = NarrativeEngine(
            engine.world,
            voice_builder=getattr(engine, 'character_voice_builder', None),
            personality_engine=getattr(engine, 'personality_engine', None),
        )
        self._visual          = VisualDirector(engine.world)
        self._guardian        = StateGuardian(engine.world)
        self._director        = DirectorAgent()

        # Remote communication state
        self._in_remote_comm  = False
        self._remote_target:  Optional[str] = None
        self._npc_location_hint: Optional[str] = None

        # Schedule agent — narrative time management
        self._schedule_agent: Optional[Any] = None
        self._init_schedule_agent()

        # QuestDirector — impression-based quest enrichment
        self._quest_director: Optional[Any] = None
        self._init_quest_director()

        # InitiativeAgent — spontaneous NPC initiatives
        self._initiative_agent: Optional[Any] = None
        self._init_initiative_agent()

    # =========================================================================
    # QuestDirector + InitiativeAgent init
    # =========================================================================

    def _init_quest_director(self) -> None:
        try:
            from luna.agents.quest_director import QuestDirector
            self._quest_director = QuestDirector(
                world=self.engine.world,
                quest_engine=self.engine.quest_engine,
                personality_engine=self.engine.personality_engine,
            )
            logger.info("[Orchestrator] QuestDirector initialized")
        except Exception as e:
            logger.warning("[Orchestrator] QuestDirector init failed: %s", e)

    def _init_initiative_agent(self) -> None:
        try:
            from luna.agents.initiative_agent import InitiativeAgent
            self._initiative_agent = InitiativeAgent(world=self.engine.world)
            logger.info("[Orchestrator] InitiativeAgent initialized — %d initiatives",
                        len(self._initiative_agent._definitions))
        except Exception as e:
            logger.warning("[Orchestrator] InitiativeAgent init failed: %s", e)

    # =========================================================================
    # Schedule agent init
    # =========================================================================

    def _init_schedule_agent(self) -> None:
        """Initialize ScheduleAgent if schedule_manager is available."""
        try:
            from luna.agents.schedule_agent import ScheduleAgent
            if self.engine.schedule_manager:
                self._schedule_agent = ScheduleAgent(
                    world=self.engine.world,
                    schedule_manager=self.engine.schedule_manager,
                    turns_per_phase=8,
                )
                logger.info("[Orchestrator] ScheduleAgent initialized")
        except Exception as e:
            logger.warning("[Orchestrator] ScheduleAgent init failed: %s", e)

    # =========================================================================
    # Main entry point - execute() and _finalize_turn()
    # These methods are kept in this file as they are the core orchestration logic
    # =========================================================================
    
    async def execute(self, user_input: str) -> TurnResult:
        """Execute one complete game turn.

        Pipeline:
          _phase_pre_turn    → Steps 0, 0.5, 0.7, 1, 2
          _phase_world_state → Steps 2.5, 2.7, 2.9, 2.8, 3
          _phase_context     → Steps 4, 5
          _phase_narrative   → Steps 5.5, 6, 6c, 7, 7.5
          _phase_finalize    → Steps 8, 9, 10
          _build_result      → Step 12

        Tutta la logica delle fasi è in phase_handlers.py.
        Lo stato del turno viaggia in TurnContext (turn_context.py).
        """
        text = user_input.strip()
        if not text:
            return TurnResult(
                text="[Nessun input ricevuto]",
                user_input=user_input,
                turn_number=self.engine.state.turn_count,
                provider_used="system",
            )

        game_state = self.engine.state
        turn_logger = getattr(self.engine, "turn_logger", None)
        if turn_logger:
            try:
                turn_logger.start_turn(game_state.turn_count, text, game_state)
            except Exception as log_err:
                logger.warning("[TurnLogger] start failed: %s", log_err)
                turn_logger = None

        ctx = TurnContext(
            user_input=user_input,
            game_state=game_state,
            text=text,
            turn_logger=turn_logger,
        )

        logger.info(
            "=== TURN %d | companion=%s | location=%s ===",
            ctx.game_state.turn_count,
            ctx.game_state.active_companion,
            ctx.game_state.current_location,
        )

        ctx = await self._phase_pre_turn(ctx)
        if ctx.early_return is not None:
            return self._build_result(ctx)

        ctx = await self._phase_world_state(ctx)
        ctx = await self._phase_context(ctx)
        ctx = await self._phase_narrative(ctx)
        ctx = await self._phase_finalize(ctx)
        return self._build_result(ctx)

