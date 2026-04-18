# Luna RPG v8 — Testing Strategy & Execution Guide

**Documento:** Piano di test completo per Milestone M7  
**Data:** 2026-04-12  
**Versione:** 1.0  
**Stato:** DA IMPLEMENTARE

---

## Indice

1. [Setup Ambiente Test](#1-setup-ambiente-test)
2. [Test Unitari](#2-test-unitari)
3. [Test di Integrazione](#3-test-di-integrazione)
4. [Test End-to-End](#4-test-end-to-end)
5. [Test Specifici v8](#5-test-specifici-v8)
6. [Test Regression](#6-test-regression)
7. [Test Performance](#7-test-performance)
8. [Criteri di Accettazione](#8-criteri-di-accettazione)
9. [Esecuzione Test](#9-esecuzione-test)

---

## 1. Setup Ambiente Test

### 1.1 Prerequisiti

```bash
# Clone del progetto
cd /path/to/luna-rpg-v8

# Creazione virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# oppure
.venv\Scripts\activate     # Windows

# Installazione dipendenze
pip install -e .
pip install -r requirements-dev.txt  # se esiste

# Dipendenze test
pip install pytest pytest-asyncio pytest-cov pytest-mock
pip install eval7  # CRITICO per poker
```

### 1.2 File .env di Test

Creare `.env.test` con configurazione isolata:

```bash
# .env.test
LUNA_DB_PATH=./test_data/test_game.db
LUNA_DEBUG_MODE=1
LUNA_DEBUG_NO_MEDIA=1  # Skip generazione immagini/video

# API Keys (opzionale per test con mock)
ANTHROPIC_API_KEY=test_key_mock
GEMINI_API_KEY=test_key_mock

# Test config
LUNA_TEST_MODE=1
LUNA_FAST_SIMULATION=1  # Simula tick più velocemente
```

### 1.3 Struttura Directory Test

```
tests/
├── __init__.py
├── conftest.py              # Fixture pytest condivise
├── fixtures/                # Dati test (world config, save files)
│   ├── test_worlds/
│   └── test_saves/
├── unit/                    # Test unitari
│   ├── test_poker_engine.py
│   ├── test_npc_mind.py
│   ├── test_tension_tracker.py
│   └── ...
├── integration/             # Test integrazione
│   ├── test_poker_full_hand.py
│   ├── test_npc_persistence.py
│   └── ...
└── e2e/                     # Test end-to-end
    ├── test_full_session.py
    └── test_poker_strip_flow.py
```

---

## 2. Test Unitari

### 2.1 Poker Engine (engine_v2.py)

**File:** `tests/unit/test_poker_engine.py`

```python
import pytest
from luna.systems.mini_games.poker.engine_v2 import GameState, GameConfig, Player

class TestPokerEngine:
    """Test del motore poker Texas Hold'em."""
    
    def test_initial_deal(self):
        """Verifica distribuzione carte iniziale."""
        cfg = GameConfig(small_blind=50, big_blind=100, starting_stack=1000)
        players = [
            Player(player_id="player", stack=1000, is_active=True),
            Player(player_id="luna", stack=1000, is_active=True),
        ]
        state = GameState(cfg=cfg, players=players)
        state.start_hand()
        
        # Ogni giocatore ha 2 carte
        assert len(state.hands["player"]) == 2
        assert len(state.hands["luna"]) == 2
        
        # Board vuoto preflop
        assert len(state.board) == 0
        
        # Blind postati
        assert state.pot > 0
        assert state.players[0].bet_this_street > 0  # small blind
        assert state.players[1].bet_this_street > 0  # big blind
    
    def test_preflop_betting(self):
        """Verifica betting round preflop."""
        cfg = GameConfig(small_blind=50, big_blind=100, starting_stack=1000)
        players = [
            Player(player_id="player", stack=1000, is_active=True),
            Player(player_id="luna", stack=1000, is_active=True),
        ]
        state = GameState(cfg=cfg, players=players)
        state.start_hand()
        
        # Player call
        legal = state.legal_actions("player")
        assert legal.get("call") == True
        state.act_call("player")
        
        # Luna check
        state.act_check("luna")
        
        # Avanza a flop
        state.settle_and_next_street_if_needed()
        assert state.street == "flop"
        assert len(state.board) == 3
    
    def test_raise_logic(self):
        """Verifica logica rilancio."""
        cfg = GameConfig(small_blind=50, big_blind=100, starting_stack=1000)
        players = [
            Player(player_id="player", stack=1000, is_active=True),
            Player(player_id="luna", stack=1000, is_active=True),
        ]
        state = GameState(cfg=cfg, players=players)
        state.start_hand()
        
        # Player raise 300
        state.act_raise("player", 300)
        assert state.players[0].bet_this_street == 300
        
        # Luna deve almeno chiamare 300
        legal = state.legal_actions("luna")
        assert legal.get("call") == True
        assert state.to_call("luna") == 300
    
    def test_all_in_logic(self):
        """Verifica all-in con stack diversi."""
        cfg = GameConfig(small_blind=50, big_blind=100, starting_stack=1000)
        players = [
            Player(player_id="player", stack=500, is_active=True),
            Player(player_id="luna", stack=1000, is_active=True),
        ]
        state = GameState(cfg=cfg, players=players)
        state.start_hand()
        
        # Player all-in (500 chips)
        state.act_allin("player")
        assert state.players[0].stack == 0
        assert state.players[0].total_bet == 500
        
        # Luna call
        state.act_call("luna")
        
        # Side pot non dovrebbe esistere (solo 2 giocatori)
        state.settle_and_next_street_if_needed()
        assert len(state.side_pots) <= 1
    
    def test_showdown_winner(self):
        """Verifica showdown con eval7."""
        cfg = GameConfig(small_blind=50, big_blind=100, starting_stack=1000)
        players = [
            Player(player_id="player", stack=1000, is_active=True),
            Player(player_id="luna", stack=1000, is_active=True),
        ]
        state = GameState(cfg=cfg, players=players)
        state.start_hand()
        
        # Simula fino a river
        state.act_call("player")
        state.act_check("luna")
        state.settle_and_next_street_if_needed()  # flop
        
        state.act_check("player")
        state.act_check("luna")
        state.settle_and_next_street_if_needed()  # turn
        
        state.act_check("player")
        state.act_check("luna")
        state.settle_and_next_street_if_needed()  # river
        
        state.act_check("player")
        state.act_check("luna")
        state.settle_and_next_street_if_needed()  # showdown
        
        assert state.street == "showdown"
        # Verifica che un vincitore esista
        winners = state.settle_showdown()
        assert len(winners) > 0


class TestPokerAgents:
    """Test AI agents poker."""
    
    def test_risk_agent_fold(self):
        """Verifica che bot folda con equity bassa."""
        from luna.systems.mini_games.poker.agents import RiskAgent, AgentContext, RiskProfile
        import random
        
        profile = RiskProfile(aggression=0.3, bluff=0.2)
        ctx = AgentContext(rng=random.Random(42))
        agent = RiskAgent(profile, ctx)
        
        # Simula stato con equity pessima (0.1 = 10%)
        # Il bot dovrebbe foldare
        # (test specifico richiede mock di GameState)
        pass  # TODO: implement con mock state
    
    def test_risk_profile_modification(self):
        """Verifica modifica personalità dopo strip."""
        from luna.systems.mini_games.poker.agents import RiskProfile
        
        profile = RiskProfile(aggression=0.5, bluff=0.3)
        
        # Livello strip 3: embarrassed → aggression down
        profile.aggression -= 0.15
        profile.bluff -= 0.05
        
        assert profile.aggression == 0.35
        assert profile.bluff == 0.25
```

**Esecuzione:**
```bash
pytest tests/unit/test_poker_engine.py -v
```

---

### 2.2 NPCMind System

**File:** `tests/unit/test_npc_mind.py`

```python
import pytest
from luna.systems.npc_mind import NPCMindManager, NPCState

class TestNPCMind:
    """Test sistema psicologico NPC."""
    
    def test_need_accumulation(self):
        """Verifica accumulo bisogni nel tempo."""
        mind = NPCState(
            npc_id="luna",
            needs={"social": 0.2, "intimacy": 0.3, "rest": 0.1},
        )
        
        # Simula 10 tick senza interazioni
        for _ in range(10):
            # Need aumentano di ~0.02 per tick (esempio)
            mind.needs["social"] += 0.02
            mind.needs["intimacy"] += 0.02
        
        assert mind.needs["social"] > 0.3
        assert mind.needs["intimacy"] > 0.4
    
    def test_goal_generation_fallback(self):
        """Verifica che goal fallback sia sempre presente."""
        from luna.systems.npc_mind import NPCMindManager
        
        manager = NPCMindManager()
        mind = NPCState(
            npc_id="luna",
            needs={"social": 0.3, "intimacy": 0.2, "rest": 0.6},
        )
        
        # Anche senza template match, deve generare goal
        goal = manager._generate_goal(mind, game_state=None, turn_number=1)
        
        assert goal is not None
        assert goal.description != ""
        # Goal dovrebbe essere basato su "rest" (need dominante)
        assert "riposo" in goal.description.lower() or "stanca" in goal.description.lower()
    
    def test_unspoken_thoughts(self):
        """Verifica accumulo pensieri non detti."""
        mind = NPCState(npc_id="luna")
        
        # Aggiungi pensiero non detto
        mind.unspoken.append({
            "thought": "Ha visto Stella flirtare con te",
            "weight": 0.7,
            "turn_added": 10
        })
        
        assert len(mind.unspoken) == 1
        assert mind.unspoken[0]["weight"] == 0.7
    
    def test_emotional_state_ttl(self):
        """Verifica decadimento emotional state."""
        mind = NPCState(
            npc_id="luna",
            emotional_state="intimate",
            emotional_state_set_turn=10
        )
        
        # Dopo 8 turni, "intimate" dovrebbe scadere
        current_turn = 18
        TTL_INTIMATE = 8
        
        age = current_turn - mind.emotional_state_set_turn
        if age >= TTL_INTIMATE:
            mind.emotional_state = "default"
            mind.emotional_state_set_turn = 0
        
        assert mind.emotional_state == "default"


class TestNPCPersistence:
    """Test salvataggio/caricamento NPCMind."""
    
    @pytest.mark.asyncio
    async def test_save_load_npc_minds(self):
        """Verifica save/load da database."""
        from luna.core.database import Database
        from luna.systems.npc_mind import NPCState
        
        # Setup DB test
        db = Database(db_path=":memory:")
        await db.init()
        
        # Crea NPCMind
        minds_dict = {
            "luna": {
                "npc_id": "luna",
                "needs": {"social": 0.5, "intimacy": 0.7},
                "emotional_state": "conflicted",
                "current_goal": {"description": "vuole parlare", "urgency": 0.6}
            }
        }
        
        # Save
        session_id = "test_session_001"
        async with db.get_session() as session:
            await db.save_npc_minds(session, session_id, minds_dict)
        
        # Load
        async with db.get_session() as session:
            loaded = await db.load_npc_minds(session, session_id)
        
        assert "luna" in loaded
        assert loaded["luna"]["mind_data"]["needs"]["intimacy"] == 0.7
        assert loaded["luna"]["mind_data"]["emotional_state"] == "conflicted"
```

**Esecuzione:**
```bash
pytest tests/unit/test_npc_mind.py -v --asyncio-mode=auto
```

---

### 2.3 TensionTracker

**File:** `tests/unit/test_tension_tracker.py`

```python
import pytest
from luna.systems.tension_tracker import TensionTracker

class TestTensionTracker:
    """Test tracking tensione narrativa."""
    
    def test_tension_phases(self):
        """Verifica fasi: CALM → FORESHADOWING → BUILDUP → TRIGGER."""
        tracker = TensionTracker()
        
        # CALM (0-0.35)
        tracker.romantic = 0.2
        assert tracker.get_phase("romantic") == "CALM"
        
        # FORESHADOWING (0.35-0.55)
        tracker.romantic = 0.45
        assert tracker.get_phase("romantic") == "FORESHADOWING"
        
        # BUILDUP (0.55-0.75)
        tracker.romantic = 0.65
        assert tracker.get_phase("romantic") == "BUILDUP"
        
        # TRIGGER (0.75+)
        tracker.romantic = 0.80
        assert tracker.get_phase("romantic") == "TRIGGER"
    
    def test_pressure_hints(self):
        """Verifica generazione hint narrativi."""
        tracker = TensionTracker()
        
        # CALM: nessun hint
        tracker.romantic = 0.1
        hint = tracker.get_pressure_hint("romantic")
        assert hint is None
        
        # FORESHADOWING: hint ambientale
        tracker.romantic = 0.40
        hint = tracker.get_pressure_hint("romantic")
        assert hint is not None
        assert "ambient" in hint.lower() or "atmosfera" in hint.lower()
        
        # TRIGGER: evento obbligatorio
        tracker.romantic = 0.78
        hint = tracker.get_pressure_hint("romantic")
        assert hint is not None
        assert "deve" in hint.lower() or "event" in hint.lower()
    
    def test_tension_increase(self):
        """Verifica incremento tensione."""
        tracker = TensionTracker()
        
        initial = tracker.romantic
        tracker.romantic += 0.1
        
        assert tracker.romantic > initial
        assert tracker.romantic <= 1.0  # Cap a 1.0
```

**Esecuzione:**
```bash
pytest tests/unit/test_tension_tracker.py -v
```

---

## 3. Test di Integrazione

### 3.1 Poker Full Hand (M7 Priority)

**File:** `tests/integration/test_poker_full_hand.py`

```python
import pytest
from luna.systems.mini_games.poker.poker_game import PokerGame
from luna.core.models import GameState

class TestPokerFullHand:
    """Test mano completa di poker: preflop → river → showdown."""
    
    @pytest.mark.asyncio
    async def test_complete_hand_player_wins(self):
        """Simula mano completa dove il giocatore vince."""
        
        # Setup game state
        game_state = GameState(
            session_id="test_poker_001",
            turn_count=1,
            active_companion="luna",
            companions={
                "luna": {
                    "affinity": 50,
                    "emotional_state": "default"
                }
            }
        )
        
        # Inizializza poker game
        poker = PokerGame(
            companion_names=["luna"],
            game_engine=None,  # Mock
            llm_manager=None   # Mock
        )
        await poker.start_game(game_state)
        
        # === PREFLOP ===
        result = await poker.process_action("vedo", game_state)
        assert "preflop" in result.text.lower() or "carte" in result.text.lower()
        assert poker._poker.street in ["preflop", "flop"]
        
        # === FLOP ===
        if poker._poker.street == "preflop":
            # NPC actions
            result = await poker.process_action("check", game_state)
        
        assert poker._poker.street in ["flop", "turn"]
        assert len(poker._poker.board) >= 3
        
        # === TURN ===
        result = await poker.process_action("check", game_state)
        assert poker._poker.street in ["turn", "river"]
        assert len(poker._poker.board) >= 4
        
        # === RIVER ===
        result = await poker.process_action("check", game_state)
        assert poker._poker.street in ["river", "showdown"]
        assert len(poker._poker.board) == 5
        
        # === SHOWDOWN ===
        result = await poker.process_action("check", game_state)
        assert poker._poker.street == "showdown"
        assert "vinto" in result.text.lower() or "perso" in result.text.lower()
    
    @pytest.mark.asyncio
    async def test_complete_hand_with_raises(self):
        """Mano con rilanci multipli."""
        
        game_state = GameState(session_id="test_poker_002", turn_count=1)
        poker = PokerGame(companion_names=["luna"], game_engine=None, llm_manager=None)
        await poker.start_game(game_state)
        
        # Player rilancia
        result = await poker.process_action("rilancio 200", game_state)
        assert poker._poker.players[0].bet_this_street >= 200
        
        # Luna dovrebbe rispondere (call/raise/fold)
        # Verifica che il gioco continui
        assert poker._poker.street != "finished"
    
    @pytest.mark.asyncio
    async def test_all_in_scenario(self):
        """Test scenario all-in."""
        
        game_state = GameState(session_id="test_poker_003", turn_count=1)
        poker = PokerGame(companion_names=["luna"], game_engine=None, llm_manager=None)
        await poker.start_game(game_state)
        
        # Player all-in
        result = await poker.process_action("all-in", game_state)
        assert poker._poker.players[0].stack == 0
        assert "all" in result.text.lower() or "tutto" in result.text.lower()


class TestPokerStripProgression:
    """Test progressione strip events."""
    
    @pytest.mark.asyncio
    async def test_strip_level_progression(self):
        """Verifica progressione livelli strip quando NPC perde chips."""
        
        game_state = GameState(session_id="test_strip_001", turn_count=1)
        poker = PokerGame(companion_names=["luna"], game_engine=None, llm_manager=None)
        await poker.start_game(game_state)
        
        # Simula luna che perde 50% dello stack
        luna_player = next(p for p in poker._poker.players if p.player_id == "luna")
        initial_stack = luna_player.stack
        luna_player.stack = initial_stack // 2
        
        strip_events = poker._check_strip_after_hand(game_state)
        
        # Dovrebbe triggerare strip event
        assert len(strip_events) > 0
        assert strip_events[0]["npc_name"] == "luna"
    
    @pytest.mark.asyncio
    async def test_strip_dialogue_llm_generation(self):
        """Verifica generazione dialogo strip con LLM."""
        
        # Richiede LLM mock
        from unittest.mock import AsyncMock, Mock
        
        llm_manager = Mock()
        llm_manager.generate = AsyncMock(return_value=Mock(
            text="Non mi aspettavo di arrivare a questo punto..."
        ))
        
        game_state = GameState(session_id="test_strip_002", turn_count=1)
        poker = PokerGame(
            companion_names=["luna"],
            game_engine=None,
            llm_manager=llm_manager
        )
        
        # Simula strip level 3 (LLM-generated)
        dialogue = await poker._generate_strip_dialogue_llm(
            npc_name="luna",
            strip_level=3,
            game_state=game_state
        )
        
        assert dialogue != ""
        assert len(dialogue) > 0
        # Verifica che LLM sia stato chiamato
        llm_manager.generate.assert_called_once()
```

**Esecuzione:**
```bash
pytest tests/integration/test_poker_full_hand.py -v --asyncio-mode=auto
```

---

### 3.2 NPCMind Persistence

**File:** `tests/integration/test_npc_persistence.py`

```python
import pytest
from datetime import datetime, timedelta
from luna.core.engine import GameEngine
from luna.core.database import Database

class TestNPCPersistence:
    """Test persistenza NPCMind tra sessioni."""
    
    @pytest.mark.asyncio
    async def test_npc_state_persists_across_sessions(self):
        """Verifica che stato NPC persista tra sessioni."""
        
        # === SESSIONE 1 ===
        db = Database(db_path=":memory:")
        await db.init()
        
        engine = GameEngine(
            world_name="school_life_complete",
            db=db,
            no_media=True
        )
        await engine.start_new_game()
        
        # Modifica stato Luna
        luna_mind = engine.npc_mind_manager.minds["luna"]
        luna_mind.needs["intimacy"] = 0.85
        luna_mind.emotional_state = "vulnerable"
        luna_mind.unspoken.append({
            "thought": "test_unspoken",
            "weight": 0.9,
            "turn_added": 10
        })
        
        session_id = engine.game_state.session_id
        
        # Salva
        await engine.state_memory.save_all()
        
        # === SESSIONE 2 (dopo 3 ore) ===
        engine2 = GameEngine(
            world_name="school_life_complete",
            db=db,
            no_media=True
        )
        
        # Carica sessione esistente
        await engine2.load_game(session_id)
        
        # Verifica stato Luna persistito
        luna_mind2 = engine2.npc_mind_manager.minds["luna"]
        
        assert luna_mind2.needs["intimacy"] >= 0.85  # Può essere cresciuto
        assert luna_mind2.emotional_state in ["vulnerable", "default"]  # Può essere decaduto
        assert len(luna_mind2.unspoken) > 0
        assert any("test_unspoken" in u["thought"] for u in luna_mind2.unspoken)
    
    @pytest.mark.asyncio
    async def test_offline_time_simulation(self):
        """Verifica simulazione tempo offline."""
        
        db = Database(db_path=":memory:")
        await db.init()
        
        engine = GameEngine(world_name="school_life_complete", db=db, no_media=True)
        await engine.start_new_game()
        
        # Stato iniziale
        luna_mind = engine.npc_mind_manager.minds["luna"]
        initial_social_need = luna_mind.needs.get("social", 0.0)
        
        # Salva
        session_id = engine.game_state.session_id
        await engine.state_memory.save_all()
        
        # Simula che siano passate 6 ore
        # (1 ora = 1 tick, quindi 6 tick)
        
        # Ricarica e forza timestamp vecchio
        engine2 = GameEngine(world_name="school_life_complete", db=db, no_media=True)
        
        # Mock: forza saved_at a 6 ore fa
        # (normalmente fatto dall'engine durante load)
        luna_mind2 = engine2.npc_mind_manager.minds["luna"]
        engine2.npc_mind_manager.simulate_offline_ticks(
            n_turns=6,
            start_turn=engine2.game_state.turn_count
        )
        
        # Needs dovrebbero essere cresciuti
        final_social_need = luna_mind2.needs.get("social", 0.0)
        assert final_social_need > initial_social_need
```

**Esecuzione:**
```bash
pytest tests/integration/test_npc_persistence.py -v --asyncio-mode=auto
```

---

### 3.3 Memory Isolation

**File:** `tests/integration/test_memory_isolation.py`

```python
import pytest
from luna.core.engine import GameEngine

class TestMemoryIsolation:
    """Test isolamento memorie tra companion."""
    
    @pytest.mark.asyncio
    async def test_companion_memory_isolation(self):
        """Verifica che memorie di Luna non appaiano in conversazione con Stella."""
        
        engine = GameEngine(world_name="school_life_complete", no_media=True)
        await engine.start_new_game()
        
        # === Conversazione con Luna ===
        engine.game_state.active_companion = "luna"
        
        result1 = await engine.process_turn("Ciao Luna, sei speciale per me")
        # Memoria salvata per Luna
        
        # Fai altre 10 interazioni con Luna
        for i in range(10):
            await engine.process_turn(f"Luna messaggio {i}")
        
        # === Switch a Stella ===
        engine.game_state.active_companion = "stella"
        
        result2 = await engine.process_turn("Ciao Stella")
        
        # Verifica che la risposta di Stella NON faccia riferimento
        # a conversazioni con Luna
        assert "sei speciale" not in result2.text.lower()
        assert "luna" not in result2.text.lower()
        
        # === Ritorno a Luna ===
        engine.game_state.active_companion = "luna"
        
        result3 = await engine.process_turn("Ti ricordi cosa ti ho detto prima?")
        
        # Luna DOVREBBE ricordare
        assert "speciale" in result3.text.lower() or "ricord" in result3.text.lower()
```

**Esecuzione:**
```bash
pytest tests/integration/test_memory_isolation.py -v --asyncio-mode=auto
```

---

## 4. Test End-to-End

### 4.1 Full Session Test

**File:** `tests/e2e/test_full_session.py`

```python
import pytest
from luna.core.engine import GameEngine

class TestFullSession:
    """Test sessione completa di gioco."""
    
    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_complete_game_session(self):
        """Simula sessione di gioco completa: 30+ turni."""
        
        engine = GameEngine(
            world_name="school_life_complete",
            no_media=True,
            no_llm=False  # Usa LLM vero (richiede API key)
        )
        
        await engine.start_new_game()
        
        # Sequenza azioni realistiche
        actions = [
            "Ciao Luna, come stai?",
            "Possiamo parlare in privato?",
            "Vado in aula studio",
            "Parlo con Stella",
            "Torno da Luna",
            "Invito Luna a cena",
            # ... 30+ azioni
        ]
        
        for i, action in enumerate(actions):
            result = await engine.process_turn(action)
            
            # Verifica integrità base
            assert result is not None
            assert result.text != ""
            assert engine.game_state.turn_count == i + 1
            
            # Log per debugging
            print(f"\n=== Turno {i+1} ===")
            print(f"Azione: {action}")
            print(f"Risposta: {result.text[:100]}...")
        
        # Verifica stato finale
        assert engine.game_state.turn_count == len(actions)
        
        # Luna dovrebbe aver sviluppato affinità
        luna_affinity = engine.game_state.companions["luna"]["affinity"]
        assert luna_affinity > 0
```

**Esecuzione:**
```bash
# Richiede API key valida
export ANTHROPIC_API_KEY=your_key_here
pytest tests/e2e/test_full_session.py -v -s --asyncio-mode=auto
```

---

## 5. Test Specifici v8

### 5.1 DirectorAgent

**File:** `tests/unit/test_director_agent.py`

```python
import pytest
from luna.agents.director import DirectorAgent
from luna.systems.world_sim.turn_director import TurnDirective

class TestDirectorAgent:
    """Test DirectorAgent v8."""
    
    @pytest.mark.asyncio
    async def test_director_called_on_npc_initiative(self):
        """Verifica che DirectorAgent venga chiamato quando NPC prende iniziativa."""
        
        from unittest.mock import AsyncMock, Mock
        
        # Mock LLM
        llm_manager = Mock()
        llm_manager.generate = AsyncMock(return_value=Mock(
            text='{"beat": "Luna si alza", "tone": "intimate", "npc_intent": "cerca contatto"}'
        ))
        
        director = DirectorAgent(llm_manager=llm_manager)
        
        directive = TurnDirective(
            driver="npc",
            companion_name="luna",
            reason="goal_driven"
        )
        
        # Chiama director
        scene = await director.direct(
            turn_directive=directive,
            game_state=None,  # Mock
            tension_state=None  # Mock
        )
        
        # Verifica output
        assert scene is not None
        assert "beat" in scene or hasattr(scene, "beat")
        
        # LLM chiamato
        llm_manager.generate.assert_called_once()
```

---

### 5.2 Emotional State TTL

**File:** `tests/unit/test_emotional_ttl.py`

```python
import pytest
from luna.systems.world_sim.world_simulator import WorldSimulator
from luna.core.models import GameState, NPCState

class TestEmotionalStateTTL:
    """Test decadimento emotional state."""
    
    def test_intimate_state_expires_after_8_turns(self):
        """Verifica che 'intimate' scada dopo 8 turni."""
        
        game_state = GameState(turn_count=10)
        game_state.npc_states["luna"] = NPCState(
            npc_id="luna",
            emotional_state="intimate",
            emotional_state_set_turn=10
        )
        
        simulator = WorldSimulator()
        
        # Simula 8 turni
        for turn in range(11, 19):
            game_state.turn_count = turn
            simulator._tick_emotional_state_ttl(game_state, turn)
        
        # Dopo turno 18 (8 turni passati), stato dovrebbe essere "default"
        assert game_state.npc_states["luna"].emotional_state == "default"
    
    def test_default_state_never_expires(self):
        """Verifica che 'default' non scada mai."""
        
        game_state = GameState(turn_count=1)
        game_state.npc_states["luna"] = NPCState(
            npc_id="luna",
            emotional_state="default",
            emotional_state_set_turn=1
        )
        
        simulator = WorldSimulator()
        
        # Simula 100 turni
        for turn in range(2, 102):
            game_state.turn_count = turn
            simulator._tick_emotional_state_ttl(game_state, turn)
        
        # Stato deve rimanere "default"
        assert game_state.npc_states["luna"].emotional_state == "default"
```

---

## 6. Test Regression

### 6.1 Feature v7 Still Working

**File:** `tests/regression/test_v7_features.py`

```python
import pytest

class TestV7Regression:
    """Verifica che feature v7 funzionino ancora in v8."""
    
    @pytest.mark.asyncio
    async def test_quest_system_still_works(self):
        """Quest system da v7 deve funzionare."""
        # TODO: implement
        pass
    
    @pytest.mark.asyncio
    async def test_schedule_manager_still_works(self):
        """ScheduleManager deve posizionare NPC correttamente."""
        # TODO: implement
        pass
```

---

## 7. Test Performance

### 7.1 Performance Benchmarks

**File:** `tests/performance/test_benchmarks.py`

```python
import pytest
import time
from luna.core.engine import GameEngine

class TestPerformance:
    """Test performance critiche."""
    
    @pytest.mark.asyncio
    @pytest.mark.benchmark
    async def test_turn_processing_time(self):
        """Verifica che un turno completi in <5 secondi."""
        
        engine = GameEngine(world_name="school_life_complete", no_media=True)
        await engine.start_new_game()
        
        start = time.time()
        result = await engine.process_turn("Ciao")
        elapsed = time.time() - start
        
        assert elapsed < 5.0, f"Turno troppo lento: {elapsed:.2f}s"
    
    @pytest.mark.asyncio
    async def test_database_save_time(self):
        """Verifica che save DB completi in <2 secondi."""
        
        engine = GameEngine(world_name="school_life_complete", no_media=True)
        await engine.start_new_game()
        
        # Fai 10 turni per accumulare dati
        for i in range(10):
            await engine.process_turn(f"Azione {i}")
        
        start = time.time()
        await engine.state_memory.save_all()
        elapsed = time.time() - start
        
        assert elapsed < 2.0, f"Save troppo lento: {elapsed:.2f}s"
```

**Esecuzione:**
```bash
pytest tests/performance/ -v -m benchmark
```

---

## 8. Criteri di Accettazione

### 8.1 Checklist M7

**Tutti i test devono passare prima di considerare M7 completa:**

- [ ] **Poker Full Hand**: ✅ 100% test pass
  - [ ] Preflop → Flop → Turn → River → Showdown
  - [ ] Rilanci multipli
  - [ ] All-in scenarios
  - [ ] Showdown con eval7 corretto

- [ ] **NPCMind Persistence**: ✅ 100% test pass
  - [ ] Save/load da database
  - [ ] Simulazione tempo offline
  - [ ] Needs crescono offline
  - [ ] Emotional state decade offline

- [ ] **Memory Isolation**: ✅ 100% test pass
  - [ ] Memorie Luna ≠ memorie Stella
  - [ ] No bleed tra companion

- [ ] **Strip Events**: ✅ 100% test pass
  - [ ] Progressione livelli corretta
  - [ ] Dialogo LLM per livelli 3-5
  - [ ] Fallback deterministico se LLM fallisce
  - [ ] AI personality shift dopo strip

- [ ] **DirectorAgent**: ✅ Test pass
  - [ ] Chiamato su turni NPC
  - [ ] Output valido (beat, tone, intent)

- [ ] **Emotional State TTL**: ✅ Test pass
  - [ ] Stati scadono dopo TTL
  - [ ] Default non scade mai

- [ ] **Performance**: ✅ Benchmark rispettati
  - [ ] Turno < 5s
  - [ ] Save DB < 2s

---

### 8.2 Exit Criteria

**Milestone M7 COMPLETA quando:**

1. **100% test unitari** passano (poker, npc_mind, tension)
2. **100% test integrazione** passano (full hand, persistence, memory)
3. **Almeno 1 test E2E** completo passa (30+ turni sessione)
4. **Zero critical bugs** aperti
5. **Performance benchmarks** rispettati
6. **Documentazione aggiornata** con risultati test

---

## 9. Esecuzione Test

### 9.1 Run Completo

```bash
# Setup
cd /path/to/luna-rpg-v8
source .venv/bin/activate
export ANTHROPIC_API_KEY=your_key  # Per test con LLM

# Run tutti i test
pytest tests/ -v

# Con coverage
pytest tests/ -v --cov=src/luna --cov-report=html

# Solo test veloci (esclude E2E)
pytest tests/ -v -m "not slow"

# Solo test critici M7
pytest tests/integration/test_poker_full_hand.py -v
pytest tests/integration/test_npc_persistence.py -v
pytest tests/integration/test_memory_isolation.py -v
```

---

### 9.2 CI/CD Pipeline (Futuro)

```yaml
# .github/workflows/test.yml
name: Luna RPG Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: |
          pip install -e .
          pip install pytest pytest-asyncio pytest-cov
      
      - name: Run tests
        run: |
          pytest tests/ -v --cov=src/luna
        env:
          LUNA_TEST_MODE: 1
          LUNA_DEBUG_NO_MEDIA: 1
      
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

---

### 9.3 Test Reports

Dopo esecuzione, generare report:

```bash
# HTML coverage report
pytest tests/ --cov=src/luna --cov-report=html
open htmlcov/index.html

# JUnit XML (per CI)
pytest tests/ --junitxml=test-results.xml

# Test duration report
pytest tests/ -v --durations=10
```

---

## 10. Troubleshooting

### 10.1 Problemi Comuni

**ImportError: No module named 'eval7'**
```bash
pip install eval7
```

**Async test errors**
```bash
pip install pytest-asyncio
# In pytest.ini:
[pytest]
asyncio_mode = auto
```

**Database locked**
```bash
# Usa DB in-memory per test
db = Database(db_path=":memory:")
```

**LLM timeout in test**
```bash
# Usa mock LLM
from unittest.mock import Mock, AsyncMock
llm_manager = Mock()
llm_manager.generate = AsyncMock(return_value=Mock(text="test"))
```

---

## Appendice: Test Data Fixtures

### A.1 Fixture conftest.py

```python
# tests/conftest.py
import pytest
from luna.core.database import Database
from luna.core.engine import GameEngine

@pytest.fixture
async def test_db():
    """Database in-memory per test."""
    db = Database(db_path=":memory:")
    await db.init()
    yield db
    # Cleanup
    await db.close()

@pytest.fixture
async def test_engine(test_db):
    """GameEngine configurato per test."""
    engine = GameEngine(
        world_name="school_life_complete",
        db=test_db,
        no_media=True,
        no_llm=True  # Mock LLM
    )
    await engine.start_new_game()
    yield engine

@pytest.fixture
def mock_llm_manager():
    """Mock LLM manager."""
    from unittest.mock import Mock, AsyncMock
    
    manager = Mock()
    manager.generate = AsyncMock(return_value=Mock(
        text="Test response",
        usage={"total_tokens": 100}
    ))
    return manager
```

---

**Fine Documento**

Versione: 1.0  
Ultima modifica: 2026-04-12  
Autore: Test Strategy Team
