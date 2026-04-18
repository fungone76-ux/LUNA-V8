"""Pytest configuration and shared fixtures for Luna RPG v8 tests."""
import pytest
import sys
from pathlib import Path
from typing import AsyncGenerator, Generator
from unittest.mock import Mock, AsyncMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture
async def test_db():
    """In-memory database for isolated tests.
    
    Usage:
        async def test_something(test_db):
            async with test_db.get_session() as session:
                # ... test database operations
    """
    from luna.core.database import Database
    
    db = Database(db_path=":memory:")
    await db.init()
    
    yield db
    
    # Cleanup
    try:
        await db.close()
    except Exception:
        pass


@pytest.fixture
async def test_db_with_data(test_db):
    """Database with pre-populated test data."""
    # Add sample game state, memories, etc.
    async with test_db.get_session() as session:
        # TODO: Add sample data creation
        pass
    
    yield test_db


# ============================================================================
# Game Engine Fixtures
# ============================================================================

@pytest.fixture
async def mock_engine():
    """Basic GameEngine with mocked dependencies.
    
    Usage:
        async def test_turn(mock_engine):
            result = await mock_engine.process_turn("test input")
            assert result is not None
    """
    from luna.core.engine import GameEngine
    
    engine = GameEngine(
        world_name="school_life_complete",
        no_media=True,  # Skip image/video generation
        no_llm=True     # Use mock LLM
    )
    
    # Don't start game automatically - let test do it
    yield engine


@pytest.fixture
async def test_game_state():
    """Minimal GameState for testing.
    
    Usage:
        def test_something(test_game_state):
            test_game_state.turn_count = 10
            # ... test logic
    """
    from luna.core.models import GameState
    
    return GameState(
        session_id="test_session_001",
        turn_count=1,
        active_companion="luna",
        companions={
            "luna": {
                "affinity": 50,
                "emotional_state": "default",
                "strip_level": 0
            },
            "stella": {
                "affinity": 30,
                "emotional_state": "default",
                "strip_level": 0
            }
        },
        flags={},
        player_location="classroom",
        npc_locations={"luna": "office", "stella": "library"}
    )


# ============================================================================
# LLM Mocking Fixtures
# ============================================================================

@pytest.fixture
def mock_llm_manager():
    """Mock LLM manager that returns predefined responses.
    
    Usage:
        async def test_with_llm(mock_llm_manager):
            response = await mock_llm_manager.generate(prompt="test")
            assert response.text == "Mocked response"
    """
    manager = Mock()
    manager.generate = AsyncMock(return_value=Mock(
        text="Mocked response from LLM",
        usage={"total_tokens": 100, "prompt_tokens": 50, "completion_tokens": 50}
    ))
    manager.is_available = Mock(return_value=True)
    return manager


@pytest.fixture
def mock_llm_failing():
    """Mock LLM that always fails (for testing error handling)."""
    manager = Mock()
    manager.generate = AsyncMock(side_effect=Exception("LLM API error"))
    manager.is_available = Mock(return_value=False)
    return manager


# ============================================================================
# Poker Fixtures
# ============================================================================

@pytest.fixture
def poker_config():
    """Standard poker configuration for tests."""
    from luna.systems.mini_games.poker.engine_v2 import GameConfig
    
    return GameConfig(
        small_blind=50,
        big_blind=100,
        initial_stack=1000
    )


@pytest.fixture
def poker_players():
    """Standard 2-player setup for poker tests."""
    from luna.systems.mini_games.poker.engine_v2 import Player
    
    return [
        Player(name="player", stack=1000, is_user=True),
        Player(name="luna", stack=1000),
    ]


@pytest.fixture
async def poker_game(test_game_state, mock_llm_manager):
    """PokerGame instance ready for testing.
    
    Usage:
        async def test_poker_hand(poker_game, test_game_state):
            await poker_game.start_game(test_game_state)
            result = await poker_game.process_action("vedo", test_game_state)
    """
    from luna.systems.mini_games.poker.poker_game import PokerGame
    
    game = PokerGame(
        companion_names=["luna"],
        game_engine=None,  # Mock if needed
        llm_manager=mock_llm_manager
    )
    
    yield game


# ============================================================================
# NPCMind Fixtures
# ============================================================================

@pytest.fixture
def test_npc_mind():
    """Sample NPCState for testing.
    
    Usage:
        def test_needs(test_npc_mind):
            test_npc_mind.needs["intimacy"] = 0.8
            assert test_npc_mind.needs["intimacy"] > 0.5
    """
    from luna.systems.npc_mind import NPCState
    
    return NPCState(
        npc_id="luna",
        needs={
            "social": 0.3,
            "intimacy": 0.2,
            "recognition": 0.4,
            "rest": 0.5
        },
        emotional_state="default",
        emotional_state_set_turn=0,
        unspoken=[],
        current_goal=None,
        off_screen_events=[]
    )


@pytest.fixture
def npc_mind_manager():
    """NPCMindManager for testing."""
    from luna.systems.npc_mind import NPCMindManager
    
    return NPCMindManager()


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def temp_world_dir(tmp_path):
    """Temporary directory for test world files.
    
    Usage:
        def test_world_loading(temp_world_dir):
            world_file = temp_world_dir / "test_world.yaml"
            # ... create test world config
    """
    worlds_dir = tmp_path / "worlds"
    worlds_dir.mkdir()
    return worlds_dir


@pytest.fixture
def sample_companion_config():
    """Sample companion YAML config for testing."""
    return {
        "companion": {
            "name": "TestCompanion",
            "role": "Test Role",
            "age": 25,
            "base_personality": "Friendly and helpful",
            "physical_description": "Test description"
        },
        "personality_system": {
            "core_traits": {
                "role": "Test",
                "age": "25",
                "base_personality": "Test"
            },
            "emotional_states": {
                "default": {
                    "description": "Normal state",
                    "dialogue_tone": "Casual"
                }
            },
            "affinity_tiers": {
                "0-25": {
                    "name": "Stranger",
                    "tone": "Cold"
                }
            }
        }
    }


# ============================================================================
# Session-scoped Fixtures (expensive setup)
# ============================================================================

@pytest.fixture(scope="session")
def test_world_name():
    """Name of the test world to use (session-scoped)."""
    return "school_life_complete"


# ============================================================================
# Parametrized Fixtures (for testing multiple scenarios)
# ============================================================================

@pytest.fixture(params=["luna", "stella", "maria"])
def companion_name(request):
    """Parametrized companion names for testing all companions.
    
    Usage:
        def test_all_companions(companion_name):
            # This test will run 3 times, once for each companion
            assert companion_name in ["luna", "stella", "maria"]
    """
    return request.param


@pytest.fixture(params=[0, 1, 2, 3, 4, 5])
def strip_level(request):
    """Parametrized strip levels for testing all levels."""
    return request.param


# ============================================================================
# Autouse Fixtures (run automatically)
# ============================================================================

@pytest.fixture(autouse=True)
def setup_test_environment(monkeypatch):
    """Set environment variables for all tests."""
    monkeypatch.setenv("LUNA_TEST_MODE", "1")
    monkeypatch.setenv("LUNA_DEBUG_NO_MEDIA", "1")
    monkeypatch.setenv("LUNA_DEBUG_MODE", "1")


@pytest.fixture(autouse=True)
def reset_random_seed():
    """Reset random seed for reproducible tests."""
    import random
    random.seed(42)


# ============================================================================
# Markers Helpers
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "requires_llm: test requires valid LLM API key"
    )
    config.addinivalue_line(
        "markers", "poker: poker-related tests"
    )


# ============================================================================
# Custom Assertions
# ============================================================================

class CustomAssertions:
    """Custom assertion helpers for Luna RPG tests."""
    
    @staticmethod
    def assert_valid_turn_result(result):
        """Assert TurnResult has required fields."""
        assert result is not None
        assert hasattr(result, "text")
        assert hasattr(result, "image_path")
        assert hasattr(result, "turn_number")
        assert result.text != ""
        assert isinstance(result.turn_number, int)
    
    @staticmethod
    def assert_valid_npc_state(npc_state):
        """Assert NPCState is valid."""
        assert npc_state is not None
        assert hasattr(npc_state, "npc_id")
        assert hasattr(npc_state, "needs")
        assert hasattr(npc_state, "emotional_state")
        assert all(0 <= v <= 1 for v in npc_state.needs.values())


@pytest.fixture
def assert_luna():
    """Fixture that provides custom assertions."""
    return CustomAssertions()
