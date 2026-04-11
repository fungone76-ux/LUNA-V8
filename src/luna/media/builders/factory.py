"""Luna RPG - Prompt Builder Factory.

Factory for creating the right builder based on scene context.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Set

from .character_builders import MultiCharacterBuilder, NPCBuilder, SingleCharacterBuilder
from ...core.models.media_models import SceneAnalysis

if TYPE_CHECKING:
    from luna.core.models import WorldDefinition
    from .base import BasePromptBuilder

class PromptBuilderFactory:
    """Factory for creating appropriate builder based on scene."""
    
    @staticmethod
    def create_builder(
        scene_analysis: Optional[SceneAnalysis] = None,
        primary_character: str = "",
        known_companions: Optional[Set[str]] = None,
    ) -> BasePromptBuilder:
        """Create appropriate builder for scene.
        
        Args:
            scene_analysis: Scene analysis
            primary_character: Main character name
            known_companions: Set of known companion names
            
        Returns:
            Appropriate prompt builder
        """
        known = known_companions or set()
        
        # Check if multi-character
        if scene_analysis and scene_analysis.is_multi_character:
            return MultiCharacterBuilder()
        
        # Check if known companion
        if primary_character in known:
            return SingleCharacterBuilder()
        
        # Default to NPC builder
        return NPCBuilder()


