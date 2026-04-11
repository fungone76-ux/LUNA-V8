"""Luna RPG - Location Models.

Location definitions, instances, and movement models.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from .base import LunaBaseModel
from .enums import LocationState, TimeOfDay


class Location(LunaBaseModel):
    """Location definition from world YAML."""
    id: str
    name: str
    description: str = ""
    visual_style: str = ""
    lighting: str = ""
    connected_to: List[str] = Field(default_factory=list)
    parent_location: Optional[str] = None
    sub_locations: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    requires_item: Optional[str] = None
    requires_flag: Optional[str] = None
    requires_parent: bool = False
    hidden: bool = False
    discovery_hint: str = ""
    available_times: List[TimeOfDay] = Field(default_factory=lambda: list(TimeOfDay))
    closed_description: str = ""
    available_characters: List[str] = Field(default_factory=list)
    companion_can_follow: bool = True
    companion_refuse_message: str = ""
    dynamic_descriptions: Dict[str, str] = Field(default_factory=dict)
    time_descriptions: Dict[str, str] = Field(default_factory=dict)


class LocationInstance(LunaBaseModel):
    """Runtime state of a location."""
    location_id: str
    current_state: LocationState = LocationState.NORMAL
    discovered: bool = True
    custom_description: str = ""
    flags: Dict[str, Any] = Field(default_factory=dict)
    npcs_present: List[str] = Field(default_factory=list)

    def get_effective_description(self, location_def: Location, time_of_day: TimeOfDay) -> str:
        if self.custom_description:
            return self.custom_description
        state_val = self.current_state.value if hasattr(self.current_state, "value") else str(self.current_state)
        if state_val in location_def.dynamic_descriptions:
            return location_def.dynamic_descriptions[state_val]
        time_key = time_of_day.value if hasattr(time_of_day, "value") else str(time_of_day)
        if time_key in location_def.time_descriptions:
            return location_def.time_descriptions[time_key]
        return location_def.description


class LocationTransition(LunaBaseModel):
    """Transition description between locations."""
    from_location: str = ""
    to_location: str = ""
    description: str = ""


class MovementRequest(LunaBaseModel):
    """Request to move to a new location."""
    target_location: str
    force: bool = False


class MovementResponse(LunaBaseModel):
    """Result of a movement attempt."""
    success: bool
    new_location: str = ""
    transition_text: str = ""
    block_reason: str = ""
    block_description: str = ""
    companion_left_behind: bool = False
    companion_left_message: str = ""


class ScheduleEntry(LunaBaseModel):
    """Companion schedule entry."""
    time_slot: str
    location: str
    activity: str = ""
    outfit: Optional[str] = None
