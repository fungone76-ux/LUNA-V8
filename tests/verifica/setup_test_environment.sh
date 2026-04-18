#!/bin/bash
# setup_test_environment.sh
# Script per configurare automaticamente l'ambiente di test per Luna RPG v8

set -e  # Exit on error

echo "========================================="
echo "Luna RPG v8 - Test Environment Setup"
echo "========================================="
echo ""

# Colori per output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Funzione per stampare con colore
print_green() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_yellow() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_red() {
    echo -e "${RED}✗ $1${NC}"
}

# Verifica di essere nella directory root del progetto
if [ ! -f "pyproject.toml" ] && [ ! -f "setup.py" ]; then
    print_red "Errore: esegui questo script dalla directory root del progetto (luna-rpg-v8)"
    exit 1
fi

print_green "Directory corrente: $(pwd)"
echo ""

# Step 1: Verifica Python
echo "Step 1/6: Verifica Python..."
if ! command -v python3 &> /dev/null; then
    print_red "Python 3 non trovato. Installa Python 3.10+ prima di continuare."
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
print_green "Trovato: $PYTHON_VERSION"
echo ""

# Step 2: Crea virtual environment
echo "Step 2/6: Creazione virtual environment..."
if [ -d ".venv" ]; then
    print_yellow "Virtual environment già esistente (.venv)"
    read -p "Vuoi ricreare il venv? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf .venv
        python3 -m venv .venv
        print_green "Virtual environment ricreato"
    else
        print_yellow "Mantengo venv esistente"
    fi
else
    python3 -m venv .venv
    print_green "Virtual environment creato"
fi
echo ""

# Step 3: Attiva virtual environment
echo "Step 3/6: Attivazione virtual environment..."
source .venv/bin/activate || source .venv/Scripts/activate 2>/dev/null
print_green "Virtual environment attivato"
echo ""

# Step 4: Aggiorna pip
echo "Step 4/6: Aggiornamento pip..."
pip install --upgrade pip > /dev/null 2>&1
print_green "pip aggiornato"
echo ""

# Step 5: Installa dipendenze
echo "Step 5/6: Installazione dipendenze..."

# Dipendenze principali
echo "  - Installazione dipendenze principali..."
pip install -e . > /dev/null 2>&1
print_green "  Dipendenze principali installate"

# Dipendenze test
echo "  - Installazione dipendenze test..."
pip install pytest pytest-asyncio pytest-cov pytest-mock pytest-benchmark > /dev/null 2>&1
print_green "  Dipendenze test installate"

# Dipendenze critiche
echo "  - Installazione dipendenze critiche..."
pip install eval7 > /dev/null 2>&1
print_green "  eval7 installato (poker engine)"

echo ""

# Step 6: Verifica installazione
echo "Step 6/6: Verifica installazione..."

# Verifica pytest
if pytest --version > /dev/null 2>&1; then
    PYTEST_VERSION=$(pytest --version | head -n1)
    print_green "pytest installato: $PYTEST_VERSION"
else
    print_red "pytest non installato correttamente"
    exit 1
fi

# Verifica eval7
if python3 -c "import eval7" 2>/dev/null; then
    print_green "eval7 importabile"
else
    print_red "eval7 non importabile"
    exit 1
fi

# Verifica luna package
if python3 -c "import sys; sys.path.insert(0, 'src'); from luna.core.engine import GameEngine" 2>/dev/null; then
    print_green "luna package importabile"
else
    print_yellow "luna package potrebbe avere problemi di import (normale se mancano API keys)"
fi

echo ""

# Step 7: Crea directory test se non esistono
echo "Creazione directory test..."
mkdir -p tests/{unit,integration,e2e,fixtures,performance,regression}
print_green "Directory test create"
echo ""

# Step 8: Crea file .env.test
echo "Creazione file .env.test..."
if [ ! -f ".env.test" ]; then
    cat > .env.test << 'EOF'
# .env.test - Configurazione test per Luna RPG v8
# Questo file è usato durante i test automatici

# Database (in-memory per test)
LUNA_DB_PATH=:memory:

# Debug flags
LUNA_DEBUG_MODE=1
LUNA_DEBUG_NO_MEDIA=1
LUNA_TEST_MODE=1

# API Keys (lascia vuoto per usare mock LLM nei test)
ANTHROPIC_API_KEY=
GEMINI_API_KEY=

# Optional: abilita per test che richiedono LLM vero
# ANTHROPIC_API_KEY=sk-ant-your-key-here
# GEMINI_API_KEY=your-gemini-key-here
EOF
    print_green ".env.test creato"
else
    print_yellow ".env.test già esistente (non sovrascritto)"
fi
echo ""

# Step 9: Esegui test di verifica
echo "========================================="
echo "Esecuzione test di verifica..."
echo "========================================="
echo ""

if [ -f "tests/unit/test_poker_engine_example.py" ]; then
    echo "Eseguo test di esempio poker engine..."
    if pytest tests/unit/test_poker_engine_example.py::TestPokerEngineBasics::test_game_config_creation -v; then
        echo ""
        print_green "TEST DI VERIFICA PASSATO!"
    else
        echo ""
        print_red "Test di verifica fallito - controlla l'output sopra"
        exit 1
    fi
else
    print_yellow "Test di esempio non trovato, salta verifica"
fi

echo ""
echo "========================================="
echo "Setup Completato!"
echo "========================================="
echo ""
echo "Prossimi passi:"
echo ""
echo "1. Attiva il virtual environment:"
echo "   source .venv/bin/activate   (Linux/Mac)"
echo "   .venv\\Scripts\\activate      (Windows)"
echo ""
echo "2. Esegui i test:"
echo "   pytest tests/ -v"
echo ""
echo "3. Esegui test con coverage:"
echo "   pytest tests/ -v --cov=src/luna --cov-report=html"
echo ""
echo "4. Leggi la documentazione:"
echo "   docs/TESTING_STRATEGY_V8.md"
echo "   docs/QUICK_START_TESTING.md"
echo ""
print_green "Ambiente di test pronto per l'uso!"
echo ""
