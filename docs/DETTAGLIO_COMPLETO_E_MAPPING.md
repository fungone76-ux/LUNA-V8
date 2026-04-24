# Luna RPG v8 - Dettaglio completo + appendice mapping

## Scopo
Questo documento integra **documentazione** e **codice reale** per offrire una vista tecnica end-to-end del progetto, con un'appendice di mapping file -> responsabilita e simboli principali.

Analisi basata su lettura diretta di:
- documenti (`docs/*.md`, `STATO_PROGETTO.md`, `SETUP.md`)
- entrypoint/UI/core/agents/systems/tests/world YAML
- moduli poker e world simulation

## 1) Executive architecture (stato reale)

### Stack
- Linguaggio/runtime: Python 3.12+
- UI: PySide6 + qasync
- Persistenza: SQLAlchemy async + SQLite
- AI: provider chain (Gemini/Ollama/Moonshot/Claude) con retry/fallback
- Media: pipeline immagini/video opzionale (disattivabile con `--no-media` / flag env)
- Packaging/test: `pyproject.toml`, pytest

### Macro-layer
1. **Boot/UI layer**
   - `src/luna/__main__.py` imposta logging e delega a `luna.ui.app.main`.
   - `src/luna/ui/app.py` crea Qt app + event loop async + startup flow.
2. **Engine coordination layer**
   - `src/luna/core/engine.py` orchestra tutti i sottosistemi.
3. **Turn orchestration layer**
   - `src/luna/agents/orchestrator/*` implementa la pipeline di turno (fasi).
4. **Domain systems layer**
   - quest, world loading, memory, schedule, location/movement, world sim, gameplay, eventi.
5. **Infrastructure layer**
   - config/env, database, model package, media pipeline, LLM manager.

## 2) Flusso runtime end-to-end

### Avvio
- `python -m luna` -> `src/luna/__main__.py:main()`
- parsing argomenti (`--world`, `--companion`, `--no-media`, `--log-level`, `--session`)
- logging root + tee su `game_debug.log`
- bootstrap UI (`luna.ui.app.main`)

### Bootstrap UI
- `src/luna/ui/app.py`
  - crea `QApplication`
  - applica tema scuro
  - installa `QEventLoop` (qasync)
  - `ApplicationRunner.run()`:
    1. `StartupDialog`
    2. applicazione impostazioni execution mode
    3. `MainWindow.initialize_game(...)`

### Inizializzazione gioco
- `src/luna/ui/main_window/main_window.py:initialize_game`
  - crea `GameEngine(world_id, companion)`
  - `engine.initialize()` o `engine.load_session(session_id)`
  - collega callback UI (time change, messaggi intermedi MultiNPC, immagini intermedie)
  - aggiorna widget
  - genera intro (`engine.generate_intro()`)

### Loop di turno
- Input utente -> `GameController._on_send()` -> `engine.process_turn(text)`
- `GameEngine.process_turn` delega a `TurnOrchestrator.execute`
- pipeline (phase mixin) in `src/luna/agents/orchestrator/phase_handlers.py`:
  1. pre-turn (intent, intervention, switch, special intents)
  2. world state (world sim, tension, GM agenda, eventi)
  3. context build (memory/personality/quest/event/schedule/multi-npc hints)
  4. narrative (LLM + guardian + post-turn world sim)
  5. finalize (advance turn/phase, save, visual/media)
- output finale: `TurnResult` -> UI rendering (`DisplayManager.display_result`)

## 3) Core behavior per sottosistema

### Engine e stato
- `src/luna/core/engine.py`
  - coordinatore centrale; contiene riferimenti ai sistemi
  - init a 2 stadi:
    - `_init_systems()` (strutture principali)
    - `_init_runtime_systems(game_state)` (sistemi dipendenti da sessione/stato)
  - supporta phase advance manuale (`preview_phase_advance`, `advance_phase`)
  - persistenza runtime: `StateMemoryManager.save_all()`

- `src/luna/core/state.py`
  - ownership delle mutazioni di `GameState`
  - create/load/save session state JSON

### Orchestrazione narrativa
- `src/luna/agents/orchestrator/orchestrator.py`
  - compone mixin per separare responsabilita
  - inizializza intent router, narrative engine, visual director, guardian, director agent

- `src/luna/agents/orchestrator/context_builder.py`
  - compone il contesto LLM con:
    - memoria filtrata per companion
    - personality analysis + voice builder
    - quest/story/event/schedule context
    - npc presence context da world sim

- `src/luna/agents/narrative.py`
  - costruisce system prompt esteso e richiede output JSON compatto
  - converte risposta provider in `NarrativeOutput`

- `src/luna/agents/guardian.py`
  - gate deterministico su update LLM
  - clamping affinity, outfit update, flag/quest, npc emotion, facts/promises

- `src/luna/agents/visual.py`
  - traduce narrativa in prompt SD/visual output
  - gestione composizione, tag, anti-fusion multi-char, filtri global/per-companion

### Mondo e quest
- `src/luna/systems/world.py`
  - loader YAML legacy + modulare
  - merge file world + sottocartelle `missions/` e `events/`
  - normalizzazione time key, parsing companions/locations/quests/events

- `src/luna/systems/quest_engine.py`
  - activation/update/transition/fail/complete
  - evaluator typed (no eval)
  - azioni quest (`set_flag`, `set_location`, `set_outfit`, `set_emotional_state`, `time_advance`, ...)

- `src/luna/systems/quest_engine_sequential.py`
  - variante usata da engine v8
  - policy one-active-quest-at-a-time
  - journal snapshot per UI

### Simulazione mondo (v7/v8)
- `src/luna/systems/world_sim/world_simulator.py`
  - tick npc minds, off-screen events, ambient details, turn driver
  - emotional state TTL (revert su `default`)
- `src/luna/systems/world_sim/turn_director.py`
  - decide player/npc/ambient driver
  - policy `should_use_director` (NPC initiative, multi-NPC, alta tensione)

### Memoria e persistenza
- `src/luna/systems/memory.py`
  - history + facts + retrieval keyword/semantic
  - semantic memory opzionale via ChromaDB
- `src/luna/systems/state_memory.py`
  - save unificato multi-sistema in transaction
  - serializza flag/snapshot di phase clock, world sim, tension, invitations, quest states, npc minds

- `src/luna/core/database.py`
  - tabelle principali: `game_sessions`, `conversation_messages`, `memory_entries`, `quest_states`, `npc_minds`
  - API async CRUD + save/load NPC minds

### Scheduling, movement, eventi
- `src/luna/systems/schedule_manager.py`
  - schedule NPC da world + fallback da companion/default
- `src/luna/systems/location.py`
  - location state/discovery/validation movement
- `src/luna/systems/movement.py`
  - parsing intent movement italiano + target resolution
- `src/luna/systems/global_events.py`
  - attivazione/cooldown/priorita eventi globali
- `src/luna/systems/gameplay_manager.py`
  - aggrega sistemi gameplay modulari (affinity/combat/inventory/economy/...)

### Poker mini-game
- `src/luna/systems/mini_games/poker/poker_game.py`
  - handler integrato nel loop di turno
  - parser azioni poker + canale dialogo `/d`
  - strip progression e integrazione media
- `src/luna/systems/mini_games/poker/engine_v2.py`
  - motore Hold'em completo (street, pot, action legality, showdown)
- `src/luna/systems/mini_games/poker/agents.py`
  - bot AI con equity Monte Carlo + profilo rischio

## 4) UI architecture (modulare)

- `src/luna/ui/main_window/main_window.py`: coordinatore UI
- `src/luna/ui/main_window/layout_manager.py`: costruzione widget/layout
- `src/luna/ui/main_window/game_controller.py`: invio turni e branch poker
- `src/luna/ui/main_window/event_handler.py`: callback UI/action bar/setting controls
- `src/luna/ui/main_window/display_manager.py`: rendering stato/result/widget sync
- `src/luna/ui/main_window/media_manager.py`: save/load/audio/video
- `src/luna/ui/startup_dialog.py`: setup sessione/modalita

## 5) Dati e contenuti world

- `worlds/school_life_complete` e struttura modulare effettiva:
  - `_meta.yaml`, `locations.yaml`, `time.yaml`, companions yaml
  - `missions/*.yaml` (quest per Luna/Stella/Maria)
  - `events/*.yaml` (NPC/global events)

Campioni verificati:
- `worlds/school_life_complete/missions/luna_private_lesson.yaml`
- `worlds/school_life_complete/events/npc_preside_inspection.yaml`

## 6) Test suite (panoramica)

- regressione sistemi core/simulazione: `tests/test_core_systems.py`
- comportamento multi-NPC: `tests/test_multi_npc.py`
- coerenza quest/event: `tests/test_quest_coherence.py`
- altri blocchi presenti: beat integration, agenda, media builders, narrative/story, ecc.

## 7) Divergenze docs vs codice (importante)

Dalla lettura incrociata emergono alcune discrepanze tra documenti storici e stato attuale:
- `STATO_PROGETTO.md` riporta "handler mancanti" che nel codice corrente risultano presenti (`days_since_flag`, activation random/time/location-like, `on_complete.memory` in quest engine).
- in `V8_PROGRESS.md` alcune sezioni risultano sia marcate come completate sia replicate sotto "DA FARE" (traccia storica non pulita).
- naming versione non uniforme (v4/v6/v7/v8) in header/docstring, pur essendo il branch/progetto v8.

## 8) Conclusione tecnica

Il progetto e **strutturalmente modulare** e gia operativo su una pipeline completa:
- boot UI async
- engine coordinator
- orchestrator a fasi
- world sim + quest + memory + persistence
- visual/media pipeline
- mini-game poker reale con engine dedicato

L'area piu sensibile per manutenzione futura e la **coerenza documentale** (stato milestone e naming), non la mancanza di componenti core.

---

## Appendice A - Mapping file -> responsabilita/simboli

### A.1 Entrypoint e setup

| File | Responsabilita | Simboli principali |
|---|---|---|
| `src/luna/__main__.py` | CLI entrypoint, logging bootstrap | `main`, `_setup_logging`, `_Tee` |
| `src/luna/ui/app.py` | QApplication + async runner | `main`, `ApplicationRunner.run` |
| `run_game.bat` | avvio standard/no-media/debug shortcut | arg handling, `python -m luna` |
| `run_game_debug.bat` | avvio debug no-media | `--no-media --log-level DEBUG` |
| `SETUP.md` | onboarding locale | setup venv/install/run |
| `pyproject.toml` | dipendenze/build/test config | `project.dependencies`, pytest opts |

### A.2 Core

| File | Responsabilita | Simboli principali |
|---|---|---|
| `src/luna/core/engine.py` | coordinatore centrale runtime | `GameEngine`, `initialize`, `process_turn`, `_init_systems`, `_init_runtime_systems` |
| `src/luna/core/state.py` | lifecycle e mutazioni GameState | `StateManager.create_new/load/save` |
| `src/luna/core/database.py` | persistence async e schema | `DatabaseManager`, ORM models, `save_npc_minds/load_npc_minds` |
| `src/luna/core/config.py` | load env/settings | `get_settings`, `reload_settings`, `UserPrefs` |
| `src/luna/core/story_director.py` | beat progression narrativa | `StoryDirector` |
| `src/luna/core/event_context_builder.py` | contesto eventi per prompt | `EventContextBuilder` |
| `src/luna/core/debug_tracer.py` | tracing debug UI/sistemi | `tracer` |
| `src/luna/core/config1.py` | variante legacy config | modelli/config legacy |

### A.3 Modelli

| File | Responsabilita |
|---|---|
| `src/luna/core/models/__init__.py` | re-export centralizzato modelli |
| `src/luna/core/models/base.py` | base model comune |
| `src/luna/core/models/enums.py` | enum dominio (time, intent, quest status, ecc.) |
| `src/luna/core/models/state_models.py` | `GameState`, `PlayerState`, `NPCState`, outfit runtime |
| `src/luna/core/models/quest_models.py` | quest definitions/stages/actions/conditions |
| `src/luna/core/models/world_models.py` | world/global events/endgame definitions |
| `src/luna/core/models/location_models.py` | location/movement models |
| `src/luna/core/models/story_models.py` | beats/arco narrativo |
| `src/luna/core/models/output_models.py` | `TurnResult`, `NarrativeOutput`, output agents |
| `src/luna/core/models/media_models.py` | prompt/media payload |
| `src/luna/core/models/memory_models.py` | memory/message models |
| `src/luna/core/models/personality_models.py` | stato psicologico/impression |
| `src/luna/core/models/config_models.py` | `AppConfig` e risposta analisi |
| `src/luna/core/models/config_models1.py` | variante legacy |
| `src/luna/core/models/updates.py` | update payload LLM/state |
| `src/luna/core/models/companion_models.py` | definizione companion/wardrobe |

### A.4 Agent layer

| File | Responsabilita | Simboli principali |
|---|---|---|
| `src/luna/agents/intent_router.py` | intent classification | `IntentRouter.analyze` |
| `src/luna/agents/narrative.py` | prompt+LLM narrativa | `NarrativeEngine.generate` |
| `src/luna/agents/guardian.py` | validazione/applicazione update | `StateGuardian.apply` |
| `src/luna/agents/visual.py` | visual prompt composer | `VisualDirector.build` |
| `src/luna/agents/director.py` | micro-direction scene beats | `DirectorAgent` |
| `src/luna/agents/schedule_agent.py` | atmosfera/time hints | `ScheduleAgent` |
| `src/luna/agents/quest_director.py` | arricchimento quest context | `QuestDirector` |
| `src/luna/agents/initiative_agent.py` | iniziative NPC spontanee | `InitiativeAgent` |

### A.5 Orchestrator mixins

| File | Responsabilita |
|---|---|
| `src/luna/agents/orchestrator/orchestrator.py` | entrypoint pipeline turno |
| `src/luna/agents/orchestrator/phase_handlers.py` | fasi pre/world/context/narrative/finalize |
| `src/luna/agents/orchestrator/context_builder.py` | build/enrich context LLM |
| `src/luna/agents/orchestrator/intent_handlers.py` | gestione intent speciali |
| `src/luna/agents/orchestrator/state_manager.py` | salvataggio e lifecycle stato turno |
| `src/luna/agents/orchestrator/support.py` | helper media/farewell/minimal narrative |
| `src/luna/agents/orchestrator/turn_context.py` | contenitore stato turno |

### A.6 AI provider layer

| File | Responsabilita |
|---|---|
| `src/luna/ai/manager.py` | fallback chain/retry/timeout provider |
| `src/luna/ai/base.py` | interfaccia client LLM |
| `src/luna/ai/gemini.py` | client Gemini |
| `src/luna/ai/ollama_client.py` | client Ollama locale |
| `src/luna/ai/moonshot.py` | client Moonshot |
| `src/luna/ai/claude_client.py` | client Anthropic |
| `src/luna/ai/json_repair.py` | hint/riparazione parsing JSON |
| `src/luna/ai/mock.py` | provider mock |
| `src/luna/ai/manager1.py` | variante legacy manager |

### A.7 Systems (runtime)

| File | Responsabilita |
|---|---|
| `src/luna/systems/world.py` | world loader YAML (legacy+modular) |
| `src/luna/systems/quest_engine.py` | quest lifecycle e condition evaluator |
| `src/luna/systems/quest_engine_sequential.py` | policy sequenziale quest |
| `src/luna/systems/memory.py` | memory manager + semantic store |
| `src/luna/systems/state_memory.py` | save coordinator multi-sistema |
| `src/luna/systems/location.py` | location graph/stati/move validation |
| `src/luna/systems/movement.py` | parse+execute movement intent |
| `src/luna/systems/schedule_manager.py` | routines NPC per fase |
| `src/luna/systems/global_events.py` | attivazione/ciclo eventi globali |
| `src/luna/systems/gameplay_manager.py` | orchestrazione sistemi gameplay |
| `src/luna/systems/gm_agenda.py` | promise threads, arc climate, agenda logic |
| `src/luna/systems/personality.py` | analysis tratti/impression/contesto psicologico |
| `src/luna/systems/presence_tracker.py` | presenza NPC e dinamica sociale |
| `src/luna/systems/emotional_state_engine.py` | stato emotivo runtime NPC |
| `src/luna/systems/character_voice_builder.py` | voice/persona context per prompt |
| `src/luna/systems/npc_detector_v2.py` | rilevazione NPC menzionati/input parsing |
| `src/luna/systems/npc_location_router.py` | routing frasi tipo "vado da X" -> location |
| `src/luna/systems/npc_mind.py` | modello mind/goal/needs/unspoken |
| `src/luna/systems/npc_mind_ext.py` | estensioni manager NPCMind |
| `src/luna/systems/npc_state_manager.py` | query unificate stato NPC |
| `src/luna/systems/witness_system.py` | knowledge/witness propagation |
| `src/luna/systems/tension_tracker.py` | pressure/tension axes narrative |
| `src/luna/systems/phase_clock.py` | avanzamento fasi giorno/notte |
| `src/luna/systems/invitation_manager.py` | inviti companion e arrivi |
| `src/luna/systems/situational_interventions.py` | interventi contestuali pre-turn |
| `src/luna/systems/input_intent.py` | parsing intent (legacy/support) |
| `src/luna/systems/dynamic_events.py` | eventi gameplay dinamici |
| `src/luna/systems/turn_logger.py` | log strutturato per turno |
| `src/luna/systems/affinity_calculator.py` | delta/tier affinity helper |
| `src/luna/systems/companion_locator.py` | supporto localizzazione companion |
| `src/luna/systems/npc_message_system.py` | messaggistica NPC |
| `src/luna/systems/intro.py` | intro generator |
| `src/luna/systems/outfit_engine.py` | stato outfit + prompt conversion |
| `src/luna/systems/outfit_modifier.py` | modifiche outfit da input/turno |
| `src/luna/systems/outfit_renderer.py` | rendering descrizione outfit |
| `src/luna/systems/pose_extractor.py` | estrazione pose forzate |

### A.8 World simulation internals

| File | Responsabilita |
|---|---|
| `src/luna/systems/world_sim/world_simulator.py` | tick orchestrator simulazione mondo |
| `src/luna/systems/world_sim/turn_director.py` | driver decision logic |
| `src/luna/systems/world_sim/ambient_engine.py` | dettagli ambientali |
| `src/luna/systems/world_sim/cross_location_hints.py` | hint cross-location |
| `src/luna/systems/world_sim/models.py` | datamodel directive/pressure/presence |

### A.9 Gameplay package

| File | Responsabilita |
|---|---|
| `src/luna/systems/gameplay/base.py` | interfacce/base gameplay systems |
| `src/luna/systems/gameplay/affinity.py` | sistema affinita e tier |
| `src/luna/systems/gameplay/combat.py` | sistema combattimento |
| `src/luna/systems/gameplay/inventory.py` | inventario e item |
| `src/luna/systems/gameplay/economy.py` | valuta/transazioni |
| `src/luna/systems/gameplay/skills.py` | skill checks/progressione |
| `src/luna/systems/gameplay/reputation.py` | reputazione fazioni |
| `src/luna/systems/gameplay/clues.py` | clues/indizi |
| `src/luna/systems/gameplay/survival.py` | bisogni/sopravvivenza |
| `src/luna/systems/gameplay/morality.py` | moral alignment/flags |

### A.10 Multi-NPC package

| File | Responsabilita |
|---|---|
| `src/luna/systems/multi_npc/manager.py` | orchestrazione sequenze multi-NPC |
| `src/luna/systems/multi_npc/interaction_rules.py` | regole intervento NPC secondari |
| `src/luna/systems/multi_npc/types.py` | datamodel sequenze/turni |

### A.11 Poker mini-game

| File | Responsabilita |
|---|---|
| `src/luna/systems/mini_games/poker/poker_game.py` | bridge mini-game <-> engine principale |
| `src/luna/systems/mini_games/poker/engine_v2.py` | motore Hold'em core |
| `src/luna/systems/mini_games/poker/agents.py` | decision AI poker |
| `src/luna/systems/mini_games/poker/poker_renderer.py` | rendering tavolo/street/cards |
| `src/luna/systems/mini_games/poker/simple_strip_manager.py` | strip progression/dialoghi base |
| `src/luna/systems/mini_games/INTEGRATION_INSTRUCTIONS.md` | note integrazione |
| `src/luna/systems/mini_games/EXAMPLES_AND_NOTES.md` | esempi/annotazioni |

### A.12 UI package

| File | Responsabilita |
|---|---|
| `src/luna/ui/startup_dialog.py` | selezione world/save/settings all'avvio |
| `src/luna/ui/save_dialog.py` | save/load dialog support |
| `src/luna/ui/main_window/main_window.py` | coordinatore finestra principale |
| `src/luna/ui/main_window/layout_manager.py` | layout/widget wiring |
| `src/luna/ui/main_window/game_controller.py` | invio turni + poker window hook |
| `src/luna/ui/main_window/event_handler.py` | callback input/action/menu |
| `src/luna/ui/main_window/display_manager.py` | update stato e rendering widget |
| `src/luna/ui/main_window/media_manager.py` | media/save operations |
| `src/luna/ui/poker_window.py` | finestra dedicata poker |
| `src/luna/ui/action_bar.py` | quick actions |
| `src/luna/ui/quest_journal_widget.py` | journal missioni |
| `src/luna/ui/quest_choice_widget.py` | scelte quest/event |
| `src/luna/ui/narrative_compass_widget.py` | visualizzazione compass narrativa |
| `src/luna/ui/feedback_visualizer.py` | feedback UX (affinity/tier/etc.) |
| `src/luna/ui/location_widget.py` | (integrato in widgets composite) |
| `src/luna/ui/video_dialog.py` | dialog generazione video |
| `src/luna/ui/image_viewer.py` | viewer immagini |
| `src/luna/ui/image_navigator.py` | navigazione immagini storiche |
| `src/luna/ui/debug_panel.py` | pannello debug runtime |
| `src/luna/ui/widgets.py` | componenti UI riutilizzabili |

### A.13 World content e configurazioni progetto

| File/Path | Responsabilita |
|---|---|
| `worlds/school_life_complete/_meta.yaml` | meta, lore, narrative arc, gameplay systems |
| `worlds/school_life_complete/locations.yaml` | location definitions |
| `worlds/school_life_complete/time.yaml` | time slots/atmosfera |
| `worlds/school_life_complete/companion_schedules.yaml` | schedule explicit companion |
| `worlds/school_life_complete/luna.yaml` | companion Luna |
| `worlds/school_life_complete/stella.yaml` | companion Stella |
| `worlds/school_life_complete/maria.yaml` | companion Maria |
| `worlds/school_life_complete/missions/*.yaml` | quest modulari |
| `worlds/school_life_complete/events/*.yaml` | eventi modulari NPC/global |
| `worlds/school_life_complete/global_events.yaml` | eventi globali classici |
| `worlds/school_life_complete/random_events.yaml` | random events |
| `worlds/school_life_complete/npc_templates.yaml` | template NPC secondari |
| `config/comfy_workflow_image.json` | workflow immagini |
| `config/comfy_workflow_video.json` | workflow video |
| `config/google_credentials.json` | credenziali Google API |

### A.14 Test suite mapping

| File | Focus |
|---|---|
| `tests/test_core_systems.py` | world sim/turn director/model behavior deterministico |
| `tests/test_multi_npc.py` | regole intervento multi-NPC |
| `tests/test_quest_coherence.py` | coerenza trigger quest/event |
| `tests/test_narrative_coherence.py` | coerenza output narrativo |
| `tests/test_story_beats.py` | progression story beats |
| `tests/test_gm_agenda.py` | agenda/promesse/dramatic questions |
| `tests/test_media_builders.py` | prompt/media builders |
| `tests/test_beat_integration.py` | integrazione beat-orchestrator |
| `tests/test_v7_systems.py` | regressioni sistemi v7 |
| `tests/test_initiative_telemetry.py` | telemetry/initiative behavior |
| `tests/test_env.py` | environment/config setup |
| `tests/check_models.py` | sanity modelli Pydantic |

---

## Appendice B - File docs di riferimento analizzati

- `docs/LUNA_V8_SPEC.md`
- `docs/V8_PROGRESS.md`
- `STATO_PROGETTO.md`
- `SETUP.md`
- `docs/NPC_IMMERSION_IMPLEMENTATION.md`
- `docs/REPORT_MEMORIA_NPC_COMPANION.md`
- `docs/EVENTI_CORE_NPC_E_COMPANION_SOLUZIONI.md`

(Nota: i file in appendice B sono la base narrativa/progettuale; la mappa A rappresenta lo stato implementativo letto nel codice.)

