# Luna v8 — Progress Tracker
# Aggiornato ad ogni sessione di sviluppo

---

## STATO GENERALE: M1+M2+M3+M4+M5+M6 completate (2026-04-10). M7 da fare.

---

## Milestone completate

### M1 — Setup progetto (2026-04-10) ✅
- Cartella D:/luna-rpg-v8 creata
- Sorgenti copiati da v6 (src/, worlds/, config/, tests/)
- pyproject.toml aggiornato → luna-rpg8 v8.0.0
- .env con API keys copiate da v7
- run_game.bat / run_game_debug.bat aggiornati per v8

### M2 — Completamento v7 (2026-04-10) ✅
- FIX 1: DirectorAgent — `should_use_director()` espanso: ora attivato per qualsiasi turno NPC (non solo urgency high/critical). File: `systems/world_sim/turn_director.py`
- FIX 2: TensionTracker → NarrativeEngine — aggiunto handler fase "trigger" in `build_context()` (era silenzioso). File: `systems/world_sim/models.py`
- FIX 3: Memory isolation — già corretta nel path principale (companion_filter già passato)
- FIX 4: Goal fallback garantito — aggiunto Priority 6 in `_generate_goal()`: NPCMind non è mai più senza goal. File: `systems/npc_mind.py`
- FIX 5: Emotional state TTL — aggiunto `emotional_state_set_turn` a NPCState, metodo `_tick_emotional_state_ttl()` in WorldSimulator, Guardian registra il turno. Files: `core/models/state_models.py`, `agents/guardian.py`, `systems/world_sim/world_simulator.py`

### M3 — Poker Fix (2026-04-10) ✅
- POKER FIX 1: `poker_game.py` completamente riscritto usando `engine_v2`. Il giocatore ora vede le carte, fa azioni reali (fold/call/raise/all-in), il bot AI usa RiskAgent con equity Monte Carlo.
- POKER FIX 2: `agents.py` bug fix — `state.last_bet_or_raise_amount` → `state.min_raise_size`, `state.cfg.bb` → `state.cfg.big_blind`. File: `systems/mini_games/poker/agents.py`

### M5 — NPCMind persistente (2026-04-10) ✅
- DB: tabella `npc_minds` con ORM `NpcMindModel` aggiunta a `database.py`
- DB: `save_npc_minds(db, session_id, minds_dict)` — upsert per-NPC JSON blob
- DB: `load_npc_minds(db, session_id)` — restituisce `{npc_id: {mind_data, saved_at}}`
- `StateMemoryManager`: aggiunto parametro `npc_mind_manager`, chiamata `save_npc_minds()` in `save_all()` (step 6)
- `NPCMindManager`: aggiunto metodo `simulate_offline_ticks(n_turns, start_turn)` — simula accumulo bisogni, decay emozioni, crescita urgency goal senza game_state
- `engine.py`: dopo ripristino minds da flags, carica da DB table; calcola ore offline (`now - saved_at`), simula ticks (1 ora = 1 tick, cap 72); wira `npc_mind_manager` in StateMemoryManager
- **"Il Mondo Ricorda"**: se il gioco è chiuso 6 ore, all'apertura i bisogni degli NPC sono cresciuti di 6 tick

### M4 — Poker New Features (2026-04-10) ✅
- Strip dialogue LLM: livelli 3/4/5 usano NarrativeEngine per dialogo personalizzato (affinity + emotional state). File: `poker_game.py:_generate_strip_dialogue_llm()`
- AI personality shift: dopo ogni strip level, RiskProfile dell'NPC viene modificato (lvl 3: più passivo, lvl 5: disperato/aggressivo). File: `poker_game.py:_check_strip_after_hand()`
- .env creato (API keys vuote — da inserire)
- run_game.bat e run_game_debug.bat aggiornati per v8
- Spec LUNA_V8_SPEC.md creata
- Venv da creare: `cd D:\luna-rpg-v8 && python -m venv .venv && .venv\Scripts\activate && pip install -e .`

---

## Milestone da completare

### M2 — Completamento v7 → COMPLETATA ✅ (vedi sezione sopra)
### M3 — Poker Fix → COMPLETATA ✅ (vedi sezione sopra)
### M4 — Poker New Features → COMPLETATA ✅ (vedi sezione sopra)

---

### M5 — NPCMind persistente

#### Save/load NPCMind
- **File:** `src/luna/core/database.py`, `src/luna/systems/npc_mind.py`
- **Cosa fare:**
  - Aggiungere tabella `npc_minds` nel DB
  - `save_npc_minds()` chiamato in `state_memory.py` alla fine sessione
  - `load_npc_minds()` chiamato in `engine.py` all'avvio
- **Stato:** DA FARE

#### Simulazione offline (tempo tra sessioni)
- **File:** `src/luna/systems/npc_mind.py`
- **Cosa fare:** `simulate_offline_ticks(n_turns)` per ogni NPCMind
- **Stato:** DA FARE

---

### M6 — Cleanup (2026-04-10) ✅

#### Rimozione dead code ✅
- `src/luna/systems/initiative_system.py` — eliminato
- `src/luna/systems/activity_system.py` — eliminato
- `engine.py`: import rimossi, attributi rimossi
- `context_builder.py`: blocco ActivitySystem sostituito con `schedule_manager.get_npc_activity()`
  (ScheduleManager già aveva `get_npc_activity()` — sostituzione 1:1 senza perdita di funzionalità)

#### NPCLocationState unificato
- **File:** nuovo `src/luna/systems/npc_location_state.py`
- **Cosa fare:** Dataclass NPCLocationState + migrazione da 3 sistemi
- **Stato:** RIMANDATO (non critico, sistemi attuali funzionano)

---

### M7 — Test e fix bug

- Test di integrazione sessione completa
- Test poker hand completa
- Test cambio sessione (NPCMind persist)
- **Stato:** DA FARE

---

## Bug noti (da fixare durante sviluppo)

| Bug | File | Descrizione |
|-----|------|-------------|
| agents.py crash | `poker/agents.py:117` | `state.last_bet_or_raise_amount` non esiste |
| agents.py crash | `poker/agents.py:118` | `state.cfg.bb` non esiste |
| poker random | `poker/poker_game.py:127` | `random.choice` invece di engine_v2 |
| goal None | `npc_mind.py:_generate_goal` | Nessun fallback se template non matcha |
| emotion permanente | `world_simulator.py:tick` | Nessun TTL per forced emotional state |
| memory bleed | `context_builder.py` | companion_filter non sempre passato |
| director inutilizzato | `director.py` | `needs_director` sempre False |
| tension non injected | `tension_tracker.py` | hint mai passato al prompt |

---

## Note per prossime sessioni

- Iniziare sempre da questo file per capire dove eravamo rimasti
- Spec completa in: `docs/LUNA_V8_SPEC.md`
- Dopo ogni milestone: aggiornare questo file (✅ + data)
- Il venv v8 va creato manualmente la prima volta:
  ```
  cd D:\luna-rpg-v8
  python -m venv .venv
  .venv\Scripts\activate
  pip install -e .
  ```
- Le API keys vanno inserite nel `.env` (sono vuote per sicurezza)
