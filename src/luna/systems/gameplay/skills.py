"""Skills System - Character abilities and checks.

Supports skill-based challenges and progression.
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from luna.systems.gameplay.base import GameplaySystem


class Skill:
    """Character skill."""
    
    def __init__(
        self,
        skill_id: str,
        name: str,
        value: int = 0,
        max_value: int = 100,
    ) -> None:
        self.skill_id = skill_id
        self.name = name
        self.value = value
        self.max_value = max_value
    
    def improve(self, amount: int = 1) -> None:
        """Increase skill value."""
        self.value = min(self.max_value, self.value + amount)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "value": self.value,
            "max_value": self.max_value,
        }


class SkillsSystem(GameplaySystem):
    """Skill-based mechanics system.
    
    Config options:
        - stats: ["strength", "mind", "charisma", ...]
        - dice_type: "d20" | "d6" | "d100"
        - starting_value: Default skill value
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        self._skills: Dict[str, Skill] = {}
        
        super().__init__(config)
    
    @property
    def name(self) -> str:
        return "skills"
    
    def _initialize(self) -> None:
        """Initialize skills from config."""
        stat_list = self.config.get("stats", ["strength", "mind", "charisma"])
        starting_value = self.config.get("starting_value", 10)
        
        for stat_id in stat_list:
            self._skills[stat_id] = Skill(
                skill_id=stat_id,
                name=stat_id.replace("_", " ").title(),
                value=starting_value,
            )
    
    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get skill by ID."""
        return self._skills.get(skill_id)
    
    def get_skill_value(self, skill_id: str) -> int:
        """Get skill value."""
        skill = self._skills.get(skill_id)
        return skill.value if skill else 0
    
    def improve_skill(self, skill_id: str, amount: int = 1) -> bool:
        """Improve a skill."""
        if skill_id not in self._skills:
            return False
        self._skills[skill_id].improve(amount)
        return True
    
    def skill_check(
        self,
        skill_id: str,
        difficulty: int = 10,
    ) -> tuple[bool, int]:
        """Perform skill check.
        
        Args:
            skill_id: Skill to check
            difficulty: Target number to beat
            
        Returns:
            Tuple of (success, roll)
        """
        skill = self._skills.get(skill_id)
        if not skill:
            return False, 0
        
        dice_type = self.config.get("dice_type", "d20")
        dice_max = int(dice_type.replace("d", ""))
        
        roll = random.randint(1, dice_max)
        total = roll + (skill.value // 5)  # Skill bonus
        
        return total >= difficulty, roll
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_active": self.is_active,
            "skills": {k: v.to_dict() for k, v in self._skills.items()},
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        super().from_dict(data)
        self._skills = {
            k: Skill(**v) for k, v in data.get("skills", {}).items()
        }
