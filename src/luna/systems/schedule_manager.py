"""NPC Schedule System - Dynamic routines based on time.

V4 Schedule System:
- Each NPC has preferred location per time slot
- Auto-switch when entering location (who's here?)
- Can ALWAYS interact with anyone (mention them)
- Images adapt based on who's present vs mentioned

Extracted to new file to keep engine.py clean.
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

from typing import Optional, Dict, List, Set, Tuple
from dataclasses import dataclass, field

from luna.core.models import TimeOfDay, GameState


@dataclass
class ScheduleEntry:
    """Single time slot schedule for an NPC."""
    location: str  # Location ID where NPC is
    activity: str  # What they're doing (for LLM context)
    outfit:   str  = "default"  # Outfit style for this time
    urgency:  str  = "medium"   # high/medium/low — departure negotiability
    available: bool = True  # Can be interacted with


@dataclass
class NPCSchedule:
    """Complete daily routine for an NPC."""
    npc_name: str
    schedules: Dict[TimeOfDay, ScheduleEntry] = field(default_factory=dict)
    
    def get_current(self, time_of_day: TimeOfDay) -> Optional[ScheduleEntry]:
        """Get schedule for current time."""
        if isinstance(time_of_day, str):
            try:
                time_of_day = TimeOfDay(time_of_day)
            except ValueError:
                time_of_day = TimeOfDay.MORNING
        return self.schedules.get(time_of_day)


class ScheduleManager:
    """Manages NPC routines and location-based presence.
    
    V4.2: Now generic - works with any world, not just school_life.
    Loads schedules from world.npc_schedules if available, 
    otherwise creates default schedules for all companions.
    
    Key concept: Schedule = WHERE you find them, not IF you can talk.
    You can ALWAYS interact with any NPC by mentioning them.
    """
    
    def __init__(self, game_state: GameState, world: Optional[Any] = None):
        """Initialize schedule manager.
        
        Args:
            game_state: Current game state for time/location
            world: World definition (optional, for loading schedules)
        """
        self.game_state = game_state
        self.world = world
        self._schedules: Dict[str, NPCSchedule] = {}
        self._load_schedules()
    
    def _load_schedules(self) -> None:
        """Load NPC schedules.
        
        Priority:
        1. Load from world.npc_schedules if available
        2. Create default schedules for all companions
        """
        if self.world and self.world.npc_schedules:
            # Load from world definition
            self._load_from_world()
        else:
            # Create generic default schedules
            self._create_default_schedules()
    
    def _load_from_world(self) -> None:
        """Load schedules from world.npc_schedules."""
        logger.debug(f"[ScheduleManager] Loading schedules from world definition")
        
        # Map lowercase time strings to TimeOfDay enum
        time_mapping = {
            "morning": TimeOfDay.MORNING,
            "afternoon": TimeOfDay.AFTERNOON,
            "evening": TimeOfDay.EVENING,
            "night": TimeOfDay.NIGHT,
        }
        
        for npc_name, schedule_data in self.world.npc_schedules.items():
            schedules = {}
            for time_str, entry_data in schedule_data.items():
                time_key = time_str.lower()
                if time_key not in time_mapping:
                    logger.warning(f"[ScheduleManager] Warning: Invalid time slot '{time_str}' for {npc_name}")
                    continue
                
                time_of_day = time_mapping[time_key]
                schedules[time_of_day] = ScheduleEntry(
                    location=entry_data.get("location", "unknown"),
                    activity=entry_data.get("activity", ""),
                    outfit=entry_data.get("outfit", "default"),
                    urgency=entry_data.get("urgency", "medium"),
                    available=entry_data.get("available", True),
                )
            
            if schedules:
                self._schedules[npc_name] = NPCSchedule(
                    npc_name=npc_name,
                    schedules=schedules
                )
                logger.debug(f"[ScheduleManager] Loaded schedule for {npc_name}")
    
    def _create_default_schedules(self) -> None:
        """Create generic default schedules for all companions.
        
        V4.2: Works with any world. Creates simple schedules:
        - Morning: First location in world
        - Afternoon: Same as morning
        - Evening: NPC's home (if defined) or same
        - Night: NPC's home or same
        """
        logger.debug(f"[ScheduleManager] Creating default schedules for companions")
        
        if not self.world or not self.world.companions:
            # No world or no companions - use hardcoded school_life for backward compat
            self._load_school_life_defaults()
            return
        
        # Get first location as default
        default_location = None
        if self.world.locations:
            default_location = next(iter(self.world.locations.keys()))
        
        for npc_name, companion in self.world.companions.items():
            # Skip temporary/solo companions
            if getattr(companion, 'is_temporary', False) or npc_name == "_solo_":
                continue
            
            # Try to find a "home" location for this NPC
            home_location = None
            npc_home_id = f"{npc_name.lower()}_home"
            if npc_home_id in self.world.locations:
                home_location = npc_home_id
            
            # Use spawn_locations if available
            spawn_locations = getattr(companion, 'spawn_locations', [])
            morning_loc = spawn_locations[0] if spawn_locations else (default_location or "unknown")
            
            schedules = {
                TimeOfDay.MORNING: ScheduleEntry(
                    location=morning_loc,
                    activity=f"{npc_name} is here",
                    outfit=getattr(companion, 'default_outfit', 'default'),
                ),
                TimeOfDay.AFTERNOON: ScheduleEntry(
                    location=morning_loc,
                    activity=f"{npc_name} is still here",
                    outfit=getattr(companion, 'default_outfit', 'default'),
                ),
                TimeOfDay.EVENING: ScheduleEntry(
                    location=home_location or morning_loc,
                    activity=f"{npc_name} is resting",
                    outfit="casual",
                ),
                TimeOfDay.NIGHT: ScheduleEntry(
                    location=home_location or morning_loc,
                    activity=f"{npc_name} is sleeping",
                    outfit="nightwear",
                ),
            }
            
            self._schedules[npc_name] = NPCSchedule(
                npc_name=npc_name,
                schedules=schedules
            )
            logger.debug(f"[ScheduleManager] Created default schedule for {npc_name}")
    
    def _load_school_life_defaults(self) -> None:
        """Load hardcoded school_life schedules for backward compatibility."""
        logger.debug(f"[ScheduleManager] Loading school_life defaults (backward compat)")
        
        # Luna - Teacher
        self._schedules["Luna"] = NPCSchedule(
            npc_name="Luna",
            schedules={
                TimeOfDay.MORNING: ScheduleEntry(
                    location="school_classroom",
                    activity="Insegna matematica alla classe",
                    outfit="teacher_suit"
                ),
                TimeOfDay.AFTERNOON: ScheduleEntry(
                    location="school_office_luna",
                    activity="Corregge compiti nel suo ufficio",
                    outfit="teacher_suit"
                ),
                TimeOfDay.EVENING: ScheduleEntry(
                    location="school_office_luna",
                    activity="Prepara lezioni per domani",
                    outfit="casual"
                ),
                TimeOfDay.NIGHT: ScheduleEntry(
                    location="luna_home",
                    activity="Riposa a casa sua",
                    outfit="nightwear",
                    available=True
                ),
            }
        )
        
        # Add other school_life NPCs if needed
        # (omitted for brevity - can be expanded)
    
    def get_npc_location(self, npc_name: str, time_of_day: Optional[TimeOfDay] = None) -> Optional[str]:
        """Get current location of an NPC based on time.
        
        Args:
            npc_name: Name of the NPC
            time_of_day: Specific time, or None for current game state time
            
        Returns:
            Location ID or None
        """
        schedule = self._schedules.get(npc_name)
        if not schedule:
            return None
        
        tod = time_of_day or self.game_state.time_of_day
        entry = schedule.get_current(tod)
        return entry.location if entry else None
    
    def get_npc_location_at_time(self, npc_name: str, time_of_day: TimeOfDay) -> Optional[str]:
        """Get NPC location at a specific time.
        
        Args:
            npc_name: Name of the NPC
            time_of_day: Specific time period
            
        Returns:
            Location ID or None
        """
        return self.get_npc_location(npc_name, time_of_day)
    
    def get_npc_activity(self, npc_name: str, time_of_day: Optional[TimeOfDay] = None) -> str:
        """Get current activity description for context.
        
        Args:
            npc_name: Name of the NPC
            time_of_day: Specific time, or None for current game state time
            
        Returns:
            Activity description
        """
        schedule = self._schedules.get(npc_name)
        if not schedule:
            return ""
        
        tod = time_of_day or self.game_state.time_of_day
        entry = schedule.get_current(tod)
        return entry.activity if entry else ""
    
    def get_current_activity(self, npc_name: str) -> Tuple[str, str]:
        """Get current location and activity for an NPC.
        
        Args:
            npc_name: Name of the NPC
            
        Returns:
            Tuple of (location_id, activity_description)
        """
        location = self.get_npc_current_location(npc_name)
        activity = self.get_npc_activity(npc_name)
        return location, activity
    
    def get_present_npcs(self, location_id: str) -> List[str]:
        """Get list of NPCs currently at this location.
        
        Args:
            location_id: Location to check
            
        Returns:
            List of NPC names present
        """
        present = []
        for npc_name, schedule in self._schedules.items():
            entry = schedule.get_current(self.game_state.time_of_day)
            if entry and entry.location == location_id:
                present.append(npc_name)
        return present
    
    def get_primary_npc(self, location_id: str) -> Optional[str]:
        """Get the 'main' NPC at this location (for auto-switch).
        
        Priority: Affinity-based or first found
        
        Args:
            location_id: Location to check
            
        Returns:
            NPC name or None
        """
        present = self.get_present_npcs(location_id)
        if not present:
            return None
        
        # If multiple, prefer based on affinity
        if len(present) > 1 and self.game_state:
            # Sort by affinity (highest first)
            present.sort(
                key=lambda name: self.game_state.affinity.get(name, 0),
                reverse=True
            )
        
        return present[0]
    
    def get_npc_current_location(self, npc_name: str) -> Optional[str]:
        """Get the current location of an NPC based on their schedule.
        
        Args:
            npc_name: Name of the NPC
            
        Returns:
            Location ID where NPC should be, or None if no schedule
        """
        schedule = self._schedules.get(npc_name)
        if not schedule:
            return None
        
        entry = schedule.get_current(self.game_state.time_of_day)
        if not entry:
            return None
        
        return entry.location
    
    def build_schedule_context(self, npc_name: str) -> str:
        """Build context string for LLM about NPC's current situation.
        
        Args:
            npc_name: Name of the NPC
            
        Returns:
            Context string for LLM prompt
        """
        schedule = self._schedules.get(npc_name)
        if not schedule:
            return ""
        
        entry = schedule.get_current(self.game_state.time_of_day)
        if not entry:
            return ""
        
        # Check if player is at same location
        at_same_location = self.game_state.current_location == entry.location
        
        context_parts = []
        time_val = self.game_state.time_of_day
        time_str = time_val.value if hasattr(time_val, 'value') else str(time_val)
        context_parts.append(f"CURRENT TIME: {time_str}")
        context_parts.append(f"LOCATION: {entry.location}")
        context_parts.append(f"ACTIVITY: {entry.activity}")
        context_parts.append(f"OUTFIT: {entry.outfit}")
        
        if at_same_location:
            context_parts.append("PLAYER IS PRESENT: The player is here with you.")
        else:
            context_parts.append(
                f"PLAYER IS ELSEWHERE: You are at {entry.location}, "
                f"player is at {self.game_state.current_location}. "
                f"If player mentions you, you can respond as if texting/calling."
            )
        
        return "\n".join(context_parts)
    
    def should_auto_switch(self, location_id: str, current_companion: str) -> Optional[str]:
        """Determine if should auto-switch companion on location enter.
        
        Args:
            location_id: Location being entered
            current_companion: Current active companion
            
        Returns:
            New companion name or None (keep current)
        """
        primary = self.get_primary_npc(location_id)
        
        # Don't switch if no one is here
        if not primary:
            return None
        
        # Don't switch if already with someone present
        if current_companion == primary:
            return None
        
        # Don't switch from temporary NPCs (let player finish interaction)
        # This would need is_temporary check from outside
        
        return primary
    
    def get_schedule_summary(self, npc_name: str) -> str:
        """Get human-readable schedule for display.
        
        Args:
            npc_name: Name of the NPC
            
        Returns:
            Formatted schedule string
        """
        schedule = self._schedules.get(npc_name)
        if not schedule:
            return f"No schedule found for {npc_name}"
        
        lines = [f"Routine di {npc_name}:"]
        for time_slot, entry in schedule.schedules.items():
            icon = {
                TimeOfDay.MORNING: "[M]",
                TimeOfDay.AFTERNOON: "[P]",
                TimeOfDay.EVENING: "[S]",
                TimeOfDay.NIGHT: "[N]",
            }.get(time_slot, "[-]")
            time_slot_str = time_slot.value if hasattr(time_slot, 'value') else str(time_slot)
            lines.append(f"  {icon} {time_slot_str}: {entry.activity} @ {entry.location}")
        
        return "\n".join(lines)
    
    def get_all_scheduled_npcs(self) -> List[str]:
        """Get list of all NPCs that have schedules.

        V4.2: Generic method used by PhaseManager to iterate over
        all scheduled NPCs without hardcoding names.

        Returns:
            List of NPC names with schedules
        """
        return list(self._schedules.keys())

    def get_entry(self, npc_name: str, time_of_day=None) -> Optional["ScheduleEntry"]:
        """Get schedule entry for an NPC at a given time."""
        schedule = self._schedules.get(npc_name)
        if not schedule:
            return None
        tod = time_of_day if time_of_day is not None else self.game_state.time_of_day
        return schedule.get_current(tod)

    def who_is_here(self, location_id: str, time_of_day=None) -> Optional[str]:
        """Return the primary NPC scheduled at location_id (for auto-switch after movement)."""
        return self.get_primary_npc(location_id)
