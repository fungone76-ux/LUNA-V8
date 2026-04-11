"""Global Events System - Dynamic world events.

Manages global events like weather, school events, social situations.
Events activate based on conditions (time, location, random) and affect gameplay.
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum


class EventTriggerType(Enum):
    """Types of event triggers."""
    RANDOM = "random"           # Random chance per turn
    TIME_BASED = "time"         # Specific time of day
    LOCATION_BASED = "location"  # Player in specific location
    AFFINITY_BASED = "affinity"  # Affinity threshold reached
    FLAG_BASED = "flag"         # Specific flag set
    SCHEDULED = "scheduled"     # Specific turn number


@dataclass
class GlobalEventInstance:
    """An active global event instance."""
    event_id: str
    name: str
    description: str
    icon: str = "🌍"
    duration_turns: int = 5
    remaining_turns: int = 5
    effects: Dict[str, Any] = field(default_factory=dict)
    narrative_prompt: str = ""  # Template for LLM context
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "duration_turns": self.duration_turns,
            "remaining_turns": self.remaining_turns,
            "effects": self.effects,
            "narrative_prompt": self.narrative_prompt,
        }


class GlobalEventManager:
    """Manages global events in the world.
    
    Events can be triggered by:
    - Random chance each turn
    - Specific conditions (time, location, affinity)
    - Story progression (specific turn)
    
    Active events affect:
    - Available actions
    - Character moods
    - Location descriptions
    - Quest triggers
    """
    
    def __init__(self, world: Any) -> None:
        """Initialize event manager.
        
        Args:
            world: World definition with global_events config
        """
        self.world = world
        self.event_definitions = getattr(world, 'global_events', {})
        
        # Active events
        self.active_events: Dict[str, GlobalEventInstance] = {}
        
        # Event history (to prevent immediate re-trigger)
        self.event_history: Dict[str, int] = {}  # event_id -> last_turn_ended
        
        # Current turn for tracking
        self._current_turn = 0
        
        # Callback when event activates/deactivates
        self.on_event_changed: Optional[Callable[[Optional[GlobalEventInstance]], None]] = None
        
        logger.debug(f"[GlobalEventManager] Loaded {len(self.event_definitions)} event definitions")
    
    # Maximum number of simultaneously active global events
    MAX_ACTIVE_EVENTS = 1
    # First turn events can fire (avoids startup burst)
    MIN_ACTIVATION_TURN = 1

    def check_and_activate_events(
        self,
        game_state: Any,
        force_random: bool = False,
    ) -> List[GlobalEventInstance]:
        """Check conditions and activate events.

        Called each turn by GameEngine.

        Args:
            game_state: Current game state
            force_random: Force random roll even if not turn-based

        Returns:
            List of newly activated events
        """
        self._current_turn = getattr(game_state, 'turn_count', 0)
        newly_activated: List[GlobalEventInstance] = []

        # Don't activate on turn 0 (startup burst prevention)
        if self._current_turn < self.MIN_ACTIVATION_TURN and not force_random:
            self._update_active_events()
            return newly_activated

        # If already at max active events, only update existing ones
        if len(self.active_events) >= self.MAX_ACTIVE_EVENTS:
            self._update_active_events()
            return newly_activated

        # Collect all eligible events (don't activate yet)
        eligible: List[tuple] = []  # (priority, event_id, event_def)

        for event_id, event_def in self.event_definitions.items():
            if event_id in self.active_events:
                continue
            if self._is_in_cooldown(event_id):
                continue
            if self._should_activate(event_def, game_state, force_random):
                priority = getattr(event_def, 'priority', 1) if hasattr(event_def, 'priority') else 1
                eligible.append((priority, event_id, event_def))

        # Activate only the highest-priority eligible event
        if eligible:
            eligible.sort(key=lambda x: x[0], reverse=True)
            _, event_id, event_def = eligible[0]
            event_instance = self._activate_event(event_id, event_def)
            if event_instance:
                newly_activated.append(event_instance)

        # Decrement remaining turns for active events
        self._update_active_events()

        return newly_activated
    
    def _is_in_cooldown(self, event_id: str) -> bool:
        """Check if event is in cooldown period."""
        if event_id not in self.event_history:
            return False
        
        last_ended = self.event_history[event_id]
        turns_since = self._current_turn - last_ended
        
        # Default 10-turn cooldown
        return turns_since < 10
    
    def _should_activate(
        self,
        event_def: Any,
        game_state: Any,
        force_random: bool,
    ) -> bool:
        """Check if event should activate based on conditions."""
        # Handle both GlobalEventDefinition model and raw dict
        if hasattr(event_def, 'title'):
            # GlobalEventDefinition model (from WorldLoader)
            trigger_type = getattr(event_def, 'trigger_type', 'random')
            trigger_chance = getattr(event_def, 'trigger_chance', 0.1)
            trigger_conditions = getattr(event_def, 'trigger_conditions', [])
            allowed_times = getattr(event_def, 'allowed_times', [])
            allowed_locations = getattr(event_def, 'allowed_locations', [])
            min_turn = getattr(event_def, 'min_turn', 0)
        else:
            # Raw dict format (legacy)
            meta = getattr(event_def, 'meta', None)
            if not meta:
                return False
            trigger = getattr(event_def, 'trigger', None)
            if not trigger:
                return random.random() < 0.05
            trigger_type = trigger.get('type', 'random')
            trigger_chance = trigger.get('chance', 0.15)
            trigger_conditions = trigger.get('conditions', [])
            allowed_times = trigger.get('allowed_times', [])
            allowed_locations = trigger.get('allowed_locations', [])
            min_turn = trigger.get('min_turn', 0)
        
        # Check min_turn requirement
        current_turn = getattr(game_state, 'turn_count', 0)
        if current_turn < min_turn:
            return False
        
        # Check location requirement
        if allowed_locations:
            current_loc = getattr(game_state, 'current_location', '')
            location_match = any(
                loc.lower() in str(current_loc).lower() 
                for loc in allowed_locations
            )
            if not location_match:
                return False
        
        # RANDOM trigger
        if trigger_type == 'random':
            if force_random or random.random() < trigger_chance:
                return True
        
        # TIME_BASED trigger (check allowed_times)
        elif trigger_type == 'time' or trigger_type == 'conditional':
            current_time = getattr(game_state, 'time_of_day', None)
            if hasattr(current_time, 'value'):
                current_time = current_time.value
            current_time_str = str(current_time)
            
            # Check allowed_times list
            if allowed_times:
                time_match = any(
                    str(t).lower() == current_time_str.lower() 
                    for t in allowed_times
                )
                if time_match and random.random() < trigger_chance:
                    return True
            
            # Check trigger conditions
            for condition in trigger_conditions:
                if isinstance(condition, dict):
                    # Handle time condition
                    if 'time' in condition:
                        req_time = condition['time']
                        if str(req_time).lower() == current_time_str.lower():
                            if random.random() < trigger_chance:
                                return True
                    # Handle location condition
                    if 'location' in condition:
                        req_loc = condition['location']
                        current_loc = getattr(game_state, 'current_location', '')
                        if req_loc and req_loc.lower() in str(current_loc).lower():
                            if random.random() < trigger_chance:
                                return True
                    # Handle affinity condition
                    if 'affinity' in condition:
                        char = condition.get('target', condition.get('character'))
                        threshold = condition.get('value', condition.get('threshold', 50))
                        affinity = getattr(game_state, 'affinity', {})
                        if char and affinity.get(char, 0) >= threshold:
                            if random.random() < trigger_chance:
                                return True
        
        # LOCATION_BASED trigger
        elif trigger_type == 'location':
            # Check in conditions
            for condition in trigger_conditions:
                if isinstance(condition, dict) and 'location' in condition:
                    req_loc = condition['location']
                    current_loc = getattr(game_state, 'current_location', '')
                    if req_loc and req_loc.lower() in str(current_loc).lower():
                        return random.random() < trigger_chance
        
        # AFFINITY_BASED trigger
        elif trigger_type == 'affinity':
            for condition in trigger_conditions:
                if isinstance(condition, dict) and 'affinity' in condition:
                    char = condition.get('target', condition.get('character'))
                    threshold = condition.get('value', condition.get('threshold', 50))
                    affinity = getattr(game_state, 'affinity', {})
                    if char and affinity.get(char, 0) >= threshold:
                        return random.random() < trigger_chance
        
        # FLAG_BASED trigger
        elif trigger_type == 'flag':
            for condition in trigger_conditions:
                if isinstance(condition, dict) and 'flag' in condition:
                    required_flag = condition['flag']
                    flags = getattr(game_state, 'flags', {})
                    if required_flag and flags.get(required_flag, False):
                        return random.random() < trigger_chance
        
        # SCHEDULED trigger
        elif trigger_type == 'scheduled':
            for condition in trigger_conditions:
                if isinstance(condition, dict) and 'turn' in condition:
                    target_turn = condition['turn']
                    if target_turn and self._current_turn >= target_turn:
                        return True
        
        return False
    
    def _activate_event(self, event_id: str, event_def: Any) -> Optional[GlobalEventInstance]:
        """Activate an event."""
        try:
            # Handle both GlobalEventDefinition model and raw dict
            if hasattr(event_def, 'title'):
                # GlobalEventDefinition model
                name = event_def.title
                description = event_def.description
                icon = '🌍'
                # Get duration from effects
                effects_obj = getattr(event_def, 'effects', None)
                if effects_obj:
                    duration = getattr(effects_obj, 'duration', 5)
                else:
                    duration = 5
                # Use narrative if available, fallback to narrative_prompt
                narrative_prompt = getattr(event_def, 'narrative', '') or getattr(event_def, 'narrative_prompt', '')
                # Get choices if available
                choices = getattr(event_def, 'choices', [])
                # Convert effects to dict for storage
                effects_dict = {}
                if effects_obj:
                    effects_dict = {
                        'duration': getattr(effects_obj, 'duration', 5),
                        'visual_tags': getattr(effects_obj, 'visual_tags', []),
                        'atmosphere_change': getattr(effects_obj, 'atmosphere_change', ''),
                        'affinity_multiplier': getattr(effects_obj, 'affinity_multiplier', 1.0),
                    }
                # Add choices to effects so they're available
                if choices:
                    effects_dict['choices'] = choices
            else:
                # Raw dict format (legacy)
                meta = event_def.get('meta', {})
                name = meta.get('name', meta.get('title', event_id))
                description = meta.get('description', '')
                icon = meta.get('icon', '🌍')
                duration_data = event_def.get('duration', {}).get('turns', 5)
                if isinstance(duration_data, dict):
                    duration = random.randint(duration_data.get('min', 3), duration_data.get('max', 8))
                else:
                    duration = duration_data
                narrative_prompt = event_def.get('narrative', event_def.get('narrative_prompt', ''))
                effects_dict = event_def.get('effects', {})
                # Add choices from root if present
                if 'choices' in event_def:
                    effects_dict['choices'] = event_def['choices']
            
            instance = GlobalEventInstance(
                event_id=event_id,
                name=name,
                description=description,
                icon=icon,
                duration_turns=duration,
                remaining_turns=duration,
                effects=effects_dict,
                narrative_prompt=narrative_prompt,
            )
            
            self.active_events[event_id] = instance
            try:
                logger.debug(f"[GlobalEventManager] ACTIVATED: {instance.name} ({instance.icon})")
            except UnicodeEncodeError:
                logger.debug(f"[GlobalEventManager] ACTIVATED: {instance.name}")
            
            # Notify callback
            if self.on_event_changed:
                self.on_event_changed(instance)
            
            return instance
            
        except Exception as e:
            logger.warning(f"[GlobalEventManager] Error activating {event_id}: {e}")
            return None
    
    def _update_active_events(self) -> None:
        """Update all active events (decrement turns, expire if needed)."""
        expired = []
        
        for event_id, event in self.active_events.items():
            event.remaining_turns -= 1
            
            if event.remaining_turns <= 0:
                expired.append(event_id)
        
        # Remove expired events
        for event_id in expired:
            self._deactivate_event(event_id)
    
    def _deactivate_event(self, event_id: str) -> None:
        """Deactivate an event."""
        if event_id in self.active_events:
            event = self.active_events.pop(event_id)
            self.event_history[event_id] = self._current_turn
            logger.debug(f"[GlobalEventManager] ENDED: {event.name}")
            
            # Notify callback (no active event = None)
            if self.active_events:
                # Return first active event or None
                first_event = next(iter(self.active_events.values()))
                if self.on_event_changed:
                    self.on_event_changed(first_event)
            else:
                if self.on_event_changed:
                    self.on_event_changed(None)
    
    def has_pending_event(self) -> bool:
        """Return True if there is at least one active event."""
        return bool(self.active_events)

    def get_primary_event(self) -> Optional[GlobalEventInstance]:
        """Get the primary/most important active event.
        
        Returns:
            The first active event, or None if no events active
        """
        if not self.active_events:
            return None
        return next(iter(self.active_events.values()))
    
    def get_all_active_events(self) -> List[GlobalEventInstance]:
        """Get all currently active events."""
        return list(self.active_events.values())
    
    def get_event_modifiers(self) -> Dict[str, Any]:
        """Get combined modifiers from all active events.
        
        Returns:
            Dict of modifiers (affinity_bonus, action_restrictions, etc.)
        """
        modifiers = {
            'affinity_multiplier': 1.0,
            'action_restrictions': [],
            'location_modifiers': {},
            'mood_override': None,
        }
        
        for event in self.active_events.values():
            effects = event.effects
            
            # Affinity multiplier
            if 'affinity_multiplier' in effects:
                modifiers['affinity_multiplier'] *= effects['affinity_multiplier']
            
            # Action restrictions
            if 'restrict_actions' in effects:
                modifiers['action_restrictions'].extend(effects['restrict_actions'])
            
            # Mood override (last one wins)
            if 'force_mood' in effects:
                modifiers['mood_override'] = effects['force_mood']
        
        return modifiers
    
    def force_activate_event(self, event_id: str) -> bool:
        """Force activate an event (for debug/story)."""
        if event_id not in self.event_definitions:
            return False
        
        if event_id in self.active_events:
            return False  # Already active
        
        event_def = self.event_definitions[event_id]
        instance = self._activate_event(event_id, event_def)
        return instance is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize active events for saving."""
        return {
            "active_events": {
                eid: evt.to_dict() 
                for eid, evt in self.active_events.items()
            },
            "event_history": self.event_history,
            "current_turn": self._current_turn,
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore active events from save."""
        self.active_events = {}
        for eid, evt_data in data.get("active_events", {}).items():
            self.active_events[eid] = GlobalEventInstance(**evt_data)
        
        self.event_history = data.get("event_history", {})
        self._current_turn = data.get("current_turn", 0)
