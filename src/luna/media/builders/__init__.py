"""Luna RPG - Media Prompt Builders Package.

Image prompt building system for Stable Diffusion.

REFACTORED: Builders are now split across multiple modules:
- base.py: BasePromptBuilder, ImagePrompt
- outfit_mapper.py: OutfitPromptMapper
- character_builders.py: Single/Multi/NPCBuilder
- factory.py: PromptBuilderFactory
- image_builder.py: ImagePromptBuilder (main)

Backward compatibility: All imports from luna.media.builders
continue to work unchanged.
"""
from .base import BasePromptBuilder, ImagePrompt
from .character_builders import (
    MultiCharacterBuilder,
    NPCBuilder,
    SingleCharacterBuilder,
)
from .factory import PromptBuilderFactory
from .image_builder import ImagePromptBuilder
from .outfit_mapper import OutfitPromptMapper

__all__ = [
    "BasePromptBuilder",
    "ImagePrompt",
    "OutfitPromptMapper",
    "SingleCharacterBuilder",
    "MultiCharacterBuilder",
    "NPCBuilder",
    "PromptBuilderFactory",
    "ImagePromptBuilder",
]
