# Luna RPG v8 — Implementazione Sistema NPC Immersivo
## Metodi 2 + 3 + 7: Comunicazione Asincrona + Reazioni a Catena + Mondo Persistente

**Data analisi:** 2026-04-15  
**Basato su:** Lettura completa codebase (zip allegato)  
**Obiettivo:** Eliminare interruzioni meccaniche, creare mondo vivo e immersivo

---

## PARTE 1: STATO ATTUALE — COSA FUNZIONA E COSA NO

Prima di toccare qualsiasi cosa, è fondamentale sapere cosa esiste davvero e come funziona.

---

### 1.1 Random Events (`random_events.yaml` → `DynamicEventManager`)

**Sistema:** `systems/dynamic_events.py` → `systems/gameplay_manager.py`  
**Wired in engine:** ✅ SÌ, via `gameplay_manager.event_manager`  
**Stato:** ✅ **FUNZIONA** (parzialmente)

**Cosa fa davvero:**
- Ogni turno: 15% di chance di check evento random
- Seleziona evento tra quelli eligibili per location + time + condizioni
- Mostra narrative text + scelte al giocatore
- Applica effetti: affinity_changes, flags, stat_changes
- Ha cooldown system (3 turni default)

**Problemi:**
- `sudden_rain` in random_events.yaml: mostra narrativa ma non blocca meccanicamente l'uscita
- Gli effetti `set_flags` funzionano, ma `affinity_change` con target `_global_` non è gestito dal parser
- La chance 15% flat per turno è troppo frequente → spam di eventi non richiesti

**Decisione: ✅ TENERE — con modifiche minori**

Gli eventi random (`lost_student`, `phone_call`, `found_item`, `overhear_conversation`, `music_from_gym`, ecc.) sono **buoni**. Sono atmosferici, opzionali, non interrompono la relazione con gli NPC. Vanno tenuti e eventualmente ridotti di frequenza.

**Modifica necessaria:** Ridurre `_should_check_random()` da 15% a 8%.

```python
# systems/dynamic_events.py — riga ~330
def _should_check_random(self) -> bool:
    return random.random() < 0.08  # Era 0.15 → troppo frequente
```

---

### 1.2 Global Events (`global_events.yaml` → `GlobalEventManager`)

**Sistema:** `systems/global_events.py`  
**Wired in engine:** ✅ SÌ, via `engine.event_manager` + `check_and_activate_events()` in phase_handlers.py  
**Stato:** ⚠️ **FUNZIONA SOLO PARZIALMENTE**

**Cosa fa davvero:**
- Il `narrative_prompt` viene iniettato nel context LLM → ✅ narrativa cambia
- L'affinity_multiplier viene applicato → ✅ funziona
- Il nome dell'evento appare nel context → ✅ funziona

**Cosa NON fa (mai implementato):**
- `on_start` / `on_end` actions → **❌ MAI PARSATI** — non esiste codice che li esegua
- `location_modifiers.blocked` → **❌ MAI APPLICATO** — il blocco location non avviene mai
- `set_emotional_state` in YAML → **❌ MAI ESEGUITO** — solo dichiarato
- `set_flag` in on_start → **❌ MAI ESEGUITO**

**Conseguenza pratica:**

```yaml
# YAML dice:
rainstorm:
  effects:
    on_start:
      - action: "set_flag"
        key: "rainstorm_active"      # ← NON viene mai settato
      - action: "set_emotional_state"
        character: "{current_companion}"
        state: "flustered"           # ← NON viene mai applicato
    location_modifiers:
      - location: "school_entrance"
        blocked: true                # ← NON blocca mai nulla
```

**In pratica:** `rainstorm` e `blackout` sono solo **narrative_prompt injection** all'LLM. 
L'LLM scrive della pioggia, ma meccanicamente non cambia nulla.

---

#### Analisi dettagliata Global Events:

| Evento | Tipo | Funziona? | Problema |
|--------|------|-----------|---------|
| `rainstorm` | random | ⚠️ Parziale | Narrative OK, effetti NO |
| `blackout` | random | ⚠️ Parziale | Narrative OK, effetti NO |
| `morning_announcements` | scheduled | ✅ OK | Semplice, funziona |
| `lunch_rush` | scheduled | ✅ OK | Atmospheric, funziona |
| `club_activities` | scheduled | ✅ OK | Funziona |
| `teacher_overtime` | random | ✅ OK | Good immersion |
| `night_school` | scheduled | ✅ OK | Atmosferico |
| `after_school_cleaning` | scheduled | ✅ OK | Ottimo per Maria |
| `detention_time` | random | ✅ OK | Funziona |
| `found_item` | random | ✅ OK | Funziona |
| `luna_private_lesson_event` | conditional | ✅ OK | Quest event, funziona |
| `stella_photoshoot_event` | conditional | ✅ OK | Quest event, funziona |
| `stella_basketball_event` | conditional | ✅ OK | Quest event, funziona |
| `maria_secrets_event` | conditional | ✅ OK | Quest event, funziona |
| `maria_home_dinner_event` | conditional | ✅ OK | Quest event, funziona |
| `message_notification` | random | ✅ OK | Base per Metodo 2! |
| `sunset_corridor` | scheduled | ✅ OK | Atmosferico |
| `alone_in_classroom` | random | ✅ OK | Romantic trigger |
| `luna_gym_substitute_event` | conditional | ✅ OK | Quest event |

**Decisione per rainstorm/blackout:**

❌ **NON eliminare** — la narrativa LLM funziona bene  
✅ **Semplificare** — rimuovere gli effetti meccanici non implementati dallo YAML  
✅ **Implementare solo** l'effetto emotional_state (semplice da fare)

---

### 1.3 Sistema Initiative Attuale (da ELIMINARE/TRASFORMARE)

**Sistema:** `systems/npc_goal_evaluator.py` + `systems/npc_initiative_turn.py`  
**UI Timer:** `ui/main_window/main_window.py` → `self._initiative_timer` ogni 15s  
**Stato:** ✅ Tecnicamente funziona, ma **concettualmente sbagliato**

**Cosa fa:**
1. Ogni turno: `NpcGoalEvaluator.evaluate()` controlla goal_templates di tutti gli NPC
2. Se goal attivo: crea `GoalHint` e aggiunge a `engine._pending_initiatives`
3. Ogni 15 secondi: timer UI esegue `_on_initiative_tick()` → `_run_initiative_turn()`
4. `NpcInitiativeTurn.run()` chiama LLM e genera narrativa
5. UI mostra: `"⚡ {npc_name} prende l'iniziativa..."` + scena

**Cosa va cambiato:**
- Il timer a 15s fisso → meccanico e prevedibile
- `"⚡ NPC prende l'iniziativa"` → rompe immersione
- `authority` mode: forza cambio location + blocca input → frustrante
- Max 1 in queue → se Luna e Stella vogliono parlare, una "scompare"

---

### 1.4 Off-Screen Simulation (già esiste, da potenziare)

**Sistema:** `systems/world_sim/world_simulator.py` → `_simulate_off_screen()`  
**Stato:** ✅ Esiste! Già funziona parzialmente.

**Cosa fa già:**
```python
# Ogni turno simula interazioni tra NPC non con il giocatore:
# - "ha avuto uno scambio teso con {npc_b}" (25% chance)  
# - "ha chiacchierato con {npc_b}" (35% chance)
# - "ha incrociato {npc_b} in corridoio" (40% chance)
```

Questi eventi finiscono in `npc_mind.off_screen_log` e vengono iniettati nel context LLM quando si parla con quell'NPC.

**Già funziona:** Luna che dice "Oggi ho parlato con Stella, sembrava strana..."  
**Manca:** La propagazione deliberata del gossip e la coscienza di Maria come witness.

---

## PARTE 2: COSA ELIMINARE DEFINITIVAMENTE

### 2.1 Eliminare: UI Text "⚡ NPC prende l'iniziativa..."

**File:** `ui/main_window/game_controller.py` — riga ~157

```python
# ELIMINARE questa riga:
w.lbl_status.setText(f"⚡ {hint.npc_display_name} prende l'iniziativa...")

# SOSTITUIRE con:
w.lbl_status.setText("...")  # Status bar non annuncia l'NPC
```

### 2.2 Eliminare: Authority Mode (Interruzione Forzata)

**File:** `systems/npc_initiative_turn.py`  
**Eliminare:** il blocco `is_authority` che forza cambio location e blocca input

```python
# QUESTO BLOCCO VA ELIMINATO:
if is_authority and dialogue_turns and engine._ui_intermediate_message_callback:
    for turn in dialogue_turns:
        await engine._ui_intermediate_message_callback(...)

# E: la logica che cambia location forzatamente
```

Il Preside non interrompe più. Invia una convocazione scritta (vedi Metodo 2).

### 2.3 Eliminare: Timer Fisso 15 Secondi

**File:** `ui/main_window/main_window.py`

```python
# ELIMINARE:
self._initiative_timer = QTimer(self)
self._initiative_timer.setInterval(15_000)
self._initiative_timer.timeout.connect(self.game_controller._on_initiative_tick)
self._initiative_timer.start()
```

Il check degli NPC avviene **dopo ogni turno del giocatore**, non su timer temporale.

### 2.4 Eliminare: `initiative_style = "authority"` come categoria

Nel `npc_goal_evaluator.py` e in tutti i YAML, il concetto di "authority" come stile che interrompe e forza. Il Preside usa il nuovo sistema di convocazioni (Metodo 2).

---

## PARTE 3: METODO 2 — COMUNICAZIONE ASINCRONA

### Concetto

Gli NPC non interrompono. Comunicano attraverso canali naturali:
- **Luna, Stella** → Messaggi digitali (telefono)
- **Maria** → Note cartacee lasciate nei luoghi
- **Preside** → Convocazione ufficiale con scadenza
- **Bidella, altri** → Commenti ambientali (non messaggi diretti)

### 3.1 Nuovo Sistema: `NpcMessageSystem`

**File da creare:** `systems/npc_message_system.py`

```python
"""NPC Message System — Metodo 2: Comunicazione Asincrona.

Sostituisce NpcInitiativeTurn per friendly + authority style.
Gli NPC comunicano attraverso messaggi/note, non interruzioni.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from luna.systems.npc_goal_evaluator import GoalHint


class MessageChannel(str, Enum):
    PHONE = "phone"          # Luna, Stella → messaggio digitale
    NOTE = "note"            # Maria → nota cartacea
    OFFICIAL = "official"    # Preside → convocazione ufficiale
    AMBIENT = "ambient"      # Commento ambientale (non diretto)


@dataclass
class NpcMessage:
    """Un messaggio da un NPC al giocatore."""
    npc_id: str
    npc_display_name: str
    channel: MessageChannel
    text: str                        # Testo del messaggio
    goal_hint: "GoalHint"            # Goal originale
    turn_sent: int
    deadline_turns: Optional[int] = None   # Solo per Preside
    deadline_consequence: str = ""         # Cosa succede se ignori
    read: bool = False
    responded: bool = False
    expires_at_turn: Optional[int] = None  # Dopo quanti turni scade
```

### 3.2 Modifiche a `NpcGoalEvaluator` — Rimozione Authority

**File:** `systems/npc_goal_evaluator.py`

```python
# PRIMA (eliminare):
AUTHORITY_GLOBAL_COOLDOWN = 35
AUTHORITY_SESSION_MAX = 3

# DOPO: Mantenere solo cooldown per non-spammare messaggi
MESSAGE_COOLDOWN_FRIENDLY = 8    # Min turni tra messaggi friendly dello stesso NPC  
MESSAGE_COOLDOWN_OFFICIAL = 20   # Min turni tra convocazioni ufficiali
MESSAGE_SESSION_MAX = 2          # Max convocazioni ufficiali per sessione
```

### 3.3 Modifiche a `phase_handlers.py` — Nuova Pipeline

**File:** `agents/orchestrator/phase_handlers.py`  
**Sezione:** Step 0.5 (NPC Goal Check)

```python
# PRIMA: aggiungeva a _pending_initiatives (queue per timer)
pending = getattr(self.engine, '_pending_initiatives', None)
if pending is not None and len(pending) == 0:
    if goal_hint.initiative_style != 'secret_keeper':
        pending.append(goal_hint)

# DOPO: genera messaggio asincrono
if goal_hint.initiative_style != 'secret_keeper':
    await self._deliver_npc_message(goal_hint, game_state)
```

**Nuovo metodo `_deliver_npc_message()`:**

```python
async def _deliver_npc_message(
    self,
    hint: "GoalHint",
    game_state: "GameState",
) -> None:
    """Genera e accoda un messaggio NPC senza interrompere."""
    from luna.systems.npc_message_system import NpcMessage, MessageChannel
    
    # Determina canale per NPC
    channel_map = {
        "luna":   MessageChannel.PHONE,
        "stella": MessageChannel.PHONE,
        "maria":  MessageChannel.NOTE,
        "preside": MessageChannel.OFFICIAL,
    }
    channel = channel_map.get(hint.npc_id, MessageChannel.AMBIENT)
    
    # Genera testo messaggio via LLM (breve, non invasivo)
    text = await self._generate_message_text(hint, channel, game_state)
    
    # Crea messaggio
    message = NpcMessage(
        npc_id=hint.npc_id,
        npc_display_name=hint.npc_display_name,
        channel=channel,
        text=text,
        goal_hint=hint,
        turn_sent=game_state.turn_count,
        deadline_turns=15 if channel == MessageChannel.OFFICIAL else None,
        deadline_consequence=(
            "Il Preside aumenta la severità della convocazione"
            if channel == MessageChannel.OFFICIAL else ""
        ),
        expires_at_turn=game_state.turn_count + 20,
    )
    
    # Accoda (NON interrompe il turno corrente)
    if not hasattr(game_state, '_pending_messages'):
        game_state._pending_messages = []
    game_state._pending_messages.append(message)
```

### 3.4 Come i Messaggi Vengono Mostrati in UI

**NON interrompono.** Appaiono in modo discreto alla **fine del turno normale**, DOPO la risposta narrativa.

**File:** `ui/main_window/display_manager.py`

```python
def display_result(self, result: TurnResult) -> None:
    """Display turn result, poi messaggi NPC pendenti."""
    
    # 1. Display normale (già esiste)
    self._display_narrative(result)
    
    # 2. NUOVO: Mostra messaggi pendenti in coda (discreta)
    if result.pending_messages:
        for msg in result.pending_messages:
            self._display_npc_message(msg)

def _display_npc_message(self, msg: "NpcMessage") -> None:
    """Mostra messaggio NPC in modo non invasivo."""
    
    if msg.channel == MessageChannel.PHONE:
        # Appare come notifica telefono nel testo narrativo
        self._append_to_narrative(
            f"\n📱 *{msg.npc_display_name}:* \"{msg.text}\"\n"
        )
    
    elif msg.channel == MessageChannel.NOTE:
        # Appare come nota trovata
        self._append_to_narrative(
            f"\n📝 *Trovi un biglietto piegato:*\n"
            f"\"_{msg.text}_\"\n"
            f"— {msg.npc_display_name}\n"
        )
    
    elif msg.channel == MessageChannel.OFFICIAL:
        # Convocazione formale con deadline
        turns_left = msg.deadline_turns
        self._append_to_narrative(
            f"\n📄 *CONVOCAZIONE UFFICIALE*\n"
            f"Il Preside La attende nel suo ufficio.\n"
            f"_Scadenza: entro {turns_left} turni._\n"
        )
        # Imposta flag deadline tracking
        # game_state.flags["preside_deadline_turn"] = current_turn + deadline_turns
```

### 3.5 Modifiche YAML — Preside e NPCs Secondari

**File:** `worlds/school_life_complete/npc_templates.yaml`

```yaml
# PRIMA:
preside:
  goal_templates:
    - initiative_style: "authority"  # ← ELIMINARE

# DOPO:
preside:
  goal_templates:
    - id: "disciplinary_hearing"
      goal: "Convocare studente per questioni disciplinari"
      initiative_style: "official_summons"  # ← NUOVO STILE
      message_template: |
        La convoco nel mio ufficio per una questione disciplinare urgente.
        Non ammetto ritardi.
      deadline_turns: 15
      deadline_consequence_flag: "preside_ignored_summons"
      
    - id: "positive_recognition"
      goal: "Riconoscere studente meritevole"  
      initiative_style: "official_summons"
      message_template: |
        Desidero parlarLe di un'opportunità. Mi trovi domani.
      deadline_turns: 20
```

### 3.6 Conseguenze del Ignorare i Messaggi

**File:** `agents/orchestrator/phase_handlers.py` — Step 0.3 (check scadenze)

```python
async def _check_message_deadlines(self, game_state: "GameState") -> None:
    """Controlla scadenze messaggi e applica conseguenze."""
    
    messages = getattr(game_state, '_pending_messages', [])
    current_turn = game_state.turn_count
    
    for msg in messages:
        if msg.responded:
            continue
        if msg.expires_at_turn and current_turn > msg.expires_at_turn:
            # Messaggio scaduto: applica conseguenza
            if msg.deadline_consequence and msg.channel == MessageChannel.OFFICIAL:
                # Preside: aumenta severità
                current_severity = game_state.flags.get("preside_severity", 0)
                game_state.flags["preside_severity"] = current_severity + 1
                
                if current_severity >= 2:
                    # Terzo ignore: scena forzata (MA narrativa, non interrupt)
                    # Il giorno dopo il preside ti ferma nel corridoio
                    game_state.flags["preside_confrontation_pending"] = True
            
            msg.responded = True  # Marca come gestita (con conseguenza)
```

---

## PARTE 4: METODO 3 — REAZIONI A CATENA

### Concetto

Gli NPC vedono, sentono, e reagiscono a quello che succede. Maria è il fulcro: è ovunque, vede tutto, e il suo comportamento dipende dall'affinity con il giocatore.

### 4.1 Sistema Witnessing — Maria Come Osservatrice

**File da creare:** `systems/witness_system.py`

```python
"""Witness System — Metodo 3: Reazioni a Catena.

Traccia chi vede cosa e propaga le informazioni tra NPC.
Maria è il witness primario: vede tutto perché pulisce ovunque.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from luna.core.models import GameState


@dataclass
class WitnessEvent:
    """Un evento osservato da un NPC."""
    event_type: str          # "intimate_with_luna", "argument", "kind_act"
    subject_npc: str         # Chi è coinvolto (es. "luna")
    witness_npc: str         # Chi ha visto (es. "maria")
    location: str
    turn: int
    certainty: float         # 1.0 = visto direttamente, 0.5 = sentito
    told_to: List[str] = field(default_factory=list)  # A chi l'ha detto
    covered: bool = False    # Maria ha coperto invece di rivelare


class WitnessSystem:
    """Gestisce witnessing e propagazione gossip."""
    
    # Maria è nella stessa location del giocatore con questa probabilità
    MARIA_PRESENCE_CHANCE = {
        "school_corridor":  0.6,   # Alta: pulisce sempre
        "school_classroom": 0.3,   # Media: entra a pulire
        "school_bathroom":  0.5,   # Alta: va spesso
        "teacher_office":   0.4,   # Media: pulisce uffici
        "school_library":   0.3,
        "school_gym":       0.2,
        "principal_office": 0.1,   # Bassa: il preside non vuole
    }
    
    def __init__(self) -> None:
        self.witness_log: List[WitnessEvent] = []
    
    def check_maria_witnesses(
        self,
        event_type: str,
        subject_npc: str,
        location: str,
        game_state: "GameState",
    ) -> Optional[WitnessEvent]:
        """
        Controlla se Maria ha visto qualcosa.
        Chiamato dopo scene intimate/importanti con un NPC.
        """
        import random
        
        # Maria non può vedere se è la active companion
        if game_state.active_companion == "maria":
            return None
        
        # Check probabilità presenza
        chance = self.MARIA_PRESENCE_CHANCE.get(location, 0.2)
        if random.random() > chance:
            return None
        
        # Maria ha visto!
        event = WitnessEvent(
            event_type=event_type,
            subject_npc=subject_npc,
            witness_npc="maria",
            location=location,
            turn=game_state.turn_count,
            certainty=0.8,  # Vista diretta
        )
        self.witness_log.append(event)
        return event
    
    def maria_decides_action(
        self,
        event: WitnessEvent,
        game_state: "GameState",
    ) -> str:
        """
        Decide cosa fa Maria con quello che ha visto.
        Dipende dalla sua affinity con il giocatore.
        
        Returns: "cover", "gossip_npc", "gossip_preside", "keep_secret"
        """
        maria_affinity = game_state.affinity.get("maria", 0)
        
        if maria_affinity >= 60:
            # Alta affinity: copre sempre
            event.covered = True
            return "cover"
        
        elif maria_affinity >= 30:
            # Media affinity: tiene per sé ma potrebbe dirlo a Stella (gossip)
            return "keep_secret"
        
        else:
            # Bassa affinity: gossip con altri NPC
            # Chance 30% che arrivi al preside
            import random
            if random.random() < 0.3:
                return "gossip_preside"
            return "gossip_npc"
    
    def propagate_gossip(
        self,
        event: WitnessEvent,
        action: str,
        game_state: "GameState",
    ) -> None:
        """Propaga l'informazione ad altri NPC."""
        
        if action == "cover":
            # Maria non dice niente, ma ricorda
            self._add_to_npc_knowledge("maria", event, game_state)
            return
        
        elif action == "gossip_npc":
            # Stella sente voci (certezza ridotta)
            stella_event = WitnessEvent(
                event_type=event.event_type,
                subject_npc=event.subject_npc,
                witness_npc="stella",
                location="school_corridor",
                turn=game_state.turn_count + 1,
                certainty=0.4,  # È gossip, incerto
            )
            self.witness_log.append(stella_event)
            self._add_to_npc_knowledge("stella", stella_event, game_state)
            event.told_to.append("stella")
        
        elif action == "gossip_preside":
            # Preside aumenta suspicion
            current = game_state.flags.get("preside_suspicion", 0)
            game_state.flags["preside_suspicion"] = current + 20
            event.told_to.append("preside")
            
            # Attiva goal convocazione se suspicion alta
            if game_state.flags["preside_suspicion"] >= 40:
                game_state.flags["preside_wants_meeting"] = True
    
    def _add_to_npc_knowledge(
        self,
        npc_id: str,
        event: WitnessEvent,
        game_state: "GameState",
    ) -> None:
        """Aggiunge l'evento alla conoscenza dell'NPC via off_screen_log."""
        # Inietta nel mind dell'NPC come off_screen event
        knowledge_key = f"_knowledge_{npc_id}"
        known = game_state.flags.get(knowledge_key, [])
        known.append({
            "event_type": event.event_type,
            "subject": event.subject_npc,
            "turn": event.turn,
            "certainty": event.certainty,
            "covered": event.covered,
        })
        game_state.flags[knowledge_key] = known
```

### 4.2 Dove Chiamare il WitnessSystem

**File:** `agents/orchestrator/phase_handlers.py` — post-turno

```python
# Dopo che una scena intima/importante si conclude:
async def _check_witness_events(self, ctx: "TurnContext") -> None:
    """Controlla se qualcuno ha assistito alla scena."""
    
    game_state = ctx.game_state
    witness_system = getattr(self.engine, 'witness_system', None)
    if not witness_system:
        return
    
    # Determina tipo di evento dalla scena (dal result narrative)
    # Semplice keyword detection sul testo generato:
    narrative_lower = ctx.result_text.lower() if ctx.result_text else ""
    
    event_type = None
    if any(w in narrative_lower for w in ["vicini", "mano", "abbracci", "baci", "intimi"]):
        event_type = "intimate_moment"
    elif any(w in narrative_lower for w in ["argoment", "lite", "arrabbiat", "urla"]):
        event_type = "argument"
    elif any(w in narrative_lower for w in ["sola", "piange", "lacrime", "vulnerabile"]):
        event_type = "emotional_moment"
    
    if event_type:
        # Check se Maria ha visto
        witness_event = witness_system.check_maria_witnesses(
            event_type=event_type,
            subject_npc=game_state.active_companion,
            location=game_state.current_location,
            game_state=game_state,
        )
        
        if witness_event:
            action = witness_system.maria_decides_action(witness_event, game_state)
            witness_system.propagate_gossip(witness_event, action, game_state)
            
            # Se Maria ha coperto: lei lo sa e lo ricorda
            # La prossima volta che vai da lei, potrebbe dirlo
            if action == "cover":
                maria_mind = self.engine.mind_manager.get("maria") if hasattr(self.engine, 'mind_manager') else None
                if maria_mind:
                    maria_mind.add_off_screen(
                        f"ha visto qualcosa tra te e {game_state.active_companion}, ha deciso di non dire niente",
                        game_state.turn_count,
                        importance=0.8
                    )
```

### 4.3 Come Reagisce Stella al Gossip

**File:** `agents/orchestrator/context_builder.py`

```python
# Nel build_context, se Stella ha knowledge di un evento:
def _add_stella_jealousy_context(self, game_state: "GameState") -> str:
    """Aggiunge contesto gelosia Stella se ha sentito gossip su Luna."""
    
    stella_knowledge = game_state.flags.get("_knowledge_stella", [])
    if not stella_knowledge:
        return ""
    
    # Trova eventi recenti (ultimi 10 turni)
    current_turn = game_state.turn_count
    recent = [k for k in stella_knowledge 
              if current_turn - k["turn"] <= 10 
              and k["subject"] == "luna"
              and not k.get("acknowledged")]
    
    if not recent:
        return ""
    
    certainty = recent[-1]["certainty"]
    
    if certainty >= 0.7:
        return "Stella SA di Luna e il giocatore (ha visto o sentito con certezza). È gelosa ma cerca di nasconderlo."
    else:
        return "Stella ha sentito voci su Luna e il giocatore. Non è sicura. Potrebbe fare domande indirette."
```

### 4.4 Come Reagisce il Preside al Gossip

**File:** `systems/npc_goal_evaluator.py`

```python
# Nel _check_preside_goals():
def _check_preside_goals(self, game_state: "GameState") -> Optional[GoalHint]:
    """Il Preside reagisce alla suspicion accumulata."""
    
    suspicion = game_state.flags.get("preside_suspicion", 0)
    wants_meeting = game_state.flags.get("preside_wants_meeting", False)
    
    if wants_meeting and suspicion >= 40:
        return GoalHint(
            npc_id="preside",
            npc_display_name="Il Preside",
            goal_text="Ha ricevuto segnalazioni su comportamenti inappropriati",
            urgency=min(suspicion / 100, 0.9),
            goal_type="confrontation",
            goal_id="disciplinary_meeting",
            initiative_style="official_summons",  # NON authority
            location_display="Ufficio del Preside",
            time_display="Qualsiasi ora",
        )
    
    return None
```

---

## PARTE 5: METODO 7 — MONDO PERSISTENTE

### Concetto

Gli NPC vivono anche quando non li guardi. I loro bisogni crescono, le loro emozioni cambiano. Quando vai da loro, la scena riflette quello che hanno vissuto off-screen. Non ci sono interruzioni: il giocatore scopre lo stato degli NPC visitandoli.

### 5.1 Il Sistema Già Esiste — Va Potenziato

Il `WorldSimulator._simulate_off_screen()` già simula interazioni tra NPC off-screen. Il `NPCMind` già traccia needs che crescono ogni turno.

**Quello che manca:**
- I needs off-screen non si traducono in comportamento visibile quando il giocatore arriva
- Non c'è "stato accumulato" visibile
- Luna che era sola per 10 turni si comporta uguale a Luna che era sola per 2 turni

### 5.2 Modifiche a `WorldSimulator` — Enhanced Off-Screen

**File:** `systems/world_sim/world_simulator.py`

```python
def _simulate_off_screen(self, game_state: Any, turn: int) -> None:
    """Enhanced: simula vita off-screen più ricca."""
    active = game_state.active_companion
    player_loc = game_state.current_location
    
    for npc_id, mind in self.mind_manager.minds.items():
        if npc_id == active:
            continue
        
        npc_loc = game_state.npc_locations.get(npc_id, "unknown")
        
        # NUOVO: Simula stato emotivo off-screen basato su needs
        self._update_npc_mood_from_needs(npc_id, mind, game_state, turn)
        
        # NUOVO: Simula attività specifica per NPC
        self._simulate_npc_activity(npc_id, mind, npc_loc, game_state, turn)
        
        # Già esistente: interazioni tra NPC
        # ...

def _update_npc_mood_from_needs(
    self,
    npc_id: str,
    mind: "NPCMind",
    game_state: Any,
    turn: int,
) -> None:
    """Aggiorna umore NPC basato su needs accumulati."""
    
    social_need = mind.needs.get("social", 0.0)
    rest_need = mind.needs.get("rest", 0.0)
    intimacy_need = mind.needs.get("intimacy", 0.0)
    
    # Determina mood prevalente
    if social_need > 0.75 and npc_id in ["luna", "stella"]:
        # Molto sola → lonely
        if game_state.npc_states.get(npc_id, {}).get("emotional_state") == "default":
            # Solo se non c'è già uno stato forzato
            npc_state = game_state.npc_states.get(npc_id)
            if npc_state:
                game_state.npc_states[npc_id] = npc_state.model_copy(
                    update={"emotional_state": "lonely", "emotional_state_set_turn": turn}
                )
    
    elif rest_need > 0.8:
        # Stanca → tired
        npc_state = game_state.npc_states.get(npc_id)
        if npc_state and npc_state.emotional_state == "default":
            game_state.npc_states[npc_id] = npc_state.model_copy(
                update={"emotional_state": "tired", "emotional_state_set_turn": turn}
            )

def _simulate_npc_activity(
    self,
    npc_id: str,
    mind: "NPCMind",
    location: str,
    game_state: Any,
    turn: int,
) -> None:
    """Simula attività specifica dell'NPC off-screen."""
    
    # Luna: corregge compiti la sera, prepara lezioni la mattina
    if npc_id == "luna":
        time = game_state.time_of_day
        if str(time) in ["Evening", "Night"]:
            if not mind.off_screen_log or mind.off_screen_log[-1].description != "sta correggendo compiti":
                mind.add_off_screen(
                    "stava correggendo compiti da sola nel suo ufficio",
                    turn, importance=0.3
                )
    
    # Maria: pulisce zone specifiche per orario
    elif npc_id == "maria":
        time = game_state.time_of_day
        area_map = {
            "Morning": "l'atrio e i corridoi del piano terra",
            "Afternoon": "le aule dopo le lezioni",
            "Evening": "gli uffici dei professori",
            "Night": "i bagni e le scale",
        }
        area = area_map.get(str(time), "la scuola")
        mind.add_off_screen(
            f"stava pulendo {area}",
            turn, importance=0.2
        )
    
    # Stella: studia/socializza a seconda dell'orario
    elif npc_id == "stella":
        import random
        activities = ["studiava in biblioteca", "era con le amiche al bar", 
                      "guardava il telefono", "pensava a qualcosa"]
        activity = random.choice(activities)
        if turn % 5 == 0:  # Solo ogni 5 turni per non spammare
            mind.add_off_screen(activity, turn, importance=0.2)
```

### 5.3 Come lo Stato Accumulato Cambia la Scena

Quando il giocatore va da un NPC, il context LLM deve ricevere informazioni su **quanto tempo l'NPC ha passato da solo** e **in che stato emotivo**.

**File:** `agents/orchestrator/context_builder.py`

```python
def _build_npc_presence_context(
    self,
    npc_id: str,
    game_state: "GameState",
) -> str:
    """
    Costruisce contesto sulla situazione attuale dell'NPC.
    Chiesto dall'LLM per calibrare la scena.
    """
    
    npc_state = game_state.npc_states.get(npc_id)
    if not npc_state:
        return ""
    
    mind = self.engine.mind_manager.get(npc_id) if hasattr(self.engine, 'mind_manager') else None
    if not mind:
        return ""
    
    parts = []
    
    # Quanto tempo sola
    turns_alone = mind.turns_since_last_initiative
    if turns_alone > 10:
        parts.append(f"È sola da {turns_alone} turni. Si nota.")
    elif turns_alone > 5:
        parts.append(f"È sola da un po' ({turns_alone} turni).")
    
    # Stato emotivo accumulato
    emotional_state = npc_state.emotional_state
    if emotional_state != "default":
        state_descriptions = {
            "lonely":     "Si sente sola e lo si vede dalla postura, dagli occhi.",
            "tired":      "È stanca. Si muove lentamente, le palpebre pesanti.",
            "anxious":    "È in ansia. Agita le mani, guarda spesso verso la porta.",
            "happy":      "È di buonumore. Si nota dalla leggerezza nei movimenti.",
            "vulnerable": "Si sente vulnerabile in questo momento. Fragile.",
            "conflicted": "Ha qualcosa in testa. Si vede che sta pensando a qualcosa.",
        }
        desc = state_descriptions.get(emotional_state, f"È in stato '{emotional_state}'.")
        parts.append(desc)
    
    # Needs elevati (senza mostrare numeri)
    social_need = mind.needs.get("social", 0)
    if social_need > 0.7:
        parts.append("Ha bisogno di compagnia. Non lo dirà esplicitamente, ma si vede.")
    
    # Off-screen recenti rilevanti
    recent_events = [e for e in (mind.off_screen_log or [])
                     if not e.told_to_player and e.importance > 0.5]
    if recent_events:
        latest = recent_events[-1]
        parts.append(f"Poco fa: {latest.description}")
    
    return " ".join(parts) if parts else ""
```

### 5.4 Rimozione del Timer — Check Post-Turno

**File:** `ui/main_window/game_controller.py`

```python
# ELIMINARE il metodo _on_initiative_tick() e tutto il QTimer

# AGGIUNGERE: dopo ogni turno processato, check messaggi pendenti
async def _process_turn(self, user_input: str) -> None:
    """Processa un turno completo."""
    
    w = self.window
    
    # ... processing normale ...
    
    result = await w.engine.process_turn(user_input)
    
    # NUOVO: check NPC messages generate dal turno
    pending = getattr(w.engine.state, '_pending_messages', [])
    unread = [m for m in pending if not m.read]
    
    if unread:
        result.pending_messages = unread[:2]  # Max 2 messaggi per turno
        for m in unread[:2]:
            m.read = True
    
    # Display result (include messaggi)
    w.display_manager.display_result(result)
```

### 5.5 Luna: Comportamento Quando il Giocatore Arriva

Il punto centrale del Metodo 7 è che Luna risponde al suo **stato accumulato**, non a un "trigger":

```
[Giocatore va in teacher_office, sera, turno 45]

[Sistema in context_builder]:
→ Luna.turns_alone = 12 turni
→ Luna.emotional_state = "lonely" (accumulato)
→ Luna.social_need = 0.78
→ Luna.off_screen: "stava correggendo compiti"

[Context LLM riceve]:
"Luna è sola da 12 turni. Si sente sola, lo si vede.
 Ha bisogno di compagnia. Stava correggendo compiti.
 Quando il giocatore entra, reagisce al suo stato reale."

[LLM genera - NESSUN TRIGGER, è organico]:
Luna: *alza la testa dai fogli* "Oh..."
      *pausa, come se non si aspettasse qualcuno*
      "Sei tu. Stavo... correggendo questi compiti.
       Da ore. *sospiro* Siediti, se vuoi."
```

Versus se il giocatore arrivasse subito (turno 35, Luna.turns_alone = 2):

```
[Context LLM]:
"Luna è appena arrivata in ufficio. Nessuno stato particolare."

[LLM genera]:
Luna: "Ah, Enrico. Ho appena finito la riunione.
       Volevi qualcosa?"
```

**Stessa location, stessa Luna. Comportamento completamente diverso.** Senza un timer. Senza un trigger meccanico. Solo il tempo che passa.

---

## PARTE 6: MODIFICHE YAML NECESSARIE

### 6.1 `npc_templates.yaml` — Eliminare Authority Style

```yaml
# PRIMA — da cambiare:
preside:
  goal_templates:
    - id: "disciplinary_hearing"
      initiative_style: "authority"    # ← ELIMINARE

# DOPO:
preside:
  goal_templates:
    - id: "disciplinary_hearing"
      initiative_style: "official_summons"  # ← NUOVO
      message_channel: "official"
      deadline_turns: 15
```

### 6.2 `luna.yaml` — Goal Templates Revisionati

```yaml
# PRIMA:
goal_templates:
  - id: "lonely_evening"
    initiative_style: "friendly"

# DOPO: stessa logica, nuovo stile
goal_templates:
  - id: "lonely_evening"
    initiative_style: "phone_message"    # ← Manda messaggio telefono
    message_template: "Sei ancora a scuola? 🥺"
    # Oppure: se il giocatore è già lì, la scena parte organicamente
    organic_if_present: true  # ← Se già in ufficio, non manda msg
```

### 6.3 `global_events.yaml` — Semplificazione Rainstorm/Blackout

```yaml
# PRIMA (effetti non implementati, confusi):
rainstorm:
  effects:
    duration: 3
    location_modifiers:
      - location: "school_entrance"
        blocked: true              # ← NON funziona, rimuovere
    on_start:
      - action: "set_flag"        # ← NON funziona, rimuovere
        key: "rainstorm_active"
      - action: "set_emotional_state"  # ← NON funziona, rimuovere
        character: "{current_companion}"
        state: "flustered"

# DOPO (semplice, implementabile):
rainstorm:
  effects:
    duration: 3
    emotional_state_companion: "flustered"  # ← Implementato in GlobalEventManager
    visual_tags: ["rain", "wet", "dark_sky", "puddles"]
    atmosphere_change: "dramatic, trapped, intimate"
    
  narrative_prompt: "..."  # ← Già funziona
```

---

## PARTE 7: RIEPILOGO MODIFICHE FILE PER FILE

### File da modificare:

| File | Modifica | Priorità |
|------|---------|---------|
| `ui/main_window/game_controller.py` | Eliminare `_on_initiative_tick()` e QTimer | 🔴 ALTA |
| `ui/main_window/main_window.py` | Eliminare `_initiative_timer` setup | 🔴 ALTA |
| `ui/main_window/display_manager.py` | Aggiungere `_display_npc_message()` | 🔴 ALTA |
| `agents/orchestrator/phase_handlers.py` | Sostituire queue initiative con message delivery | 🔴 ALTA |
| `systems/npc_initiative_turn.py` | Refactoring → solo friendly note generator | 🟡 MEDIA |
| `systems/npc_goal_evaluator.py` | Rimuovere authority constants, aggiungere message logic | 🟡 MEDIA |
| `systems/world_sim/world_simulator.py` | Potenziare `_simulate_off_screen()` | 🟡 MEDIA |
| `systems/global_events.py` | Implementare `emotional_state_companion` effect | 🟡 MEDIA |
| `agents/orchestrator/context_builder.py` | Aggiungere `_build_npc_presence_context()` | 🟡 MEDIA |
| `systems/dynamic_events.py` | Ridurre chance random da 0.15 a 0.08 | 🟢 BASSA |
| `worlds/school_life_complete/npc_templates.yaml` | Cambiare authority in official_summons | 🔴 ALTA |
| `worlds/school_life_complete/luna.yaml` | Aggiungere `organic_if_present: true` ai goals | 🟢 BASSA |
| `worlds/school_life_complete/global_events.yaml` | Semplificare effetti rainstorm/blackout | 🟢 BASSA |

### File da creare:

| File | Contenuto | Priorità |
|------|----------|---------|
| `systems/npc_message_system.py` | NpcMessage, MessageChannel, NpcMessageSystem | 🔴 ALTA |
| `systems/witness_system.py` | WitnessEvent, WitnessSystem | 🟡 MEDIA |

---

## PARTE 8: ORDINE DI IMPLEMENTAZIONE RACCOMANDATO

### Sprint 1 — Rimuovere il Male (1-2 giorni)

```
1. Eliminare QTimer 15s (main_window.py)
2. Eliminare _on_initiative_tick() (game_controller.py)
3. Eliminare "⚡ NPC prende l'iniziativa..." (game_controller.py)
4. Eliminare authority interrupt mode (npc_initiative_turn.py)
5. Ridurre random events chance 0.15 → 0.08 (dynamic_events.py)
6. Cambiare authority → official_summons nei YAML
```

Dopo Sprint 1: il gioco non ha più interruzioni meccaniche.  
Gli NPC non prendono più iniziativa autonoma (per ora).

### Sprint 2 — Metodo 7 (2-3 giorni)

```
7. Potenziare _simulate_off_screen() (world_simulator.py)
8. Aggiungere _update_npc_mood_from_needs() (world_simulator.py)  
9. Aggiungere _build_npc_presence_context() (context_builder.py)
10. Testare: Luna sola 10 turni vs 2 turni → comportamento diverso
```

Dopo Sprint 2: il mondo è vivo. Visitare Luna dopo che è sola a lungo è diverso da visitarla subito.

### Sprint 3 — Metodo 2 (2-3 giorni)

```
11. Creare npc_message_system.py
12. Modificare phase_handlers.py → _deliver_npc_message()
13. Aggiungere _display_npc_message() (display_manager.py)
14. Aggiungere _check_message_deadlines() (phase_handlers.py)
15. Testare: Luna manda messaggio telefono, Preside invia convocazione
```

Dopo Sprint 3: comunicazione asincrona attiva. Messaggi non interrompono.

### Sprint 4 — Metodo 3 (3-4 giorni)

```
16. Creare witness_system.py
17. Aggiungere _check_witness_events() in phase_handlers.py
18. Aggiungere _add_stella_jealousy_context() in context_builder.py
19. Aggiungere _check_preside_goals() in npc_goal_evaluator.py
20. Testare: scena con Luna → Maria vede → Stella sente voci
```

Dopo Sprint 4: mondo interconnesso. Le azioni hanno conseguenze sociali.

### Sprint 5 — Pulizia e YAML (1-2 giorni)

```
21. Semplificare global_events.yaml (rainstorm/blackout)
22. Implementare emotional_state_companion in GlobalEventManager
23. Aggiornare goal_templates YAML tutti i companion
24. Test end-to-end completo
```

---

## PARTE 9: COSA NON TOCCARE

Questi sistemi funzionano bene e non vanno modificati:

- ✅ `NPCMind` (needs, goals, emotions, off_screen_log) — già buono
- ✅ `MemoryManager` — già buono  
- ✅ `ScheduleManager` — già buono
- ✅ `EmotionalStateTTL` — già funziona
- ✅ `DynamicEventManager` random events (lost_student, phone_call, ecc.)
- ✅ `GlobalEventManager` atmospheric events (tramonto, scuola di notte, ecc.)
- ✅ Quest events condizionali (luna_private_lesson, stella_photoshoot, ecc.)
- ✅ `secret_keeper` style per Maria — già corretto, non cambia
- ✅ `AffinityCalculator`
- ✅ `TensionTracker`
- ✅ `StoryDirector`

---

## SINTESI FINALE

### Prima (sistema attuale):

```
Turno 45 →
Timer 15s scatta →
UI: "⚡ Luna prende l'iniziativa..." →
Scena forzata →
INTERRUZIONE
```

### Dopo (nuovo sistema):

```
Turno 45 →
Luna è in ufficio da 12 turni
Luna.emotional_state = "lonely"
Luna.social_need = 0.78
→ Luna manda messaggio: "Sei ancora a scuola? 🥺"
   (appare discretamente dopo la risposta narrativa)
   
   OPPURE (se il giocatore è già lì):
→ Il context LLM riceve stato accumulato
→ Luna risponde in modo organico alla sua situazione reale
→ NESSUNA INTERRUZIONE, solo vita che accade
```

### La Filosofia

**Prima:** Gli NPC aspettano il timer per "attivarsi".  
**Dopo:** Gli NPC esistono sempre. Il giocatore scopre il loro stato visitandoli.

**Prima:** Il Preside ti teletrasporta nel suo ufficio.  
**Dopo:** Il Preside ti manda una nota. Tu scegli quando andare. Le conseguenze arrivano se aspetti troppo.

**Prima:** Maria è passiva (secret_keeper, pull-only).  
**Dopo:** Maria è attiva: vede, decide, copre o rivela. La tua relazione con lei ha un peso reale.

---

*Fine documento — Pronti per implementazione Sprint 1*
