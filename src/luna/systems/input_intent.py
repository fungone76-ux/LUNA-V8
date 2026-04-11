"""Luna RPG V5 - M1: Unified Input Intent Layer.

Single entry point for all input analysis.
Produces one InputIntentBundle per turn - no scattered if/else chains.

Intent priority (deterministic, no conflicts):
1. DYNAMIC_EVENT_CHOICE  - answering a pending event
2. MOVEMENT              - player wants to go somewhere
3. FAREWELL              - dismissing active companion
4. REST                  - sleep/rest command (advances time)
5. FREEZE                - debug freeze/unfreeze turns
6. SCHEDULE_QUERY        - asking where an NPC is
7. REMOTE_COMM           - phone/message/call an NPC
8. INVITATION            - invite NPC to a location
9. SUMMON                - call NPC to current location
10. INTIMATE_SCENE       - romantic/physical scene triggers
11. OUTFIT_MAJOR         - change to a completely new outfit
12. OUTFIT_OVERLAY       - partial modification (remove shoes, etc.)
13. POSE_HINT            - camera/pose direction in input
14. STANDARD             - normal conversational turn
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

from luna.core.models import GameState, WorldDefinition


class IntentType(str, Enum):
    DYNAMIC_EVENT_CHOICE = "dynamic_event_choice"
    MOVEMENT = "movement"
    FAREWELL = "farewell"
    REST = "rest"
    FREEZE = "freeze"
    SCHEDULE_QUERY = "schedule_query"
    REMOTE_COMM = "remote_comm"
    INVITATION = "invitation"
    SUMMON = "summon"
    INTIMATE_SCENE = "intimate_scene"
    OUTFIT_MAJOR = "outfit_major"
    OUTFIT_OVERLAY = "outfit_overlay"
    POSE_HINT = "pose_hint"
    STANDARD = "standard"


@dataclass
class MovementIntent:
    target_raw: str           # raw text player used ("vado in bagno")
    target_location_id: Optional[str] = None   # resolved location id


@dataclass
class RemoteCommIntent:
    target_npc: str
    comm_type: str = "message"   # message | call


@dataclass
class InvitationIntent:
    target_npc: str
    arrival_time: str       # morning | afternoon | evening | night
    target_location: str    # location id


@dataclass
class SummonIntent:
    target_npc: str


@dataclass
class IntimateSceneIntent:
    """Intimate/romantic scene detected.
    
    Triggers time freeze and keeps companion close.
    """
    trigger_words: List[str]  # Words that triggered this intent
    intensity: str = "mild"   # mild | moderate | intense


@dataclass
class OutfitOverlayIntent:
    """Partial outfit change: remove shoes, lift skirt, etc."""
    component: str
    state: str      # removed | wet | lifted | torn | partial_unbuttoned | lowered | added
    raw_text: str


@dataclass
class OutfitMajorIntent:
    """Switch to a completely different outfit."""
    description: str    # Italian description of requested outfit


@dataclass
class PoseHint:
    composition: Optional[str] = None    # close_up | medium_shot | wide_shot
    body_focus: Optional[str] = None


@dataclass
class InputIntentBundle:
    """Single DTO produced from one user input.

    One input → one bundle → no conflicts.
    Priority field indicates which intent was selected when multiple matched.
    """
    raw_input: str
    primary: IntentType = IntentType.STANDARD

    # Populated only when relevant intent is active
    movement: Optional[MovementIntent] = None
    remote_comm: Optional[RemoteCommIntent] = None
    invitation: Optional[InvitationIntent] = None
    summon: Optional[SummonIntent] = None
    intimate_scene: Optional[IntimateSceneIntent] = None
    outfit_overlay: Optional[OutfitOverlayIntent] = None
    outfit_major: Optional[OutfitMajorIntent] = None
    pose_hint: Optional[PoseHint] = None
    event_choice_index: Optional[int] = None   # 1-based choice number
    schedule_query_npc: Optional[str] = None
    rest_message: Optional[str] = None          # message to show when time advances
    freeze_action: Optional[str] = None         # "freeze" | "unfreeze"

    # Secondary intents that can coexist with primary
    # e.g. a STANDARD turn can still have pose_hint or outfit_overlay
    secondary: List[IntentType] = field(default_factory=list)


# =============================================================================
# Patterns
# =============================================================================

_MOVEMENT_PATTERNS = [
    r"\bvado\s+", r"\bvai\s+", r"\bandiamo\s+", r"\bmuoviti\s+",
    r"\bentra\s+", r"\bentriamo\s+", r"\bentro\s+",
    r"\besco\s+", r"\besci\s+", r"\busciamo\s+", r"\buscire\s+",
    r"\braggiungi\s+", r"\braggiungiamo\s+", r"\braggiungo\s+",
    r"\btorniamo\s+", r"\btorna\s+", r"\btorno\s+",
    r"\bandare\s+", r"\bentrare\s+", r"\braggiungere\s+", r"\btornare\s+",
    r"\bandrei\s+", r"\bentrerei\s+",
]

_QUESTION_PATTERNS = [
    r"^\s*posso\s", r"^\s*possiamo\s", r"\?$",
    r"\bmi\s+(consenti|lasci|permetti)\b",
]

_REST_PATTERNS = [
    r"\bdormo\b", r"\bdormire\b", r"\bvado\s+a\s+dormire\b",
    r"\bfinisco\s+la\s+giornata\b", r"\bvado\s+a\s+casa\b",
    r"\bmi\s+riposo\b", r"\briposo\b", r"\ba\s+letto\b",
    r"\bbuonanotte\b",
]

_FREEZE_PATTERNS = {
    "freeze": [r"\bfreeze\b", r"\bblocca\s+il\s+tempo\b"],
    "unfreeze": [r"\bunfreeze\b", r"\bsblocca\s+il\s+tempo\b", r"\briprendi\b"],
}

_SCHEDULE_PATTERNS = [
    r"\bdov[eè]\s+([A-ZÀ-Ÿ][a-zà-ÿ]+)\b",
    r"\broutine\s+di\s+([A-ZÀ-Ÿ][a-zà-ÿ]+)\b",
    r"\bordine\s+del\s+giorno\s+di\s+([A-ZÀ-Ÿ][a-zà-ÿ]+)\b",
]

_REMOTE_COMM_PATTERNS = [
    (r"\bscrivo\s+a\b", "message"),
    (r"\bmando\s+un\s+messaggio\b", "message"),
    (r"\bmando\s+un\s+sms\b", "message"),
    (r"\bchatto\s+con\b", "message"),
    (r"\bwhatsapp\s+a\b", "message"),
    (r"\btelefono\s+a\b", "call"),
    (r"\bchiamo\b", "call"),
    (r"\bfaccio\s+una\s+chiamata\b", "call"),
]

_INVITATION_TIME_PATTERNS = {
    "morning": [r"\bmattina\b", r"\bstamattina\b"],
    "afternoon": [r"\bpomeriggio\b"],
    "evening": [r"\bsera\b", r"\bstasera\b", r"\bquesta\s+sera\b"],
    "night": [r"\bnotte\b", r"\bstanotte\b"],
}

_INVITATION_LOCATION_PATTERNS: Dict[str, List[str]] = {
    "player_home": [r"\ba\s+casa\b", r"\bcasa\s+mia\b", r"\bda\s+me\b"],
    "bar": [r"\bal\s+bar\b", r"\bpub\b"],
    "gym": [r"\bin\s+palestra\b", r"\balla\s+palestra\b"],
    "park": [r"\bal\s+parco\b", r"\bin\s+parco\b"],
}

# Outfit overlay patterns (Italian → component/state)
_OUTFIT_OVERLAY_PATTERNS = [
    # (regex_on_input, component, state)
    (r"\b(togli|togliti|si\s+toglie?|rimuovi)\s+(le\s+)?scarpe\b", "shoes", "removed"),
    (r"\b(togli|togliti|si\s+toglie?|rimuovi)\s+(le\s+)?calze\b", "pantyhose", "removed"),
    (r"\b(togli|togliti|si\s+toglie?|rimuovi)\s+(la\s+)?gonna\b", "bottom", "removed"),
    (r"\b(togli|togliti|si\s+toglie?|rimuovi)\s+(la\s+)?camicia\b", "top", "removed"),
    (r"\b(togli|togliti|si\s+toglie?|rimuovi)\s+(il\s+)?reggiseno\b", "bra", "removed"),
    (r"\bsollev[a-z]+\s+(la\s+)?gonna\b", "bottom", "lifted"),
    (r"\bgonna\s+sollevat[aoie]\b", "bottom", "lifted"),
    (r"\bsbotton[a-z]+\s+(la\s+)?camicia\b", "top", "partial_unbuttoned"),
    (r"\bcamicia\s+sbottonat[aoie]\b", "top", "partial_unbuttoned"),
    (r"\bbagnata?\b", "top", "wet"),
    (r"\bstrappat[aoie]\b.*calze\b|\bcalze\b.*strappat[aoie]\b", "pantyhose", "torn"),
    (r"\bcalze\s+strappate?\b", "pantyhose", "torn"),
]

_OUTFIT_MAJOR_TRIGGERS = [
    r"\bmettiti\b", r"\bindossa\b", r"\bcambia\s+(il\s+)?vestito\b",
    r"\bmetti\s+(il\s+|la\s+|un[ao]?\s+)", r"\bvestiti\s+(da|con)\b",
    r"\babbigliamento\b", r"\bpigiama\b", r"\bbikini\b", r"\bcostume\b",
    r"\blingerie\b", r"\bnuda?\b",
]

_POSE_PATTERNS = {
    "close_up": [r"\bprimo\s+piano\b", r"\bclose.?up\b", r"\bviso\b"],
    "wide_shot": [r"\bcampo\s+largo\b", r"\bwide\s+shot\b", r"\bintero\b"],
    "medium_shot": [r"\bmezzo\s+busto\b", r"\bmedium\s+shot\b"],
    "from_below": [r"\bdal\s+basso\b", r"\bfrom\s+below\b"],
    "from_above": [r"\bdall'alto\b", r"\bfrom\s+above\b"],
}

# Intimate scene triggers - physical sensations, moans, breathing, etc.
_INTIMATE_SCENE_TRIGGERS = {
    "intense": [
        r"\btrema\b", r"\btremi\b", r"\btremando\b", r"\btrema\b",
        r"\bgemi\b", r"\bgemo\b", r"\bgemiamo\b", r"\bgemen\b",
        r"\bmuore\s+(dal|di)\b", r"\bmuor[ai]\b",
        r"\bgemiti\b", r"\bgr[ai]di\b", r"\bgrida\b",
        r"\bsucc[ui]mb\b", r"\bsoccomb\b",
        r"\bimpazz[ai]\b", r"\bimpazzo\b",
        r"\bperdut[ao]\b.*s[e\xc3\xa9]", r"\bperdim\b",
    ],
    "moderate": [
        r"\bansim[a-z]*\b", r"\bansimar\b", r"\bansim\b",
        r"\brespir[a-z]*\b", r"\bfar[le]\s+fatica\b",
        r"\bsospir[a-z]*\b", r"\bsospir\b",
        r"\bmormor[a-z]*\b", r"\bmormora\b",
        r"\bsusurr[a-z]*\b", r"\bsussurra\b",
        r"\barcigna\b", r"\barcigno\b",
        r"\bpiegh[a-z]*\b", r"\bpiegat[ao]\b",
        r"\barcan[a-z]*\b", r"\barcano\b",
        r"\bsensibil\b", r"\bsensazion\b",
    ],
    "mild": [
        r"\bsorride\b", r"\bsorrida\b", r"\bsorridi\b",
        r"\btocc[a-z]*\b.*pelle\b|\bpelle\b.*tocc",
        r"\baccarezza\b", r"\baccarezz[a-z]*\b",
        r"\bbaciami\b", r"\bbaciam\b", r"\bbacio\b",
        r"\bsguard[a-z]*\b.*intens\b|\bintens\b.*sguard",
        r"\blabbra\b", r"\blabbr[a-z]*\b",
        r"\binfuoca\b", r"\binfuocat[ao]\b",
    ],
}


# =============================================================================
# Intent Analyzer
# =============================================================================

class InputIntentAnalyzer:
    """Analyzes user input and produces a single InputIntentBundle.

    Stateless: all context passed via parameters.
    """

    def __init__(self, world: WorldDefinition) -> None:
        self.world = world
        # Build alias map: alias_lower → companion_name
        self._alias_map: Dict[str, str] = {}
        for name, comp in world.companions.items():
            self._alias_map[name.lower()] = name
            for alias in comp.aliases:
                self._alias_map[alias.lower()] = name

    def analyze(
        self,
        user_input: str,
        game_state: GameState,
        has_pending_event: bool = False,
        in_remote_communication: bool = False,
    ) -> InputIntentBundle:
        """Analyze input and return a bundle with exactly one primary intent."""
        text = user_input.strip()
        lower = text.lower()
        bundle = InputIntentBundle(raw_input=text)

        # --- Priority 1: Pending event choice ---
        if has_pending_event:
            idx = self._parse_event_choice(lower)
            if idx is not None:
                bundle.primary = IntentType.DYNAMIC_EVENT_CHOICE
                bundle.event_choice_index = idx
                return bundle

        # --- Priority 2: Movement ---
        if not in_remote_communication:
            movement = self._detect_movement(lower)
            if movement:
                bundle.primary = IntentType.MOVEMENT
                bundle.movement = movement
                # Still check overlay/pose as secondary
                self._add_secondary_intents(bundle, lower)
                return bundle

        # --- Priority 3: Farewell (companion dismissal) ---
        if self._is_farewell(lower, game_state.active_companion):
            bundle.primary = IntentType.FAREWELL
            return bundle

        # --- Priority 4: Rest ---
        rest_msg = self._detect_rest(lower)
        if rest_msg:
            bundle.primary = IntentType.REST
            bundle.rest_message = rest_msg
            return bundle

        # --- Priority 5: Freeze ---
        freeze = self._detect_freeze(lower)
        if freeze:
            bundle.primary = IntentType.FREEZE
            bundle.freeze_action = freeze
            return bundle

        # --- Priority 6: Schedule query ---
        npc = self._detect_schedule_query(lower)
        if npc:
            bundle.primary = IntentType.SCHEDULE_QUERY
            bundle.schedule_query_npc = npc
            return bundle

        # --- Priority 7: Remote communication ---
        remote = self._detect_remote_comm(lower)
        if remote and not in_remote_communication:
            bundle.primary = IntentType.REMOTE_COMM
            bundle.remote_comm = remote
            return bundle

        # --- Priority 8: Invitation ---
        invitation = self._detect_invitation(lower)
        if invitation:
            bundle.primary = IntentType.INVITATION
            bundle.invitation = invitation
            return bundle

        # --- Priority 9: Summon ---
        summon = self._detect_summon(lower, game_state)
        if summon:
            bundle.primary = IntentType.SUMMON
            bundle.summon = summon
            return bundle

        # --- Priority 10: Intimate scene (if active companion present) ---
        if game_state.active_companion and game_state.active_companion != "solo":
            intimate = self._detect_intimate_scene(lower)
            if intimate:
                bundle.primary = IntentType.INTIMATE_SCENE
                bundle.intimate_scene = intimate
                self._add_secondary_intents(bundle, lower, skip_outfit=True)
                return bundle

        # --- Priority 11: Outfit major ---
        major = self._detect_outfit_major(lower)
        if major:
            bundle.primary = IntentType.OUTFIT_MAJOR
            bundle.outfit_major = major
            self._add_secondary_intents(bundle, lower, skip_outfit=True)
            return bundle

        # --- Priority 12-14: Standard turn, with secondary intents ---
        bundle.primary = IntentType.STANDARD
        self._add_secondary_intents(bundle, lower)
        return bundle

    # -------------------------------------------------------------------------
    # Detection helpers
    # -------------------------------------------------------------------------

    def _parse_event_choice(self, lower: str) -> Optional[int]:
        """Return 1-based choice index or None."""
        patterns = [
            (r"\b(scelta|opzione|risposta)\s*[:#]?\s*([1-9])\b", 2),
            (r"\b([1-9])\b", 1),
            (r"\bprima\b", None),  # → 1
            (r"\bseconda\b", None),  # → 2
        ]
        if re.search(r"\bprima\b", lower):
            return 1
        if re.search(r"\bseconda\b", lower):
            return 2
        if re.search(r"\bterza\b", lower):
            return 3
        m = re.search(r"\b([1-9])\b", lower)
        if m:
            return int(m.group(1))
        return None

    def _detect_movement(self, lower: str) -> Optional[MovementIntent]:
        # Skip if it's a question
        for pat in _QUESTION_PATTERNS:
            if re.search(pat, lower):
                return None
        for pat in _MOVEMENT_PATTERNS:
            if re.search(pat, lower):
                return MovementIntent(target_raw=lower)
        return None

    def _is_farewell(self, lower: str, active_companion: str) -> bool:
        if active_companion in ("_solo_", "", None):
            return False
        farewell_words = [
            r"\barrivederci\b", r"\bciao\b(?!\s+come)", r"\baddio\b",
            r"\bci\s+vediamo\b", r"\bvattene\b", r"\bvai\s+pure\b",
        ]
        for pat in farewell_words:
            if re.search(pat, lower):
                # also check companion name is mentioned or it's general
                comp_lower = active_companion.lower()
                if comp_lower in lower or not any(
                    alias in lower for alias in self._alias_map if alias != comp_lower
                ):
                    return True
        return False

    def _detect_rest(self, lower: str) -> Optional[str]:
        for pat in _REST_PATTERNS:
            if re.search(pat, lower):
                return "💤 Decidi di riposare..."
        return None

    def _detect_freeze(self, lower: str) -> Optional[str]:
        for action, patterns in _FREEZE_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, lower):
                    return action
        return None

    def _detect_schedule_query(self, lower: str) -> Optional[str]:
        for pat in _SCHEDULE_PATTERNS:
            m = re.search(pat, lower, re.IGNORECASE)
            if m:
                name_raw = m.group(1)
                resolved = self._alias_map.get(name_raw.lower())
                if resolved:
                    return resolved
        return None

    def _detect_remote_comm(self, lower: str) -> Optional[RemoteCommIntent]:
        for pat, comm_type in _REMOTE_COMM_PATTERNS:
            if re.search(pat, lower):
                # Find which NPC is mentioned
                for alias, name in self._alias_map.items():
                    if alias in lower:
                        return RemoteCommIntent(target_npc=name, comm_type=comm_type)
        return None

    def _detect_invitation(self, lower: str) -> Optional[InvitationIntent]:
        # Must mention "invito" or "vieni" + time + location + NPC
        invite_triggers = [r"\binvito\b", r"\bvieni\b", r"\bpassare\b", r"\bpassi\b"]
        if not any(re.search(p, lower) for p in invite_triggers):
            return None
        target_npc = None
        for alias, name in self._alias_map.items():
            if alias in lower:
                target_npc = name
                break
        if not target_npc:
            return None
        arrival_time = "evening"  # default
        for time_key, patterns in _INVITATION_TIME_PATTERNS.items():
            if any(re.search(p, lower) for p in patterns):
                arrival_time = time_key
                break
        target_location = "player_home"  # default
        for loc_key, patterns in _INVITATION_LOCATION_PATTERNS.items():
            if any(re.search(p, lower) for p in patterns):
                target_location = loc_key
                break
        return InvitationIntent(
            target_npc=target_npc,
            arrival_time=arrival_time,
            target_location=target_location,
        )

    def _detect_summon(self, lower: str, game_state: GameState) -> Optional[SummonIntent]:
        summon_triggers = [r"\bchiama\b", r"\bvieni\s+qui\b", r"\bvieni\s+da\s+me\b", r"\bvieni\s+subito\b"]
        if not any(re.search(p, lower) for p in summon_triggers):
            return None
        for alias, name in self._alias_map.items():
            if alias in lower and name != game_state.active_companion:
                return SummonIntent(target_npc=name)
        return None

    def _detect_intimate_scene(self, lower: str) -> Optional[IntimateSceneIntent]:
        """Detect intimate/romantic scene triggers.
        
        Returns None if no triggers found.
        Returns IntimateSceneIntent with intensity level if triggers found.
        """
        matched_words: List[str] = []
        
        # Check intense triggers
        for pattern in _INTIMATE_SCENE_TRIGGERS["intense"]:
            if re.search(pattern, lower):
                matched_words.append(pattern)
        
        if matched_words:
            return IntimateSceneIntent(trigger_words=matched_words[:3], intensity="intense")
        
        # Check moderate triggers
        for pattern in _INTIMATE_SCENE_TRIGGERS["moderate"]:
            if re.search(pattern, lower):
                matched_words.append(pattern)
        
        if matched_words:
            return IntimateSceneIntent(trigger_words=matched_words[:3], intensity="moderate")
        
        # Check mild triggers
        for pattern in _INTIMATE_SCENE_TRIGGERS["mild"]:
            if re.search(pattern, lower):
                matched_words.append(pattern)
        
        if matched_words:
            return IntimateSceneIntent(trigger_words=matched_words[:3], intensity="mild")
        
        return None

    def _detect_outfit_major(self, lower: str) -> Optional[OutfitMajorIntent]:
        for pat in _OUTFIT_MAJOR_TRIGGERS:
            if re.search(pat, lower):
                return OutfitMajorIntent(description=lower)
        return None

    def _detect_outfit_overlay(self, lower: str) -> Optional[OutfitOverlayIntent]:
        for pat, component, state in _OUTFIT_OVERLAY_PATTERNS:
            if re.search(pat, lower):
                return OutfitOverlayIntent(component=component, state=state, raw_text=lower)
        return None

    def _detect_pose_hint(self, lower: str) -> Optional[PoseHint]:
        for composition, patterns in _POSE_PATTERNS.items():
            if any(re.search(p, lower) for p in patterns):
                return PoseHint(composition=composition)
        return None

    def _add_secondary_intents(
        self, bundle: InputIntentBundle, lower: str, skip_outfit: bool = False
    ) -> None:
        """Add secondary intents that can coexist with primary."""
        if not skip_outfit:
            overlay = self._detect_outfit_overlay(lower)
            if overlay:
                bundle.outfit_overlay = overlay
                bundle.secondary.append(IntentType.OUTFIT_OVERLAY)

        pose = self._detect_pose_hint(lower)
        if pose:
            bundle.pose_hint = pose
            bundle.secondary.append(IntentType.POSE_HINT)
