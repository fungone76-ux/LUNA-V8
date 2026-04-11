"""Interaction rules for Multi-NPC system.

Defines when and how NPCs interact with each other based on their relationships.
"""
from __future__ import annotations

import logging
logger = logging.getLogger(__name__)

from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional, Any


class InteractionType(Enum):
    """Types of NPC-NPC interactions."""
    
    HOSTILE = auto()      # Interrupts with criticism, mockery
    SUPPORTIVE = auto()   # Interrupts with agreement, defense  
    NEUTRAL = auto()      # Observation, curiosity
    NONE = auto()         # No interaction


@dataclass
class InteractionRule:
    """Rule defining when an NPC should intervene.
    
    Attributes:
        min_rapport: Minimum rapport value to trigger (for SUPPORTIVE)
        max_rapport: Maximum rapport value to trigger (for HOSTILE)
        interaction_type: Type of interaction
        probability: Chance of triggering (0.0-1.0)
        max_per_turn: Max interventions by this NPC per turn
    """
    min_rapport: int = -100
    max_rapport: int = 100
    interaction_type: InteractionType = InteractionType.NONE
    probability: float = 1.0
    max_per_turn: int = 1
    
    def should_trigger(self, rapport: int) -> bool:
        """Check if this rule should trigger given a rapport value.
        
        Args:
            rapport: Current rapport between NPCs (-100 to 100)
            
        Returns:
            True if interaction should occur
        """
        if rapport < self.min_rapport:
            return False
        if rapport > self.max_rapport:
            return False
        return True


class InteractionRuleset:
    """Collection of interaction rules for Multi-NPC system."""
    
    DEFAULT_RULES = {
        # Hostile: strong conflict — NPC interrupts to criticize/contradict
        "hostile_strong": InteractionRule(
            min_rapport=-100,
            max_rapport=-50,
            interaction_type=InteractionType.HOSTILE,
            probability=0.5,
        ),
        # Supportive: good friends — NPC defends/agrees (lowered threshold from 70 to 50)
        "supportive_strong": InteractionRule(
            min_rapport=50,
            max_rapport=100,
            interaction_type=InteractionType.SUPPORTIVE,
            probability=0.4,
        ),
        # Shared location: any NPC present may make a neutral remark (no rapport requirement)
        "location_shared": InteractionRule(
            min_rapport=-49,
            max_rapport=49,
            interaction_type=InteractionType.NEUTRAL,
            probability=0.15,
        ),
    }
    
    def __init__(self, custom_rules: Optional[Dict[str, InteractionRule]] = None):
        """Initialize ruleset.
        
        Args:
            custom_rules: Optional custom rules to override defaults
        """
        self.rules = self.DEFAULT_RULES.copy()
        if custom_rules:
            self.rules.update(custom_rules)
    
    def check_interaction(
        self,
        rapport: int,
        interaction_count: int = 0,
    ) -> Optional[InteractionType]:
        """Check what type of interaction should occur.
        
        Args:
            rapport: Current rapport between NPCs
            interaction_count: How many times this NPC has intervened this turn
            
        Returns:
            InteractionType or None if no interaction
        """
        for rule in self.rules.values():
            if interaction_count >= rule.max_per_turn:
                continue
                
            if rule.should_trigger(rapport):
                # Check probability
                import random
                if random.random() <= rule.probability:
                    return rule.interaction_type
        
        return None
    
    def get_npcs_that_might_intervene(
        self,
        active_npc: str,
        present_npcs: List[str],
        npc_links: Dict[str, Dict[str, Any]],
        force_interaction: bool = False,
    ) -> List[tuple]:
        """Get list of NPCs that might intervene based on relationships.
        
        Args:
            active_npc: Currently speaking NPC
            present_npcs: All NPCs present in scene
            npc_links: Relationship data between NPCs
            force_interaction: If True, always include NPCs (for mentioned/location cases)
            
        Returns:
            List of (npc_name, interaction_type, rapport) tuples
        """
        logger.debug(f"[RULESET DEBUG] get_npcs_that_might_intervene called")
        logger.debug(f"[RULESET DEBUG]   active_npc={active_npc}")
        logger.debug(f"[RULESET DEBUG]   present_npcs={present_npcs}")
        logger.debug(f"[RULESET DEBUG]   force_interaction={force_interaction}")

        candidates = []

        for npc in present_npcs:
            logger.debug(f"[RULESET DEBUG] Checking npc={npc}, active={active_npc}")
            if npc == active_npc:
                logger.debug(f"[RULESET DEBUG]   Skipping - same as active")
                continue

            # Get rapport from npc_links
            links = npc_links.get(npc, {})
            link_data = links.get(active_npc, {})
            rapport = link_data.get("rapport", 0) if isinstance(link_data, dict) else 0

            logger.debug(f"[RULESET DEBUG]   links={links}, rapport={rapport}")

            interaction = self.check_interaction(rapport)
            logger.debug(f"[RULESET DEBUG]   check_interaction returned: {interaction}")

            # If force_interaction is True and no interaction type found, use NEUTRAL
            if force_interaction and (not interaction or interaction == InteractionType.NONE):
                logger.debug(f"[RULESET DEBUG]   Forcing NEUTRAL interaction")
                interaction = InteractionType.NEUTRAL

            if interaction and interaction != InteractionType.NONE:
                logger.debug(f"[RULESET DEBUG]   Adding to candidates: {npc}, {interaction}, {rapport}")
                candidates.append((npc, interaction, rapport))
            else:
                logger.debug(f"[RULESET DEBUG]   Skipping - no valid interaction")

        logger.debug(f"[RULESET DEBUG] Final candidates: {candidates}")
        
        # Sort by rapport extremity (most extreme first)
        candidates.sort(key=lambda x: abs(x[2]), reverse=True)
        return candidates
