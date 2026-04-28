"""HomeGuestManager — companion ospitate a casa del giocatore senza TTL."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HOME_LOCATION = "player_home"

HOME_INVITE_PATTERNS = [
    r"\bvieni a casa\b",
    r"\bvieni da me\b",
    r"\bvieni a casa mia\b",
    r"\bpassa a casa\b",
    r"\bti aspetto a casa\b",
    r"\bfermati da me\b",
    r"\brimani da me\b",
    r"\bstai da me\b",
    r"\bdormi da me\b",
    r"\bvieni a dormire\b",
]

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
    npc_name: str
    arrived_turn: int
    is_active: bool = True

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
    """Companion ospitate a casa — restano finché non congedate, nessun TTL."""

    FLAG_KEY = "_home_guests"

    def __init__(self, world: Any) -> None:
        self.world = world
        self._guests: Dict[str, HomeGuest] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def invite(self, npc_name: str, current_turn: int) -> bool:
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
        guest = self._guests.get(npc_name)
        if guest and guest.is_active:
            guest.is_active = False
            logger.info("[HomeGuest] %s congedata", npc_name)
            return True
        return False

    def dismiss_all(self) -> None:
        for guest in self._guests.values():
            guest.is_active = False
        logger.info("[HomeGuest] Tutte le companion congedate")

    def get_active_guests(self) -> List[str]:
        return [g.npc_name for g in self._guests.values() if g.is_active]

    def is_guest(self, npc_name: str) -> bool:
        g = self._guests.get(npc_name)
        return g is not None and g.is_active

    def has_guests(self) -> bool:
        return any(g.is_active for g in self._guests.values())

    # ── Intent detection ───────────────────────────────────────────────────────

    def detect_invite_intent(self, user_input: str, npc_name: str) -> bool:
        text = user_input.lower()
        has_invite = any(re.search(p, text) for p in HOME_INVITE_PATTERNS)
        if not has_invite:
            return False
        npc_lower = npc_name.lower()
        all_companions = [c.lower() for c in (self.world.companions.keys() if self.world else [])]
        other_mentioned = any(c in text for c in all_companions if c != npc_lower)
        return not other_mentioned or npc_lower in text

    def detect_invite_multiple(self, user_input: str) -> List[str]:
        text = user_input.lower()
        if not any(re.search(p, text) for p in HOME_INVITE_PATTERNS):
            return []
        if re.search(r"\btutte\b|\bentrambe\b|\btutti\b", text):
            if self.world:
                return list(self.world.companions.keys())
        mentioned = []
        if self.world:
            for name in self.world.companions.keys():
                if name.lower() in text:
                    mentioned.append(name)
        return mentioned

    def detect_dismiss_intent(self, user_input: str) -> bool:
        text = user_input.lower()
        return any(re.search(p, text) for p in DISMISS_PATTERNS)

    # ── Persistence ────────────────────────────────────────────────────────────

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
