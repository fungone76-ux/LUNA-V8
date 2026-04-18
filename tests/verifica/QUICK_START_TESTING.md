# Quick Start - Testing Luna RPG v8

**Guida rapida per eseguire i test dopo aver letto `TESTING_STRATEGY_V8.md`**

---

## Setup Iniziale (da fare una volta sola)

```bash
# 1. Posizionarsi nella directory del progetto
cd /path/to/luna-rpg-v8

# 2. Creare virtual environment
python -m venv .venv

# 3. Attivare virtual environment
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 4. Installare dipendenze principali
pip install -e .

# 5. Installare dipendenze test
pip install pytest pytest-asyncio pytest-cov pytest-mock pytest-benchmark

# 6. Installare dipendenze critiche
pip install eval7  # IMPORTANTE per poker

# 7. Verificare installazione
pytest --version
```

---

## Comandi Test Rapidi

### Test Completo (tutti i test)
```bash
pytest tests/ -v
```

### Test Solo Unitari (veloci)
```bash
pytest tests/unit/ -v
```

### Test Solo Integrazione
```bash
pytest tests/integration/ -v
```

### Test con Coverage
```bash
pytest tests/ -v --cov=src/luna --cov-report=html
# Apri htmlcov/index.html nel browser
```

### Test Specifici per Categoria

```bash
# Solo test poker
pytest tests/ -v -m poker

# Solo test NPCMind
pytest tests/ -v -m npc

# Solo test veloci (escludi E2E)
pytest tests/ -v -m "not slow"

# Solo test che richiedono LLM
pytest tests/ -v -m requires_llm
```

### Test Singolo File
```bash
pytest tests/unit/test_poker_engine_example.py -v
```

### Test Singola Classe
```bash
pytest tests/unit/test_poker_engine_example.py::TestPokerEngineBasics -v
```

### Test Singolo Metodo
```bash
pytest tests/unit/test_poker_engine_example.py::TestPokerEngineBasics::test_game_config_creation -v
```

---

## Debug Test Falliti

### Run con output dettagliato
```bash
pytest tests/ -vv -s
# -vv = extra verbose
# -s = mostra print() statements
```

### Run ultimo test fallito
```bash
pytest --lf -v
# --lf = last failed
```

### Run fino al primo errore
```bash
pytest tests/ -x
# -x = stop at first failure
```

### Run con debugger
```bash
pytest tests/ --pdb
# Entra in debugger quando test fallisce
```

---

## Test Performance

```bash
# Run benchmark
pytest tests/performance/ -v --benchmark-only

# Confronta con baseline
pytest tests/performance/ -v --benchmark-compare
```

---

## Configurazione API Keys per Test con LLM

```bash
# File .env.test
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...

# Esegui test
pytest tests/ -v -m requires_llm
```

**NOTA:** I test senza `-m requires_llm` usano mock LLM e non necessitano API keys.

---

## Test Example - Verifica Setup

Dopo aver completato il setup, esegui questo test di esempio:

```bash
pytest tests/unit/test_poker_engine_example.py::TestPokerEngineBasics::test_game_config_creation -v
```

**Output atteso:**
```
tests/unit/test_poker_engine_example.py::TestPokerEngineBasics::test_game_config_creation PASSED [100%]
```

Se vedi `PASSED`, il setup è corretto! ✅

---

## Troubleshooting Comuni

### Errore: `No module named 'eval7'`
```bash
pip install eval7
```

### Errore: `No module named 'luna'`
```bash
# Assicurati di aver installato in modalità editable
pip install -e .
```

### Errore: `ImportError: cannot import name 'GameState'`
```bash
# Verifica che src/ sia nel PYTHONPATH
# Oppure esegui da directory root del progetto
cd /path/to/luna-rpg-v8
pytest tests/
```

### Errore: `Database is locked`
```bash
# I test usano :memory: database, non dovrebbe accadere
# Se accade, verifica che non ci siano processi Luna in esecuzione
```

### Test bloccati (hang)
```bash
# Aggiungi timeout
pytest tests/ -v --timeout=30
```

---

## Report Test

### Genera report HTML
```bash
pytest tests/ -v --html=report.html --self-contained-html
```

### Genera report JUnit (per CI/CD)
```bash
pytest tests/ -v --junitxml=junit.xml
```

### Report durata test
```bash
pytest tests/ -v --durations=10
# Mostra i 10 test più lenti
```

---

## Workflow Consigliato per Sviluppatore

1. **Prima di committare codice:**
   ```bash
   pytest tests/unit/ -v
   ```

2. **Prima di merge/PR:**
   ```bash
   pytest tests/ -v --cov=src/luna
   ```

3. **Dopo fix bug:**
   ```bash
   # Esegui test specifico
   pytest tests/unit/test_poker_engine.py -v
   
   # Poi regression
   pytest tests/regression/ -v
   ```

4. **Prima di release:**
   ```bash
   # Full test suite con coverage
   pytest tests/ -v --cov=src/luna --cov-report=html
   
   # Verifica report coverage
   open htmlcov/index.html
   ```

---

## Criteri di Successo M7

**Tutti questi comandi devono completare senza errori:**

```bash
# 1. Test unitari poker
pytest tests/unit/test_poker_engine.py -v

# 2. Test integrazione poker
pytest tests/integration/test_poker_full_hand.py -v

# 3. Test persistence NPCMind
pytest tests/integration/test_npc_persistence.py -v

# 4. Test memory isolation
pytest tests/integration/test_memory_isolation.py -v

# 5. Full suite (almeno 80% coverage)
pytest tests/ -v --cov=src/luna
```

---

## Risorse

- **Strategia completa:** `docs/TESTING_STRATEGY_V8.md`
- **Fixture condivise:** `tests/conftest.py`
- **Config pytest:** `pytest.ini`
- **Documentazione pytest:** https://docs.pytest.org/

---

**Prossimi Passi:**

1. Esegui test di esempio per verificare setup ✅
2. Leggi `TESTING_STRATEGY_V8.md` per dettagli completi 📖
3. Implementa test mancanti secondo milestone M7 🔨
4. Esegui full suite prima di considerare M7 completa ✔️

**Domande?** Consulta `TESTING_STRATEGY_V8.md` sezione "Troubleshooting"
