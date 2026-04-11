"""NPCStateManager — single authority for querying NPC location, mind, and affinity."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from luna.core.models import GameState, WorldDefinition
    from luna.systems.npc_mind import NPCMind, NPCMindManager

logger = logging.getLogger(__name__)


@dataclass
class NPCSnapshot:
    """Read-only combined view of an NPC's current state."""
    npc_id: str
    name: str
    location: Optional[str]
    affinity: int
    is_active_companion: bool
    # Mind fields (None if NPC has no mind entry)
    current_goal: Optional[str] = None
    dominant_emotion: Optional[str] = None
    has_burning_unspoken: bool = False


class NPCStateManager:
    """
    Single authority for querying NPC state across the three sources:
      - game_state.npc_locations  (physical location overrides)
      - NPCMindManager            (goals, emotions, unspoken items)
      - game_state.affinity       (player relationship score)

    Write operations delegate to game_state so it remains the data source of truth.
    This class does NOT replace those sources — it provides a unified read/write API
    for code that needs cross-source queries (e.g. "who is at this location and unhappy?").
    """

    def __init__(
        self,
        mind_manager: "NPCMindManager",
        world: Optional["WorldDefinition"] = None,
    ) -> None:
        self.mind_manager = mind_manager
        self.world = world

    # -------------------------------------------------------------------------
    # Location queries
    # -------------------------------------------------------------------------

    def location_of(self, npc_id: str, game_state: "GameState") -> Optional[str]:
        """Effective location override from game_state (None = use schedule)."""
        return game_state.npc_locations.get(npc_id)

    def npcs_at(
        self,
        location: str,
        game_state: "GameState",
        *,
        exclude_active: bool = False,
    ) -> List[str]:
        """NPC IDs whose location override matches `location`."""
        result = []
        for npc_id, npc_loc in game_state.npc_locations.items():
            if exclude_active and npc_id == game_state.active_companion:
                continue
            if npc_loc == location:
                result.append(npc_id)
        return result

    def npcs_near(
        self,
        location: str,
        game_state: "GameState",
    ) -> List[str]:
        """NPC IDs in locations that are directly connected to `location`."""
        connected: List[str] = []
        if self.world:
            loc_def = self.world.locations.get(location)
            if loc_def:
                connected = list(getattr(loc_def, "connected_to", []))
        if not connected:
            return []
        return [
            npc_id
            for npc_id, npc_loc in game_state.npc_locations.items()
            if npc_loc in connected
        ]

    def npcs_offscreen(
        self,
        game_state: "GameState",
    ) -> Dict[str, List[str]]:
        """
        Returns {location: [npc_id, ...]} for all NPCs NOT at player's location
        and NOT the active companion. Useful for off-screen simulation.
        """
        player_loc = game_state.current_location
        active = game_state.active_companion
        grouped: Dict[str, List[str]] = {}
        for npc_id, npc_loc in game_state.npc_locations.items():
            if npc_id == active:
                continue
            if npc_loc == player_loc:
                continue
            grouped.setdefault(npc_loc, []).append(npc_id)
        # Also include mind-tracked NPCs not in npc_locations
        for npc_id in self.mind_manager.minds:
            if npc_id == active or npc_id in game_state.npc_locations:
                continue
            grouped.setdefault("unknown", []).append(npc_id)
        return grouped

    # -------------------------------------------------------------------------
    # Mind access (proxy)
    # -------------------------------------------------------------------------

    def mind(self, npc_id: str) -> Optional["NPCMind"]:
        """Return the NPCMind for npc_id, or None."""
        return self.mind_manager.get(npc_id)

    # -------------------------------------------------------------------------
    # Combined snapshot
    # -------------------------------------------------------------------------

    def snapshot(self, npc_id: str, game_state: "GameState") -> NPCSnapshot:
        """Build a read-only combined view of an NPC's current state."""
        m = self.mind_manager.get(npc_id)
        dom_emo = None
        current_goal = None
        has_burning = False
        if m:
            dom = m.dominant_emotion
            dom_emo = dom.emotion.value if dom else None
            current_goal = m.current_goal.description if m.current_goal else None
            has_burning = m.has_burning_unspoken
        return NPCSnapshot(
            npc_id=npc_id,
            name=m.name if m else npc_id,
            location=self.location_of(npc_id, game_state),
            affinity=game_state.affinity.get(npc_id, 0),
            is_active_companion=(npc_id == game_state.active_companion),
            current_goal=current_goal,
            dominant_emotion=dom_emo,
            has_burning_unspoken=has_burning,
        )

    def all_snapshots(self, game_state: "GameState") -> List[NPCSnapshot]:
        """Snapshot every tracked NPC."""
        return [self.snapshot(npc_id, game_state) for npc_id in self.mind_manager.minds]

    # -------------------------------------------------------------------------
    # Write operations (delegate to game_state)
    # -------------------------------------------------------------------------

    def move(
        self,
        npc_id: str,
        location: str,
        game_state: "GameState",
        ttl_turns: int = 0,
    ) -> None:
        """Move an NPC to a location. ttl_turns > 0 = override expires after N turns."""
        game_state.set_npc_location(npc_id, location, ttl_turns)
        logger.debug("[NPCState] %s → %s (ttl=%d)", npc_id, location, ttl_turns)

    def clear(self, npc_id: str, game_state: "GameState") -> None:
        """Remove location override for npc_id (reverts to schedule)."""
        game_state.clear_npc_location(npc_id)
        logger.debug("[NPCState] %s location cleared", npc_id)
