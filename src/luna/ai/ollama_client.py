"""Luna RPG v8 - Ollama LLM Client.

Usa modelli Llama/Qwen/Mistral via Ollama su RunPod (o in locale).

URL su RunPod:  https://{runpod_id}-11434.proxy.runpod.net
URL in locale:  http://localhost:11434

Configurazione .env:
    LLM_PROVIDER=ollama
    OLLAMA_MODEL=qwen2.5:32b
    EXECUTION_MODE=RUNPOD
    RUNPOD_ID=lj13bxzxitso4n

NOTA: usa stream=true per evitare timeout del proxy RunPod (2 min).
      Con stream=false la risposta arriva solo a fine generazione
      e il proxy va in timeout prima.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp

from luna.ai.base import BaseLLMClient
from luna.ai.json_repair import RepairErrorType, repair_json
from luna.core.models import LLMResponse, StateUpdate

logger = logging.getLogger(__name__)


class OllamaClient(BaseLLMClient):
    """Client Ollama — modelli locali su RunPod o PC."""

    DEFAULT_MODEL   = "qwen2.5:32b"
    TEMPERATURE     = 0.95
    MAX_TOKENS      = 4096
    REQUEST_TIMEOUT = 300  # 5 minuti — abbondante per 32B

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        from luna.core.config import get_settings
        settings = get_settings()

        resolved_model = (
            model
            or os.environ.get("OLLAMA_MODEL", "")
            or self.DEFAULT_MODEL
        )
        super().__init__(resolved_model, **kwargs)

        self.base_url = (
            base_url
            or os.environ.get("OLLAMA_URL", "")
            or settings.ollama_url
        ).rstrip("/")

        self.temperature  = temperature if temperature is not None else self.TEMPERATURE
        self.max_tokens   = max_tokens  if max_tokens  is not None else self.MAX_TOKENS
        self.timeout      = aiohttp.ClientTimeout(total=self.REQUEST_TIMEOUT)
        self._initialized = True

        logger.info(
            "[Ollama] Client pronto — model: %s  url: %s",
            self.model, self.base_url
        )

    @property
    def provider_name(self) -> str:
        return "ollama"

    # -------------------------------------------------------------------------
    # Health check
    # -------------------------------------------------------------------------

    async def health_check(self) -> bool:
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=8)
            ) as session:
                async with session.get(f"{self.base_url}/api/tags") as resp:
                    if resp.status != 200:
                        logger.warning("[Ollama] Server HTTP %d", resp.status)
                        return False
                    data  = await resp.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    base   = self.model.split(":")[0]
                    found  = any(m == self.model or m.startswith(base) for m in models)
                    if not found:
                        logger.warning(
                            "[Ollama] Modello '%s' non trovato. Disponibili: %s",
                            self.model, ", ".join(models) or "(nessuno)"
                        )
                    return found
        except aiohttp.ClientConnectorError:
            logger.warning("[Ollama] Connessione rifiutata a %s", self.base_url)
            return False
        except Exception as e:
            logger.warning("[Ollama] Health check error: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Generation — streaming per evitare timeout proxy RunPod
    # -------------------------------------------------------------------------

    async def generate(
        self,
        system_prompt: str,
        user_input: str,
        history: List[Dict[str, str]],
        json_mode: bool = True,
        companion_name: Optional[str] = None,
    ) -> LLMResponse:
        messages = self._build_messages(system_prompt, user_input, history)

        payload: Dict[str, Any] = {
            "model":      self.model,
            "messages":   messages,
            "stream":     True,       # STREAMING: evita timeout proxy RunPod
            "keep_alive": "10m",      # mantieni modello in VRAM 10 min
            "options": {
                "temperature": self.temperature,
                "top_p":       0.98,
                "top_k":       40,
                "num_predict": 1024,   # risposte RPG raramente superano 300 token
            },
        }

        if json_mode:
            payload["format"] = "json"

        try:
            raw = await self._stream_response(payload)
        except aiohttp.ClientConnectorError:
            logger.error("[Ollama] Impossibile connettersi a %s", self.base_url)
            return self._create_error_response("Ollama non raggiungibile")
        except TimeoutError:
            logger.warning("[Ollama] Timeout dopo %ds", self.REQUEST_TIMEOUT)
            return self._create_error_response("Timeout generazione")
        except Exception as e:
            logger.warning("[Ollama] Errore: %s", e)
            return self._create_error_response(str(e))

        if not raw:
            logger.warning("[Ollama] Risposta vuota")
            return self._create_error_response("Risposta vuota")

        logger.debug("[Ollama] %s OK (%d chars)", self.model, len(raw))
        return self._parse(raw)

    async def _stream_response(self, payload: Dict[str, Any]) -> str:
        """Legge lo stream di Ollama e assembla la risposta completa.

        Con stream=true Ollama manda chunk JSON uno per riga.
        Ogni chunk ha {"message": {"content": "..."}, "done": false/true}.
        Assembliamo tutto fino a done=true.
        Questo evita il timeout del proxy RunPod (max 2 min senza dati).
        """
        collected = []

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(
                f"{self.base_url}/api/chat",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(
                        "[Ollama] HTTP %d — %s", resp.status, body[:200]
                    )
                    raise Exception(f"HTTP {resp.status}: {body[:100]}")

                # Legge riga per riga (ogni riga è un chunk JSON)
                async for line in resp.content:
                    line = line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            collected.append(content)
                        if chunk.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue

        return "".join(collected)

    # -------------------------------------------------------------------------
    # Parsing
    # -------------------------------------------------------------------------

    def _parse(self, raw: str) -> LLMResponse:
        result = repair_json(raw)

        if result.error_type == RepairErrorType.EMPTY or result.data is None:
            logger.warning("[Ollama] JSON non valido — uso testo grezzo")
            return LLMResponse(
                text=raw.strip(),
                visual_en="",
                tags_en=[],
                provider=f"ollama/{self.model}",
            )

        data = result.data
        if not data.get("text"):
            data["text"] = (
                data.get("response", "")
                or data.get("content", "")
                or raw.strip()
            )

        if result.was_repaired:
            logger.debug("[Ollama] JSON riparato")

        return self._build_response(data)

    def _build_response(self, data: Dict[str, Any]) -> LLMResponse:
        updates_data = data.get("updates", {})
        try:
            updates = StateUpdate(**updates_data) if updates_data else StateUpdate()
        except Exception:
            updates = StateUpdate()

        return LLMResponse(
            text=data.get("text", ""),
            visual_en=data.get("visual_en", ""),
            tags_en=data.get("tags_en", []),
            body_focus=data.get("body_focus"),
            aspect_ratio=data.get("aspect_ratio", "portrait"),
            dop_reasoning=data.get("dop_reasoning", ""),
            composition=data.get("composition"),
            secondary_characters=data.get("secondary_characters", []),
            approach_used=data.get("approach_used", "standard"),
            updates=updates,
            raw_response=data.get("_raw", ""),
            provider=f"ollama/{self.model}",
        )
