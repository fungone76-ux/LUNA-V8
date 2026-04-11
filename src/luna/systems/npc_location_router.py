"""NPC Location Router — M3 of NPC Secondary Activation System.

Routes player input like "vado dall'infermiera" to the correct location,
checking NPC availability via schedule.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from luna.core.models import GameState, WorldDefinition

logger = logging.getLogger(__name__)


def _get_value(obj, key: str, default=None):
    """Safely get value from object or dict."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@dataclass
class RouteResult:
    """Result of location routing."""
    npc_id: str
    npc_display_name: str
    location_id: str
    was_scheduled: bool  # True if NPC is there by schedule, False if spawn_locations


class NpcLocationRouter:
    """Routes player movement intents to NPC locations.
    
    Handles patterns like:
    - "vado da [alias]" → NPC spawn location
    - "vado in [location]" → that location (already handled elsewhere)
    - "cerco [alias]" → NPC location by current schedule
    """
    
    def __init__(self, world: "WorldDefinition") -> None:
        self.world = world
        # Compile patterns for routing detection
        self._patterns = [
            re.compile(r"\b(?:vado|vado\s+da|cerco|trova|dove\s+e|cerco)\s+(?:da\s+)?(.+)", re.IGNORECASE),
            re.compile(r"\b(?:andare|andiamo|spostarsi)\s+(?:da|in)\s+(.+)", re.IGNORECASE),
        ]
    
    def resolve(
        self, 
        player_input: str, 
        game_state: "GameState"
    ) -> Optional[RouteResult]:
        """Resolve player input to a route if it mentions an NPC.
        
        Args:
            player_input: The text input from player
            game_state: Current game state (for location/time checks)
            
        Returns:
            RouteResult if an NPC was found and is accessible, None otherwise
        """
        if not self.world or not game_state:
            return None
            
        # Try to extract potential target from input
        target_name = self._extract_target(player_input)
        if not target_name:
            return None
        
        # Search through npc_templates for matching alias
        for npc_id, npc_def in self.world.npc_templates.items():
            # Check if target matches name or any alias
            npc_name = _get_value(npc_def, 'name', '')
            aliases = [npc_name.lower()] if npc_name else []
            aliases.extend([a.lower() for a in _get_value(npc_def, 'aliases', [])])
            
            if target_name.lower() in aliases:
                # Found matching NPC, check if accessible
                location_id = self._get_npc_location(npc_def, game_state)
                if location_id:
                    # Check if player is already there
                    if location_id == game_state.current_location:
                        logger.debug("[LocationRouter] Player already at %s", location_id)
                        return None
                    
                    # Check for required flags
                    requires_flag = _get_value(npc_def, 'requires_flag', None)
                    if requires_flag and not game_state.flags.get(requires_flag):
                        logger.debug("[LocationRouter] Missing flag %s for %s", requires_flag, npc_id)
                        return None
                    
                    logger.info("[LocationRouter] Routing to %s via %s", location_id, npc_id)
                    return RouteResult(
                        npc_id=npc_id,
                        npc_display_name=_get_value(npc_def, 'name', npc_id),
                        location_id=location_id,
                        was_scheduled=self._is_scheduled_presence(npc_def, game_state)
                    )
        
        return None
    
    # Italian articles/prepositions to strip from extracted target
    _ARTICLES = re.compile(
        r"^(?:dall[ao]?'?\s*|dell[ao]?'?\s*|dal\s+|del\s+|dalla\s+|della\s+|"
        r"lo\s+|la\s+|le\s+|gli\s+|il\s+|i\s+|l'|un[ao]?\s+)",
        re.IGNORECASE,
    )

    def _extract_target(self, player_input: str) -> Optional[str]:
        """Extract potential target name from player input, stripping Italian articles."""
        for pattern in self._patterns:
            match = pattern.search(player_input)
            if match:
                target = match.group(1).strip().lower()
                # Strip Italian articles/prepositions at the start
                target = self._ARTICLES.sub("", target).strip()
                # Clean up common trailing suffixes
                target = re.sub(r"\s+(per|con|da)\s+.+", "", target)
                return target if target else None
        return None
    
    def _get_npc_location(self, npc_def, game_state: "GameState") -> Optional[str]:
        """Get the current location of an NPC based on schedule or spawn_locations."""
        current_time = game_state.time_of_day
        if isinstance(current_time, str):
            from luna.core.models import TimeOfDay
            try:
                current_time = TimeOfDay(current_time)
            except ValueError:
                current_time = TimeOfDay.MORNING
        
        # Check schedule availability — npc_template schedules are descriptive text,
        # not location IDs. We use them only to verify the NPC is accessible now.
        # Location routing always uses spawn_locations.
        schedule = _get_value(npc_def, 'schedule', None)
        if schedule:
            time_key = current_time.value if hasattr(current_time, 'value') else str(current_time)
            if schedule and time_key not in schedule:
                # NPC has a schedule but is not listed for this time — not accessible
                logger.debug("[LocationRouter] NPC not accessible at %s", time_key)
                return None
            # Schedule entry is descriptive text (not location ID) — fall through to spawn_locations
        
        # Use spawn_locations
        spawn_locs = _get_value(npc_def, 'spawn_locations', [])
        if spawn_locs:
            # For scheduled NPCs, pick based on time if multiple locations
            if len(spawn_locs) > 1 and schedule:
                time_str = current_time.value if hasattr(current_time, 'value') else str(current_time)
                # Simple rotation based on time
                time_index = ["Morning", "Afternoon", "Evening", "Night"].index(time_str) if time_str in ["Morning", "Afternoon", "Evening", "Night"] else 0
                return spawn_locs[time_index % len(spawn_locs)]
            return spawn_locs[0]
        
        return None
    
    def _is_scheduled_presence(self, npc_def, game_state: "GameState") -> bool:
        """Check if NPC presence is due to schedule (True) or static spawn (False)."""
        schedule = _get_value(npc_def, 'schedule', None)
        if not schedule:
            return False
        
        current_time = game_state.time_of_day
        time_str = current_time.value if hasattr(current_time, 'value') else str(current_time)
        return time_str in schedule
