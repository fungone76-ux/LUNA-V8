"""Luna RPG v8 - LLM Manager.

Chain configurabile via LLM_PROVIDER nel .env:
  LLM_PROVIDER=ollama  -> Ollama (primary) -> Gemini -> Moonshot
  LLM_PROVIDER=gemini  -> Gemini (primary) -> Moonshot -> Claude

Timeout dinamico: 120s per Ollama, 30s per cloud API.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Tuple

from luna.ai.base import BaseLLMClient
from luna.ai.json_repair import _parse_hint
from luna.core.models import LLMResponse

logger = logging.getLogger(__name__)


class LLMManager:
    """Manages LLM providers with fallback and retry."""

    MAX_RETRIES = 3

    def __init__(self) -> None:
        from luna.core.config import get_settings
        self.settings    = get_settings()
        self._primary:   Optional[BaseLLMClient] = None
        self._fallback:  Optional[BaseLLMClient] = None
        self._fallback2: Optional[BaseLLMClient] = None
        self._clients:   Dict[str, BaseLLMClient] = {}
        self._init_clients()

    # -------------------------------------------------------------------------
    # Initialization
    # -------------------------------------------------------------------------

    def _init_clients(self) -> None:
        """Inizializza provider in base a LLM_PROVIDER nel .env."""
        provider = self.settings.llm_provider.lower()
        logger.info("[LLMManager] Provider configurato: %s", provider)

        if provider == "ollama":
            self._init_ollama_chain()
        else:
            self._init_gemini_chain()

        if not self._primary and not self._fallback and not self._fallback2:
            logger.critical(
                "[LLMManager] Nessun provider disponibile! LLM_PROVIDER=%s", provider
            )

    def _init_ollama_chain(self) -> None:
        """Ollama (primary) -> Gemini (fallback) -> Moonshot (fallback2)."""

        # 1. PRIMARY: Ollama
        try:
            from luna.ai.ollama_client import OllamaClient
            client = OllamaClient()
            self._clients["ollama"] = client
            self._primary = client
            logger.info(
                "[LLMManager] Ollama inizializzato (PRIMARY) — model: %s  url: %s",
                client.model, client.base_url,
            )
        except Exception as e:
            logger.error("[LLMManager] Ollama init failed: %s", e)

        # 2. FALLBACK: Gemini
        try:
            from luna.ai.gemini import GeminiClient
            client = GeminiClient()
            self._clients["gemini"] = client
            self._fallback = client
            logger.info("[LLMManager] Gemini inizializzato (FALLBACK)")
        except Exception as e:
            logger.warning("[LLMManager] Gemini non disponibile: %s", e)

        # 3. FALLBACK 2: Moonshot
        if self.settings.moonshot_api_key:
            try:
                from luna.ai.moonshot import MoonshotClient
                client = MoonshotClient(api_key=self.settings.moonshot_api_key)
                self._clients["moonshot"] = client
                self._fallback2 = client
                logger.info("[LLMManager] Moonshot inizializzato (FALLBACK 2)")
            except Exception as e:
                logger.warning("[LLMManager] Moonshot non disponibile: %s", e)

    def _init_gemini_chain(self) -> None:
        """Gemini (primary) -> Moonshot (fallback) -> Claude (fallback2)."""

        # 1. PRIMARY: Gemini
        try:
            from luna.ai.gemini import GeminiClient
            client = GeminiClient()
            self._clients["gemini"] = client
            self._primary = client
            logger.info("[LLMManager] Gemini inizializzato (PRIMARY)")
        except Exception as e:
            logger.error("[LLMManager] Gemini init failed: %s", e)

        # 2. FALLBACK: Moonshot
        if self.settings.moonshot_api_key:
            try:
                from luna.ai.moonshot import MoonshotClient
                client = MoonshotClient(api_key=self.settings.moonshot_api_key)
                self._clients["moonshot"] = client
                self._fallback = client
                logger.info("[LLMManager] Moonshot inizializzato (FALLBACK)")
            except Exception as e:
                logger.error("[LLMManager] Moonshot init failed: %s", e)

        # 3. FALLBACK 2: Claude
        if self.settings.anthropic_api_key:
            try:
                from luna.ai.claude_client import ClaudeClient
                client = ClaudeClient(api_key=self.settings.anthropic_api_key)
                self._clients["claude"] = client
                self._fallback2 = client
                logger.info("[LLMManager] Claude inizializzato (FALLBACK 2)")
            except Exception as e:
                logger.error("[LLMManager] Claude init failed: %s", e)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def generate(
        self,
        system_prompt: str,
        user_input: str,
        history: Optional[List[Dict]] = None,
        json_mode: bool = True,
        companion_name: str = "NPC",
    ) -> Tuple[LLMResponse, str]:
        """Generate response with automatic fallback chain.

        Returns (LLMResponse, provider_used).
        Never raises — always returns a valid response.
        """
        history = history or []

        providers = [
            (self._primary,   "primary"),
            (self._fallback,  "fallback"),
            (self._fallback2, "fallback2"),
        ]

        for client, label in providers:
            if client is None:
                continue
            result, provider = await self._try_provider(
                client, system_prompt, user_input, history, json_mode
            )
            if result is not None:
                logger.debug("[LLMManager] Success via %s (%s)", client.provider_name, label)
                return result, provider

        logger.error("[LLMManager] All providers failed — using base fallback")
        return self._guaranteed_fallback(companion_name), "fallback_base"

    async def generate_simple(self, prompt: str) -> Optional[str]:
        """Generate simple text (non-JSON) for summaries etc."""
        if self._primary:
            try:
                result, _ = await self.generate(
                    system_prompt="You are a helpful assistant. Be concise.",
                    user_input=prompt,
                    json_mode=False,
                )
                return result.text if result else None
            except Exception as e:
                logger.warning("[LLMManager] Simple generation failed: %s", e)
        return None

    def get_available_providers(self) -> List[str]:
        return list(self._clients.keys())

    def has_provider(self, name: str) -> bool:
        return name in self._clients

    # -------------------------------------------------------------------------
    # Retry logic
    # -------------------------------------------------------------------------

    async def _try_provider(
        self,
        client: BaseLLMClient,
        system_prompt: str,
        user_input: str,
        history: List[Dict],
        json_mode: bool,
    ) -> Tuple[Optional[LLMResponse], str]:
        """Try a provider up to MAX_RETRIES times.

        Timeout dinamico: 120s per Ollama (carica il modello),
        30s per API cloud (Gemini, Claude, Moonshot).
        """
        extra_hint = ""

        # Ollama locale e' piu' lento al primo avvio (carica il modello in VRAM)
        TIMEOUT = 300.0 if client.provider_name == "ollama" else 30.0

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = await asyncio.wait_for(
                    client.generate(
                        system_prompt=system_prompt + extra_hint,
                        user_input=user_input,
                        history=history,
                        json_mode=json_mode,
                    ),
                    timeout=TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[LLMManager] %s attempt %d/%d: timeout after %.0fs",
                    client.provider_name, attempt, self.MAX_RETRIES, TIMEOUT,
                )
                extra_hint = _parse_hint()
                continue
            except Exception as e:
                logger.warning(
                    "[LLMManager] %s attempt %d/%d exception: %s",
                    client.provider_name, attempt, self.MAX_RETRIES, e,
                )
                extra_hint = _parse_hint()
                continue

            if not response or not response.text:
                logger.warning(
                    "[LLMManager] %s attempt %d/%d: empty response",
                    client.provider_name, attempt, self.MAX_RETRIES,
                )
                extra_hint = _parse_hint()
                continue

            if response.text.startswith("[Error:"):
                logger.warning(
                    "[LLMManager] %s attempt %d/%d: error — %s",
                    client.provider_name, attempt, self.MAX_RETRIES, response.text[:80],
                )
                extra_hint = _parse_hint()
                continue

            return response, client.provider_name

        logger.warning(
            "[LLMManager] %s exhausted after %d attempts",
            client.provider_name, self.MAX_RETRIES,
        )
        return None, ""

    # -------------------------------------------------------------------------
    # Guaranteed fallback
    # -------------------------------------------------------------------------

    def _guaranteed_fallback(self, companion_name: str) -> LLMResponse:
        """Always returns a valid, natural-looking response."""
        client = self._primary or self._fallback or self._fallback2
        if client:
            return client._create_fallback_response(companion_name)

        return LLMResponse(
            text=(
                f"*{companion_name} ti guarda in silenzio.* "
                "\"Un momento...\""
            ),
            visual_en=f"{companion_name} standing, thoughtful expression",
            tags_en=["1girl", "standing", "looking_at_viewer"],
            provider="fallback_base",
        )

    # -------------------------------------------------------------------------
    # Health & cleanup
    # -------------------------------------------------------------------------

    async def health_check(self) -> Dict[str, bool]:
        results = {}
        for name, client in self._clients.items():
            try:
                results[name] = await client.health_check()
            except Exception:
                results[name] = False
        return results

    async def close(self) -> None:
        for client in self._clients.values():
            if hasattr(client, "close"):
                try:
                    await client.close()
                except Exception:
                    pass


# =============================================================================
# Singleton
# =============================================================================

_llm_manager: Optional[LLMManager] = None


def get_llm_manager() -> LLMManager:
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMManager()
    return _llm_manager


def reset_llm_manager() -> None:
    global _llm_manager
    _llm_manager = None
