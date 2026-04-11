"""Base class for all gameplay systems.

Every gameplay mechanic inherits from GameplaySystem.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class GameplaySystem(ABC):
    """Abstract base class for gameplay mechanics.
    
    Each system represents a distinct gameplay mechanic that can be
    enabled/disabled per world (combat, economy, inventory, etc.)
    
    Attributes:
        name: System identifier
        is_active: Whether system is currently active
        config: Configuration dict from world YAML
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize gameplay system.
        
        Args:
            config: Configuration from world YAML gameplay_systems section
        """
        self.config = config
        self.is_active = True
        self._state: Dict[str, Any] = {}
        
        self._validate_config()
        self._initialize()
    
    @property
    @abstractmethod
    def name(self) -> str:
        """System identifier (e.g., 'combat', 'economy')."""
        pass
    
    @property
    def display_name(self) -> str:
        """Human-readable system name."""
        return self.name.replace("_", " ").title()
    
    def _validate_config(self) -> None:
        """Validate system configuration.
        
        Override to validate required config fields.
        Raises ValueError if config is invalid.
        """
        pass
    
    def _initialize(self) -> None:
        """Initialize system state.
        
        Override to set up initial state.
        """
        pass
    
    def update(self, delta_time: float) -> None:
        """Update system state (called each frame/tick).
        
        Args:
            delta_time: Time elapsed since last update
        """
        pass
    
    def enable(self) -> None:
        """Activate system."""
        self.is_active = True
    
    def disable(self) -> None:
        """Deactivate system."""
        self.is_active = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize system state for saving.
        
        Returns:
            Serializable state dict
        """
        return {
            "is_active": self.is_active,
            "state": self._state,
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore system state from save.
        
        Args:
            data: Serialized state from to_dict()
        """
        self.is_active = data.get("is_active", True)
        self._state = data.get("state", {})
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value.
        
        Args:
            key: Config key
            default: Default value if key not found
            
        Returns:
            Config value or default
        """
        return self.config.get(key, default)
    
    def __repr__(self) -> str:
        """String representation."""
        status = "active" if self.is_active else "inactive"
        return f"<{self.__class__.__name__} ({status})>"


class GameplayEvent:
    """Event triggered by gameplay systems.
    
    Used for communication between systems and engine.
    """
    
    def __init__(
        self,
        event_type: str,
        source: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create gameplay event.
        
        Args:
            event_type: Type of event (e.g., 'combat_end', 'item_crafted')
            source: System that triggered the event
            data: Event-specific data
        """
        self.event_type = event_type
        self.source = source
        self.data = data or {}
    
    def __repr__(self) -> str:
        return f"<GameplayEvent {self.event_type} from {self.source}>"
