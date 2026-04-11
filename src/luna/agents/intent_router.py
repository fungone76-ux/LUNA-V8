"""Luna RPG v6 - Intent Router Agent.

Analyzes player input and classifies the intent.
Deterministic (regex-based) for speed — no LLM call needed.
Only ambiguous cases would need LLM, but in practice regex is sufficient.

Intent priority (highest first):
1. MOVEMENT       - "vado in", "mi sposto", "entro in"
2. FAREWELL       - "arrivederci", "ciao", "vado via"
3. REST           - "dormo", "riposo", "vado a letto"
4. FREEZE/UNFREEZE - "/freeze", "/unfreeze"
5. SCHEDULE_QUERY  - "dove si trova", "dov'è"
6. REMOTE_COMM    - "scrivo a", "chiamo", "messaggio a"
7. INVITATION     - "vieni a casa", "ti invito"
8. SUMMON         - "vieni qui", "avvicinati"
9. INTIMATE_SCENE - romantic/physical trigger words
10. OUTFIT_MAJOR  - "mettiti", "cambiate vestiti"
11. EVENT_CHOICE  - numeric choice during events
12. STANDARD      - everything else → LLM dialogue
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from luna.core.models import GameState, IntentBundle, IntentType, WorldDefinition

logger = logging.getLogger(__name__)


# =============================================================================
# Pattern definitions
# =============================================================================

_MOVEMENT_PATTERNS = [
    r"\b(vado|vai|andiamo|andate|mi\s+sposto|mi\s+dirigo|entro|usciamo?)\s+(in|a|al|alla|nel|nella|verso|da|dal|dalla)\b",
    r"\b(torno|ritorno)\s+(in|a|al|alla|nel|nella|verso|da)\b",
    r"\btrasferisco\s+a\b",
]

_FAREWELL_PATTERNS = [
    r"\b(arrivederci|addio|ciao\s+ciao|ci\s+vediamo|a\s+dopo|a\s+presto)\b",
    r"\b(vado\s+via|me\s+ne\s+vado|devo\s+andare|devo\s+scappare)\b",
    r"\b(lasciami|lasciala?|lasciatemi)\s+(solo|sola|in\s+pace)\b",
    r"\bcongedami\b",
]

_REST_PATTERNS = [
    r"\b(dormo|dormiamo|vado\s+a\s+dormire|vado\s+a\s+letto)\b",
    r"\b(riposo|mi\s+riposo|facciamo\s+un\s+pisolino)\b",
    r"\b(aspetta\s+domani|skip|salta\s+il\s+tempo)\b",
]

_FREEZE_PATTERNS = [
    r"^/freeze\b",
    r"^/unfreeze\b",
    r"\bferma\s+il\s+tempo\b",
    r"\bsblocca\s+il\s+tempo\b",
]

_SCHEDULE_PATTERNS = [
    r"\bdov[eè]\s+(si\s+trova|è)\s+(\w+)",
    r"\b(dove|dov)\s+(sta|sono)\s+(\w+)",
    r"\b(dove\s+posso\s+trovare)\b",
]

_REMOTE_COMM_PATTERNS = [
    r"\b(scrivo|mando\s+un?\s+messaggio|invio\s+un?\s+messaggio)\s+a\b",
    r"\b(chiamo|telefono|mando\s+un\s+sms)\s+a\b",
    r"\b(contatto|contatta)\s+\w+\b",
]

_INVITATION_PATTERNS = [
    r"\b(vieni|viene)\s+(a\s+casa\s+(mia|nostra)|da\s+me|stasera|questa\s+sera)\b",
    r"\bti\s+invito\b",
    r"\binvita\s+\w+\b",
    r"\bpassare\s+da\s+me\b",
]

_SUMMON_PATTERNS = [
    r"\b(vieni\s+qui|avvicinati|siediti\s+qui|stai\s+con\s+me)\b",
    r"\b(vieni\s+con\s+me|seguimi|resta\s+con\s+me)\b",
]

_INTIMATE_TRIGGERS = {
    "intense": [
        r"\b(trema|gemi|muori\s+di\s+piacere|grida|urla\s+il\s+mio\s+nome)\b",
        r"\b(vieni|orgasmo|eccitati)\b",
        r"\b(toccami|prendimi|baciami\s+ancora)\b",
    ],
    "moderate": [
        r"\b(ansima|respira\s+affannosamente|sospira\s+il\s+mio\s+nome)\b",
        r"\b(accarezzami|stringimi|abbracciami\s+forte)\b",
        r"\b(ti\s+desidero|ti\s+voglio|mi\s+manchi)\b",
    ],
    "mild": [
        r"\b(sorride\s+intensamente|tocca\s+la\s+mia|accarezza)\b",
        r"\b(baciami|un\s+bacio|stai\s+vicina?\s+a\s+me)\b",
        r"\b(ti\s+piaccio|mi\s+piaci|sei\s+bella)\b",
    ],
}

_OUTFIT_MAJOR_PATTERNS = [
    r"\b(mettiti|indossa|cambiati|cambiate)\s+\w+",
    r"\b(togli|togliti)\s+(tutto|i\s+vestiti|il\s+vestito)\b",
    r"\b(nuda|spogliati|svestiti)\b",
]

_EVENT_CHOICE_PATTERN = re.compile(r"^\s*([1-9])\s*$")

_POKER_KEYWORDS = [
    "poker",
    "giochiamo a poker",
    "partita a poker",
    "gioco a carte",
    "giochiamo a carte",
    "scommettiamo",
    "facciamo una partita",
    "strip poker",
]


# =============================================================================
# Intent Router
# =============================================================================

class IntentRouter:
    """Classifies player input into an IntentBundle.

    Fully deterministic — no LLM call.
    Fast enough to run every turn without overhead.
    """

    def __init__(self, world: WorldDefinition) -> None:
        self.world = world
        # Pre-compile all patterns
        self._movement_re  = [re.compile(p, re.IGNORECASE) for p in _MOVEMENT_PATTERNS]
        self._farewell_re  = [re.compile(p, re.IGNORECASE) for p in _FAREWELL_PATTERNS]
        self._rest_re      = [re.compile(p, re.IGNORECASE) for p in _REST_PATTERNS]
        self._freeze_re    = [re.compile(p, re.IGNORECASE) for p in _FREEZE_PATTERNS]
        self._schedule_re  = [re.compile(p, re.IGNORECASE) for p in _SCHEDULE_PATTERNS]
        self._remote_re    = [re.compile(p, re.IGNORECASE) for p in _REMOTE_COMM_PATTERNS]
        self._invitation_re = [re.compile(p, re.IGNORECASE) for p in _INVITATION_PATTERNS]
        self._summon_re    = [re.compile(p, re.IGNORECASE) for p in _SUMMON_PATTERNS]
        self._outfit_re    = [re.compile(p, re.IGNORECASE) for p in _OUTFIT_MAJOR_PATTERNS]
        self._intimate_re  = {
            lvl: [re.compile(p, re.IGNORECASE) for p in patterns]
            for lvl, patterns in _INTIMATE_TRIGGERS.items()
        }

    def analyze(
        self,
        text: str,
        game_state: GameState,
        has_pending_event: bool = False,
    ) -> IntentBundle:
        """Analyze input and return classified IntentBundle."""
        lower = text.lower().strip()
        bundle = IntentBundle(raw_input=text)

        # --- Event choice (only if event active) ---
        if has_pending_event:
            m = _EVENT_CHOICE_PATTERN.match(lower)
            if m:
                bundle.primary = IntentType.EVENT_CHOICE
                bundle.event_choice_index = int(m.group(1)) - 1
                return bundle

        # --- Movement ---
        if any(r.search(lower) for r in self._movement_re):
            target = self._extract_location(lower, game_state)
            if target:
                bundle.primary         = IntentType.MOVEMENT
                bundle.target_location = target
                bundle.movement_text   = text
                return bundle

        # --- Farewell ---
        if any(r.search(lower) for r in self._farewell_re):
            # Only treat as farewell if it's a short direct message
            # Long roleplay texts may contain farewell words in-character
            word_count = len(lower.split())
            has_roleplay = lower.startswith("*") or lower.startswith('"') or word_count > 20
            if not has_roleplay:
                bundle.primary = IntentType.FAREWELL
            return bundle

        # --- Rest ---
        if any(r.search(lower) for r in self._rest_re):
            bundle.primary = IntentType.REST
            return bundle

        # --- Freeze / Unfreeze ---
        for r in self._freeze_re:
            m = r.search(lower)
            if m:
                bundle.primary = IntentType.FREEZE
                bundle.freeze_action = "unfreeze" if "unfreeze" in lower or "sblocca" in lower else "freeze"
                return bundle

        # --- Schedule query ---
        if any(r.search(lower) for r in self._schedule_re):
            npc = self._extract_npc_name(lower, game_state)
            if npc:
                bundle.primary    = IntentType.SCHEDULE_QUERY
                bundle.target_npc = npc
                return bundle

        # --- Remote communication ---
        if any(r.search(lower) for r in self._remote_re):
            npc = self._extract_npc_name(lower, game_state)
            if npc:
                bundle.primary    = IntentType.REMOTE_COMM
                bundle.target_npc = npc
                bundle.comm_type  = "call" if re.search(r"\b(chiamo|telefono)\b", lower) else "message"
                return bundle

        # --- Invitation ---
        if any(r.search(lower) for r in self._invitation_re):
            npc = self._extract_npc_name(lower, game_state)
            bundle.primary       = IntentType.INVITATION
            bundle.target_npc    = npc or game_state.active_companion
            bundle.arrival_time  = self._extract_arrival_time(lower)
            bundle.target_location = game_state.current_location
            return bundle

        # --- Summon ---
        if any(r.search(lower) for r in self._summon_re):
            npc = self._extract_npc_name(lower, game_state)
            if npc and npc != game_state.active_companion:
                bundle.primary    = IntentType.SUMMON
                bundle.target_npc = npc
                return bundle

        # --- Intimate scene ---
        intensity = self._detect_intimate(lower)
        if intensity:
            bundle.primary            = IntentType.INTIMATE_SCENE
            bundle.intimate_intensity = intensity
            return bundle

        # --- Major outfit change ---
        if any(r.search(lower) for r in self._outfit_re):
            bundle.primary            = IntentType.OUTFIT_MAJOR
            bundle.outfit_description = text
            return bundle

        # --- Poker game ---
        # If a poker game is already active, ALL input goes to the poker engine
        # (fold/call/check/raise etc. don't contain the keyword "poker")
        if game_state.flags.get("poker_active"):
            logger.info("[IntentRouter] Detected: POKER_GAME (active session)")
            bundle.primary = IntentType.POKER_GAME
            return bundle
        if any(kw in lower for kw in _POKER_KEYWORDS):
            logger.info("[IntentRouter] Detected: POKER_GAME")
            bundle.primary = IntentType.POKER_GAME
            return bundle

        # --- Standard dialogue ---
        bundle.primary = IntentType.STANDARD
        return bundle

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _extract_location(self, text: str, game_state: GameState) -> Optional[str]:
        """Try to identify a location ID from the input."""
        for loc_id, loc_def in self.world.locations.items():
            if loc_id == game_state.current_location:
                continue
            # Check name and aliases
            names_to_check = [loc_def.name.lower()] + [a.lower() for a in loc_def.aliases]
            if any(name in text for name in names_to_check):
                return loc_id
        return None

    def _extract_npc_name(self, text: str, game_state: GameState) -> Optional[str]:
        """Try to identify an NPC name from the input."""
        for npc_name, companion in self.world.companions.items():
            aliases = [npc_name.lower()] + [a.lower() for a in companion.aliases]
            if any(alias in text for alias in aliases):
                return npc_name
        return None

    def _extract_arrival_time(self, text: str) -> str:
        """Extract when an NPC should arrive."""
        if re.search(r"\b(stasera|questa\s+sera|sera)\b", text, re.IGNORECASE):
            return "Evening"
        if re.search(r"\b(domani\s+mattina|mattina)\b", text, re.IGNORECASE):
            return "Morning"
        if re.search(r"\b(pomeriggio)\b", text, re.IGNORECASE):
            return "Afternoon"
        if re.search(r"\b(notte|mezzanotte)\b", text, re.IGNORECASE):
            return "Night"
        return "Evening"  # default

    def _detect_intimate(self, text: str) -> Optional[str]:
        """Detect intimate scene trigger and return intensity level."""
        for intensity in ("intense", "moderate", "mild"):
            if any(r.search(text) for r in self._intimate_re[intensity]):
                return intensity
        return None
