"""Luna RPG - Base Prompt Builder Classes.

Abstract base class and data models for prompt building.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from luna.core.models import GameState, WorldDefinition


class ImagePrompt(BaseModel):
    """Stable Diffusion / ComfyUI prompt contract."""
    positive: str
    negative: str = ""
    width: int = Field(default=896, ge=512, le=2048)
    height: int = Field(default=1152, ge=512, le=2048)
    steps: int = Field(default=24, ge=1, le=100)
    cfg_scale: float = Field(default=7.0, ge=1.0, le=30.0)
    sampler: str = "euler"
    seed: Optional[int] = None
    aspect_ratio: str = "portrait"
    composition: str = "cowboy_shot"
    loras: List[str] = Field(default_factory=list)
    lora_stack: List[Dict[str, Any]] = Field(default_factory=list)
    dop_reasoning: str = ""


class BasePromptBuilder(ABC):
    """Abstract base for all prompt builders."""

    def __init__(self, world: Optional[WorldDefinition] = None):
        self.world = world

    @abstractmethod
    def build(
        self,
        game_state: GameState,
        visual_en: str,
        tags_en: List[str],
        **kwargs: Any,
    ) -> ImagePrompt:
        """Build image prompt from game state.

        Args:
            game_state: Current game state
            visual_en: Visual description (English)
            tags_en: Visual tags (English)
            **kwargs: Additional builder-specific params

        Returns:
            Complete ImagePrompt ready for SD
        """
        pass

    def _build_quality_tags(self) -> List[str]:
        """Build standard quality tags."""
        return [
            "masterpiece",
            "best quality",
            "high resolution",
            "detailed",
            "sharp focus",
        ]

    def _build_negative_tags(self) -> List[str]:
        """Build standard negative tags."""
        return [
            "lowres",
            "bad anatomy",
            "bad hands",
            "text",
            "error",
            "missing fingers",
            "extra digit",
            "fewer digits",
            "cropped",
            "worst quality",
            "low quality",
            "normal quality",
            "jpeg artifacts",
            "signature",
            "watermark",
            "username",
            "blurry",
        ]

    def _sanitize_tags(self, tags: List[str]) -> List[str]:
        """Clean and normalize tags for SD prompt.
        
        Args:
            tags: Raw tags from LLM
            
        Returns:
            Cleaned list of tags
        """
        if not tags:
            return []
        
        cleaned = []
        for tag in tags:
            if not tag or not isinstance(tag, str):
                continue
            # Strip whitespace and convert to lowercase
            tag = tag.strip().lower()
            # Remove empty tags
            if not tag:
                continue
            # Remove duplicates
            if tag not in cleaned:
                cleaned.append(tag)
        
        return cleaned

    def _extract_character_from_tags(self, tags: List[str]) -> Optional[str]:
        """Extract character name from tags."""
        for tag in tags:
            if tag.startswith("character:"):
                return tag.replace("character:", "").strip()
        return None

    def _extract_location_from_tags(self, tags: List[str]) -> Optional[str]:
        """Extract location from tags."""
        for tag in tags:
            if tag.startswith("location:"):
                return tag.replace("location:", "").strip()
        return None

    def _build_lighting(self, time_of_day: str) -> str:
        """Build lighting description based on time."""
        lighting_map = {
            "morning": "soft morning light, warm glow",
            "afternoon": "bright daylight, natural lighting",
            "evening": "golden hour, warm sunset lighting",
            "night": "moonlight, ambient night lighting",
        }
        return lighting_map.get(time_of_day.lower(), "natural lighting")
