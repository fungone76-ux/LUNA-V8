"""Luna RPG v7 — NPCMind System.

Every NPC (companion AND template) has an internal state that evolves
each turn, even when the player is not interacting with them.

This replaces:
- InitiativeSystem (hardcoded templates → dynamic goals)
- ActivitySystem (hardcoded activities → NPCMind + schedule)

Key concepts:
- Needs: grow over time (social, recognition, intimacy, safety, rest, purpose)
- Goals: what the NPC wants to do RIGHT NOW (generated from needs + context)
- Emotions: stack of current emotional states
- Unspoken: things the NPC knows but hasn't told the player
- OffScreen: things that happened to the NPC while player wasn't present
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================

class NeedType(str, Enum):
    SOCIAL = "social"               # desire to talk / interact
    RECOGNITION = "recognition"     # desire to be noticed / appreciated
    INTIMACY = "intimacy"           # desire for closeness (with player or others)
    SAFETY = "safety"               # desire for stability / fear of consequences
    REST = "rest"                   # tiredness accumulation
    PURPOSE = "purpose"             # desire to do something meaningful


class GoalType(str, Enum):
    SOCIAL = "social"               # wants to chat / share / vent
    TASK = "task"                   # needs to do / deliver something
    EMOTIONAL = "emotional"         # needs emotional connection or release
    CONFRONTATION = "confrontation" # needs to address something (jealousy, anger)
    PROPOSAL = "proposal"           # wants to propose an activity
    # Extended types for world-specific goals
    OBSERVATION = "observation"     # watching / monitoring situation
    URGENT = "urgent"               # time-critical goal
    INTERROGATION = "interrogation" # questioning / investigating
    TERRITORIAL = "territorial"     # defending / marking territory
    PRESSURE = "pressure"           # applying pressure / intimidation
    ESCALATION = "escalation"       # escalating situation
    PATROL = "patrol"               # patrolling / guarding
    REPORT = "report"               # reporting information
    MEETING = "meeting"             # attending / organizing meeting
    INTELLIGENCE = "intelligence"   # gathering information
    SERVICE = "service"             # providing service / assistance
    WARNING = "warning"             # issuing warnings
    TRADE = "trade"                 # trading / bartering


class EmotionType(str, Enum):
    NEUTRAL = "neutral"
    HAPPY = "happy"
    SAD = "sad"
    FRUSTRATED = "frustrated"
    NERVOUS = "nervous"
    ANGRY = "angry"
    LONELY = "lonely"
    EXCITED = "excited"
    JEALOUS = "jealous"
    VULNERABLE = "vulnerable"
    FLIRTY = "flirty"
    TIRED = "tired"
    AUTHORITATIVE = "authoritative"
    EMBARRASSED = "embarrassed"


class TurnDriver(str, Enum):
    """Who drives this turn."""
    PLAYER = "player"           # player action is specific enough
    NPC = "npc"                 # an NPC has something to do/say
    WORLD_EVENT = "world_event" # a world event triggers
    AMBIENT = "ambient"         # ambient details enrich the scene


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class Emotion:
    """Single emotion in the NPC's emotional stack."""
    emotion: EmotionType
    intensity: float = 0.5      # 0.0 - 1.0
    cause: str = ""             # why they feel this way
    since_turn: int = 0         # when it started
    decay_rate: float = 0.05    # how fast it fades per turn

    def tick(self) -> bool:
        """Decay the emotion. Returns False if it should be removed."""
        self.intensity = max(0.0, self.intensity - self.decay_rate)
        return self.intensity > 0.05


_DEFAULT_GOAL_TTL = 25      # turns before a stale goal is auto-discarded
_DEFAULT_UNSPOKEN_TTL = 40  # turns before an unspoken item is auto-discarded
_MAX_UNSPOKEN = 20          # hard cap on unspoken list
_MAX_OFF_SCREEN = 50        # hard cap on off-screen log
_MAX_EMOTIONS = 10          # hard cap on emotion stack


@dataclass
class NPCGoal:
    """What the NPC wants to do right now."""
    description: str            # human-readable: "vuole parlarti del preside"
    goal_type: GoalType
    target: str = "player"      # "player", npc_id, "self"
    urgency: float = 0.3        # 0.0 - 1.0, grows over time
    max_urgency: float = 1.0
    growth_rate: float = 0.05   # per turn
    created_at_turn: int = 0
    ttl_turns: int = _DEFAULT_GOAL_TTL   # 0 = no expiry
    context: str = ""           # extra context for LLM
    source: str = ""            # what generated this goal (need, event, etc.)

    def tick(self) -> None:
        """Increase urgency over time."""
        self.urgency = min(self.max_urgency, self.urgency + self.growth_rate)

    @property
    def is_urgent(self) -> bool:
        return self.urgency >= 0.7

    @property
    def is_critical(self) -> bool:
        return self.urgency >= 0.9


@dataclass
class UnspokenItem:
    """Something the NPC knows but hasn't told the player."""
    content: str                # "ha visto Stella parlare con te"
    since_turn: int = 0
    emotional_weight: float = 0.3   # how much it bothers them (grows)
    weight_growth: float = 0.02     # per turn
    trigger_context: str = ""       # when they might say it
    ttl_turns: int = _DEFAULT_UNSPOKEN_TTL  # 0 = no expiry
    # e.g. "when alone with player", "when Stella is mentioned"

    def tick(self) -> None:
        self.emotional_weight = min(1.0, self.emotional_weight + self.weight_growth)

    @property
    def is_burning(self) -> bool:
        """Is this bothering them enough to bring up spontaneously?"""
        return self.emotional_weight >= 0.7


@dataclass
class OffScreenEvent:
    """Something that happened to the NPC while player wasn't present."""
    description: str            # "ha litigato col preside"
    turn: int = 0
    importance: float = 0.5     # 0.0 - 1.0
    told_to_player: bool = False
    related_npc: str = ""       # who was involved
    emotional_impact: str = ""  # "frustrated", "happy", etc.

    @property
    def should_mention(self) -> bool:
        return not self.told_to_player and self.importance >= 0.3


@dataclass
class NPCRelationship:
    """Relationship between this NPC and another NPC."""
    target_npc: str
    rel_type: str = ""          # "rivale silenziosa", "confidente", etc.
    description: str = ""       # longer description
    tension: float = 0.0        # 0.0 - 1.0 (how tense the relationship is)
    base_tension: float = 0.0   # baseline tension (from YAML)
    last_interaction_turn: int = 0


@dataclass
class NeedProfile:
    """Growth rates for each need, per NPC (from YAML or defaults)."""
    social: float = 0.03
    recognition: float = 0.02
    intimacy: float = 0.02
    safety: float = 0.01
    rest: float = 0.015
    purpose: float = 0.02

    def get_rate(self, need: NeedType) -> float:
        return getattr(self, need.value, 0.02)


@dataclass
class GoalTemplate:
    """Template for generating goals (from YAML)."""
    goal_id: str
    description: str
    goal_type: GoalType = GoalType.SOCIAL
    target: str = "player"
    urgency_start: float = 0.3
    growth_rate: float = 0.05
    context: str = ""
    # Conditions
    conditions: Dict[str, Any] = field(default_factory=dict)
    # e.g. {"time": "Evening", "need_social": ">0.6", "affinity": ">40"}


# =============================================================================
# NPCMind
# =============================================================================

@dataclass
class NPCMind:
    """Internal state of a single NPC. Evolves every turn."""

    npc_id: str
    name: str
    is_companion: bool = True   # False for template NPCs

    # --- Needs (0.0 → 1.0) ---
    needs: Dict[str, float] = field(default_factory=lambda: {
        "social": 0.2,
        "recognition": 0.1,
        "intimacy": 0.1,
        "safety": 0.5,
        "rest": 0.0,
        "purpose": 0.2,
    })

    # --- Current goal ---
    current_goal: Optional[NPCGoal] = None
    goal_history: List[str] = field(default_factory=list)  # last N goal descriptions

    # --- Emotional stack ---
    emotions: List[Emotion] = field(default_factory=list)

    # --- Unspoken things ---
    unspoken: List[UnspokenItem] = field(default_factory=list)

    # --- Off-screen events ---
    off_screen_log: List[OffScreenEvent] = field(default_factory=list)

    # --- Relationships with other NPCs ---
    relationships: Dict[str, NPCRelationship] = field(default_factory=dict)

    # --- Need profile (growth rates) ---
    need_profile: NeedProfile = field(default_factory=NeedProfile)

    # --- Goal templates (from YAML) ---
    goal_templates: List[GoalTemplate] = field(default_factory=list)

    # --- Counters ---
    turns_since_player_contact: int = 0
    turns_in_current_activity: int = 0
    turns_since_last_initiative: int = 0

    # --- Serialization ---

    def to_dict(self) -> Dict[str, Any]:
        return {
            "npc_id": self.npc_id,
            "name": self.name,
            "is_companion": self.is_companion,
            "needs": dict(self.needs),
            "current_goal": {
                "description": self.current_goal.description,
                "goal_type": self.current_goal.goal_type.value,
                "target": self.current_goal.target,
                "urgency": self.current_goal.urgency,
                "created_at_turn": self.current_goal.created_at_turn,
                "ttl_turns": self.current_goal.ttl_turns,
                "context": self.current_goal.context,
                "source": self.current_goal.source,
            } if self.current_goal else None,
            "emotions": [
                {"emotion": e.emotion.value, "intensity": e.intensity,
                 "cause": e.cause, "since_turn": e.since_turn}
                for e in self.emotions
            ],
            "unspoken": [
                {"content": u.content, "since_turn": u.since_turn,
                 "emotional_weight": u.emotional_weight,
                 "trigger_context": u.trigger_context,
                 "ttl_turns": u.ttl_turns}
                for u in self.unspoken
            ],
            "off_screen_log": [
                {"description": o.description, "turn": o.turn,
                 "importance": o.importance, "told_to_player": o.told_to_player,
                 "related_npc": o.related_npc}
                for o in self.off_screen_log
            ],
            "turns_since_player_contact": self.turns_since_player_contact,
            "turns_since_last_initiative": self.turns_since_last_initiative,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        self.needs = data.get("needs", self.needs)
        self.turns_since_player_contact = data.get("turns_since_player_contact", 0)
        self.turns_since_last_initiative = data.get("turns_since_last_initiative", 0)

        goal_data = data.get("current_goal")
        if goal_data:
            self.current_goal = NPCGoal(
                description=goal_data["description"],
                goal_type=GoalType(goal_data.get("goal_type", "social")),
                target=goal_data.get("target", "player"),
                urgency=goal_data.get("urgency", 0.3),
                created_at_turn=goal_data.get("created_at_turn", 0),
                ttl_turns=goal_data.get("ttl_turns", _DEFAULT_GOAL_TTL),
                context=goal_data.get("context", ""),
                source=goal_data.get("source", ""),
            )

        self.emotions = [
            Emotion(
                emotion=EmotionType(e["emotion"]),
                intensity=e.get("intensity", 0.5),
                cause=e.get("cause", ""),
                since_turn=e.get("since_turn", 0),
            )
            for e in data.get("emotions", [])
        ]

        self.unspoken = [
            UnspokenItem(
                content=u["content"],
                since_turn=u.get("since_turn", 0),
                emotional_weight=u.get("emotional_weight", 0.3),
                trigger_context=u.get("trigger_context", ""),
                ttl_turns=u.get("ttl_turns", _DEFAULT_UNSPOKEN_TTL),
            )
            for u in data.get("unspoken", [])
        ]

        self.off_screen_log = [
            OffScreenEvent(
                description=o["description"],
                turn=o.get("turn", 0),
                importance=o.get("importance", 0.5),
                told_to_player=o.get("told_to_player", False),
                related_npc=o.get("related_npc", ""),
            )
            for o in data.get("off_screen_log", [])
        ]

    # --- Convenience ---

    @property
    def dominant_emotion(self) -> Optional[Emotion]:
        if not self.emotions:
            return None
        return max(self.emotions, key=lambda e: e.intensity)

    @property
    def dominant_need(self) -> Tuple[str, float]:
        if not self.needs:
            return ("social", 0.0)
        name = max(self.needs, key=self.needs.get)
        return (name, self.needs[name])

    @property
    def has_burning_unspoken(self) -> bool:
        return any(u.is_burning for u in self.unspoken)

    @property
    def untold_events(self) -> List[OffScreenEvent]:
        return [e for e in self.off_screen_log if e.should_mention]

    def add_emotion(self, emotion: EmotionType, intensity: float = 0.5,
                    cause: str = "", turn: int = 0) -> None:
        # Replace if same emotion exists, otherwise add
        for existing in self.emotions:
            if existing.emotion == emotion:
                existing.intensity = max(existing.intensity, intensity)
                existing.cause = cause or existing.cause
                return
        self.emotions.append(Emotion(
            emotion=emotion, intensity=intensity,
            cause=cause, since_turn=turn,
        ))

    def add_unspoken(self, content: str, turn: int = 0,
                     weight: float = 0.3, trigger: str = "") -> None:
        # Don't duplicate
        for u in self.unspoken:
            if u.content == content:
                return
        self.unspoken.append(UnspokenItem(
            content=content, since_turn=turn,
            emotional_weight=weight, trigger_context=trigger,
        ))

    def add_off_screen(self, description: str, turn: int = 0,
                       importance: float = 0.5, related_npc: str = "",
                       emotional_impact: str = "") -> None:
        self.off_screen_log.append(OffScreenEvent(
            description=description, turn=turn,
            importance=importance, related_npc=related_npc,
            emotional_impact=emotional_impact,
        ))
        # Also add emotion if significant
        if emotional_impact and importance >= 0.4:
            try:
                emo = EmotionType(emotional_impact)
                self.add_emotion(emo, intensity=importance, cause=description, turn=turn)
            except ValueError:
                pass

    def mark_event_told(self, event: OffScreenEvent) -> None:
        event.told_to_player = True

    def clear_old_events(self, current_turn: int, max_age: int = 30) -> None:
        """Remove old off-screen events."""
        self.off_screen_log = [
            e for e in self.off_screen_log
            if current_turn - e.turn < max_age or not e.told_to_player
        ]

    def get_context_for_llm(self) -> str:
        """Build context string for injection into NarrativeEngine prompt."""
        parts = []

        # Current goal
        if self.current_goal and self.current_goal.urgency >= 0.3:
            urgency_label = "URGENT" if self.current_goal.is_urgent else "moderate"
            parts.append(
                f"[GOAL ({urgency_label})] {self.name} wants to: "
                f"{self.current_goal.description}"
            )
            if self.current_goal.context:
                parts.append(f"  Context: {self.current_goal.context}")

        # Dominant emotion
        dom = self.dominant_emotion
        if dom and dom.emotion != EmotionType.NEUTRAL:
            parts.append(
                f"[EMOTION] {self.name} is feeling {dom.emotion.value} "
                f"(intensity: {dom.intensity:.1f})"
            )
            if dom.cause:
                parts.append(f"  Because: {dom.cause}")

        # Untold events (most important first)
        untold = sorted(self.untold_events, key=lambda e: e.importance, reverse=True)
        for event in untold[:2]:  # max 2
            parts.append(
                f"[OFF-SCREEN] {self.name}: {event.description}"
            )

        # Burning unspoken
        burning = [u for u in self.unspoken if u.is_burning]
        for item in burning[:1]:  # max 1
            parts.append(
                f"[UNSPOKEN] {self.name} is holding back: {item.content}"
            )

        # High needs
        high_needs = [
            (name, val) for name, val in self.needs.items() if val >= 0.6
        ]
        if high_needs:
            needs_str = ", ".join(f"{n}={v:.1f}" for n, v in high_needs)
            parts.append(f"[NEEDS] {self.name}: {needs_str}")

        if not parts:
            return ""

        return "\n".join([
            f"=== {self.name.upper()} — INTERNAL STATE ===",
            *parts,
            "",
        ])


# =============================================================================
# NPCMind Manager — ticks all minds each turn
# =============================================================================

class NPCMindManager:
    """Manages all NPCMind instances. Ticks them each turn."""

    def __init__(self) -> None:
        self.minds: Dict[str, NPCMind] = {}

    def register(self, mind: NPCMind) -> None:
        self.minds[mind.npc_id] = mind

    def get(self, npc_id: str) -> Optional[NPCMind]:
        return self.minds.get(npc_id)

    def get_or_create(self, npc_id: str, name: str = "",
                      is_companion: bool = True) -> NPCMind:
        if npc_id not in self.minds:
            mind = NPCMind(npc_id=npc_id, name=name or npc_id,
                           is_companion=is_companion)
            self.minds[npc_id] = mind
        return self.minds[npc_id]

    # -------------------------------------------------------------------------
    # Main tick — called every turn by WorldSimulator
    # -------------------------------------------------------------------------

    def tick_all(
        self,
        active_companion: str,
        game_state: Any,
        turn_number: int,
    ) -> None:
        """Tick every NPC mind. Called once per turn."""
        for npc_id, mind in self.minds.items():
            is_with_player = (npc_id == active_companion)
            self._tick_one(mind, is_with_player, game_state, turn_number)

    def _tick_one(
        self,
        mind: NPCMind,
        is_with_player: bool,
        game_state: Any,
        turn_number: int,
    ) -> None:
        """Tick a single NPCMind."""

        # 1. Needs grow (or decay if with player)
        for need_name in list(mind.needs.keys()):
            rate = mind.need_profile.get_rate(NeedType(need_name))
            if is_with_player and need_name == "social":
                # Social need decreases when talking to player
                mind.needs[need_name] = max(0.0, mind.needs[need_name] - 0.08)
            elif is_with_player and need_name == "recognition":
                mind.needs[need_name] = max(0.0, mind.needs[need_name] - 0.03)
            else:
                mind.needs[need_name] = min(1.0, mind.needs[need_name] + rate)

        # 2. Contact counter
        if is_with_player:
            mind.turns_since_player_contact = 0
        else:
            mind.turns_since_player_contact += 1

        # 3. Emotions decay + size cap
        mind.emotions = [e for e in mind.emotions if e.tick()]
        if len(mind.emotions) > _MAX_EMOTIONS:
            # Keep highest intensity emotions
            mind.emotions.sort(key=lambda e: e.intensity, reverse=True)
            mind.emotions = mind.emotions[:_MAX_EMOTIONS]

        # 4. Unspoken items: grow in weight, purge expired, enforce cap
        for item in mind.unspoken:
            item.tick()
        mind.unspoken = [
            u for u in mind.unspoken
            if u.ttl_turns == 0 or (turn_number - u.since_turn) < u.ttl_turns
        ]
        if len(mind.unspoken) > _MAX_UNSPOKEN:
            # Keep highest emotional weight items
            mind.unspoken.sort(key=lambda u: u.emotional_weight, reverse=True)
            mind.unspoken = mind.unspoken[:_MAX_UNSPOKEN]

        # 5. Goal urgency grows; expire goal if TTL exceeded
        if mind.current_goal:
            goal = mind.current_goal
            goal.tick()
            age = turn_number - goal.created_at_turn
            expired = goal.ttl_turns > 0 and age >= goal.ttl_turns
            maxed = goal.urgency >= goal.max_urgency
            if maxed or expired:
                if expired:
                    logger.debug("Goal TTL expired for %s: %s (age %d)", mind.name, goal.description, age)
                mind.goal_history.append(goal.description)
                if len(mind.goal_history) > 10:
                    mind.goal_history.pop(0)
                mind.current_goal = None

        # 6. Generate goal if needed
        if not mind.current_goal:
            mind.current_goal = self._generate_goal(mind, game_state, turn_number)

        # 7. Initiative counter
        mind.turns_since_last_initiative += 1

        # 8. Clean old events + enforce off-screen cap
        mind.clear_old_events(turn_number)
        if len(mind.off_screen_log) > _MAX_OFF_SCREEN:
            # Keep most important / most recent untold events
            mind.off_screen_log.sort(
                key=lambda e: (not e.told_to_player, e.importance, e.turn),
                reverse=True,
            )
            mind.off_screen_log = mind.off_screen_log[:_MAX_OFF_SCREEN]

    # -------------------------------------------------------------------------
    # Goal generation
    # -------------------------------------------------------------------------

    def _generate_goal(
        self,
        mind: NPCMind,
        game_state: Any,
        turn_number: int,
    ) -> Optional[NPCGoal]:
        """Generate a goal based on needs, emotions, unspoken, and templates."""

        # Priority 1: Burning unspoken → confrontation goal
        burning = [u for u in mind.unspoken if u.is_burning]
        if burning:
            item = burning[0]
            return NPCGoal(
                description=f"Vuole parlarti di: {item.content}",
                goal_type=GoalType.CONFRONTATION,
                target="player",
                urgency=item.emotional_weight,
                context=item.trigger_context,
                source="unspoken",
                created_at_turn=turn_number,
            )

        # Priority 2: Untold important events → social goal
        untold = mind.untold_events
        if untold:
            event = max(untold, key=lambda e: e.importance)
            return NPCGoal(
                description=f"Vuole raccontarti: {event.description}",
                goal_type=GoalType.SOCIAL,
                target="player",
                urgency=event.importance * 0.8,
                context=f"È successo al turno {event.turn}",
                source="off_screen_event",
                created_at_turn=turn_number,
            )

        # Priority 3: Check goal templates from YAML
        for template in mind.goal_templates:
            if self._template_matches(template, mind, game_state):
                return NPCGoal(
                    description=template.description,
                    goal_type=template.goal_type,
                    target=template.target,
                    urgency=template.urgency_start,
                    growth_rate=template.growth_rate,
                    context=template.context,
                    source=f"template:{template.goal_id}",
                    created_at_turn=turn_number,
                )

        # Priority 4: Need-driven goals
        dom_need, dom_val = mind.dominant_need
        if dom_val >= 0.6:
            return self._goal_from_need(mind, dom_need, dom_val, turn_number)

        # Priority 5: Emotion-driven goals
        dom_emo = mind.dominant_emotion
        if dom_emo and dom_emo.intensity >= 0.5 and dom_emo.emotion != EmotionType.NEUTRAL:
            return self._goal_from_emotion(mind, dom_emo, turn_number)

        # Priority 6 (v8): Absolute fallback — always return a goal based on
        # the dominant need, even if its value is below the 0.6 threshold.
        # Guarantees NPC always has an intent and avoids silent "empty" responses.
        dom_need, dom_val = mind.dominant_need
        return NPCGoal(
            description=self._goal_from_need(mind, dom_need, dom_val, turn_number).description,
            goal_type=GoalType.SOCIAL,
            target="player",
            urgency=max(0.15, dom_val * 0.3),
            growth_rate=0.03,
            ttl_turns=30,
            source=f"fallback:{dom_need}",
            created_at_turn=turn_number,
        )

    def _template_matches(
        self, template: GoalTemplate, mind: NPCMind, game_state: Any,
    ) -> bool:
        """Check if a goal template's conditions are met."""
        conditions = template.conditions
        if not conditions:
            return False

        for key, value in conditions.items():
            if key == "time":
                current_time = getattr(game_state, "time_of_day", None)
                t_str = current_time.value if hasattr(current_time, "value") else str(current_time)
                if isinstance(value, list):
                    if t_str not in value:
                        return False
                elif t_str != value:
                    return False

            elif key.startswith("need_"):
                need_name = key[5:]
                threshold = float(value.replace(">", "").replace("<", ""))
                actual = mind.needs.get(need_name, 0.0)
                if ">" in value and actual <= threshold:
                    return False
                if "<" in value and actual >= threshold:
                    return False

            elif key == "affinity":
                threshold = float(value.replace(">", "").replace("<", ""))
                actual = game_state.affinity.get(mind.npc_id, 0)
                if ">" in value and actual <= threshold:
                    return False

            elif key == "random_chance":
                if random.random() > float(value):
                    return False

            elif key == "off_screen":
                # Check if a specific off_screen event type exists
                found = any(value in e.description for e in mind.off_screen_log
                            if not e.told_to_player)
                if not found:
                    return False

            elif key == "unspoken":
                found = any(value in u.content for u in mind.unspoken)
                if not found:
                    return False

            elif key == "flags_not":
                # Block goal if ANY of the listed flags is set in game_state
                flags = value if isinstance(value, list) else [value]
                if any(game_state.flags.get(f) for f in flags):
                    return False

        return True

    def _goal_from_need(
        self, mind: NPCMind, need: str, value: float, turn: int,
    ) -> NPCGoal:
        """Generate a generic goal from a dominant need."""
        goals_by_need = {
            "social": NPCGoal(
                description="Vuole parlare, ha bisogno di compagnia",
                goal_type=GoalType.SOCIAL, target="player",
                urgency=value * 0.6, source=f"need:{need}",
                created_at_turn=turn,
            ),
            "recognition": NPCGoal(
                description="Vuole sentirsi apprezzata, cerca un complimento",
                goal_type=GoalType.EMOTIONAL, target="player",
                urgency=value * 0.5, source=f"need:{need}",
                created_at_turn=turn,
            ),
            "intimacy": NPCGoal(
                description="Cerca vicinanza, vuole un momento intimo",
                goal_type=GoalType.EMOTIONAL, target="player",
                urgency=value * 0.7, source=f"need:{need}",
                created_at_turn=turn,
            ),
            "rest": NPCGoal(
                description="È stanca, vorrebbe riposarsi o andare a casa",
                goal_type=GoalType.PROPOSAL, target="self",
                urgency=value * 0.4, source=f"need:{need}",
                created_at_turn=turn,
            ),
            "purpose": NPCGoal(
                description="Vuole fare qualcosa di concreto, proporre un'attività",
                goal_type=GoalType.PROPOSAL, target="player",
                urgency=value * 0.5, source=f"need:{need}",
                created_at_turn=turn,
            ),
            "safety": NPCGoal(
                description="È preoccupata per qualcosa, cerca rassicurazione",
                goal_type=GoalType.EMOTIONAL, target="player",
                urgency=value * 0.4, source=f"need:{need}",
                created_at_turn=turn,
            ),
        }
        return goals_by_need.get(need, goals_by_need["social"])

    def _goal_from_emotion(
        self, mind: NPCMind, emotion: Emotion, turn: int,
    ) -> NPCGoal:
        """Generate a goal from a dominant emotion."""
        emo_goals = {
            EmotionType.FRUSTRATED: "Vuole sfogarsi, è irritata",
            EmotionType.LONELY: "Si sente sola, cerca compagnia",
            EmotionType.JEALOUS: "È gelosa, vuole confrontarti",
            EmotionType.EXCITED: "È entusiasta, vuole condividere qualcosa",
            EmotionType.VULNERABLE: "Si sente vulnerabile, cerca conforto",
            EmotionType.SAD: "È triste, ha bisogno di supporto",
            EmotionType.ANGRY: "È arrabbiata, potrebbe esplodere",
        }
        desc = emo_goals.get(emotion.emotion, "Ha qualcosa in mente")
        goal_type = GoalType.CONFRONTATION if emotion.emotion in (
            EmotionType.JEALOUS, EmotionType.ANGRY
        ) else GoalType.EMOTIONAL

        return NPCGoal(
            description=desc,
            goal_type=goal_type,
            target="player",
            urgency=emotion.intensity * 0.7,
            context=emotion.cause,
            source=f"emotion:{emotion.emotion.value}",
            created_at_turn=turn,
        )

    # -------------------------------------------------------------------------
    # Serialization
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            npc_id: mind.to_dict()
            for npc_id, mind in self.minds.items()
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        for npc_id, mind_data in data.items():
            mind = self.get_or_create(
                npc_id,
                name=mind_data.get("name", npc_id),
                is_companion=mind_data.get("is_companion", True),
            )
            mind.from_dict(mind_data)

    def simulate_offline_ticks(self, n_turns: int, start_turn: int = 0) -> None:
        """Simulate N turns of offline time passing (Il Mondo Ricorda).

        Called when a session is loaded after real-world time has passed.
        NPCs accumulate needs, emotions decay, and goal urgencies grow —
        so the world reacts as if time actually elapsed between sessions.
        Goal generation is deferred to the first real turn (no game_state available).
        """
        if n_turns <= 0:
            return
        logger.info("[NPCMindManager] Simulating %d offline ticks across %d minds",
                    n_turns, len(self.minds))
        for i in range(n_turns):
            turn = start_turn + i
            for mind in self.minds.values():
                # 1. All needs grow (player is absent)
                for need_name in list(mind.needs.keys()):
                    rate = mind.need_profile.get_rate(NeedType(need_name))
                    mind.needs[need_name] = min(1.0, mind.needs[need_name] + rate)
                # 2. Contact counter grows
                mind.turns_since_player_contact += 1
                # 3. Emotions decay
                mind.emotions = [e for e in mind.emotions if e.tick()]
                if len(mind.emotions) > _MAX_EMOTIONS:
                    mind.emotions.sort(key=lambda e: e.intensity, reverse=True)
                    mind.emotions = mind.emotions[:_MAX_EMOTIONS]
                # 4. Unspoken items accumulate weight, expired ones purged
                for item in mind.unspoken:
                    item.tick()
                mind.unspoken = [
                    u for u in mind.unspoken
                    if u.ttl_turns == 0 or (turn - u.since_turn) < u.ttl_turns
                ]
                if len(mind.unspoken) > _MAX_UNSPOKEN:
                    mind.unspoken.sort(key=lambda u: u.emotional_weight, reverse=True)
                    mind.unspoken = mind.unspoken[:_MAX_UNSPOKEN]
                # 5. Goal urgency grows (no new goals without game_state)
                if mind.current_goal:
                    mind.current_goal.tick()
