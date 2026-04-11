"""Gameplay Manager - Orchestrates all gameplay systems.

Coordinates the 9 gameplay systems and integrates them with the game engine.
Provides a unified API for game mechanics.
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

from typing import Any, Dict, List, Optional, Type

from luna.core.models import GameState, WorldDefinition
from luna.systems.gameplay.base import GameplayEvent, GameplaySystem
from luna.systems.gameplay.affinity import AffinitySystem
from luna.systems.gameplay.combat import CombatEntity
from luna.systems.gameplay.combat import CombatSystem
from luna.systems.gameplay.inventory import InventorySystem, Item
from luna.systems.gameplay.economy import EconomySystem
from luna.systems.gameplay.skills import SkillsSystem
from luna.systems.gameplay.reputation import ReputationSystem
from luna.systems.gameplay.clues import ClueSystem
from luna.systems.gameplay.survival import SurvivalSystem
from luna.systems.gameplay.morality import MoralitySystem
from luna.systems.dynamic_events import DynamicEventManager, EventResult, EventInstance


class GameplayAction:
    """Represents an available action to the player."""
    
    def __init__(
        self,
        action_id: str,
        name: str,
        description: str,
        category: str,  # "social", "combat", "item", "movement", "quest"
        icon: str = "🎯",
        enabled: bool = True,
        cooldown: int = 0,
        requires_target: bool = False,
        target_type: Optional[str] = None,  # "companion", "location", "item"
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.action_id = action_id
        self.name = name
        self.description = description
        self.category = category
        self.icon = icon
        self.enabled = enabled
        self.cooldown = cooldown
        self.requires_target = requires_target
        self.target_type = target_type
        self.metadata = metadata or {}
        self.current_cooldown: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "enabled": self.enabled,
            "cooldown": self.cooldown,
            "requires_target": self.requires_target,
            "target_type": self.target_type,
            "metadata": self.metadata,
        }


class GameplayResult:
    """Result of a gameplay action."""
    
    def __init__(
        self,
        success: bool,
        message: str = "",
        events: Optional[List[GameplayEvent]] = None,
        affinity_changes: Optional[Dict[str, int]] = None,
        items_gained: Optional[List[Item]] = None,
        items_lost: Optional[List[str]] = None,
        money_change: int = 0,
        flags_set: Optional[Dict[str, Any]] = None,
        unlocked_actions: Optional[List[str]] = None,
    ) -> None:
        self.success = success
        self.message = message
        self.events = events or []
        self.affinity_changes = affinity_changes or {}
        self.items_gained = items_gained or []
        self.items_lost = items_lost or []
        self.money_change = money_change
        self.flags_set = flags_set or {}
        self.unlocked_actions = unlocked_actions or []


class GameplayManager:
    """Manages all gameplay systems and provides unified API.
    
    This is the bridge between the game engine and the gameplay systems.
    It coordinates interactions between systems and provides context-aware
    action availability.
    """
    
    # System registry
    SYSTEM_CLASSES: Dict[str, Type[GameplaySystem]] = {
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
    
    def __init__(self, world: WorldDefinition) -> None:
        """Initialize gameplay manager with world configuration.
        
        Args:
            world: World definition with gameplay_systems config
        """
        self.world = world
        self._systems: Dict[str, GameplaySystem] = {}
        self._available_actions: List[GameplayAction] = []
        self._action_history: List[Dict[str, Any]] = []
        
        self._initialize_systems()
        
        # Initialize dynamic events system
        self.event_manager = DynamicEventManager(world)
        
        self._update_available_actions()
    
    def _initialize_systems(self) -> None:
        """Initialize all gameplay systems based on world config."""
        gameplay_config = getattr(self.world, 'gameplay_systems', None)
        
        if not gameplay_config:
            # Default: enable only affinity system
            gameplay_config = {"affinity": {"enabled": True}}
        
        for system_name, system_class in self.SYSTEM_CLASSES.items():
            config = gameplay_config.get(system_name, {}) if gameplay_config else {}
            
            # Check if system is enabled
            if config and config.get("enabled", True):
                try:
                    system = system_class(config)
                    self._systems[system_name] = system
                    logger.debug(f"[GameplayManager] Initialized: {system_name}")
                except Exception as e:
                    logger.error(f"[GameplayManager] Failed to init {system_name}: {e}")
    
    # ========================================================================
    # System Access
    # ========================================================================
    
    def get_system(self, name: str) -> Optional[GameplaySystem]:
        """Get a gameplay system by name."""
        return self._systems.get(name)
    
    def has_system(self, name: str) -> bool:
        """Check if a system is active."""
        system = self._systems.get(name)
        return system is not None and system.is_active
    
    @property
    def affinity(self) -> Optional[AffinitySystem]:
        """Get affinity system."""
        return self._systems.get("affinity")  # type: ignore
    
    @property
    def combat(self) -> Optional[CombatSystem]:
        """Get combat system."""
        return self._systems.get("combat")  # type: ignore
    
    @property
    def inventory(self) -> Optional[InventorySystem]:
        """Get inventory system."""
        return self._systems.get("inventory")  # type: ignore
    
    @property
    def economy(self) -> Optional[EconomySystem]:
        """Get economy system."""
        return self._systems.get("economy")  # type: ignore
    
    @property
    def skills(self) -> Optional[SkillsSystem]:
        """Get skills system."""
        return self._systems.get("skills")  # type: ignore
    
    @property
    def reputation(self) -> Optional[ReputationSystem]:
        """Get reputation system."""
        return self._systems.get("reputation")  # type: ignore
    
    @property
    def clues(self) -> Optional[ClueSystem]:
        """Get clues system."""
        return self._systems.get("clues")  # type: ignore
    
    # ========================================================================
    # Action System
    # ========================================================================
    
    def get_available_actions(
        self,
        game_state: GameState,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[GameplayAction]:
        """Get all available actions for current context.
        
        Args:
            game_state: Current game state
            context: Additional context (e.g., nearby NPCs, items)
            
        Returns:
            List of available actions
        """
        actions: List[GameplayAction] = []
        companion = game_state.active_companion
        location = game_state.current_location
        
        # Social actions based on affinity
        if self.has_system("affinity") and companion:
            actions.extend(self._get_social_actions(companion))
        
        # Inventory actions
        if self.has_system("inventory"):
            actions.extend(self._get_inventory_actions())
        
        # Combat actions
        if self.has_system("combat"):
            actions.extend(self._get_combat_actions())
        
        # Economy actions (if in shop location)
        if self.has_system("economy"):
            actions.extend(self._get_economy_actions(location))
        
        # Movement actions
        actions.extend(self._get_movement_actions(game_state))
        
        return actions
    
    def _get_social_actions(self, companion: str) -> List[GameplayAction]:
        """Get social actions based on affinity."""
        actions = []
        affinity_system = self.affinity
        
        if not affinity_system:
            return actions
        
        # Always available
        actions.append(GameplayAction(
            action_id="chat",
            name="Chat",
            description=f"Talk with {companion}",
            category="social",
            icon="💬",
        ))
        
        # Check unlocked actions
        if affinity_system.can_perform_action(companion, "flirt"):
            actions.append(GameplayAction(
                action_id="flirt",
                name="Flirt",
                description=f"Flirt with {companion}",
                category="social",
                icon="😘",
                requires_target=True,
                target_type="companion",
            ))
        
        if affinity_system.can_perform_action(companion, "gift"):
            actions.append(GameplayAction(
                action_id="gift",
                name="Give Gift",
                description=f"Give a gift to {companion}",
                category="social",
                icon="🎁",
                requires_target=True,
                target_type="item",
            ))
        
        if affinity_system.can_perform_action(companion, "hug"):
            actions.append(GameplayAction(
                action_id="hug",
                name="Hug",
                description=f"Hug {companion}",
                category="social",
                icon="🤗",
            ))
        
        if affinity_system.can_perform_action(companion, "kiss"):
            actions.append(GameplayAction(
                action_id="kiss",
                name="Kiss",
                description=f"Kiss {companion}",
                category="social",
                icon="💋",
            ))
        
        return actions
    
    def _get_inventory_actions(self) -> List[GameplayAction]:
        """Get inventory-related actions."""
        actions = []
        inventory = self.inventory
        
        if not inventory:
            return actions
        
        # Add actions for usable items
        for item in inventory._items.values():
            if item.usable:
                actions.append(GameplayAction(
                    action_id=f"use_{item.item_id}",
                    name=f"Use {item.name}",
                    description=item.description,
                    category="item",
                    icon="🧪" if item.category == "consumable" else "📦",
                    metadata={"item_id": item.item_id},
                ))
        
        return actions
    
    def _get_combat_actions(self) -> List[GameplayAction]:
        """Get combat actions if in combat."""
        actions = []
        combat = self.combat
        
        # Handle both enum and string state
        combat_state = combat.state.value if hasattr(combat.state, 'value') else str(combat.state)
        if not combat or combat_state == "inactive":
            return actions
        
        actions.append(GameplayAction(
            action_id="combat_attack",
            name="Attack",
            description="Attack the enemy",
            category="combat",
            icon="⚔️",
            requires_target=True,
            target_type="enemy",
        ))
        
        actions.append(GameplayAction(
            action_id="combat_defend",
            name="Defend",
            description="Defend against attacks",
            category="combat",
            icon="🛡️",
        ))
        
        actions.append(GameplayAction(
            action_id="combat_escape",
            name="Escape",
            description="Try to escape from combat",
            category="combat",
            icon="🏃",
        ))
        
        return actions
    
    def _get_economy_actions(self, location: str) -> List[GameplayAction]:
        """Get economy actions (shop, etc)."""
        actions = []
        economy = self.economy
        
        if not economy:
            return actions
        
        # Check if location has a shop
        shops = economy._shops.keys()
        if location.lower() in shops or "shop" in location.lower():
            actions.append(GameplayAction(
                action_id="shop_buy",
                name="Buy Items",
                description="Browse shop items",
                category="economy",
                icon="🛒",
            ))
        
        return actions
    
    def _get_movement_actions(self, game_state: GameState) -> List[GameplayAction]:
        """Get movement actions based on location."""
        actions = []
        
        # Movement is always available but context-aware
        actions.append(GameplayAction(
            action_id="move",
            name="Move",
            description="Go to another location",
            category="movement",
            icon="🚶",
            requires_target=True,
            target_type="location",
        ))
        
        return actions
    
    def execute_action(
        self,
        action_id: str,
        game_state: GameState,
        target: Optional[str] = None,
    ) -> GameplayResult:
        """Execute a gameplay action.
        
        Args:
            action_id: Action to execute
            game_state: Current game state
            target: Optional target
            
        Returns:
            Gameplay result with changes
        """
        # Social actions
        if action_id in ["chat", "flirt", "gift", "hug", "kiss"]:
            return self._execute_social_action(action_id, game_state, target)
        
        # Combat actions
        if action_id.startswith("combat_"):
            return self._execute_combat_action(action_id, target)
        
        # Item actions
        if action_id.startswith("use_"):
            item_id = action_id.replace("use_", "")
            return self._execute_item_action(item_id)
        
        return GameplayResult(
            success=False,
            message=f"Unknown action: {action_id}",
        )
    
    def _execute_social_action(
        self,
        action_id: str,
        game_state: GameState,
        target: Optional[str],
    ) -> GameplayResult:
        """Execute a social action."""
        companion = game_state.active_companion
        affinity_system = self.affinity
        
        if not companion or not affinity_system:
            return GameplayResult(success=False, message="No companion available")
        
        # Base affinity changes
        affinity_changes = {companion: 0}
        messages = []
        
        if action_id == "chat":
            affinity_changes[companion] = 1
            messages.append(f"You chat with {companion}")
        
        elif action_id == "flirt":
            # Check if unlocked
            if affinity_system.can_perform_action(companion, "flirt"):
                affinity_changes[companion] = 3
                messages.append(f"You flirt with {companion}")
            else:
                return GameplayResult(
                    success=False,
                    message=f"{companion} is not interested in flirting yet",
                )
        
        elif action_id == "gift":
            if target and self.inventory and self.inventory.has_item(target):
                item = self.inventory._items.get(target)
                if item:
                    affinity_changes[companion] = 5
                    self.inventory.remove_item(target)
                    messages.append(f"You give {item.name} to {companion}")
            else:
                return GameplayResult(
                    success=False,
                    message="You don't have that item",
                )
        
        elif action_id == "hug":
            if affinity_system.can_perform_action(companion, "hug"):
                affinity_changes[companion] = 2
                messages.append(f"You hug {companion}")
            else:
                return GameplayResult(
                    success=False,
                    message=f"{companion} is not comfortable with hugging yet",
                )
        
        elif action_id == "kiss":
            if affinity_system.can_perform_action(companion, "kiss"):
                affinity_changes[companion] = 5
                messages.append(f"You kiss {companion}")
            else:
                return GameplayResult(
                    success=False,
                    message=f"{companion} is not ready for that yet",
                )
        
        # Apply affinity changes
        for char, amount in affinity_changes.items():
            if amount != 0:
                new_val, tier_changed = affinity_system.change_affinity(
                    char, amount, f"action:{action_id}"
                )
                if tier_changed:
                    messages.append(f"💕 Affinity tier changed with {char}!")
        
        return GameplayResult(
            success=True,
            message="\n".join(messages),
            affinity_changes=affinity_changes,
        )
    
    def _execute_combat_action(self, action_id: str, target: Optional[str]) -> GameplayResult:
        """Execute a combat action."""
        combat = self.combat
        
        if not combat:
            return GameplayResult(success=False, message="Combat system not available")
        
        if action_id == "combat_attack":
            # Find enemy
            for i, entity in enumerate(combat.entities):
                if not entity.is_player:
                    result = combat.execute_action("attack", 0, i)
                    return GameplayResult(
                        success=result["success"],
                        message=result["message"],
                    )
        
        elif action_id == "combat_defend":
            return GameplayResult(
                success=True,
                message="You take a defensive stance",
            )
        
        elif action_id == "combat_escape":
            combat.state = CombatSystem.CombatState.ESCAPED  # type: ignore
            return GameplayResult(
                success=True,
                message="You escape from combat",
            )
        
        return GameplayResult(success=False, message="Combat action failed")
    
    def _execute_item_action(self, item_id: str) -> GameplayResult:
        """Execute an item use action."""
        inventory = self.inventory
        
        if not inventory:
            return GameplayResult(success=False, message="Inventory not available")
        
        effects = inventory.use_item(item_id)
        
        if effects:
            item = inventory._items.get(item_id)
            item_name = item.name if item else item_id
            return GameplayResult(
                success=True,
                message=f"You use {item_name}",
                items_lost=[item_id],
            )
        
        return GameplayResult(success=False, message="Cannot use that item")
    
    def _update_available_actions(self) -> None:
        """Update the list of available actions."""
        # This will be called when state changes
        pass
    
    # ========================================================================
    # Integration Helpers
    # ========================================================================
    
    def on_turn_end(self, game_state: GameState) -> List[GameplayEvent]:
        """Process end-of-turn updates for all systems.
        
        Args:
            game_state: Current game state
            
        Returns:
            List of gameplay events
        """
        events: List[GameplayEvent] = []
        
        # Update each system
        for name, system in self._systems.items():
            if system.is_active:
                system.update(1.0)  # 1 turn = 1 time unit
        
        # Update dynamic events (cooldowns, etc.)
        self.event_manager.on_turn_end(game_state)
        
        return events
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get summary of all system statuses."""
        summary = {}
        
        for name, system in self._systems.items():
            summary[name] = {
                "active": system.is_active,
                "state": system.to_dict(),
            }
        
        return summary
    
    # ========================================================================
    # System Integration Helpers
    # ========================================================================
    
    
    # ========================================================================
    # Dynamic Events Integration
    # ========================================================================
    
    def check_dynamic_event(self, game_state: GameState) -> Optional[EventInstance]:
        """Check for random or daily event.
        
        Args:
            game_state: Current game state
            
        Returns:
            Event instance if one triggers, None otherwise
        """
        return self.event_manager.check_for_event(game_state)
    
    def has_pending_event(self) -> bool:
        """Check if there's a pending event waiting for player choice."""
        return self.event_manager.get_current_event() is not None
    
    def get_pending_event(self) -> Optional[EventInstance]:
        """Get current pending event if any."""
        return self.event_manager.get_current_event()
    
    def process_event_choice(
        self,
        choice_index: int,
        game_state: GameState,
    ) -> EventResult:
        """Process player choice for current event.
        
        Args:
            choice_index: Index of chosen option (0-based)
            game_state: Current game state
            
        Returns:
            EventResult with effects applied
        """
        return self.event_manager.process_choice(choice_index, game_state)
    
    def skip_current_event(self) -> None:
        """Skip current event without choosing."""
        self.event_manager.skip_event()
    
    # ========================================================================
    # Serialization
    # ========================================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize all systems."""
        return {
            name: system.to_dict()
            for name, system in self._systems.items()
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore all systems from save."""
        for name, system_data in data.items():
            if name in self._systems:
                self._systems[name].from_dict(system_data)
