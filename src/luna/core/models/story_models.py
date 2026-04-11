"""Luna RPG - Story Models.

Story beats, narrative arcs, and beat execution tracking.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import Field

from .base import LunaBaseModel


class StoryBeat(LunaBaseModel):
    """Narrative story beat definition."""
    id: str
    description: str
    trigger: str = ""
    required_elements: List[str] = Field(default_factory=list)
    tone: str = ""
    once: bool = True
    priority: int = Field(default=5, ge=1, le=10)
    consequence: Optional[str] = None


class BeatExecution(LunaBaseModel):
    """Runtime tracking of executed story beat."""
    beat_id: str
    triggered_at: int
    completed: bool = False
    execution_quality: float = Field(default=1.0, ge=0.0, le=1.0)
    narrative_snapshot: str = ""


class NarrativeArc(LunaBaseModel):
    """Character narrative arc definition."""
    premise: str = ""
    themes: List[str] = Field(default_factory=list)
    hard_limits: List[str] = Field(default_factory=list)
    soft_guidelines: List[str] = Field(default_factory=list)
    beats: List[StoryBeat] = Field(default_factory=list)
