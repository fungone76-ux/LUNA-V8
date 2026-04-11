"""Dynamic Events System - Random and Daily Events.

Manages random exploratory events and daily routine events.
Integrates with GameEngine to provide dynamic world interactions.
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

from luna.core.models import GameState, TimeOfDay


class EventType(str, Enum):
    """Types of dynamic events."""
    RANDOM = "random"
    DAILY = "daily"


class EventStatus(str, Enum):
    """Status of an event instance."""
    PENDING = "pending"      # Waiting for player choice
    COMPLETED = "completed"  # Player responded
    EXPIRED = "expired"      # Time ran out


@dataclass
class EventChoice:
    """A choice in an event."""
    text: str
    effect: Dict[str, Any] = field(default_factory=dict)
    followup: str = ""
    condition: Optional[Dict[str, Any]] = None
    check: Optional[Dict[str, Any]] = None
    success_text: str = ""
    failure_text: str = ""


@dataclass
class EventEffect:
    """An effect to apply."""
    type: str
    stat: str = ""
    value: int = 0
    text: str = ""
    item: str = ""
    quantity: int = 1
    flag: str = ""


@dataclass
class EventDefinition:
    """Definition of a random or daily event."""
    event_id: str
    event_type: EventType
    narrative: str
    location: Optional[str] = None
    locations: List[str] = field(default_factory=list)
    time: Optional[TimeOfDay] = None
    times: List[TimeOfDay] = field(default_factory=list)
    weight: int = 10
    priority: int = 1
    repeatable: bool = True
    cooldown: int = 3
    frequency: str = "daily"  # For daily events
    conditions: Dict[str, Any] = field(default_factory=dict)
    choices: List[EventChoice] = field(default_factory=list)
    effects: List[EventEffect] = field(default_factory=list)
    # Lifecycle controls
    max_occurrences: int = 0        # 0 = unlimited
    resolve_flag: str = ""          # flag set on game_state when event fires (blocks re-trigger)
    ttl_turns: int = 3              # turns player has to respond (daily events use this too)
    
    def matches_location(self, location: str) -> bool:
        """Check if event matches given location."""
        if not self.location and not self.locations:
            return True
        if self.location and self.location == location:
            return True
        if self.locations and location in self.locations:
            return True
        return False
    
    def matches_time(self, time_of_day: TimeOfDay) -> bool:
        """Check if event matches given time."""
        if not self.time and not self.times:
            return True
        if self.time and self.time == time_of_day:
            return True
        if self.times and time_of_day in self.times:
            return True
        return False


@dataclass
class EventInstance:
    """An active event instance."""
    event_id: str
    event_type: EventType
    narrative: str
    choices: List[EventChoice]
    effects: List[EventEffect]
    status: EventStatus = EventStatus.PENDING
    turn_started: int = 0
    turn_expires: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "narrative": self.narrative,
            "choices": [
                {
                    "text": c.text,
                    "effect": c.effect,
                    "followup": c.followup,
                }
                for c in self.choices
            ],
            "status": self.status.value,
            "turn_started": self.turn_started,
        }


@dataclass
class EventResult:
    """Result of processing an event."""
    success: bool
    message: str = ""
    narrative: str = ""
    followup: str = ""
    effects_applied: List[Dict[str, Any]] = field(default_factory=list)
    affinity_changes: Dict[str, int] = field(default_factory=dict)
    items_gained: List[str] = field(default_factory=list)
    items_lost: List[str] = field(default_factory=list)
    flags_set: Dict[str, Any] = field(default_factory=dict)
    stat_changes: Dict[str, int] = field(default_factory=dict)
    continue_to_normal_turn: bool = True


class DynamicEventManager:
    """Manages random and daily events.
    
    Features:
    - Random events based on location, weight, and conditions
    - Daily events based on time of day
    - Cooldown tracking to prevent repetition
    - Choice handling with stat checks and effects
    """
    
    def __init__(self, world: Any) -> None:
        """Initialize event manager.
        
        Args:
            world: World definition with random_events and daily_events
        """
        self.world = world
        
        # Event definitions
        self.random_events: Dict[str, EventDefinition] = {}
        self.daily_events: Dict[str, EventDefinition] = {}
        
        # Runtime state
        self.cooldowns: Dict[str, int] = {}  # event_id -> turns remaining
        self.completed_events: set = set()   # Non-repeatable events completed
        self.current_event: Optional[EventInstance] = None
        self.event_history: List[str] = []   # Last N events for variety
        
        # Daily event tracking (prevents duplicates in same day)
        self.daily_events_triggered: set = set()
        self.last_day_check: Optional[TimeOfDay] = None
        
        # Grace period after skipping an event (prevents immediate new event)
        self.skip_grace_period: int = 0  # Turns to wait before checking new events

        # Occurrence tracking: event_id -> how many times it has fired
        self.occurrence_counts: Dict[str, int] = {}
        
        # Load events from world
        self._load_events()
        
        logger.debug(f"[DynamicEventManager] Loaded {len(self.random_events)} random, "
                     f"{len(self.daily_events)} daily events")
    
    def _load_events(self) -> None:
        """Load event definitions from world."""
        # Load random events
        random_data = getattr(self.world, 'random_events', {})
        if isinstance(random_data, dict):
            for evt_id, evt_data in random_data.items():
                try:
                    event = self._parse_event_definition(evt_id, evt_data, EventType.RANDOM)
                    if event:
                        self.random_events[evt_id] = event
                except Exception as e:
                    logger.warning(f"[DynamicEventManager] Error loading random event {evt_id}: {e}")
        
        # Load daily events
        daily_data = getattr(self.world, 'daily_events', {})
        if isinstance(daily_data, dict):
            for evt_id, evt_data in daily_data.items():
                try:
                    event = self._parse_event_definition(evt_id, evt_data, EventType.DAILY)
                    if event:
                        self.daily_events[evt_id] = event
                except Exception as e:
                    logger.warning(f"[DynamicEventManager] Error loading daily event {evt_id}: {e}")
    
    def _parse_event_definition(
        self,
        event_id: str,
        data: Dict[str, Any],
        event_type: EventType,
    ) -> Optional[EventDefinition]:
        """Parse event definition from YAML data."""
        # Parse narrative
        narrative = data.get('narrative', data.get('text', ''))
        if not narrative:
            return None
        
        # Parse location(s) - support both direct and trigger.allowed_locations
        location = data.get('location')
        locations = data.get('locations', [])
        if isinstance(locations, str):
            locations = [locations]
        
        # Parse time(s) - support both 'time', 'time_slot', and 'trigger.allowed_times'
        time = None
        times = []
        
        # Check for 'time' or 'time_slot' (daily events use time_slot)
        time_value = data.get('time') or data.get('time_slot')
        
        if time_value:
            if isinstance(time_value, str):
                try:
                    time = TimeOfDay(time_value)
                except ValueError:
                    pass
            elif isinstance(time_value, list):
                for t in time_value:
                    try:
                        times.append(TimeOfDay(t))
                    except ValueError:
                        pass
        
        # Also check for 'times' array
        if 'times' in data:
            for t in data['times']:
                try:
                    times.append(TimeOfDay(t))
                except ValueError:
                    pass
        
        # Parse trigger section (random events use trigger.allowed_times and trigger.allowed_locations)
        trigger = data.get('trigger', {})
        if trigger:
            # Parse allowed_times from trigger
            allowed_times = trigger.get('allowed_times', [])
            if isinstance(allowed_times, str):
                allowed_times = [allowed_times]
            for t in allowed_times:
                try:
                    times.append(TimeOfDay(t))
                except ValueError:
                    pass
            
            # Parse allowed_locations from trigger
            allowed_locations = trigger.get('allowed_locations', [])
            if isinstance(allowed_locations, str):
                allowed_locations = [allowed_locations]
            if allowed_locations:
                if isinstance(locations, list):
                    locations.extend(allowed_locations)
                else:
                    locations = list(allowed_locations)
        
        # Parse choices
        choices = []
        for choice_data in data.get('choices', []):
            choice = EventChoice(
                text=choice_data.get('text', ''),
                effect=choice_data.get('effect', {}),
                followup=choice_data.get('followup', choice_data.get('success', '')),
                condition=choice_data.get('condition'),
                check=choice_data.get('check'),
                success_text=choice_data.get('success', ''),
                failure_text=choice_data.get('failure', ''),
            )
            choices.append(choice)
        
        # Parse effects (for daily events)
        effects = []
        for effect_data in data.get('effects', []):
            if isinstance(effect_data, dict):
                effect = EventEffect(
                    type=effect_data.get('type', 'none'),
                    stat=effect_data.get('stat', ''),
                    value=effect_data.get('value', 0),
                    text=effect_data.get('text', ''),
                    item=effect_data.get('item', ''),
                    quantity=effect_data.get('quantity', 1),
                    flag=effect_data.get('flag', ''),
                )
                effects.append(effect)
        
        # Parse conditions and trigger data
        conditions = data.get('conditions', {})
        
        # Parse trigger section for random events
        trigger = data.get('trigger', {})
        
        # Convert chance (0.0-1.0) to weight (1-100)
        weight = data.get('weight', 10)
        if trigger and 'chance' in trigger:
            # Convert probability to weight (e.g., 0.25 -> 25)
            weight = int(trigger['chance'] * 100)
        
        # Add min_turn to conditions
        if trigger and 'min_turn' in trigger:
            conditions['min_turn'] = trigger['min_turn']
        
        return EventDefinition(
            event_id=event_id,
            event_type=event_type,
            narrative=narrative,
            location=location,
            locations=locations,
            time=time,
            times=times,
            weight=weight,
            priority=data.get('priority', 1),
            repeatable=data.get('repeatable', True),
            cooldown=data.get('cooldown', 3),
            frequency=data.get('frequency', 'daily'),
            conditions=conditions,
            choices=choices,
            effects=effects,
            max_occurrences=data.get('max_occurrences', 0),
            resolve_flag=data.get('resolve_flag', ''),
            ttl_turns=data.get('ttl_turns', 3),
        )
    
    def check_for_event(
        self,
        game_state: GameState,
        force_random: bool = False,
    ) -> Optional[EventInstance]:
        """Check if an event should trigger.
        
        Args:
            game_state: Current game state
            force_random: Force a random check even if not normally triggered
            
        Returns:
            Event instance if one triggers, None otherwise
        """
        # If there's a current pending event, don't start another
        if self.current_event and self.current_event.status == EventStatus.PENDING:
            return self.current_event
        
        # Check grace period (after user skipped an event, wait before offering new ones)
        if self.skip_grace_period > 0:
            logger.warning(f"[DynamicEventManager] Grace period active ({self.skip_grace_period} turns remaining), skipping event check")
            self.skip_grace_period -= 1
            return None
        
        # Check for daily event first (higher priority)
        daily = self._check_daily_event(game_state)
        if daily:
            self.current_event = daily
            return daily
        
        # Then check for random event
        if force_random or self._should_check_random():
            random_evt = self._check_random_event(game_state)
            if random_evt:
                self.current_event = random_evt
                return random_evt
        
        return None
    
    def _check_daily_event(self, game_state: GameState) -> Optional[EventInstance]:
        """Check for daily event based on time."""
        current_time = game_state.time_of_day
        
        # Reset daily events if time changed significantly
        if self.last_day_check != current_time:
            self.daily_events_triggered.clear()
            self.last_day_check = current_time
        
        # Find matching daily events
        candidates = []
        logger.debug(f"[_check_daily_event] Checking {len(self.daily_events)} daily events, triggered: {self.daily_events_triggered}")
        for evt_id, evt_def in self.daily_events.items():
            # Skip if already triggered this time period
            if evt_id in self.daily_events_triggered:
                logger.warning(f"[_check_daily_event] Skipping {evt_id} - already triggered")
                continue

            # Skip if max_occurrences reached
            if evt_def.max_occurrences > 0:
                if self.occurrence_counts.get(evt_id, 0) >= evt_def.max_occurrences:
                    continue

            # Skip if resolve_flag already set
            if evt_def.resolve_flag:
                flags = getattr(game_state, 'flags', {})
                if flags.get(evt_def.resolve_flag, False):
                    continue

            # Check time match
            if not evt_def.matches_time(current_time):
                continue

            # Check location
            if not evt_def.matches_location(game_state.current_location):
                continue

            # Check conditions
            if not self._check_conditions(evt_def, game_state):
                continue

            candidates.append(evt_def)
        
        if not candidates:
            return None
        
        # Sort by priority and pick highest
        candidates.sort(key=lambda e: e.priority, reverse=True)
        selected = candidates[0]
        
        # Mark as triggered
        self.daily_events_triggered.add(selected.event_id)

        return EventInstance(
            event_id=selected.event_id,
            event_type=EventType.DAILY,
            narrative=selected.narrative,
            choices=selected.choices,
            effects=selected.effects,
            status=EventStatus.PENDING,
            turn_started=game_state.turn_count,
            turn_expires=game_state.turn_count + selected.ttl_turns,
        )
    
    def _check_random_event(self, game_state: GameState) -> Optional[EventInstance]:
        """Check for random event based on weights."""
        # Update cooldowns
        self._update_cooldowns()
        
        # Find eligible events
        candidates = []
        weights = []
        
        for evt_id, evt_def in self.random_events.items():
            # Skip if on cooldown
            if evt_id in self.cooldowns:
                continue

            # Skip if not repeatable and already completed
            if not evt_def.repeatable and evt_id in self.completed_events:
                continue

            # Skip if max_occurrences reached
            if evt_def.max_occurrences > 0:
                if self.occurrence_counts.get(evt_id, 0) >= evt_def.max_occurrences:
                    continue

            # Skip if resolve_flag already set
            if evt_def.resolve_flag:
                flags = getattr(game_state, 'flags', {})
                if flags.get(evt_def.resolve_flag, False):
                    continue

            # Skip if recently seen (for variety)
            if evt_id in self.event_history:
                continue
            
            # Check location
            if not evt_def.matches_location(game_state.current_location):
                continue
            
            # Check time
            if not evt_def.matches_time(game_state.time_of_day):
                continue
            
            # Check conditions
            if not self._check_conditions(evt_def, game_state):
                continue
            
            candidates.append(evt_def)
            weights.append(evt_def.weight)
        
        if not candidates:
            return None
        
        # Weighted random selection
        selected = random.choices(candidates, weights=weights, k=1)[0]
        
        # Set cooldown
        self.cooldowns[selected.event_id] = selected.cooldown
        
        # Add to history
        self.event_history.append(selected.event_id)
        if len(self.event_history) > 10:
            self.event_history.pop(0)
        
        # Track if not repeatable
        if not selected.repeatable:
            self.completed_events.add(selected.event_id)
        
        return EventInstance(
            event_id=selected.event_id,
            event_type=EventType.RANDOM,
            narrative=selected.narrative,
            choices=selected.choices,
            effects=selected.effects,
            status=EventStatus.PENDING,
            turn_started=game_state.turn_count,
            turn_expires=game_state.turn_count + 3,  # 3 turns to respond
        )
    
    def _should_check_random(self) -> bool:
        """Determine if we should check for random event this turn."""
        # Base 15% chance per turn
        return random.random() < 0.15
    
    def _check_conditions(self, event_def: EventDefinition, game_state: GameState) -> bool:
        """Check if event conditions are met."""
        conditions = event_def.conditions
        if not conditions:
            return True
        
        # Check affinity conditions
        for key, value in conditions.items():
            if key.startswith('affinity_'):
                companion = key.replace('affinity_', '')
                affinity = game_state.affinity.get(companion, 0)
                if isinstance(value, str) and value.startswith('>='):
                    threshold = int(value[2:])
                    if affinity < threshold:
                        return False
                elif isinstance(value, int):
                    if affinity < value:
                        return False
            
            elif key == 'time':
                if isinstance(value, list):
                    if game_state.time_of_day not in value:
                        return False
            
            elif key == 'location':
                if isinstance(value, list):
                    if game_state.current_location not in value:
                        return False
            
            elif key == 'flag':
                flags = getattr(game_state, 'flags', {})
                if not flags.get(value, False):
                    return False
            
            elif key == 'min_turn':
                # Check minimum turn requirement
                current_turn = getattr(game_state, 'turn_count', 0)
                if current_turn < value:
                    return False
        
        return True
    
    def _update_cooldowns(self) -> None:
        """Decrement all cooldowns."""
        expired = []
        for evt_id, remaining in self.cooldowns.items():
            self.cooldowns[evt_id] = remaining - 1
            if self.cooldowns[evt_id] <= 0:
                expired.append(evt_id)
        
        for evt_id in expired:
            del self.cooldowns[evt_id]
    
    def process_choice(
        self,
        choice_index: int,
        game_state: GameState,
    ) -> EventResult:
        """Process player choice for current event.
        
        Args:
            choice_index: Index of chosen option
            game_state: Current game state
            
        Returns:
            EventResult with effects applied
        """
        if not self.current_event:
            return EventResult(success=False, message="No active event")
        
        if self.current_event.status != EventStatus.PENDING:
            return EventResult(success=False, message="Event already resolved")
        
        if choice_index < 0 or choice_index >= len(self.current_event.choices):
            return EventResult(success=False, message="Invalid choice")
        
        choice = self.current_event.choices[choice_index]
        
        # Mark event as completed
        self.current_event.status = EventStatus.COMPLETED

        # Track occurrence count
        evt_id = self.current_event.event_id
        self.occurrence_counts[evt_id] = self.occurrence_counts.get(evt_id, 0) + 1

        # Set resolve_flag if configured
        evt_def = self.random_events.get(evt_id) or self.daily_events.get(evt_id)
        if evt_def and evt_def.resolve_flag:
            game_state.flags[evt_def.resolve_flag] = True
        # Move to completed if max_occurrences reached
        if evt_def and evt_def.max_occurrences > 0:
            if self.occurrence_counts[evt_id] >= evt_def.max_occurrences:
                self.completed_events.add(evt_id)
        
        # Check condition if present
        if choice.condition:
            can_choose, fail_msg = self._check_choice_condition(choice.condition, game_state)
            if not can_choose:
                return EventResult(success=False, message=fail_msg)
        
        # Perform stat check if present
        success = True
        if choice.check:
            success = self._perform_check(choice.check, game_state)
        
        # Build result
        result = EventResult(
            success=True,
            narrative=self.current_event.narrative,
            followup=choice.followup if success else choice.failure_text,
            continue_to_normal_turn=True,
        )
        
        # Apply effects
        self._apply_effects(choice.effect, result, game_state)
        
        # Apply default effects for daily events
        if self.current_event.event_type == EventType.DAILY:
            for effect in self.current_event.effects:
                self._apply_event_effect(effect, result, game_state)
        
        return result
    
    def _check_choice_condition(
        self,
        condition: Dict[str, Any],
        game_state: GameState,
    ) -> tuple[bool, str]:
        """Check if player meets condition for choice.
        
        Returns:
            (can_choose, error_message)
        """
        # Check item requirement
        if 'item' in condition:
            item_id = condition['item']
            inventory = getattr(game_state.player, 'inventory', [])
            required_qty = condition.get('quantity', 1)
            
            # Simple count - could be enhanced with actual InventorySystem
            if isinstance(inventory, list):
                has_qty = sum(1 for i in inventory if i == item_id)
            else:
                has_qty = 1 if item_id in inventory else 0
            
            if has_qty < required_qty:
                return False, f"Non hai abbastanza {item_id}"
        
        # Check affinity requirement
        if 'affinity' in condition:
            for char, threshold in condition['affinity'].items():
                if game_state.affinity.get(char, 0) < threshold:
                    return False, f"Affinità troppo bassa con {char}"
        
        # Check flag requirement
        if 'flag' in condition:
            flags = getattr(game_state, 'flags', {})
            if not flags.get(condition['flag'], False):
                return False, "Condizione non soddisfatta"
        
        return True, ""
    
    def _perform_check(
        self,
        check: Dict[str, Any],
        game_state: GameState,
    ) -> bool:
        """Perform a stat check.
        
        Args:
            check: Dict with 'stat' and 'difficulty'
            game_state: Current game state
            
        Returns:
            True if check passed
        """
        stat = check.get('stat', 'mind')
        difficulty = check.get('difficulty', 10)
        
        # Get stat value
        player = game_state.player
        stat_value = getattr(player, stat, 10)
        
        # Roll d20
        roll = random.randint(1, 20)
        total = roll + (stat_value - 10) // 2  # Simple modifier
        
        return total >= difficulty
    
    def _apply_effects(
        self,
        effect_dict: Dict[str, Any],
        result: EventResult,
        game_state: GameState,
    ) -> None:
        """Apply effects from choice."""
        # FIX: Handle case where effect is not a dict
        if not effect_dict:
            return
        if isinstance(effect_dict, str):
            # Handle string effects as special narrative flags
            logger.debug(f"[DynamicEvent] String effect detected: {effect_dict}")
            self._apply_string_effect(effect_dict, result, game_state)
            return
        
        for key, value in effect_dict.items():
            if key == 'affinity_all':
                for companion in game_state.affinity:
                    result.affinity_changes[companion] = value
            
            elif key.startswith('affinity_'):
                companion = key.replace('affinity_', '')
                result.affinity_changes[companion] = value
            
            elif key == 'add_item':
                if isinstance(value, str):
                    result.items_gained.append(value)
                elif isinstance(value, list):
                    result.items_gained.extend(value)
            
            elif key == 'remove_item':
                if isinstance(value, str):
                    result.items_lost.append(value)
            
            elif key == 'energy':
                result.stat_changes['energy'] = value
            
            elif key == 'health':
                result.stat_changes['health'] = value
            
            elif key == 'set_flag':
                result.flags_set[value] = True
            
            elif key == 'reputation':
                result.stat_changes['reputation'] = value
            
            elif key == 'karma':
                result.stat_changes['karma'] = value
    
    def _apply_string_effect(
        self,
        effect_name: str,
        result: EventResult,
        game_state: GameState,
    ) -> None:
        """Apply string-based narrative effects (e.g., 'obedient', 'rebel').
        
        These effects set flags that can influence future interactions.
        """
        # Map of string effects to their mechanical outcomes
        effect_mapping = {
            'obedient': {
                'flag': 'obedient_attitude',
                'affinity_change': {'authority': 2},  # Positive with authority figures
                'message': 'Gli insegnanti notano il tuo comportamento esemplare.'
            },
            'rebel': {
                'flag': 'rebel_attitude', 
                'affinity_change': {'authority': -2},  # Negative with authority figures
                'message': 'Il preside ti osserva con sospetto.'
            },
            'helpful': {
                'flag': 'helpful_nature',
                'affinity_change': {},
                'message': 'La tua gentilezza non passa inosservata.'
            },
            'selfish': {
                'flag': 'selfish_nature',
                'affinity_change': {},
                'message': 'Qualcuno nota il tuo comportamento egoista.'
            },
        }
        
        if effect_name in effect_mapping:
            mapping = effect_mapping[effect_name]
            # Set flag
            if mapping.get('flag'):
                result.flags_set[mapping['flag']] = True
            # Apply affinity changes
            for companion, value in mapping.get('affinity_change', {}).items():
                if companion == 'authority':
                    # Special case: affects all authority figures
                    for auth in ['preside', 'professoressa', 'segretaria', 'bibliotecaria']:
                        if auth in game_state.affinity:
                            result.affinity_changes[auth] = result.affinity_changes.get(auth, 0) + value
                else:
                    result.affinity_changes[companion] = result.affinity_changes.get(companion, 0) + value
            # Set message
            if mapping.get('message'):
                result.message = mapping['message']
        else:
            # Unknown string effect, just log it
            logger.debug(f"[DynamicEvent] Unknown string effect: {effect_name}")
    
    def _apply_event_effect(
        self,
        effect: EventEffect,
        result: EventResult,
        game_state: GameState,
    ) -> None:
        """Apply an effect from daily event."""
        if effect.type == 'restore_stat':
            result.stat_changes[effect.stat] = effect.value
        
        elif effect.type == 'modify_stat':
            result.stat_changes[effect.stat] = effect.value
        
        elif effect.type == 'message':
            result.message = effect.text
        
        elif effect.type == 'add_item':
            result.items_gained.append(effect.item)
    
    def skip_event(self) -> None:
        """Skip current event without choosing."""
        if self.current_event:
            event_id = self.current_event.event_id
            event_type = self.current_event.event_type
            
            logger.warning(f"[DynamicEventManager] Skipping event: {event_id} (type: {event_type.value})")
            
            # Mark as expired
            self.current_event.status = EventStatus.EXPIRED
            self.current_event = None
            
            # Add cooldown to prevent immediate re-trigger
            if event_type == EventType.DAILY:
                # For daily events, mark as triggered for this time period
                self.daily_events_triggered.add(event_id)
                logger.debug(f"[DynamicEventManager] Added to daily_events_triggered: {event_id}")
            else:
                # For random events, set cooldown
                self.cooldowns[event_id] = 5  # 5 turn cooldown
                logger.debug(f"[DynamicEventManager] Set cooldown for: {event_id}")
            
            # Set grace period - don't offer new events for 5 turns
            # This gives user time to continue conversation normally
            # (Set to 5 instead of 3 because process_turn may be called multiple times)
            self.skip_grace_period = 5
            logger.debug(f"[DynamicEventManager] Set grace period: 3 turns")
    
    def get_current_event(self) -> Optional[EventInstance]:
        """Get current pending event if any."""
        if self.current_event and self.current_event.status == EventStatus.PENDING:
            return self.current_event
        return None
    
    def on_turn_end(self, game_state: GameState) -> None:
        """Process end of turn updates."""
        # Update cooldowns
        self._update_cooldowns()
        
        # Check for expired events
        if self.current_event:
            if (self.current_event.turn_expires and 
                game_state.turn_count >= self.current_event.turn_expires):
                self.current_event.status = EventStatus.EXPIRED
                self.current_event = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize state for saving."""
        return {
            "cooldowns": self.cooldowns,
            "completed_events": list(self.completed_events),
            "event_history": self.event_history,
            "daily_events_triggered": list(self.daily_events_triggered),
            "last_day_check": self.last_day_check.value if self.last_day_check else None,
            "current_event": self.current_event.to_dict() if self.current_event else None,
            "occurrence_counts": self.occurrence_counts,
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore state from save."""
        self.cooldowns = data.get("cooldowns", {})
        self.completed_events = set(data.get("completed_events", []))
        self.event_history = data.get("event_history", [])
        self.daily_events_triggered = set(data.get("daily_events_triggered", []))
        self.occurrence_counts = data.get("occurrence_counts", {})

        last_day = data.get("last_day_check")
        if last_day:
            try:
                self.last_day_check = TimeOfDay(last_day)
            except ValueError:
                self.last_day_check = None

        # current_event is not restored — it will re-trigger naturally next turn
