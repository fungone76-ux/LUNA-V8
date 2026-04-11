"""Event Context Builder - Transforms GlobalEventInstance into LLM-friendly context.

This module builds structured context from active events for transmission to the LLM,
ensuring narrative coherence when world events are active.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import re

from luna.core.models import GameState


@dataclass
class EventContext:
    """Structured event context optimized for LLM consumption.
    
    This dataclass holds processed event data ready to be formatted
    into the system prompt.
    """
    
    # Identity
    event_id: str
    name: str
    icon: str
    
    # Narrative
    atmosphere: str
    narrative: str
    urgency_hint: str  # "beginning", "ongoing", "ending"
    
    # World state changes
    world_state_changes: List[str] = field(default_factory=list)
    
    # Visual generation hints
    visual_tags: List[str] = field(default_factory=list)
    
    # Timing
    remaining_turns: int = 0
    total_turns: int = 0
    
    @property
    def header(self) -> str:
        """Formatted header with icon and name."""
        return f"{self.icon} {self.name}"
    
    @property
    def is_ending_soon(self) -> bool:
        """True if event is in final phase."""
        if self.total_turns == 0:
            return False
        return self.remaining_turns / self.total_turns < 0.34
    
    def to_prompt_section(self) -> str:
        """Convert to formatted prompt section for LLM.
        
        Returns:
            Formatted string ready to insert in system prompt
        """
        lines = [
            "=== ACTIVE WORLD EVENT ===",
            f"{self.header}",
            f"Atmosphere: {self.atmosphere}",
            "",
        ]
        
        # Urgency indicator
        if self.urgency_hint == "beginning":
            lines.append("⚡ The event has just started! The situation is new and unfolding.")
        elif self.urgency_hint == "ending":
            lines.append("⏳ The event is about to end... The situation is returning to normal.")
        
        # Narrative context (most important for LLM)
        if self.narrative:
            lines.extend([
                "",
                "NARRATIVE CONTEXT:",
                self.narrative,
            ])
        
        # World state changes
        if self.world_state_changes:
            lines.extend([
                "",
                "WORLD STATE CHANGES:",
            ] + [f"• {change}" for change in self.world_state_changes])
        
        # Visual notes for image coherence
        if self.visual_tags:
            lines.extend([
                "",
                "VISUAL NOTES:",
                f"Scene should include: {', '.join(self.visual_tags)}",
            ])
        
        lines.append("")  # Trailing newline
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_id": self.event_id,
            "name": self.name,
            "icon": self.icon,
            "atmosphere": self.atmosphere,
            "narrative": self.narrative,
            "urgency": self.urgency_hint,
            "remaining_turns": self.remaining_turns,
            "total_turns": self.total_turns,
            "world_state": self.world_state_changes,
            "visual_tags": self.visual_tags,
        }


class EventContextBuilder:
    """Builds LLM-friendly context from active global events.
    
    This class transforms raw event instances into structured EventContext
    objects with variable substitution and urgency calculation.
    
    Usage:
        builder = EventContextBuilder(world)
        context = builder.build_context(event_instance, game_state)
        prompt_section = context.to_prompt_section()
    """
    
    # Valid placeholders that will be substituted in narrative_prompt
    PLACEHOLDERS = {
        '{current_companion}': lambda gs: gs.active_companion,
        '{location}': lambda gs: gs.current_location,
        '{time}': lambda gs: gs.time_of_day.value if hasattr(gs.time_of_day, 'value') else str(gs.time_of_day),
        '{player_name}': lambda gs: gs.player.name if hasattr(gs, 'player') and gs.player else "Protagonist",
    }
    
    def __init__(self, world: Any) -> None:
        """Initialize builder with world definition.
        
        Args:
            world: World definition containing global_events for lookup
        """
        self.world = world
    
    def build_context(
        self,
        event_instance: Any,  # GlobalEventInstance
        game_state: GameState,
    ) -> EventContext:
        """Build complete event context for LLM.
        
        Args:
            event_instance: Active event instance from GlobalEventManager
            game_state: Current game state for variable substitution
            
        Returns:
            EventContext ready for LLM transmission
        """
        # Get narrative prompt from instance
        narrative_prompt = getattr(event_instance, 'narrative_prompt', '')
        
        # If not in instance, try to get from definition
        if not narrative_prompt and self.world and hasattr(self.world, 'global_events'):
            event_def = self.world.global_events.get(event_instance.event_id)
            if event_def:
                narrative_prompt = getattr(event_def, 'narrative_prompt', '')
        
        # Substitute variables in narrative
        narrative = self._substitute_variables(narrative_prompt, game_state)
        
        # Get effects
        effects = getattr(event_instance, 'effects', {}) or {}
        if not isinstance(effects, dict):
            effects = effects.__dict__ if hasattr(effects, '__dict__') else {}
        
        # Calculate urgency
        duration = getattr(event_instance, 'duration_turns', 0)
        remaining = getattr(event_instance, 'remaining_turns', 0)
        urgency = self._calculate_urgency(remaining, duration)
        
        # Extract world state changes
        world_state = self._extract_world_state_changes(effects)
        
        # Get visual tags
        visual_tags = effects.get('visual_tags', [])
        if not isinstance(visual_tags, list):
            visual_tags = []
        
        # Get atmosphere
        atmosphere = effects.get('atmosphere_change', 'neutral')
        if not atmosphere or not isinstance(atmosphere, str):
            atmosphere = 'neutral'
        
        return EventContext(
            event_id=event_instance.event_id,
            name=event_instance.name,
            icon=getattr(event_instance, 'icon', '🌍'),
            atmosphere=atmosphere,
            narrative=narrative,
            urgency_hint=urgency,
            world_state_changes=world_state,
            visual_tags=visual_tags,
            remaining_turns=remaining,
            total_turns=duration,
        )
    
    def _substitute_variables(self, text: str, game_state: GameState) -> str:
        """Substitute placeholders in text with game state values.
        
        Args:
            text: Template text with placeholders like {current_companion}
            game_state: Current game state
            
        Returns:
            Text with placeholders replaced
        """
        if not text:
            return ""
        
        result = text
        for placeholder, getter in self.PLACEHOLDERS.items():
            try:
                value = getter(game_state)
                result = result.replace(placeholder, str(value))
            except Exception:
                # If substitution fails, leave placeholder as-is
                pass
        
        return result
    
    def _calculate_urgency(self, remaining: int, total: int) -> str:
        """Calculate event urgency phase.
        
        Args:
            remaining: Remaining turns
            total: Total duration in turns
            
        Returns:
            "beginning", "ongoing", or "ending"
        """
        if total <= 0:
            return "ongoing"
        
        ratio = remaining / total
        
        if ratio > 0.7:
            return "beginning"
        elif ratio < 0.34:
            return "ending"
        return "ongoing"
    
    def _extract_world_state_changes(self, effects: Dict[str, Any]) -> List[str]:
        """Extract human-readable world state changes from effects.
        
        Args:
            effects: Event effects dictionary
            
        Returns:
            List of world state change descriptions
        """
        changes: List[str] = []
        
        # Location modifiers
        location_mods = effects.get('location_modifiers', [])
        if isinstance(location_mods, list):
            for mod in location_mods:
                if not isinstance(mod, dict):
                    continue
                
                location = mod.get('location', 'unknown')
                blocked = mod.get('blocked', False)
                message = mod.get('message', '')
                
                if blocked:
                    if message:
                        changes.append(f"Location '{location}' is BLOCKED: {message}")
                    else:
                        changes.append(f"Location '{location}' is currently inaccessible")
        
        # Location lock
        location_lock = effects.get('location_lock')
        if location_lock:
            changes.append(f"Player is confined to '{location_lock}' until event ends")
        
        # Affinity multiplier
        mult = effects.get('affinity_multiplier', 1.0)
        if mult and mult != 1.0:
            if mult > 1.0:
                changes.append(f"Relationships develop faster ({mult}x affinity gain)")
            else:
                changes.append(f"Relationships develop slower ({mult}x affinity gain)")
        
        return changes
    
    def build_combined_context(
        self,
        event_instances: List[Any],
        game_state: GameState,
    ) -> str:
        """Build combined context for multiple active events.
        
        Args:
            event_instances: List of active event instances
            game_state: Current game state
            
        Returns:
            Combined prompt section for all events
        """
        if not event_instances:
            return ""
        
        if len(event_instances) == 1:
            context = self.build_context(event_instances[0], game_state)
            return context.to_prompt_section()
        
        # Multiple events - combine them
        lines = [
            "=== ACTIVE WORLD EVENTS ===",
            f"Multiple events are affecting the world ({len(event_instances)} active):",
            "",
        ]
        
        for i, instance in enumerate(event_instances, 1):
            context = self.build_context(instance, game_state)
            lines.extend([
                f"--- Event {i}: {context.header} ---",
                f"Atmosphere: {context.atmosphere}",
            ])
            
            if context.narrative:
                lines.extend(["Context:", context.narrative])
            
            if context.world_state_changes:
                lines.extend(["Effects:"] + [f"• {s}" for s in context.world_state_changes])
            
            lines.append("")
        
        # Combine visual tags from all events
        all_tags = []
        for instance in event_instances:
            effects = getattr(instance, 'effects', {}) or {}
            if not isinstance(effects, dict):
                effects = effects.__dict__ if hasattr(effects, '__dict__') else {}
            tags = effects.get('visual_tags', [])
            if isinstance(tags, list):
                all_tags.extend(tags)
        
        if all_tags:
            unique_tags = list(dict.fromkeys(all_tags))  # Preserve order, remove duplicates
            lines.extend([
                "COMBINED VISUAL NOTES:",
                f"Scene should include: {', '.join(unique_tags)}",
                "",
            ])
        
        return "\n".join(lines)


def format_event_for_llm(
    event_instance: Any,
    game_state: GameState,
    world: Any,
) -> str:
    """Convenience function to format a single event for LLM.
    
    Args:
        event_instance: Active event instance
        game_state: Current game state
        world: World definition
        
    Returns:
        Formatted prompt section
    """
    builder = EventContextBuilder(world)
    context = builder.build_context(event_instance, game_state)
    return context.to_prompt_section()
