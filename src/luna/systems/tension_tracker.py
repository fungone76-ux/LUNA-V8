"""Luna RPG v7 — Tension Tracker.

Replaces random event triggers with organic narrative pressure.
Instead of `random.random() < 0.35`, tension builds over time
and events fire when pressure crosses a threshold.

Cycle: CALM → FORESHADOWING → BUILDUP → EVENT → CALM

Each tension axis has:
- growth_rate: how fast it grows per turn
- decay_rate: how fast it drops after an event fires
- foreshadow_at: pressure level for hints
- threshold: pressure level to trigger event
- hints: narrative hints for foreshadowing and buildup phases
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from luna.core.models import GameState
    from luna.systems.world_simulator import NarrativePressure

logger = logging.getLogger(__name__)


@dataclass
class TensionAxis:
    """A single axis of narrative tension."""
    name: str
    level: float = 0.0
    growth_rate: float = 0.02
    decay_rate: float = 0.15
    threshold: float = 0.75
    foreshadow_at: float = 0.4
    buildup_at: float = 0.6

    # Hints for each phase
    foreshadow_hints: List[str] = field(default_factory=list)
    buildup_hints: List[str] = field(default_factory=list)

    # Events that can trigger at threshold
    events: List[str] = field(default_factory=list)

    # Boost conditions
    growth_boosts: List[Dict[str, Any]] = field(default_factory=list)

    # Tracking
    last_triggered_turn: int = -99
    cooldown: int = 15  # min turns between triggers on same axis
    hint_cooldown: int = 0  # turns until next hint is allowed

    @property
    def phase(self) -> str:
        if self.level < self.foreshadow_at:
            return "calm"
        if self.level < self.buildup_at:
            return "foreshadowing"
        if self.level < self.threshold:
            return "buildup"
        return "trigger"

    def tick(self, turn: int, boosts: Dict[str, float] = None) -> None:
        """Advance tension by one turn."""
        # Base growth
        self.level = min(1.0, self.level + self.growth_rate)

        # Apply boosts
        if boosts:
            for trigger, amount in boosts.items():
                if trigger in (self.growth_boosts or []):
                    self.level = min(1.0, self.level + amount)

        # Hint cooldown
        if self.hint_cooldown > 0:
            self.hint_cooldown -= 1

    def trigger_event(self, turn: int) -> Optional[str]:
        """Try to trigger an event. Returns event_id or None."""
        if self.level < self.threshold:
            return None
        if turn - self.last_triggered_turn < self.cooldown:
            return None
        if not self.events:
            return None

        event = random.choice(self.events)
        self.last_triggered_turn = turn
        self.level = max(0.0, self.level - self.decay_rate)
        logger.info(
            "[TensionTracker] Axis '%s' triggered event '%s' at level %.2f",
            self.name, event, self.level + self.decay_rate,
        )
        return event

    def get_hint(self) -> Optional[str]:
        """Get a phase-appropriate hint, if cooldown allows."""
        if self.hint_cooldown > 0:
            return None

        phase = self.phase
        hints = []
        if phase == "foreshadowing" and self.foreshadow_hints:
            hints = self.foreshadow_hints
        elif phase == "buildup" and self.buildup_hints:
            hints = self.buildup_hints

        if hints:
            self.hint_cooldown = 2  # don't hint every turn
            return random.choice(hints)
        return None

    def decay(self, amount: Optional[float] = None) -> None:
        """Decay tension (after event fires or situation resolves)."""
        self.level = max(0.0, self.level - (amount or self.decay_rate))


class TensionTracker:
    """Manages all tension axes. Produces narrative pressure hints."""

    def __init__(self) -> None:
        self.axes: Dict[str, TensionAxis] = {}
        self._pending_events: List[str] = []

    def add_axis(self, axis: TensionAxis) -> None:
        self.axes[axis.name] = axis

    def get_axis(self, name: str) -> Optional[TensionAxis]:
        return self.axes.get(name)

    # -------------------------------------------------------------------------
    # Main tick — called by WorldSimulator
    # -------------------------------------------------------------------------

    def tick(self, game_state: "GameState", turn: int) -> List[str]:
        """Tick all axes. Returns list of triggered event_ids."""
        triggered = []

        for name, axis in self.axes.items():
            # Context-dependent boosts
            boosts = self._compute_boosts(axis, game_state)

            # Tick the axis
            axis.tick(turn, boosts)

            # Check for event trigger
            event = axis.trigger_event(turn)
            if event:
                triggered.append(event)

        return triggered

    def get_pressure_hint(
        self, game_state: "GameState", turn: int,
    ) -> Optional["NarrativePressure"]:
        """Get the most pressing narrative hint across all axes."""
        from luna.systems.world_simulator import NarrativePressure

        best_hint = None
        best_level = 0.0

        for name, axis in self.axes.items():
            if axis.level <= axis.foreshadow_at:
                continue
            if axis.level <= best_level:
                continue

            hint_text = axis.get_hint()
            if not hint_text:
                continue

            best_level = axis.level
            phase = axis.phase
            best_hint = NarrativePressure(
                pressure_type=phase,
                hint=hint_text,
                building_towards=axis.events[0] if axis.events else name,
                pressure_level=axis.level,
            )

        return best_hint

    # -------------------------------------------------------------------------
    # Manual pressure adjustments
    # -------------------------------------------------------------------------

    def boost(self, axis_name: str, amount: float = 0.1) -> None:
        """Manually boost tension (e.g., player broke a rule → authority rises)."""
        axis = self.axes.get(axis_name)
        if axis:
            axis.level = min(1.0, axis.level + amount)
            logger.debug("[TensionTracker] Boosted '%s' by %.2f → %.2f",
                         axis_name, amount, axis.level)

    def release(self, axis_name: str, amount: float = 0.2) -> None:
        """Release tension (e.g., romantic scene happened → romantic drops)."""
        axis = self.axes.get(axis_name)
        if axis:
            axis.decay(amount)
            logger.debug("[TensionTracker] Released '%s' by %.2f → %.2f",
                         axis_name, amount, axis.level)

    # -------------------------------------------------------------------------
    # Context boosts based on game state
    # -------------------------------------------------------------------------

    def _compute_boosts(
        self, axis: TensionAxis, game_state: "GameState",
    ) -> Dict[str, float]:
        """Compute contextual boosts for a tension axis."""
        boosts = {}

        if axis.name == "romantic":
            # Romantic tension grows faster with high affinity
            active = game_state.active_companion
            aff = game_state.affinity.get(active, 0)
            if aff > 50:
                extra = (aff - 50) / 500.0  # max +0.1 at affinity 100
                boosts["high_affinity"] = extra

        elif axis.name == "authority":
            # Authority tension boosted by rule-breaking flags
            if game_state.flags.get("caught_cheating"):
                boosts["rule_breaking"] = 0.05
            if game_state.flags.get("caught_spying"):
                boosts["rule_breaking"] = 0.08

        elif axis.name == "environmental":
            # Environmental tension grows slightly in evening/night
            time_str = game_state.time_of_day.value if hasattr(
                game_state.time_of_day, "value"
            ) else str(game_state.time_of_day)
            if time_str in ("Evening", "Night"):
                boosts["dark_time"] = 0.01

        return boosts

    # -------------------------------------------------------------------------
    # Initialization from YAML
    # -------------------------------------------------------------------------

    def load_from_config(self, config: Dict[str, Any]) -> None:
        """Load tension axes from tension_config.yaml."""
        # Tolerate both {"tension_axes": {...}} and direct {axis_name: {...}} formats
        if "tension_axes" in config:
            config = config["tension_axes"]
        for axis_name, axis_data in config.items():
            axis = TensionAxis(
                name=axis_name,
                growth_rate=axis_data.get("growth_rate", 0.02),
                decay_rate=axis_data.get("decay_rate", 0.15),
                threshold=axis_data.get("threshold", 0.75),
                foreshadow_at=axis_data.get("foreshadow_at", 0.4),
                buildup_at=axis_data.get("buildup_at", axis_data.get("foreshadow_at", 0.4) + 0.2),
                foreshadow_hints=axis_data.get("foreshadow_hints", []),
                buildup_hints=axis_data.get("buildup_hints", []),
                events=axis_data.get("events", []),
                cooldown=axis_data.get("cooldown", 15),
            )
            self.add_axis(axis)
            logger.debug("[TensionTracker] Loaded axis '%s'", axis_name)

    def load_defaults(self) -> None:
        """Load default tension axes (for worlds without tension_config)."""
        defaults = {
            "romantic": TensionAxis(
                name="romantic",
                growth_rate=0.025,
                decay_rate=0.15,
                foreshadow_at=0.35,
                buildup_at=0.55,
                threshold=0.75,
                foreshadow_hints=[
                    "Gli sguardi tra voi durano un po' troppo",
                    "Un silenzio carico di tensione",
                ],
                buildup_hints=[
                    "L'aria tra voi è carica di qualcosa di non detto",
                    "Ogni contatto accidentale sembra elettrico",
                ],
                events=["alone_classroom"],
            ),
            "environmental": TensionAxis(
                name="environmental",
                growth_rate=0.015,
                decay_rate=0.25,
                foreshadow_at=0.3,
                buildup_at=0.5,
                threshold=0.7,
                foreshadow_hints=[
                    "Il cielo fuori si è scurito",
                    "Un colpo di vento fa sbattere una finestra",
                ],
                buildup_hints=[
                    "Le finestre vibrano per il vento",
                    "Si sentono tuoni in lontananza",
                ],
                events=["rainstorm", "blackout"],
                cooldown=20,
            ),
            "authority": TensionAxis(
                name="authority",
                growth_rate=0.012,
                decay_rate=0.2,
                foreshadow_at=0.45,
                buildup_at=0.65,
                threshold=0.8,
                foreshadow_hints=[
                    "Il preside è stato visto aggirarsi per i corridoi",
                    "La segretaria sembra nervosa oggi",
                ],
                buildup_hints=[
                    "Si mormora di un'ispezione imminente",
                    "Il preside ha convocato una riunione urgente",
                ],
                events=["luna_discipline"],
                cooldown=25,
            ),
            "social": TensionAxis(
                name="social",
                growth_rate=0.018,
                decay_rate=0.12,
                foreshadow_at=0.4,
                buildup_at=0.6,
                threshold=0.75,
                foreshadow_hints=[
                    "Noti sguardi curiosi da parte degli studenti",
                    "Qualcuno mormora qualcosa al tuo passaggio",
                ],
                buildup_hints=[
                    "Il gossip sulla tua vicinanza con lei si sta diffondendo",
                    "Stella ti lancia un'occhiata carica di significato",
                ],
                events=["stella_entourage"],
            ),
            "routine_break": TensionAxis(
                name="routine_break",
                growth_rate=0.03,
                decay_rate=0.3,
                foreshadow_at=0.5,
                buildup_at=0.7,
                threshold=0.85,
                foreshadow_hints=[
                    "La giornata sembra scorrere come tutte le altre",
                    "Senti il bisogno che succeda qualcosa",
                ],
                buildup_hints=[
                    "Un rumore insolito dal corridoio",
                    "Qualcuno bussa alla porta inaspettatamente",
                ],
                events=["maria_cleaning"],
                cooldown=12,
            ),
        }

        for name, axis in defaults.items():
            self.add_axis(axis)

    # -------------------------------------------------------------------------
    # GM Agenda support
    # -------------------------------------------------------------------------

    def get_compass_data(self, default_climate: str = "") -> dict:
        """Return data snapshot for the Narrative Compass UI and GM Agenda.

        Returns a dict with:
            active_axis:   name of the hottest tension axis (or None)
            tension_phase: phase string of the hottest axis
            tension_level: float 0.0–1.0 of the hottest axis
            climate_text:  hint string for the climate whisper (may be empty)
            climate_ttl:   suggested UI refresh interval in turns (3 when hint found, 0 otherwise)
            hint_source:   "buildup" | "foreshadow" | "default" | "none"

        Args:
            default_climate: Fallback whisper from world YAML (gm_agenda.default_climate).
                             Used when the tracker has no axis hints.
        """
        _empty = {
            "active_axis": None,
            "tension_phase": "calm",
            "tension_level": 0.0,
            "climate_text": default_climate,
            "climate_ttl": 3 if default_climate else 0,
            "hint_source": "default" if default_climate else "none",
        }
        if not self.axes:
            return _empty

        hottest = max(self.axes.values(), key=lambda a: a.level)

        # Pick climate hint deterministically (no random.choice — stable across turns)
        climate = ""
        hint_source = "none"
        if hottest.level >= hottest.buildup_at and hottest.buildup_hints:
            climate = hottest.buildup_hints[0]
            hint_source = "buildup"
        elif hottest.level >= hottest.foreshadow_at and hottest.foreshadow_hints:
            climate = hottest.foreshadow_hints[0]
            hint_source = "foreshadow"

        # Fall back to world YAML default when tracker has no hints
        if not climate and default_climate:
            climate = default_climate
            hint_source = "default"

        return {
            "active_axis": hottest.name,
            "tension_phase": hottest.phase,
            "tension_level": hottest.level,
            "climate_text": climate,
            "climate_ttl": 3 if climate else 0,
            "hint_source": hint_source,
        }

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            name: {
                "level": axis.level,
                "last_triggered_turn": axis.last_triggered_turn,
                "hint_cooldown": axis.hint_cooldown,
            }
            for name, axis in self.axes.items()
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        for name, saved in data.items():
            axis = self.axes.get(name)
            if axis:
                axis.level = saved.get("level", 0.0)
                axis.last_triggered_turn = saved.get("last_triggered_turn", -99)
                axis.hint_cooldown = saved.get("hint_cooldown", 0)
