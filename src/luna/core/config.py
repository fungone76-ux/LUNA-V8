"""Luna RPG v6 - Configuration loader.

Reads from .env file. Never modifies .env.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from luna.core.models import AppConfig


def _load_env_file(path: Path) -> None:
    """Load .env file into os.environ if it exists."""
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key   = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _find_project_root() -> Path:
    """Find project root (directory containing 'worlds' folder)."""
    here = Path(__file__).resolve()
    for parent in [
        here.parent,
        here.parent.parent,
        here.parent.parent.parent,
        here.parent.parent.parent.parent,
    ]:
        if (parent / "worlds").exists():
            return parent
    return Path.cwd()


class UserPrefs:
    """User preferences with attribute access."""
    def __init__(self) -> None:
        self.audio_enabled:          bool = os.environ.get("AUDIO_ENABLED", "true").lower() == "true"
        self.audio_muted:            bool = os.environ.get("AUDIO_MUTED", "false").lower() == "true"
        self.enable_semantic_memory: bool = os.environ.get("LUNA_SEMANTIC_MEMORY", "true").lower() == "true"
        self.last_world:             str  = os.environ.get("LUNA_LAST_WORLD", "")
        self.last_companion:         str  = os.environ.get("LUNA_LAST_COMPANION", "")
        self.execution_mode:         str  = os.environ.get("LUNA_EXECUTION_MODE", "LOCAL")
        self.runpod_id:              str  = os.environ.get("LUNA_RUNPOD_ID", "")


def get_user_prefs() -> UserPrefs:
    """Load user preferences (non-critical settings)."""
    return UserPrefs()


def reload_settings() -> AppConfig:
    """Clear cached settings and reload."""
    get_settings.cache_clear()
    return get_settings()


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    """Load and cache application settings from environment."""
    project_root = _find_project_root()

    # Try multiple candidate .env locations
    for candidate in [
        Path(".env"),
        project_root / ".env",
        Path("../.env"),
        Path("config/.env"),
        project_root / "config" / ".env",
    ]:
        _load_env_file(candidate)

    return AppConfig(
        execution_mode=os.environ.get("EXECUTION_MODE", "LOCAL"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        llm_provider=os.environ.get("LLM_PROVIDER", "gemini"),

        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        moonshot_api_key=os.environ.get("MOONSHOT_API_KEY"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        runpod_id=os.environ.get("RUNPOD_ID"),
        runpod_api_key=os.environ.get("RUNPOD_API_KEY"),

        local_sd_url=os.environ.get("LOCAL_SD_URL", "http://127.0.0.1:7860"),
        local_comfy_url=os.environ.get("LOCAL_COMFY_URL", "http://127.0.0.1:8188"),
        database_url=os.environ.get(
            "DATABASE_URL",
            f"sqlite+aiosqlite:///{project_root / 'storage' / 'saves' / 'luna_v6.db'}",
        ),
        google_credentials_path=os.environ.get(
            "GOOGLE_CREDENTIALS_PATH",
            str(project_root / "config" / "google_credentials.json"),
        ),

        video_enabled=os.environ.get("VIDEO_ENABLED", "false").lower() == "true",
        video_motion_speed=int(os.environ.get("VIDEO_MOTION_SPEED", "6")),
        memory_history_limit=int(os.environ.get("MEMORY_HISTORY_LIMIT", "50")),
        image_width=int(os.environ.get("IMAGE_WIDTH", "896")),
        image_height=int(os.environ.get("IMAGE_HEIGHT", "1152")),
        image_steps=int(os.environ.get("IMAGE_STEPS", "24")),
        mock_llm=os.environ.get("MOCK_LLM", "false").lower() == "true",
        mock_media=os.environ.get("MOCK_MEDIA", "false").lower() == "true",
        worlds_path=os.environ.get("WORLDS_PATH", str(project_root / "worlds")),
        debug_no_media=os.environ.get("LUNA_DEBUG_NO_MEDIA", "0") == "1",
    )
