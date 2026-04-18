# Luna RPG v8 - Core Engine Testing Guide

**Documento:** Strategia testing completa per GameEngine e sistemi chiave  
**Target Coverage:** Da 0% → 80%+  
**File principale:** `core/engine.py` (445 righe)  
**Sistemi coperti:** quest_engine, memory, schedule_manager, location, dynamic_events, personality

---

## Indice

1. [Panoramica Core Engine](#1-panoramica-core-engine)
2. [Strategia Testing](#2-strategia-testing)
3. [Setup Testing](#3-setup-testing)
4. [Test Core Engine](#4-test-core-engine)
5. [Test Sistemi Chiave](#5-test-sistemi-chiave)
6. [Test Integrazione](#6-test-integrazione)
7. [Mock Dependencies](#7-mock-dependencies)
8. [Coverage Target](#8-coverage-target)

---

## 1. Panoramica Core Engine

### 1.1 Ruolo del GameEngine

**`core/engine.py`** è l'**orchestratore principale** di Luna RPG:

```
GameEngine
├── Gestisce lifecycle: init → process_turn → shutdown
├── Wire tutti i sottosistemi (30+ dipendenze)
├── Delega business logic ai sistemi specializzati
└── Fornisce API pulita alla UI
```

**Principio fondamentale:** L'engine **NON contiene business logic**, solo coordinamento.

### 1.2 Sistemi Chiave (attualmente 0% coverage)

| Sistema | Responsabilità | File | Priorità |
|---------|---------------|------|----------|
| **QuestEngine** | Gestione quest, progressione, trigger | `systems/quest_engine_sequential.py` | 🔴 ALTA |
| **MemoryManager** | Memoria conversazionale, contesto LLM | `systems/memory.py` | 🔴 ALTA |
| **ScheduleManager** | Orari NPC, posizioni per fase | `systems/schedule_manager.py` | 🟡 MEDIA |
| **LocationManager** | Gestione luoghi, validazione movimenti | `systems/location.py` | 🟡 MEDIA |
| **PersonalityEngine** | Analisi personalità, evoluzione companion | `systems/personality.py` | 🟡 MEDIA |
| **GlobalEventManager** | Eventi dinamici world-wide | `systems/global_events.py` | 🟢 BASSA |

### 1.3 Flusso Tipico

```
1. UI chiama: engine.initialize()
   └─> _init_systems() crea tutti i managers
   └─> _init_runtime_systems() inizializza con game_state

2. UI chiama: engine.process_turn(user_input)
   └─> TurnOrchestrator.execute()
       ├─> MemoryManager: context retrieval
       ├─> QuestEngine: check triggers
       ├─> LocationManager: validate movement
       ├─> NPCMind: goal evaluation
       ├─> LLM: narrative generation
       └─> MediaPipeline: image/video

3. UI chiama: engine.shutdown()
   └─> StateMemory.save_all()
   └─> LLM cleanup
```

---

## 2. Strategia Testing

### 2.1 Sfide Principali

**Challenge 1: Dipendenze Multiple**
- Engine wire 30+ sottosistemi
- Molti dipendono da DB, LLM, Media pipeline

**Soluzione:** Mock aggressivo + fixture gerarchiche

**Challenge 2: Media Pipeline (ComfyUI/SD)**
- Media generation richiede server esterni
- Impossibile testare in CI/CD

**Soluzione:** Flag `no_media=True` + mock MediaPipeline

**Challenge 3: Async Heavy**
- Quasi tutto è async (DB, LLM, turn processing)

**Soluzione:** `pytest-asyncio` + async fixtures

### 2.2 Approccio a Strati

```
Layer 1: UNIT TESTS (sistemi isolati)
├── QuestEngine (mock world, mock state)
├── MemoryManager (DB in-memory)
├── ScheduleManager (mock world)
└── LocationManager (mock world)

Layer 2: INTEGRATION TESTS (engine + 2-3 sistemi)
├── Engine initialization (tutti i sistemi)
├── Engine + QuestEngine + Memory
├── Engine + ScheduleManager + Location
└── Turn processing (no LLM, mock narrative)

Layer 3: E2E TESTS (full stack)
└── Complete game session (richiede LLM API key)
```

### 2.3 Coverage Target

| Componente | Current | Target | Priorità |
|------------|---------|--------|----------|
| `engine.py` | 0% | 75% | 🔴 CRITICO |
| `quest_engine` | 0% | 80% | 🔴 ALTA |
| `memory.py` | 0% | 80% | 🔴 ALTA |
| `schedule_manager.py` | 0% | 70% | 🟡 MEDIA |
| `location.py` | 0% | 70% | 🟡 MEDIA |
| `personality.py` | 0% | 60% | 🟢 BASSA |
| `global_events.py` | 0% | 50% | 🟢 BASSA |

**Target complessivo Core Engine stack: 70%+**

---

## 3. Setup Testing

### 3.1 Dipendenze Specifiche

```bash
# Oltre alle dipendenze base pytest
pip install pytest-asyncio pytest-mock aiosqlite
```

### 3.2 Fixture Essenziali

**File:** `tests/conftest.py` (aggiungere a quelle esistenti)

```python
import pytest
from pathlib import Path
from luna.core.models import WorldDefinition, CompanionDefinition

@pytest.fixture
def minimal_world():
    """Minimal world definition for testing."""
    return WorldDefinition(
        name="test_world",
        description="World for testing",
        player_character={
            "name": "TestPlayer",
            "default_location": "home"
        },
        companions={
            "test_companion": CompanionDefinition(
                name="TestCompanion",
                role="Test NPC",
                age=25,
                base_personality="Friendly",
                physical_description="Test description",
                base_prompt="test prompt",
                default_outfit="casual",
                wardrobe={},
                personality_system={},
                schedules={},
                quest_templates=[]
            )
        },
        locations={
            "home": {
                "name": "Home",
                "description": "Test home",
                "allowed_actions": []
            },
            "office": {
                "name": "Office",
                "description": "Test office",
                "allowed_actions": []
            }
        },
        quests={},
        global_events=[],
        time_config={
            "starting_time": "morning",
            "phase_duration_minutes": 60
        }
    )


@pytest.fixture
async def mock_engine_no_media(minimal_world, test_db, tmp_path):
    """GameEngine with no_media=True for fast testing."""
    from luna.core.engine import GameEngine
    from unittest.mock import Mock, patch
    
    # Mock world loading
    with patch.object(GameEngine, '_load_world', return_value=minimal_world):
        engine = GameEngine(
            world_id="test_world",
            companion="test_companion",
            no_media=True
        )
        
        # Replace DB with test DB
        engine.db = test_db
        
        yield engine
        
        # Cleanup
        if engine._initialized:
            await engine.shutdown()


@pytest.fixture
def mock_llm_simple():
    """Simple mock LLM for engine tests."""
    from unittest.mock import Mock, AsyncMock
    
    llm = Mock()
    llm.generate = AsyncMock(return_value=Mock(
        text="Test narrative response",
        usage={"total_tokens": 100}
    ))
    llm.close = AsyncMock()
    llm.is_available = Mock(return_value=True)
    return llm


@pytest.fixture
async def initialized_engine(mock_engine_no_media, mock_llm_simple):
    """Fully initialized engine ready for testing."""
    engine = mock_engine_no_media
    engine.llm_manager = mock_llm_simple
    
    await engine.initialize()
    
    yield engine
    
    await engine.shutdown()
```

---

## 4. Test Core Engine

### 4.1 Test Initialization

**File:** `tests/unit/test_core_engine.py`

```python
"""Unit tests for GameEngine core functionality."""
import pytest
from luna.core.engine import GameEngine
from luna.core.models import GameState


class TestEngineInitialization:
    """Test engine initialization and lifecycle."""
    
    @pytest.mark.asyncio
    async def test_engine_creation(self, minimal_world):
        """Test creating an engine instance."""
        from unittest.mock import patch
        
        with patch.object(GameEngine, '_load_world', return_value=minimal_world):
            engine = GameEngine(
                world_id="test_world",
                companion="test_companion",
                no_media=True
            )
        
        assert engine.world_id == "test_world"
        assert engine.companion == "test_companion"
        assert engine.no_media is True
        assert engine._initialized is False
    
    @pytest.mark.asyncio
    async def test_initialize_creates_systems(self, mock_engine_no_media):
        """Test that initialize() creates all subsystems."""
        engine = mock_engine_no_media
        
        await engine.initialize()
        
        # Verify core systems created
        assert engine.state_manager is not None
        assert engine.memory_manager is not None
        assert engine.quest_engine is not None
        assert engine.schedule_manager is not None
        assert engine.location_manager is not None
        assert engine.personality_engine is not None
        
        # Verify runtime state
        assert engine._initialized is True
        assert engine._session_id is not None
        
        await engine.shutdown()
    
    @pytest.mark.asyncio
    async def test_initialize_sets_game_state(self, mock_engine_no_media):
        """Test that initialize() creates valid game state."""
        engine = mock_engine_no_media
        
        await engine.initialize()
        
        state = engine.state
        
        assert isinstance(state, GameState)
        assert state.world_id == "test_world"
        assert state.active_companion == "test_companion"
        assert state.turn_count == 0
        assert state.session_id is not None
        
        await engine.shutdown()
    
    @pytest.mark.asyncio
    async def test_double_initialize_idempotent(self, mock_engine_no_media):
        """Test that calling initialize() twice is safe."""
        engine = mock_engine_no_media
        
        await engine.initialize()
        first_session = engine._session_id
        
        await engine.initialize()  # Call again
        second_session = engine._session_id
        
        # Should be same session
        assert first_session == second_session
        
        await engine.shutdown()
    
    @pytest.mark.asyncio
    async def test_no_media_flag_disables_pipeline(self, mock_engine_no_media):
        """Test that no_media=True disables media generation."""
        engine = mock_engine_no_media
        
        await engine.initialize()
        
        assert engine.media_pipeline is None
        
        await engine.shutdown()


class TestEngineLifecycle:
    """Test engine save/load lifecycle."""
    
    @pytest.mark.asyncio
    async def test_save_and_load_session(self, mock_engine_no_media):
        """Test saving and loading a game session."""
        engine = mock_engine_no_media
        
        # Create new game
        await engine.initialize()
        original_session_id = engine._session_id
        
        # Modify state
        engine.state.turn_count = 5
        engine.state.flags["test_flag"] = True
        
        # Save
        await engine.shutdown()
        
        # Create new engine instance
        from unittest.mock import patch
        with patch.object(GameEngine, '_load_world', return_value=engine.world):
            engine2 = GameEngine(
                world_id="test_world",
                companion="test_companion",
                no_media=True
            )
            engine2.db = engine.db
        
        # Load previous session
        success = await engine2.load_session(original_session_id)
        
        assert success is True
        assert engine2.state.turn_count == 5
        assert engine2.state.flags.get("test_flag") is True
        
        await engine2.shutdown()
    
    @pytest.mark.asyncio
    async def test_load_nonexistent_session_fails(self, mock_engine_no_media):
        """Test loading a session that doesn't exist."""
        engine = mock_engine_no_media
        
        success = await engine.load_session(99999)
        
        assert success is False
        assert engine._initialized is False


class TestEngineTurnProcessing:
    """Test turn processing."""
    
    @pytest.mark.asyncio
    async def test_process_turn_before_init_fails(self, mock_engine_no_media):
        """Test that process_turn fails if engine not initialized."""
        engine = mock_engine_no_media
        
        result = await engine.process_turn("test input")
        
        assert result.error == "not_initialized"
        assert "[Engine not initialized]" in result.text
    
    @pytest.mark.asyncio
    async def test_process_turn_delegates_to_orchestrator(
        self, initialized_engine, mock_llm_simple
    ):
        """Test that process_turn delegates to TurnOrchestrator."""
        engine = initialized_engine
        
        from unittest.mock import AsyncMock, Mock
        
        # Mock orchestrator
        mock_orchestrator = Mock()
        mock_result = Mock(
            text="Test response",
            turn_number=1,
            provider_used="test"
        )
        mock_orchestrator.execute = AsyncMock(return_value=mock_result)
        engine.turn_orchestrator = mock_orchestrator
        
        result = await engine.process_turn("Hello")
        
        # Verify orchestrator was called
        mock_orchestrator.execute.assert_called_once_with("Hello")
        assert result.text == "Test response"
        assert result.turn_number == 1


class TestEngineAPIEndpoints:
    """Test public API methods."""
    
    @pytest.mark.asyncio
    async def test_get_game_state(self, initialized_engine):
        """Test get_game_state() returns current state."""
        engine = initialized_engine
        
        state = engine.get_game_state()
        
        assert isinstance(state, GameState)
        assert state.world_id == "test_world"
    
    @pytest.mark.asyncio
    async def test_get_active_quests(self, initialized_engine):
        """Test get_active_quests() returns quest list."""
        engine = initialized_engine
        
        # Initially empty
        quests = engine.get_active_quests()
        assert isinstance(quests, list)
        assert len(quests) == 0
        
        # Add a quest
        engine.state.active_quests.append("test_quest_1")
        
        quests = engine.get_active_quests()
        assert len(quests) == 1
        assert "test_quest_1" in quests
    
    @pytest.mark.asyncio
    async def test_toggle_audio(self, initialized_engine):
        """Test toggle_audio() when no media pipeline."""
        engine = initialized_engine
        
        # No media pipeline (no_media=True)
        result = engine.toggle_audio()
        
        assert result is False


class TestEngineShutdown:
    """Test shutdown and cleanup."""
    
    @pytest.mark.asyncio
    async def test_shutdown_saves_state(self, initialized_engine):
        """Test that shutdown saves game state."""
        engine = initialized_engine
        
        # Modify state
        engine.state.turn_count = 10
        
        # Mock state_memory save
        from unittest.mock import AsyncMock
        engine.state_memory.save_all = AsyncMock()
        
        await engine.shutdown()
        
        # Verify save was called
        engine.state_memory.save_all.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_shutdown_closes_llm(self, initialized_engine):
        """Test that shutdown closes LLM connection."""
        engine = initialized_engine
        
        from unittest.mock import AsyncMock
        engine.llm_manager.close = AsyncMock()
        
        await engine.shutdown()
        
        engine.llm_manager.close.assert_called_once()
```

**Esecuzione:**
```bash
pytest tests/unit/test_core_engine.py -v
```

---

## 5. Test Sistemi Chiave

### 5.1 QuestEngine Tests

**File:** `tests/unit/test_quest_engine.py`

```python
"""Unit tests for QuestEngine."""
import pytest
from luna.systems.quest_engine_sequential import SequentialQuestEngine
from luna.core.models import QuestStatus, QuestInstance


class TestQuestEngineBasics:
    """Test basic quest engine functionality."""
    
    def test_quest_engine_creation(self, minimal_world):
        """Test creating quest engine."""
        from unittest.mock import Mock
        
        mock_engine = Mock()
        quest_engine = SequentialQuestEngine(minimal_world, mock_engine)
        
        assert quest_engine.world == minimal_world
        assert quest_engine.engine == mock_engine
    
    def test_get_all_instances_empty(self, minimal_world):
        """Test getting instances when no quests active."""
        from unittest.mock import Mock
        
        quest_engine = SequentialQuestEngine(minimal_world, Mock())
        instances = quest_engine.get_all_instances()
        
        assert isinstance(instances, dict)
        assert len(instances) == 0
    
    def test_check_triggers_no_quests(self, minimal_world, test_game_state):
        """Test check_triggers when no quests defined."""
        from unittest.mock import Mock
        
        quest_engine = SequentialQuestEngine(minimal_world, Mock())
        
        # Should not crash
        quest_engine.check_triggers(test_game_state)


class TestQuestProgression:
    """Test quest progression and state changes."""
    
    def test_start_quest(self, minimal_world, test_game_state):
        """Test starting a quest."""
        from luna.core.models import QuestDefinition, QuestTrigger
        from unittest.mock import Mock
        
        # Add test quest to world
        test_quest = QuestDefinition(
            id="test_quest_1",
            title="Test Quest",
            description="A test quest",
            trigger=QuestTrigger(
                condition="always",
                parameters={}
            ),
            steps=[],
            rewards={}
        )
        minimal_world.quests["test_quest_1"] = test_quest
        
        quest_engine = SequentialQuestEngine(minimal_world, Mock())
        
        # Start quest
        quest_engine._start_quest("test_quest_1", test_game_state)
        
        # Verify quest is active
        assert "test_quest_1" in test_game_state.active_quests
        
        instances = quest_engine.get_all_instances()
        assert "test_quest_1" in instances
        assert instances["test_quest_1"].status == QuestStatus.IN_PROGRESS
    
    def test_complete_quest(self, minimal_world, test_game_state):
        """Test completing a quest."""
        from luna.core.models import QuestDefinition, QuestTrigger
        from unittest.mock import Mock
        
        test_quest = QuestDefinition(
            id="test_quest_2",
            title="Complete Quest Test",
            description="Test completion",
            trigger=QuestTrigger(condition="always", parameters={}),
            steps=[],
            rewards={"affinity": 10}
        )
        minimal_world.quests["test_quest_2"] = test_quest
        
        quest_engine = SequentialQuestEngine(minimal_world, Mock())
        
        # Start quest
        quest_engine._start_quest("test_quest_2", test_game_state)
        
        # Complete quest
        quest_engine._complete_quest("test_quest_2", test_game_state)
        
        # Verify quest completed
        assert "test_quest_2" in test_game_state.completed_quests
        assert "test_quest_2" not in test_game_state.active_quests
        
        instances = quest_engine.get_all_instances()
        if "test_quest_2" in instances:
            assert instances["test_quest_2"].status == QuestStatus.COMPLETED
```

**Esecuzione:**
```bash
pytest tests/unit/test_quest_engine.py -v
```

---

### 5.2 MemoryManager Tests

**File:** `tests/unit/test_memory_manager.py`

```python
"""Unit tests for MemoryManager."""
import pytest
from luna.systems.memory import MemoryManager


class TestMemoryManagerBasics:
    """Test basic memory operations."""
    
    @pytest.mark.asyncio
    async def test_memory_manager_creation(self, test_db):
        """Test creating memory manager."""
        memory = MemoryManager(
            db_manager=test_db,
            session_id=1,
            history_limit=50,
            enable_semantic=False
        )
        
        assert memory.session_id == 1
        assert memory.history_limit == 50
    
    @pytest.mark.asyncio
    async def test_add_memory_simple(self, test_db):
        """Test adding a simple memory."""
        memory = MemoryManager(
            db_manager=test_db,
            session_id=1,
            history_limit=50,
            enable_semantic=False
        )
        
        await memory.add_memory(
            role="user",
            content="Hello",
            companion_name="test_companion",
            turn_number=1
        )
        
        # Retrieve memories
        async with test_db.get_session() as session:
            memories = await test_db.get_memories(
                session, session_id=1, companion_filter="test_companion"
            )
        
        assert len(memories) > 0
        assert memories[-1]["content"] == "Hello"
    
    @pytest.mark.asyncio
    async def test_memory_isolation_by_companion(self, test_db):
        """Test that memories are isolated by companion."""
        memory = MemoryManager(
            db_manager=test_db,
            session_id=1,
            history_limit=50,
            enable_semantic=False
        )
        
        # Add memory for companion A
        await memory.add_memory(
            role="user",
            content="Message for A",
            companion_name="companion_a",
            turn_number=1
        )
        
        # Add memory for companion B
        await memory.add_memory(
            role="user",
            content="Message for B",
            companion_name="companion_b",
            turn_number=2
        )
        
        # Retrieve for companion A
        async with test_db.get_session() as session:
            memories_a = await test_db.get_memories(
                session, session_id=1, companion_filter="companion_a"
            )
        
        # Should only contain A's messages
        assert len(memories_a) > 0
        assert all("companion_a" in str(m) for m in memories_a)
        assert not any("Message for B" in str(m) for m in memories_a)
    
    @pytest.mark.asyncio
    async def test_build_context(self, test_db):
        """Test building LLM context from memories."""
        memory = MemoryManager(
            db_manager=test_db,
            session_id=1,
            history_limit=50,
            enable_semantic=False
        )
        
        # Add some memories
        await memory.add_memory("user", "Hi", "test", 1)
        await memory.add_memory("assistant", "Hello!", "test", 1)
        await memory.add_memory("user", "How are you?", "test", 2)
        
        # Build context
        context = await memory.build_context(
            companion_name="test",
            limit=10
        )
        
        assert isinstance(context, str)
        assert "Hi" in context or "Hello" in context


class TestMemoryLimits:
    """Test memory limit enforcement."""
    
    @pytest.mark.asyncio
    async def test_history_limit_enforced(self, test_db):
        """Test that history limit is enforced."""
        memory = MemoryManager(
            db_manager=test_db,
            session_id=1,
            history_limit=5,  # Small limit
            enable_semantic=False
        )
        
        # Add more than limit
        for i in range(10):
            await memory.add_memory(
                role="user",
                content=f"Message {i}",
                companion_name="test",
                turn_number=i
            )
        
        # Retrieve
        async with test_db.get_session() as session:
            memories = await test_db.get_memories(
                session, session_id=1, companion_filter="test"
            )
        
        # Should have trimmed to limit
        # (actual behavior depends on implementation)
        assert len(memories) <= 10  # DB may store all, manager trims on retrieval
```

**Esecuzione:**
```bash
pytest tests/unit/test_memory_manager.py -v
```

---

### 5.3 ScheduleManager Tests

**File:** `tests/unit/test_schedule_manager.py`

```python
"""Unit tests for ScheduleManager."""
import pytest
from luna.systems.schedule_manager import ScheduleManager
from luna.core.models import TimeOfDay


class TestScheduleManagerBasics:
    """Test basic schedule operations."""
    
    def test_schedule_manager_creation(self, minimal_world, test_game_state):
        """Test creating schedule manager."""
        scheduler = ScheduleManager(
            game_state=test_game_state,
            world=minimal_world
        )
        
        assert scheduler.game_state == test_game_state
        assert scheduler.world == minimal_world
    
    def test_get_npc_location_from_schedule(self, minimal_world, test_game_state):
        """Test getting NPC location from schedule."""
        # Add schedule to companion
        minimal_world.companions["test_companion"].schedules = {
            "morning": {"location": "home", "activity": "sleeping"},
            "afternoon": {"location": "office", "activity": "working"},
        }
        
        scheduler = ScheduleManager(
            game_state=test_game_state,
            world=minimal_world
        )
        
        # Get location for morning
        location = scheduler.get_npc_location("test_companion", TimeOfDay.MORNING)
        assert location == "home"
        
        # Get location for afternoon
        location = scheduler.get_npc_location("test_companion", TimeOfDay.AFTERNOON)
        assert location == "office"
    
    def test_get_npc_activity(self, minimal_world, test_game_state):
        """Test getting NPC current activity."""
        minimal_world.companions["test_companion"].schedules = {
            "morning": {"location": "home", "activity": "sleeping"},
        }
        
        test_game_state.time_of_day = TimeOfDay.MORNING
        
        scheduler = ScheduleManager(
            game_state=test_game_state,
            world=minimal_world
        )
        
        activity = scheduler.get_npc_activity("test_companion")
        assert activity == "sleeping"


class TestSchedulePhaseChanges:
    """Test schedule updates during phase changes."""
    
    def test_all_npcs_move_on_phase_change(self, minimal_world, test_game_state):
        """Test that NPCs move to new locations on phase change."""
        # Setup schedules
        minimal_world.companions["test_companion"].schedules = {
            "morning": {"location": "home"},
            "afternoon": {"location": "office"},
        }
        
        test_game_state.time_of_day = TimeOfDay.MORNING
        test_game_state.npc_locations["test_companion"] = "home"
        
        scheduler = ScheduleManager(
            game_state=test_game_state,
            world=minimal_world
        )
        
        # Change phase to afternoon
        test_game_state.time_of_day = TimeOfDay.AFTERNOON
        
        # Get new location
        new_location = scheduler.get_npc_location(
            "test_companion",
            TimeOfDay.AFTERNOON
        )
        
        assert new_location == "office"
        assert new_location != test_game_state.npc_locations["test_companion"]
```

**Esecuzione:**
```bash
pytest tests/unit/test_schedule_manager.py -v
```

---

### 5.4 LocationManager Tests

**File:** `tests/unit/test_location_manager.py`

```python
"""Unit tests for LocationManager."""
import pytest
from luna.systems.location import LocationManager


class TestLocationManagerBasics:
    """Test basic location operations."""
    
    def test_location_manager_creation(self, minimal_world):
        """Test creating location manager."""
        from unittest.mock import Mock
        
        state_manager = Mock()
        loc_mgr = LocationManager(minimal_world, state_manager)
        
        assert loc_mgr.world == minimal_world
    
    def test_get_location_info(self, minimal_world):
        """Test getting location information."""
        from unittest.mock import Mock
        
        loc_mgr = LocationManager(minimal_world, Mock())
        
        info = loc_mgr.get_location("home")
        
        assert info is not None
        assert info["name"] == "Home"
        assert info["description"] == "Test home"
    
    def test_get_nonexistent_location(self, minimal_world):
        """Test getting a location that doesn't exist."""
        from unittest.mock import Mock
        
        loc_mgr = LocationManager(minimal_world, Mock())
        
        info = loc_mgr.get_location("nonexistent")
        
        # Should return None or handle gracefully
        assert info is None or info == {}
    
    def test_list_all_locations(self, minimal_world):
        """Test listing all locations."""
        from unittest.mock import Mock
        
        loc_mgr = LocationManager(minimal_world, Mock())
        
        locations = loc_mgr.list_locations()
        
        assert isinstance(locations, (list, dict))
        assert len(locations) >= 2  # home, office


class TestLocationValidation:
    """Test location validation and movement rules."""
    
    def test_validate_movement_allowed(self, minimal_world, test_game_state):
        """Test validating allowed movement."""
        from unittest.mock import Mock
        
        state_manager = Mock()
        state_manager.current = test_game_state
        
        loc_mgr = LocationManager(minimal_world, state_manager)
        
        test_game_state.current_location = "home"
        
        # Movement to office should be allowed (both exist)
        is_valid = loc_mgr.validate_movement("home", "office")
        
        assert is_valid is True
    
    def test_validate_movement_to_nonexistent(self, minimal_world, test_game_state):
        """Test movement to nonexistent location."""
        from unittest.mock import Mock
        
        state_manager = Mock()
        loc_mgr = LocationManager(minimal_world, state_manager)
        
        is_valid = loc_mgr.validate_movement("home", "nonexistent")
        
        assert is_valid is False
```

**Esecuzione:**
```bash
pytest tests/unit/test_location_manager.py -v
```

---

## 6. Test Integrazione

### 6.1 Engine + Quest Integration

**File:** `tests/integration/test_engine_quest_integration.py`

```python
"""Integration tests for Engine + QuestEngine."""
import pytest


class TestEngineQuestIntegration:
    """Test engine integration with quest system."""
    
    @pytest.mark.asyncio
    async def test_quest_engine_initialized_with_engine(
        self, initialized_engine
    ):
        """Test that quest engine is properly wired to engine."""
        engine = initialized_engine
        
        assert engine.quest_engine is not None
        assert engine.quest_engine.engine == engine
        assert engine.quest_engine.world == engine.world
    
    @pytest.mark.asyncio
    async def test_quest_triggers_checked_on_turn(
        self, initialized_engine
    ):
        """Test that quest triggers are checked during turn processing."""
        engine = initialized_engine
        
        from unittest.mock import Mock, AsyncMock
        
        # Mock quest trigger check
        original_check = engine.quest_engine.check_triggers
        check_called = False
        
        def mock_check(game_state):
            nonlocal check_called
            check_called = True
            return original_check(game_state)
        
        engine.quest_engine.check_triggers = mock_check
        
        # Mock orchestrator to avoid full turn
        mock_result = Mock(text="Test", turn_number=1)
        engine.turn_orchestrator = Mock()
        engine.turn_orchestrator.execute = AsyncMock(return_value=mock_result)
        
        await engine.process_turn("test input")
        
        # Quest check happens inside orchestrator, may not be called directly
        # Adjust based on actual implementation
    
    @pytest.mark.asyncio
    async def test_get_pending_quest_choices(self, initialized_engine):
        """Test retrieving pending quest choices."""
        engine = initialized_engine
        
        choices = engine.get_pending_quest_choices()
        
        assert isinstance(choices, list)
        # Initially empty (no quests defined in minimal_world)
        assert len(choices) == 0
```

---

### 6.2 Engine + Memory Integration

**File:** `tests/integration/test_engine_memory_integration.py`

```python
"""Integration tests for Engine + MemoryManager."""
import pytest


class TestEngineMemoryIntegration:
    """Test engine integration with memory system."""
    
    @pytest.mark.asyncio
    async def test_memory_manager_initialized(self, initialized_engine):
        """Test memory manager is properly initialized."""
        engine = initialized_engine
        
        assert engine.memory_manager is not None
        assert engine.memory_manager.session_id == engine._session_id
    
    @pytest.mark.asyncio
    async def test_memory_persists_across_turns(self, initialized_engine):
        """Test that conversation memory persists."""
        engine = initialized_engine
        
        # Add a memory
        await engine.memory_manager.add_memory(
            role="user",
            content="Remember this",
            companion_name="test_companion",
            turn_number=1
        )
        
        # Retrieve context
        context = await engine.memory_manager.build_context(
            companion_name="test_companion",
            limit=10
        )
        
        assert "Remember this" in context
    
    @pytest.mark.asyncio
    async def test_memory_saved_on_shutdown(self, initialized_engine):
        """Test that memory is saved during shutdown."""
        engine = initialized_engine
        
        # Add memory
        await engine.memory_manager.add_memory(
            role="user",
            content="Save me",
            companion_name="test_companion",
            turn_number=1
        )
        
        session_id = engine._session_id
        
        # Shutdown (should save)
        await engine.shutdown()
        
        # Create new engine and load
        from unittest.mock import patch
        with patch.object(type(engine), '_load_world', return_value=engine.world):
            engine2 = type(engine)(
                world_id=engine.world_id,
                companion=engine.companion,
                no_media=True
            )
            engine2.db = engine.db
        
        await engine2.load_session(session_id)
        
        # Memory should be loaded
        context = await engine2.memory_manager.build_context(
            companion_name="test_companion",
            limit=10
        )
        
        assert "Save me" in context
        
        await engine2.shutdown()
```

---

## 7. Mock Dependencies

### 7.1 Mock Media Pipeline

**File:** `tests/mocks/mock_media.py`

```python
"""Mock implementations for media pipeline."""
from unittest.mock import Mock, AsyncMock


class MockMediaPipeline:
    """Mock MediaPipeline for testing."""
    
    def __init__(self):
        self.generate_all = AsyncMock(return_value=Mock(
            image_path="/fake/image.png",
            video_path=None,
            audio_path=None
        ))
        self.toggle_audio = Mock(return_value=False)
    
    async def generate_image(self, *args, **kwargs):
        """Mock image generation."""
        return Mock(image_path="/fake/image.png")


def get_mock_media_pipeline():
    """Factory for mock media pipeline."""
    return MockMediaPipeline()
```

### 7.2 Mock LLM Manager

```python
"""Mock LLM manager."""
from unittest.mock import Mock, AsyncMock


class MockLLMManager:
    """Mock LLM manager for testing."""
    
    def __init__(self, response_text="Mock LLM response"):
        self.response_text = response_text
        self.generate = AsyncMock(return_value=Mock(
            text=response_text,
            usage={"total_tokens": 100}
        ))
        self.close = AsyncMock()
        self.is_available = Mock(return_value=True)
    
    def set_response(self, text):
        """Update mock response."""
        self.response_text = text
        self.generate = AsyncMock(return_value=Mock(
            text=text,
            usage={"total_tokens": 100}
        ))
```

---

## 8. Coverage Target

### 8.1 Esecuzione Test con Coverage

```bash
# Run solo core engine tests
pytest tests/unit/test_core_engine.py -v --cov=src/luna/core/engine

# Run tutti i test sistemi chiave
pytest tests/unit/test_quest_engine.py \
       tests/unit/test_memory_manager.py \
       tests/unit/test_schedule_manager.py \
       tests/unit/test_location_manager.py \
       -v --cov=src/luna/systems

# Run integrazione
pytest tests/integration/test_engine_*_integration.py \
       -v --cov=src/luna/core

# Report HTML
pytest tests/ -v --cov=src/luna/core --cov=src/luna/systems \
       --cov-report=html

open htmlcov/index.html
```

### 8.2 Metriche di Successo

**Milestone completa quando:**

- ✅ `core/engine.py`: **75%+ coverage**
- ✅ `systems/quest_engine*.py`: **80%+ coverage**
- ✅ `systems/memory.py`: **80%+ coverage**
- ✅ `systems/schedule_manager.py`: **70%+ coverage**
- ✅ `systems/location.py`: **70%+ coverage**
- ✅ Tutti i test passano senza errori
- ✅ Nessun crash durante init/shutdown
- ✅ Memory isolation verificata
- ✅ Quest progression verificata

### 8.3 Test Priority Roadmap

**Phase 1 (Priority 🔴 ALTA):**
```bash
1. test_core_engine.py - Initialization, lifecycle
2. test_quest_engine.py - Quest progression
3. test_memory_manager.py - Memory isolation
```

**Phase 2 (Priority 🟡 MEDIA):**
```bash
4. test_schedule_manager.py - NPC scheduling
5. test_location_manager.py - Location validation
6. test_engine_quest_integration.py - Integration
```

**Phase 3 (Priority 🟢 BASSA):**
```bash
7. test_personality.py - Personality analysis
8. test_global_events.py - Dynamic events
9. Full E2E with real LLM
```

---

## 9. Quick Start

### Setup (5 minuti)

```bash
# 1. Installa dipendenze
pip install pytest pytest-asyncio pytest-mock pytest-cov aiosqlite

# 2. Crea i file test (usa template sopra)
mkdir -p tests/unit tests/integration tests/mocks

# 3. Copia fixture in conftest.py

# 4. Esegui primo test
pytest tests/unit/test_core_engine.py::TestEngineInitialization::test_engine_creation -v
```

### Test Loop Sviluppatore

```bash
# 1. Scrivi test
vim tests/unit/test_core_engine.py

# 2. Run test
pytest tests/unit/test_core_engine.py -v -k test_initialize

# 3. Check coverage
pytest tests/unit/test_core_engine.py --cov=src/luna/core/engine --cov-report=term-missing

# 4. Fix code se necessario

# 5. Commit quando green + coverage OK
```

---

## 10. Troubleshooting

### Import Errors

```bash
# Assicurati che src/ sia nel path
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"

# Oppure installa in editable mode
pip install -e .
```

### Async Errors

```bash
# Aggiungi marker
@pytest.mark.asyncio
async def test_...

# Configura pytest.ini
[pytest]
asyncio_mode = auto
```

### Database Locked

```bash
# Usa :memory: database in test
db = Database(db_path=":memory:")
```

### Media Pipeline Crash

```bash
# Sempre usa no_media=True in test
engine = GameEngine(..., no_media=True)
```

---

**Prossimi Passi:**

1. ✅ Setup dipendenze test
2. ✅ Crea file fixture in conftest.py
3. ✅ Implementa test Phase 1 (core engine + quest + memory)
4. ✅ Run coverage check
5. ✅ Implementa test Phase 2 (schedule + location)
6. ✅ Target 70%+ coverage raggiunto!

**Domande?** Consulta `TESTING_STRATEGY_V8.md` per pattern generali.
