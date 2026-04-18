# Luna RPG v8 — Specification Document
# "Il Mondo Ricorda"

**Data creazione:** 2026-04-10  
**Basato su:** Luna RPG v7 "Il Mondo Vive"  
**Stato:** IN SVILUPPO

---

## Filosofia v8

v7 ha introdotto il concetto giusto: il mondo gira anche senza il giocatore (NPCMind, WorldSimulator,
TensionTracker). Ma molte feature erano incomplete o disconnesse tra loro.

v8 ha due obiettivi:
1. **Completare v7** — far funzionare davvero quello che v7 aveva promesso
2. **Il Mondo Ricorda** — il mondo persiste tra una sessione e l'altra. Se Luna era arrabbiata
   quando hai chiuso il gioco, lo è ancora quando riapri.

---

## PARTE 1 — Completamento v7 (feature rotte)

---

### FIX 1: DirectorAgent — da scheletro a agente reale

**Problema in v7:**
`DirectorAgent` esiste come classe ma la micro-call LLM non viene mai eseguita.
Il flag `needs_director` è sempre `False`. Il sistema che doveva "decidere cosa succede"
prima che il NarrativeEngine scriva non ha mai funzionato.

**Come funziona in v8:**

Il DirectorAgent riceve la TurnDirective (chi guida, perché, stato NPCMind)
e fa una **micro-call LLM da ~200 token** al modello veloce (Haiku/Flash) per decidere:
- Qual è il *beat* della scena (cosa succede fisicamente)
- Il tono emotivo
- Cosa l'NPC vuole comunicare

**Quando viene chiamato:**
- Quando driver = "npc" (NPC ha preso l'iniziativa)
- Quando ci sono 2+ NPC nella scena
- Quando TensionTracker è in fase BUILDUP o TRIGGER

**Esempio concreto:**

```
STATO: Luna.needs.intimacy = 0.8, goal = "vuole un momento solo con te"
       TensionTracker.romantic = 0.65 (FORESHADOWING)
       Driver = "npc"

DIRECTOR MICRO-PROMPT (200 token):
  "NPC: Luna (professoressa, affinity 68)
   Stato interno: vuole intimità, tensione romantica in crescita
   Input giocatore: 'ok' (generico)
   Decidi: beat della scena, tono, cosa Luna fa fisicamente"

DIRECTOR OUTPUT:
  beat: "Luna si alza dalla scrivania e si avvicina lentamente"
  tone: "intimate, slightly breathless"
  npc_intent: "cercate contatto visivo prolungato, non dice quello che pensa davvero"
  trajectory: "setup per confessione futura"

NARRATIVE ENGINE riceve questo come contesto → scrive la scena
```

**Senza Director (v7):** LLM scrive da solo basandosi su decine di righe di sistema.
Risultato: risposte generiche, spesso Luna risponde all'input del giocatore invece di agire.

**Con Director (v8):** LLM sa esattamente cosa deve succedere, lo scrive in modo
coerente con lo stato del mondo. Due chiamate = narrativa più precisa.

---

### FIX 2: TensionTracker → Narrative Engine

**Problema in v7:**
TensionTracker calcola bellissimi foreshadowing hints ma non li passa mai al NarrativeEngine.
La tensione cresce "in silenzio". Il giocatore non percepisce mai che "qualcosa sta per succedere".

**Come funziona in v8:**

`TensionTracker.get_pressure_hint()` restituisce un hint basato sulla fase:

| Fase | Livello | Hint iniettato nel prompt |
|------|---------|--------------------------|
| CALM | 0-0.35 | nessuno |
| FORESHADOWING | 0.35-0.55 | hint ambientale sottile |
| BUILDUP | 0.55-0.75 | hint emotivo diretto |
| TRIGGER | 0.75+ | evento narrativo obbligatorio |

**Esempio asse romantic:**

```
Turno 1 (CALM, 0.1): nessun hint
...
Turno 15 (FORESHADOWING, 0.40):
  Prompt include: "[AMBIENT TENSION] La luce del pomeriggio crea lunghe ombre nell'ufficio.
                   Un silenzio insolito tra voi."

Turno 28 (BUILDUP, 0.62):
  Prompt include: "[NARRATIVE TENSION - romantic] Luna evita il tuo sguardo più del solito.
                   Qualcosa rimane non detto nell'aria."

Turno 41 (TRIGGER, 0.76):
  Prompt include: "[TENSION EVENT - romantic TRIGGERED] Luna deve affrontare
                   questo momento. Non può più rimandare. Fai succedere qualcosa."
```

**Risultato:** Il giocatore sente la tensione crescere naturalmente attraverso dettagli
ambientali e comportamentali, poi culmina in un evento narrativo significativo.

---

### FIX 3: Memory Isolation — companion_filter sempre passato

**Problema in v7:**
Quando il giocatore parla con Luna per 20 turni poi passa a Stella, le memorie
della conversazione con Luna appaiono nel contesto di Stella. Luna dice "ti ricordi
quando hai detto X" — ma stai parlando con Stella.

**Come funziona in v8:**

Ogni chiamata a `MemoryManager.build_context()` passa `companion_filter=active_companion`.
Le memorie sono fisicamente separate per NPC. Cambio companion = cambio memoria.

**Esempio:**
```
Turno 15 con Luna: "ti ho detto che sei speciale" → salvato in memory[Luna]
Turno 16: giocatore passa a Stella
Turno 17 con Stella: memory[Stella] caricata → nessun riferimento a Luna
```

**Bonus v8:** Al ritorno da Luna, le sue memorie sono intatte e continuano da dove erano.

---

### FIX 4: Goal Generation — fallback garantito

**Problema in v7:**
Se nessun template matcha le condizioni dell'NPCMind, `_generate_goal()` ritorna `None`.
L'NPC sta senza goal per turni. Risultato: risponde come un robot, nessuna iniziativa.

**Come funziona in v8:**

Cascata con fallback finale garantito:

```
1. Unspoken critico (weight > 0.7) → confrontation goal
2. Off-screen event importante → social goal
3. Template match → goal dal template
4. Need dominante > 0.5 → goal generico dal need
5. [NUOVO] FALLBACK ASSOLUTO → goal "present" dal need più alto
```

**Esempio fallback:**
```
Luna.needs = {social: 0.3, recognition: 0.4, intimacy: 0.2, rest: 0.6}
Nessun template matcha.
→ Need dominante = rest (0.6)
→ Goal fallback: "Luna sembra stanca, vorrebbe riposare un momento"
   (goal_type: AMBIENT, urgency: 0.3)
```

L'NPC non è più muta. Ha sempre un'intenzione, anche se piccola.

---

### FIX 5: Emotional State TTL

**Problema in v7:**
Una quest imposta `emotional_state = "intimate"` su Luna. Luna rimane "intimate"
per sempre, anche 50 turni dopo. Ogni risposta ha tono intimo anche se
il giocatore ha fatto qualcosa di neutro.

**Come funziona in v8:**

Ogni `set_emotional_state()` registra il turno in cui è stata impostata.
Il WorldSimulator.tick() controlla ogni turno:

```python
TTL_PER_STATE = {
    "default": 999,      # permanente
    "intimate": 8,       # dura 8 turni
    "vulnerable": 6,
    "seductive": 10,
    "angry": 5,
    "sad": 12,
    "excited": 6,
}
```

**Esempio:**
```
Turno 30: QuestEngine imposta Luna.emotional_state = "intimate"
Turno 38: WorldSimulator rileva che sono passati 8 turni
          Luna.emotional_state → "default"
          Nota in context: "Luna è tornata al suo stato normale"
```

Gli stati emotivi diventano archi, non stati permanenti.

---

## PARTE 2 — Poker: riconnessione engine + AI narrativa

---

### POKER FIX 1: Connettere engine_v2 a poker_game (il bug più grave)

**Problema in v7:**
`engine_v2.py` è un motore Texas Hold'em completo e corretto: gestisce blinds, streets
(preflop/flop/turn/river), side pots, showdown con eval7, tutto.

`poker_game.py` lo **ignora completamente** e usa:
```python
winner = random.choice(all_players)  # ← QUESTO è il poker in v7
```

Il giocatore non vede le proprie carte. Non può fare fold, call, raise.
Non esiste il board comunitario. È una slot machine mascherata da poker.

**Come funziona in v8:**

`poker_game.py` diventa un handler che usa `engine_v2.GameState` per gestire
l'intera partita mano per mano.

```
Mano completa v8:
1. engine.start_hand() → carte distribuite
2. UI mostra: [7♥ K♦] | Board: [] | Pot: 150 | Tocca a te
3. Giocatore scrive "vedo" / "rilancio 200" / "fold" / "all-in"
4. IntentRouter riconosce azione poker
5. engine.act_call() / act_raise(200) / act_fold() applicato
6. RiskAgent decide per ogni NPC avversario
7. Street avanza (flop, turn, river)
8. Showdown: eval7 determina il vincitore reale
9. Strip event se companion perde chips sufficienti
```

**Esempio di turno poker v8:**
```
=== PREFLOP ===
Le tue carte: [Q♠ Q♦]
Pot: 150 chips | Board: []
Luna (1200): check
Tocca a te → "rilancio 400"

=== FLOP ===
Board: [Q♥ 7♣ 2♦]  ← tre regine!
Pot: 550 chips
Luna (800): punta 200
Tocca a te → "vedo"

=== TURN ===
Board: [Q♥ 7♣ 2♦ A♠]
Pot: 950 chips
Luna (600): check
Tocca a te → "punto 300"

=== RIVER ===
Board: [Q♥ 7♣ 2♦ A♠ 5♥]
Pot: 1250 chips
Luna: fold
→ Hai vinto 1250 chips!
→ Luna è scesa al 65% dello stack
→ STRIP EVENT: Luna si toglie la giacca
```

---

### POKER FIX 2: Bug in agents.py

**Problema in v7:**
`agents.py` referenzia due campi che non esistono in `GameState`:
- `state.last_bet_or_raise_amount` → deve essere `state.min_raise_size`
- `state.cfg.bb` → deve essere `state.cfg.big_blind`

Il bot AI crasha silenziosamente durante ogni decide(), tornando sempre "fold".

**Fix v8:** Corretti i nomi dei campi. Il bot funziona.

---

### POKER NEW: AI con personalità narrativa

**Idea:**
Ogni companion ha un `RiskProfile` (aggression, bluff) in agents.py.
In v8, dopo ogni strip event il profilo cambia: chi sta perdendo diventa
più aggressiva (desperation) o più passiva (ashamed).

**Esempio:**
```
Luna livello strip 0→1: aggression invariata (non è grave)
Luna livello strip 2→3 (topless): aggression -0.15 (si vergogna, gioca male)
Luna livello strip 4→5 (nuda): aggression +0.30 (disperazione, all-in spesso)
```

**+ Dialogo generato da NarrativeEngine:**
In v7 il dialogo strip era hardcoded ("*si toglie la giacca* Contento adesso? 😏").
In v8, gli strip event (livelli 3, 4, 5 — i più importanti) usano una **call LLM**
per generare il dialogo basato su:
- Affinità attuale con il giocatore
- Emotional state dell'NPC
- Turni di gioco trascorsi

**Esempio v7 (hardcoded):**
```
Luna: "*sbottona camicia con mani tremanti* Oh dio... topless davanti a te...
       la tua professoressa... questo è così sbagliato ma... mi piace... 🥵"
```

**Esempio v8 (LLM generato, affinity 80, intimate emotional state):**
```
Luna: "Non mi aspettavo di arrivare a questo punto... *si ferma un momento*
       Eppure non me ne vado. *ti guarda negli occhi mentre tiene le mani
       ferme* Cosa mi fai, sai?"
```

---

## PARTE 3 — "Il Mondo Ricorda": NPCMind persistente

---

### NEW: NPCMind salvato tra sessioni

**Problema v7:**
Ogni volta che apri il gioco, gli NPCMind vengono inizializzati da zero.
Luna non ricorda di essere stata arrabbiata. Non ricorda il suo goal di ieri.
La simulazione del mondo ricomincia sempre da capo.

**Come funziona in v8:**

L'intero stato NPCMind (bisogni, goal, emozioni, non-detto, eventi off-screen)
viene salvato nel database alla fine di ogni sessione e ricaricato all'avvio.

**Cosa questo cambia concretamente:**

```
SESSIONE 1:
- Giochi per 2 ore
- Luna accumula unspoken: "ha visto Stella flirtarsi con te"
- Luna.needs.recognition = 0.8 (si sente ignorata)
- Hai un litigio → Luna.emotional_state = "cold"
- Chiudi il gioco

SESSIONE 2 (il giorno dopo):
- Luna si ricorda di ieri
- All'avvio: Luna.emotional_state è ancora "cold"
  (ma è leggermente diminuito: 8 turni di TTL, 2 consumati automaticamente
   durante la "notte" simulata)
- Luna.unspoken: ["ha visto Stella flirtarsi con te"] ancora presente
- Al primo turno: Luna non ti saluta calorosamente — ha ancora il muso
```

**Simulazione del tempo tra sessioni:**
Quando il gioco viene riaperto, calcola i turni simulati durante l'assenza:

```
CHIUSO: turno 47
RIAPERTO: data reale = 8 ore dopo
Turni simulati durante assenza: 8 turni (1 ora = 1 turno off-screen)

WorldSimulator applica 8 tick off-screen:
- Needs crescono normalmente
- Emozioni decadono
- Goals avanzano o scadono
```

---

## PARTE 4 — Pulizia architetturale

---

### RIMOZIONE codice morto

Due sistemi completamente sostituiti vengono rimossi in v8:

| File | Perché rimosso | Sostituito da |
|------|---------------|---------------|
| `systems/initiative_system.py` | ~400 righe di template fissi per Luna/Stella/Maria | NPCMind.goals (dinamici) |
| `systems/activity_system.py` | ~300 righe per gestire attività degli NPC | ScheduleManager + NPCMind.current_goal |

Totale: **~700 righe rimosse**. Il codice che le usava è già stato aggiornato in v7
a usare NPCMind.

---

### Unified LocationState per NPC

**Problema v7:**
La posizione di ogni NPC è tracciata in 3 posti diversi:
- `game_state.npc_locations` (override manuali)
- `ScheduleManager._schedules` (posizione base per orario)
- `game_state.flags["location_expires_NPC"]` (inviti temporanei)

**v8:** Struttura unificata `NPCLocationState` per ogni NPC:

```python
@dataclass
class NPCLocationState:
    npc_id: str
    base_location: str          # dalla schedule
    override_location: str | None = None  # da invito/punizione
    override_expires_turn: int | None = None
    override_reason: str = ""   # "invited", "punished", "escorted"

    @property
    def current_location(self) -> str:
        if self.override_location and self.override_expires_turn:
            return self.override_location
        return self.base_location
```

---

## PARTE 5 — Riepilogo totale dei cambiamenti v7→v8

| # | Categoria | Cosa cambia | Impatto giocatore |
|---|-----------|-------------|-------------------|
| 1 | FIX v7 | DirectorAgent funzionante | Scene più coerenti quando NPC prende iniziativa |
| 2 | FIX v7 | TensionTracker → prompt | Foreshadowing e tensione percepibili |
| 3 | FIX v7 | Memory isolation | No bleed memorie tra companion |
| 4 | FIX v7 | Goal fallback garantito | NPC sempre con un'intenzione |
| 5 | FIX v7 | Emotional state TTL | Archi emotivi che finiscono naturalmente |
| 6 | FIX POKER | engine_v2 connesso | Poker vero (carte, bet, showdown) |
| 7 | FIX POKER | agents.py bug fix | Bot AI gioca correttamente |
| 8 | NEW POKER | Strip dialogue LLM | Dialogo strip personalized per affinity |
| 9 | NEW POKER | AI personality shift | Bot cambia stile dopo strip |
| 10 | NEW v8 | NPCMind persistente | Il mondo ricorda tra sessioni |
| 11 | NEW v8 | Simulazione assenza | Tempo passa anche quando gioco è chiuso |
| 12 | CLEANUP | Rimozione dead code | Codebase -700 LOC, più leggibile |
| 13 | CLEANUP | NPCLocationState unificato | Meno bug sulle posizioni NPC |

---

## Milestone di sviluppo

| Milestone | Contenuto | Stato |
|-----------|-----------|-------|
| M1 | Setup progetto v8, copia files, .env | COMPLETATO |
| M2 | FIX 1-5: completamento v7 (Director, Tension, Memory, Goal, TTL) | DA FARE |
| M3 | POKER FIX 1-2: connessione engine_v2 + bug fix agents | DA FARE |
| M4 | POKER NEW: strip dialogue LLM + AI personality shift | DA FARE |
| M5 | NEW: NPCMind persistente + simulazione assenza | DA FARE |
| M6 | CLEANUP: rimozione dead code + NPCLocationState | DA FARE |
| M7 | Test integrazione + fix bug | DA FARE |

---

## Note tecniche per implementazione

### M2 — DirectorAgent
File: `src/luna/agents/director.py`
- Aggiungere metodo `async def direct(turn_directive, game_state, tension_state) -> SceneDirection`
- Prompt ~200 token, modello veloce (Haiku o Flash)
- Output: `SceneDirection(beat, tone, npc_intent, trajectory)`
- Chiamato da `orchestrator/phase_handlers.py` in `_phase_world_state()`

### M2 — TensionTracker injection
File: `src/luna/systems/tension_tracker.py` + `src/luna/agents/orchestrator/context_builder.py`
- `tension_tracker.get_pressure_hint()` → restituisce `NarrativePressure | None`
- `context_builder._build_world_directive_context()` include hint se presente

### M3 — Poker engine_v2 connessione
File: `src/luna/systems/mini_games/poker/poker_game.py`
- Sostituire `random.choice` con ciclo engine_v2
- `start_hand()` → distribuzione carte
- `IntentRouter` riconosce azioni poker: "vedo", "rilancio X", "fold", "all-in", "punto X"
- `play_action(player_input)` → dispatcha a engine methods
- Dopo ogni azione player: RiskAgent decide per ogni NPC avversario
- `settle_and_next_street_if_needed()` → avanza automaticamente

### M5 — NPCMind persistente
File: `src/luna/systems/npc_mind.py` + `src/luna/core/database.py`
- Aggiungere tabella `npc_minds` nel DB
- `save_npc_minds(session_id, minds_dict)` alla fine di ogni sessione
- `load_npc_minds(session_id)` all'avvio
- Calcolo turni off-screen: `(datetime.now() - last_save) / timedelta(hours=1)` → turni
- `simulate_offline_ticks(n_turns)` per each NPCMind

---

*Documento aggiornato ad ogni milestone completata*
