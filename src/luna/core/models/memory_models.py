"""Luna RPG - Memory Models.

Memory entries and conversation message models.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import Field

from .base import LunaBaseModel


class MemoryEntry(LunaBaseModel):
    """Single memory entry stored in database."""
    id: Optional[int] = None
    type: Literal["summary", "fact", "event"] = "fact"
    content: str
    turn_count: int = Field(ge=0)
    created_at: Optional[datetime] = None
    importance: int = Field(default=5, ge=1, le=10)
    companion: str = Field(default="")   # V5: companion isolation


class ConversationMessage(LunaBaseModel):
    """Single message in conversation history."""
    role: Literal["user", "assistant", "system"]
    content: str
    turn_number: int = Field(ge=0)
    visual_en: Optional[str] = None
    tags_en: Optional[List[str]] = None
    companion: Optional[str] = None
    timestamp: Optional[datetime] = None
