"""Luna RPG - Turn Context.

Stato esplicito di un singolo turno di gioco.
Creato da execute(), passato in pipeline attraverso le fasi.

Separato da orchestrator.py per evitare import circolari:
  turn_context.py → luna.core.models   (nessun ciclo)
  orchestrator.py → turn_context.py    (stesso package)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from luna.core.models import (
        GameState,
        IntentBundle,
        NarrativeCompassData,
        NarrativeOutput,
        VisualOutput,
    )
    from luna.systems.npc_location_router import RouteResult
    from luna.systems.npc_goal_evaluator import GoalHint


@dataclass
class MultiNPCResult:
    """Output del blocco MultiNPC — tutto ciò che _run_multi_npc produce.

    Raccoglie i turni completati, i path delle immagini e i flag di controllo
    del flusso in un unico oggetto restituito a _phase_narrative.
    """
    completed_turns: List[Any] = field(default_factory=list)
    image_paths: List[Optional[str]] = field(default_factory=list)
    was_interrupted: bool = False
    # Se True, _phase_narrative salta la chiamata LLM standard
    skip_standard_llm: bool = False
    # NarrativeOutput sintetizzato dall'ultimo turno MultiNPC
    narrative: Optional["NarrativeOutput"] = None


@dataclass
class TurnContext:
    """Stato esplicito di un turno. Creato in execute(), passato alle fasi.

    Sostituisce le ~20 variabili locali di execute() con un oggetto
    con nome e tipo espliciti. GameState è mutato in-place dalle fasi
    esattamente come avveniva con le variabili locali.

    Campi obbligatori: user_input, game_state, text.
    Tutti gli altri sono opzionali e vengono popolati dalle fasi.
    """

    # ── Input ────────────────────────────────────────────────────────────────
    user_input: str
    game_state: "GameState"   # Mutato in-place dalle fasi (come prima)
    text: str = ""            # user_input.strip(), impostato in execute()

    # ── Fase pre-turn (Steps 0–2) ────────────────────────────────────────────
    intent: Optional["IntentBundle"] = None
    switched: bool = False
    old_companion: Optional[str] = None
    is_temporary: bool = False
    initiative_context: str = ""
    initiative_event_payload: Optional[Dict[str, Any]] = None
    # Se non None, execute() ritorna immediatamente con questo risultato
    early_return: Optional[Any] = None   # TurnResult — Any per evitare import circolare

    # ── v8: NPC Secondary Activation System ─────────────────────────────────
    npc_route_target: Optional["RouteResult"] = None  # Step 0.3: routing to NPC
    npc_goal_hint: Optional["GoalHint"] = None        # Step 0.6: NPC goal hint

    # ── Fase world state (Steps 2.5–3) ──────────────────────────────────────
    directive: Optional[Any] = None           # TurnDirective da WorldSimulator
    directive_summary: Optional[Dict[str, Any]] = None
    scene_direction: Optional[Any] = None     # SceneDirection da DirectorAgent
    gm_agenda_context: str = ""
    gm_move_name: str = ""
    narrative_compass: Optional["NarrativeCompassData"] = None
    cross_npc_hint: str = ""                  # Fix 3: hint da NPC non attivo

    # ── Fase context (Steps 4–5) ─────────────────────────────────────────────
    context: Dict[str, Any] = field(default_factory=dict)

    # ── Fase narrative (Steps 5.5–7.5) ──────────────────────────────────────
    multi_npc: Optional[MultiNPCResult] = None
    narrative: Optional["NarrativeOutput"] = None
    changes: Dict[str, Any] = field(default_factory=dict)  # da guardian.apply()

    # ── Fase finalize (Steps 8–10) ───────────────────────────────────────────
    phase_changed: bool = False
    visual_output: Optional["VisualOutput"] = None
    media: Optional[Dict[str, Any]] = None

    # ── Flag per avanzamento fase manuale ────────────────────────────────────
    is_manual_phase_advance: bool = False

    # ── Infrastruttura ───────────────────────────────────────────────────────
    turn_logger: Optional[Any] = None
