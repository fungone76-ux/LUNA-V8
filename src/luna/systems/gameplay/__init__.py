"""Gameplay Systems - Dynamic mechanics loader.

Each world can enable/disable different gameplay mechanics.
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

from typing import Any, Dict, Optional, Type

from luna.systems.gameplay.base import GameplaySystem
from luna.systems.gameplay.affinity import AffinitySystem
from luna.systems.gameplay.combat import CombatSystem
from luna.systems.gameplay.inventory import InventorySystem
from luna.systems.gameplay.economy import EconomySystem
from luna.systems.gameplay.skills import SkillsSystem
from luna.systems.gameplay.reputation import ReputationSystem
from luna.systems.gameplay.clues import ClueSystem
from luna.systems.gameplay.survival import SurvivalSystem
from luna.systems.gameplay.morality import MoralitySystem

# Registry of available systems
SYSTEM_REGISTRY: Dict[str, Type[GameplaySystem]] = {
    "affinity": AffinitySystem,
    "combat": CombatSystem,
    "inventory": InventorySystem,
    "economy": EconomySystem,
    "skills": SkillsSystem,
    "reputation": ReputationSystem,
    "clues": ClueSystem,
    "survival": SurvivalSystem,
    "morality": MoralitySystem,
}


def get_system_class(name: str) -> Optional[Type[GameplaySystem]]:
    """Get system class by name.
    
    Args:
        name: System identifier
        
    Returns:
        System class or None if not found
    """
    return SYSTEM_REGISTRY.get(name)


def list_available_systems() -> list[str]:
    """List all available gameplay systems.
    
    Returns:
        List of system identifiers
    """
    return list(SYSTEM_REGISTRY.keys())


def create_system(name: str, config: Dict[str, Any]) -> Optional[GameplaySystem]:
    """Create and initialize a gameplay system.
    
    Args:
        name: System identifier
        config: System configuration from world YAML
        
    Returns:
        Initialized system or None
    """
    system_class = get_system_class(name)
    if not system_class:
        logger.warning(f"Warning: Unknown gameplay system '{name}'")
        return None
    
    try:
        return system_class(config)
    except Exception as e:
        logger.warning(f"Error initializing system '{name}': {e}")
        return None


class GameplayManager:
    """Manages active gameplay systems for current world.
    
    Loads only systems enabled in world configuration.
    """
    
    def __init__(self, systems_config: Dict[str, Dict[str, Any]]) -> None:
        """Initialize gameplay manager.
        
        Args:
            systems_config: Configuration dict from world YAML
                Example: {"combat": {"enabled": true, ...}, ...}
        """
        self.systems: Dict[str, GameplaySystem] = {}
        self.config = systems_config or {}
        
        self._load_systems()
    
    def _load_systems(self) -> None:
        """Load all enabled systems."""
        for name, config in self.config.items():
            if config.get("enabled", False):
                system = create_system(name, config)
                if system:
                    self.systems[name] = system
                    logger.debug(f"[Gameplay] Loaded system: {name}")
    
    def has_system(self, name: str) -> bool:
        """Check if a system is active."""
        return name in self.systems
    
    def get_system(self, name: str) -> Optional[GameplaySystem]:
        """Get active system by name."""
        return self.systems.get(name)
    
    def get_active_systems(self) -> list[str]:
        """Get list of active system names."""
        return list(self.systems.keys())
    
    # Convenience methods for common systems
    @property
    def affinity(self) -> Optional[AffinitySystem]:
        """Get affinity system if active."""
        return self.systems.get("affinity")  # type: ignore
    
    @property
    def combat(self) -> Optional[CombatSystem]:
        """Get combat system if active."""
        return self.systems.get("combat")  # type: ignore
    
    @property
    def inventory(self) -> Optional[InventorySystem]:
        """Get inventory system if active."""
        return self.systems.get("inventory")  # type: ignore
    
    @property
    def economy(self) -> Optional[EconomySystem]:
        """Get economy system if active."""
        return self.systems.get("economy")  # type: ignore
    
    def update(self, delta_time: float) -> None:
        """Update all active systems.
        
        Args:
            delta_time: Time since last update
        """
        for system in self.systems.values():
            if system.is_active:
                system.update(delta_time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize all systems state."""
        return {
            name: system.to_dict()
            for name, system in self.systems.items()
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore systems state."""
        for name, state in data.items():
            if name in self.systems:
                self.systems[name].from_dict(state)
