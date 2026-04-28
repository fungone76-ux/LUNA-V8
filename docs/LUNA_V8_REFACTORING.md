# Luna RPG v8 — Piano di Refactoring Completo
# Documento per Claude Code CLI

**Data:** 2026-04-26  
**Codebase:** `D:/luna-rpg-v8/` (Windows, conda env, Python 3.12)  
**Stack:** Python + PySide6 + SQLAlchemy async + Gemini/Ollama API + ComfyUI  
**Entry point:** `src/luna/__main__.py` → `ui/app.py` → `core/engine.py`

---

## Contesto architetturale (leggi prima di toccare qualsiasi file)

Il gioco processa ogni turno in una pipeline di 12 step coordinata da:
- `src/luna/agents/orchestrator/orchestrator.py` → entry point `execute()`
- `src/luna/agents/orchestrator/phase_handlers.py` → le 5 fasi del turno

Il flusso dati del turno viaggia in `TurnContext` (turn_context.py).  
Lo stato del gioco vive in `GameState` (core/models/state_models.py).  
Le missioni sono definite in YAML sotto `worlds/<world_id>/missions/` e `worlds/<world_id>/events/`.  
Il quest engine attivo è `SequentialQuestEngine` in `systems/quest_engine_sequential.py`,  
che estende `QuestEngine` in `systems/quest_engine.py` (quest_engine.py contiene il cuore della logica).

---

## OPZIONE A — Pulizia file morti e duplicati

**Priorità:** Alta. Zero rischio di regressioni. Riduce confusione immediata.  
**Stima:** 30 minuti.

### A1 — Eliminare file backup/duplicati

I seguenti file sono versioni vecchie o backup non più usati. Nessun import li referenzia nel codice attivo.  
**Verificare con `grep -r "manager1\|config1\|config_models1" src/ --include="*.py"` prima di eliminare.**

| File da eliminare | Motivo |
|---|---|
| `src/luna/ai/manager1.py` | Backup di manager.py, non importato da nessuno |
| `src/luna/core/config1.py` | Backup di config.py, non importato da nessuno |
| `src/luna/core/models/config_models1.py` | Backup di config_models.py, non importato |
| `temp_dump.txt` (root del progetto) | File di debug da 110KB, dimenticato |

**Comando:**
```bash
rm src/luna/ai/manager1.py
rm src/luna/core/config1.py
rm src/luna/core/models/config_models1.py
rm temp_dump.txt
```

---

### A2 — Eliminare il vecchio quest_engine.py

**ATTENZIONE: questo è più delicato.** `quest_engine.py` (989 righe) NON è morto — viene importato da `quest_engine_sequential.py`:

```python
from luna.systems.quest_engine import QuestEngine, QuestUpdateResult
```

E contiene classi ancora attive: `QuestEngine`, `QuestUpdateResult`, `ConditionEvaluator`, `_execute_action`.

**NON eliminare quest_engine.py.** Invece, rinominarlo per chiarire il suo ruolo:

```bash
# Rinomina il file
mv src/luna/systems/quest_engine.py src/luna/systems/quest_engine_base.py

# Aggiorna l'import in quest_engine_sequential.py riga 10:
# DA:  from luna.systems.quest_engine import QuestEngine, QuestUpdateResult
# A:   from luna.systems.quest_engine_base import QuestEngine, QuestUpdateResult

# Aggiorna tutti gli altri import nel progetto:
grep -r "from luna.systems.quest_engine import\|import quest_engine" src/ --include="*.py"
# Aggiorna ciascuno sostituendo quest_engine con quest_engine_base
```

---

### A3 — Semplificare il world_simulator shim

`src/luna/systems/world_simulator.py` è già un file di 14 righe che fa solo re-export.  
**Non fare nulla** — è già pulito. È necessario per compatibilità backward con import sparsi.

---

### A4 — Pulizia __pycache__ e .pyc multipli

I `__pycache__` contengono `.pyc` compilati con pytest 7.4.4, 8.4.2, 9.0.x insieme.  
Questo non è un bug ma indica che i test non vengono runnati regolarmente.

```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -name "*.pyc" -delete
```

---

## OPZIONE B — Completare il Quest Engine

**Priorità:** Altissima. Impatto diretto sul gameplay e sulle missioni.  
**File principali coinvolti:**
- `src/luna/systems/quest_engine.py` → aggiungere i casi mancanti
- `src/luna/systems/quest_engine_sequential.py` → override per `companion_initiative`
- `worlds/school_life_complete/missions/stella_*.yaml` → riscrivere nel nuovo formato
- `worlds/school_life_complete/missions/maria_*.yaml` → riscrivere nel nuovo formato

---

### B1 — `on_complete.memory` — scrivere la memoria del personaggio

**Stato attuale:** FUNZIONA già al 90%. Il bug è che `_flush_pending_npc_memories()` esiste in `context_builder.py` (riga 296) ed è già chiamato (riga 283), ma il path `on_complete_memory` nel YAML **bypassa** `on_complete` in alcuni casi.

**Verifica:** Nel metodo `_advance_stage()` in `quest_engine.py` (circa riga 849):

```python
if quest_def.on_complete:
    self.execute_actions(quest_def.on_complete, game_state, self._engine)
if quest_def.on_complete_memory:
    mem = quest_def.on_complete_memory
    ...
    game_state.flags[f"_pending_npc_memory_{character}"] = {...}
```

Questo funziona. Il problema è nei YAML delle missioni di Stella e Maria: usano il vecchio campo `on_complete:` senza il sotto-campo `memory:`. Le missioni di Luna nel formato nuovo usano `on_complete_memory:` come campo YAML separato.

**Azione:** Verificare che `QuestDefinition` in `core/models/quest_models.py` abbia il campo `on_complete_memory` definito correttamente, e che il parser YAML (`systems/world.py`) lo carichi.

```bash
grep -n "on_complete_memory\|on_complete" src/luna/core/models/quest_models.py
grep -n "on_complete_memory" src/luna/systems/world.py
```

Se il campo non è nel modello, aggiungere:
```python
# In QuestDefinition (quest_models.py)
on_complete_memory: Optional[Dict[str, Any]] = None
```

---

### B2 — `activation_type: random` con cooldown corretto

**Stato attuale:** Parzialmente implementato. In `quest_engine.py` riga 616:

```python
elif quest_def.activation_type == "random":
    if quest_def.allowed_times:
        current_time = game_state.time_of_day.value ...
        if current_time not in quest_def.allowed_times:
            continue
    if quest_def.probability > 0 and random.random() >= quest_def.probability:
        continue
    if not self._evaluator.evaluate_all(quest_def.activation_conditions, ...):
        continue
```

Il cooldown esiste già (`game_state.flags[f"_cooldown_{quest_id}"]`) ma viene **settato solo al completamento** di una quest ripetibile. Per eventi random come `npc_preside_inspection` (che non si "completa" nello stesso senso), il cooldown non viene mai settato dopo l'attivazione.

**Fix da applicare in `quest_engine.py` nel metodo `_activate_quest()`:**

Trovare il metodo `_activate_quest()` e aggiungere, dopo aver settato lo stato ACTIVE, il cooldown immediato per le quest `random`:

```python
def _activate_quest(self, quest_def: QuestDefinition, game_state: GameState) -> None:
    # ... codice esistente ...
    
    # AGGIUNGERE: per quest random, setta cooldown immediato all'attivazione
    if quest_def.activation_type == "random" and quest_def.cooldown_turns > 0:
        game_state.flags[f"_cooldown_{quest_def.quest_id}"] = (
            game_state.turn_count + quest_def.cooldown_turns
        )
        logger.info(
            "[QuestEngine] Random quest '%s' activated, cooldown set: %d turns",
            quest_def.quest_id, quest_def.cooldown_turns,
        )
```

**Verificare che `QuestDefinition` abbia `cooldown_turns: int = 0` nel modello.**  
Il YAML di `npc_preside_inspection.yaml` usa `cooldown: 40` — verificare che il parser lo mappi a `cooldown_turns`.

```bash
grep -n "cooldown" src/luna/core/models/quest_models.py
grep -n "cooldown" src/luna/systems/world.py
```

---

### B3 — `activation_type: location_pass`

**Stato attuale:** Trattato uguale ad `auto` — valuta solo `activation_conditions`. Non ha logica specifica per "il giocatore sta passando da questo luogo".

**Cosa significa:** La quest si attiva quando `game_state.current_location` corrisponde a un certo valore, indipendentemente dal fatto che il giocatore ci "vada" esplicitamente. Ogni turno va controllato.

**Fix in `quest_engine.py`, nel dispatcher `_find_eligible_quests()`:**

Aggiungere prima del blocco `elif quest_def.activation_type in (...)`:

```python
elif quest_def.activation_type == "location_pass":
    # Si attiva se il giocatore è alla location richiesta
    required_location = quest_def.trigger_location  # nuovo campo nel modello
    if required_location and game_state.current_location != required_location:
        continue
    if quest_def.allowed_times:
        current_time = game_state.time_of_day.value if hasattr(game_state.time_of_day, "value") else str(game_state.time_of_day)
        if current_time not in quest_def.allowed_times:
            continue
    if not self._evaluator.evaluate_all(quest_def.activation_conditions, game_state, user_input):
        continue
```

**Aggiungere `trigger_location` a `QuestDefinition` in `quest_models.py`:**

```python
trigger_location: Optional[str] = None  # per activation_type: location_pass
```

**Parser YAML in `world.py`:** verificare che `trigger_location:` venga letto dal YAML e passato al modello.

**Esempio YAML (`luna_divorce_confession.yaml`):**
```yaml
activation:
  type: "location_pass"
  trigger_location: "ufficio_luna"   # ← nuovo campo
  allowed_times: ["Evening", "Night"]
  conditions:
    - type: "flag"
      target: "luna_private_lesson"
      value: true
```

---

### B4 — `activation_type: time_since_flag`

**Stato attuale:** Il `ConditionEvaluator` ha già il tipo `days_since_flag` per le **condizioni** (riga 153 di quest_engine.py). Ma come **activation_type**, `time_since_flag` viene trattato uguale ad `auto`.

**Cosa serve:** Quando `activation_type == "time_since_flag"`, la quest si attiva dopo X giorni dal momento in cui un determinato flag è stato settato.

**Fix in `quest_engine.py`, nel dispatcher:**

```python
elif quest_def.activation_type == "time_since_flag":
    # Legge il flag e il numero di giorni richiesti dal modello
    watch_flag = quest_def.trigger_flag       # nome del flag da osservare
    required_days = quest_def.trigger_days    # giorni da aspettare
    if not watch_flag:
        continue
    flag_set_turn = game_state.flags.get(f"_flag_ts_{watch_flag}")
    if flag_set_turn is None:
        continue  # flag non ancora settato
    turns_elapsed = game_state.turn_count - int(flag_set_turn)
    days_elapsed = turns_elapsed / 4  # 4 fasi = 1 giorno di gioco
    if days_elapsed < (required_days or 1):
        continue
    if not self._evaluator.evaluate_all(quest_def.activation_conditions, game_state, user_input):
        continue
```

**Aggiungere a `QuestDefinition`:**

```python
trigger_flag: Optional[str] = None   # flag da osservare per time_since_flag
trigger_days: int = 1                # giorni da aspettare dopo il flag
```

**Nota importante:** Il sistema di timestamp dei flag (`_flag_ts_{flag_name}`) è già implementato in `_execute_action()` per `set_flag` (riga 277). Quindi qualsiasi `set_flag` nel quest engine scrive già automaticamente il timestamp. Il tempo è in turni, con la convenzione 4 fasi/giorno già usata in `ConditionEvaluator.days_since_flag`.

---

### B5 — `activation_type: companion_initiative`

**Stato attuale:** Trattato uguale ad `auto`. Non ha connessione con NPCMind o TurnDirective.

**Cosa significa:** La quest si attiva quando è l'NPC stesso a prendere l'iniziativa — cioè quando `TurnDirective.driver == TurnDriver.NPC` e l'NPC attivo corrisponde al companion della quest.

**Approccio corretto:** Non modificare il dispatcher principale. Invece, nel momento in cui il `WorldSimulator` produce una `TurnDirective` con `driver=NPC`, passare questa informazione al quest engine tramite un flag temporaneo.

**Fix in `phase_handlers.py`, metodo `_phase_world_state()`, dopo lo step 2.5:**

```python
# Dopo: ctx.directive = self.engine.world_simulator.tick(...)
if ctx.directive and ctx.directive.driver.value == "npc":
    active_npc = ctx.game_state.active_companion
    # Setta flag temporaneo consumato dal quest engine questo turno
    ctx.game_state.flags["_npc_initiative_active"] = active_npc
else:
    ctx.game_state.flags.pop("_npc_initiative_active", None)
```

**Fix in `quest_engine.py`, nel dispatcher, aggiungere:**

```python
elif quest_def.activation_type == "companion_initiative":
    # Si attiva solo se questo turno il companion ha preso l'iniziativa
    initiative_npc = game_state.flags.get("_npc_initiative_active", "")
    quest_character = quest_def.character  # campo già presente in meta
    if not initiative_npc:
        continue
    if quest_character and initiative_npc.lower() != quest_character.lower():
        continue
    if quest_def.allowed_times:
        current_time = game_state.time_of_day.value if hasattr(game_state.time_of_day, "value") else str(game_state.time_of_day)
        if current_time not in quest_def.allowed_times:
            continue
    if not self._evaluator.evaluate_all(quest_def.activation_conditions, game_state, user_input):
        continue
```

**Nota:** `quest_def.character` deve essere letto dal YAML nella sezione `meta.character`. Verificare che sia nel modello:
```bash
grep -n "character" src/luna/core/models/quest_models.py
```

---

### B6 — Conversione missioni Stella nel nuovo formato

Le 4 missioni di Stella sono attualmente nel vecchio formato dentro `worlds/school_life_complete/stella.yaml` (sezione `quests:`). Vanno estratte in file separati sotto `worlds/school_life_complete/missions/`.

**Regole obbligatorie per ogni missione (dal STATO_PROGETTO.md):**
```
- once: true
- on_enter: set_outfit + set_location sempre presenti
- llm_context: tutto in inglese
- exit_conditions: player_action con pattern di saluto
- on_complete: time_advance + on_complete_memory (character, entry, emotional_impact)
- Il trigger è narrativo, non solo una soglia di affinità
- Le scene esplicite sono permesse e non vanno ammorbidite
```

**Le 4 missioni di Stella (file da creare):**

**`missions/stella_photoshoot.yaml`**
- Trigger narrativo: Stella ferma il giocatore nel corridoio e chiede di fotografarla
- Stage 1 `invitation`: corridoio, uniform_mod
- Stage 2 `the_shoot`: palestra, sport (o swimsuit se nell'arco)
- Uscita libera con saluto
- on_complete_memory: "Il servizio fotografico — per la prima volta mi ha guardata come una persona, non come una bambola"

**`missions/stella_jealousy.yaml`**
- Trigger narrativo: Stella vede il giocatore vicino a Luna o Maria
- Activation type: `event`, trigger_event: `stella_jealousy_trigger`
- Stage 1: confronto in corridoio
- Stage 2: scena di chiarimento intimo
- on_complete_memory: "Quando ti ho visto con lei ho capito che ero gelosa. Non lo ammetto ancora."

**`missions/stella_basketball.yaml`**
- Trigger narrativo: Stella sfida il giocatore al campo da basket
- Activation type: `companion_initiative` + affinità ≥ 30 + pomeriggio
- Stage 1: sfida al campo
- Stage 2: docce / dopo partita
- on_complete_memory: "Per la prima volta ho perso qualcosa che volevo vincere. E non me ne importava."

**`missions/stella_confession.yaml`**
- Trigger narrativo: sera tardi, Stella cerca il giocatore
- Activation type: `companion_initiative` + affinità ≥ 60 + M3 completata + sera
- Stage 1: richiesta di incontro
- Stage 2: camera di Stella, prom_dress o pajamas
- on_complete_memory: "Quella notte ho detto cose che non avevo mai detto a nessuno."

**Dopo aver creato i file:**
1. Rimuovere la sezione `quests:` da `stella.yaml`
2. Verificare che `world.py` carichi le sottocartelle `missions/` per stella (dovrebbe già farlo)

---

### B7 — Conversione missioni Maria nel nuovo formato

Stessa operazione per Maria. Le missioni esistenti in `maria.yaml` vanno estratte.

**Le 4 missioni di Maria (file da creare):**

Sono già parzialmente definite in `worlds/school_life_complete/missions/`:
- `maria_defense.yaml` ✅ (esiste già nel nuovo formato)
- `maria_home_dinner.yaml` ✅ (esiste già)
- `maria_night.yaml` ✅ (esiste già)
- `maria_secrets.yaml` ✅ (esiste già)

**Azione:** Verificare che le missioni Maria già esistenti nella cartella `missions/` siano complete e corrette, poi rimuovere la sezione `quests:` da `maria.yaml`.

```bash
# Controlla quali missioni maria sono già migrate
ls worlds/school_life_complete/missions/maria_*.yaml
# Controlla se maria.yaml ha ancora una sezione quests:
grep -n "^quests:" worlds/school_life_complete/maria.yaml
```

---

### B8 — Correzione `_execute_action` per tipo `memory`

Attualmente non esiste un action type `memory` in `_execute_action()`. Le missioni nel nuovo formato usano `on_complete_memory` come campo YAML top-level (non come action). Ma alcune missioni potrebbero voler scrivere memoria anche in `on_enter` o in stage `on_complete`.

**Aggiungere in `_execute_action()` in `quest_engine.py`:**

```python
elif act == "write_memory":
    # action: write_memory
    # character: Luna
    # entry: "Descrizione evento da memorizzare"
    # emotional_impact: intimate (opzionale)
    character = char or game_state.active_companion
    entry_text = str(value or "")
    emotional_impact = action.emotional_impact if hasattr(action, "emotional_impact") else action.get("emotional_impact", "neutral")
    if character and entry_text:
        game_state.flags[f"_pending_npc_memory_{character}"] = {
            "entry": entry_text,
            "emotional_impact": emotional_impact,
        }
        logger.info("[QuestAction] write_memory queued for '%s'", character)
```

---

## OPZIONE C — Spezzare phase_handlers.py

**Priorità:** Media. Non risolve bug, ma migliora drasticamente la manutenibilità.  
**File coinvolto:** `src/luna/agents/orchestrator/phase_handlers.py` (1227 righe)

Il file contiene già i 5 metodi di fase (`_phase_pre_turn`, `_phase_world_state`, ecc.) più 3 helper enormi. L'obiettivo è estrarre i 3 helper in file separati mantenendo il pattern mixin esistente.

---

### C1 — Estrarre `_run_gm_agenda` → `gm_agenda_runner.py`

**Dove si trova:** `phase_handlers.py`, metodo `_run_gm_agenda()`, circa 144 righe (dalla sezione `# Helper privati`).

**Azione:**
1. Creare `src/luna/agents/orchestrator/gm_agenda_runner.py`
2. Definire la classe `GmAgendaRunnerMixin` con il metodo `_run_gm_agenda(self, ctx: TurnContext) -> TurnContext`
3. Incollare il corpo del metodo esatto (inclusi tutti gli import lazy dentro il metodo)
4. In `phase_handlers.py`: rimuovere il metodo, importare il mixin
5. In `orchestrator.py`: aggiungere `GmAgendaRunnerMixin` all'elenco delle classi base di `TurnOrchestrator`

**Struttura del nuovo file:**
```python
"""Luna RPG — GM Agenda Runner Mixin.

Step 2.9 del turno: seleziona e inietta la mossa GM.
Popola ctx.gm_agenda_context, ctx.gm_move_name, ctx.narrative_compass.
"""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Optional
from .turn_context import TurnContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)
_SOLO_COMPANION = "_solo_"


class GmAgendaRunnerMixin:
    async def _run_gm_agenda(self, ctx: TurnContext) -> TurnContext:
        # ... corpo del metodo esatto da phase_handlers.py ...
```

---

### C2 — Estrarre `_run_multi_npc` → `multi_npc_runner.py`

**Dove si trova:** `phase_handlers.py`, metodo `_run_multi_npc()`, circa 200 righe.

**Azione:** Stessa procedura del punto C1.

**Struttura del nuovo file:**
```python
"""Luna RPG — MultiNPC Runner Mixin.

Step 5.5 del turno: gestisce le scene con più NPC contemporaneamente.
Restituisce MultiNPCResult con completed_turns, image_paths, was_interrupted.
"""
from __future__ import annotations
import logging
from typing import TYPE_CHECKING
from .turn_context import MultiNPCResult, TurnContext

logger = logging.getLogger(__name__)


class MultiNpcRunnerMixin:
    async def _run_multi_npc(self, ctx: TurnContext) -> MultiNPCResult:
        # ... corpo del metodo esatto da phase_handlers.py ...
```

---

### C3 — Estrarre `_run_phase_clock` → `phase_clock_runner.py`

**Dove si trova:** `phase_handlers.py`, metodo `_run_phase_clock()`, circa 74 righe (Step 8 nella fase `_phase_finalize`).

**Stessa procedura.**

---

### C4 — Aggiornare orchestrator.py con i nuovi mixin

Dopo C1/C2/C3, `orchestrator.py` deve ereditare dai nuovi mixin. Aprire `orchestrator.py` e modificare:

```python
# DA:
from .phase_handlers import PhaseHandlersMixin

class TurnOrchestrator(
    PhaseHandlersMixin,
    IntentHandlersMixin,
    ...
):

# A:
from .phase_handlers import PhaseHandlersMixin
from .gm_agenda_runner import GmAgendaRunnerMixin
from .multi_npc_runner import MultiNpcRunnerMixin
from .phase_clock_runner import PhaseClockRunnerMixin

class TurnOrchestrator(
    PhaseHandlersMixin,
    GmAgendaRunnerMixin,
    MultiNpcRunnerMixin,
    PhaseClockRunnerMixin,
    IntentHandlersMixin,
    ...
):
```

---

### C5 — Risultato atteso dopo C1-C4

| File | Righe prima | Righe dopo |
|---|---|---|
| `phase_handlers.py` | 1227 | ~830 |
| `gm_agenda_runner.py` | 0 | ~160 |
| `multi_npc_runner.py` | 0 | ~220 |
| `phase_clock_runner.py` | 0 | ~90 |

Il comportamento del gioco non cambia. Solo la struttura.

---

## OPZIONE D — NPCLocationState unificato

**Priorità:** Bassa. La spec v8 (LUNA_V8_SPEC.md) la classifica come "non critico, sistemi attuali funzionano".  
**File coinvolti:** 3 sistemi da unificare + un nuovo dataclass.

---

### D1 — Il problema attuale

La posizione di ogni NPC è tracciata in 3 posti separati:

1. `game_state.npc_locations` (dict `npc_id → location_id`) — posizione corrente effettiva
2. `ScheduleManager._schedules` — posizione base per fascia oraria
3. `game_state.npc_location_expires` (dict `npc_id → turn`) — scadenza override da inviti

Ogni sistema che ha bisogno di sapere "dove si trova un NPC" deve interrogare tutti e 3.

---

### D2 — Soluzione: classe NPCLocationState

Creare `src/luna/systems/npc_location_state.py`:

```python
"""NPCLocationState — posizione unificata di un NPC.

Sostituisce la tripla (npc_locations, _schedules, npc_location_expires).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NPCLocationState:
    npc_id: str
    base_location: str                      # dalla schedule (fascia oraria)
    override_location: Optional[str] = None # da invito / punizione / quest
    override_expires_turn: Optional[int] = None
    override_reason: str = ""               # "invited" | "punished" | "quest"

    @property
    def current_location(self) -> str:
        """Restituisce la location effettiva considerando eventuali override."""
        if (
            self.override_location is not None
            and self.override_expires_turn is not None
        ):
            return self.override_location
        return self.base_location

    def is_override_expired(self, current_turn: int) -> bool:
        if self.override_expires_turn is None:
            return False
        return current_turn >= self.override_expires_turn

    def clear_override(self) -> None:
        self.override_location = None
        self.override_expires_turn = None
        self.override_reason = ""

    def set_override(
        self,
        location: str,
        expires_turn: int,
        reason: str = "manual",
    ) -> None:
        self.override_location = location
        self.override_expires_turn = expires_turn
        self.override_reason = reason
```

---

### D3 — Migrazione

**Fase 1:** Creare `NPCLocationState` e usarlo in `ScheduleManager` come struttura interna.  
Modificare `ScheduleManager.get_npc_location(npc, phase)` per restituire `NPCLocationState.current_location`.

**Fase 2:** In `GameState`, aggiungere `npc_location_states: Dict[str, NPCLocationState] = {}`.  
Mantenere `npc_locations` come property computed per compatibilità backward:

```python
@property
def npc_locations_computed(self) -> Dict[str, str]:
    return {nid: s.current_location for nid, s in self.npc_location_states.items()}
```

**Fase 3:** Aggiornare `engine._on_phase_change()`, `InvitationManager`, e `quest_engine` `set_location` action per usare `NPCLocationState` invece di modificare direttamente i 3 dict separati.

**Fase 4:** Deprecare `game_state.npc_location_expires` dopo che tutti i writer sono migrati.

**⚠ Nota:** Questa migrazione è la più rischiosa delle 4 opzioni perché `npc_locations` viene letto/scritto in decine di posti. Procedere con test di integrazione ad ogni step.

---

## Ordine di esecuzione consigliato

```
A (pulizia)        → immediato, zero rischi
B1, B2             → fix quest engine isolati, basso rischio
B3, B4, B5         → nuovi activation_type, testare con un world nuovo
B6, B7             → YAML puro, zero impatto sul codice
B8                 → aggiunta action type, additive
C1, C2, C3, C4     → refactoring strutturale, nessun bug fix
D                  → solo se le posizioni NPC danno problemi concreti
```

---

## Come testare dopo ogni modifica

```bash
# Test rapido: avvia il gioco in modalità no-media
cd D:/luna-rpg-v8
python -m luna --no-media

# Test quest engine in isolamento
python -m pytest tests/test_quest_coherence.py -v

# Test narrative coherence
python -m pytest tests/test_narrative_coherence.py -v

# Test completo
python -m pytest tests/ -v --tb=short
```

Per testare i nuovi `activation_type`:
1. Creare una quest di test con `activation_type: random` e `probability: 1.0` (si attiva sempre)
2. Verificare che si attivi al turno successivo
3. Verificare che il cooldown prevenga la ri-attivazione immediata

---

## File di riferimento chiave

| Cosa cerchi | File |
|---|---|
| Pipeline completa del turno | `agents/orchestrator/phase_handlers.py` |
| Logica attivazione quest | `systems/quest_engine.py` → `_find_eligible_quests()` |
| Esecuzione azioni quest | `systems/quest_engine.py` → `_execute_action()` |
| Valutazione condizioni | `systems/quest_engine.py` → `ConditionEvaluator._eval()` |
| Avanzamento stage | `systems/quest_engine.py` → `_advance_stage()` |
| Modello QuestDefinition | `core/models/quest_models.py` |
| Formato YAML missioni | `worlds/school_life_complete/missions/luna_private_lesson.yaml` (esempio completo) |
| Stato gioco | `core/models/state_models.py` → `GameState` |
| NPCMind | `systems/npc_mind.py` → `NPCMind`, `NPCMindManager` |
| WorldSimulator | `systems/world_sim/world_simulator.py` |
| TurnDirective | `systems/world_sim/turn_director.py` |
