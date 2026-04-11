"""Mock LLM client for testing without API keys."""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from luna.core.models import LLMResponse, StateUpdate
from luna.ai.base import BaseLLMClient


class MockLLMClient(BaseLLMClient):
    """Mock LLM client for development and testing.
    
    Returns predefined responses based on user input patterns.
    No API calls, no cost, instant responses.
    """
    
    DEFAULT_RESPONSES = [
        {
            "text": "Luna ti guarda con un sorriso enigmatico. 'Sei arrivato proprio al momento giusto', sussurra.",
            "visual_en": "Luna standing by the window, sunlight illuminating her long hair, mysterious smile",
            "tags_en": ["1girl", "school_uniform", "window", "sunlight", "smile"],
            "body_focus": "face",
        },
        {
            "text": "'Ho aspettato questo momento per tutto il giorno', ammette Luna, giocando con una ciocca di capelli.",
            "visual_en": "Luna twirling her hair with one finger, looking shy but happy, school background",
            "tags_en": ["1girl", "blushing", "playing_with_hair", "school"],
            "body_focus": "face",
        },
        {
            "text": "Luna si avvicina, il suo profumo di vaniglia riempie l'aria. 'Hai qualcosa da dirmi?'",
            "visual_en": "Luna leaning closer, intimate distance, vanilla scent atmosphere, detailed eyes",
            "tags_en": ["1girl", "close_up", "detailed_eyes", "leaning_forward"],
            "body_focus": "face",
        },
    ]
    
    def __init__(
        self,
        responses: Optional[List[Dict[str, Any]]] = None,
        fail_rate: float = 0.0,
        **kwargs: Any,
    ) -> None:
        """Initialize mock client.
        
        Args:
            responses: Custom response templates (uses defaults if None)
            fail_rate: Probability of simulating failure (0.0-1.0)
        """
        super().__init__("mock", **kwargs)
        self.responses = responses or self.DEFAULT_RESPONSES
        self.fail_rate = fail_rate
        self._initialized = True
        self._call_count = 0
    
    @property
    def provider_name(self) -> str:
        """Provider identifier."""
        return "mock"
    
    async def health_check(self) -> bool:
        """Mock is always ready."""
        return True
    
    async def generate(
        self,
        system_prompt: str,
        user_input: str,
        history: List[Dict[str, str]],
        json_mode: bool = True,
    ) -> LLMResponse:
        """Generate mock response.
        
        Args:
            system_prompt: Ignored in mock
            user_input: Used to select response variation
            history: Ignored
            json_mode: Ignored
            
        Returns:
            Mock LLMResponse
        """
        self._call_count += 1
        
        # Simulate random failures
        if random.random() < self.fail_rate:
            return self._create_error_response("Simulated failure")
        
        # Select response based on input hash for consistency
        response_idx = hash(user_input) % len(self.responses)
        template = self.responses[response_idx]
        
        # Add some variation based on call count
        text = template["text"]
        if "affinity" in user_input.lower():
            text += " (Senti che l'affinità è cresciuta.)"
        elif "outfit" in user_input.lower():
            text += " (Ha cambiato vestito.)"
        
        return LLMResponse(
            text=text,
            visual_en=template.get("visual_en", ""),
            tags_en=template.get("tags_en", []),
            body_focus=template.get("body_focus"),
            approach_used="standard",
            composition="medium_shot",
            updates=StateUpdate(),
            raw_response=str(template),
            provider=self.provider_name,
        )
    
    def get_call_count(self) -> int:
        """Return number of generate() calls made."""
        return self._call_count
    
    def reset(self) -> None:
        """Reset call counter."""
        self._call_count = 0
