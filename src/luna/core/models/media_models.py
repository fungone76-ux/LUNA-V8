"""Luna RPG - Media Generation Models.

Models for image and video generation prompts.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from .base import LunaBaseModel


class SceneAnalysis(LunaBaseModel):
    """Scene composition analysis."""
    composition: str = ""
    lighting: str = ""
    mood: str = ""
    focus_subject: str = ""
    background: str = ""
    camera_angle: str = ""
    tags: List[str] = Field(default_factory=list)


class ImagePrompt(LunaBaseModel):
    """Stable Diffusion image generation prompt.

    NOTE: The authoritative ImagePrompt used by the media pipeline is
    luna.media.builders.base.ImagePrompt (plain BaseModel, extra=ignore).
    This class is kept for schema documentation purposes only.
    """
    positive: str
    negative: str = ""
    width: int = Field(default=896, ge=512, le=2048)
    height: int = Field(default=1152, ge=512, le=2048)
    steps: int = Field(default=24, ge=1, le=100)
    cfg_scale: float = Field(default=7.0, ge=1.0, le=30.0)
    sampler: str = "euler"
    seed: Optional[int] = None
    aspect_ratio: str = Field(default="portrait")
    composition: str = "medium_shot"
    dop_reasoning: str = ""
    loras: List[str] = Field(default_factory=list)
    lora_stack: List[Dict[str, Any]] = Field(default_factory=list)


class VideoPrompt(LunaBaseModel):
    """Video generation prompt."""
    positive: str
    negative: str = ""
    width: int = Field(default=512, ge=256, le=1024)
    height: int = Field(default=768, ge=256, le=1024)
    frames: int = Field(default=81, ge=16, le=121)
    motion_speed: int = Field(default=6, ge=1, le=10)
