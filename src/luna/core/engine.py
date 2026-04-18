"""Luna RPG v6 - Game Engine.

Pure coordinator. Owns references to all subsystems.
Contains ZERO business logic — delegates everything.

Lifecycle:
    engine = GameEngine(world_id, companion)
    await engine.initialize()           # new game
    await engine.load_session(id)       # load saved game
    result = await engine.process_turn(user_input)
    await engine.shutdown()
"""
from __future__ import annotations

import logging
import os
import traceback
from typing import Any, Dict, List, Optional

from luna.core.models import GameState, TurnResult, WorldDefinition
from luna.systems.gameplay_manager import GameplayManager

from luna.core.config import get_settings
from luna.core.database import get_db_manager, DatabaseManager

logger = logging.getLogger(__name__)


class GameEngine:
    """Orchestrates all Luna RPG v6 systems.

    Responsibilities:
    - Initialize and wire all subsystems
    - Provide clean API to the UI layer
    - Delegate turn execution to TurnOrchestrator
    - Hold NO business logic
    """

    def __init__(
        self,
        world_id: str,
        companion: str,
        no_media: bool = False,
    ) -> None:
        self.world_id  = world_id
        self.companion = companion
        self.no_media  = no_media or os.environ.get("LUNA_DEBUG_NO_MEDIA") == "1"

        self.settings = get_settings()

        # Load world
        self.world = self._load_world(world_id)
        if not self.world:
            raise ValueError(f"World not found: {world_id}")

        # Core
        self.db: DatabaseManager = get_db_manager(self.settings)

        # All subsystems
        self.state_manager            = None
        self.state_memory             = None
        self.memory_manager           = None
        self.quest_engine             = None
        self.personality_engine       = None
        self.story_director           = None
        self.location_manager         = None
        self.movement_handler         = None
        self.schedule_manager         = None
        self.npc_detector             = None
        self.affinity_calculator      = None
        self.multi_npc_manager        = None
        self.event_manager            = None
        self.outfit_engine            = None
        self.outfit_modifier          = None
        self.phase_clock              = None
        self.phase_manager            = None  # alias for UI
        self.lora_mapping             = None
        self.gameplay_manager         = None
        self.llm_manager              = None
        self.media_pipeline           = None
        # activity_system / initiative_system removed in v8 M6 (dead code)
        self.situational_intervention = None
        self.invitation_manager       = None
        self.pose_extractor           = None
        self.turn_orchestrator        = None
        self.turn_logger              = None

        # v7 new systems
        self.world_simulator          = None
        self.tension_tracker          = None
        self.npc_state                = None   # NPCStateManager

        # v8 Character Realism System
        self.presence_tracker         = None
        self.emotional_state_engine   = None
        self.character_voice_builder  = None

        # UI callbacks
        self._ui_time_change_cb: Optional[Callable] = None
        
        # V2 MultiNPC Expanded callbacks
        self._ui_intermediate_message_callback: Optional[Callable] = None
        self._show_interrupt_callback: Optional[Callable] = None
        self._ui_image_callback: Optional[Callable] = None

        # Internal
        self._initialized: bool = False
        self._session_id: Optional[int] = None
        self._last_user_input: str = ""

    # =========================================================================
    # Public API
    # =========================================================================

    async def initialize(self) -> None:
        """Create new game session."""
        if self._initialized:
            return
        await self.db.create_tables()
        self._init_systems()

        async with self.db.session() as db:
            game_state = await self.state_manager.create_new(
                db=db,
                world_id=self.world_id,
                companion=self.companion,
                companions_list=list(self.world.companions.keys()),
                player_character=self.world.player_character,
            )

        self._session_id = game_state.session_id
        await self._init_runtime_systems(game_state)
        self._initialized = True
        logger.info(
            "New game initialized: world=%s, companion=%s",
            self.world_id, self.companion,
        )

    async def load_session(self, session_id: int) -> bool:
        """Load existing game session."""
        await self.db.create_tables()
        self._init_systems()

        async with self.db.session() as db:
            game_state = await self.state_manager.load(db, session_id)

        if not game_state:
            logger.error("Session %d not found", session_id)
            return False

        self._session_id = session_id
        await self._init_runtime_systems(game_state)
        self._initialized = True
        logger.info(
            "Session %d loaded: world=%s, companion=%s, turn=%d",
            session_id, game_state.world_id,
            game_state.active_companion, game_state.turn_count,
        )
        return True

    async def process_turn(self, user_input: str) -> TurnResult:
        """Process one game turn. Main game loop entry point."""
        if not self._initialized:
            return TurnResult(
                text="[Engine not initialized]",
                turn_number=0,
                provider_used="system",
                error="not_initialized",
            )
        self._last_user_input = user_input
        return await self.turn_orchestrator.execute(user_input)

    async def generate_intro(self) -> TurnResult:
        """Generate opening scene for a new game."""
        try:
            from luna.systems.intro import IntroGenerator
            intro_gen = IntroGenerator(
                self.world, self.llm_manager, self.media_pipeline,
                self.memory_manager, self.gameplay_manager,
            )
            return await intro_gen.generate(self.state)
        except Exception as e:
            logger.warning("Intro generation failed: %s", e)
            return TurnResult(
                text=f"*Benvenuto nel mondo di {self.world.name}.*",
                turn_number=0,
                provider_used="system",
            )

    async def run_initiative_turn(self, hint) -> Optional[Any]:
        """Run an autonomous NPC-initiated turn (narrative + image, no player input)."""
        if not self.npc_initiative_runner:
            return None
        try:
            return await self.npc_initiative_runner.run(hint)
        except Exception as e:
            logger.warning("[Engine] initiative turn failed for %s: %s", getattr(hint, 'npc_id', '?'), e)
            return None

    async def generate_image_after_outfit_change(self) -> Optional[str]:
        """Regenerate image after UI-triggered outfit change."""
        if self.no_media or not self.media_pipeline:
            return None
        game_state = self.state
        comp_def   = self.world.companions.get(game_state.active_companion)
        outfit     = game_state.get_outfit()
        sd_prompt  = self.outfit_engine.to_sd_prompt(outfit) if self.outfit_engine else ""
        result     = await self.media_pipeline.generate_all(
            text="", visual_en=sd_prompt, tags=[],
            companion_name=game_state.active_companion,
            base_prompt=comp_def.base_prompt if comp_def else "",
            location_id=game_state.current_location,
        )
        return result.image_path if result else None

    async def resolve_quest_choice(self, quest_id: str, accepted: bool) -> Optional[str]:
        if self.quest_engine:
            return self.quest_engine.resolve_choice(quest_id, accepted, self.state)
        return None

    def get_game_state(self) -> GameState:
        return self.state

    def get_active_quests(self) -> List[str]:
        return self.state.active_quests

    def get_pending_quest_choices(self) -> List[Dict[str, Any]]:
        from luna.core.models import QuestStatus
        choices = []
        if not self.quest_engine:
            return choices
        for quest_id, instance in self.quest_engine.get_all_instances().items():
            if instance.status == QuestStatus.PENDING_CHOICE:
                quest_def = self.world.quests.get(quest_id)
                if quest_def:
                    choices.append({
                        "quest_id":    quest_id,
                        "title":       quest_def.choice_title or quest_def.title,
                        "description": quest_def.choice_description or quest_def.description,
                        "accept_text": quest_def.accept_button_text,
                        "decline_text": quest_def.decline_button_text,
                    })
        return choices

    def toggle_audio(self) -> bool:
        if self.media_pipeline:
            return self.media_pipeline.toggle_audio()
        return False

    def set_ui_time_change_callback(self, cb: Callable) -> None:
        self._ui_time_change_cb = cb
    
    # V2 MultiNPC Expanded callbacks
    def set_ui_intermediate_message_callback(self, callback: Callable) -> None:
        """Set callback for intermediate NPC messages during MultiNPC.
        
        Args:
            callback: async function(text, speaker, turn_number, visual_en, tags_en)
        """
        self._ui_intermediate_message_callback = callback
    
    def set_ui_show_interrupt_callback(self, callback: Callable) -> None:
        """Set callback to show/hide interrupt button.
        
        Args:
            callback: function(show: bool)
        """
        self._show_interrupt_callback = callback
    
    def set_ui_image_callback(self, callback: Callable) -> None:
        """Set callback for intermediate image display.
        
        Args:
            callback: function(image_path: str)
        """
        self._ui_image_callback = callback

    def get_available_actions(self) -> List[Dict[str, Any]]:
        if not self.gameplay_manager:
            return []
        try:
            actions = self.gameplay_manager.get_available_actions(self.get_game_state())
            result  = []
            for a in actions:
                if isinstance(a, dict):
                    result.append(a)
                else:
                    result.append({
                        "action_id":       getattr(a, "action_id", ""),
                        "name":            getattr(a, "name", ""),
                        "description":     getattr(a, "description", ""),
                        "category":        getattr(a, "category", "general"),
                        "icon":            getattr(a, "icon", "🎯"),
                        "enabled":         getattr(a, "enabled", True),
                        "requires_target": getattr(a, "requires_target", False),
                        "target_type":     getattr(a, "target_type", None),
                        "metadata":        getattr(a, "metadata", {}),
                    })
            return result
        except Exception:
            return []

    async def execute_action(self, action_id: str, target: Optional[str] = None) -> Any:
        if self.gameplay_manager:
            return await self.gameplay_manager.execute_action(
                action_id, target, self.get_game_state()
            )
        return None

    # =========================================================================
    # Manual Phase Advance (v8)
    # =========================================================================

    def preview_phase_advance(self) -> Optional[Any]:
        """Sincrono. Calcola chi si sposta dove alla prossima fase.

        Nessuna LLM call, nessuna modifica di stato.
        Usato dalla UI per mostrare il warning prima della conferma.
        """
        from luna.core.models import TimeOfDay
        from luna.core.models.output_models import NpcMovement, PhasePreview

        if not self.phase_clock or not self.schedule_manager:
            return None

        _cycle = [TimeOfDay.MORNING, TimeOfDay.AFTERNOON,
                  TimeOfDay.EVENING, TimeOfDay.NIGHT]
        current = self.state.time_of_day
        try:
            idx = _cycle.index(current)
        except ValueError:
            return None
        next_phase = _cycle[(idx + 1) % len(_cycle)]

        movements: list = []
        active = self.state.active_companion
        staying = getattr(self.state, "companion_staying_with_player", False)

        for npc_name in self.state.npc_locations:
            if staying and npc_name == active:
                continue
            new_loc = self.schedule_manager.get_npc_location(npc_name, next_phase)
            if not new_loc:
                continue
            old_loc = self.state.get_npc_location(npc_name)
            if old_loc != new_loc:
                movements.append(NpcMovement(
                    npc_name=npc_name,
                    from_location=old_loc or "?",
                    to_location=new_loc,
                    is_active_companion=(npc_name == active),
                ))

        active_leaves = any(m.is_active_companion for m in movements)

        return PhasePreview(
            current_phase=current,
            next_phase=next_phase,
            movements=movements,
            active_companion_leaves=active_leaves,
        )

    async def advance_phase(self) -> Any:
        """Asincrono. Esegue il cambio fase con farewell LLM se necessario.

        Chiamato dalla UI dopo che l'utente ha confermato il warning.
        """
        if not self.turn_orchestrator:
            from luna.core.models import TurnResult
            return TurnResult(
                text="[Errore: orchestrator non inizializzato]",
                turn_number=self.state.turn_count,
                provider_used="system",
                error="orchestrator_not_initialized",
            )
        return await self.turn_orchestrator.execute_phase_advance()

    async def list_saves(self) -> List[Dict[str, Any]]:
        async with self.db.session() as db:
            return await self.db.list_saves(db)

    async def shutdown(self) -> None:
        if self._initialized:
            if self.state_memory:
                await self.state_memory.save_all()
            if self.llm_manager:
                await self.llm_manager.close()
            logger.info("Engine shutdown complete")

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def state(self) -> GameState:
        return self.state_manager.current

    # =========================================================================
    # Internal initialization
    # =========================================================================

    def _init_systems(self) -> None:
        """Initialize all subsystems. Called once before game/load."""
        from luna.core.state import StateManager
        from luna.ai.manager import get_llm_manager
        from luna.systems.personality import PersonalityEngine
        from luna.systems.location import LocationManager
        from luna.systems.npc_detector_v2 import NPCDetectorV2 as NPCDetector
        from luna.systems.affinity_calculator import get_calculator
        from luna.systems.multi_npc import MultiNPCManager
        from luna.systems.global_events import GlobalEventManager
        from luna.systems.outfit_engine import OutfitEngine
        from luna.systems.outfit_modifier import OutfitModifierSystem
        from luna.systems.quest_engine_sequential import SequentialQuestEngine as QuestEngine
        # ActivitySystem / InitiativeSystem removed in v8 M6 (replaced by ScheduleManager + NPCMind)
        from luna.systems.invitation_manager import InvitationManager
        from luna.systems.pose_extractor import get_pose_extractor
        from luna.core.story_director import StoryDirector
        from luna.media.lora_mapping import LoraMapping
        from luna.systems.gameplay_manager import GameplayManager

        self.state_manager       = StateManager(self.db)
        self.personality_engine  = PersonalityEngine(
            self.state_manager, world=self.world,
            use_llm_analysis=True, llm_analysis_interval=5,
        )
        self.story_director      = StoryDirector(self.world.narrative_arc)
        self.quest_engine        = QuestEngine(self.world, engine=self)
        self.outfit_engine       = OutfitEngine()
        self.outfit_modifier     = OutfitModifierSystem()
        self.llm_manager         = get_llm_manager()
        self.location_manager    = LocationManager(self.world, self.state_manager)
        self.npc_detector        = NPCDetector(self.world)
        self.affinity_calculator = get_calculator()
        self.multi_npc_manager   = MultiNPCManager(world=self.world, enabled=True)
        self.event_manager       = GlobalEventManager(self.world)
        self.lora_mapping        = LoraMapping()
        self.gameplay_manager    = GameplayManager(self.world)
        self.invitation_manager  = InvitationManager(self.state_manager, self.world)
        self.pose_extractor      = get_pose_extractor()

        # v8: Character Realism System
        from luna.systems.presence_tracker import PresenceTracker
        from luna.systems.emotional_state_engine import EmotionalStateEngine
        from luna.systems.character_voice_builder import CharacterVoiceBuilder
        self.presence_tracker        = PresenceTracker(world=self.world)
        self.emotional_state_engine  = EmotionalStateEngine()
        self.character_voice_builder = CharacterVoiceBuilder()

        # v8: NPC Secondary Activation System
        from luna.systems.npc_location_router import NpcLocationRouter
        from luna.systems.npc_goal_evaluator import NpcGoalEvaluator
        from luna.systems.npc_initiative_turn import NpcInitiativeTurn
        self.npc_location_router  = NpcLocationRouter(world=self.world)
        self.npc_goal_evaluator   = NpcGoalEvaluator(world=self.world)
        self.npc_initiative_runner = NpcInitiativeTurn(engine=self)
        self._pending_initiatives: List = []   # queue of GoalHint waiting for autonomous turn
        self._active_authority_scene = None    # context of last authority initiative turn

        if not self.no_media:
            from luna.media.pipeline import MediaPipeline
            self.media_pipeline = MediaPipeline(lora_mapping=self.lora_mapping)
        else:
            self.media_pipeline = None
            logger.info("Media generation disabled (--no-media)")

    async def _init_runtime_systems(self, game_state: GameState) -> None:
        """Initialize systems that need game_state. Shared by new+load."""
        from luna.systems.state_memory import StateMemoryManager
        from luna.systems.schedule_manager import ScheduleManager
        from luna.systems.movement import MovementHandler
        from luna.systems.memory import MemoryManager
        from luna.systems.situational_interventions import SituationalInterventionSystem
        from luna.systems.phase_clock import PhaseClock, PhaseClockConfig

        from pathlib import Path
        from luna.core.config import get_user_prefs
        _user_prefs = get_user_prefs()
        _semantic_enabled = _user_prefs.enable_semantic_memory
        _semantic_path = None
        if _semantic_enabled:
            _semantic_path = Path("storage/semantic")
            _semantic_path.mkdir(parents=True, exist_ok=True)

        self.memory_manager = MemoryManager(
            db_manager=self.db,
            session_id=game_state.session_id,
            history_limit=self.settings.memory_history_limit,
            enable_semantic=_semantic_enabled,
            storage_path=_semantic_path,
        )

        self.schedule_manager = ScheduleManager(
            game_state=game_state, world=self.world
        )

        # Populate npc_locations from schedule at game start
        for npc_name in self.world.companions:
            if npc_name == "_solo_":
                continue
            loc = self.schedule_manager.get_npc_location(npc_name, game_state.time_of_day)
            if loc and npc_name not in game_state.npc_locations:
                game_state.set_npc_location(npc_name, loc)
                logger.debug("[Engine] NPC %s starting at %s", npc_name, loc)

        self.movement_handler = MovementHandler(
            world=self.world,
            location_manager=self.location_manager,
            game_state=game_state,
        )

        # v8: Manual phase advance — disabilita tick automatico, usa pulsante UI
        self.phase_clock = PhaseClock(
            current_phase=game_state.time_of_day,
            config=PhaseClockConfig(turns_per_phase=8),
            on_phase_change=self._on_phase_change,
            manual_mode=True,  # ← Abilita avanzamento manuale via pulsante
        )
        self.phase_manager = self.phase_clock

        phase_state = game_state.flags.get("_phase_clock_state")
        if phase_state:
            self.phase_clock.from_dict(phase_state)

        # Restore DynamicEventManager state (occurrence_counts, cooldowns, etc.)
        dyn_state = game_state.flags.get("_dynamic_events_state")
        if dyn_state and self.gameplay_manager:
            self.gameplay_manager.event_manager.from_dict(dyn_state)
            logger.info("[Engine] DynamicEventManager state restored")

        # Restore InvitationManager pending invitations
        inv_state = game_state.flags.get("_invitation_state")
        if inv_state and self.invitation_manager:
            self.invitation_manager.from_dict(inv_state)
            logger.info("[Engine] InvitationManager state restored (%d pending)",
                        len(inv_state.get("pending", [])))

        self.state_memory = StateMemoryManager(
            db=self.db,
            session_id=game_state.session_id,
            state_manager=self.state_manager,
            memory_manager=self.memory_manager,
            quest_engine=self.quest_engine,
            event_manager=self.event_manager,
            story_director=self.story_director,
            personality_engine=self.personality_engine,
            phase_clock=self.phase_clock,
            world_simulator=None,          # set after WorldSimulator init below
            tension_tracker=None,          # set after TensionTracker init below
            dynamic_event_manager=self.gameplay_manager.event_manager if self.gameplay_manager else None,
            invitation_manager=self.invitation_manager,
        )

        self.situational_intervention = SituationalInterventionSystem(
            engine=self,
            world=self.world,
            state_manager=self.state_manager,
            multi_npc_manager=self.multi_npc_manager,
            llm_manager=self.llm_manager,
            state_memory=self.state_memory,
        )

        async with self.db.session() as db:
            quest_states = await self.db.get_all_quest_states(db, game_state.session_id)
        self._restore_quest_instances(quest_states, game_state)

        # Set starting location
        if game_state.current_location in ("Unknown", "", None) and self.world.locations:
            active_sched = self.schedule_manager._schedules.get(game_state.active_companion)
            active_entry = active_sched.get_current(game_state.time_of_day) if active_sched else None
            if active_entry and active_entry.location in self.world.locations:
                game_state.current_location = active_entry.location
            else:
                game_state.current_location = next(iter(self.world.locations.keys()))

        # Turn logger setup
        try:
            from luna.systems.turn_logger import TurnLogger
            storage_root = Path("storage")
            storage_root.mkdir(parents=True, exist_ok=True)
            if game_state.session_id is not None:
                self.turn_logger = TurnLogger(storage_root, game_state.session_id)
        except Exception as e:
            self.turn_logger = None
            logger.warning("[Engine] TurnLogger init failed: %s", e)

        # Initialize outfits
        for companion_name, comp_def in self.world.companions.items():
            if companion_name not in game_state.companion_outfits:
                npc_sched    = self.schedule_manager._schedules.get(companion_name)
                schedule     = npc_sched.get_current(game_state.time_of_day) if npc_sched else None
                outfit_style = schedule.outfit if schedule else comp_def.default_outfit
                self.outfit_engine.apply_schedule_outfit(
                    outfit_style, comp_def, game_state, 0
                )

        # ── v7: TensionTracker (independent from WorldSimulator) ─────────────
        try:
            from luna.systems.tension_tracker import TensionTracker

            self.tension_tracker = TensionTracker()
            tension_config = getattr(self.world, 'tension_config', None)
            if tension_config and isinstance(tension_config, dict):
                self.tension_tracker.load_from_config(tension_config)
            else:
                self.tension_tracker.load_defaults()

            tension_state = game_state.flags.get("_tension_tracker_state")
            if tension_state:
                self.tension_tracker.from_dict(tension_state)

            logger.info("[Engine] TensionTracker initialized")
        except Exception as e:
            logger.warning("[Engine] TensionTracker init failed: %s", e)
            self.tension_tracker = None

        # ── v7: WorldSimulator ────────────────────────────────────────────────
        try:
            from luna.systems.npc_mind_ext import NPCMindManagerExt as NPCMindManager
            from luna.systems.world_simulator import WorldSimulator

            mind_manager = NPCMindManager()
            self.world_simulator = WorldSimulator(
                mind_manager=mind_manager,
                world=self.world,
                tension_tracker=self.tension_tracker,
                story_director=self.story_director,
            )
            self.world_simulator.initialize_from_world(self.world, game_state)

            # NPCStateManager: unified query API over location + mind + affinity
            from luna.systems.npc_state_manager import NPCStateManager
            self.npc_state = NPCStateManager(mind_manager=mind_manager, world=self.world)

            from luna.systems.witness_system import WitnessSystem
            self.witness_system = WitnessSystem(self.npc_state)

            # Restore NPC mind states if saved
            minds_state = game_state.flags.get("_npc_minds_state")
            if minds_state:
                mind_manager.from_dict(minds_state)

            # Restore WorldSimulator cooldown counters only — NOT via from_dict() which
            # would call mind_manager.from_dict({}) and wipe minds just restored above.
            ws_meta = game_state.flags.get("_world_sim_meta")
            if ws_meta and self.world_simulator:
                try:
                    self.world_simulator._turns_since_event = ws_meta.get("turns_since_event", 0)
                    self.world_simulator._last_ambient_turn = ws_meta.get("last_ambient_turn", 0)
                    logger.debug("[Engine] WorldSimulator metadata restored from state")
                except Exception as e:
                    logger.warning("[Engine] WorldSimulator metadata restore failed: %s", e)

            logger.info("[Engine] v7 WorldSimulator initialized with %d minds",
                        len(mind_manager.minds))

            # Wire to state_memory for persistence
            if self.state_memory:
                self.state_memory.world_simulator = self.world_simulator
                self.state_memory.tension_tracker = self.tension_tracker
                self.state_memory.npc_mind_manager = mind_manager  # v8 M5

            # v8 M5: Load NPCMind states from dedicated DB table and simulate
            # offline time (Il Mondo Ricorda — the world remembers).
            # If the dedicated table has data newer than the flags snapshot, use it.
            try:
                from datetime import datetime, timezone
                async with self.db.session() as db:
                    db_minds = await self.db.load_npc_minds(db, game_state.session_id)
                if db_minds:
                    # Check if DB data is newer than flags snapshot (prefer flags
                    # snapshot only if no DB row exists yet — DB rows always win).
                    db_data = {nid: v["mind_data"] for nid, v in db_minds.items()}
                    mind_manager.from_dict(db_data)
                    logger.info("[Engine] NPC minds restored from DB table (%d NPCs)",
                                len(db_minds))

                    # Calculate elapsed real-world time and simulate offline ticks
                    # (1 offline hour ≈ 1 simulated turn — keeps pacing gentle)
                    any_saved_at = next(iter(db_minds.values()))["saved_at"]
                    if any_saved_at:
                        now = datetime.now(timezone.utc)
                        saved_utc = any_saved_at
                        if saved_utc.tzinfo is None:
                            saved_utc = saved_utc.replace(tzinfo=timezone.utc)
                        hours_offline = (now - saved_utc).total_seconds() / 3600.0
                        offline_ticks = min(int(hours_offline), 72)  # cap at 3 days
                        if offline_ticks > 0:
                            mind_manager.simulate_offline_ticks(
                                offline_ticks,
                                start_turn=game_state.turn_count,
                            )
                            logger.info(
                                "[Engine] Simulated %d offline ticks (%.1f hours offline)",
                                offline_ticks, hours_offline,
                            )
            except Exception as e:
                logger.warning("[Engine] NPC mind DB load/offline-sim failed: %s", e)

        except Exception as e:
            logger.warning("[Engine] v7 WorldSimulator init failed: %s", e)
            self.world_simulator = None

        # Turn orchestrator — last
        from luna.agents.orchestrator import TurnOrchestrator
        self.turn_orchestrator = TurnOrchestrator(self)

        logger.debug("Runtime systems initialized for session %d", game_state.session_id)

    def _restore_quest_instances(self, quest_states: Any, game_state: GameState) -> None:
        from luna.core.models import QuestInstance, QuestStatus
        instances = {}
        for qs in quest_states:
            try:
                instances[qs.quest_id] = QuestInstance(
                    quest_id=qs.quest_id,
                    status=QuestStatus(qs.status),
                    current_stage_id=qs.current_stage_id,
                    stage_data=qs.stage_data or {},
                    started_at=qs.started_at or 0,
                    completed_at=qs.completed_at,
                    pending_since_turn=qs.pending_since_turn,
                    stage_entered_at=qs.stage_entered_at or 0,
                )
            except Exception as e:
                logger.warning("Could not restore quest %s: %s", qs.quest_id, e)
        self.quest_engine.load_instances(instances)

    def _on_phase_change(self, event: Any) -> None:
        """Called by PhaseClock when phase changes."""
        if self._ui_time_change_cb:
            try:
                self._ui_time_change_cb(event.new_phase, event.message)
            except Exception as e:
                logger.error("UI time change callback failed: %s", e)

        if self.invitation_manager and self.state_manager.is_loaded:
            try:
                arrivals = self.invitation_manager.check_arrivals(
                    event.new_phase,  # current time
                    self.state.current_location,  # player location
                    self.location_manager  # for updating NPC presence
                )
                for arrival in arrivals:
                    logger.info(
                        "[PhaseChange] %s arrived at %s",
                        arrival.npc_name, arrival.location,
                    )
            except Exception as e:
                logger.warning("[PhaseChange] Invitation check failed: %s", e)

        if self.state_manager.is_loaded and self.schedule_manager:
            try:
                state   = self.state
                staying = getattr(state, "companion_staying_with_player", False)
                active  = state.active_companion
                # First, purge any expired location overrides (e.g. invitations that ended)
                expired = state.purge_expired_npc_locations()
                for npc in expired:
                    logger.info("[PhaseChange] Location override expired for %s", npc)

                for npc_name in list(state.npc_locations.keys()):
                    if staying and npc_name == active:
                        continue
                    # Respect active invitation overrides — skip if TTL is still running
                    if npc_name in state.npc_location_expires:
                        logger.debug("[PhaseChange] Skipping schedule update for %s (invite active)", npc_name)
                        continue
                    new_loc = self.schedule_manager.get_npc_location(
                        npc_name, event.new_phase
                    )
                    if new_loc:
                        old_loc = state.get_npc_location(npc_name)
                        if old_loc != new_loc:
                            state.set_npc_location(npc_name, new_loc)
                            logger.info(
                                "[PhaseChange] %s: %s → %s",
                                npc_name, old_loc, new_loc,
                            )
                            # Update outfit to match new schedule
                            comp_def = self.world.companions.get(npc_name)
                            if comp_def:
                                sched = self.schedule_manager._schedules.get(npc_name)
                                if sched:
                                    entry = sched.get_current(event.new_phase)
                                    if entry and entry.outfit:
                                        self.outfit_engine.apply_schedule_outfit(
                                            entry.outfit, comp_def, state, state.turn_count
                                        )
                                        logger.info(
                                            "[PhaseChange] %s outfit updated to: %s",
                                            npc_name, entry.outfit,
                                        )
            except Exception as e:
                logger.warning("[PhaseChange] NPC relocation failed: %s", e)

    def _load_world(self, world_id: str) -> Optional[WorldDefinition]:
        from luna.systems.world import get_world_loader
        loader = get_world_loader()
        try:
            return loader.load_world(world_id)
        except Exception as e:
            logger.error("Failed to load world '%s': %s", world_id, e)
            return None
