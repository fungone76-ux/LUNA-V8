"""Intro Generation System - Opening scene generation.

V4 Refactor: Extracted from engine.py for cleaner architecture.
Handles:
- Opening scene generation when game starts
- First encounter narrative with main character
- Initial image generation
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from luna.core.models import GameState, LLMResponse, TurnResult

logger = logging.getLogger(__name__)


class IntroGenerator:
    """Generates the opening introduction scene."""
    
    def __init__(self, world, llm_manager, media_pipeline, memory_manager=None, gameplay_manager=None):
        """Initialize intro generator.
        
        Args:
            world: World definition
            llm_manager: LLM manager for generation
            media_pipeline: Media pipeline for images
            memory_manager: Optional memory manager
            gameplay_manager: Optional gameplay manager
        """
        self.world = world
        self.llm_manager = llm_manager
        self.media_pipeline = media_pipeline
        self.memory_manager = memory_manager
        self.gameplay_manager = gameplay_manager
    
    async def generate(
        self,
        game_state: GameState,
    ) -> TurnResult:
        """Generate opening introduction with character image.
        
        Creates the initial scene when the game starts:
        - Narrative introduction text
        - Character portrait image
        
        Args:
            game_state: Current game state
            
        Returns:
            Turn result with intro text and image path
        """
        companion = self.world.companions.get(game_state.active_companion)
        
        # Build intro-specific system prompt
        system_prompt = self._build_prompt(game_state, companion)
        
        # Generate intro via LLM
        try:
            _result = await self.llm_manager.generate(
                system_prompt=system_prompt,
                user_input="Generate the opening scene introduction.",
                history=[],
                json_mode=True,
            )
            # v6 returns tuple (response, provider), v5 returns response directly
            llm_response = _result[0] if isinstance(_result, tuple) else _result
            
            # Save to memory with companion isolation (V4.6)
            if self.memory_manager:
                await self.memory_manager.add_message(
                    role="assistant",
                    content=llm_response.text,
                    turn_number=0,
                    visual_en=llm_response.visual_en,
                    tags_en=llm_response.tags_en,
                    companion_name=game_state.active_companion,
                )
            
        except Exception as e:
            logger.error(f"[IntroGenerator] Intro generation failed: {e}")
            # Fallback intro - use location name instead of ID
            location_id = game_state.current_location
            loc_def = self.world.locations.get(location_id) if self.world else None
            location_name = loc_def.name if loc_def else location_id.replace("_", " ").title()
            
            llm_response = LLMResponse(
                text=f"Sei arrivato all'ingresso della scuola. {game_state.active_companion} ti aspetta.",
                visual_en=f"{game_state.active_companion} standing, welcoming expression, school entrance background",
                tags_en=["1girl", "solo", "standing", "smile"],
            )
        
        # Generate image
        outfit = game_state.get_outfit()
        
        # Get base prompt for active companion (SACRED for visual consistency)
        active_companion_def = self.world.companions.get(game_state.active_companion)
        base_prompt = active_companion_def.base_prompt if active_companion_def else None
        
        # V4.0: Get location description for image generation
        location_id = game_state.current_location
        location_desc = None
        if location_id and self.world:
            loc_def = self.world.locations.get(location_id)
            if loc_def:
                location_desc = loc_def.visual_style if loc_def.visual_style else loc_def.name
        
        # V4.2: Check if media pipeline available (may be disabled with --no-media)
        media_result = None
        if self.media_pipeline:
            media_result = await self.media_pipeline.generate_all(
                text=llm_response.text,
                visual_en=llm_response.visual_en,
                tags=llm_response.tags_en,
                companion_name=game_state.active_companion,
                outfit=outfit,
                base_prompt=base_prompt,  # SACRED: Use companion's base prompt from world YAML
                secondary_characters=None,  # Intro is always single character
                location_id=location_id,  # V4.0: Pass location for visual enforcement
                location_description=location_desc,
                location_visual_style=location_desc,  # V4.1: Pass for solo mode
            )
        else:
            logger.debug("[IntroGenerator] Media pipeline not available - skipping intro image")
        
        # Get available actions for intro
        available_actions = []
        if self.gameplay_manager:
            actions = self.gameplay_manager.get_available_actions(game_state)
            available_actions = [a.to_dict() for a in actions]
        
        return TurnResult(
            text=llm_response.text,
            image_path=media_result.image_path if media_result else None,
            audio_path=media_result.audio_path if media_result else None,
            turn_number=0,
            provider_used=getattr(llm_response, 'provider', 'unknown'),
            available_actions=available_actions,
        )
    
    def _build_prompt(
        self,
        game_state: GameState,
        companion: Optional[Any],
    ) -> str:
        """Build system prompt for intro generation.
        
        Args:
            game_state: Current game state
            companion: Active companion definition
            
        Returns:
            System prompt for intro
        """
        sections = [
            "=== LUNA RPG - OPENING SCENE ===",
            "",
            f"Genre: {self.world.genre}",
            f"World: {self.world.name}",
            "",
            "You are writing the OPENING SCENE of a visual novel.",
            "This is the first moment the player sees - make it captivating!",
            "",
            "=== SETTING ===",
            self.world.lore or self.world.description,
            "",
            "=== MAIN CHARACTER ===",
        ]
        
        if companion:
            # Use physical_description if available, fallback to base_prompt
            appearance = companion.physical_description or companion.base_prompt
            sections.extend([
                f"Name: {companion.name}",
                f"Role: {companion.role}",
                f"Age: {companion.age}",
                f"Personality: {companion.base_personality}",
                f"Appearance: {appearance}",
            ])
            if companion.wardrobe:
                default_outfit = list(companion.wardrobe.keys())[0]
                sections.append(f"Current Outfit: {default_outfit}")
        
        # Handle both enum and string time_of_day
        time_str = game_state.time_of_day.value if hasattr(game_state.time_of_day, 'value') else str(game_state.time_of_day)
        
        # V4.1 FIX: Get location description for intro
        location_desc = "Unknown location"
        location_visual = ""
        loc_def = None
        if game_state.current_location and self.world:
            loc_def = self.world.locations.get(game_state.current_location)
            if loc_def:
                location_desc = loc_def.description or loc_def.name
                location_visual = loc_def.visual_style or ""
        
        sections.extend([
            "",
            f"=== STARTING LOCATION ===",
            f"Location ID: {game_state.current_location}",
            f"Location Name: {loc_def.name if loc_def else game_state.current_location}",
            f"Location Description: {location_desc}",
            f"Visual Style: {location_visual}",
            f"Time: {time_str}",
            "",
            "CRITICAL - SET THE SCENE IN THE STARTING LOCATION:",
            f"1. The ENTIRE opening scene MUST take place in: {loc_def.name if loc_def else game_state.current_location}",
            "2. Describe the environment based on the Location Description above",
            "3. The visual_en background MUST reflect this location, not a generic classroom",
            f"4. Example: If location is 'Ingresso della Scuola', show the entrance, doors, students arriving",
            "",
            "=== YOUR TASK ===",
            "Write an engaging OPENING SCENE where the player FIRST ENCOUNTERS the main character.",
            "",
            "CRITICAL - FIRST MEETING RULES:",
            "1. This is the VERY FIRST TIME the characters meet",
            "2. The NPC does NOT know the player's name yet",
            "3. The NPC must NOT use the player's name in dialogue",
            "4. The NPC should address the player formally or with generic terms ('you', 'new student', 'stranger')",
            "5. Include a moment of introduction where names would naturally be exchanged",
            "",
            "Set the mood, describe the atmosphere, introduce the character naturally.",
            "",
            "=== VISUAL GENERATION (CRITICAL) ===",
            "The visual_en MUST include the character's BASE PROMPT for image generation:",
            "",
            f"BASE PROMPT for {companion.name if companion else 'character'}:",
            companion.base_prompt if companion else "1girl, solo, detailed",
            "",
            "INSTRUCTIONS:",
            "1. visual_en MUST start with the BASE PROMPT above (contains LoRAs and core features)",
            "2. Add pose, expression, clothing, lighting details AFTER the base prompt",
            "3. NEVER omit the base prompt - it defines the character's visual identity!",
            "",
            "=== OUTPUT FORMAT ===",
            "Respond with valid JSON:",
            "{",
            '  "text": "Opening narrative in Italian (2-3 paragraphs, immersive, set the scene)",',
            '  "visual_en": "BASE_PROMPT_HERE, pose, expression, clothing, lighting, background",',
            '  "tags_en": ["score_9", "score_8_up", "1girl", "solo", "portrait", ...],',
            '  "composition": "medium_shot"',
            "}",
            "",
            "=== RULES ===",
            "1. Introduce the character and setting naturally",
            "2. Use atmospheric, sensory details",
            "3. visual_en should focus on the character's appearance and expression",
            "4. This is the FIRST impression - make it memorable!",
            "",
            "=== END INSTRUCTIONS ===",
        ])
        
        return "\n".join(sections)
