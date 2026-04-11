"""Luna RPG - Outfit Prompt Mapper.

Maps outfit components to Stable Diffusion prompt tags.
"""
from __future__ import annotations

from typing import Any, Dict, List

from luna.core.models.state_models import OutfitState


class OutfitPromptMapper:
    """Maps outfit components to SD tags with quality modifiers."""

    @staticmethod
    def map_outfit(outfit) -> tuple[str, str]:
        """Map outfit to SD prompt tags.
        
        Args:
            outfit: OutfitState or OutfitInstance with components
            
        Returns:
            Tuple of (positive_prompt, negative_prompt)
        """
        mapper = OutfitPromptMapper()
        
        # Check for components first
        if hasattr(outfit, 'components') and outfit.components:
            # Build from components
            pos_parts = []
            neg_parts = []
            
            for component_name, component_data in outfit.components.items():
                if isinstance(component_data, dict):
                    desc = component_data.get('sd_description', component_data.get('description', ''))
                    visible = component_data.get('visible', True)
                else:
                    desc = str(component_data)
                    visible = True
                
                if desc and visible:
                    pos_parts.append(f"({desc}:1.2)")
                    
            return ", ".join(pos_parts) if pos_parts else "", ""
        
        # Fallback: use base_sd_prompt if available
        if hasattr(outfit, 'base_sd_prompt') and outfit.base_sd_prompt:
            return outfit.base_sd_prompt, ""
        
        # Fallback: use description
        if hasattr(outfit, 'description') and outfit.description:
            return f"(wearing {outfit.description}:1.3)", ""
        
        return "", ""

    def __init__(self) -> None:
        # Component-specific quality adjectives
        self._quality_map = {
            "top": [
                "well-fitted",
                "tailored",
                "comfortable",
                "stylish",
                "fashionable",
            ],
            "bottom": [
                "perfectly-fitted",
                "comfortable",
                "form-fitting",
                "stylish",
            ],
            "shoes": [
                "polished",
                "clean",
                "comfortable",
                "stylish",
            ],
            "underwear": [
                "comfortable",
                "form-fitting",
                "supportive",
            ],
            "accessories": [
                "elegant",
                "delicate",
                "tasteful",
                "stylish",
            ],
            "outerwear": [
                "warm",
                "protective",
                "stylish",
                "well-made",
            ],
        }

        # Seasonal modifiers for certain items
        self._seasonal_hints = {
            "winter": ["warm", "insulated", "thick"],
            "summer": ["light", "breathable", "cooling"],
            "spring": ["light", "comfortable"],
            "autumn": ["comfortable", "layered"],
        }

    def map_outfit_to_tags(
        self,
        outfit: OutfitState,
        max_tags: int = 20,
        season: str = "",
    ) -> List[str]:
        """Convert outfit state to SD prompt tags.

        Args:
            outfit: Current outfit state
            max_tags: Maximum number of tags to return
            season: Optional season hint (winter/summer/etc.)

        Returns:
            List of SD prompt tags
        """
        tags: List[str] = []

        # Add base outfit components
        if outfit.top:
            tags.extend(self._build_component_tags("top", outfit.top, season))
        if outfit.bottom:
            tags.extend(self._build_component_tags("bottom", outfit.bottom, season))
        if outfit.shoes:
            tags.extend(self._build_component_tags("shoes", outfit.shoes, season))
        if outfit.underwear and outfit.underwear_visible:
            tags.extend(
                self._build_component_tags("underwear", outfit.underwear, season)
            )
        if outfit.accessories:
            tags.extend(
                self._build_component_tags("accessories", outfit.accessories, season)
            )
        if outfit.outerwear:
            tags.extend(
                self._build_component_tags("outerwear", outfit.outerwear, season)
            )

        # Add modifications if any
        if outfit.modifications:
            for mod in outfit.modifications:
                if mod.visible:
                    tags.append(mod.description)

        # Add overall style hints
        if outfit.style:
            tags.append(f"{outfit.style} style")

        # Add color hints if dominant
        if outfit.dominant_colors:
            colors = ", ".join(outfit.dominant_colors[:2])
            tags.append(f"{colors} clothing")

        # Add formality level
        if outfit.formality:
            tags.append(f"{outfit.formality} attire")

        # Limit total tags
        return tags[:max_tags]

    def _build_component_tags(
        self, component: str, description: str, season: str = ""
    ) -> List[str]:
        """Build tags for a single outfit component.

        Args:
            component: Component type (top, bottom, etc.)
            description: Text description of the component
            season: Optional season hint

        Returns:
            List of tags for this component
        """
        tags = []

        # Add base description
        if description:
            tags.append(description)

        # Add quality modifier
        quality_words = self._quality_map.get(component, [])
        if quality_words:
            quality = quality_words[0]  # Use first as default
            tags.append(quality)

        # Add seasonal modifier if applicable
        if season and season.lower() in self._seasonal_hints:
            seasonal_words = self._seasonal_hints[season.lower()]
            if seasonal_words:
                tags.append(seasonal_words[0])

        return tags

    def build_outfit_prompt(
        self,
        outfit: OutfitState,
        character_name: str = "",
        include_quality: bool = True,
    ) -> str:
        """Build complete outfit prompt string for SD.

        Args:
            outfit: Current outfit state
            character_name: Optional character name for context
            include_quality: Whether to include quality modifiers

        Returns:
            Complete prompt string
        """
        tags = self.map_outfit_to_tags(outfit, max_tags=15)

        # Build prompt
        prompt_parts = []

        if character_name:
            prompt_parts.append(f"{character_name} wearing")

        prompt_parts.extend(tags)

        if include_quality:
            prompt_parts.append("high quality clothing")
            prompt_parts.append("detailed fabric texture")

        return ", ".join(prompt_parts)
