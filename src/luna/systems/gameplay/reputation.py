"""Reputation System - Faction standing.

Tracks reputation with different factions/groups.
"""
from __future__ import annotations

from typing import Any, Dict

from luna.systems.gameplay.base import GameplaySystem


class FactionStanding:
    """Reputation with a faction."""
    
    def __init__(
        self,
        faction_id: str,
        value: int = 0,
        description: str = "",
    ) -> None:
        self.faction_id = faction_id
        self.value = max(-100, min(100, value))  # Clamp -100 to 100
        self.description = description
    
    def change(self, amount: int) -> int:
        """Change reputation."""
        self.value = max(-100, min(100, self.value + amount))
        return self.value
    
    @property
    def tier(self) -> str:
        """Get reputation tier."""
        if self.value <= -80:
            return "hated"
        elif self.value <= -40:
            return "disliked"
        elif self.value <= 40:
            return "neutral"
        elif self.value <= 80:
            return "liked"
        else:
            return "revered"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "faction_id": self.faction_id,
            "value": self.value,
            "description": self.description,
        }


class ReputationSystem(GameplaySystem):
    """Faction reputation system.
    
    Config options:
        - factions: Dict of faction_id -> {name, description}
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        self._factions: Dict[str, FactionStanding] = {}
        
        super().__init__(config)
    
    @property
    def name(self) -> str:
        return "reputation"
    
    def _initialize(self) -> None:
        """Initialize factions."""
        for faction_id, data in self.config.get("factions", {}).items():
            self._factions[faction_id] = FactionStanding(
                faction_id=faction_id,
                value=data.get("starting", 0),
                description=data.get("description", ""),
            )
    
    def get_reputation(self, faction_id: str) -> int:
        """Get reputation value."""
        if faction_id not in self._factions:
            return 0
        return self._factions[faction_id].value
    
    def change_reputation(self, faction_id: str, amount: int) -> int:
        """Change reputation with faction."""
        if faction_id not in self._factions:
            return 0
        return self._factions[faction_id].change(amount)
    
    def get_tier(self, faction_id: str) -> str:
        """Get reputation tier."""
        if faction_id not in self._factions:
            return "neutral"
        return self._factions[faction_id].tier
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_active": self.is_active,
            "factions": {k: v.to_dict() for k, v in self._factions.items()},
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        super().from_dict(data)
        self._factions = {
            k: FactionStanding(**v) for k, v in data.get("factions", {}).items()
        }
