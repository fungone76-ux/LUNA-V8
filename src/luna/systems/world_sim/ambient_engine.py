"""World Simulator — ambient detail generation."""
from __future__ import annotations

import logging
import random
from typing import Any, List, Optional, TYPE_CHECKING

from luna.systems.world_sim.models import AmbientDetail

if TYPE_CHECKING:
    from luna.core.models import WorldDefinition

logger = logging.getLogger(__name__)

_TIME_AMBIENT: dict = {
    "Morning": [
        "La campanella dell'inizio lezioni suona in lontananza",
        "Studenti frettolosi passano nel corridoio",
    ],
    "Afternoon": [
        "Il sole alto filtra dalle finestre",
        "Si sente il mormorio della classe accanto",
    ],
    "Evening": [
        "La scuola si sta svuotando lentamente",
        "I passi nel corridoio si fanno rari",
    ],
    "Night": [
        "Il silenzio avvolge tutto",
        "Solo il ronzio delle luci al neon",
    ],
}

_MAX_AMBIENT_PER_TURN = 3


class AmbientEngine:
    """Generates ambient scene details from location, time, and nearby NPCs."""

    def __init__(self, world: Optional["WorldDefinition"] = None) -> None:
        self.world = world

    def generate(
        self,
        game_state: Any,
        turn: int,
        mind_manager: Any,
    ) -> List[AmbientDetail]:
        details: List[AmbientDetail] = []
        player_loc = game_state.current_location
        time_str = (
            game_state.time_of_day.value
            if hasattr(game_state.time_of_day, "value")
            else str(game_state.time_of_day)
        )

        # Location-based ambient from world definition
        if self.world:
            loc_def = self.world.locations.get(player_loc)
            if loc_def:
                time_descs = getattr(loc_def, "time_descriptions", {})
                if isinstance(time_descs, dict) and time_str in time_descs:
                    details.append(AmbientDetail(
                        description=time_descs[time_str],
                        source="location",
                    ))

        # NPC ambient: sounds from adjacent locations
        for npc_id, mind in mind_manager.minds.items():
            if npc_id == game_state.active_companion:
                continue
            npc_loc = game_state.npc_locations.get(npc_id)
            if not npc_loc:
                continue
            if self.world:
                current_loc_def = self.world.locations.get(player_loc)
                if current_loc_def:
                    connected = getattr(current_loc_def, "connected_to", [])
                    if npc_loc in connected and random.random() < 0.3:
                        loc_name = npc_loc
                        loc_def = self.world.locations.get(npc_loc)
                        if loc_def:
                            loc_name = loc_def.name
                        details.append(AmbientDetail(
                            description=f"Senti {mind.name} da {loc_name}",
                            source="nearby_npc",
                        ))

        # Time-based ambient
        if time_str in _TIME_AMBIENT and random.random() < 0.4:
            details.append(AmbientDetail(
                description=random.choice(_TIME_AMBIENT[time_str]),
                source="time",
            ))

        return details[:_MAX_AMBIENT_PER_TURN]
