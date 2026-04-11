"""Morality System - Karma and ethics.

Tracks moral choices and their consequences.
"""
from __future__ import annotations

from typing import Any, Dict, List

from luna.systems.gameplay.base import GameplaySystem


class MoralitySystem(GameplaySystem):
    """Karma and morality tracking.
    
    Config options:
        - alignment_axes: ["good_evil", "law_chaos"] or custom
        - starting_alignment: Initial values
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        self._alignment: Dict[str, int] = {}
        self._choices: List[Dict[str, Any]] = []
        
        super().__init__(config)
    
    @property
    def name(self) -> str:
        return "morality"
    
    def _initialize(self) -> None:
        """Initialize alignment axes."""
        axes = self.config.get("alignment_axes", ["good_evil", "law_chaos"])
        starting = self.config.get("starting_alignment", {})
        
        for axis in axes:
            self._alignment[axis] = starting.get(axis, 0)
    
    def get_alignment(self, axis: str) -> int:
        """Get alignment value for axis."""
        return self._alignment.get(axis, 0)
    
    def shift_alignment(self, axis: str, amount: int) -> int:
        """Shift alignment.
        
        Returns:
            New value
        """
        if axis not in self._alignment:
            return 0
        
        self._alignment[axis] = max(-100, min(100, self._alignment[axis] + amount))
        return self._alignment[axis]
    
    def record_choice(
        self,
        choice_id: str,
        description: str,
        moral_weight: Dict[str, int],
    ) -> None:
        """Record a moral choice.
        
        Args:
            choice_id: Choice identifier
            description: What happened
            moral_weight: Alignment shifts
        """
        self._choices.append({
            "choice_id": choice_id,
            "description": description,
            "moral_weight": moral_weight,
        })
        
        # Apply shifts
        for axis, amount in moral_weight.items():
            self.shift_alignment(axis, amount)
    
    def get_moral_standing(self) -> str:
        """Get overall moral description."""
        good_evil = self._alignment.get("good_evil", 0)
        law_chaos = self._alignment.get("law_chaos", 0)
        
        # Classic D&D alignments
        if good_evil > 20:
            if law_chaos > 20:
                return "Lawful Good"
            elif law_chaos < -20:
                return "Chaotic Good"
            else:
                return "Neutral Good"
        elif good_evil < -20:
            if law_chaos > 20:
                return "Lawful Evil"
            elif law_chaos < -20:
                return "Chaotic Evil"
            else:
                return "Neutral Evil"
        else:
            if law_chaos > 20:
                return "Lawful Neutral"
            elif law_chaos < -20:
                return "Chaotic Neutral"
            else:
                return "True Neutral"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_active": self.is_active,
            "alignment": self._alignment,
            "choices": self._choices,
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        super().from_dict(data)
        self._alignment = data.get("alignment", {})
        self._choices = data.get("choices", [])
