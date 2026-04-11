"""Luna RPG V5 - M3: Phase Clock (deterministic time/phase state machine).

Single owner of time advancement. Invariants:
- Only PhaseClock can advance time/phase.
- No double advancement in one turn.
- freeze=True suspends phase ticks but not turn count.
- Manual freeze never auto-unfreezes (only explicit unfreeze).
- Auto-freeze (for important scenes) auto-unfreezes after N turns.

Phase cycle: Morning → Afternoon → Evening → Night → Morning
Ticks per phase: configurable (default 8 turns).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

from luna.core.models import TimeOfDay

logger = logging.getLogger(__name__)


class PhaseAdvanceReason(str, Enum):
    TICK = "tick"              # normal phase tick
    REST = "rest"              # player issued rest command
    FORCED = "forced"          # external force (quest, story beat)


_PHASE_ORDER = [
    TimeOfDay.MORNING,
    TimeOfDay.AFTERNOON,
    TimeOfDay.EVENING,
    TimeOfDay.NIGHT,
]

_PHASE_MESSAGES = {
    TimeOfDay.MORNING:   "☀️ Una nuova alba... è mattino.",
    TimeOfDay.AFTERNOON: "🌅 Il sole sale più alto... è pomeriggio.",
    TimeOfDay.EVENING:   "🌆 Il cielo si tinge d'arancione... è sera.",
    TimeOfDay.NIGHT:     "🌙 Cala la notte...",
}


@dataclass
class PhaseChangeEvent:
    old_phase: TimeOfDay
    new_phase: TimeOfDay
    reason: PhaseAdvanceReason
    message: str
    turn_number: int


@dataclass
class PhaseClockConfig:
    turns_per_phase: int = 8
    auto_freeze_max_turns: int = 3   # auto-freeze auto-unfreezes after this many turns


class PhaseClock:
    """Deterministic time/phase state machine.

    Owns all time advancement. No other system may change time_of_day
    directly on GameState without going through PhaseClock.

    Lifecycle per turn:
        1. Call tick(turn_number) once per turn.
        2. Check returned PhaseChangeEvent (None = no change).
        3. If freeze → no tick (turns_in_phase stays still).
    """

    def __init__(
        self,
        current_phase: TimeOfDay,
        config: Optional[PhaseClockConfig] = None,
        on_phase_change: Optional[Callable[[PhaseChangeEvent], None]] = None,
        manual_mode: bool = False,
    ) -> None:
        self._phase = current_phase
        self._config = config or PhaseClockConfig()
        self._on_phase_change = on_phase_change

        # If True, tick() is always a no-op — phase advances only via force_advance()
        self.manual_mode: bool = manual_mode

        self._turns_in_phase: int = 0
        self._frozen: bool = False
        self._freeze_reason: str = ""
        self._frozen_turns: int = 0
        self._is_manual_freeze: bool = False

        # Guard: ensure tick() is called at most once per turn
        self._last_ticked_turn: int = -1

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def current_phase(self) -> TimeOfDay:
        return self._phase

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    @property
    def turns_in_phase(self) -> int:
        return self._turns_in_phase

    @property
    def turns_until_next_phase(self) -> int:
        if self._frozen:
            return -1
        return self._config.turns_per_phase - self._turns_in_phase

    def _next_phase(self) -> "TimeOfDay":
        """Return the phase that comes after the current one."""
        idx = _PHASE_ORDER.index(self._phase)
        return _PHASE_ORDER[(idx + 1) % len(_PHASE_ORDER)]

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def tick(self, turn_number: int) -> Optional[PhaseChangeEvent]:
        """Advance one turn. Returns PhaseChangeEvent if phase changed, else None.

        Safety: calling tick() twice for the same turn is a no-op.
        Returns None immediately when manual_mode=True (use force_advance instead).
        """
        if self.manual_mode:
            return None

        if turn_number == self._last_ticked_turn:
            logger.warning("PhaseClock.tick() called twice for turn %d — ignored", turn_number)
            return None
        self._last_ticked_turn = turn_number

        if self._frozen:
            self._frozen_turns += 1
            # Auto-unfreeze if not manual and exceeded max
            if not self._is_manual_freeze and self._frozen_turns >= self._config.auto_freeze_max_turns:
                self.unfreeze()
                logger.debug("Auto-unfreeze after %d frozen turns", self._frozen_turns)
            return None

        self._turns_in_phase += 1
        if self._turns_in_phase >= self._config.turns_per_phase:
            return self._advance_phase(PhaseAdvanceReason.TICK, turn_number)
        return None

    def force_advance(self, reason: PhaseAdvanceReason, turn_number: int) -> PhaseChangeEvent:
        """Force immediate phase advance (rest command, quest trigger, etc.)."""
        self._turns_in_phase = 0
        if self._frozen:
            self.unfreeze()
        return self._advance_phase(reason, turn_number)

    def freeze(self, reason: str = "", manual: bool = False) -> None:
        """Freeze phase ticking."""
        if self._frozen:
            return
        self._frozen = True
        self._freeze_reason = reason
        self._frozen_turns = 0
        self._is_manual_freeze = manual
        logger.debug("PhaseClock frozen: %s (manual=%s)", reason, manual)

    def unfreeze(self) -> None:
        """Unfreeze phase ticking."""
        self._frozen = False
        self._freeze_reason = ""
        self._frozen_turns = 0
        self._is_manual_freeze = False
        logger.debug("PhaseClock unfrozen")

    def reset_phase_counter(self) -> None:
        """Reset turns_in_phase to 0 (e.g., after a forced time change)."""
        self._turns_in_phase = 0

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "phase": self._phase.value,
            "turns_in_phase": self._turns_in_phase,
            "frozen": self._frozen,
            "freeze_reason": self._freeze_reason,
            "frozen_turns": self._frozen_turns,
            "is_manual_freeze": self._is_manual_freeze,
            "manual_mode": self.manual_mode,
        }

    def from_dict(self, data: dict) -> None:
        try:
            self._phase = TimeOfDay(data["phase"])
        except (KeyError, ValueError):
            pass
        self._turns_in_phase = data.get("turns_in_phase", 0)
        self._frozen = data.get("frozen", False)
        self._freeze_reason = data.get("freeze_reason", "")
        self._frozen_turns = data.get("frozen_turns", 0)
        self._is_manual_freeze = data.get("is_manual_freeze", False)
        self.manual_mode = data.get("manual_mode", False)

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _advance_phase(self, reason: PhaseAdvanceReason, turn_number: int) -> PhaseChangeEvent:
        old_phase = self._phase
        idx = _PHASE_ORDER.index(self._phase)
        self._phase = _PHASE_ORDER[(idx + 1) % len(_PHASE_ORDER)]
        self._turns_in_phase = 0

        event = PhaseChangeEvent(
            old_phase=old_phase,
            new_phase=self._phase,
            reason=reason,
            message=_PHASE_MESSAGES[self._phase],
            turn_number=turn_number,
        )
        logger.info(
            "Phase: %s → %s (reason=%s, turn=%d)",
            old_phase.value, self._phase.value, reason.value, turn_number,
        )
        if self._on_phase_change:
            try:
                self._on_phase_change(event)
            except Exception as e:
                logger.error("on_phase_change callback failed: %s", e)
        return event
