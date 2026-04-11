"""Companion Locator System - Hint UI

Lightweight system that shows where companions are based on:
1. Time of day (schedule from companion YAML)
2. Player affinity level (unlocks more info)
3. Special events/quests (override schedule)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, List, Any
from enum import Enum

from luna.core.models import TimeOfDay


class InfoLevel(Enum):
    """How much location info player gets based on affinity."""
    UNKNOWN = 0      # 0-25: No idea where they are
    VAGUE = 1        # 26-50: "In school somewhere"
    SPECIFIC = 2     # 51-75: "In her office, 2nd floor"
    PRECISE = 3      # 76-100: Full schedule + exact location


@dataclass
class LocationHint:
    """Hint about where a companion is."""
    location_id: str
    location_name: str
    activity: str
    can_find_them: bool  # If false, they're busy/inaccessible
    hint_text: str       # What to show the player


class CompanionLocator:
    """Tracks companion locations based on schedule and time."""
    
    def __init__(self, world, game_state) -> None:
        self.world = world
        self.game_state = game_state
    
    def get_hint(self, companion_name: str) -> Optional[LocationHint]:
        """Get location hint for companion based on affinity and time."""
        companion = self.world.companions.get(companion_name)
        if not companion:
            return None
        
        affinity = self.game_state.affinity.get(companion_name, 0)
        info_level = self._get_info_level(affinity)
        
        # Get scheduled location
        schedule_entry = self._get_current_schedule(companion)
        if not schedule_entry:
            return None
        
        # Handle both dict and ScheduleEntry object
        if isinstance(schedule_entry, dict):
            location_id = schedule_entry.get("location", "unknown")
            activity = schedule_entry.get("activity", "busy")
        else:
            # It's a ScheduleEntry object
            location_id = getattr(schedule_entry, "location", "unknown")
            activity = getattr(schedule_entry, "activity", "busy")
        
        location = self.world.locations.get(location_id)
        
        # Build hint based on info level
        hint_text = self._build_hint_text(
            companion_name, 
            location, 
            location_id,
            activity, 
            info_level
        )
        
        return LocationHint(
            location_id=location_id,
            location_name=location.name if location else "Unknown",
            activity=activity,
            can_find_them=info_level.value >= InfoLevel.SPECIFIC.value,
            hint_text=hint_text
        )
    
    def get_all_available_companions(self) -> List[str]:
        """Get list of companions player can interact with now."""
        available = []
        for name in self.world.companions:
            hint = self.get_hint(name)
            if hint and hint.can_find_them:
                available.append(name)
        return available
    
    def _get_info_level(self, affinity: int) -> InfoLevel:
        """Determine how much info to show based on affinity."""
        if affinity >= 76:
            return InfoLevel.PRECISE
        elif affinity >= 51:
            return InfoLevel.SPECIFIC
        elif affinity >= 26:
            return InfoLevel.VAGUE
        return InfoLevel.UNKNOWN
    
    def _get_current_schedule(self, companion) -> Optional[Any]:
        """Get companion's schedule entry for current time."""
        schedule = getattr(companion, "schedule", None)
        if not schedule:
            return None
        
        # Get current time as TimeOfDay enum
        current_time = self.game_state.time_of_day
        
        # Try to get schedule by enum key
        if current_time in schedule:
            return schedule[current_time]
        
        # Try string key fallback
        time_str = str(current_time)
        if hasattr(current_time, 'value'):
            time_str = current_time.value
        
        if time_str in schedule:
            return schedule[time_str]
        
        # Try lowercase
        time_str_lower = time_str.lower()
        for key in schedule:
            if str(key).lower() == time_str_lower:
                return schedule[key]
        
        return None
    
    def _build_hint_text(
        self, 
        companion_name: str, 
        location, 
        location_id: str,
        activity: str,
        info_level: InfoLevel
    ) -> str:
        """Build hint text based on info level."""
        if not activity:
            activity = "busy"
        
        if info_level == InfoLevel.UNKNOWN:
            return f"{companion_name} is somewhere in school."
        
        elif info_level == InfoLevel.VAGUE:
            vague_area = self._get_vague_area(location, location_id)
            return f"{companion_name} is probably in the {vague_area}."
        
        elif info_level == InfoLevel.SPECIFIC:
            loc_name = location.name if location else location_id
            return f"{companion_name} is at {loc_name}. {activity}."
        
        else:  # PRECISE
            loc_name = location.name if location else location_id
            return f"{companion_name} is at {loc_name}. {activity}. You can find her there."
    
    def _get_vague_area(self, location, location_id: str) -> str:
        """Get vague description of area."""
        if not location:
            return "school"
        
        # Map specific locations to vague areas
        area_map = {
            "school_classroom": "classroom area",
            "school_office_luna": "administrative area", 
            "school_gym": "gym area",
            "school_library": "library area",
            "school_cafeteria": "common area",
        }
        return area_map.get(location_id, "school building")


def get_locator(world, game_state) -> CompanionLocator:
    """Factory function to create locator."""
    return CompanionLocator(world, game_state)
