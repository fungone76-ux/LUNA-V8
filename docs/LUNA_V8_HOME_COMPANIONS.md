# Luna RPG v8 — Sistema Companion a Casa (Home Visit)
# Documento per Claude Code CLI

**Data:** 2026-04-26  
**Feature:** Invitare una o più companion a casa del giocatore con interazione multi-personaggio estesa  
**Priorità:** Alta  

---

## Panoramica del problema

Il `InvitationManager` esistente gestisce inviti con un TTL di 6 turni (`ttl_turns=6`).  
Questo va bene per "vieni al bar stasera" ma non per "vieni a casa mia" — dove la companion  
dovrebbe restare finché il giocatore non la congeda, ignorando la sua schedule normale.

Quando ci sono più companion a casa, il sistema attuale non le fa interagire tra loro:  
il `MultiNPCManager` è pensato per "interruzioni occasionali", non per scene di gruppo estese  
dove Luna e Stella possono litigare tra loro e il giocatore può rivolgersi all'una o all'altra.

---

## Architettura della soluzione (3 componenti)

```
[1] HomeGuestManager       → chi è a casa, stato persistente, gestione entrata/uscita
[2] HomeSceneContext        → inietta nel prompt LLM la consapevolezza delle altre companion
[3] HomeSceneOrchestrator   → gestisce il turno quando ci sono 2+ companion a casa
```

---

## COMPONENTE 1 — HomeGuestManager

### 1.1 — Nuovo file: `src/luna/systems/home_guest_manager.py`

```python
"""HomeGuestManager — gestisce le companion ospitate a casa del giocatore.

Differenza dal InvitationManager:
- Gli ospiti restano a player_home finché non vengono congedati esplicitamente.
- Non esiste TTL. Il cambio di fase NON le riporta alla loro schedule.
- Persistono tra sessioni (salvati in GameState.flags).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

HOME_LOCATION = "player_home"

# Pattern per invitare a casa (integrare con InvitationManager esistente)
HOME_INVITE_PATTERNS = [
    r"\bvieni a casa\b",
    r"\bvieni da me\b",
    r"\bvieni a casa mia\b",
    r"\bpassа a casa\b",
    r"\bti aspetto a casa\b",
    r"\bfermati da me\b",
    r"\brimani da me\b",
    r"\bstai da me\b",
    r"\bdormi da me\b",
    r"\bvieni a dormire\b",
]

# Pattern per congedare (player parla con una companion specifica)
DISMISS_PATTERNS = [
    r"\bvai a casa\b",
    r"\btorna a casa\b",
    r"\bpuoi andare\b",
    r"\barrivederci\b",
    r"\bcongeda\b",
    r"\bvattene\b",
    r"\bora vai\b",
    r"\bè tardi\b",
    r"\bti saluto\b",
]


@dataclass
class HomeGuest:
    """Una companion ospite a casa del giocatore."""
    npc_name: str
    arrived_turn: int
    is_active: bool = True          # False = congedata ma record ancora presente

    def to_dict(self) -> dict:
        return {
            "npc_name": self.npc_name,
            "arrived_turn": self.arrived_turn,
            "is_active": self.is_active,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HomeGuest":
        return cls(
            npc_name=d["npc_name"],
            arrived_turn=d["arrived_turn"],
            is_active=d.get("is_active", True),
        )


class HomeGuestManager:
    """Gestisce le companion ospitate a casa del giocatore.

    Questa classe è il punto di verità su chi è attualmente a casa.
    Viene consultata da:
    - engine._on_phase_change() per NON spostare le companion ospiti
    - MultiNPCManager.get_present_npcs() per includere gli ospiti
    - NarrativeEngine per iniettare il contesto di gruppo
    """

    FLAG_KEY = "_home_guests"  # Chiave nei game_state.flags per la persistenza

    def __init__(self, world: Any) -> None:
        self.world = world
        self._guests: Dict[str, HomeGuest] = {}

    # =========================================================================
    # Public API
    # =========================================================================

    def invite(self, npc_name: str, current_turn: int) -> bool:
        """Aggiunge una companion agli ospiti di casa.

        Returns True se aggiunta, False se già presente.
        """
        if npc_name in self._guests and self._guests[npc_name].is_active:
            logger.debug("[HomeGuest] %s già a casa", npc_name)
            return False
        self._guests[npc_name] = HomeGuest(
            npc_name=npc_name,
            arrived_turn=current_turn,
            is_active=True,
        )
        logger.info("[HomeGuest] %s invitata a casa (turno %d)", npc_name, current_turn)
        return True

    def dismiss(self, npc_name: str) -> bool:
        """Congeda una companion. Returns True se era presente."""
        guest = self._guests.get(npc_name)
        if guest and guest.is_active:
            guest.is_active = False
            logger.info("[HomeGuest] %s congedata", npc_name)
            return True
        return False

    def dismiss_all(self) -> None:
        """Congeda tutte le companion (es. giocatore esce di casa)."""
        for guest in self._guests.values():
            guest.is_active = False
        logger.info("[HomeGuest] Tutte le companion congedate")

    def get_active_guests(self) -> List[str]:
        """Lista dei nomi delle companion attualmente a casa."""
        return [g.npc_name for g in self._guests.values() if g.is_active]

    def is_guest(self, npc_name: str) -> bool:
        """True se la companion è attualmente ospite a casa."""
        g = self._guests.get(npc_name)
        return g is not None and g.is_active

    def has_guests(self) -> bool:
        """True se c'è almeno una companion a casa."""
        return any(g.is_active for g in self._guests.values())

    # =========================================================================
    # Intent detection
    # =========================================================================

    def detect_invite_intent(self, user_input: str, npc_name: str) -> bool:
        """True se l'input del giocatore invita questa companion a casa."""
        text = user_input.lower()
        has_invite = any(re.search(p, text) for p in HOME_INVITE_PATTERNS)
        if not has_invite:
            return False
        # Controlla che sia menzionata questa companion (o nessuna specifica → invita l'attiva)
        npc_lower = npc_name.lower()
        all_companions = [c.lower() for c in (self.world.companions.keys() if self.world else [])]
        other_companions_mentioned = any(
            c in text for c in all_companions if c != npc_lower
        )
        return not other_companions_mentioned or npc_lower in text

    def detect_invite_multiple(self, user_input: str) -> List[str]:
        """Rileva se il giocatore invita più companion contemporaneamente.

        Es: "venite tutte a casa", "Luna e Stella venite da me"
        Returns: lista di nomi companion da invitare (vuota se non rilevato)
        """
        text = user_input.lower()
        if not any(re.search(p, text) for p in HOME_INVITE_PATTERNS):
            return []
        mentioned = []
        if self.world:
            for name in self.world.companions.keys():
                if name.lower() in text:
                    mentioned.append(name)
        # "tutte" o "entrambe" → invita tutte le companion con affinità > 0
        if re.search(r"\btutte\b|\bentrambe\b|\btutti\b", text):
            if self.world:
                return list(self.world.companions.keys())
        return mentioned

    def detect_dismiss_intent(self, user_input: str) -> bool:
        """True se il giocatore congeda la companion attiva."""
        text = user_input.lower()
        return any(re.search(p, text) for p in DISMISS_PATTERNS)

    # =========================================================================
    # Persistence (save/load tramite game_state.flags)
    # =========================================================================

    def save_to_flags(self, flags: dict) -> None:
        flags[self.FLAG_KEY] = [g.to_dict() for g in self._guests.values()]

    def load_from_flags(self, flags: dict) -> None:
        raw = flags.get(self.FLAG_KEY, [])
        self._guests = {}
        for d in raw:
            guest = HomeGuest.from_dict(d)
            self._guests[guest.npc_name] = guest
        if self._guests:
            logger.info(
                "[HomeGuest] Ripristinati %d ospiti: %s",
                len(self._guests),
                [g.npc_name for g in self._guests.values() if g.is_active],
            )
```

---

### 1.2 — Integrare HomeGuestManager in GameEngine

**File:** `src/luna/core/engine.py`

**In `_init_systems()`** aggiungere dopo gli altri sistemi:
```python
from luna.systems.home_guest_manager import HomeGuestManager
self.home_guest_manager = HomeGuestManager(world=self.world)
```

**In `_init_runtime_systems()`** dopo il ripristino degli altri stati:
```python
# Ripristina ospiti di casa dalla sessione salvata
if self.home_guest_manager:
    self.home_guest_manager.load_from_flags(game_state.flags)
    # Forza la location degli ospiti attivi a player_home
    for npc_name in self.home_guest_manager.get_active_guests():
        game_state.set_npc_location(npc_name, "player_home")
```

**In `_on_phase_change()`** nel loop che aggiorna le location degli NPC per la nuova fase:
```python
# AGGIUNGERE: salta le companion ospiti a casa — ignorano la schedule
if self.home_guest_manager and self.home_guest_manager.is_guest(npc_name):
    logger.debug("[PhaseChange] %s è ospite a casa, skip schedule update", npc_name)
    continue
```

**In `StateMemoryManager.save_all()`** (file: `src/luna/systems/state_memory.py`):
```python
# Alla fine del metodo, prima del return:
if hasattr(engine, "home_guest_manager") and engine.home_guest_manager:
    engine.home_guest_manager.save_to_flags(game_state.flags)
```

---

### 1.3 — Gestire l'invito nel turno (phase_handlers.py)

**File:** `src/luna/agents/orchestrator/phase_handlers.py`

**In `_phase_pre_turn()`**, dopo Step 0.3 (NpcLocationRouter), aggiungere:

```python
# ── Step 0.35: HomeGuestManager — rileva inviti a casa ─────────────────
home_mgr = getattr(self.engine, "home_guest_manager", None)
if home_mgr:
    active = game_state.active_companion
    # Invito multiplo (es. "venite tutte a casa")
    multi_invite = home_mgr.detect_invite_multiple(text)
    if multi_invite:
        for npc_name in multi_invite:
            if home_mgr.invite(npc_name, game_state.turn_count):
                game_state.set_npc_location(npc_name, "player_home")
                ctx.home_invited.append(npc_name)
        logger.info("[Orchestrator] Home multi-invite: %s", multi_invite)

    # Invito singolo (companion attiva)
    elif active and home_mgr.detect_invite_intent(text, active):
        if home_mgr.invite(active, game_state.turn_count):
            game_state.set_npc_location(active, "player_home")
            ctx.home_invited.append(active)
            logger.info("[Orchestrator] Home invite: %s", active)

    # Congedo (il giocatore saluta la companion attiva e lei va via)
    elif active and home_mgr.is_guest(active) and home_mgr.detect_dismiss_intent(text):
        home_mgr.dismiss(active)
        game_state.mark_npc_departed(active)
        ctx.home_dismissed = active
        logger.info("[Orchestrator] Home dismiss: %s", active)

    # Se il giocatore lascia casa, congeda tutti
    if (
        ctx.intent.primary == IntentType.MOVEMENT
        and game_state.current_location == "player_home"
        and ctx.intent.target_location != "player_home"
    ):
        if home_mgr.has_guests():
            home_mgr.dismiss_all()
            logger.info("[Orchestrator] Giocatore uscito di casa, companion congedate")
```

**Aggiungere a TurnContext** (`turn_context.py`):
```python
home_invited: List[str] = field(default_factory=list)   # companion appena invitate questo turno
home_dismissed: Optional[str] = None                     # companion congedata questo turno
```

---

## COMPONENTE 2 — HomeSceneContext (consapevolezza reciproca nel prompt)

Quando ci sono 2+ companion a casa, ciascuna deve sapere chi c'è e come si relaziona con le altre.

### 2.1 — Nuovo metodo in NarrativeEngine

**File:** `src/luna/agents/narrative.py`

Aggiungere in `_build_prompt()` DOPO `_npc_presence_context` e PRIMA di `_multi_npc_context`:

```python
sections += self._home_scene_context(context)   # NUOVO: gruppo a casa
```

Aggiungere il metodo:

```python
def _home_scene_context(self, context: Dict[str, Any]) -> List[str]:
    """Inietta nel prompt la consapevolezza del gruppo a casa.

    Attivo solo quando ci sono 2+ companion a player_home.
    Descrive chi è presente, i rapporti tra loro, e le regole di interazione.
    """
    home_scene = context.get("home_scene_context")
    if not home_scene:
        return []
    return [
        "=== SCENA DI GRUPPO — CASA DEL GIOCATORE ===",
        home_scene,
        "",
    ]
```

### 2.2 — Costruire il context in ContextBuilder

**File:** `src/luna/agents/orchestrator/context_builder.py`

Aggiungere alla fine del metodo `_build_context()` (o in `_enrich_context()`):

```python
# ── Home scene context ────────────────────────────────────────────────
home_mgr = getattr(self.engine, "home_guest_manager", None)
if home_mgr and home_mgr.has_guests():
    guests = home_mgr.get_active_guests()
    active = game_state.active_companion
    all_present = [active] + [g for g in guests if g != active]

    if len(all_present) >= 2:
        ctx["home_scene_context"] = self._build_home_scene_text(
            all_present, active, game_state
        )
        ctx["home_mode"] = True
        ctx["home_companions"] = all_present
```

Aggiungere il metodo privato `_build_home_scene_text()`:

```python
def _build_home_scene_text(
    self,
    all_present: List[str],
    active: str,
    game_state: "GameState",
) -> str:
    """Costruisce il testo di contesto per la scena di gruppo a casa."""
    lines = []

    # Chi è presente
    present_str = ", ".join(all_present)
    lines.append(f"PRESENTI A CASA: {present_str}")
    lines.append("")

    # Affinità del giocatore con ciascuno
    lines.append("AFFINITÀ GIOCATORE:")
    for npc in all_present:
        aff = game_state.affinity.get(npc, 0)
        lines.append(f"  - {npc}: {aff}/100")
    lines.append("")

    # Relazioni tra le companion stesse (se definite nel mondo)
    npc_relationships = []
    for i, npc_a in enumerate(all_present):
        for npc_b in all_present[i+1:]:
            rel = self._get_npc_relationship(npc_a, npc_b)
            if rel:
                npc_relationships.append(f"  - {npc_a} ↔ {npc_b}: {rel}")
    if npc_relationships:
        lines.append("RELAZIONI TRA COMPANION:")
        lines.extend(npc_relationships)
        lines.append("")

    # Chi risponde a chi — regole di indirizzamento
    others = [n for n in all_present if n != active]
    lines.append("REGOLE DI SCENA:")
    lines.append(f"  - Stai scrivendo la risposta di {active} (companion attiva).")
    if others:
        lines.append(
            f"  - {', '.join(others)} sono presenti e REAGISCONO a ciò che accade."
        )
        lines.append(
            f"  - Se il giocatore menziona esplicitamente {others[0] if len(others)==1 else 'un altro companion'},"
            f" quella companion risponde nel turno corrente."
        )
        lines.append(
            f"  - Le companion si parlano tra loro in modo naturale — possono essere d'accordo,"
            f" in disaccordo, gelose, o complici."
        )
    lines.append("  - MAX 2 voci per turno. Non fare parlare tutti contemporaneamente.")
    lines.append("")

    # Istruzione esplicita sull'indirizzamento
    lines.append("INDIRIZZAMENTO PLAYER:")
    lines.append("  - Input generico → risponde l'attiva, le altre reagiscono brevemente se rilevante.")
    lines.append(f"  - '[NomePerson], ...' → risponde quella companion, le altre ascoltano.")
    lines.append("  - 'tutte', 'entrambe', 'ragazze' → tutti rispondono (brevemente ciascuna).")

    return "\n".join(lines)

def _get_npc_relationship(self, npc_a: str, npc_b: str) -> str:
    """Restituisce la descrizione del rapporto tra due NPC, se definita."""
    # Prima cerca nelle personality/npc_links
    if not self.engine.personality_engine:
        return ""
    try:
        state_a = self.engine.personality_engine._ensure_state(npc_a)
        links = state_a.npc_links.get(npc_b, {})
        rapport = links.get("rapport", 0) if isinstance(links, dict) else 0
        rel_type = links.get("relationship_type", "") if isinstance(links, dict) else ""
        if rel_type:
            return rel_type
        if rapport > 50:
            return "amiche, si fidano l'una dell'altra"
        elif rapport < -20:
            return "rivali, tensione evidente"
        elif rapport < 0:
            return "freddezza, competizione silenziosa"
        else:
            return "si conoscono, neutrali"
    except Exception:
        return ""
```

---

## COMPONENTE 3 — HomeSceneOrchestrator (turno con 2+ companion a casa)

Questo è il cuore della feature. Quando ci sono 2+ companion a `player_home`, il normale  
`_run_multi_npc` è troppo conservativo (cooldown, soglie affinità, interruzioni occasionali).  
Serve una modalità "home scene" dedicata con regole diverse.

### 3.1 — Nuovo file: `src/luna/systems/home_scene_orchestrator.py`

```python
"""HomeSceneOrchestrator — gestisce i turni con più companion a casa.

Differenze rispetto al MultiNPCManager standard:
- Nessun cooldown: tutte le companion possono parlare ogni turno
- Nessuna soglia affinità minima: se sei a casa tua, sono tutte presenti
- Il giocatore può indirizzare una companion specifica per nome
- Le companion si parlano tra loro (botta e risposta inter-NPC)
- Il sistema genera sequenze di dialogo naturali, non interruzioni
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# Pattern per rilevare a chi il giocatore si sta rivolgendo
# Es: "Luna, cosa pensi?", "Stella dimmi", "ragazze guardate"
_ADDRESS_PATTERNS = {
    "all": [r"\bragazze\b", r"\btutte\b", r"\bentrambe\b", r"\bvoi due\b", r"\bvoi\b"],
}


@dataclass
class HomeTurn:
    """Un singolo turno di dialogo nella home scene."""
    speaker: str             # Nome NPC che parla
    text: str                # Testo generato
    is_reaction: bool = False  # True se è una reazione breve a un'altra companion
    addresses: Optional[str] = None  # A chi si rivolge (None = al giocatore)


@dataclass
class HomeSceneResult:
    """Risultato completo del turno home scene."""
    turns: List[HomeTurn] = field(default_factory=list)
    addressed_npc: Optional[str] = None   # NPC a cui il player si è rivolto
    all_addressed: bool = False           # Player ha parlato a tutte
    primary_speaker: str = ""             # Chi ha risposto per primo/principalmente
    skip_standard_llm: bool = False       # True se questo result sostituisce il normale turno


class HomeSceneOrchestrator:
    """Gestisce i turni di dialogo quando ci sono 2+ companion a casa.

    Viene chiamato dall'orchestratore principale quando home_mode è True.
    """

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def detect_addressed_npc(
        self,
        player_input: str,
        companions_present: List[str],
        active_companion: str,
    ) -> Tuple[Optional[str], bool]:
        """Rileva a chi il giocatore si rivolge.

        Returns:
            (npc_name, all_addressed)
            npc_name: nome specifica companion, None se all_addressed o non specificato
            all_addressed: True se il giocatore si rivolge a tutte
        """
        text = player_input.lower()

        # Controlla "tutte / entrambe / ragazze"
        for pattern in _ADDRESS_PATTERNS["all"]:
            if re.search(pattern, text):
                return None, True

        # Controlla se nomina una companion specifica all'inizio
        for npc_name in companions_present:
            npc_lower = npc_name.lower()
            # "Luna, ..." o "Luna ..." all'inizio
            if re.match(rf"^{re.escape(npc_lower)}\b", text):
                return npc_name, False
            # "[npc], ..." con virgola
            if re.search(rf"\b{re.escape(npc_lower)}\s*,", text):
                return npc_name, False

        # Nessuna specifica → risponde la companion attiva
        return None, False

    def build_reaction_prompt(
        self,
        reacting_npc: str,
        primary_text: str,
        primary_speaker: str,
        player_input: str,
        game_state: Any,
        context: Dict[str, Any],
    ) -> str:
        """Costruisce il prompt per la reazione breve di una companion secondaria.

        La reazione è 1 frase max — un commento, un'espressione, una risposta
        a ciò che ha appena detto l'altra companion.
        """
        comp_def = self.engine.world.companions.get(reacting_npc)
        personality = ""
        if comp_def:
            personality = getattr(comp_def, "base_personality", "")

        aff = game_state.affinity.get(reacting_npc, 0)
        rel = context.get(f"_rel_{reacting_npc}_{primary_speaker}", "neutrale")

        return f"""Sei {reacting_npc}. Personalità: {personality}.
Affinità con il giocatore: {aff}/100.
Rapporto con {primary_speaker}: {rel}.

Il giocatore ha detto: "{player_input}"
{primary_speaker} ha appena risposto: "{primary_text}"

Reagisci in modo brevissimo (UNA frase sola, in italiano) a ciò che ha detto {primary_speaker}.
Puoi essere d'accordo, in disaccordo, gelosa, sorpresa, ironica — in base alla tua personalità.
Stai in personaggio. Non ripetere ciò che ha detto {primary_speaker}.
Parla in prima persona come {reacting_npc}. Nessun JSON — solo la frase di dialogo."""

    def build_inter_npc_dialogue_prompt(
        self,
        speaker: str,
        listener: str,
        context_text: str,
        game_state: Any,
    ) -> str:
        """Prompt per il dialogo diretto companion→companion.

        Usato quando Luna vuole dire qualcosa a Stella o viceversa.
        """
        comp_def = self.engine.world.companions.get(speaker)
        personality = getattr(comp_def, "base_personality", "") if comp_def else ""
        aff_speaker = game_state.affinity.get(speaker, 0)

        return f"""Sei {speaker}. Personalità: {personality}.
Affinità con il giocatore: {aff_speaker}/100.

{context_text}

Dì qualcosa direttamente a {listener} (in italiano, UNA sola frase).
Resta in personaggio. Puoi essere amichevole, competitiva, gelosa, ironica.
Nessun JSON — solo la frase di dialogo, senza virgolette esterne."""
```

---

### 3.2 — Integrare HomeSceneOrchestrator in phase_handlers.py

**File:** `src/luna/agents/orchestrator/phase_handlers.py`

Nel metodo `_run_multi_npc()`, aggiungere **all'inizio** del metodo (prima del check `_has_foreground_quest`):

```python
# ── HOME SCENE MODE: 2+ companion a casa ─────────────────────────────
home_mgr = getattr(self.engine, "home_guest_manager", None)
if (
    home_mgr
    and home_mgr.has_guests()
    and game_state.current_location == "player_home"
):
    ctx = await self._run_home_scene(ctx)
    if ctx.multi_npc.skip_standard_llm:
        return ctx.multi_npc
    # Se home_scene non ha generato output completo, continua con il flow normale
```

Aggiungere il nuovo metodo `_run_home_scene()` in `phase_handlers.py`:

```python
async def _run_home_scene(self, ctx: TurnContext) -> TurnContext:
    """Gestisce il turno quando ci sono 2+ companion a casa.

    Logica:
    1. Rileva a chi il giocatore si sta rivolgendo
    2. La companion indirizzata risponde (normale LLM call)
    3. Le altre companion reagiscono brevemente se rilevante
    4. Se il giocatore si rivolge a tutte, tutte rispondono brevemente

    NOTA: Per default (input generico), la companion ATTIVA risponde normalmente
    via il flusso standard e le altre aggiungono solo una reazione breve.
    Skip_standard_llm è True solo quando il player indirizza una NON-attiva.
    """
    game_state = ctx.game_state
    home_mgr = self.engine.home_guest_manager
    result = MultiNPCResult()

    # Companion presenti (attiva + ospiti)
    guests = home_mgr.get_active_guests()
    active = game_state.active_companion
    all_present = [active] + [g for g in guests if g != active]

    if len(all_present) < 2:
        return ctx  # Nessuna home scene se meno di 2

    # Rileva a chi il player si rivolge
    from luna.systems.home_scene_orchestrator import HomeSceneOrchestrator
    home_orch = HomeSceneOrchestrator(engine=self.engine)
    addressed_npc, all_addressed = home_orch.detect_addressed_npc(
        ctx.text, all_present, active
    )

    # ── CASO 1: Player si rivolge a una companion NON attiva ─────────────
    if addressed_npc and addressed_npc != active:
        # Switcha temporaneamente la companion attiva
        old_active = active
        game_state.active_companion = addressed_npc

        # Genera risposta della companion indirizzata
        companion_narrative = await self._narrative.generate(
            user_input=ctx.text,
            game_state=game_state,
            llm_manager=self.engine.llm_manager,
            context=ctx.context,
        )

        # Genera reazione breve della companion originale
        if companion_narrative and companion_narrative.text:
            reaction_prompt = home_orch.build_reaction_prompt(
                reacting_npc=old_active,
                primary_text=companion_narrative.text,
                primary_speaker=addressed_npc,
                player_input=ctx.text,
                game_state=game_state,
                context=ctx.context,
            )
            try:
                reaction_response, _ = await self.engine.llm_manager.generate(
                    system_prompt=reaction_prompt,
                    user_input="",
                    history=[],
                    json_mode=False,
                    companion_name=old_active,
                )
                reaction_text = reaction_response.text if reaction_response else ""
            except Exception as e:
                logger.warning("[HomeScene] Reaction generation failed: %s", e)
                reaction_text = ""

            from luna.systems.multi_npc.dialogue_sequence import SpeakerType
            result.completed_turns = [
                type("Turn", (), {
                    "speaker": addressed_npc,
                    "text": companion_narrative.text,
                    "visual_en": companion_narrative.visual_en,
                    "tags_en": companion_narrative.tags_en,
                    "speaker_type": SpeakerType.COMPANION,
                })(),
            ]
            if reaction_text:
                result.completed_turns.append(type("Turn", (), {
                    "speaker": old_active,
                    "text": reaction_text,
                    "visual_en": "",
                    "tags_en": [],
                    "speaker_type": SpeakerType.COMPANION,
                })())

        # Ripristina la companion attiva (non cambia il gamestate permanente)
        game_state.active_companion = old_active

        result.skip_standard_llm = True
        result.narrative = companion_narrative
        ctx.multi_npc = result
        return ctx

    # ── CASO 2: Player si rivolge a tutte ────────────────────────────────
    if all_addressed:
        # Ogni companion risponde con una frase breve
        # Ordine: attiva per prima, poi le altre
        turns_list = []
        from luna.systems.multi_npc.dialogue_sequence import SpeakerType

        prev_text = ""
        for npc in all_present:
            old_active = game_state.active_companion
            game_state.active_companion = npc
            try:
                if prev_text:
                    # Aggiunge contesto del turno precedente nel context
                    enriched_context = dict(ctx.context)
                    enriched_context["previous_home_turn"] = (
                        f"[{old_active if npc != old_active else all_present[0]} ha appena detto: {prev_text[:100]}]"
                    )
                else:
                    enriched_context = ctx.context

                npc_narrative = await self._narrative.generate(
                    user_input=ctx.text,
                    game_state=game_state,
                    llm_manager=self.engine.llm_manager,
                    context=enriched_context,
                )
                if npc_narrative and npc_narrative.text:
                    turns_list.append(type("Turn", (), {
                        "speaker": npc,
                        "text": npc_narrative.text,
                        "visual_en": npc_narrative.visual_en,
                        "tags_en": npc_narrative.tags_en,
                        "speaker_type": SpeakerType.COMPANION,
                    })())
                    prev_text = npc_narrative.text
            except Exception as e:
                logger.warning("[HomeScene] All-addressed turn failed for %s: %s", npc, e)
            finally:
                game_state.active_companion = old_active

        result.completed_turns = turns_list
        result.skip_standard_llm = True
        if turns_list:
            # Usa l'ultima narrativa come principale per il guardian
            result.narrative = type("NarrativeOutput", (), {
                "text": " | ".join(t.text for t in turns_list),
                "visual_en": turns_list[0].visual_en if turns_list else "",
                "tags_en": turns_list[0].tags_en if turns_list else [],
            })()
        ctx.multi_npc = result
        return ctx

    # ── CASO 3: Input generico → risponde l'attiva (flusso normale) ──────
    # Aggiunge solo una reazione breve delle altre companion se rilevante.
    # skip_standard_llm = False → il normale LLM call avverrà per la companion attiva.
    # Le reazioni vengono aggiunte DOPO la narrativa principale (in _phase_narrative).
    ctx.home_mode_secondary = [g for g in guests if g != active]
    return ctx
```

---

### 3.3 — Aggiungere le reazioni secondarie post-narrativa

**File:** `src/luna/agents/orchestrator/phase_handlers.py`

Nel metodo `_phase_narrative()`, dopo Step 7 (StateGuardian) e prima di Step 7.5:

```python
# ── Step 7.2: Home scene secondary reactions ──────────────────────────
home_secondary = getattr(ctx, "home_mode_secondary", [])
if home_secondary and ctx.narrative and ctx.narrative.text:
    from luna.systems.home_scene_orchestrator import HomeSceneOrchestrator
    home_orch = HomeSceneOrchestrator(engine=self.engine)
    from luna.systems.multi_npc.dialogue_sequence import SpeakerType
    secondary_turns = []
    for secondary_npc in home_secondary[:1]:  # Max 1 reazione per turno nel flusso normale
        reaction_prompt = home_orch.build_reaction_prompt(
            reacting_npc=secondary_npc,
            primary_text=ctx.narrative.text,
            primary_speaker=game_state.active_companion,
            player_input=ctx.text,
            game_state=game_state,
            context=ctx.context,
        )
        try:
            reaction_response, _ = await self.engine.llm_manager.generate(
                system_prompt=reaction_prompt,
                user_input="",
                history=[],
                json_mode=False,
                companion_name=secondary_npc,
            )
            if reaction_response and reaction_response.text:
                secondary_turns.append(type("Turn", (), {
                    "speaker": secondary_npc,
                    "text": reaction_response.text,
                    "visual_en": "",
                    "tags_en": [],
                    "speaker_type": SpeakerType.COMPANION,
                })())
        except Exception as e:
            logger.warning("[HomeScene] Secondary reaction failed for %s: %s", secondary_npc, e)
    if secondary_turns:
        if not ctx.multi_npc:
            from .turn_context import MultiNPCResult
            ctx.multi_npc = MultiNPCResult()
        ctx.multi_npc.completed_turns = (ctx.multi_npc.completed_turns or []) + secondary_turns
```

---

## COMPONENTE 4 — Companion-to-companion dialogue (botta e risposta inter-NPC)

Quando il giocatore sta osservando e Luna e Stella litigano o chiacchierano tra loro.

### 4.1 — Pattern di attivazione

Il dialogo inter-NPC si attiva quando:
1. `game_state.current_location == "player_home"`
2. `home_guest_manager.has_guests()` == True
3. Il giocatore fa un input che invita all'interazione tra le companion, es:
   - "parlate tra di voi"
   - "cosa ne pensi tu Luna di Stella?"
   - "ditevi quello che pensate"
   - "lasciatevi parlare"
   - oppure semplicemente il player non dice nulla / dice qualcosa di neutro → le companion reagiscono tra loro spontaneamente

### 4.2 — Implementazione

**In `phase_handlers._run_home_scene()`**, aggiungere dopo il CASO 3:

```python
# ── CASO 4: Dialogo inter-NPC ─────────────────────────────────────────
# Attivato quando il player invita le companion a parlarsi tra loro,
# oppure quando il NPCMind di una companion ha un goal verso l'altra.
_INTER_NPC_PATTERNS = [
    r"\bparlatevi\b", r"\bparlate tra\b", r"\bditevi\b",
    r"\bcosa ne pens\w+ tu .+ di .+\b", r"\blasciatevi\b",
]
text_lower = ctx.text.lower()
is_inter_npc = any(re.search(p, text_lower) for p in _INTER_NPC_PATTERNS)

# Controlla anche se il WorldSimulator suggerisce dialogo inter-NPC
# (es. NPCMind di Luna ha un goal verso Stella)
if not is_inter_npc and self.engine.world_simulator:
    for guest_npc in guests:
        mind = self.engine.world_simulator.mind_manager.get(guest_npc)
        if mind and mind.current_goal:
            goal_target = getattr(mind.current_goal, "target", "")
            if goal_target in all_present and goal_target != "player":
                is_inter_npc = True
                break

if is_inter_npc and len(all_present) >= 2:
    # Luna risponde a Stella (o viceversa, in base al goal)
    speaker, listener = all_present[0], all_present[1]
    context_text = f"Sei in casa del giocatore con {listener}. Il giocatore sta guardando."
    if ctx.text and ctx.text.strip():
        context_text += f"\nIl giocatore ha detto: '{ctx.text}'"

    inter_prompt = home_orch.build_inter_npc_dialogue_prompt(
        speaker=speaker,
        listener=listener,
        context_text=context_text,
        game_state=game_state,
    )
    # Genera risposta di speaker
    # Poi genera risposta di listener a speaker
    # ... (stessa logica del CASO 1, ma speaker → listener invece che companion → player)
```

---

## COMPONENTE 5 — UI: mostrare il gruppo a casa

### 5.1 — HomeStatusWidget (opzionale ma consigliato)

La UI dovrebbe mostrare in modo visibile chi è a casa in questo momento.

**Nel TurnResult** (`core/models/output_models.py`), aggiungere:
```python
home_guests: List[str] = field(default_factory=list)  # companion attualmente a casa
```

**In `_build_result()` in `phase_handlers.py`**:
```python
home_mgr = getattr(self.engine, "home_guest_manager", None)
if home_mgr:
    result.home_guests = home_mgr.get_active_guests()
```

**Nella UI** (`ui/main_window/display_manager.py` o equivalente):
- Mostrare i nomi delle companion a casa nell'HUD (es. icone sotto l'immagine)
- Quando `result.home_guests` è non vuoto e `result.present_characters` include 2+ companion → attivare visualizzazione "scena di gruppo"

---

## Ordine di implementazione

```
1. Creare HomeGuestManager (home_guest_manager.py)           → nuovo file, zero rischi
2. Integrare HomeGuestManager in engine.py                   → _init_systems + _on_phase_change
3. Aggiungere HomeGuestManager a StateMemoryManager          → persistenza
4. Aggiungere Step 0.35 in phase_handlers._phase_pre_turn    → rilevamento inviti
5. Aggiungere _home_scene_context in NarrativeEngine         → consapevolezza nel prompt
6. Aggiungere _build_home_scene_text in ContextBuilder       → costruzione contesto
7. Creare HomeSceneOrchestrator (home_scene_orchestrator.py) → nuovo file
8. Aggiungere _run_home_scene in phase_handlers              → turno multi-companion
9. Aggiungere Step 7.2 in phase_handlers._phase_narrative    → reazioni secondarie
10. Aggiungere home_guests a TurnResult + UI                 → visibilità status
```

---

## Test da fare dopo ogni step

```bash
# Step 1-3: verificare che la companion invitata sia a player_home dopo il fase-change
# Input: "Luna, vieni a casa stasera" → fase avanza → Luna deve essere ancora a player_home

# Step 5-6: verificare che il prompt contenga il context di gruppo
# Input: con Luna a casa, invita Stella → il prompt deve mostrare "PRESENTI A CASA: Luna, Stella"

# Step 7-8: verificare il routing
# Input: "Luna, cosa pensi?" con Stella attiva → deve rispondere Luna, Stella reagisce
# Input: "ragazze, cosa fate?" → devono rispondere entrambe

# Step 8 avanzato: botta e risposta
# Input: "parlatevi" → Luna dice qualcosa a Stella, Stella risponde a Luna
```

---

## File di riferimento esistenti

| File | Cosa contiene di utile |
|---|---|
| `systems/invitation_manager.py` | Pattern di rilevamento inviti già scritti (riusare) |
| `systems/multi_npc/manager.py` | `get_present_npcs()` — logica che filtra per location |
| `agents/orchestrator/phase_handlers.py` | `_run_multi_npc()` — da cui prendere spunto |
| `core/models/state_models.py` | `GameState.companion_staying_with_player` — campo analogo |
| `worlds/school_life_complete/locations.yaml` | `player_home` location già definita (riga 390) |
| `core/engine.py` | `_on_phase_change()` — dove aggiungere lo skip per home guests |

---

## Note importanti

**1. `companion_staying_with_player`** (già in GameState) serve per un singolo companion  
che resta con il giocatore durante il cambio di fase. Il `HomeGuestManager` è il suo  
equivalente per N companion + con stato persistente tra sessioni.  
Non rimuovere il campo esistente — mantieni entrambi per backward compat.

**2. Il cambio companion attivo** (`game_state.active_companion`) durante `_run_home_scene`  
è **temporaneo** — viene ripristinato alla fine. Non triggera un companion switch reale.

**3. Il `MultiNPCManager` esistente** continuerà a funzionare normalmente  
per le scene fuori casa. La home scene è una modalità separata, non una sostituzione.

**4. Le immagini** nelle home scene: per ora viene generata una sola immagine  
(quella della companion attiva). Il sistema multi-immagine del `_run_multi_npc` esistente  
può essere riadattato in futuro per mostrare le companion insieme.

**5. Il `player_home` è già definito** in `worlds/school_life_complete/locations.yaml`  
con `companion_can_follow: false`. Questo va cambiato a `true` o rimosso  
(le companion sono invitate esplicitamente, non che "seguono" il giocatore).
