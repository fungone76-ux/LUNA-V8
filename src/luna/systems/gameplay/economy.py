"""Economy System - Currency and trading.

Manages money, prices, and shop transactions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from luna.systems.gameplay.base import GameplaySystem


class ShopItem:
    """Item available in shop."""
    
    def __init__(
        self,
        item_id: str,
        name: str,
        price: int,
        description: str = "",
        stock: int = -1,  # -1 = infinite
    ) -> None:
        self.item_id = item_id
        self.name = name
        self.price = price
        self.description = description
        self.stock = stock
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "name": self.name,
            "price": self.price,
            "description": self.description,
            "stock": self.stock,
        }


class EconomySystem(GameplaySystem):
    """Currency and economy system.
    
    Config options:
        - currency: Currency name (e.g., "gold", "yen", "credits")
        - starting_amount: Initial money
        - prices: Dict of item_id -> price
        - inflation_rate: Price increase over time
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        self._balance = 0
        self._transaction_history: List[Dict[str, Any]] = []
        self._shops: Dict[str, List[ShopItem]] = {}
        
        super().__init__(config)
    
    @property
    def name(self) -> str:
        return "economy"
    
    def _initialize(self) -> None:
        """Initialize starting balance."""
        self._balance = self.config.get("starting_amount", 0)
        
        # Load shop definitions
        for shop_id, items in self.config.get("shops", {}).items():
            self._shops[shop_id] = [ShopItem(**item) for item in items]
    
    @property
    def currency(self) -> str:
        """Currency name."""
        return self.config.get("currency", "gold")
    
    @property
    def balance(self) -> int:
        """Current balance."""
        return self._balance
    
    def add_money(self, amount: int, reason: str = "") -> int:
        """Add money.
        
        Returns:
            New balance
        """
        self._balance += amount
        self._transaction_history.append({
            "amount": amount,
            "reason": reason,
            "balance_after": self._balance,
        })
        return self._balance
    
    def remove_money(self, amount: int, reason: str = "") -> bool:
        """Remove money.
        
        Returns:
            True if successful
        """
        if amount > self._balance:
            return False
        
        self._balance -= amount
        self._transaction_history.append({
            "amount": -amount,
            "reason": reason,
            "balance_after": self._balance,
        })
        return True
    
    def can_afford(self, amount: int) -> bool:
        """Check if can afford amount."""
        return self._balance >= amount
    
    def get_price(self, item_id: str) -> Optional[int]:
        """Get item price."""
        prices = self.config.get("prices", {})
        return prices.get(item_id)
    
    def buy_item(self, item_id: str, shop_id: str = "default") -> bool:
        """Buy item from shop.
        
        Returns:
            True if successful
        """
        price = self.get_price(item_id)
        if price is None:
            return False
        
        if not self.remove_money(price, f"Bought {item_id}"):
            return False
        
        return True
    
    def sell_item(self, item_id: str) -> int:
        """Sell item for money.
        
        Returns:
            Amount received
        """
        price = self.get_price(item_id)
        if price is None:
            return 0
        
        # Sell for 50% of buy price
        sell_price = price // 2
        self.add_money(sell_price, f"Sold {item_id}")
        return sell_price
    
    def get_shop_items(self, shop_id: str = "default") -> List[ShopItem]:
        """Get items available in shop."""
        return self._shops.get(shop_id, [])
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_active": self.is_active,
            "balance": self._balance,
            "transaction_history": self._transaction_history,
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        super().from_dict(data)
        self._balance = data.get("balance", 0)
        self._transaction_history = data.get("transaction_history", [])
