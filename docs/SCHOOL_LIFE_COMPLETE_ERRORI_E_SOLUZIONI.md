# School Life Complete - Errori trovati e soluzioni proposte

## Obiettivo
Questo documento riassume gli errori emersi durante la verifica di `school_life_complete` e propone fix concreti, ordinati per priorita'.


## Stato rapido
- Verifica statica + runtime effettuata su loader world, quest engine e global events.
- Test rapidi passati: `tests/test_quest_coherence.py`, `tests/test_core_systems.py::TestWorldTimeNormalization`.
- Test legacy da aggiornare: `tests/test_story_beats.py`, `tests/test_beat_integration.py` (usano API non piu' disponibile: `load_from_folder`).

---

## 1) BLOCCANTE - Tipi di attivazione quest non rispettati
**Errore**
- Il motore considera di fatto solo `activation.conditions`.
- Tipi dichiarati nei YAML come `event`, `companion_initiative`, `time_since_flag`, `location_pass` non sono gestiti con logica dedicata.
- Nei YAML e' spesso usato `activation.trigger`, mentre il loader legge `activation.trigger_event`.

**Impatto**
- Le missioni possono attivarsi in momenti sbagliati o non attivarsi affatto.
- La progressione narrativa puo' diventare incoerente.

**Riferimenti**
- `src/luna/systems/quest_engine.py`
- `src/luna/systems/world.py`
- `worlds/school_life_complete/missions/stella_jealousy.yaml`
- `worlds/school_life_complete/missions/luna_private_lesson.yaml`

**Soluzione proposta**
1. Estendere `_find_eligible_quests()` in `quest_engine` con dispatcher per `activation_type`.
2. Supportare esplicitamente: `event`, `companion_initiative`, `time_since_flag`, `location_pass`.
3. Nel loader quest, normalizzare `trigger` -> `trigger_event` in modo retrocompatibile.
4. Aggiungere test unitari per ogni `activation_type`.

---

## 2) BLOCCANTE - `on_complete` delle missioni non viene caricato
**Errore**
- Il modello `QuestDefinition` prevede `on_complete` e il motore lo esegue.
- Ma il loader (`_process_quest`) non trasferisce `on_complete` dal YAML al modello.
- Risultato runtime osservato: `quests_with_on_complete_loaded = 0`.

**Impatto**
- Le azioni finali di missione (es. `time_advance`, flag finali) non partono.
- Le catene di missioni/eventi successive possono rompersi.

**Riferimenti**
- `src/luna/core/models/quest_models.py`
- `src/luna/systems/world.py`
- `src/luna/systems/quest_engine.py`

**Soluzione proposta**
1. In `_process_quest`, parsare `on_complete.actions` in lista di `QuestAction`.
2. Salvare il risultato in `QuestDefinition(on_complete=...)`.
3. Aggiungere test che verifica esecuzione reale di `on_complete` su completamento missione.

---

## 3) ALTO - Metadati stage `location`/`time` ignorati
**Errore**
- Nei YAML stage sono presenti campi `location` e `time`.
- `QuestStage` non li include, quindi quei vincoli non entrano nel runtime.

**Impatto**
- Le scene possono avanzare in luogo/orario non previsti dal design.

**Riferimenti**
- `src/luna/core/models/quest_models.py`
- `worlds/school_life_complete/missions/stella_basketball.yaml`
- `worlds/school_life_complete/missions/luna_final_choice.yaml`

**Soluzione proposta**
1. Aggiungere `location: Optional[str]` e `time: List[str]` a `QuestStage`.
2. Applicare gating in `_update_active_quest()` prima di valutare `exit_conditions`.
3. Aggiungere test: stage non avanza fuori da location/time previsti.

---

## 4) ALTO - `set_location` usa `target`, nei YAML spesso e' su `value`
**Errore**
- In `_execute_action`, `set_location` legge `target`.
- Molti YAML usano `value: "..."`.

**Impatto**
- Spostamenti di scena non applicati.
- Flusso missione incoerente (player e stage fuori sync).

**Riferimenti**
- `src/luna/systems/quest_engine.py`
- `worlds/school_life_complete/missions/luna_private_lesson.yaml`
- `worlds/school_life_complete/missions/stella_photoshoot.yaml`

**Soluzione proposta**
1. Rendere `set_location` tollerante: `destination = target or value`.
2. Loggare warning se `destination` mancante o location non valida.
3. Migrazione graduale YAML verso un solo standard (`target`).

---

## 5) ALTO - `global_events.effects` non propagato dal loader
**Errore**
- `GlobalEventDefinition` supporta `effects`, ma `world.py` non lo passa durante il build.
- Campi come `visual_tags`, `on_start`, `on_end`, `affinity_multiplier` vengono persi.

**Impatto**
- Eventi globali parziali: atmosfera/azioni mancanti, side-effect non applicati.

**Riferimenti**
- `src/luna/core/models/world_models.py`
- `src/luna/systems/world.py`
- `worlds/school_life_complete/global_events.yaml`

**Soluzione proposta**
1. In `WorldLoader`, valorizzare `effects=GlobalEventEffect(**evt_data.get("effects", {}))`.
2. Aggiungere test di serializzazione e test runtime su `on_start/on_end`.

---

## 6) ALTO - Trigger `scheduled` basati su `time` non compatibili col manager
**Errore**
- YAML usa `trigger.type: "scheduled"` con `trigger.time`.
- `GlobalEventManager` per `scheduled` cerca invece `turn` nelle condizioni.

**Impatto**
- Eventi giornalieri schedulati possono non attivarsi.

**Riferimenti**
- `src/luna/systems/global_events.py`
- `worlds/school_life_complete/global_events.yaml`

**Soluzione proposta**
1. Uniformare semantica: per `scheduled` supportare sia `time` sia `turn`.
2. Se presente `time`, confrontare con `game_state.time_of_day`.
3. Aggiungere test per entrambi i formati.

---

## 7) MEDIO - Mismatch outfit nei schedule companion
**Errore**
- Alcuni `schedule.outfit` non corrispondono a chiavi reali del `wardrobe`.

**Impatto**
- Fallback inattesi o outfit non applicato.

**Riferimenti**
- `worlds/school_life_complete/stella.yaml`
- `worlds/school_life_complete/luna.yaml`

**Soluzione proposta**
1. Allineare le chiavi schedule ai nomi effettivi di wardrobe.
2. Aggiungere validatore di coerenza world: `schedule.outfit in wardrobe`.

---

## 8) RISOLTO - NameError in Multi-NPC
**Errore (gia' corretto)**
- `active_npc_lower` usata senza inizializzazione in `process_turn`.

**Fix applicato**
- Aggiunta inizializzazione robusta:
- `active_npc_lower = (active_npc or "").lower().strip()`

**Riferimento**
- `src/luna/systems/multi_npc/manager.py`

---

## Backlog consigliato (ordine di implementazione)
1. Loader quest: `on_complete` + normalizzazione `trigger`/`trigger_event`.
2. Quest engine: gestione reale `activation_type` + gating `location/time` stage.
3. Action executor: `set_location` compatibile con `target` e `value`.
4. Loader global events: propagazione `effects` completa.
5. GlobalEventManager: supporto `scheduled` con `time` oltre a `turn`.
6. Pulizia YAML world (`outfit`, convenzioni campi).
7. Aggiornamento test legacy (`load_from_folder` -> API attuale loader).

## Criteri di accettazione post-fix
- Le missioni si attivano solo quando trigger e condizioni del YAML sono soddisfatti.
- `on_complete` esegue realmente azioni finali.
- Eventi globali applicano `effects`, `on_start`, `on_end`.
- Eventi `scheduled` funzionano con semantica oraria.
- Nessun mismatch outfit nei companion principali.

