# Luna RPG v8 — Stato Completo del Progetto

## Obiettivo generale
Riscrivere completamente il sistema missioni ed eventi. Il vecchio sistema attivava le missioni in modo silenzioso al raggiungimento di soglie di affinità. Il nuovo sistema ha:
- Ogni missione con **trigger narrativo specifico** (un evento in gioco, un'azione del giocatore)
- **Inizio e fine chiari** — la missione si attiva, si svolge, si chiude
- **Luogo fisso** — ogni scena ha un `location` e un `outfit` definiti
- **LLM context in inglese** — iniettato nel prompt solo quando la missione è attiva
- **`once: true`** — la missione non si ripete dopo il completamento
- **`on_complete.memory`** — ciò che accade viene scritto nella memoria del personaggio
- **Uscita libera** — il giocatore decide quando uscire con un saluto naturale (`player_action` exit)
- **`time_advance`** on complete — dopo il saluto il tempo avanza e gli NPC seguono la loro schedule
- Affinità è **conseguenza**, non prerequisito

---

## Architettura tecnica — cosa è stato modificato

### `src/luna/core/models/quest_models.py`
- Aggiunto `time_advance`, `set_secondary_npc`, `clear_secondary_npc` alle azioni
- Aggiunto `player_action`, `days_since_flag` ai tipi condizione
- Aggiunto `flag`, `days` come campi opzionali in `QuestCondition`
- Aggiunto `llm_context: Dict[str, Any]` a `QuestStage`
- Aggiunto `on_complete: List[QuestAction]` a `QuestDefinition`
- Estesi i tipi di `activation_type`: `event`, `random`, `time_since_flag`, `companion_initiative`, `location_pass`

### `src/luna/systems/quest_engine.py`
- `_advance_stage()`: esegue `quest_def.on_complete` dopo `_apply_rewards()`
- `_execute_action()`: gestori per `time_advance`, `set_secondary_npc`, `clear_secondary_npc`
- `_build_context()`: inietta i campi `llm_context` nel prompt LLM
- `ConditionEvaluator._eval()`: aggiunto tipo `player_action` (legge `_last_player_input`)

### `src/luna/systems/world.py`
- Aggiunto loop per le sottocartelle `missions/` ed `events/` nel caricamento del mondo
- I file nelle sottocartelle vengono letti e mergiati come se fossero `quests:`

### `worlds/school_life_complete/luna.yaml`
- Rimossa l'intera sezione `quests:` (era il vecchio sistema)
- Commento di riferimento alle sottocartelle missioni

---

## File missioni creati — School Life Complete

### Cartella `worlds/school_life_complete/missions/`

| File | ID | Trigger | Stato |
|------|-----|---------|-------|
| `luna_private_lesson.yaml` | `luna_private_lesson` | `classroom_interrogation_success` + affinity ≥ 5 | ✅ carica |
| `luna_divorce_confession.yaml` | `luna_divorce_confession` | `location_pass` ufficio + sera + M1 fatto + 2gg dopo | ✅ carica |
| `luna_gym_substitute.yaml` | `luna_gym_substitute` | mattina + `luna_physically_opened_up` + 1gg dopo M2 | ✅ carica |
| `luna_final_choice.yaml` | `luna_final_choice` | `companion_initiative` + affinity ≥ 75 + M3 fatto + sera | ✅ carica |

### Cartella `worlds/school_life_complete/events/`

| File | ID | Tipo | Stato |
|------|-----|------|-------|
| `npc_preside_inspection.yaml` | `npc_preside_inspection` | Evento random (8%, cooldown 40 turni) | ✅ carica |

---

## Dettaglio missioni Luna (school_life_complete)

### M1 — La Lezione Privata (`luna_private_lesson`)
- **Trigger:** `classroom_interrogation_success` + affinità ≥ 5
- **Stage 1 `invitation`:** Luna trattiene il giocatore dopo la lezione — aula, teacher_suit
- **Stage 2 `the_lesson`:** Studio di Luna, porta chiusa — ufficio, private_tutoring. Scena seduttiva graduale. Uscita libera con saluto.
- **On complete:** time_advance + memoria Luna ("La prima lezione privata...")
- **Once:** sì

### M2 — La Confessione (`luna_divorce_confession`)
- **Trigger:** giocatore passa davanti all'ufficio di sera + M1 completata + almeno 2 giorni dopo
- **Stage 1 `the_light`:** corridoio, luce accesa nell'ufficio di Luna
- **Stage 2 `confession`:** Studio di Luna, casual_teacher. Luna parla della sua solitudine fisica. Scena molto esplicita. Uscita libera.
- **On complete:** time_advance + memoria Luna
- **Once:** sì

### M3 — Supplenza in Palestra (`luna_gym_substitute`)
- **Trigger:** mattina + `luna_physically_opened_up` + almeno 1 giorno dopo M2
- **Stage 1 `announcement`:** corridoio, annuncio interfono — Luna fa supplenza in palestra
- **Stage 2 `the_class`:** palestra, gym_teacher. Lezione di ginnastica, poi studenti escono — scena esplicita con Luna in tuta.
- **On complete:** time_advance + memoria Luna
- **Once:** sì

### M4 — La Scelta Finale (`luna_final_choice`)
- **Trigger:** `companion_initiative` + affinità ≥ 75 + M3 completata + sera
- **Stage 1 `the_invitation`:** ufficio Luna, sera tardi — la invita a casa sua
- **Stage 2 `her_home`:** casa di Luna, lingerie. Scena completamente esplicita, nessun limite.
- **On complete:** time_advance + memoria Luna
- **Once:** sì

### Evento NPC — L'Ispezione del Preside (`npc_preside_inspection`)
- **Trigger:** random, 8% chance, cooldown 40 turni, mai durante M1-M4 attive
- **Meccanica:** alternanza 2 turni — turno dispari: Preside parla + immagine multi-personaggio (Preside+Luna); turno pari: Luna risponde + immagine singola (Luna con stato aggiornato)
- **LLM:** istruito a fare ricatto progressivo, Luna riluttante ma sempre compliant
- **`[IMAGE:]` tag** a fine risposta segnala il tipo di immagine da generare
- **On complete:** `clear_secondary_npc` + time_advance + memoria Luna
- **Once:** no (può ripetersi)

---

## Cosa manca da fare

### STELLA — School Life Complete
Tutte e 4 le missioni di Stella sono ancora nel vecchio formato in `stella.yaml`.
Vanno riscritte seguendo il nuovo standard (trigger narrativo, once, llm_context inglese, outfit, location, on_complete memory, time_advance).

Idee discusse:
- M1: servizio fotografico — trigger: Stella chiede consiglio su look per un evento
- M2: sfida a basket — trigger: Stella sfida il giocatore al campo
- M3: scena di gelosia — trigger: Stella vede il giocatore vicino a Luna/Maria
- M4: "sei mio" — trigger: companion_initiative + affinità alta, sera

### MARIA — School Life Complete
Tutte e 4 le missioni di Maria ancora nel vecchio formato in `maria.yaml`.
Stessa cosa: riscrivere con nuovo standard.

### Valnera e Prehistoric Tribe
Mondo ancora non toccato. Zero missioni nel nuovo formato.

### Handler del quest engine ancora mancanti
- `ConditionEvaluator` non gestisce `days_since_flag` — serve handler in `quest_engine.py`
- `activation_type: "random"` — serve logica probabilità + cooldown nel quest engine
- `activation_type: "location_pass"` / `"time_since_flag"` / `"companion_initiative"` — nessuna logica implementata
- `on_complete.memory` nel YAML non è ancora parsato — serve scrittura in `CharacterMemory`

---

## Regole standard (da rispettare in ogni nuova missione)

```
- once: true  (per missioni narrative)
- on_enter: set_outfit + set_location sempre presenti
- llm_context: tutto in inglese
- exit_conditions: player_action con pattern di saluto (incluso italiano: arrivederci, vado, ecc.)
- on_complete: time_advance + memory (character, entry, emotional_impact, flags_to_record)
- Le scene esplicite sono permesse e non vanno ammorbidite
- Titoli/descrizioni player-facing possono essere in italiano
- I campi narrative_prompt e companion_situation vanno in inglese
```
