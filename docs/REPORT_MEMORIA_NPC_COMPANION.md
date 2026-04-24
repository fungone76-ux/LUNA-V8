# Report memoria NPC e Companion (School Life Complete)

Data: 2026-04-21  
Scope: `Luna`, `Stella`, `Maria`, `preside`, `segretaria`, `cuoca` + pipeline memoria breve/lungo termine.

## 1) Come funziona oggi (in breve)

### Memoria breve termine (STM)
- La STM conversazionale e' gestita da `MemoryManager` in cache (`_recent_messages`) + tabella DB `conversation_messages`.
- Ad ogni turno player/NPC, l'orchestrator salva i messaggi in `MemoryManager.add_message(...)` (`src/luna/agents/orchestrator/state_manager.py`).
- In prompt, `ContextBuilder` inserisce:
  - `conversation_history` (ultimi messaggi)
  - `memory_context` (fatti rilevanti)
  (`src/luna/agents/orchestrator/context_builder.py`).
- E' presente isolamento per companion via campo `companion` su messaggi/fatti.

### Memoria lungo termine narrativa (LTM)
- LTM narrativa = tabella `memory_entries` (`type=fact`, `importance`) + cache `_facts` (`src/luna/systems/memory.py`, `src/luna/core/database.py`).
- I fatti nascono da `changes["new_fact"]` in `_save()` orchestrator.
- Se attiva, memoria semantica (Chroma) supporta retrieval per similarita'.

### Memoria "viva" degli NPC (non solo testo)
- Stato mentale NPC (needs, emozioni, goal, unspoken, off-screen log) in `NPCMind` (`src/luna/systems/npc_mind.py`).
- Tick ogni turno via `WorldSimulator.tick()` (`src/luna/systems/world_sim/world_simulator.py`).
- Persistenza su tabella dedicata `npc_minds` (`DatabaseManager.save_npc_minds/load_npc_minds`).
- Al load viene simulato anche tempo offline (`simulate_offline_ticks`) per continuita'.

---

## 2) Valutazione integrazione con personaggi richiesti

### Companion (`Luna`, `Stella`, `Maria`)
- Hanno doppio livello memoria:
  1. conversazione/fatti (`MemoryManager`)
  2. stato interno dinamico (`NPCMind`).
- Architettura buona e modulare: il gioco ricorda sia cosa e' stato detto, sia come il personaggio "si sente" nel tempo.

### NPC secondari (`preside`, `segretaria`, `cuoca`)
- Sono presenti come `npc_templates` ricorrenti (`worlds/school_life_complete/npc_templates.yaml`) e hanno `NPCMind` persistente.
- Possono avere goal/relazioni/off-screen log, quindi memoria comportamentale reale.
- Memoria conversazionale in `MemoryManager` viene registrata solo quando parlano effettivamente nel flusso narrativo.

---

## 3) Problemi trovati (priorita' alta -> bassa)

## [ALTA] Incoerenza ID maiuscolo/minuscolo rompe parte di memoria/mood off-screen
- Evidenza: in world load i companion sono chiavi da `companion.name` (`"Luna"`, `"Stella"`, `"Maria"`) (`src/luna/systems/world.py`).
- Ma in `WorldSimulator` ci sono check hardcoded lowercase:
  - `if npc_id == "luna"` / `"stella"` / `"maria"` in `_simulate_npc_activity`
  - `if npc_id in ("luna", "stella", "maria")` in `_update_npc_mood_from_needs`
  (`src/luna/systems/world_sim/world_simulator.py`).
- Impatto: attivita' off-screen e mood automatici possono non scattare per i companion principali.

Soluzione proposta:
- Normalizzare sempre l'id con `npc_id_norm = npc_id.lower().strip()` prima dei confronti hardcoded.
- Oppure (meglio) eliminare hardcode e pilotare da metadata world (`npc_traits`/tag YAML).

## [ALTA] Possibile leakage memoria semantica tra companion
- Evidenza: durante `MemoryManager.load()`, i facts vengono reinseriti nel vector store senza metadata companion (`src/luna/systems/memory.py`).
- Il filtro semantico per companion dipende da metadata `companion`/`npc`; senza metadata, record legacy passano il filtro.
- Impatto: richiami memoria non sempre isolati per companion attivo.

Soluzione proposta:
- In `load()`, quando chiami `_semantic_store.add_memory(...)`, includere `companion` del fact.
- Eseguire una reindicizzazione una tantum delle sessioni vecchie.

## [MEDIA] Fatti LTM troppo dipendenti da `new_fact` (copertura incompleta)
- Evidenza: `_save()` aggiunge fact solo se `changes.get("new_fact")` e' valorizzato (`src/luna/agents/orchestrator/state_manager.py`).
- Impatto: eventi importanti (off-screen, svolte relazionali, decisioni missione) possono non finire in LTM testuale.

Soluzione proposta:
- Aggiungere estrazione eventi chiave post-turno (es. completamento quest stage, salto affinity, evento off-screen importante raccontato) e salvarli sempre come fact con importance graduata.

## [MEDIA] `state_memory.add_message()` ridondante/non usato
- Evidenza: metodo presente in `src/luna/systems/state_memory.py` ma il flusso usa `MemoryManager.add_message()`.
- Impatto: rischio confusione e divergenza futura.

Soluzione proposta:
- O rimuovere metodo ridondante, o farlo diventare unico entrypoint (ma uno solo).

## [BASSA] Messaggi DB filtrati diversamente rispetto al filtro in memoria
- Evidenza: `DatabaseManager.get_messages(companion_filter=...)` fa match esatto e non include `NULL`; `MemoryManager` invece include anche messaggi senza companion.
- Impatto: minimo ora (perche' `load()` non usa companion_filter SQL), ma possibile incoerenza futura.

Soluzione proposta:
- Uniformare policy: con filtro companion includere anche record globali (`companion IS NULL OR companion=''`).

---

## 4) Memoria breve vs lunga: stato qualitativo

- STM dialogica: buona per continuita' locale del dialogo.
- LTM fattuale: discreta ma dipende da trigger `new_fact` (da rinforzare).
- Memoria comportamentale NPC (`NPCMind`): molto buona, e' il pezzo piu' interessante del sistema.
- Persistenza complessiva: buona (DB + ripristino + offline ticks).

Valutazione complessiva: **7.5/10** (struttura forte, ma i 2 bug "alta" riducono immersione/consistenza).

---

## 5) Fix consigliati in ordine operativo

1. Correggere subito normalizzazione ID in `world_simulator.py` (bug piu' visibile in game).
2. Correggere metadata companion nel semantic store (`memory.py`) + migrazione/reindex.
3. Ampliare pipeline `new_fact` con estrattore eventi chiave automatico.
4. Pulizia API memoria (`state_memory.add_message`).
5. Uniformare policy SQL filter messaggi.

---

## 6) Impatto sui personaggi target

- `Luna` / `Stella` / `Maria`: con fix ID e semantic isolation diventano molto piu' coerenti (mood accumulato + ricordi contestuali giusti).
- `preside` / `segretaria` / `cuoca`: gia' buoni su memoria comportamentale (NPCMind); migliorano ulteriormente se il logging facts viene ampliato.

---

## 7) Nota finale

Il sistema base e' gia' superiore alla media: la parte `NPCMind + offline ticks + context injection` e' una base solida da prodotto. I fix sopra sono mirati e ad alto ROI: poca superficie di modifica, resa immersione nettamente migliore.
