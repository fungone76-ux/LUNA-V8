"""Async ComfyUI client for image generation.

Real implementation based on v3 - uses ComfyUI API with workflow patching.
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import aiofiles

from luna.core.config import get_settings, _find_project_root
from luna.media.builders import ImagePrompt
from luna.media.aspect_ratio_director import AspectRatio, DirectorOfPhotography


class ComfyUIClient:
    """Real async ComfyUI client for image generation.
    
    Based on v3 implementation:
    - Loads workflow JSON
    - Patches prompts and parameters
    - Stacks LoRAs automatically
    - Polls for completion
    - Downloads result
    """
    
    def __init__(self, workflow_path: Optional[Path] = None) -> None:
        """Initialize ComfyUI client.
        
        Args:
            workflow_path: Path to workflow JSON (default: workflow_image.json)
        """
        self.settings = get_settings()
        self.client_id = str(uuid.uuid4())
        self.workflow_path = self._resolve_workflow_path(workflow_path)
        
        # Timeout 5 minutes for generation
        self.timeout = aiohttp.ClientTimeout(total=300)
        
        # LoRA configuration from v3
        self.lora_config = {
            "Luna": ("stsDebbie-10e.safetensors", 0.7),
            "Stella": ("alice_milf_catchers_lora.safetensors", 0.7),
            "Maria": ("stsSmith-10e.safetensors", 0.65),
        }
    
    def _resolve_workflow_path(self, override: Optional[Path]) -> Path:
        """Resolve workflow path with multiple fallbacks."""
        filename = "comfy_workflow_image.json"
        candidates: List[Path] = []

        if override:
            resolved = Path(override).expanduser().resolve()
            logger.debug(f"[ComfyUI] Using explicit workflow path: {resolved}")
            return resolved

        env_override = os.environ.get("COMFY_WORKFLOW_IMAGE_PATH")
        if env_override:
            candidates.append(Path(env_override).expanduser().resolve())

        project_root = _find_project_root()
        candidates.append((project_root / "config" / filename).resolve())
        candidates.append((project_root / filename).resolve())

        cwd = Path.cwd()
        candidates.append((cwd / "config" / filename).resolve())
        candidates.append((cwd / filename).resolve())

        for candidate in candidates:
            if candidate.exists():
                logger.debug(f"[ComfyUI] Workflow resolved to: {candidate}")
                return candidate

        logger.warning(
            "[ComfyUI] Workflow file missing in expected locations: %s",
            ", ".join(str(p) for p in candidates),
        )
        return candidates[0]

    async def generate(
        self,
        prompt: ImagePrompt,
        character_name: str = "",
        save_dir: Optional[Path] = None,
        extra_loras: Optional[List[str]] = None,
    ) -> Optional[Path]:
        """Generate image using ComfyUI.
        
        Args:
            prompt: Built image prompt
            character_name: Character name for LoRA selection
            save_dir: Directory to save image
            
        Returns:
            Path to generated image or None
        """
        comfy_url = self.settings.comfy_url
        logger.debug(f"[ComfyUI] URL: {comfy_url} (mode: {self.settings.execution_mode}, runpod_id: {self.settings.runpod_id or 'N/A'})")
        if not comfy_url:
            logger.debug("[ComfyUI] URL not configured")
            return None
        
        try:
            # 1. Load and patch workflow
            workflow = await self._load_workflow()
            
            # 2. Apply prompt and parameters
            self._patch_workflow(workflow, prompt, character_name, extra_loras=extra_loras)
            
            # 3. Log complete prompt
            self._log_prompt(workflow, character_name)
            
            # 4. Submit to ComfyUI
            logger.debug(f"[ComfyUI] Generating {character_name}...")
            prompt_id = await self._submit_workflow(comfy_url, workflow)
            if not prompt_id:
                return None
            
            # 5. Wait and download
            img_path = await self._wait_and_download(
                comfy_url, prompt_id, character_name, save_dir
            )
            return img_path
            
        except Exception as e:
            logger.warning(f"[ComfyUI] Error: {e}")
            return None
    
    async def _load_workflow(self) -> Dict[str, Any]:
        """Load workflow JSON file.
        
        Returns:
            Workflow dict
        """
        async with aiofiles.open(self.workflow_path, "r") as f:
            content = await f.read()
            workflow = json.loads(content)
        
        # Remove _meta from all nodes (causes 400 errors)
        for node_id in list(workflow.keys()):
            if "_meta" in workflow[node_id]:
                del workflow[node_id]["_meta"]
        
        return workflow
    
    def _patch_workflow(
        self,
        workflow: Dict[str, Any],
        prompt: ImagePrompt,
        character_name: str,
        extra_loras: Optional[List[str]] = None,
    ) -> None:
        """Patch workflow with prompt parameters.

        Args:
            workflow: Workflow dict (modified in place)
            prompt: Image prompt
            character_name: Character name
            extra_loras: Optional list of "name:weight" clothing LoRA strings
        """
        # Node 2 = positive prompt
        if "2" in workflow:
            workflow["2"]["inputs"]["text"] = prompt.positive
        
        # Node 3 = negative prompt
        if "3" in workflow:
            workflow["3"]["inputs"]["text"] = prompt.negative
        
        # Node 7 = size
        # V4.6: Fixed to 1024x1024 for higher quality square images
        logger.debug(f"[ComfyClient] Using fixed size 1024x1024")
        if "7" in workflow:
            workflow["7"]["inputs"]["width"] = 1024
            workflow["7"]["inputs"]["height"] = 1024
        
        # Node 4 = seed
        if "4" in workflow:
            seed = prompt.seed or int(time.time()) % 1000000000
            workflow["4"]["inputs"]["noise_seed"] = seed
        
        # Node 9 = filename prefix
        if "9" in workflow:
            prefix = character_name or "Luna"
            workflow["9"]["inputs"]["filename_prefix"] = f"{prefix}_ComfyUI"
        
        # Setup LoRA stacking
        self._setup_lora_stack(workflow, character_name, extra_loras=extra_loras)
        
        # Sampler settings
        if "5" in workflow:
            workflow["5"]["inputs"]["sampler_name"] = getattr(prompt, "sampler", None) or "euler"
        if "6" in workflow:
            workflow["6"]["inputs"]["scheduler"] = "karras"
            workflow["6"]["inputs"]["cfg"] = getattr(prompt, "cfg_scale", 7.0) or 7.0
    
    def _setup_lora_stack(
        self,
        workflow: Dict[str, Any],
        character_name: str,
        extra_loras: Optional[List[str]] = None,
    ) -> None:
        """Setup LoRA stacking nodes.

        Fixed nodes: 20 (character), 23 (Expressive_H), 24 (FantasyWorldPony).
        Dynamic clothing LoRAs are added as nodes 25, 26, ... chained after node 24.

        Args:
            workflow: Workflow dict
            character_name: Character name for character LoRA
            extra_loras: Optional list of "name.safetensors:weight" or "name:weight" strings
        """
        # Get character LoRA
        lora_name, lora_strength = self.lora_config.get(
            character_name,
            ("stsDebbie-10e.safetensors", 0.7)
        )

        # Node 20 = Character LoRA
        if "20" in workflow:
            workflow["20"]["inputs"]["lora_name"] = lora_name
            workflow["20"]["inputs"]["strength_model"] = lora_strength

        # Node 23 = Expressive_H LoRA (weight 0.2)
        workflow["23"] = {
            "inputs": {
                "lora_name": "Expressive_H-000001.safetensors",
                "strength_model": 0.2,
                "strength_clip": 1.0,
                "model": ["20", 0],
                "clip": ["20", 1],
            },
            "class_type": "LoraLoader",
        }

        # Node 24 = FantasyWorldPonyV2 LoRA (weight 0.4)
        workflow["24"] = {
            "inputs": {
                "lora_name": "FantasyWorldPonyV2.safetensors",
                "strength_model": 0.4,
                "strength_clip": 1.0,
                "model": ["23", 0],
                "clip": ["23", 1],
            },
            "class_type": "LoraLoader",
        }

        # Dynamic clothing LoRAs — nodes 25, 26, ...
        last_node = "24"
        if extra_loras:
            for i, lora_spec in enumerate(extra_loras):
                parts = lora_spec.rsplit(":", 1)
                if len(parts) != 2:
                    continue
                dyn_name, dyn_weight_str = parts
                try:
                    dyn_weight = float(dyn_weight_str)
                except ValueError:
                    continue
                # Ensure .safetensors extension
                if not dyn_name.endswith(".safetensors"):
                    dyn_name = dyn_name + ".safetensors"
                node_id = str(25 + i)
                workflow[node_id] = {
                    "inputs": {
                        "lora_name": dyn_name,
                        "strength_model": dyn_weight,
                        "strength_clip": 1.0,
                        "model": [last_node, 0],
                        "clip": [last_node, 1],
                    },
                    "class_type": "LoraLoader",
                }
                last_node = node_id
                logger.debug(f"[ComfyUI] Clothing LoRA added: {dyn_name} @ {dyn_weight}")

        # Reconnect sampler/clip to last LoRA node
        if "4" in workflow:
            workflow["4"]["inputs"]["model"] = [last_node, 0]
        if "6" in workflow:
            workflow["6"]["inputs"]["model"] = [last_node, 0]
        if "2" in workflow:
            workflow["2"]["inputs"]["clip"] = [last_node, 1]
        if "3" in workflow:
            workflow["3"]["inputs"]["clip"] = [last_node, 1]
    
    def _log_prompt(self, workflow: Dict[str, Any], character_name: str) -> None:
        """Log complete prompt for debugging.
        
        Args:
            workflow: Patched workflow
            character_name: Character name
        """
        logger.debug(f"\n{'='*60}")
        logger.debug(f"[COMFYUI PROMPT - {character_name}]")
        logger.debug(f"{'='*60}")
        
        if "1" in workflow:
            logger.debug(f"Checkpoint: {workflow['1']['inputs'].get('ckpt_name', 'unknown')}")
        
        logger.debug(f"Size: {workflow.get('7', {}).get('inputs', {}).get('width', '?')}x"
                     f"{workflow.get('7', {}).get('inputs', {}).get('height', '?')}")
        logger.debug(f"Seed: {workflow.get('4', {}).get('inputs', {}).get('noise_seed', '?')}")
        logger.debug(f"Scheduler: {workflow.get('6', {}).get('inputs', {}).get('scheduler', '?')}")

        logger.debug(f"\n--- LoRA Stack ---")
        logger.debug(f"  1. {workflow.get('20', {}).get('inputs', {}).get('lora_name', '?')} "
                     f"(strength: {workflow.get('20', {}).get('inputs', {}).get('strength_model', '?')})")
        logger.debug(f"  2. {workflow.get('23', {}).get('inputs', {}).get('lora_name', '?')} "
                     f"(strength: {workflow.get('23', {}).get('inputs', {}).get('strength_model', '?')})")
        logger.debug(f"  3. {workflow.get('24', {}).get('inputs', {}).get('lora_name', '?')} "
                     f"(strength: {workflow.get('24', {}).get('inputs', {}).get('strength_model', '?')})")
        
        logger.debug(f"\n--- Positive Prompt (FULL) ---")
        positive_text = workflow.get("2", {}).get("inputs", {}).get("text", "")
        logger.debug(positive_text)
        logger.debug(f"\n[Prompt length: {len(positive_text)} chars]")
        logger.debug(f"{'='*60}\n")
    
    async def _submit_workflow(
        self,
        comfy_url: str,
        workflow: Dict[str, Any],
    ) -> Optional[str]:
        """Submit workflow to ComfyUI.
        
        Args:
            comfy_url: ComfyUI URL
            workflow: Patched workflow
            
        Returns:
            Prompt ID or None
        """
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(
                f"{comfy_url}/prompt",
                json={"prompt": workflow, "client_id": self.client_id}
            ) as resp:
                if resp.status != 200:
                    error_body = await resp.text()
                    logger.warning(f"[ComfyUI] Queue failed: {resp.status}")
                    logger.warning(f"[ComfyUI] Error: {error_body[:500]}")
                    return None
                
                data = await resp.json()
                prompt_id = data.get("prompt_id")
                if prompt_id:
                    logger.debug(f"[ComfyUI] Queue ID: {prompt_id}")
                return prompt_id
    
    async def _wait_and_download(
        self,
        comfy_url: str,
        prompt_id: str,
        character: str,
        save_dir: Optional[Path],
    ) -> Optional[Path]:
        """Wait for generation and download result.
        
        Args:
            comfy_url: ComfyUI URL
            prompt_id: Prompt ID
            character: Character name
            save_dir: Save directory
            
        Returns:
            Path to downloaded image or None
        """
        max_wait = 120  # 2 minutes
        poll_interval = 2  # Check every 2 seconds
        
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            for attempt in range(0, max_wait, poll_interval):
                await asyncio.sleep(poll_interval)
                
                try:
                    async with session.get(f"{comfy_url}/history/{prompt_id}") as r:
                        if r.status == 200:
                            data = await r.json()
                            outputs = data.get(prompt_id, {}).get("outputs", {})
                            
                            if outputs:  # Complete!
                                logger.debug(f"[ComfyUI] Done in {attempt + poll_interval}s")
                                
                                # Download image
                                for nid, node in outputs.items():
                                    images = node.get("images", [])
                                    for img in images:
                                        fname = img.get("filename", "")
                                        if fname.endswith(".png"):
                                            return await self._download_image(
                                                session, comfy_url, fname, character, save_dir
                                            )
                                return None
                                
                except Exception as e:
                    logger.warning(f"[!] Poll error: {e}")
                    continue
            
            logger.debug("[ComfyUI] Timeout waiting for generation")
            return None
    
    async def _download_image(
        self,
        session: aiohttp.ClientSession,
        comfy_url: str,
        filename: str,
        character: str,
        save_dir: Optional[Path],
    ) -> Optional[Path]:
        """Download image from ComfyUI.
        
        Args:
            session: HTTP session
            comfy_url: ComfyUI URL
            filename: Image filename
            character: Character name
            save_dir: Save directory
            
        Returns:
            Path to saved image or None
        """
        async with session.get(f"{comfy_url}/view?filename={filename}") as r:
            if r.status == 200:
                img_data = await r.read()
                
                # Determine save path
                if save_dir is None:
                    save_dir = Path("storage/images")
                save_dir.mkdir(parents=True, exist_ok=True)
                
                path = save_dir / f"{character}_{int(time.time())}.png"
                
                async with aiofiles.open(path, "wb") as f:
                    await f.write(img_data)
                
                logger.debug(f"[ComfyUI] Saved: {path}")
                return path
            
            return None


# Need asyncio import
import asyncio
