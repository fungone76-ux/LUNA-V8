# Tests Directory - Luna RPG v8

Questa directory contiene tutti i test per il progetto Luna RPG v8.

## Struttura

```
tests/
├── conftest.py              # Fixture condivise pytest
├── pytest.ini               # Configurazione pytest (nella root)
│
├── unit/                    # Test unitari (componenti isolati)
│   ├── test_poker_engine_example.py
│   ├── test_npc_mind.py
│   ├── test_tension_tracker.py
│   └── ...
│
├── integration/             # Test integrazione (componenti insieme)
│   ├── test_poker_full_hand.py
│   ├── test_npc_persistence.py
│   ├── test_memory_isolation.py
│   └── ...
│
├── e2e/                     # Test end-to-end (flussi completi)
│   ├── test_full_session.py
│   └── ...
│
├── performance/             # Test performance e benchmark
│   └── test_benchmarks.py
│
├── regression/              # Test regressione (feature v7)
│   └── test_v7_features.py
│
└── fixtures/                # Dati test (world config, save files)
    ├── test_worlds/
    └── test_saves/
```

## Quick Start

```bash
# Setup iniziale (una volta sola)
./setup_test_environment.sh

# Esegui tutti i test
pytest tests/ -v

# Esegui solo test unitari
pytest tests/unit/ -v

# Esegui con coverage
pytest tests/ -v --cov=src/luna --cov-report=html
```

## Categorie Test

### Unit Tests (`tests/unit/`)
Test di singoli componenti in isolamento:
- Poker engine (engine_v2.py)
- NPCMind system
- TensionTracker
- DirectorAgent
- Memory system

**Caratteristiche:**
- Veloci (<1s per test)
- Isolati (no database, no LLM)
- Usano mock/fixture

**Esecuzione:**
```bash
pytest tests/unit/ -v
```

### Integration Tests (`tests/integration/`)
Test di componenti che lavorano insieme:
- Mano completa poker (preflop → showdown)
- NPCMind save/load da database
- Memory isolation tra companion
- Strip events con LLM

**Caratteristiche:**
- Moderati (1-5s per test)
- Database in-memory
- Mock LLM (opzionale LLM vero)

**Esecuzione:**
```bash
pytest tests/integration/ -v
```

### End-to-End Tests (`tests/e2e/`)
Test di flussi completi di gioco:
- Sessione completa 30+ turni
- Poker + dialogo + strip progression
- Save/load sessione completa

**Caratteristiche:**
- Lenti (10-30s per test)
- Database persistente
- LLM vero (richiede API key)

**Esecuzione:**
```bash
# Richiede API key
export ANTHROPIC_API_KEY=your_key
pytest tests/e2e/ -v
```

### Performance Tests (`tests/performance/`)
Benchmark e test performance:
- Tempo elaborazione turno
- Tempo save database
- Memoria usata

**Esecuzione:**
```bash
pytest tests/performance/ -v --benchmark-only
```

### Regression Tests (`tests/regression/`)
Verifica che feature v7 funzionino ancora:
- Quest system
- Schedule manager
- Location system

**Esecuzione:**
```bash
pytest tests/regression/ -v
```

## Markers Pytest

Usa markers per filtrare test:

```bash
# Solo test poker
pytest -v -m poker

# Solo test NPCMind
pytest -v -m npc

# Escludi test lenti
pytest -v -m "not slow"

# Solo test che richiedono LLM
pytest -v -m requires_llm

# Solo benchmark
pytest -v -m benchmark
```

## Fixture Comuni (conftest.py)

Fixture disponibili in tutti i test:

### Database
- `test_db` - Database in-memory
- `test_db_with_data` - Database con dati pre-popolati

### Game Engine
- `mock_engine` - GameEngine con mock
- `test_game_state` - GameState minimale

### LLM
- `mock_llm_manager` - Mock LLM che restituisce risposte
- `mock_llm_failing` - Mock LLM che fallisce (test errori)

### Poker
- `poker_config` - Configurazione poker standard
- `poker_players` - 2 giocatori standard
- `poker_game` - PokerGame pronto per test

### NPCMind
- `test_npc_mind` - NPCState di esempio
- `npc_mind_manager` - NPCMindManager

### Utility
- `assert_luna` - Asserzioni personalizzate
- `companion_name` - Parametrizzato (luna/stella/maria)
- `strip_level` - Parametrizzato (0-5)

## Esempi Uso Fixture

```python
# Test con database
async def test_save_game(test_db):
    async with test_db.get_session() as session:
        # ... test database operations
        pass

# Test con poker game
async def test_poker_hand(poker_game, test_game_state):
    await poker_game.start_game(test_game_state)
    result = await poker_game.process_action("vedo", test_game_state)
    assert result is not None

# Test con mock LLM
async def test_narrative(mock_llm_manager):
    response = await mock_llm_manager.generate(prompt="test")
    assert response.text == "Mocked response from LLM"

# Test parametrizzato
def test_all_companions(companion_name):
    # Questo test gira 3 volte: luna, stella, maria
    assert companion_name in ["luna", "stella", "maria"]
```

## Coverage

Target coverage per M7: **80%+**

```bash
# Genera report coverage HTML
pytest tests/ -v --cov=src/luna --cov-report=html

# Apri report
open htmlcov/index.html
```

## Criteri Accettazione M7

✅ Tutti questi test devono passare:

```bash
# 1. Poker full hand
pytest tests/integration/test_poker_full_hand.py -v

# 2. NPCMind persistence
pytest tests/integration/test_npc_persistence.py -v

# 3. Memory isolation
pytest tests/integration/test_memory_isolation.py -v

# 4. Full suite con coverage
pytest tests/ -v --cov=src/luna
```

## Troubleshooting

### Import Error
```bash
# Assicurati di essere nella directory root
cd /path/to/luna-rpg-v8
pytest tests/
```

### Missing Module 'eval7'
```bash
pip install eval7
```

### Test Hang
```bash
# Aggiungi timeout
pytest tests/ -v --timeout=30
```

### Database Locked
```bash
# Test usano :memory: database
# Se accade, chiudi altre istanze di Luna
```

## Risorse

- **Strategia completa:** `../docs/TESTING_STRATEGY_V8.md`
- **Quick start:** `../docs/QUICK_START_TESTING.md`
- **Setup automatico:** `../setup_test_environment.sh`
- **Pytest docs:** https://docs.pytest.org/

## Contribuire

Quando aggiungi nuovi test:

1. **Scegli categoria giusta** (unit/integration/e2e)
2. **Usa fixture esistenti** (vedi conftest.py)
3. **Aggiungi markers** se appropriato
4. **Documenta** cosa testa e perché
5. **Verifica** che passi: `pytest tests/unit/your_test.py -v`

### Template Test Unitario

```python
"""Test description."""
import pytest

class TestMyComponent:
    """Test MyComponent functionality."""
    
    def test_basic_functionality(self):
        """Test that basic feature works."""
        # Arrange
        component = MyComponent()
        
        # Act
        result = component.do_something()
        
        # Assert
        assert result == expected_value
    
    @pytest.mark.asyncio
    async def test_async_functionality(self, test_db):
        """Test async operations."""
        async with test_db.get_session() as session:
            result = await component.async_operation(session)
            assert result is not None
```

## Domande?

Consulta `../docs/TESTING_STRATEGY_V8.md` per dettagli completi.
