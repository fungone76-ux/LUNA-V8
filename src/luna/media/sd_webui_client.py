"""Async Stable Diffusion WebUI client for local image generation.

Uses Automatic1111 API for local image generation.
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp
import aiofiles

from luna.core.config import get_settings
from luna.media.builders import ImagePrompt


class SDWebUIClient:
    """Async Stable Diffusion WebUI (Automatic1111) client.
    
    Used for LOCAL mode image generation.
    """
    
    def __init__(self) -> None:
        """Initialize SD WebUI client."""
        self.settings = get_settings()
        self.timeout = aiohttp.ClientTimeout(total=600)  # 10 min for local generation
    
    async def generate(
        self,
        prompt: ImagePrompt,
        character_name: str = "",
        save_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """Generate image using SD WebUI.
        
        Args:
            prompt: Built image prompt
            character_name: Character name
            save_dir: Directory to save image
            
        Returns:
            Path to generated image or None
        """
        sd_url = self.settings.local_sd_url
        
        try:
            # Convert ComfyUI sampler name to SD WebUI format
            sampler_map = {
                "dpmpp_2m": "DPM++ 2M Karras",
                "euler": "Euler",
                "euler_ancestral": "Euler a",
                "dpm_2": "DPM2",
                "dpm_2_ancestral": "DPM2 a",
            }
            sampler_name = sampler_map.get(getattr(prompt, "sampler", "euler") or "euler", "DPM++ 2M Karras")

            # Prepare payload for SD WebUI API
            payload = {
                "prompt": prompt.positive,
                "negative_prompt": prompt.negative,
                "width": prompt.width,
                "height": prompt.height,
                "steps": prompt.steps,
                "cfg_scale": getattr(prompt, "cfg_scale", 7.0) or 7.0,
                "sampler_name": sampler_name,
                "seed": getattr(prompt, "seed", None) or -1,
                "batch_size": 1,
                "n_iter": 1,
            }
            
            logger.debug(f"\n[SD WebUI] Generating {character_name}...")
            logger.debug(f"[SD WebUI] Size: {prompt.width}x{prompt.height}")
            logger.debug(f"[SD WebUI] Prompt: {prompt.positive}")
            
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # Generate image
                async with session.post(
                    f"{sd_url}/sdapi/v1/txt2img",
                    json=payload
                ) as resp:
                    if resp.status != 200:
                        error = await resp.text()
                        logger.warning(f"[SD WebUI] Generation failed: {resp.status} - {error[:200]}")
                        return None
                    
                    data = await resp.json()
                    images = data.get("images", [])
                    
                    if not images:
                        logger.debug("[SD WebUI] No images returned")
                        return None
                    
                    # Save image
                    import base64
                    img_data = base64.b64decode(images[0])
                    
                    if save_dir is None:
                        save_dir = Path("storage/images")
                    save_dir = save_dir.resolve()  # Convert to absolute path
                    save_dir.mkdir(parents=True, exist_ok=True)
                    
                    path = save_dir / f"{character_name}_{int(time.time())}.png"
                    
                    async with aiofiles.open(path, "wb") as f:
                        await f.write(img_data)
                    
                    logger.debug(f"[SD WebUI] Saved: {path}")
                    return path.resolve()  # Return absolute path
                    
        except Exception as e:
            logger.warning(f"[SD WebUI] Error: {e}")
            return None
    
    async def check_available(self) -> bool:
        """Check if SD WebUI is running.
        
        Returns:
            True if available
        """
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(f"{self.settings.local_sd_url}/sdapi/v1/samplers") as resp:
                    return resp.status == 200
        except:
            return False
