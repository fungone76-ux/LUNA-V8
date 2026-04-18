"""Async ComfyUI client for image generation.

Real implementation based on v3 - uses ComfyUI API with workflow patching.
"""

from __future__ import annotations
import asyncio
import logging
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

logger = logging.getLogger(__name__)


class ComfyUIClient:
    """Real async ComfyUI client for image generation."""

    def __init__(self, workflow_path: Optional[Path] = None) -> None:
        self.settings    = get_settings()
        self.client_id   = str(uuid.uuid4())
        self.workflow_path = self._resolve_workflow_path(workflow_path)
        self.timeout     = aiohttp.ClientTimeout(total=300)

        self.lora_config = {
            "Luna":  ("stsDebbie-10e.safetensors",           0.7),
            "Stella":("alice_milf_catchers_lora.safetensors", 0.7),
            "Maria": ("stsSmith-10e.safetensors",             0.65),
        }

    # ------------------------------------------------------------------
    # Workflow path resolution
    # ------------------------------------------------------------------

    def _resolve_workflow_path(self, override: Optional[Path]) -> Path:
        filename   = "comfy_workflow_image.json"
        candidates: List[Path] = []

        if override:
            return Path(override).expanduser().resolve()

        env_override = os.environ.get("COMFY_WORKFLOW_IMAGE_PATH")
        if env_override:
            candidates.append(Path(env_override).expanduser().resolve())

        project_root = _find_project_root()
        candidates += [
            (project_root / "config" / filename).resolve(),
            (project_root / filename).resolve(),
            (Path.cwd() / "config" / filename).resolve(),
            (Path.cwd() / filename).resolve(),
        ]

        for c in candidates:
            if c.exists():
                logger.debug("[ComfyUI] Workflow: %s", c)
                return c

        logger.warning("[ComfyUI] Workflow file not found in: %s",
                       ", ".join(str(p) for p in candidates))
        return candidates[0]

    # ------------------------------------------------------------------
    # Connection health check
    # ------------------------------------------------------------------

    async def check_connection(self, comfy_url: str) -> bool:
        """Verifica che ComfyUI sia raggiungibile e pronto.

        Fa un GET /system_stats — risposta JSON valida = OK.
        Risposta vuota o HTML = pod non pronto.
        """
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as session:
                async with session.get(f"{comfy_url}/system_stats") as resp:
                    body = await resp.text()
                    if resp.status == 200 and body.strip().startswith("{"):
                        logger.info("[ComfyUI] Server OK — %s", comfy_url)
                        return True
                    else:
                        logger.warning(
                            "[ComfyUI] Server not ready — HTTP %d — body: %s",
                            resp.status, body[:200] or "(vuoto)"
                        )
                        return False
        except aiohttp.ClientConnectorError as e:
            logger.warning("[ComfyUI] Connessione rifiutata: %s", e)
            return False
        except asyncio.TimeoutError:
            logger.warning("[ComfyUI] Timeout connessione a %s", comfy_url)
            return False
        except Exception as e:
            logger.warning("[ComfyUI] Health check error: %s", e)
            return False

    # ------------------------------------------------------------------
    # Main generate
    # ------------------------------------------------------------------

    async def generate(
        self,
        prompt: ImagePrompt,
        character_name: str = "",
        save_dir: Optional[Path] = None,
        extra_loras: Optional[List[str]] = None,
    ) -> Optional[Path]:
        comfy_url = self.settings.comfy_url
        logger.debug(
            "[ComfyUI] URL: %s (mode: %s, runpod_id: %s)",
            comfy_url,
            self.settings.execution_mode,
            self.settings.runpod_id or "N/A",
        )

        if not comfy_url:
            logger.warning("[ComfyUI] URL non configurata — immagine saltata")
            return None

        # ── Health check prima di generare ────────────────────────────
        ready = await self.check_connection(comfy_url)
        if not ready:
            logger.warning(
                "[ComfyUI] Server non raggiungibile a %s\n"
                "  → Se usi RunPod: assicurati che il pod sia AVVIATO "
                "e ComfyUI sia in esecuzione prima di lanciare il gioco.",
                comfy_url,
            )
            return None

        try:
            workflow = await self._load_workflow()
            self._patch_workflow(workflow, prompt, character_name,
                                 extra_loras=extra_loras)
            self._log_prompt(workflow, character_name)

            prompt_id = await self._submit_workflow(comfy_url, workflow)
            if not prompt_id:
                return None

            return await self._wait_and_download(
                comfy_url, prompt_id, character_name, save_dir
            )

        except Exception as e:
            logger.warning("[ComfyUI] Errore generazione: %s", e)
            return None

    # ------------------------------------------------------------------
    # Workflow loading & patching
    # ------------------------------------------------------------------

    async def _load_workflow(self) -> Dict[str, Any]:
        async with aiofiles.open(self.workflow_path, "r") as f:
            content = await f.read()
        workflow = json.loads(content)
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
        if "2" in workflow:
            workflow["2"]["inputs"]["text"] = prompt.positive
        if "3" in workflow:
            workflow["3"]["inputs"]["text"] = prompt.negative
        if "7" in workflow:
            workflow["7"]["inputs"]["width"]  = 1024
            workflow["7"]["inputs"]["height"] = 1024
        if "4" in workflow:
            seed = prompt.seed or int(time.time()) % 1_000_000_000
            workflow["4"]["inputs"]["noise_seed"] = seed
        if "9" in workflow:
            workflow["9"]["inputs"]["filename_prefix"] = f"{character_name or 'Luna'}_ComfyUI"
        if "5" in workflow:
            workflow["5"]["inputs"]["sampler_name"] = (
                getattr(prompt, "sampler", None) or "euler"
            )
        if "6" in workflow:
            workflow["6"]["inputs"]["scheduler"] = "karras"
            workflow["6"]["inputs"]["cfg"] = getattr(prompt, "cfg_scale", 7.0) or 7.0

        self._setup_lora_stack(workflow, character_name, extra_loras=extra_loras)

    def _setup_lora_stack(
        self,
        workflow: Dict[str, Any],
        character_name: str,
        extra_loras: Optional[List[str]] = None,
    ) -> None:
        lora_name, lora_strength = self.lora_config.get(
            character_name, ("stsDebbie-10e.safetensors", 0.7)
        )

        if "20" in workflow:
            workflow["20"]["inputs"]["lora_name"]      = lora_name
            workflow["20"]["inputs"]["strength_model"] = lora_strength

        workflow["23"] = {
            "inputs": {
                "lora_name":      "Expressive_H-000001.safetensors",
                "strength_model": 0.2,
                "strength_clip":  1.0,
                "model": ["20", 0],
                "clip":  ["20", 1],
            },
            "class_type": "LoraLoader",
        }
        workflow["24"] = {
            "inputs": {
                "lora_name":      "FantasyWorldPonyV2.safetensors",
                "strength_model": 0.4,
                "strength_clip":  1.0,
                "model": ["23", 0],
                "clip":  ["23", 1],
            },
            "class_type": "LoraLoader",
        }

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
                if not dyn_name.endswith(".safetensors"):
                    dyn_name += ".safetensors"
                node_id = str(25 + i)
                workflow[node_id] = {
                    "inputs": {
                        "lora_name":      dyn_name,
                        "strength_model": dyn_weight,
                        "strength_clip":  1.0,
                        "model": [last_node, 0],
                        "clip":  [last_node, 1],
                    },
                    "class_type": "LoraLoader",
                }
                last_node = node_id

        if "4" in workflow:
            workflow["4"]["inputs"]["model"] = [last_node, 0]
        if "6" in workflow:
            workflow["6"]["inputs"]["model"] = [last_node, 0]
        if "2" in workflow:
            workflow["2"]["inputs"]["clip"] = [last_node, 1]
        if "3" in workflow:
            workflow["3"]["inputs"]["clip"] = [last_node, 1]

    def _log_prompt(self, workflow: Dict[str, Any], character_name: str) -> None:
        logger.debug("\n%s\n[COMFYUI PROMPT — %s]\n%s",
                     "=" * 60, character_name, "=" * 60)
        if "1" in workflow:
            logger.debug("Checkpoint: %s",
                         workflow["1"]["inputs"].get("ckpt_name", "?"))
        logger.debug("Size: %sx%s",
                     workflow.get("7", {}).get("inputs", {}).get("width", "?"),
                     workflow.get("7", {}).get("inputs", {}).get("height", "?"))
        positive_text = workflow.get("2", {}).get("inputs", {}).get("text", "")
        logger.debug("Positive prompt (%d chars):\n%s", len(positive_text), positive_text)

    # ------------------------------------------------------------------
    # Submit & poll
    # ------------------------------------------------------------------

    async def _submit_workflow(
        self,
        comfy_url: str,
        workflow: Dict[str, Any],
    ) -> Optional[str]:
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(
                f"{comfy_url}/prompt",
                json={"prompt": workflow, "client_id": self.client_id},
            ) as resp:
                body = await resp.text()

                if resp.status != 200:
                    logger.warning(
                        "[ComfyUI] POST /prompt → HTTP %d\n  body: %s",
                        resp.status, body[:300] or "(vuoto)"
                    )
                    return None

                if not body or not body.strip():
                    logger.warning(
                        "[ComfyUI] POST /prompt → risposta vuota (HTTP 200)\n"
                        "  Il server ComfyUI ha risposto ma non ha restituito dati.\n"
                        "  Possibili cause:\n"
                        "  1. ComfyUI sta ancora caricando i modelli\n"
                        "  2. Il workflow JSON ha errori\n"
                        "  3. RunPod pod non completamente avviato"
                    )
                    return None

                try:
                    data = json.loads(body)
                except json.JSONDecodeError as e:
                    logger.warning(
                        "[ComfyUI] POST /prompt → risposta non-JSON: %s\n"
                        "  body: %s",
                        e, body[:300]
                    )
                    return None

                prompt_id = data.get("prompt_id")
                if prompt_id:
                    logger.debug("[ComfyUI] Queue ID: %s", prompt_id)
                else:
                    logger.warning("[ComfyUI] Nessun prompt_id nella risposta: %s",
                                   str(data)[:200])
                return prompt_id

    async def _wait_and_download(
        self,
        comfy_url: str,
        prompt_id: str,
        character: str,
        save_dir: Optional[Path],
    ) -> Optional[Path]:
        max_wait      = 120
        poll_interval = 2

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            for elapsed in range(0, max_wait, poll_interval):
                await asyncio.sleep(poll_interval)
                try:
                    async with session.get(
                        f"{comfy_url}/history/{prompt_id}"
                    ) as r:
                        if r.status == 200:
                            data    = await r.json()
                            outputs = data.get(prompt_id, {}).get("outputs", {})
                            if outputs:
                                logger.debug("[ComfyUI] Completato in %ds", elapsed + poll_interval)
                                for nid, node in outputs.items():
                                    for img in node.get("images", []):
                                        fname = img.get("filename", "")
                                        if fname.endswith(".png"):
                                            return await self._download_image(
                                                session, comfy_url, fname,
                                                character, save_dir
                                            )
                                return None
                except Exception as e:
                    logger.warning("[ComfyUI] Poll error: %s", e)
                    continue

            logger.warning("[ComfyUI] Timeout (%ds) aspettando generazione", max_wait)
            return None

    async def _download_image(
        self,
        session: aiohttp.ClientSession,
        comfy_url: str,
        filename: str,
        character: str,
        save_dir: Optional[Path],
    ) -> Optional[Path]:
        async with session.get(f"{comfy_url}/view?filename={filename}") as r:
            if r.status == 200:
                img_data = await r.read()
                if save_dir is None:
                    save_dir = Path("storage/images")
                save_dir.mkdir(parents=True, exist_ok=True)
                path = save_dir / f"{character}_{int(time.time())}.png"
                async with aiofiles.open(path, "wb") as f:
                    await f.write(img_data)
                logger.debug("[ComfyUI] Salvata: %s", path)
                return path
            logger.warning("[ComfyUI] Download fallito: HTTP %d", r.status)
            return None
