# Core Engine Testing - Quick Reference

**Quick start guide per testare `core/engine.py` da 0% → 75%+ coverage**

---

## 🚀 Setup (2 minuti)

```bash
# 1. Posizionati nel progetto
cd /path/to/luna-rpg-v8

# 2. Attiva venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# 3. Verifica dipendenze
pip install pytest pytest-asyncio pytest-mock aiosqlite

# 4. Copia file test
# - docs/CORE_ENGINE_TESTING.md → documentazione completa
# - tests/unit/test_core_engine_complete.py → test pronti
```

---

## ⚡ Run Test Rapidi

### Test Singolo (verifica setup)

```bash
# Test più semplice - creazione engine
pytest tests/unit/test_core_engine_complete.py::TestEngineCreation::test_create_engine_basic -v
```

**Output atteso:**
```
test_create_engine_basic PASSED [100%]
```

Se passa → Setup OK! ✅

### Suite Completa

```bash
# Tutti i test core engine
pytest tests/unit/test_core_engine_complete.py -v
```

### Con Coverage

```bash
# Coverage specifico per engine.py
pytest tests/unit/test_core_engine_complete.py \
    --cov=src/luna/core/engine \
    --cov-report=term-missing
```

**Target:** 75%+ coverage

---

## 📊 Coverage Checkpoint

### Verifica Coverage Corrente

```bash
pytest tests/unit/test_core_engine_complete.py \
    --cov=src/luna/core/engine \
    --cov-report=html

# Apri report
open htmlcov/index.html
```

### Coverage per Sistema

```bash
# Core engine
pytest tests/unit/test_core_engine*.py --cov=src/luna/core/engine

# QuestEngine
pytest tests/unit/test_quest*.py --cov=src/luna/systems/quest_engine_sequential

# MemoryManager
pytest tests/unit/test_memory*.py --cov=src/luna/systems/memory

# ScheduleManager
pytest tests/unit/test_schedule*.py --cov=src/luna/systems/schedule_manager

# LocationManager
pytest tests/unit/test_location*.py --cov=src/luna/systems/location
```

---

## 🎯 Test Prioritari

### Phase 1: Engine Basics (30 min)

```bash
# 1. Initialization
pytest tests/unit/test_core_engine_complete.py::TestEngineInitialization -v

# 2. Session management
pytest tests/unit/test_core_engine_complete.py::TestEngineSessionManagement -v

# 3. Turn processing
pytest tests/unit/test_core_engine_complete.py::TestEngineTurnProcessing -v
```

**Target:** 50% coverage engine.py

### Phase 2: Sistemi Chiave (1 ora)

```bash
# 4. QuestEngine tests
pytest tests/unit/test_quest_engine.py -v

# 5. MemoryManager tests  
pytest tests/unit/test_memory_manager.py -v

# 6. ScheduleManager tests
pytest tests/unit/test_schedule_manager.py -v
```

**Target:** 70% coverage sistemi

### Phase 3: Integration (30 min)

```bash
# 7. Engine + Quest integration
pytest tests/integration/test_engine_quest_integration.py -v

# 8. Engine + Memory integration
pytest tests/integration/test_engine_memory_integration.py -v
```

**Target:** 75%+ coverage complessivo

---

## 🔧 Troubleshooting Rapido

### Errore: ModuleNotFoundError

```bash
# Soluzione 1: Installa in editable mode
pip install -e .

# Soluzione 2: Set PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
```

### Errore: No module 'eval7'

```bash
pip install eval7
```

### Errore: Async test failed

```bash
# Verifica pytest.ini
[pytest]
asyncio_mode = auto

# Aggiungi marker
@pytest.mark.asyncio
async def test_...
```

### Errore: Database locked

```bash
# Usa :memory: in fixture
db = Database(db_path=":memory:")
```

### Test troppo lenti

```bash
# Run solo test veloci
pytest tests/unit/ -v -m "not slow"

# Skip E2E
pytest tests/ -v --ignore=tests/e2e/
```

---

## 📝 Template Test Veloce

```python
# tests/unit/test_my_feature.py
import pytest

class TestMyFeature:
    """Test my feature."""
    
    @pytest.mark.asyncio
    async def test_basic_functionality(self, mock_engine_full):
        """Test basic case."""
        engine = mock_engine_full
        await engine.initialize()
        
        # Your test here
        assert engine.state is not None
        
        await engine.shutdown()
```

---

## 🎯 Milestone Checklist

- [ ] **Engine creation** - 5 test pass
- [ ] **Engine initialization** - 5 test pass  
- [ ] **Session save/load** - 3 test pass
- [ ] **Turn processing** - 3 test pass
- [ ] **Public API** - 5 test pass
- [ ] **Shutdown** - 3 test pass
- [ ] **Properties** - 1 test pass

**Total:** 25 test pass → **75%+ coverage** ✅

---

## 📋 Coverage Report Interpretation

```bash
Name                    Stmts   Miss  Cover   Missing
-----------------------------------------------------
core/engine.py            445    111    75%   50-55, 120-125...
```

**Interpretazione:**
- **Stmts:** Linee totali codice
- **Miss:** Linee non coperte
- **Cover:** Percentuale coverage
- **Missing:** Linee specifiche mancanti

**Target OK se:** Cover >= 75%

**Se < 75%:** Guarda colonna "Missing", aggiungi test per quelle linee

---

## 🚨 Red Flags

**Test fails con:**
```
ImportError: cannot import name 'GameState'
```
→ PYTHONPATH non impostato

**Test fails con:**
```
RuntimeError: Event loop is closed
```
→ Problema async, usa `@pytest.mark.asyncio`

**Test fails con:**
```
sqlite3.OperationalError: database is locked
```
→ Usa `:memory:` database in test

**Coverage 0%:**
```
core/engine.py     445      0     0%
```
→ Test non stanno importando il modulo corretto

---

## 📚 Documentazione Completa

**Tutti i dettagli in:**
- `docs/CORE_ENGINE_TESTING.md` - Guida completa
- `docs/TESTING_STRATEGY_V8.md` - Strategia generale
- `docs/QUICK_START_TESTING.md` - Quick start

---

## ⏱️ Time Budget

| Task | Tempo | Priorità |
|------|-------|----------|
| Setup ambiente | 5 min | 🔴 |
| Test engine creation | 10 min | 🔴 |
| Test initialization | 20 min | 🔴 |
| Test session save/load | 20 min | 🟡 |
| Test turn processing | 15 min | 🟡 |
| Test sistemi chiave | 60 min | 🟡 |
| Test integrazione | 30 min | 🟢 |
| Coverage report | 10 min | 🟢 |

**Total:** ~2.5 ore → 75%+ coverage ✅

---

## ✅ Success Criteria

**Milestone completa quando:**

1. ✅ `pytest tests/unit/test_core_engine_complete.py -v` → 100% pass
2. ✅ `pytest tests/unit/test_quest_engine.py -v` → 100% pass
3. ✅ `pytest tests/unit/test_memory_manager.py -v` → 100% pass
4. ✅ Coverage `core/engine.py` >= 75%
5. ✅ Coverage sistemi chiave >= 70%
6. ✅ No critical bugs aperti
7. ✅ Tutti i test async funzionano
8. ✅ Database tests usano :memory:
9. ✅ Media pipeline correttamente mockato
10. ✅ Report HTML coverage generato

---

## 🔄 Workflow Iterativo

```bash
# 1. Scrivi test
vim tests/unit/test_core_engine_complete.py

# 2. Run test
pytest tests/unit/test_core_engine_complete.py::TestEngineInitialization -v

# 3. Check coverage
pytest tests/unit/test_core_engine_complete.py --cov=src/luna/core/engine

# 4. Se < 75%, identifica missing lines
pytest tests/unit/test_core_engine_complete.py \
    --cov=src/luna/core/engine \
    --cov-report=term-missing

# 5. Aggiungi test per missing lines

# 6. Repeat fino a 75%+

# 7. Commit
git add tests/
git commit -m "Add core engine tests - 75% coverage"
```

---

**Start Now:**

```bash
pytest tests/unit/test_core_engine_complete.py::TestEngineCreation::test_create_engine_basic -v
```

Se passa → Sei pronto! Continua con il resto della suite! 🚀
