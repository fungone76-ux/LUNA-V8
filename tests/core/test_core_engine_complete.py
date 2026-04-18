"""Complete test suite for Luna RPG Core Engine.

This file contains ready-to-run tests for core/engine.py.
Run with: pytest tests/core/test_core_engine_complete.py -v

Coverage target: 75%+ for engine.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest
from unittest.mock import Mock, AsyncMock, patch


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def minimal_world_definition():
    """Complete minimal world for engine testing."""
    from luna.core.models import WorldDefinition, CompanionDefinition, Location

    return WorldDefinition(
        id="test_world",
        name="Test World",
        companions={
            "luna": CompanionDefinition(
                name="Luna",
                role="Teacher",
                age=30,
                base_personality="Professional",
                physical_description="Test teacher",
                base_prompt="teacher prompt",
                default_outfit="teacher_suit",
            )
        },
        locations={
            "home": Location(id="home", name="Home", description="Player home"),
            "office": Location(id="office", name="Office", description="Teacher office"),
        },
    )


@pytest.fixture
def mem_db():
    """In-memory DatabaseManager for isolated engine tests."""
    from luna.core.database import DatabaseManager
    from luna.core.models import AppConfig

    cfg = AppConfig(database_url="sqlite+aiosqlite:///:memory:")
    return DatabaseManager(config=cfg)


@pytest.fixture
async def mock_engine_full(minimal_world_definition, mem_db):
    """Fully mocked GameEngine ready for testing."""
    from luna.core.engine import GameEngine

    with patch.object(GameEngine, '_load_world', return_value=minimal_world_definition):
        engine = GameEngine(
            world_id="test_world",
            companion="luna",
            no_media=True
        )

    # Replace DB with in-memory instance
    engine.db = mem_db

    yield engine

    try:
        if engine._initialized:
            await engine.shutdown()
    except Exception:
        pass


# ============================================================================
# TEST 1: Engine Creation & Configuration
# ============================================================================

class TestEngineCreation:
    """Test engine instance creation and configuration."""

    def test_create_engine_basic(self, minimal_world_definition):
        """Test creating basic engine instance."""
        from luna.core.engine import GameEngine

        with patch.object(GameEngine, '_load_world', return_value=minimal_world_definition):
            engine = GameEngine(
                world_id="test_world",
                companion="luna",
                no_media=True
            )

        assert engine.world_id == "test_world"
        assert engine.companion == "luna"
        assert engine._initialized is False
        assert engine.world.id == "test_world"

    def test_create_engine_no_media(self, minimal_world_definition):
        """Test creating engine with media disabled."""
        from luna.core.engine import GameEngine

        with patch.object(GameEngine, '_load_world', return_value=minimal_world_definition):
            engine = GameEngine(
                world_id="test_world",
                companion="luna",
                no_media=True
            )

        assert engine.no_media is True

    def test_create_engine_env_override(self, minimal_world_definition, monkeypatch):
        """Test LUNA_DEBUG_NO_MEDIA env var overrides media setting."""
        from luna.core.engine import GameEngine

        monkeypatch.setenv("LUNA_DEBUG_NO_MEDIA", "1")

        with patch.object(GameEngine, '_load_world', return_value=minimal_world_definition):
            engine = GameEngine(
                world_id="test_world",
                companion="luna",
                no_media=False
            )

        assert engine.no_media is True

    def test_create_engine_invalid_world(self):
        """Test creating engine with invalid world raises error."""
        from luna.core.engine import GameEngine

        with patch.object(GameEngine, '_load_world', return_value=None):
            with pytest.raises(ValueError, match="World not found"):
                GameEngine(
                    world_id="nonexistent_world",
                    companion="luna",
                    no_media=True
                )


# ============================================================================
# TEST 2: Engine Initialization
# ============================================================================

class TestEngineInitialization:
    """Test engine initialization process."""

    async def test_initialize_creates_all_systems(self, mock_engine_full):
        """Test that initialize() creates all required subsystems."""
        engine = mock_engine_full

        await engine.initialize()

        # Core systems (set in _init_systems)
        assert engine.state_manager is not None, "StateManager not initialized"
        assert engine.quest_engine is not None, "QuestEngine not initialized"
        assert engine.personality_engine is not None, "PersonalityEngine not initialized"
        assert engine.location_manager is not None, "LocationManager not initialized"
        assert engine.llm_manager is not None, "LLM manager not initialized"

        # Runtime systems (set in _init_runtime_systems)
        assert engine.memory_manager is not None, "MemoryManager not initialized"
        assert engine.schedule_manager is not None, "ScheduleManager not initialized"
        assert engine.state_memory is not None, "StateMemory not initialized"

        # v8 systems
        assert engine.presence_tracker is not None, "PresenceTracker not initialized"
        assert engine.emotional_state_engine is not None, "EmotionalStateEngine not initialized"

        # Media disabled
        assert engine.media_pipeline is None

    async def test_initialize_creates_game_state(self, mock_engine_full):
        """Test that initialize creates valid game state."""
        from luna.core.models import GameState

        engine = mock_engine_full
        await engine.initialize()

        state = engine.state

        assert isinstance(state, GameState)
        assert state.world_id == "test_world"
        assert state.active_companion == "luna"
        assert state.turn_count == 0
        assert state.session_id is not None
        assert state.current_location is not None

    async def test_initialize_idempotent(self, mock_engine_full):
        """Test calling initialize twice doesn't create a new session."""
        engine = mock_engine_full

        await engine.initialize()
        first_session = engine._session_id

        await engine.initialize()
        second_session = engine._session_id

        assert first_session == second_session

    async def test_initialize_sets_initialized_flag(self, mock_engine_full):
        """Test _initialized flag is set after init."""
        engine = mock_engine_full

        assert engine._initialized is False

        await engine.initialize()

        assert engine._initialized is True

    async def test_initialize_no_media_pipeline_when_disabled(self, mock_engine_full):
        """Test media pipeline is None when no_media=True."""
        engine = mock_engine_full

        await engine.initialize()

        assert engine.media_pipeline is None


# ============================================================================
# TEST 3: Session Save/Load
# ============================================================================

class TestEngineSessionManagement:
    """Test session save and load functionality."""

    async def test_save_and_load_session_basic(self, minimal_world_definition, mem_db):
        """Test basic save/load cycle."""
        from luna.core.engine import GameEngine

        # Create and initialize engine
        with patch.object(GameEngine, '_load_world', return_value=minimal_world_definition):
            engine = GameEngine(world_id="test_world", companion="luna", no_media=True)
        engine.db = mem_db

        await engine.initialize()
        original_session_id = engine._session_id

        engine.state.flags["test_key"] = "test_value"

        await engine.shutdown()

        # Create second engine sharing the same in-memory DB
        with patch.object(GameEngine, '_load_world', return_value=minimal_world_definition):
            engine2 = GameEngine(world_id="test_world", companion="luna", no_media=True)
        engine2.db = mem_db

        success = await engine2.load_session(original_session_id)

        assert success is True
        assert engine2._initialized is True
        assert engine2.state.flags["test_key"] == "test_value"

        await engine2.shutdown()

    async def test_load_nonexistent_session(self, mock_engine_full):
        """Test loading session that doesn't exist."""
        engine = mock_engine_full

        # Initialize DB tables first (without starting a game)
        await engine.db.create_tables()

        success = await engine.load_session(999999)

        assert success is False
        assert engine._initialized is False

    async def test_load_session_restores_systems(self, minimal_world_definition, mem_db):
        """Test loading session restores all systems."""
        from luna.core.engine import GameEngine

        with patch.object(GameEngine, '_load_world', return_value=minimal_world_definition):
            engine = GameEngine(world_id="test_world", companion="luna", no_media=True)
        engine.db = mem_db

        await engine.initialize()
        session_id = engine._session_id
        await engine.shutdown()

        with patch.object(GameEngine, '_load_world', return_value=minimal_world_definition):
            engine2 = GameEngine(world_id="test_world", companion="luna", no_media=True)
        engine2.db = mem_db

        await engine2.load_session(session_id)

        assert engine2.memory_manager is not None
        assert engine2.quest_engine is not None
        assert engine2.turn_orchestrator is not None

        await engine2.shutdown()


# ============================================================================
# TEST 4: Turn Processing
# ============================================================================

class TestEngineTurnProcessing:
    """Test turn processing functionality."""

    async def test_process_turn_before_init_fails(self, mock_engine_full):
        """Test process_turn fails gracefully before initialization."""
        engine = mock_engine_full

        result = await engine.process_turn("test input")

        assert result.error == "not_initialized"
        assert "not initialized" in result.text.lower()

    async def test_process_turn_delegates_to_orchestrator(self, mock_engine_full):
        """Test process_turn delegates to TurnOrchestrator."""
        engine = mock_engine_full

        await engine.initialize()

        mock_orchestrator = Mock()
        mock_result = Mock(
            text="Test response from orchestrator",
            turn_number=1,
            provider_used="test"
        )
        mock_orchestrator.execute = AsyncMock(return_value=mock_result)
        engine.turn_orchestrator = mock_orchestrator

        result = await engine.process_turn("Hello world")

        mock_orchestrator.execute.assert_called_once_with("Hello world")
        assert result.text == "Test response from orchestrator"

    async def test_process_turn_saves_last_input(self, mock_engine_full):
        """Test _last_user_input is updated."""
        engine = mock_engine_full

        await engine.initialize()

        mock_orchestrator = Mock()
        mock_orchestrator.execute = AsyncMock(return_value=Mock(
            text="Response", turn_number=1
        ))
        engine.turn_orchestrator = mock_orchestrator

        await engine.process_turn("Test input 123")

        assert engine._last_user_input == "Test input 123"


# ============================================================================
# TEST 5: Public API Methods
# ============================================================================

class TestEnginePublicAPI:
    """Test public API methods."""

    async def test_get_game_state(self, mock_engine_full):
        """Test get_game_state returns current state."""
        from luna.core.models import GameState

        engine = mock_engine_full
        await engine.initialize()

        state = engine.get_game_state()

        assert isinstance(state, GameState)
        assert state.world_id == "test_world"

    async def test_get_active_quests_empty(self, mock_engine_full):
        """Test get_active_quests when no quests."""
        engine = mock_engine_full
        await engine.initialize()

        quests = engine.get_active_quests()

        assert isinstance(quests, list)
        assert len(quests) == 0

    async def test_get_active_quests_with_quests(self, mock_engine_full):
        """Test get_active_quests returns quest list."""
        engine = mock_engine_full
        await engine.initialize()

        engine.state.active_quests.append("test_quest_1")
        engine.state.active_quests.append("test_quest_2")

        quests = engine.get_active_quests()

        assert len(quests) == 2
        assert "test_quest_1" in quests
        assert "test_quest_2" in quests

    async def test_get_pending_quest_choices_empty(self, mock_engine_full):
        """Test get_pending_quest_choices when no pending."""
        engine = mock_engine_full
        await engine.initialize()

        choices = engine.get_pending_quest_choices()

        assert isinstance(choices, list)
        assert len(choices) == 0

    async def test_toggle_audio_no_media(self, mock_engine_full):
        """Test toggle_audio when media disabled returns False."""
        engine = mock_engine_full
        await engine.initialize()

        result = engine.toggle_audio()

        assert result is False


# ============================================================================
# TEST 6: Shutdown & Cleanup
# ============================================================================

class TestEngineShutdown:
    """Test shutdown and cleanup."""

    async def test_shutdown_saves_state(self, mock_engine_full):
        """Test shutdown saves game state."""
        engine = mock_engine_full
        await engine.initialize()

        engine.state_memory.save_all = AsyncMock()

        await engine.shutdown()

        engine.state_memory.save_all.assert_called_once()

    async def test_shutdown_closes_llm(self, mock_engine_full):
        """Test shutdown closes LLM connection."""
        engine = mock_engine_full
        await engine.initialize()

        engine.llm_manager.close = AsyncMock()

        await engine.shutdown()

        engine.llm_manager.close.assert_called_once()

    async def test_shutdown_when_not_initialized(self, mock_engine_full):
        """Test shutdown when engine not initialized does not crash."""
        engine = mock_engine_full

        # Should not raise
        await engine.shutdown()


# ============================================================================
# TEST 7: Properties
# ============================================================================

class TestEngineProperties:
    """Test engine properties."""

    async def test_state_property(self, mock_engine_full):
        """Test .state property returns state_manager.current."""
        from luna.core.models import GameState

        engine = mock_engine_full
        await engine.initialize()

        state = engine.state

        assert isinstance(state, GameState)
        assert state is engine.state_manager.current


# ============================================================================
# RUN STANDALONE
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
