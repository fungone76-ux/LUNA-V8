# Piano implementazione: dialogo con NPC nel mini-game Poker

Questo documento descrive come implementerei la possibilita' di parlare con le NPC durante la partita di poker, senza rompere il flusso delle azioni di gioco.

## Obiettivi

- Permettere input conversazionali durante il poker.
- Distinguere in modo affidabile tra azioni poker e messaggi dialogo.
- Mantenere UX chiara nella finestra poker.
- Usare LLM quando disponibile, con fallback deterministico.
- Preservare stato conversazionale nei salvataggi.
- Evitare regressioni sul gameplay esistente.

## Checklist implementativa

- [ ] Definire UX comandi e comportamento input ambiguo.
- [ ] Estendere parser input in `poker_game.py`.
- [ ] Aggiungere routing tra azione poker e dialogo.
- [ ] Implementare risposta NPC (LLM + fallback).
- [ ] Aggiornare UI (`poker_window.py`) con hint e formato chat.
- [ ] Aggiungere guardrail contenuti e limiti input/output.
- [ ] Serializzare stato dialogo in `to_dict`/`from_dict`.
- [ ] Scrivere test minimi e criteri di accettazione.

## 1) UX e comandi

File: `src/luna/ui/poker_window.py`

Proposta comandi:

- Azioni poker: invariate (`vedo`, `fold`, `check`, `punto X`, `rilancio X`, `all-in`, `esci`).
- Dialogo esplicito: `/d <messaggio>`.
- Opzionale targeting: `/d @Nome <messaggio>`.

Comportamento consigliato:

- Se input inizia con `/d`, e' dialogo.
- Se input corrisponde a un'azione poker valida, resta azione poker.
- In caso ambiguo (es. "passo"), priorita' al poker.

Aggiornamenti UI:

- Hint basso: aggiungere `/d ciao` e `/d @Luna come stai?`.
- Placeholder input: "Azione poker o /d messaggio...".
- Startup hint: spiegare il doppio canale (gioco + dialogo).

## 2) Parsing unificato input

File: `src/luna/systems/mini_games/poker/poker_game.py`

Introdurre parser unico, ad esempio `parse_poker_input(text)` che ritorna:

- `{"kind": "system", "action": "exit"}`
- `{"kind": "poker", "action": "call"}`
- `{"kind": "poker", "action": "raise", "amount": 600}`
- `{"kind": "dialogue", "target": "Luna", "text": "..."}`

Regole:

- Prima intercettare `/d`.
- Poi tentare parse poker (riuso regex esistenti).
- Se non matcha nulla: trattare come dialogo libero solo se flag attivo; altrimenti errore con hint.

## 3) Routing nel ciclo turno

File: `src/luna/systems/mini_games/poker/poker_game.py`

In `process_action(...)`:

1. Parse input con parser unico.
2. Se `kind == poker`: flusso attuale invariato (`_apply_player_action`, NPC, showdown...).
3. Se `kind == dialogue`: chiamare `handle_dialogue_turn(...)` senza avanzare betting round.
4. Se `kind == system` (`exit`): terminare partita.

Vincolo importante:

- Un turno dialogo non deve modificare pot, street, stack o to_act.

## 4) Generazione risposta NPC (LLM + fallback)

File: `src/luna/systems/mini_games/poker/poker_game.py`

Nuovo metodo: `_generate_poker_dialogue_reply(target, user_text, game_state)`

Context minimo da passare al modello:

- NPC target, strip level, stack corrente, street, board sintetico.
- Affinita' e stato emotivo dal `game_state`.
- Ultimi N messaggi dal contesto dialogo poker.

Prompting:

- Italiano, risposta breve (1-2 frasi), tono coerente al personaggio.
- Niente avanzamento azione poker implicito.

Fallback se LLM non disponibile/errore:

- Template deterministici per NPC + stato (calma, provocazione, tensione).
- Risposta generica sicura se manca tutto il resto.

## 5) Formato chat e rendering messaggi

File: `src/luna/ui/poker_window.py`

Suggerimento formato:

- `[POKER]` per azioni tecnico-gioco.
- `[DIALOGO] Tu -> NPC: ...`
- `[DIALOGO] NPC: ...`
- `[SISTEMA]` per hint/errori.

Note:

- Riutilizzare `_append_user`, `_append_npc`, `_append_system`.
- Aggiungere stile diverso (colore) per dialogo NPC per leggibilita'.

## 6) Sicurezza contenuti

File: `src/luna/systems/mini_games/poker/poker_game.py`

Guardrail minimi:

- Max lunghezza input utente (es. 280 caratteri).
- Strip whitespace e sanitizzazione base.
- Limite lunghezza output LLM (es. max 220 caratteri) con truncation.
- Timeout/fail-safe: fallback immediato.

## 7) Persistenza stato conversazione

File: `src/luna/systems/mini_games/poker/poker_game.py`

Estendere `to_dict`/`from_dict` con:

- `dialog_enabled` (feature flag)
- `dialog_history` (ultimi N scambi)
- eventuale `last_target_npc`

Conservare solo la finestra recente (es. 12 messaggi) per evitare payload grandi.

## 8) Test minimi

Cartella: `tests/`

Nuovi test suggeriti:

- `test_poker_dialogue_parser.py`
  - parse corretto `/d`, azioni poker, input ambiguo.
- `test_poker_dialogue_routing.py`
  - dialogo non altera street/pot/to_act.
- `test_poker_dialogue_fallback.py`
  - senza LLM torna risposta valida non vuota.
- `test_poker_dialogue_serialization.py`
  - history preservata su `to_dict`/`from_dict`.

## 9) Rollout consigliato

- Feature flag: `poker_dialogue_enabled` (default off in produzione).
- Abilitare prima in ambienti dev/world di test.
- Monitorare errori su `llm_manager.generate` e tempi risposta.

## Criteri di accettazione

- Input `/d` produce sempre risposta NPC (LLM o fallback).
- Azioni poker esistenti restano invariate.
- Nessun crash con `llm_manager` assente.
- Dialogo non cambia stato del round poker.
- Stato dialogo persiste correttamente nei salvataggi.

