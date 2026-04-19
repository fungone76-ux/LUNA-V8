# Eventi Core: NPC Secondari e Missioni Companion

Questo documento riassume dove vengono gestiti gli eventi nel gioco principale (non poker), i problemi principali osservati e le soluzioni proposte.

## 1) Mappa rapida del sistema eventi

| Area | Tipo | Origine (file/simbolo) | Gestione turno | Output/UI | Stato |
|---|---|---|---|---|---|
| NPC secondari | Goal/Event hint | `src/luna/systems/npc_goal_evaluator.py` (`NpcGoalEvaluator.evaluate`, `GoalHint`) | `src/luna/agents/orchestrator/phase_handlers.py` | `TurnResult.npc_action` in `src/luna/core/models/output_models.py` | Confermato |
| NPC secondari | Interventi contestuali | `src/luna/systems/multi_npc/manager.py` (`process_turn`, `check_intervention`) | Trigger durante il turno | Testo in UI | Confermato |
| NPC secondari | Iniziative autonome | `src/luna/systems/npc_initiative_turn.py` (`NpcInitiativeTurn.run`) | Coda iniziative/azioni NPC | UI via output turno | Confermato |
| NPC secondari | Eventi dinamici/globali | `src/luna/systems/dynamic_events.py`, `src/luna/systems/gameplay_manager.py` | Routing evento globale/dinamico | `src/luna/ui/main_window/display_manager.py` | Parzialmente confermato |
| Companion (Luna/Stella/Maria) | Definizione missioni | `worlds/valnera/luna.yaml`, `worlds/valnera/maria.yaml`, `worlds/valnera/stella.yaml` (`quests:`) | Caricamento in `src/luna/systems/world.py` (`WorldLoader`) | Stato quest nel contesto | Confermato |
| Companion (Luna/Stella/Maria) | Aggiornamento missioni | `src/luna/systems/quest_engine.py` (`QuestEngine.update`) | Richiamo in `src/luna/agents/orchestrator/context_builder.py` | Progressione narrativa quest | Confermato |
| Companion (Luna/Stella/Maria) | Path alternativo update | `src/luna/agents/guardian.py` (`StateGuardian._apply_quests`) | Applicazione guidata da stato/LLM | Effetto su stato/output | Parzialmente confermato |

## 2) Criticita principali

| Priorita | Problema | Impatto |
|---|---|---|
| P1 | Routing incoerente tra evento e scelta utente (`EVENT_CHOICE`) | Eventi che partono in modo non coerente o scelta non applicata correttamente |
| P2 | Mismatch ID/nome NPC (normalizzazione, maiuscole/minuscole) | Companion coerenti, NPC secondari meno affidabili |
| P3 | Doppio canale di aggiornamento missioni (engine + guardian) | Progressioni quest non prevedibili |
| P4 | Render UI non uniforme per alcuni `dynamic_event` | Sensazione di eventi deboli o scollegati dalla scena |

## 3) Soluzioni proposte

### Soluzione A - Stabilizzare il routing eventi/scelte (P1)
- Allineare gestione `has_pending_event` e `EVENT_CHOICE` tra:
  - `src/luna/agents/intent_router.py`
  - `src/luna/systems/global_events.py`
  - `src/luna/systems/gameplay_manager.py`
  - `src/luna/ui/main_window/event_handler.py`
- Obiettivo: una sola fonte di verita per lo stato "evento pendente".

### Soluzione B - Normalizzare gli ID NPC (P2)
- Introdurre una normalizzazione centralizzata per nome/ID NPC (`lowercase`, trim, mappa alias).
- Applicare la normalizzazione nei punti di matching in `world_sim` e `multi_npc`.
- Obiettivo: evitare eventi persi o assegnati al personaggio sbagliato.

### Soluzione C - Unificare update missioni companion (P3)
- Definire un percorso primario: `QuestEngine.update`.
- Lasciare `StateGuardian._apply_quests` solo come fallback controllato (con flag/telemetria).
- Obiettivo: eliminare avanzamenti duplicati o regressioni di stato.

### Soluzione D - Rendere coerente il rendering in UI (P4)
- Uniformare payload eventi (`type`, `source`, `npc_id`, `priority`, `cooldown`, `text`).
- Gestire in modo uniforme in `display_manager` gli eventi provenienti da `dynamic_events`.
- Obiettivo: output consistente tra evento interno e testo mostrato.

## 4) Piano di implementazione consigliato

1. **Fix P1**: routing `EVENT_CHOICE` + stato evento pendente.
2. **Fix P2**: normalizzazione ID NPC in tutta la pipeline.
3. **Fix P3**: unificazione percorso missioni companion.
4. **Fix P4**: allineamento renderer/payload UI.

## 5) Test di regressione minimi

- `tests/test_core_systems.py`: coerenza orchestrazione turno/evento.
- `tests/test_multi_npc.py`: interventi NPC secondari.
- `tests/test_gm_agenda.py`: coerenza avanzamento narrativo.
- Nuovi test consigliati:
  - `tests/unit/test_event_choice_routing.py`
  - `tests/unit/test_npc_id_normalization.py`
  - `tests/unit/test_companion_quest_update_single_path.py`

## 6) Nota sicurezza configurazione (.env)

Nel file `.env1` e presente una chiave API sensibile (`ANTHROPIC_API_KEY`).

Azioni consigliate immediate:
1. Rigenerare/revocare la chiave dal provider.
2. Spostare credenziali in `.env` locale non versionato.
3. Verificare che `.gitignore` escluda sempre `.env*` e file credenziali JSON.
4. Se la chiave e stata mai committata, ripulire la history Git.

