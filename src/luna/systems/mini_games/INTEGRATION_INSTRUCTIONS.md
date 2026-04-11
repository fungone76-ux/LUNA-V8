# POKER MINI-GAME - ISTRUZIONI DI INTEGRAZIONE

Modifiche da fare ai file esistenti di Luna RPG per integrare il poker.

---

## 📝 MODIFICA 1: Aggiungi Intent Type

**File**: `src/luna/core/models/enums.py`

**Cerca**:
```python
class IntentType(str, Enum):
    """Player action intent classification."""
    STANDARD        = "standard"
    MOVEMENT        = "movement"
    FAREWELL        = "farewell"
    REST            = "rest"
    FREEZE          = "freeze"
    SCHEDULE_QUERY  = "schedule_query"
    REMOTE_COMM     = "remote_comm"
    SUMMON          = "summon"
    INTIMATE_SCENE  = "intimate_scene"
    OUTFIT_MAJOR    = "outfit_major"
    INVITATION      = "invitation"
    EVENT_CHOICE    = "event_choice"
```

**Aggiungi** (alla fine, prima della chiusura della classe):
```python
    POKER_GAME      = "poker_game"  # ← NUOVO
```

**Risultato finale**:
```python
class IntentType(str, Enum):
    """Player action intent classification."""
    STANDARD        = "standard"
    MOVEMENT        = "movement"
    FAREWELL        = "farewell"
    REST            = "rest"
    FREEZE          = "freeze"
    SCHEDULE_QUERY  = "schedule_query"
    REMOTE_COMM     = "remote_comm"
    SUMMON          = "summon"
    INTIMATE_SCENE  = "intimate_scene"
    OUTFIT_MAJOR    = "outfit_major"
    INVITATION      = "invitation"
    EVENT_CHOICE    = "event_choice"
    POKER_GAME      = "poker_game"  # ← NUOVO
```

---

## 📝 MODIFICA 2: Aggiungi Detection Keywords

**File**: `src/luna/agents/intent_router.py`

**Cerca** la sezione con le keyword lists (vicino all'inizio del file):
```python
FAREWELL_KEYWORDS = [...]
MOVEMENT_KEYWORDS = [...]
# etc.
```

**Aggiungi** (dopo le altre keyword lists):
```python
# Poker game keywords
POKER_KEYWORDS = [
    "poker",
    "giochiamo a poker",
    "partita a poker",
    "gioco a carte",
    "giochiamo a carte",
    "scommettiamo",
    "facciamo una partita",
    "strip poker",  # 😏
]
```

**Poi cerca** il metodo `detect()` e **aggiungi** il check poker (PRIMA del return STANDARD finale):

```python
def detect(self, user_input: str, game_state: GameState) -> IntentType:
    """Detect intent from user input."""
    
    text_lower = user_input.lower().strip()
    
    # ... existing checks ...
    
    # Check poker game (AGGIUNGI QUESTO)
    if any(kw in text_lower for kw in POKER_KEYWORDS):
        logger.info("[IntentRouter] Detected: POKER_GAME")
        return IntentType.POKER_GAME
    
    # ... rest of existing code ...
    
    return IntentType.STANDARD
```

---

## 📝 MODIFICA 3: Aggiungi Intent Handler

**File**: `src/luna/agents/orchestrator/intent_handlers.py`

**In cima al file**, aggiungi l'import:
```python
from luna.systems.mini_games.poker import PokerGame
```

**Poi cerca** la classe `IntentHandlersMixin` e **aggiungi** questo metodo:

```python
async def _handle_poker_game(
    self,
    text: str,
    game_state: GameState,
) -> TurnResult:
    """Handle poker mini-game intent.
    
    Args:
        text: User input
        game_state: Current game state
        
    Returns:
        Turn result with poker game state
    """
    logger.info("[Orchestrator] Handling POKER_GAME intent")
    
    # Check if poker is already active
    if game_state.flags.get("poker_active"):
        # Continue existing game
        poker_data = game_state.flags.get("poker_game", {})
        poker = PokerGame.from_dict(poker_data, self.engine)
        
        # Check for exit command
        if any(cmd in text.lower() for cmd in ["esci", "basta", "fine", "stop"]):
            return await poker.end_game(game_state, "Gioco terminato dal player")
        
        # Play hand
        return await poker.play_hand(text, game_state)
    
    else:
        # Start new game
        # Determine which companions to include
        
        # Check for specific companion names in text
        available_companions = ["Luna", "Maria", "Stella"]
        requested_companions = []
        
        for comp in available_companions:
            if comp.lower() in text.lower():
                requested_companions.append(comp)
        
        # If no specific companion mentioned, use active companion
        if not requested_companions:
            requested_companions = [game_state.active_companion]
        
        # Create poker game
        poker = PokerGame(
            engine=self.engine,
            companion_names=requested_companions,
            initial_stack=1000,
        )
        
        return await poker.start_game(game_state)
```

---

## 📝 MODIFICA 4: Route Intent Handler

**File**: `src/luna/agents/orchestrator/orchestrator.py`

**Cerca** il metodo `execute()` e **trova** la sezione dove vengono chiamati gli intent handlers:

```python
# Route based on intent
if intent == IntentType.MOVEMENT:
    return await self._handle_movement(text, game_state)
elif intent == IntentType.FAREWELL:
    return await self._handle_farewell(text, game_state)
# ... altre elif ...
```

**Aggiungi** (dopo le altre elif, prima dell'else finale):
```python
elif intent == IntentType.POKER_GAME:
    return await self._handle_poker_game(text, game_state)
```

**Esempio completo**:
```python
async def execute(self, text: str, ...) -> TurnResult:
    """Execute turn."""
    
    # ... existing code ...
    
    # Detect intent
    intent = self.intent_router.detect(text, game_state)
    
    # Route intent
    if intent == IntentType.MOVEMENT:
        return await self._handle_movement(text, game_state)
    elif intent == IntentType.FAREWELL:
        return await self._handle_farewell(text, game_state)
    elif intent == IntentType.REST:
        return await self._handle_rest(text, game_state)
    # ... other intents ...
    elif intent == IntentType.POKER_GAME:  # ← AGGIUNGI QUESTO
        return await self._handle_poker_game(text, game_state)
    else:
        return await self._handle_standard(text, game_state)
```

---

## 📁 STRUTTURA FILE FINALE

Dopo tutte le modifiche, la struttura sarà:

```
src/luna/
├── core/
│   └── models/
│       └── enums.py ✅ MODIFICATO
│
├── agents/
│   ├── intent_router.py ✅ MODIFICATO
│   └── orchestrator/
│       ├── orchestrator.py ✅ MODIFICATO
│       └── intent_handlers.py ✅ MODIFICATO
│
└── systems/
    └── mini_games/ ← NUOVO FOLDER
        ├── __init__.py ← NUOVO FILE
        └── poker/ ← NUOVO FOLDER
            ├── __init__.py ← NUOVO FILE
            ├── simple_strip_manager.py ← NUOVO FILE
            └── poker_game.py ← NUOVO FILE
```

---

## ✅ CHECKLIST IMPLEMENTAZIONE

- [ ] Crea folder `src/luna/systems/mini_games/`
- [ ] Crea folder `src/luna/systems/mini_games/poker/`
- [ ] Copia codice da `POKER_COMPLETE_CODE.py` nei rispettivi file
- [ ] Modifica `enums.py` - aggiungi `POKER_GAME`
- [ ] Modifica `intent_router.py` - aggiungi keywords e detection
- [ ] Modifica `intent_handlers.py` - aggiungi `_handle_poker_game()`
- [ ] Modifica `orchestrator.py` - aggiungi routing
- [ ] Test: `python -m luna.main` e prova "giochiamo a poker"

---

## 🧪 COMANDI TEST

Dopo l'implementazione, testa con:

```
1. "Giochiamo a poker"
   → Dovrebbe startare il gioco con companion attivo

2. "Giochiamo a poker con Luna"
   → Dovrebbe startare con Luna

3. "Giochiamo a poker con Luna e Maria"
   → Dovrebbe startare con entrambe

4. "Poker con Luna, Maria e Stella"
   → Dovrebbe startare con tutte e tre

5. Durante il gioco:
   - "punto 100" → Punta 100 chips
   - "vedo" → Call
   - "all-in" → Punta tutto
   - "esci" → Esci dal gioco
```

---

## 🐛 TROUBLESHOOTING

**Errore: ModuleNotFoundError: No module named 'luna.systems.mini_games'**
→ Hai dimenticato di creare `__init__.py` nei folder

**Errore: 'PokerGame' is not defined**
→ Controlla l'import in `intent_handlers.py`

**Poker non si attiva**
→ Verifica che `POKER_KEYWORDS` sia definito in `intent_router.py`

**Intent non routato**
→ Verifica la elif in `orchestrator.py`

---

## 📖 DOCUMENTAZIONE UTENTE

Aggiungi al README o docs:

```markdown
# Poker Mini-Game

Gioca a poker con i companion! Vinci mani per farli spogliare progressivamente.

## Come Giocare

1. **Inizia partita**: "Giochiamo a poker"
2. **Scegli companion**: "Poker con Luna" o "Poker con Luna e Maria"
3. **Gioca mani**: "punto 100", "vedo", "rilancio 50", "all-in"
4. **Esci**: "esci" o "basta"

## Strip Levels

- Level 0 (100%): Outfit completo
- Level 1 (75%): Senza giacca
- Level 2 (50%): Senza gonna
- Level 3 (25%): Topless
- Level 4 (10%): Solo lingerie
- Level 5 (0%): Completamente nuda

## Multi-Companion

Puoi giocare con più companion contemporaneamente:
- "Poker con Luna, Maria e Stella"
- Ognuna strip separatamente
- Chi finisce chips → eliminata nuda
```

---

**TUTTO PRONTO!** Segui le istruzioni e il poker funzionerà! 🎰🔥
