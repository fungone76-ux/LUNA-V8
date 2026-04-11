"""Luna RPG - Enum Definitions.

All enumeration types used throughout the game.
"""
from enum import Enum


class TimeOfDay(str, Enum):
    MORNING = "Morning"
    AFTERNOON = "Afternoon"
    EVENING = "Evening"
    NIGHT = "Night"


class QuestStatus(str, Enum):
    NOT_STARTED = "not_started"
    PENDING_CHOICE = "pending_choice"   # V5: waiting for player confirmation
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    HIDDEN = "hidden"


class BehaviorType(str, Enum):
    AGGRESSIVE = "aggressive"
    SHY = "shy"
    ROMANTIC = "romantic"
    DOMINANT = "dominant"
    SUBMISSIVE = "submissive"
    CURIOUS = "curious"
    TEASING = "teasing"
    PROTECTIVE = "protective"


class OutfitComponent(str, Enum):
    TOP = "top"
    BOTTOM = "bottom"
    SHOES = "shoes"
    OUTERWEAR = "outerwear"
    ACCESSORIES = "accessories"
    SPECIAL = "special"
    BRA = "bra"
    PANTIES = "panties"
    PANTYHOSE = "pantyhose"


class TraitIntensity(str, Enum):
    SUBTLE = "subtle"
    MODERATE = "moderate"
    STRONG = "strong"


class LocationState(str, Enum):
    NORMAL = "normal"
    CROWDED = "crowded"
    EMPTY = "empty"
    LOCKED = "locked"
    DAMAGED = "damaged"
    DECORATED = "decorated"
    DARK = "dark"
    CLEANING = "cleaning"


class CompositionType(str, Enum):
    CLOSE_UP = "close_up"
    MEDIUM_SHOT = "medium_shot"
    WIDE_SHOT = "wide_shot"
    GROUP = "group"
    SCENE = "scene"


class IntentType(str, Enum):
    """Player action intent classification."""
    STANDARD        = "standard"
    MOVEMENT        = "movement"
    FAREWELL        = "farewell"
    REST            = "rest"
    FREEZE          = "freeze"
    SCHEDULE_QUERY  = "schedule_query"
    REMOTE_COMM     = "remote_comm"
    SUMMON          = "summon"
    INTIMATE_SCENE  = "intimate_scene"
    OUTFIT_MAJOR    = "outfit_major"
    INVITATION      = "invitation"
    EVENT_CHOICE    = "event_choice"
    POKER_GAME      = "poker_game"
