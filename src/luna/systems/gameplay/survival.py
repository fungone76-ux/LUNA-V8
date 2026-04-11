"""Survival System - Hunger, thirst, rest.

For survival-focused worlds.
"""
from __future__ import annotations

from typing import Any, Dict

from luna.systems.gameplay.base import GameplaySystem


class SurvivalSystem(GameplaySystem):
    """Survival mechanics (hunger, thirst, stamina).
    
    Config options:
        - needs: ["hunger", "thirst", "energy", "sanity"]
        - decay_rate: How fast needs decrease per turn
        - critical_threshold: When effects kick in
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        self._needs: Dict[str, float] = {}
        
        super().__init__(config)
    
    @property
    def name(self) -> str:
        return "survival"
    
    def _initialize(self) -> None:
        """Initialize needs."""
        needs_list = self.config.get("needs", ["hunger", "thirst", "energy"])
        for need in needs_list:
            self._needs[need] = 100.0  # Start full
    
    def get_need(self, need: str) -> float:
        """Get current need value."""
        return self._needs.get(need, 0)
    
    def modify_need(self, need: str, amount: float) -> float:
        """Modify a need value.
        
        Returns:
            New value
        """
        if need not in self._needs:
            return 0
        
        self._needs[need] = max(0, min(100, self._needs[need] + amount))
        return self._needs[need]
    
    def eat(self, amount: int = 20) -> float:
        """Reduce hunger."""
        return self.modify_need("hunger", amount)
    
    def drink(self, amount: int = 20) -> float:
        """Reduce thirst."""
        return self.modify_need("thirst", amount)
    
    def rest(self, amount: int = 30) -> float:
        """Restore energy."""
        return self.modify_need("energy", amount)
    
    def update(self, delta_time: float) -> None:
        """Decay needs over time."""
        decay = self.config.get("decay_rate", 1.0) * delta_time
        for need in self._needs:
            if need in ["hunger", "thirst"]:
                self._needs[need] -= decay
            elif need == "energy":
                self._needs[need] -= decay * 0.5
            self._needs[need] = max(0, self._needs[need])
    
    def get_status_effects(self) -> list[str]:
        """Get current status effects from low needs."""
        effects = []
        threshold = self.config.get("critical_threshold", 20)
        
        for need, value in self._needs.items():
            if value < threshold:
                effects.append(f"low_{need}")
        
        return effects
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_active": self.is_active,
            "needs": self._needs,
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        super().from_dict(data)
        self._needs = data.get("needs", {})
