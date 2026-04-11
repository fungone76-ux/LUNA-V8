"""Affinity System - Core relationship mechanic for slice of life/visual novels.

Tracks relationship levels with characters, with tier-based progression
and unlockable content.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from luna.systems.gameplay.base import GameplaySystem


class AffinityTier:
    """Represents an affinity level tier."""
    
    def __init__(
        self,
        threshold: int,
        name: str,
        description: str,
        unlocked_actions: Optional[List[str]] = None,
        unlocked_dialogues: Optional[List[str]] = None,
        unlocked_outfits: Optional[List[str]] = None,
    ) -> None:
        """Create affinity tier.
        
        Args:
            threshold: Affinity value required (0-100)
            name: Tier name (e.g., "Stranger", "Friend", "Lover")
            description: Tier description
            unlocked_actions: Actions unlocked at this tier
            unlocked_dialogues: Dialogue options unlocked
            unlocked_outfits: Outfits unlocked
        """
        self.threshold = threshold
        self.name = name
        self.description = description
        self.unlocked_actions = set(unlocked_actions or [])
        self.unlocked_dialogues = set(unlocked_dialogues or [])
        self.unlocked_outfits = set(unlocked_outfits or [])
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize tier."""
        return {
            "threshold": self.threshold,
            "name": self.name,
            "description": self.description,
            "unlocked_actions": list(self.unlocked_actions),
            "unlocked_dialogues": list(self.unlocked_dialogues),
            "unlocked_outfits": list(self.unlocked_outfits),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AffinityTier:
        """Create tier from dict."""
        return cls(
            threshold=data["threshold"],
            name=data["name"],
            description=data.get("description", ""),
            unlocked_actions=data.get("unlocked_actions", []),
            unlocked_dialogues=data.get("unlocked_dialogues", []),
            unlocked_outfits=data.get("unlocked_outfits", []),
        )


class CharacterAffinity:
    """Affinity state for a specific character."""
    
    def __init__(self, character_id: str) -> None:
        """Initialize character affinity.
        
        Args:
            character_id: Character identifier
        """
        self.character_id = character_id
        self.value = 0  # 0-100
        self.tier_index = 0
        self.history: List[Dict[str, Any]] = []  # Change history
    
    def change(self, amount: int, reason: str = "") -> int:
        """Modify affinity value.
        
        Args:
            amount: Change amount (can be negative)
            reason: Reason for change
            
        Returns:
            New affinity value
        """
        old_value = self.value
        self.value = max(0, min(100, self.value + amount))
        
        self.history.append({
            "old": old_value,
            "new": self.value,
            "change": amount,
            "reason": reason,
        })
        
        return self.value
    
    def get_current_tier(self, tiers: List[AffinityTier]) -> AffinityTier:
        """Get current tier based on affinity value.
        
        Args:
            tiers: List of tier definitions
            
        Returns:
            Current tier
        """
        current = tiers[0]
        for tier in tiers:
            if self.value >= tier.threshold:
                current = tier
            else:
                break
        return current
    
    def has_action(self, action: str, tiers: List[AffinityTier]) -> bool:
        """Check if action is unlocked.
        
        Args:
            action: Action identifier
            tiers: Tier definitions
            
        Returns:
            True if unlocked
        """
        current_tier = self.get_current_tier(tiers)
        return action in current_tier.unlocked_actions
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize state."""
        return {
            "character_id": self.character_id,
            "value": self.value,
            "history": self.history,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CharacterAffinity:
        """Restore from dict."""
        affinity = cls(data["character_id"])
        affinity.value = data.get("value", 0)
        affinity.history = data.get("history", [])
        return affinity


class AffinitySystem(GameplaySystem):
    """Core system for relationship/affinity mechanics.
    
    Essential for slice of life, visual novels, and dating sims.
    Tracks relationship progression with unlockable content.
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """Initialize affinity system.
        
        Config options:
            - min_value: Minimum affinity (default: 0)
            - max_value: Maximum affinity (default: 100)
            - change_per_turn: Max change per turn (default: 5)
            - decay_rate: Affinity decay over time (default: 0)
            - tiers: List of tier definitions
        """
        self._affinities: Dict[str, CharacterAffinity] = {}
        self._tiers: List[AffinityTier] = []
        
        super().__init__(config)
    
    @property
    def name(self) -> str:
        return "affinity"
    
    def _validate_config(self) -> None:
        """Validate affinity configuration."""
        tiers_data = self.config.get("tiers", [])
        if not tiers_data:
            # Default tiers if not specified
            self.config["tiers"] = [
                {
                    "threshold": 0,
                    "name": "Stranger",
                    "description": "Just met",
                },
                {
                    "threshold": 25,
                    "name": "Acquaintance",
                    "description": "Getting to know each other",
                    "unlocked_actions": ["chat", "ask_about_day"],
                },
                {
                    "threshold": 50,
                    "name": "Friend",
                    "description": "Good friends",
                    "unlocked_actions": ["flirt", "gift", "hug"],
                    "unlocked_outfits": ["casual"],
                },
                {
                    "threshold": 75,
                    "name": "Close Friend",
                    "description": "Very close",
                    "unlocked_actions": ["intimate_talk", "date_ask"],
                    "unlocked_outfits": ["date_dress"],
                },
                {
                    "threshold": 100,
                    "name": "Lover",
                    "description": "Romantic relationship",
                    "unlocked_actions": ["kiss", "intimate_scene"],
                    "unlocked_outfits": ["lingerie"],
                },
            ]
    
    def _initialize(self) -> None:
        """Initialize tier definitions."""
        for tier_data in self.config.get("tiers", []):
            self._tiers.append(AffinityTier.from_dict(tier_data))
        
        # Sort by threshold
        self._tiers.sort(key=lambda t: t.threshold)
    
    def register_character(self, character_id: str) -> None:
        """Register a character for affinity tracking.
        
        Args:
            character_id: Character identifier
        """
        if character_id not in self._affinities:
            self._affinities[character_id] = CharacterAffinity(character_id)
    
    def get_affinity(self, character_id: str) -> int:
        """Get current affinity with character.
        
        Args:
            character_id: Character identifier
            
        Returns:
            Affinity value (0-100)
        """
        if character_id not in self._affinities:
            self.register_character(character_id)
        return self._affinities[character_id].value
    
    def change_affinity(
        self,
        character_id: str,
        amount: int,
        reason: str = "",
        clamp: bool = True,
    ) -> tuple[int, bool]:
        """Change affinity with a character.
        
        Args:
            character_id: Character identifier
            amount: Change amount (positive or negative)
            reason: Reason for change
            clamp: Whether to clamp per-turn change
            
        Returns:
            Tuple of (new value, tier changed)
        """
        if character_id not in self._affinities:
            self.register_character(character_id)
        
        # Clamp change if specified
        if clamp:
            max_change = self.config.get("change_per_turn", 5)
            amount = max(-max_change, min(max_change, amount))
        
        old_tier = self._affinities[character_id].get_current_tier(self._tiers)
        new_value = self._affinities[character_id].change(amount, reason)
        new_tier = self._affinities[character_id].get_current_tier(self._tiers)
        
        tier_changed = old_tier.threshold != new_tier.threshold
        
        return new_value, tier_changed
    
    def get_tier(self, character_id: str) -> AffinityTier:
        """Get current affinity tier for character.
        
        Args:
            character_id: Character identifier
            
        Returns:
            Current tier
        """
        if character_id not in self._affinities:
            self.register_character(character_id)
        return self._affinities[character_id].get_current_tier(self._tiers)
    
    def get_unlocked_actions(self, character_id: str) -> Set[str]:
        """Get all unlocked actions for character.
        
        Args:
            character_id: Character identifier
            
        Returns:
            Set of unlocked action identifiers
        """
        tier = self.get_tier(character_id)
        return tier.unlocked_actions
    
    def can_perform_action(self, character_id: str, action: str) -> bool:
        """Check if action is unlocked for character.
        
        Args:
            character_id: Character identifier
            action: Action identifier
            
        Returns:
            True if unlocked
        """
        return action in self.get_unlocked_actions(character_id)
    
    def get_all_affinities(self) -> Dict[str, int]:
        """Get affinity values for all characters.
        
        Returns:
            Dict mapping character_id to affinity value
        """
        return {
            char_id: aff.value
            for char_id, aff in self._affinities.items()
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize system state."""
        return {
            "is_active": self.is_active,
            "affinities": {
                char_id: aff.to_dict()
                for char_id, aff in self._affinities.items()
            },
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore system state."""
        super().from_dict(data)
        affinities_data = data.get("affinities", {})
        self._affinities = {
            char_id: CharacterAffinity.from_dict(aff_data)
            for char_id, aff_data in affinities_data.items()
        }
