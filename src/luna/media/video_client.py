"""Async Wan2.1 I2V video generation client.

Uses API-format workflow (id -> node) compatible with ComfyUI.
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import asyncio  # FIX: moved from bottom of file
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import aiohttp
import aiofiles
from PIL import Image

from luna.core.config import get_settings, _find_project_root
from luna.ai.manager import get_llm_manager


class VideoClient:
    """Wan2.1 I2V video generation client."""
    
    def __init__(self, workflow_path: Optional[Path] = None) -> None:
        """Initialize video client."""
        self.settings = get_settings()
        self.client_id = str(uuid.uuid4())
        self.workflow_path = workflow_path or (_find_project_root() / "config" / "comfy_workflow_video.json")
        self.llm_manager = get_llm_manager()
        self.timeout = aiohttp.ClientTimeout(total=600)
    
    async def generate_video(
        self,
        image_path: Path,
        user_action: str,
        character_name: str = "",
        save_dir: Optional[Path] = None,
    ) -> Optional[Path]:
        """Generate video from image and user action description."""
        if not self.settings.video_available:
            logger.debug("[Video] Video generation not available (requires RunPod)")
            return None
        
        comfy_url = self.settings.comfy_url
        if not comfy_url:
            logger.debug("[Video] ComfyUI URL not configured")
            return None
        
        try:
            # 1. Upload image
            logger.debug(f"[Video] Uploading image to RunPod...")
            uploaded_filename = await self._upload_image(comfy_url, image_path)
            if not uploaded_filename:
                logger.warning("[Video] Failed to upload image")
                return None
            logger.debug(f"[Video] Image uploaded: {uploaded_filename}")
            
            # 1.5 Get image dimensions (for aspect ratio preservation)
            img_width, img_height = self._get_image_dimensions(image_path)
            logger.debug(f"[Video] Source image dimensions: {img_width}x{img_height}")
            
            # 2. Generate temporal prompt
            logger.debug(f"[Video] Generating temporal prompt from: '{user_action}'")
            temporal_prompt = await self._build_temporal_prompt(user_action, character_name)
            logger.debug(f"[Video] Temporal prompt ready ({len(temporal_prompt)} chars)")
            
            # 3. Unload image models to free VRAM
            await self._unload_image_models(comfy_url)
            
            # 4. Load and patch workflow
            workflow = await self._load_workflow()
            self._patch_workflow(workflow, uploaded_filename, temporal_prompt, character_name, img_width, img_height)
            
            # 5. Submit
            logger.debug(f"[Video] Submitting to Wan2.1...")
            prompt_id = await self._submit_workflow(comfy_url, workflow)
            if not prompt_id:
                return None
            
            # 6. Wait and download
            logger.debug("[Video] Generating... (this takes ~5-7 minutes)")
            video_path = await self._wait_and_download(comfy_url, prompt_id, character_name, save_dir)
            
            # 7. Cleanup
            await self._cleanup_vram(comfy_url)
            
            return video_path
            
        except Exception as e:
            logger.warning(f"[Video] Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def _upload_image(self, comfy_url: str, image_path: Path) -> Optional[str]:
        """Upload image to RunPod ComfyUI."""
        try:
            async with aiofiles.open(image_path, "rb") as f:
                image_data = await f.read()
            
            filename = image_path.name
            
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                form.add_field("image", image_data, filename=filename, content_type="image/png")
                
                async with session.post(
                    f"{comfy_url}/upload/image",
                    data=form
                ) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        return data.get("name", filename)
                    else:
                        error = await resp.text()
                        logger.warning(f"[Video] Upload failed: {resp.status} - {error[:200]}")
                        return filename
                        
        except Exception as e:
            logger.warning(f"[Video] Upload error: {e}")
            return image_path.name
    
    async def _build_temporal_prompt(self, user_action: str, character_name: str = "") -> str:
        """Convert user action to temporal prompt with timestamps (IT -> EN)."""
        system_prompt = """You are an expert video prompt engineer for Wan2.1 I2V.

Convert the user's simple action description into a detailed temporal prompt in ENGLISH.

IMPORTANT:
- The user may write in Italian or English
- You MUST output the temporal prompt in ENGLISH only
- This prompt will be used by an AI video model that understands English best

RULES:
1. Use timestamps: 0s, 2s, 4s, 6s, 8s (10 seconds total)
2. Describe ONLY physical motion - NO emotions, NO facial expressions
3. Focus on: body movement, clothing motion, hair flow
4. Be specific about speed: slowly, gently, gradually
5. Ensure smooth continuous motion
6. OUTPUT MUST BE IN ENGLISH

FORMAT:
0s: Initial state + beginning of motion
2s: Motion continues, specific movement  
4s: Peak of motion
6s: Motion slows/decays
8s: Final pose, subtle natural movement

EXAMPLE 1 (English input):
User: "she waves her hand"
Output:
0s: Character stands facing camera, right hand begins to raise slowly
2s: Hand continues rising to shoulder height, fingers slightly spread
4s: Hand waves gently side to side in greeting gesture
6s: Waving slows, hand begins to lower gradually
8s: Hand returns to resting position, subtle breathing motion

EXAMPLE 2 (Italian input -> English output):
User: "una donna si apre la camicetta"
Output:
0s: Woman sitting, hands reaching for shirt buttons, beginning to unbutton
2s: First buttons undone, shirt opening slowly, cleavage becoming visible
4s: Shirt fully open, fabric parting to reveal chest, hands on collar
6s: Hands moving to remove shirt from shoulders, motion slowing
8s: Shirt partially off, arms relaxed, subtle breathing motion"""

        user_prompt = f"Character: {character_name or 'woman'}\nAction: {user_action}\n\nGenerate temporal prompt in ENGLISH:"
        
        try:
            response = await self.llm_manager.generate(
                system_prompt=system_prompt,
                user_input=user_prompt,
                history=[],
                json_mode=False,
            )
            
            # Handle both object and tuple responses
            if isinstance(response, tuple):
                response = response[0] if response else None
            
            if response is None:
                raise ValueError("Empty response from LLM")
            
            temporal = response.text.strip() if hasattr(response, 'text') else str(response).strip()
            
            # Ensure it has timestamps
            if "0s:" not in temporal:
                temporal = f"""0s: Character begins {user_action}
2s: Motion continues smoothly
4s: Peak of {user_action}
6s: Motion slows
8s: Settles into final pose"""
            
            return temporal
            
        except Exception as e:
            logger.warning(f"[Video] Temporal prompt failed: {e}")
            return f"""0s: Character begins {user_action}
2s: Motion continues
4s: Peak of action
6s: Motion slows
8s: Final pose"""
    
    async def _unload_image_models(self, comfy_url: str) -> None:
        """Unload image models to free VRAM."""
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"{comfy_url}/free",
                    json={"unload_models": True, "free_memory": True},
                    timeout=aiohttp.ClientTimeout(total=15),  # FIX: int → ClientTimeout
                )
                await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"[Video] Unload warning: {e}")
    
    async def _cleanup_vram(self, comfy_url: str) -> None:
        """Cleanup VRAM after video generation."""
        try:
            async with aiohttp.ClientSession() as session:
                for _ in range(3):
                    await session.post(
                        f"{comfy_url}/free",
                        json={"unload_models": True, "free_memory": True},
                        timeout=aiohttp.ClientTimeout(total=30),  # FIX: int → ClientTimeout
                    )
                    await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"[Video] Cleanup warning: {e}")
    
    async def _load_workflow(self) -> Dict[str, Any]:
        """Load API-format workflow JSON."""
        async with aiofiles.open(self.workflow_path, "r", encoding="utf-8") as f:
            content = await f.read()
            return json.loads(content)
    
    def _get_image_dimensions(self, image_path: Path) -> Tuple[int, int]:
        """Get image dimensions using PIL."""
        try:
            with Image.open(image_path) as img:
                return img.size
        except Exception as e:
            logger.warning(f"[Video] Warning: Could not read image dimensions: {e}")
            # Default to square if can't read
            return 1024, 1024
    
    def _patch_workflow(
        self,
        workflow: Dict[str, Any],
        image_filename: str,
        temporal_prompt: str,
        character_name: str,
        img_width: int = 1024,
        img_height: int = 1024,
    ) -> None:
        """Patch workflow with runtime values."""
        # Calculate video dimensions preserving aspect ratio
        # Wan2.1 works best with specific resolutions, but we preserve aspect ratio
        video_width, video_height = self._calculate_video_dimensions(img_width, img_height)
        logger.debug(f"[Video] Setting video dimensions: {video_width}x{video_height} (from {img_width}x{img_height})")
        
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            
            inputs = node.get("inputs", {})
            class_type = node.get("class_type", "")
            
            # Patch LoadImage node
            if class_type == "LoadImage":
                inputs["image"] = image_filename
                logger.debug(f"[Video] Set image: {image_filename}")
            
            # Patch ImageResize node (node 9) - V4.4: 896x896
            elif class_type == "ImageResizeKJv2":
                inputs["width"] = 896
                inputs["height"] = 896
                inputs["keep_proportion"] = "resize"  # Force exact size
                logger.debug(f"[Video] Set resize to 896x896")
            
            # Patch EmptyLatentImage or similar size nodes
            elif class_type in ["EmptyLatentImage", "WanImageToVideo", "ImageOnlyWorkflow"]:
                if "width" in inputs:
                    inputs["width"] = video_width
                if "height" in inputs:
                    inputs["height"] = video_height
                if class_type == "WanImageToVideo":
                    logger.debug(f"[Video] WanImageToVideo set to {video_width}x{video_height}")
            
            # Patch positive prompt (CLIPTextEncode with "positive" in meta or longer text)
            elif class_type == "CLIPTextEncode":
                text = inputs.get("text", "")
                meta = node.get("_meta", {})
                title = meta.get("title", "").lower()
                
                # Check if this is the positive prompt node
                is_positive = (
                    "positive" in title or
                    "nsfw" in title or
                    len(str(text)) > 100 and "deformed" not in str(text).lower()
                )
                
                if is_positive:
                    inputs["text"] = temporal_prompt
                    logger.debug(f"[Video] Set temporal prompt ({len(temporal_prompt)} chars)")
            
            # Patch output filename
            elif class_type == "VHS_VideoCombine":
                if "filename_prefix" in inputs:
                    prefix = character_name or "video"
                    inputs["filename_prefix"] = f"{prefix}_Wan2.1"
                    logger.debug(f"[Video] Set filename prefix: {prefix}_Wan2.1")
                # V4.4: Enable ping-pong animation (forward then backward)
                if "pingpong" in inputs:
                    inputs["pingpong"] = True
                    logger.debug(f"[Video] Ping-pong animation enabled")
    
    def _calculate_video_dimensions(self, img_width: int, img_height: int) -> Tuple[int, int]:
        """Calculate video dimensions.
        
        V4.7: Fixed to 896x896 for balanced quality/speed.
        896 is divisible by 16 (WanVideo requirement): 896 / 16 = 56
        """
        # V4.7: Fixed 896x896 for video generation
        return 896, 896
    
    async def _submit_workflow(
        self,
        comfy_url: str,
        workflow: Dict[str, Any],
    ) -> Optional[str]:
        """Submit workflow to ComfyUI."""
        # Debug: print first node to verify structure
        first_key = list(workflow.keys())[0] if workflow else None
        logger.debug(f"[Video] Workflow has {len(workflow)} nodes, first key: {first_key}")
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            payload = {"prompt": workflow, "client_id": self.client_id}
            
            async with session.post(
                f"{comfy_url}/prompt",
                json=payload
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.warning(f"[Video] Submit failed: {resp.status} - {error[:500]}")
                    return None
                
                data = await resp.json()
                prompt_id = data.get("prompt_id")
                if prompt_id:
                    logger.debug(f"[Video] Queue ID: {prompt_id}")
                return prompt_id
    
    async def _wait_and_download(
        self,
        comfy_url: str,
        prompt_id: str,
        character: str,
        save_dir: Optional[Path],
    ) -> Optional[Path]:
        """Wait for video generation and download."""
        max_wait = 600  # 10 minutes
        poll_interval = 10
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            for attempt in range(0, max_wait, poll_interval):
                await asyncio.sleep(poll_interval)
                
                progress = min(100, int((attempt / max_wait) * 100))
                logger.debug(f"[Video] Progress: {progress}% ({attempt}s)")
                
                try:
                    async with session.get(f"{comfy_url}/history/{prompt_id}") as r:
                        if r.status == 200:
                            data = await r.json()
                            outputs = data.get(prompt_id, {}).get("outputs", {})
                            
                            if outputs:
                                logger.debug(f"[Video] Generation complete! Outputs: {list(outputs.keys())}")
                                
                                # Find video file - try multiple output formats
                                for nid, node in outputs.items():
                                    logger.debug(f"[Video] Checking node {nid}: {type(node)}")
                                    
                                    files = []
                                    if isinstance(node, dict):
                                        # Try different output formats
                                        files = (
                                            node.get("files", []) or 
                                            node.get("images", []) or 
                                            node.get("gifs", []) or
                                            node.get("videos", [])
                                        )
                                    
                                    logger.debug(f"[Video] Files found: {len(files)}")
                                    
                                    for f in files:
                                        if isinstance(f, dict):
                                            fname = f.get("filename", "")
                                            subfolder = f.get("subfolder", "")
                                        else:
                                            fname = str(f)
                                            subfolder = ""
                                        
                                        logger.debug(f"[Video] Found file: {fname} (subfolder: {subfolder})")
                                        
                                        if fname.endswith((".mp4", ".webm", ".gif", ".mov", ".avi")):
                                            logger.debug(f"[Video] Downloading: {fname}")
                                            return await self._download_video(
                                                session, comfy_url, fname, character, save_dir, subfolder
                                            )
                                
                                # If no video found in outputs, try listing the output folder
                                logger.debug("[Video] No video in outputs, trying to list output folder...")
                                try:
                                    async with session.get(f"{comfy_url}/view?type=output") as list_r:
                                        if list_r.status == 200:
                                            files_list = await list_r.json()
                                            logger.debug(f"[Video] Output folder files: {files_list}")
                                except Exception as e:
                                    logger.warning(f"[Video] List error: {e}")
                                
                                logger.debug("[Video] No video file found!")
                                return None
                                
                except Exception as e:
                    logger.warning(f"[Video] Poll error: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            logger.debug("[Video] Timeout!")
            return None
    
    async def _download_video(
        self,
        session: aiohttp.ClientSession,
        comfy_url: str,
        filename: str,
        character: str,
        save_dir: Optional[Path],
        subfolder: str = "",
    ) -> Optional[Path]:
        """Download generated video."""
        # Build URL with subfolder if present
        url = f"{comfy_url}/view?filename={filename}"
        if subfolder:
            url += f"&subfolder={subfolder}"
        
        logger.debug(f"[Video] Download URL: {url}")
        
        async with session.get(url) as r:
            if r.status == 200:
                video_data = await r.read()
                
                if save_dir is None:
                    save_dir = Path("storage/videos")
                save_dir.mkdir(parents=True, exist_ok=True)
                
                path = save_dir / f"{character}_{int(time.time())}.mp4"
                
                async with aiofiles.open(path, "wb") as f:
                    await f.write(video_data)
                
                logger.debug(f"[Video] Saved: {path} ({len(video_data)} bytes)")
                return path
            else:
                logger.warning(f"[Video] Download failed: {r.status}")
                error_text = await r.text()
                logger.warning(f"[Video] Error: {error_text[:200]}")
            
            return None