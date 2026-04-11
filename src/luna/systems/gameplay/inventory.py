"""Inventory System - Item management.

Tracks items, equipment, and consumables.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from luna.systems.gameplay.base import GameplaySystem


class Item:
    """Inventory item."""
    
    def __init__(
        self,
        item_id: str,
        name: str,
        description: str = "",
        category: str = "misc",
        stackable: bool = False,
        quantity: int = 1,
        usable: bool = False,
        effects: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.item_id = item_id
        self.name = name
        self.description = description
        self.category = category  # weapon, armor, consumable, key, misc
        self.stackable = stackable
        self.quantity = quantity
        self.usable = usable
        self.effects = effects or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "stackable": self.stackable,
            "quantity": self.quantity,
            "usable": self.usable,
            "effects": self.effects,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Item:
        return cls(**data)


class InventorySystem(GameplaySystem):
    """Inventory management system.
    
    Config options:
        - max_slots: Maximum inventory slots
        - max_stack: Maximum stack size for stackable items
        - categories: ["weapon", "armor", "consumable", "key", "misc"]
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        self._items: Dict[str, Item] = {}
        self._equipped: Dict[str, Optional[str]] = {}  # slot -> item_id
        
        super().__init__(config)
    
    @property
    def name(self) -> str:
        return "inventory"
    
    def _validate_config(self) -> None:
        """Set defaults."""
        if "max_slots" not in self.config:
            self.config["max_slots"] = 20
        if "max_stack" not in self.config:
            self.config["max_stack"] = 99
    
    def add_item(self, item: Item) -> bool:
        """Add item to inventory.
        
        Returns:
            True if successful
        """
        # Check stackable
        if item.stackable and item.item_id in self._items:
            self._items[item.item_id].quantity += item.quantity
            return True
        
        # Check capacity
        if len(self._items) >= self.config["max_slots"]:
            return False
        
        self._items[item.item_id] = item
        return True
    
    def remove_item(self, item_id: str, quantity: int = 1) -> bool:
        """Remove item from inventory."""
        if item_id not in self._items:
            return False
        
        item = self._items[item_id]
        if item.stackable:
            item.quantity -= quantity
            if item.quantity <= 0:
                del self._items[item_id]
        else:
            del self._items[item_id]
        
        return True
    
    def has_item(self, item_id: str, quantity: int = 1) -> bool:
        """Check if item is in inventory."""
        if item_id not in self._items:
            return False
        return self._items[item_id].quantity >= quantity
    
    def use_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Use an item.
        
        Returns:
            Effects dict or None
        """
        if item_id not in self._items:
            return None
        
        item = self._items[item_id]
        if not item.usable:
            return None
        
        # Apply effects
        if item.stackable:
            item.quantity -= 1
            if item.quantity <= 0:
                del self._items[item_id]
        else:
            del self._items[item_id]
        
        return item.effects
    
    def equip_item(self, item_id: str, slot: str) -> bool:
        """Equip item to slot."""
        if item_id not in self._items:
            return False
        
        item = self._items[item_id]
        if item.category not in ["weapon", "armor"]:
            return False
        
        self._equipped[slot] = item_id
        return True
    
    def unequip_item(self, slot: str) -> Optional[str]:
        """Unequip item from slot.
        
        Returns:
            Item ID or None
        """
        return self._equipped.pop(slot, None)
    
    def get_items_by_category(self, category: str) -> List[Item]:
        """Get all items of a category."""
        return [item for item in self._items.values() if item.category == category]
    
    @property
    def item_count(self) -> int:
        """Number of items in inventory."""
        return len(self._items)
    
    @property
    def is_full(self) -> bool:
        """True if inventory is full."""
        return len(self._items) >= self.config["max_slots"]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_active": self.is_active,
            "items": {k: v.to_dict() for k, v in self._items.items()},
            "equipped": self._equipped,
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        super().from_dict(data)
        self._items = {
            k: Item.from_dict(v) for k, v in data.get("items", {}).items()
        }
        self._equipped = data.get("equipped", {})
