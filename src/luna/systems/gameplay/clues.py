"""Clue System - Investigation and deduction.

For mystery/investigative worlds.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from luna.systems.gameplay.base import GameplaySystem


class Clue:
    """Investigation clue."""
    
    def __init__(
        self,
        clue_id: str,
        description: str,
        related_clues: Optional[List[str]] = None,
        leads_to: Optional[str] = None,
    ) -> None:
        self.clue_id = clue_id
        self.description = description
        self.related_clues = set(related_clues or [])
        self.leads_to = leads_to  # Mystery/case this clue contributes to
        self.discovered = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "clue_id": self.clue_id,
            "description": self.description,
            "related_clues": list(self.related_clues),
            "leads_to": self.leads_to,
            "discovered": self.discovered,
        }


class ClueSystem(GameplaySystem):
    """Investigation clue tracking.
    
    Config options:
        - mysteries: List of case/mystery IDs
    """
    
    def __init__(self, config: Dict[str, Any]) -> None:
        self._clues: Dict[str, Clue] = {}
        self._discovered: Set[str] = set()
        self._deductions: List[Dict[str, Any]] = []
        
        super().__init__(config)
    
    @property
    def name(self) -> str:
        return "clues"
    
    def discover_clue(self, clue_id: str, description: str = "") -> bool:
        """Discover a new clue."""
        if clue_id in self._discovered:
            return False
        
        if clue_id not in self._clues:
            self._clues[clue_id] = Clue(clue_id, description)
        
        self._clues[clue_id].discovered = True
        self._discovered.add(clue_id)
        return True
    
    def has_clue(self, clue_id: str) -> bool:
        """Check if clue is discovered."""
        return clue_id in self._discovered
    
    def get_discovered_clues(self) -> List[Clue]:
        """Get all discovered clues."""
        return [self._clues[c] for c in self._discovered]
    
    def make_deduction(
        self,
        required_clues: List[str],
        conclusion: str,
    ) -> bool:
        """Attempt to make deduction.
        
        Returns:
            True if player has all required clues
        """
        if not all(self.has_clue(c) for c in required_clues):
            return False
        
        self._deductions.append({
            "clues": required_clues,
            "conclusion": conclusion,
        })
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_active": self.is_active,
            "clues": {k: v.to_dict() for k, v in self._clues.items()},
            "discovered": list(self._discovered),
            "deductions": self._deductions,
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        super().from_dict(data)
        self._clues = {
            k: Clue(**v) for k, v in data.get("clues", {}).items()
        }
        self._discovered = set(data.get("discovered", []))
        self._deductions = data.get("deductions", [])
