"""Luna RPG - Configuration Models.

Application configuration and personality analysis models.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import LunaBaseModel


class AppConfig(LunaBaseModel):
    """Application configuration."""
    model_config = ConfigDict(extra="ignore")

    execution_mode: Literal["LOCAL", "RUNPOD"] = "LOCAL"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    llm_provider: Literal["gemini", "moonshot", "openai", "ollama", "claude"] = "gemini"

    gemini_api_key: Optional[str] = None
    moonshot_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    runpod_id: Optional[str] = None
    runpod_api_key: Optional[str] = None

    local_sd_url: str = "http://127.0.0.1:7860"
    local_comfy_url: str = "http://127.0.0.1:8188"
    local_ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:32b"
    database_url: str = "sqlite+aiosqlite:///storage/saves/luna_v5.db"
    google_credentials_path: str = "google_credentials.json"

    video_enabled: bool = False
    video_motion_speed: int = Field(default=6, ge=1, le=10)
    memory_history_limit: int = Field(default=50, ge=10, le=200)
    image_width: int = Field(default=896, ge=512, le=2048)
    image_height: int = Field(default=1152, ge=512, le=2048)
    image_steps: int = Field(default=24, ge=1, le=100)
    mock_llm: bool = False
    mock_media: bool = False
    worlds_path: str = "worlds"
    debug_no_media: bool = False

    @property
    def video_available(self) -> bool:
        return self.video_enabled and self.is_runpod

    @property
    def is_runpod(self) -> bool:
        return self.execution_mode == "RUNPOD"

    @property
    def is_local(self) -> bool:
        return self.execution_mode == "LOCAL"

    @property
    def comfy_url(self) -> Optional[str]:
        if self.is_runpod and self.runpod_id:
            return f"https://{self.runpod_id}-8188.proxy.runpod.net"
        return self.local_comfy_url

    @property
    def sd_url(self) -> str:
        if self.is_runpod and self.runpod_id:
            return f"https://{self.runpod_id}-7860.proxy.runpod.net"
        return self.local_sd_url

    @property
    def ollama_url(self) -> str:
        """URL Ollama — auto RunPod o localhost."""
        if self.is_runpod and self.runpod_id:
            return f"https://{self.runpod_id}-11434.proxy.runpod.net"
        return self.local_ollama_url


class DetectedTrait(BaseModel):
    """LLM-detected personality trait."""
    trait: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str


class PersonalityAnalysisResponse(BaseModel):
    """LLM personality analysis result."""
    traits: List[DetectedTrait]
    impression_changes: Dict[str, int]
    archetype_hint: Optional[str] = None
    reasoning: Optional[str] = None
