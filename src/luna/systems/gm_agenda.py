"""Luna RPG v7 — GM Agenda System.

Computes the GM Move for each turn and builds the prompt section injected
into the NarrativeEngine system prompt.

Milestone 1: TensionTracker as sole input source.
Milestone 2: NPCMind needs/unspoken integrated via priority queue.
Milestone 3: Active Promises tracked from LLM JSON output.
Milestone 4b: Arc threads from world YAML, tension phase normalization,
              climate fallback from NPCMind, fixed _last_gm_move timing.
Milestone 5:  Flag override in arc threads (§6.3), Dramatic Questions from YAML.
Milestone 6:  Group Moves (TRIANGLE, SECRET_AGREEMENT, PROTECTION_RACKET).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Global arc phase fallbacks (used when no custom arc_threads in world YAML)
# ---------------------------------------------------------------------------

_GLOBAL_ARC_PHASES: list[tuple[int, int, str, str]] = [
    (0,  20,  "UNKNOWN",   "Il personaggio non ti conosce ancora. Prima impressione da fare."),
    (20, 40,  "ARMOR",     "Mantiene distanza. Ogni avvicinamento ha un costo."),
    (40, 60,  "CRACKS",    "La maschera si incrina. Momenti di autenticità fuggenti."),
    (60, 75,  "CONFLICT",  "Vuole e rifiuta allo stesso tempo. Tensione al massimo."),
    (75, 90,  "SURRENDER", "La resistenza cede. Vulnerabilità reale emerge."),
    (90, 101, "DEVOTED",   "Arco chiuso. Gestisci l'intensità, non la conquista."),
]

_PHASE_DRAMATIC_QUESTIONS: dict[str, str] = {
    "UNKNOWN":   "Come si forma la prima impressione tra voi?",
    "ARMOR":     "{name} abbassa la guardia o costruisce un muro più alto?",
    "CRACKS":    "Il momento di autenticità durerà o verrà ritrattato?",
    "CONFLICT":  "{name} sceglie il desiderio o la protezione?",
    "SURRENDER": "Quanto profonda sarà la vulnerabilità che emerge?",
    "DEVOTED":   "Come si regge l'intensità senza consumarla?",
}

# ---------------------------------------------------------------------------
# GM Move definitions — (move_name, instruction_for_llm)
# ---------------------------------------------------------------------------

_MOVES: dict[str, tuple[str, str]] = {
    "ENRICH_WORLD": (
        "ENRICH_WORLD",
        "Arricchisci la scena con dettagli sensoriali o un NPC sullo sfondo.\n"
        "  Nessun conflitto attivo. Rendi il mondo vivo e presente.",
    ),
    "ANNOUNCE_DANGER": (
        "ANNOUNCE_DANGER",
        "Introduce un segnale sottile che qualcosa sta per cambiare.\n"
        "  Non dichiararlo esplicitamente — fallo sentire nell'atmosfera\n"
        "  o nel comportamento dell'NPC.",
    ),
    "COMPLICATE_GOAL": (
        "COMPLICATE_GOAL",
        "Il giocatore si avvicina a qualcosa? Aggiungi un ostacolo sociale\n"
        "  o emotivo. NON rifiutare frontalmente — alza il costo, non sbarra\n"
        "  la porta.",
    ),
    "PUT_IN_SPOT": (
        "PUT_IN_SPOT",
        "Metti il giocatore in una situazione che richiede una scelta reale.\n"
        "  Entrambe le opzioni devono avere un costo visibile.",
    ),
    "ADVANCE_ARC": (
        "ADVANCE_ARC",
        "Fai un piccolo passo avanti nell'arco narrativo del companion.\n"
        "  Anche un momento piccolo conta: uno sguardo diverso dal solito,\n"
        "  un'esitazione insolita, una parola più morbida o più dura.",
    ),
    "OFFER_AT_COST": (
        "OFFER_AT_COST",
        "L'NPC offre qualcosa che il giocatore desidera, ma c'è un costo\n"
        "  emotivo o sociale visibile. L'offerta deve essere reale, non\n"
        "  una trappola.",
    ),
    "REVEAL": (
        "REVEAL",
        "Qualcosa di nascosto emerge. Può essere un comportamento, una\n"
        "  reazione, un'informazione. Mostra — non spiegare.",
    ),
    "SHOW_OFF_SCREEN": (
        "SHOW_OFF_SCREEN",
        "Fai emergere nella conversazione o nel comportamento dell'NPC\n"
        "  qualcosa che è successo fuori scena. Non spiegarlo — mostralo\n"
        "  attraverso tensione o reazione.",
    ),
    "CREATE_URGENCY": (
        "CREATE_URGENCY",
        "Introduce una scadenza reale o percepita. Un evento si avvicina,\n"
        "  un'occasione sta per chiudersi. Il giocatore deve sentire\n"
        "  che il tempo stringe.",
    ),
    "RESOLVE_PROMISE": (
        "RESOLVE_PROMISE",
        "Riprendi un elemento narrativo introdotto in precedenza che\n"
        "  non è ancora stato ripreso. Deve emergere in modo naturale\n"
        "  nel testo o nel comportamento dell'NPC.",
    ),
    # --- Group Moves (Milestone 6 — multi-NPC scenes) ---
    "TRIANGLE": (
        "TRIANGLE",
        "Due personaggi sono presenti in questo momento e hanno desideri\n"
        "  o bisogni incompatibili. Lascia emergere una competizione sottile\n"
        "  per l'attenzione del giocatore. Non dichiarare il conflitto —\n"
        "  mostralo attraverso toni, sguardi, silenzi.",
    ),
    "SECRET_AGREEMENT": (
        "SECRET_AGREEMENT",
        "I personaggi presenti hanno una storia tesa tra loro e fingono\n"
        "  normalità. Mostra l'accordo di superficie mentre la tensione\n"
        "  relazionale filtra. Il giocatore non deve capire subito —\n"
        "  fa' sentire l'atmosfera.",
    ),
    "PROTECTION_RACKET": (
        "PROTECTION_RACKET",
        "Un personaggio sta proteggendo il giocatore da un'altra presenza.\n"
        "  La protezione può essere fisica, sociale o emotiva.\n"
        "  Mostra il costo che il protettore sta pagando.",
    ),
}


# Tension phase → default move name (when no NPCMind data available)
_TENSION_TO_MOVE_NAME: dict[str, str] = {
    "calm":          "ENRICH_WORLD",
    "foreshadowing": "ANNOUNCE_DANGER",
    "buildup":       "COMPLICATE_GOAL",
    "trigger":       "PUT_IN_SPOT",
}

# Normalize external phase labels to canonical internal values
_TENSION_PHASE_ALIASES: dict[str, str] = {
    "event":     "trigger",
    "threshold": "trigger",
    "presagio":  "foreshadowing",
    "accumulo":  "buildup",
    "esplosione":"trigger",
}

# NPC need → move name (critical level >0.8)
_NEED_TO_MOVE_CRITICAL: dict[str, str] = {
    "intimacy":    "OFFER_AT_COST",
    "safety":      "ANNOUNCE_DANGER",
    "recognition": "SHOW_OFF_SCREEN",
    "social":      "ADVANCE_ARC",
    "purpose":     "ADVANCE_ARC",
    "rest":        "ENRICH_WORLD",
}

# NPC need → move name (moderate level 0.6-0.8)
_NEED_TO_MOVE_MODERATE: dict[str, str] = {
    "intimacy":    "COMPLICATE_GOAL",
    "safety":      "ANNOUNCE_DANGER",
    "recognition": "ADVANCE_ARC",
    "social":      "ADVANCE_ARC",
    "purpose":     "ADVANCE_ARC",
    "rest":        "ENRICH_WORLD",
}

# Stall threshold: turns without affinity change before forcing CREATE_URGENCY
STALL_THRESHOLD = 8

# Promise lifecycle thresholds (in turns)
PROMISE_AGING_AT = 7     # fresh → aging
PROMISE_OVERDUE_AT = 15  # aging → overdue


# ---------------------------------------------------------------------------
# NPCMindSnapshot — lightweight transfer object (avoids importing npc_mind.py)
# ---------------------------------------------------------------------------

@dataclass
class NPCMindSnapshot:
    """Extracted NPCMind data needed for GM Move selection.

    Built by the orchestrator from the live NPCMind object.
    Keeps gm_agenda.py free of NPCMind dependencies.
    """
    dominant_need: str          # need name with highest value
    need_value: float           # 0.0–1.0
    has_burning_unspoken: bool  # any unspoken item with weight >= 0.7
    burning_unspoken_weight: float  # highest unspoken weight (0.0 if none)
    burning_unspoken_hint: str  # short description of the burning item
    has_untold_events: bool     # any off_screen events not told to player
    dominant_emotion: str       # dominant emotion name (empty if neutral)
    emotion_intensity: float    # 0.0–1.0


# ---------------------------------------------------------------------------
# Promise — narrative hook declared by the LLM
# ---------------------------------------------------------------------------

@dataclass
class Promise:
    """An active narrative promise declared by the LLM in a previous turn.

    Stored as dicts in game_state.flags["_active_promises"].
    Converted to this dataclass in the orchestrator for GM Agenda use.

    emotional_weight influences priority ordering when multiple promises
    compete at the same lifecycle phase (0.0 = trivial, 1.0 = critical).

    suspended_until_turn suppresses the promise from the priority queue
    until that turn (useful during mandatory story beats).
    """
    id: str                         # snake_case identifier
    turn_created: int               # turn when the promise was declared
    phase: str = "fresh"            # "fresh" | "aging" | "overdue" (computed)
    emotional_weight: float = 0.5   # tiebreaker at same priority level
    suspended_until_turn: int = 0   # 0 = never suspended

    @classmethod
    def from_dict(cls, data: dict, current_turn: int) -> "Promise":
        turn_created = data.get("turn_created", current_turn)
        age = current_turn - turn_created
        if age >= PROMISE_OVERDUE_AT:
            phase = "overdue"
        elif age >= PROMISE_AGING_AT:
            phase = "aging"
        else:
            phase = "fresh"
        return cls(
            id=data["id"],
            turn_created=turn_created,
            phase=phase,
            emotional_weight=float(data.get("emotional_weight", 0.5)),
            suspended_until_turn=int(data.get("suspended_until_turn", 0)),
        )

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "turn_created": self.turn_created,
                   "emotional_weight": self.emotional_weight}
        if self.suspended_until_turn:
            d["suspended_until_turn"] = self.suspended_until_turn
        return d


def load_promises(flags: dict, current_turn: int) -> List[Promise]:
    """Load, phase-classify, and filter active promises from game_state.flags.

    Promises suspended until a future turn are excluded from the result.
    """
    raw = flags.get("_active_promises", [])
    promises = [Promise.from_dict(p, current_turn) for p in raw if isinstance(p, dict)]
    return [p for p in promises if p.suspended_until_turn <= current_turn]


def save_promises(promises: List[Promise], flags: dict) -> None:
    """Serialize active promises back into game_state.flags."""
    flags["_active_promises"] = [p.to_dict() for p in promises]


def add_promise(promise_id: str, turn: int, flags: dict,
                emotional_weight: float = 0.5) -> None:
    """Add a new promise to the active list (no duplicates)."""
    raw: list = flags.setdefault("_active_promises", [])
    if not any(p.get("id") == promise_id for p in raw):
        raw.append({
            "id": promise_id,
            "turn_created": turn,
            "emotional_weight": max(0.0, min(1.0, emotional_weight)),
        })
        logger.debug("[GM] Promise added: %s (turn %d, weight %.2f)",
                     promise_id, turn, emotional_weight)


def remove_promise(promise_id: str, flags: dict) -> None:
    """Remove a resolved promise from the active list."""
    raw: list = flags.get("_active_promises", [])
    before = len(raw)
    flags["_active_promises"] = [p for p in raw if p.get("id") != promise_id]
    if len(flags["_active_promises"]) < before:
        logger.debug("[GM] Promise resolved: %s", promise_id)


# ---------------------------------------------------------------------------
# Group context (Milestone 6)
# ---------------------------------------------------------------------------

@dataclass
class GroupContext:
    """Multi-NPC scene context for group GM Move selection.

    Built by the orchestrator when multiple companions are present.
    Keeps gm_agenda.py free of GameState dependencies.
    """
    secondary_minds: Dict[str, "NPCMindSnapshot"]  # name → snapshot (excludes active companion)
    relationship_tensions: Dict[str, str]           # "npc_a|npc_b" → "tense|warm|neutral"


# ---------------------------------------------------------------------------
# Priority queue candidate
# ---------------------------------------------------------------------------

@dataclass
class _Candidate:
    """Internal candidate for GM Move selection.

    Sorted by (priority ASC, weight DESC): lowest priority number wins,
    ties broken by highest weight.
    """
    priority: int    # 0 = highest urgency
    weight: float    # tiebreaker within the same priority level
    move: str        # GM Move name key
    reason: str      # human-readable explanation for logging


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_arc_phase(affinity: int) -> Tuple[str, str]:
    """Return (phase_label, thread_text) for the given affinity value."""
    for lo, hi, phase, thread in _GLOBAL_ARC_PHASES:
        if lo <= affinity < hi:
            return phase, thread
    return "DEVOTED", _GLOBAL_ARC_PHASES[-1][3]


def resolve_arc_thread(
    companion_name: str,
    phase: str,
    gm_agenda_config: Optional[Dict] = None,
) -> str:
    """Return the arc thread text for a companion+phase, with YAML override support.

    Lookup chain (first match wins):
      1. world.gm_agenda.arc_threads[companion_name][phase]  — companion override
      2. If arc_threads[companion_name] is a string, treat as template key:
         world.gm_agenda.arc_thread_templates[template][phase]
      3. Global fallback from _GLOBAL_ARC_PHASES

    Args:
        companion_name:   Active companion key.
        phase:            Arc phase label (e.g. "ARMOR").
        gm_agenda_config: world.gm_agenda dict (may be empty or None).

    Returns:
        Thread description string.
    """
    if gm_agenda_config:
        companion_entry = gm_agenda_config.get("arc_threads", {}).get(companion_name)
        if isinstance(companion_entry, dict):
            # Direct phase-to-text override
            if phase in companion_entry:
                return companion_entry[phase]
        elif isinstance(companion_entry, str):
            # companion_entry is a template name
            template = gm_agenda_config.get("arc_thread_templates", {}).get(companion_entry, {})
            if isinstance(template, dict) and phase in template:
                return template[phase]

    # Global fallback
    for _, _, p, thread in _GLOBAL_ARC_PHASES:
        if p == phase:
            return thread
    return _GLOBAL_ARC_PHASES[-1][3]


def resolve_arc_phase_and_thread(
    companion_name: str,
    affinity: int,
    flags: Optional[Dict] = None,
    gm_agenda_config: Optional[Dict] = None,
) -> Tuple[str, str]:
    """Compute (phase, thread) with full fallback chain and flag override support.

    Supports two YAML formats for arc_threads[companion]:

    **List format (rich)** — supports flag_override:
    ```yaml
    arc_threads:
      Luna:
        - range: [25, 50]
          phase: "THE_CALCULATION"
          thread: "Lo studia come minaccia..."
          flag_override:
            luna_trusted_player: "THE_CRACK"
    ```

    **Dict format (simple)** — phase → thread text overrides, no flag logic:
    ```yaml
    arc_threads:
      Luna:
        ARMOR: "Custom Luna ARMOR thread"
    ```

    Fallback chain:
      1. Companion list entry matching affinity range (with flag_override check)
      2. Companion dict override for base phase
      3. Template reference (companion_entry is a string template key)
      4. Global _GLOBAL_ARC_PHASES

    Args:
        companion_name:   Active companion key.
        affinity:         Current affinity value (0–100).
        flags:            Current game_state.flags (for flag_override evaluation).
        gm_agenda_config: world.gm_agenda dict.

    Returns:
        (phase_label, thread_text)
    """
    flags = flags or {}

    if gm_agenda_config:
        companion_entry = gm_agenda_config.get("arc_threads", {}).get(companion_name)

        if isinstance(companion_entry, list):
            # Rich list format: [{range, phase, thread, flag_override?}]
            for entry in companion_entry:
                lo, hi = entry.get("range", [0, 101])
                if lo <= affinity < hi:
                    phase = entry.get("phase", "UNKNOWN")
                    thread = entry.get("thread", "")

                    # Evaluate flag overrides: first matching flag wins
                    for flag_name, override_phase in entry.get("flag_override", {}).items():
                        if flags.get(flag_name):
                            phase = override_phase
                            # Find thread for the overridden phase in same list
                            thread = ""
                            for other in companion_entry:
                                if other.get("phase") == override_phase:
                                    thread = other.get("thread", "")
                                    break
                            logger.debug(
                                "[GM] Arc flag override: %s flag=%s -> phase=%s",
                                companion_name, flag_name, override_phase,
                            )
                            break

                    if not thread:
                        thread = resolve_arc_thread(companion_name, phase, gm_agenda_config)
                    return phase, thread

        elif isinstance(companion_entry, dict):
            # Simple dict format: {PHASE: "text"}
            base_phase, _ = get_arc_phase(affinity)
            thread = companion_entry.get(base_phase) or resolve_arc_thread(
                companion_name, base_phase, gm_agenda_config
            )
            return base_phase, thread

        elif isinstance(companion_entry, str):
            # Template reference
            base_phase, _ = get_arc_phase(affinity)
            return base_phase, resolve_arc_thread(companion_name, base_phase, gm_agenda_config)

    # Global fallback
    return get_arc_phase(affinity)


def get_dramatic_question(
    phase: str,
    companion_name: str,
    gm_agenda_config: Optional[Dict] = None,
) -> str:
    """Return the active dramatic question for this arc phase.

    Checks world.gm_agenda.dramatic_questions[phase] first, then global fallback.
    Custom questions support {name} placeholder.

    Args:
        phase:            Arc phase label (e.g. "ARMOR" or custom "THE_CRACK").
        companion_name:   Used to format {name} in question templates.
        gm_agenda_config: world.gm_agenda dict (optional).
    """
    if gm_agenda_config:
        custom_q = gm_agenda_config.get("dramatic_questions", {}).get(phase)
        if custom_q:
            return str(custom_q).format(name=companion_name)
    template = _PHASE_DRAMATIC_QUESTIONS.get(phase, "Dove porta questa strada?")
    return template.format(name=companion_name)


def _get_move(name: str) -> Tuple[str, str]:
    """Return (move_name, instruction) for a known move name."""
    return _MOVES.get(name, _MOVES["ENRICH_WORLD"])


def _detect_group_move(
    group_ctx: GroupContext,
    primary_mind: Optional[NPCMindSnapshot],
) -> Optional[Tuple[str, float, str]]:
    """Detect the best group GM Move for the current scene.

    Priority within group moves:
      1. PROTECTION_RACKET — primary has high safety need + secondary present
      2. SECRET_AGREEMENT  — tense relationship between any two present NPCs
      3. TRIANGLE          — primary and secondary have different dominant needs

    Returns (move_name, weight, reason) or None if no group move applies.
    """
    if not group_ctx.secondary_minds:
        return None

    secondary_items = list(group_ctx.secondary_minds.items())

    # 1. PROTECTION_RACKET: primary has safety need >= 0.7 + secondary present
    if primary_mind and primary_mind.dominant_need == "safety" and primary_mind.need_value >= 0.7:
        sec_name = secondary_items[0][0]
        return ("PROTECTION_RACKET", 0.65, f"protection_racket:{sec_name}")

    # 2. SECRET_AGREEMENT: any tense relationship in scene
    for rel_key, tension in group_ctx.relationship_tensions.items():
        if tension == "tense":
            return ("SECRET_AGREEMENT", 0.60, f"secret_agreement:{rel_key}")

    # 3. TRIANGLE: primary and any secondary have different dominant needs (both >= 0.5)
    if primary_mind and primary_mind.need_value >= 0.5:
        for sec_name, sec_mind in secondary_items:
            if (sec_mind.need_value >= 0.5
                    and sec_mind.dominant_need != primary_mind.dominant_need):
                return ("TRIANGLE", 0.70, f"triangle:{sec_name}:{primary_mind.dominant_need}"
                        f"_vs_{sec_mind.dominant_need}")

    return None


def select_gm_move(
    tension_phase: str,
    last_move: Optional[str] = None,
    mind: Optional[NPCMindSnapshot] = None,
    stall_count: int = 0,
    promises: Optional[List[Promise]] = None,
    tension_level: float = 0.0,
    group_ctx: Optional[GroupContext] = None,
) -> Tuple[str, str, str]:
    """Select the GM Move via structured priority queue.

    Builds a list of _Candidate objects, sorts by (priority ASC, weight DESC),
    then applies anti-repeat filtering (skipped for P0–P2 emergencies).

    Priority levels:
      P0  Overdue promise           -> RESOLVE_PROMISE
      P1  Burning unspoken ≥0.7     -> REVEAL
      P2  Critical need >0.8        -> need-based move
      P3  Tension trigger/event     -> PUT_IN_SPOT
      P4  Aging promise             -> RESOLVE_PROMISE
      P5  Untold off-screen events  -> SHOW_OFF_SCREEN
      P6  Moderate need 0.6–0.8     -> need-based move
      P7  Tension buildup/foreshadow-> tension-based move (+ ADVANCE_ARC variant)
      P8  Stall counter exceeded    -> CREATE_URGENCY
      P9  Default                   -> ENRICH_WORLD

    Collision at same P: highest weight wins.
    Anti-repeat (P3+): if best == last_move, pick next non-repeated candidate.

    Args:
        tension_phase:  Phase of the hottest tension axis (normalized internally).
        last_move:      Move used last turn (anti-repeat guard).
        mind:           NPCMind snapshot (None if unavailable).
        stall_count:    Turns without affinity change.
        promises:       Active non-suspended promises (classified by phase).
        tension_level:  Float 0.0–1.0, used as weight for tension candidates.
        group_ctx:      Multi-NPC scene context (None for solo scenes). Enables
                        group moves TRIANGLE/SECRET_AGREEMENT/PROTECTION_RACKET
                        at P2 (weight 0.5–0.7, below critical individual need).

    Returns:
        (move_name, instruction_text, reason_for_log)
    """
    # Normalize phase aliases (event/threshold → trigger, etc.)
    tension_phase = _TENSION_PHASE_ALIASES.get(tension_phase, tension_phase)

    candidates: List[_Candidate] = []

    # ── P0: Overdue promise ──────────────────────────────────────────────────
    if promises:
        overdue = [p for p in promises if p.phase == "overdue"]
        if overdue:
            worst = min(overdue, key=lambda p: p.turn_created)
            candidates.append(_Candidate(0, worst.emotional_weight,
                                         "RESOLVE_PROMISE", f"promise_overdue:{worst.id}"))

    # ── P1: Burning unspoken ─────────────────────────────────────────────────
    if mind and mind.has_burning_unspoken:
        candidates.append(_Candidate(1, mind.burning_unspoken_weight,
                                     "REVEAL",
                                     f"unspoken_burning:{mind.burning_unspoken_weight:.2f}"))

    # ── P2: Critical need >0.8 ───────────────────────────────────────────────
    if mind and mind.need_value > 0.8:
        raw_move = _NEED_TO_MOVE_CRITICAL.get(mind.dominant_need, "ADVANCE_ARC")
        candidates.append(_Candidate(2, mind.need_value, raw_move,
                                     f"need_critical:{mind.dominant_need}:{mind.need_value:.2f}"))

    # ── P2 (group): Group moves — weight 0.5–0.7, below critical individual need ─
    if group_ctx:
        group_result = _detect_group_move(group_ctx, mind)
        if group_result:
            g_move, g_weight, g_reason = group_result
            candidates.append(_Candidate(2, g_weight, g_move, g_reason))

    # ── P3: Tension trigger ──────────────────────────────────────────────────
    if tension_phase == "trigger":
        candidates.append(_Candidate(3, tension_level,
                                     "PUT_IN_SPOT", "tension_phase:trigger"))

    # ── P4: Aging promise ────────────────────────────────────────────────────
    if promises:
        aging = [p for p in promises if p.phase == "aging"]
        if aging:
            worst = min(aging, key=lambda p: p.turn_created)
            candidates.append(_Candidate(4, worst.emotional_weight,
                                         "RESOLVE_PROMISE", f"promise_aging:{worst.id}"))

    # ── P5: Untold off-screen events (only during calm/foreshadowing) ────────
    if mind and mind.has_untold_events and tension_phase in ("calm", "foreshadowing"):
        candidates.append(_Candidate(5, 0.5, "SHOW_OFF_SCREEN", "untold_off_screen_event"))

    # ── P6: Moderate need 0.6–0.8 ───────────────────────────────────────────
    if mind and 0.6 <= mind.need_value <= 0.8:
        raw_move = _NEED_TO_MOVE_MODERATE.get(mind.dominant_need, "ADVANCE_ARC")
        candidates.append(_Candidate(6, mind.need_value, raw_move,
                                     f"need_moderate:{mind.dominant_need}:{mind.need_value:.2f}"))

    # ── P7: Tension buildup / foreshadowing ──────────────────────────────────
    if tension_phase in ("buildup", "foreshadowing"):
        primary = _TENSION_TO_MOVE_NAME.get(tension_phase, "ENRICH_WORLD")
        candidates.append(_Candidate(7, tension_level, primary,
                                     f"tension_phase:{tension_phase}"))
        if tension_phase == "buildup":
            # ADVANCE_ARC as natural variation — wins anti-repeat when primary repeats
            candidates.append(_Candidate(7, tension_level * 0.8,
                                         "ADVANCE_ARC", "tension_buildup_variation"))

    # ── P8: Stall counter ────────────────────────────────────────────────────
    if stall_count >= STALL_THRESHOLD:
        stall_weight = min(1.0, stall_count / (STALL_THRESHOLD * 2))
        candidates.append(_Candidate(8, stall_weight,
                                     "CREATE_URGENCY", f"stall_counter:{stall_count}"))

    # ── P9: Default ──────────────────────────────────────────────────────────
    candidates.append(_Candidate(9, 0.0, "ENRICH_WORLD", "default:ambient"))

    # Sort: priority ASC, weight DESC
    candidates.sort(key=lambda c: (c.priority, -c.weight))

    # Anti-repeat: only for P3+; P0–P2 are too urgent to skip
    best = candidates[0]
    if best.priority >= 3 and best.move == last_move:
        for alt in candidates[1:]:
            if alt.move != last_move:
                best = _Candidate(alt.priority, alt.weight, alt.move,
                                  alt.reason + ":anti_repeat")
                break

    move_name, instruction = _get_move(best.move)
    return move_name, instruction, best.reason


def build_gm_agenda_context(
    companion_name: str,
    affinity: int,
    tension_phase: str,
    tension_axis: str,
    tension_level: float,
    turn: int,
    flags: Optional[Dict] = None,
    last_move: Optional[str] = None,
    mind: Optional[NPCMindSnapshot] = None,
    stall_count: int = 0,
    promises: Optional[List[Promise]] = None,
    gm_agenda_config: Optional[Dict] = None,
    group_ctx: Optional[GroupContext] = None,
) -> Tuple[str, str]:
    """Build the GM Agenda prompt section and return it with the selected move name.

    Args:
        companion_name:   Active companion name.
        affinity:         Current affinity with the companion (0–100).
        tension_phase:    Phase of the hottest tension axis.
        tension_axis:     Name of the hottest tension axis.
        tension_level:    Float 0.0–1.0 of the hottest axis.
        turn:             Current turn number.
        flags:            Current game_state.flags (for arc thread flag_override).
        last_move:        GM Move used last turn (anti-repeat).
        mind:             NPCMind snapshot (optional, Milestone 2).
        stall_count:      Turns without affinity change (for stall detection).
        gm_agenda_config: world.gm_agenda dict — arc threads, dramatic questions.
        group_ctx:        Multi-NPC context for group moves (Milestone 6).

    Returns:
        (prompt_section_text, move_name)
    """
    phase, thread = resolve_arc_phase_and_thread(
        companion_name, affinity, flags, gm_agenda_config
    )
    dramatic_q = get_dramatic_question(phase, companion_name, gm_agenda_config)
    move_name, move_instruction, reason = select_gm_move(
        tension_phase, last_move, mind, stall_count, promises, tension_level, group_ctx
    )

    axis_label = tension_axis.replace("_", " ").title() if tension_axis else "narrativa"
    level_pct = f"{tension_level:.0%}"

    lines = [
        "=== GM AGENDA THIS TURN ===",
        f"Arc: {companion_name} — {phase} (affinity {affinity}, turn {turn})",
        f"Arc Thread: {thread}",
        f'Dramatic Question: "{dramatic_q}"',
        "",
        f"GM Move: {move_name}",
        f"  -> {move_instruction}",
        f"  (Tensione {axis_label}: {tension_phase}, livello {level_pct})",
    ]

    # Add Active Promises block (aging/overdue only — fresh ones are invisible)
    if promises:
        visible = [p for p in promises if p.phase in ("aging", "overdue")]
        if visible:
            lines.append("")
            lines.append("Active Promises (must be honored soon):")
            for p in visible:
                age = turn - p.turn_created
                lines.append(f"  [{p.phase.upper()}] {p.id} (turn {p.turn_created}, age {age}t)")

    # Add group scene context (Milestone 6)
    if group_ctx and group_ctx.secondary_minds:
        lines.append("")
        secondary_names = ", ".join(group_ctx.secondary_minds.keys())
        lines.append(f"Scene: {companion_name} + {secondary_names} (multi-NPC)")
        for sec_name, sec_mind in group_ctx.secondary_minds.items():
            lines.append(f"  [{sec_name}: need={sec_mind.dominant_need} {sec_mind.need_value:.0%}]")

    # Add NPCMind context lines when available (helps LLM understand the why)
    if mind:
        mind_lines = []
        if mind.has_burning_unspoken and mind.burning_unspoken_hint:
            mind_lines.append(
                f"  [NPC unspoken, weight {mind.burning_unspoken_weight:.0%}]: "
                f"{mind.burning_unspoken_hint}"
            )
        elif mind.need_value >= 0.6:
            mind_lines.append(
                f"  [NPC need: {mind.dominant_need} {mind.need_value:.0%}]"
            )
        if mind.dominant_emotion and mind.emotion_intensity >= 0.4:
            mind_lines.append(
                f"  [NPC emotion: {mind.dominant_emotion} "
                f"{mind.emotion_intensity:.0%}]"
            )
        if mind_lines:
            lines.append("")
            lines.extend(mind_lines)

    lines.append("")

    logger.info(
        "[GM] Turn %d | %s | Arc: %s | Move: %s | Reason: %s",
        turn, companion_name, phase, move_name, reason,
    )

    return "\n".join(lines), move_name
