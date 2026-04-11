"""Combat System - Turn-based battles.

Supports different combat styles based on world configuration.
"""
from __future__ import annotations

import random
from enum import Enum
from typing import Any, Dict, List, Optional

from luna.systems.gameplay.base import GameplaySystem


class CombatState(Enum):
    """Combat states."""
    INACTIVE = "inactive"
    PLAYER_TURN = "player_turn"
    ENEMY_TURN = "enemy_turn"
    VICTORY = "victory"
    DEFEAT = "defeat"
    ESCAPED = "escaped"


class CombatEntity:
    """Entity in combat (player, enemy, ally)."""
    
    def __init__(
        self,
        entity_id: str,
        name: str,
        hp: int,
        max_hp: int,
        stats: Optional[Dict[str, int]] = None,
        is_player: bool = False,
    ) -> None:
        self.entity_id = entity_id
        self.name = name
        self.hp = hp
        self.max_hp = max_hp
        self.stats = stats or {"strength": 10, "agility": 10, "defense": 10}
        self.is_player = is_player
        self.is_defeated = False
    
    def take_damage(self, amount: int) -> int:
        """Apply damage and return actual damage dealt."""
        damage = max(1, amount - self.stats.get("defense", 0) // 2)
        self.hp = max(0, self.hp - damage)
        if self.hp == 0:
            self.is_defeated = True
        return damage
    
    def heal(self, amount: int) -> None:
        """Restore HP."""
        self.hp = min(self.max_hp, self.hp + amount)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "stats": self.stats,
            "is_player": self.is_player,
            "is_defeated": self.is_defeated,
        }


class CombatAction:
    """Available combat action."""
    
    def __init__(
        self,
        action_id: str,
        name: str,
        damage: int = 0,
        healing: int = 0,
        stat_check: Optional[str] = None,
        description: str = "",
    ) -> None:
        self.action_id = action_id
        self.name = name
        self.damage = damage
        self.healing = healing
        self.stat_check = stat_check
        self.description = description


class CombatSystem(GameplaySystem):
    """Turn-based combat system.
    
    Config options:
        - type: "turn_based" | "real_time" | "choice_based"
        - stats: ["strength", "agility", "magic", ...]
        - dice: "d20" | "d6" | "d100"
        - allow_escape: bool
        - death_penalty: "game_over" | "wounded" | "none"
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        self.state = CombatState.INACTIVE
        self.entities: List[CombatEntity] = []
        self.current_turn = 0
        self.turn_order: List[int] = []  # Indices into entities
        self.combat_log: List[str] = []
        self._actions: Dict[str, CombatAction] = {}
        
        super().__init__(config)
    
    @property
    def name(self) -> str:
        return "combat"
    
    def _validate_config(self) -> None:
        """Validate combat configuration."""
        valid_types = ["turn_based", "real_time", "choice_based"]
        if self.config.get("type") not in valid_types:
            self.config["type"] = "turn_based"
    
    def _initialize(self) -> None:
        """Initialize default actions."""
        self._actions = {
            "attack": CombatAction("attack", "Attack", damage=10, stat_check="strength"),
            "defend": CombatAction("defend", "Defend", description="Reduce incoming damage"),
            "heal": CombatAction("heal", "Heal", healing=15, description="Restore HP"),
        }
        # Add custom actions from config
        for action_data in self.config.get("actions", []):
            action = CombatAction(**action_data)
            self._actions[action.action_id] = action
    
    def start_combat(
        self,
        player: CombatEntity,
        enemies: List[CombatEntity],
        allies: Optional[List[CombatEntity]] = None,
    ) -> None:
        """Start a new combat encounter."""
        self.state = CombatState.PLAYER_TURN
        self.entities = [player] + (allies or []) + enemies
        self.current_turn = 0
        self.combat_log = ["Combat started!"]
        
        # Calculate turn order based on agility
        self.turn_order = sorted(
            range(len(self.entities)),
            key=lambda i: self.entities[i].stats.get("agility", 10),
            reverse=True,
        )
    
    def execute_action(
        self,
        action_id: str,
        actor_index: int,
        target_index: int,
    ) -> Dict[str, Any]:
        """Execute combat action.
        
        Returns:
            Dict with results (success, damage, message)
        """
        if action_id not in self._actions:
            return {"success": False, "message": "Invalid action"}
        
        action = self._actions[action_id]
        actor = self.entities[actor_index]
        target = self.entities[target_index]
        
        result = {"success": True, "damage": 0, "healing": 0, "message": ""}
        
        # Roll for success
        dice_type = self.config.get("dice", "d20")
        dice_max = int(dice_type.replace("d", ""))
        roll = random.randint(1, dice_max)
        
        if action.stat_check:
            stat_bonus = actor.stats.get(action.stat_check, 10) // 2 - 5
            roll += stat_bonus
        
        if roll >= 10:  # Success threshold
            if action.damage > 0:
                damage = target.take_damage(action.damage)
                result["damage"] = damage
                result["message"] = f"{actor.name} hits {target.name} for {damage} damage!"
            elif action.healing > 0:
                actor.heal(action.healing)
                result["healing"] = action.healing
                result["message"] = f"{actor.name} heals for {action.healing} HP!"
            else:
                result["message"] = f"{actor.name} uses {action.name}!"
        else:
            result["success"] = False
            result["message"] = f"{actor.name} misses!"
        
        self.combat_log.append(result["message"])
        self._check_combat_end()
        
        return result
    
    def _check_combat_end(self) -> None:
        """Check if combat has ended."""
        player = next((e for e in self.entities if e.is_player), None)
        enemies = [e for e in self.entities if not e.is_player and not e.is_defeated]
        
        if not player or player.is_defeated:
            self.state = CombatState.DEFEAT
        elif not enemies:
            self.state = CombatState.VICTORY
    
    def next_turn(self) -> None:
        """Advance to next turn."""
        if self.state not in [CombatState.PLAYER_TURN, CombatState.ENEMY_TURN]:
            return
        
        self.current_turn = (self.current_turn + 1) % len(self.turn_order)
        current_entity = self.entities[self.turn_order[self.current_turn]]
        
        if current_entity.is_player:
            self.state = CombatState.PLAYER_TURN
        else:
            self.state = CombatState.ENEMY_TURN
            # Simple AI
            self._enemy_ai()
    
    def _enemy_ai(self) -> None:
        """Simple enemy AI."""
        # Find player
        player_idx = next(
            (i for i, e in enumerate(self.entities) if e.is_player),
            None
        )
        if player_idx is not None:
            self.execute_action("attack", self.turn_order[self.current_turn], player_idx)
            self.next_turn()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_active": self.is_active,
            "state": self.state.value,
            "entities": [e.to_dict() for e in self.entities],
            "current_turn": self.current_turn,
            "combat_log": self.combat_log,
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        super().from_dict(data)
        self.state = CombatState(data.get("state", "inactive"))
        self.current_turn = data.get("current_turn", 0)
        self.combat_log = data.get("combat_log", [])
