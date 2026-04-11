"""Luna RPG v6 - Initiative Agent.

Manages spontaneous NPC initiatives — moments when companions or NPCs
decide to approach the player on their own terms.

Types of initiative:
  CONVOCATION   → Authority figure summons the player (Preside)
  CONFESSION    → NPC wants to tell you something private (Maria)
  VISIT         → NPC checks on you unexpectedly (Infermiera)
  ENCOUNTER     → Companion finds you "by chance" (Stella, Luna)
  MESSAGE       → NPC leaves a note or sends a message
  INVITATION    → NPC invites you somewhere specific
  INTERVENTION  → NPC notices something and steps in

Initiative flow:
  1. Each turn: check all defined initiatives for eligibility
  2. If eligible and cooldown expired → queue initiative
  3. Next turn: inject narrative_hint + switch companion if needed
  4. Player can accept (follow the NPC) or decline (stay)

YAML definition (in world or companion file):
  initiatives:
    - id: "maria_bathroom_secret"
      npc: "Maria"
      type: "confession"
      trigger:
        location_player: ["school_corridor", "school_classroom"]
        affinity_gte: 10
        time_of_day: ["morning", "afternoon"]
        cooldown_turns: 20
        required_flags: []
        forbidden_flags: ["maria_secret_revealed"]
      narrative_prompt: >
        Maria ti ferma nel corridoio, si guarda intorno nervosa.
        "Devo dirti una cosa... non qui. Il bagno, tra 5 minuti."
      on_accept:
        - action: set_location
          target: school_bathroom_male
        - action: switch_companion
          target: Maria
      urgency: medium
      one_shot: true
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from luna.core.models import GameState, TimeOfDay, WorldDefinition

if TYPE_CHECKING:
    from luna.core.engine import GameEngine

logger = logging.getLogger(__name__)


# =============================================================================
# Data models
# =============================================================================

@dataclass
class InitiativeDefinition:
    """Definition of a possible NPC initiative."""
    initiative_id:   str
    npc:             str
    initiative_type: str           # confession / convocation / visit / encounter / message / invitation / intervention
    narrative_prompt: str          # text injected into NarrativeEngine
    urgency:         str = "medium"  # high / medium / low
    one_shot:        bool = True   # if True, fires only once per session
    # Trigger conditions
    location_player: List[str] = field(default_factory=list)   # player must be in one of these
    affinity_gte:    int = 0
    affinity_lte:    int = 100
    time_of_day:     List[str] = field(default_factory=list)   # empty = any
    cooldown_turns:  int = 15
    required_flags:  List[str] = field(default_factory=list)
    forbidden_flags: List[str] = field(default_factory=list)
    min_turn:        int = 0       # minimum game turn to fire
    # On-accept actions
    on_accept:       List[Dict[str, Any]] = field(default_factory=list)
    # Actions executed when the initiative fires (regardless of accept/decline)
    on_fire:         List[Dict[str, Any]] = field(default_factory=list)
    # Target location where NPC will be after initiative
    target_location: Optional[str] = None


@dataclass
class ActiveInitiative:
    """A pending or active initiative."""
    definition:      InitiativeDefinition
    fired_at_turn:   int
    accepted:        bool = False
    shown:           bool = False   # narrative_hint already injected


@dataclass
class InitiativeEvent:
    """Telemetry snapshot for a single initiative transition."""
    initiative_id: str
    npc: str
    initiative_type: str
    urgency: str
    status: str                # fired | accepted | declined | expired
    turn: int
    narrative_prompt: str
    player_response: Optional[str] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initiative_id": self.initiative_id,
            "npc": self.npc,
            "initiative_type": self.initiative_type,
            "urgency": self.urgency,
            "status": self.status,
            "turn": self.turn,
            "narrative_prompt": self.narrative_prompt,
            "player_response": self.player_response,
            "note": self.note,
        }


# =============================================================================
# Built-in initiative definitions
# =============================================================================

_BUILTIN_INITIATIVES: List[InitiativeDefinition] = [

    # ── Maria ─────────────────────────────────────────────────────────────────
    InitiativeDefinition(
        initiative_id="maria_bathroom_secret",
        npc="Maria",
        initiative_type="confession",
        narrative_prompt=(
            "*Maria ti ferma nel corridoio, si guarda intorno come se avesse paura "
            "di essere sentita. Le sue mani stringono il secchio un po' troppo forte.* "
            "«Scusa se ti disturbo... ma devo dirti una cosa. Non qui. "
            "Il bagno degli uomini, tra cinque minuti. Ti aspetto.»"
        ),
        urgency="medium",
        one_shot=True,
        location_player=["school_corridor", "school_classroom", "school_entrance"],
        affinity_gte=15,
        time_of_day=["morning", "afternoon"],
        cooldown_turns=25,
        forbidden_flags=["maria_secret_revealed"],
        min_turn=8,
        on_accept=[
            {"action": "set_location", "target": "school_bathroom_male"},
        ],
        target_location="school_bathroom_male",
    ),

    InitiativeDefinition(
        initiative_id="maria_lunch_offer",
        npc="Maria",
        initiative_type="invitation",
        narrative_prompt=(
            "*Maria si avvicina con un contenitore di plastica, un po' impacciata.* "
            "«Ho cucinato troppo stamattina. Se non hai mangiato... "
            "ho il mio angolino in fondo al corridoio. Non è gran cosa.»"
        ),
        urgency="low",
        one_shot=True,
        location_player=["school_corridor", "school_cafeteria"],
        affinity_gte=25,
        time_of_day=["afternoon"],
        cooldown_turns=30,
        min_turn=15,
        on_accept=[
            {"action": "set_location", "target": "school_storage"},
        ],
        target_location="school_storage",
    ),

    # ── Preside ───────────────────────────────────────────────────────────────
    InitiativeDefinition(
        initiative_id="preside_summon",
        npc="preside",
        initiative_type="convocation",
        narrative_prompt=(
            "*Un foglio scritto a mano viene consegnato al tuo banco durante la lezione. "
            "Carta intestata del liceo, scrittura precisa e formale.* "
            "«Lo studente è convocato in presidenza alle ore 14:00. "
            "Si raccomanda puntualità. — Preside Bianchi»"
        ),
        urgency="high",
        one_shot=False,
        location_player=["school_classroom", "school_corridor"],
        affinity_gte=0,
        time_of_day=["morning"],
        cooldown_turns=40,
        min_turn=5,
        on_accept=[
            {"action": "set_location", "target": "school_entrance"},
        ],
        target_location="school_entrance",
    ),

    # ── Infermiera ────────────────────────────────────────────────────────────
    InitiativeDefinition(
        initiative_id="infermiera_checkup",
        npc="infermiera",
        initiative_type="visit",
        narrative_prompt=(
            "*L'infermiera ti ferma nel corridoio con un sorriso preoccupato, "
            "tenendo in mano un foglio con il tuo nome.* "
            "«Sei tu? Bene. Ho notato che non sei ancora passato per la visita "
            "di inizio anno. Cinque minuti in infermeria, promesso.»"
        ),
        urgency="medium",
        one_shot=True,
        location_player=["school_corridor", "school_entrance"],
        affinity_gte=0,
        time_of_day=["morning", "afternoon"],
        cooldown_turns=50,
        min_turn=3,
        on_accept=[
            {"action": "set_location", "target": "school_infirmary"},
        ],
        target_location="school_infirmary",
    ),

    # ── Stella ────────────────────────────────────────────────────────────────
    InitiativeDefinition(
        initiative_id="stella_casual_encounter",
        npc="Stella",
        initiative_type="encounter",
        narrative_prompt=(
            "*Stella ti passa accanto nel corridoio rallentando il passo "
            "di un millimetro — abbastanza da essere notato, non abbastanza "
            "da essere intenzionale. O forse sì.* "
            "«Oh, sei tu.» *Pausa.* «Niente, ciao.»"
        ),
        urgency="low",
        one_shot=False,
        location_player=["school_corridor", "school_entrance"],
        affinity_gte=5,
        time_of_day=["morning", "afternoon"],
        cooldown_turns=12,
        forbidden_flags=["stella_confession_done"],
        min_turn=4,
        on_accept=[],
    ),

    InitiativeDefinition(
        initiative_id="stella_gym_challenge",
        npc="Stella",
        initiative_type="encounter",
        narrative_prompt=(
            "*Stella si avvicina con un pallone da basket sotto il braccio, "
            "aria sfidante.* "
            "«Sai giocare o sei solo bravo a guardare? "
            "Ho la palestra per altri venti minuti.»"
        ),
        urgency="low",
        one_shot=False,
        location_player=["school_corridor", "school_gym"],
        affinity_gte=20,
        time_of_day=["afternoon"],
        cooldown_turns=20,
        min_turn=10,
        on_accept=[
            {"action": "set_location", "target": "school_gym"},
        ],
        target_location="school_gym",
    ),

    # ── Luna ─────────────────────────────────────────────────────────────────
    InitiativeDefinition(
        initiative_id="luna_after_class_note",
        npc="Luna",
        initiative_type="message",
        narrative_prompt=(
            "*Trovi un biglietto piegato sul tuo banco alla fine della lezione. "
            "Scrittura ordinata, quasi troppo.* "
            "«Esercizio 14 del capitolo 3 — lo rivediamo dopo le 15. "
            "Ufficio 204. L.F.»"
        ),
        urgency="medium",
        one_shot=True,
        location_player=["school_classroom"],
        affinity_gte=20,
        time_of_day=["morning"],
        cooldown_turns=30,
        required_flags=[],
        forbidden_flags=["luna_private_lesson_done"],
        min_turn=6,
        on_accept=[
            {"action": "set_location", "target": "school_office_luna"},
        ],
        target_location="school_office_luna",
    ),

    InitiativeDefinition(
        initiative_id="luna_corridor_pause",
        npc="Luna",
        initiative_type="encounter",
        narrative_prompt=(
            "*Luna ti incrocia nel corridoio e si ferma un secondo più del necessario "
            "prima di riprendere a camminare.* "
            "«Come stai andando con il programma?» "
            "*Non aspetta davvero una risposta. Ma la domanda era reale.*"
        ),
        urgency="low",
        one_shot=False,
        location_player=["school_corridor"],
        affinity_gte=10,
        time_of_day=["morning", "afternoon"],
        cooldown_turns=15,
        min_turn=4,
        on_accept=[],
    ),

    # ── Bibliotecaria ─────────────────────────────────────────────────────────
    InitiativeDefinition(
        initiative_id="bibliotecaria_book_recommend",
        npc="bibliotecaria",
        initiative_type="encounter",
        narrative_prompt=(
            "*La bibliotecaria appoggia silenziosamente un libro sul tavolo davanti a te "
            "senza dire nulla. Poi, quasi come ripensamento:* "
            "«Qualcuno con il tuo sguardo dovrebbe leggere questo. "
            "Non c'è fretta per restituirlo.»"
        ),
        urgency="low",
        one_shot=True,
        location_player=["school_library"],
        affinity_gte=0,
        time_of_day=["afternoon", "evening"],
        cooldown_turns=30,
        min_turn=5,
        on_accept=[],
    ),

    # ── Stella attacca Luna davanti al giocatore ───────────────────────────────
    InitiativeDefinition(
        initiative_id="stella_attacks_luna_public",
        npc="Stella",
        initiative_type="intervention",
        narrative_prompt=(
            "*Stella si avvicina a Luna con un sorriso affilato come un rasoio, "
            "ignorando completamente te come se fossi arredamento.* "
            "«Professoressa Ferretti. Ho letto le sue valutazioni di metà anno.» "
            "*Pausa teatrale, voce abbastanza alta perché sentano tutti.* "
            "«Interessante come i suoi voti siano... selettivi. "
            "Dev'essere difficile essere obiettivi quando ci si affezione agli studenti.» "
            "*Luna si irrigidisce. Stella non ha finito.*"
        ),
        urgency="medium",
        one_shot=False,
        location_player=["school_corridor", "school_classroom", "school_entrance"],
        affinity_gte=10,
        time_of_day=["morning", "afternoon"],
        cooldown_turns=25,
        required_flags=[],
        forbidden_flags=["stella_luna_truce"],
        min_turn=8,
        on_accept=[],
        on_fire=[
            {"action": "set_flag", "key": "stella_attacks_luna_public_seen"},
        ],
    ),

    # ── Stella provoca Luna in privato ────────────────────────────────────────
    InitiativeDefinition(
        initiative_id="stella_corners_luna",
        npc="Stella",
        initiative_type="intervention",
        narrative_prompt=(
            "*Stella ti ferma in corridoio con aria disinvolta, ma i suoi occhi "
            "guardano oltre la tua spalla dove Luna sta raccogliendo dei libri.* "
            "«Ehi. Hai notato che la tua insegnante preferita arrossisce "
            "ogni volta che le parli?» *Sorride, soddisfatta di sé.* "
            "«Trovi normale che un'insegnante si comporti così con uno studente?»"
        ),
        urgency="low",
        one_shot=False,
        location_player=["school_corridor"],
        affinity_gte=15,
        time_of_day=["morning", "afternoon"],
        cooldown_turns=20,
        required_flags=[],
        forbidden_flags=["stella_luna_truce"],
        min_turn=12,
        on_accept=[],
    ),

    # ── Maria difende Luna davanti a Stella ────────────────────────────────────
    InitiativeDefinition(
        initiative_id="maria_defends_luna",
        npc="Maria",
        initiative_type="intervention",
        narrative_prompt=(
            "*Maria, che stava lavando il pavimento in un angolo, si raddrizza lentamente "
            "poggiando il mop. Nessuno la guarda mai. Oggi sceglie di farsi guardare.* "
            "«Signorina Conti.» *Voce quieta, senza alzarla.* «La professoressa Ferretti "
            "lavora qui dalle sei di mattina. Tutti i giorni. "
            "Prima di giudicare il suo lavoro, forse potrebbe provare a fare il suo.» "
            "*Torna a lavare. Come se non avesse detto nulla.*"
        ),
        urgency="medium",
        one_shot=False,
        location_player=["school_corridor", "school_classroom"],
        affinity_gte=20,
        time_of_day=["morning", "afternoon"],
        cooldown_turns=30,
        required_flags=["stella_attacks_luna_public_seen"],
        forbidden_flags=[],
        min_turn=15,
        on_accept=[],
    ),

    # ── Maria si avvicina a Luna in un momento di solitudine ──────────────────
    InitiativeDefinition(
        initiative_id="maria_comforts_luna",
        npc="Maria",
        initiative_type="encounter",
        narrative_prompt=(
            "*Luna è ferma davanti alla finestra del corridoio, sola. "
            "Maria passa, si ferma. Posa una tazza di caffè sul davanzale accanto a lei "
            "senza una parola.* "
            "*Luna la guarda sorpresa. Maria scrolla le spalle, quasi imbarazzata.* "
            "«L'ho fatto troppo lungo, non mi piaceva. Tanto lei lo prende amaro, no?» "
            "*Una bugia gentile. Tutte e due lo sanno.*"
        ),
        urgency="low",
        one_shot=False,
        location_player=["school_corridor", "school_entrance"],
        affinity_gte=25,
        time_of_day=["morning", "afternoon"],
        cooldown_turns=35,
        required_flags=[],
        forbidden_flags=[],
        min_turn=10,
        on_accept=[],
    ),
]


# =============================================================================
# InitiativeAgent
# =============================================================================

class InitiativeAgent:
    """Manages spontaneous NPC initiatives.

    Called by TurnOrchestrator at Step 0.5 (before intent routing).
    If an initiative fires, it injects context into the narrative and
    optionally switches the active companion.
    """

    def __init__(self, world: WorldDefinition) -> None:
        self.world = world

        # Load built-in + world-defined initiatives
        self._definitions: Dict[str, InitiativeDefinition] = {}
        for init_def in _BUILTIN_INITIATIVES:
            self._definitions[init_def.initiative_id] = init_def
        self._load_world_initiatives()

        # Runtime state
        self._last_fired: Dict[str, int] = {}     # initiative_id → turn fired
        self._fired_once: set = set()              # one-shot initiatives fired
        self._active: Optional[ActiveInitiative] = None   # currently being played
        self._latest_event: Optional[InitiativeEvent] = None

    # =========================================================================
    # Main entry — called every turn
    # =========================================================================

    def check_and_get_context(
        self,
        game_state: GameState,
        user_input: str,
    ) -> Optional[str]:
        """Check for initiatives and return narrative context if one fires.

        Returns a narrative hint string to inject into the quest_context,
        or None if no initiative is active.
        """
        decision, response_text = self._classify_player_response(user_input)
        # Check if player just accepted/declined an active initiative
        if self._active:
            current = self._active.definition
            if decision == "accept":
                self._execute_accept_actions(self._active, game_state)
                self._record_event("accepted", current, game_state.turn_count, response_text)
                logger.info("[InitiativeAgent] Accepted: %s", current.initiative_id)
            elif decision == "decline":
                self._record_event("declined", current, game_state.turn_count, response_text or user_input.strip())
                logger.info("[InitiativeAgent] Declined: %s", current.initiative_id)
            else:
                self._record_event("expired", current, game_state.turn_count, user_input.strip())
                logger.debug("[InitiativeAgent] Initiative expired without response: %s", current.initiative_id)
            self._active = None
            return None

        # Check for new initiative — fires immediately, no delay
        candidate = self._find_eligible(game_state)
        if candidate:
            self._active = ActiveInitiative(
                definition=candidate,
                fired_at_turn=game_state.turn_count,
            )
            self._last_fired[candidate.initiative_id] = game_state.turn_count
            if candidate.one_shot:
                self._fired_once.add(candidate.initiative_id)
            self._record_event("fired", candidate, game_state.turn_count)
            # Execute on_fire actions immediately when initiative triggers
            self._execute_on_fire_actions(candidate, game_state)
            logger.info(
                "[InitiativeAgent] Firing: %s (npc=%s type=%s)",
                candidate.initiative_id, candidate.npc, candidate.initiative_type
            )
            return self._build_context(candidate, game_state)

        return None

    # =========================================================================
    # Eligibility check
    # =========================================================================

    def _find_eligible(self, game_state: GameState) -> Optional[InitiativeDefinition]:
        """Find the best eligible initiative for this turn."""
        candidates = []

        for init_id, init_def in self._definitions.items():
            if not self._is_eligible(init_def, game_state):
                continue
            candidates.append(init_def)

        if not candidates:
            return None

        # Weight by type priority
        type_priority = {
            "convocation": 10,
            "confession":  8,
            "visit":       7,
            "invitation":  6,
            "encounter":   4,
            "message":     5,
            "intervention": 9,
        }

        # Add randomness — not all eligible fire every turn
        # Higher urgency = more likely
        roll_weights = {
            "high":   0.8,
            "medium": 0.4,
            "low":    0.2,
        }

        import random
        for c in sorted(candidates,
                        key=lambda x: type_priority.get(x.initiative_type, 3),
                        reverse=True):
            weight = roll_weights.get(c.urgency, 0.3)
            if random.random() < weight:
                return c

        return None

    def _is_eligible(
        self, init_def: InitiativeDefinition, game_state: GameState
    ) -> bool:
        # One-shot already fired
        if init_def.one_shot and init_def.initiative_id in self._fired_once:
            return False

        # Minimum turn
        if game_state.turn_count < init_def.min_turn:
            return False

        # Cooldown
        last = self._last_fired.get(init_def.initiative_id, -999)
        if game_state.turn_count - last < init_def.cooldown_turns:
            return False

        # Location check
        if (init_def.location_player and
                game_state.current_location not in init_def.location_player):
            return False

        # Affinity check
        affinity = game_state.affinity.get(init_def.npc, 0)
        if affinity < init_def.affinity_gte:
            return False
        if affinity > init_def.affinity_lte:
            return False

        # Time of day
        if init_def.time_of_day:
            current_tod = (
                game_state.time_of_day.value
                if hasattr(game_state.time_of_day, "value")
                else str(game_state.time_of_day)
            )
            if current_tod not in init_def.time_of_day:
                return False

        # Required flags
        for flag in init_def.required_flags:
            if not game_state.flags.get(flag):
                return False

        # Forbidden flags
        for flag in init_def.forbidden_flags:
            if game_state.flags.get(flag):
                return False

        # Don't interrupt ongoing quest scene
        if game_state.active_quests:
            # Allow only low urgency if already in quest
            if init_def.urgency == "low":
                return False

        # Don't fire if player is already with this NPC
        if game_state.active_companion == init_def.npc:
            return False

        return True

    # =========================================================================
    # Context building
    # =========================================================================

    def _build_context(
        self, init_def: InitiativeDefinition, game_state: GameState
    ) -> str:
        """Build narrative context for NarrativeEngine — sounds like story, not system."""

        urgency_tone = {
            "high":   "Do not leave room for the player to deflect. The NPC is insistent.",
            "medium": "Leave a natural beat for the player to respond.",
            "low":    "Keep it light. The NPC would not insist if brushed off.",
        }.get(init_def.urgency, "")

        loc_note = ""
        if init_def.target_location:
            loc_def = self.world.locations.get(init_def.target_location)
            loc_name = loc_def.name if loc_def else init_def.target_location
            loc_note = f" The scene could naturally shift toward {loc_name}."

        return (
            f"{init_def.narrative_prompt}\n"
            f"{urgency_tone}{loc_note}"
        )

    # =========================================================================
    # Accept actions
    # =========================================================================

    def _execute_accept_actions(
        self,
        initiative: ActiveInitiative,
        game_state: GameState,
    ) -> None:
        """Execute on_accept actions when player accepts."""
        for action in initiative.definition.on_accept:
            act    = action.get("action", "")
            target = action.get("target", "")
            if act == "set_location" and target:
                game_state.current_location = target
                logger.info("[InitiativeAgent] set_location → %s", target)
            elif act == "set_flag":
                game_state.flags[action.get("key", target)] = True

    def _execute_on_fire_actions(
        self,
        init_def: InitiativeDefinition,
        game_state: GameState,
    ) -> None:
        """Execute on_fire actions immediately when initiative triggers."""
        for action in init_def.on_fire:
            act    = action.get("action", "")
            target = action.get("target", "")
            if act == "set_flag":
                key = action.get("key", target)
                game_state.flags[key] = True
                logger.info("[InitiativeAgent] on_fire set_flag → %s", key)
            elif act == "set_location" and target:
                game_state.current_location = target
                logger.info("[InitiativeAgent] on_fire set_location → %s", target)

    # =========================================================================
    # World YAML loading
    # =========================================================================

    def _load_world_initiatives(self) -> None:
        """Load initiative definitions from world data if present."""
        try:
            if not self.world:
                return
            raw = getattr(self.world, "initiatives", None) or {}
            for init_id, data in raw.items():
                if not isinstance(data, dict):
                    continue
                try:
                    init_def = InitiativeDefinition(
                        initiative_id=init_id,
                        npc=data.get("npc", ""),
                        initiative_type=data.get("type", "encounter"),
                        narrative_prompt=data.get("narrative_prompt", ""),
                        urgency=data.get("urgency", "medium"),
                        one_shot=data.get("one_shot", True),
                        location_player=data.get("location_player", []),
                        affinity_gte=data.get("affinity_gte", 0),
                        affinity_lte=data.get("affinity_lte", 100),
                        time_of_day=data.get("time_of_day", []),
                        cooldown_turns=data.get("cooldown_turns", 20),
                        required_flags=data.get("required_flags", []),
                        forbidden_flags=data.get("forbidden_flags", []),
                        min_turn=data.get("min_turn", 0),
                        on_accept=data.get("on_accept", []),
                        on_fire=data.get("on_fire", []),
                        target_location=data.get("target_location"),
                    )
                    self._definitions[init_id] = init_def
                    logger.debug("[InitiativeAgent] Loaded world initiative: %s", init_id)
                except Exception as e:
                    logger.warning("[InitiativeAgent] Failed to load initiative %s: %s", init_id, e)
        except Exception as e:
            logger.warning("[InitiativeAgent] World initiatives load failed: %s", e)

    # =========================================================================
    # Status
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        return {
            "definitions": len(self._definitions),
            "fired_once":  list(self._fired_once),
            "active":      self._active.definition.initiative_id if self._active else None,
            "last_event": self._latest_event.to_dict() if self._latest_event else None,
        }

    def _classify_player_response(self, user_input: str) -> Tuple[str, Optional[str]]:
        """Return (decision, matched_text) for the player's reply."""
        import re

        text = user_input.strip().lower()
        if not text:
            return "none", None

        decline_patterns = r"no|non posso|adesso no|dopo|non ora|lascia perdere|maybe later"
        accept_patterns = r"sì|si|ok|certo|vengo|accetto|vado|arrivo|capito|subito|yes|arrivo subito"

        decline_match = re.search(decline_patterns, text)
        if decline_match:
            return "decline", decline_match.group(0)

        accept_match = re.search(accept_patterns, text)
        if accept_match:
            return "accept", accept_match.group(0)

        return "none", None

    def _record_event(
        self,
        status: str,
        definition: InitiativeDefinition,
        turn: int,
        player_response: Optional[str] = None,
        note: str = "",
    ) -> None:
        self._latest_event = InitiativeEvent(
            initiative_id=definition.initiative_id,
            npc=definition.npc,
            initiative_type=definition.initiative_type,
            urgency=definition.urgency,
            status=status,
            turn=turn,
            narrative_prompt=definition.narrative_prompt,
            player_response=player_response.strip() if player_response else None,
            note=note,
        )

    def consume_latest_event(self) -> Optional[InitiativeEvent]:
        """Return and clear the most recent initiative event."""
        event = self._latest_event
        self._latest_event = None
        return event
