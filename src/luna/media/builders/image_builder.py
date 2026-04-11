"""Luna RPG - Main Image Prompt Builder.

High-level builder that orchestrates the entire prompt building process.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .base import ImagePrompt
from .character_builders import MultiCharacterBuilder
from .constants import BASE_PROMPTS, NPC_BASE, NEGATIVE_PROMPTS
from .outfit_mapper import OutfitPromptMapper

from ..lora_mapping import LoraMapping

if TYPE_CHECKING:
    from luna.core.models import GameState, WorldDefinition

logger = logging.getLogger(__name__)

class ImagePromptBuilder:
    """Simple builder for creating ImagePrompt from basic parameters.
    
    Used by MediaPipeline for straightforward image generation.
    
    BASE_PROMPTS are SACRED - they define the core visual style and MUST be used.
    """
    
    def build(
        self,
        visual_description: str,
        tags: List[str],
        composition: str = "medium_shot",
        character_name: str = "",
        outfit: Optional[Any] = None,
        width: int = 896,
        height: int = 896,
        base_prompt: Optional[str] = None,
        secondary_characters: Optional[List[Dict[str, str]]] = None,
        location_visual_style: Optional[str] = None,
        aspect_ratio: str = "square",
        dop_reasoning: str = "",
        lora_mapping: Optional[LoraMapping] = None,
    ) -> ImagePrompt:
        """Build image prompt from basic parameters.
        
        Uses BASE_PROMPTS for character-specific LoRAs and quality tags.
        Supports multi-character scenes when secondary_characters is provided.
        
        Args:
            visual_description: Visual description text
            tags: SD tags list
            composition: Shot composition
            character_name: Character name (for BASE_PROMPTS lookup)
            outfit: Optional outfit state
            width: Image width
            height: Image height
            base_prompt: Optional explicit base prompt (from world YAML). If provided, overrides BASE_PROMPTS.
            secondary_characters: Optional list of secondary characters [{'name': 'X', 'base_prompt': 'Y'}]
            location_visual_style: V4: Visual style of current location (used when solo/no character)
            aspect_ratio: Director of Photography choice (landscape, portrait, square)
            dop_reasoning: Cinematographic reasoning for the aspect ratio choice
            
        Returns:
            ImagePrompt ready for generation
        """
        if not composition:
            logger.debug("[ImagePromptBuilder] Missing composition override, defaulting to medium_shot")
            composition = "medium_shot"
        # Check if multi-character scene
        if secondary_characters and len(secondary_characters) > 0:
            # Use MultiCharacterBuilder for multi-character scenes
            multi_builder = MultiCharacterBuilder()
            
            # Build characters list with primary + secondaries
            # Use the format expected by MultiCharacterBuilder
            characters = []
            
            # Primary character (center position)
            primary_outfit = outfit.style if outfit else ""
            characters.append({
                'name': character_name,
                'position': 'center',
                'outfit': primary_outfit,
                'base_prompt': base_prompt or "",
            })

            # Secondary characters (alternate left/right)
            positions = ['left', 'right']
            for i, char_data in enumerate(secondary_characters):
                char_name = char_data.get('name', '')
                char_outfit = char_data.get('outfit', '')
                position = positions[i % len(positions)]
                characters.append({
                    'name': char_name,
                    'position': position,
                    'outfit': char_outfit,
                    'base_prompt': char_data.get('base_prompt', ''),
                })
            
            # Build multi-character prompt using the builder
            return multi_builder.build_prompt(
                visual_description=visual_description,
                tags=tags,
                characters=characters,
                width=width,
                height=height,
            )
        
        # V4: Check if solo mode (no character, just environment)
        is_solo_mode = character_name == "_solo_" or character_name == ""
        
        if is_solo_mode:
            # Solo mode: Use location visual style instead of character
            logger.debug(f"[ImagePromptBuilder] Solo mode detected - using location visual style")
            if location_visual_style:
                # Use location style + quality tags
                character_base = f"score_9, score_8_up, masterpiece, photorealistic, detailed, {location_visual_style}"
            else:
                # Fallback to generic quality tags
                character_base = "score_9, score_8_up, masterpiece, photorealistic, detailed, atmospheric"
        elif base_prompt:
            # V3: Explicit base prompt provided
            character_base = base_prompt
        else:
            # Standard character: Use BASE_PROMPTS
            character_base = BASE_PROMPTS.get(character_name, NPC_BASE)
        
        # Check if visual_description already contains the base prompt (avoid duplication)
        # This happens when LLM follows the prompt instructions too literally
        visual_desc_clean = visual_description.strip()
        
        # Remove leading comma if present (to avoid ",," when joining)
        if visual_desc_clean.startswith(","):
            visual_desc_clean = visual_desc_clean[1:].strip()
        
        # Deduplication: Check if visual_description already contains base prompt content
        skip_base_prompt = False
        
        # Check 1: Contains LoRAs and quality tags - definitely has base prompt
        if "<lora:" in visual_desc_clean and "score_9" in visual_desc_clean:
            logger.warning(f"[ImagePromptBuilder] Detected LoRAs in visual_description, skipping base prompt")
            skip_base_prompt = True
        # Check 2: Contains key character keywords from base prompt (fuzzy match)
        elif character_base:
            # Extract key keywords from base prompt (first part without LoRAs)
            base_keywords = character_base.split('<lora:')[0].strip()
            # Check if main keywords are present in visual_description
            key_parts = ['score_9', 'score_8_up']
            if all(kw in visual_desc_clean for kw in key_parts):
                logger.warning(f"[ImagePromptBuilder] Base prompt keywords detected, skipping duplicate")
                skip_base_prompt = True
            # Check 3: visual_description starts with base prompt content
            elif visual_desc_clean.lower().startswith(base_keywords.lower()[:50]):
                logger.warning(f"[ImagePromptBuilder] Visual description starts with base prompt content, skipping")
                skip_base_prompt = True
        
        # If visual description already has base prompt content, remove it from visual_desc_clean
        # AND don't add character_base separately
        if skip_base_prompt:
            character_base = ""  # Don't add base prompt as prefix
            # Try to extract just the scene description part (after the duplicated base prompt)
            # Look for where score_9 ends and actual description begins
            if "score_9" in visual_desc_clean:
                # Find end of base prompt section (usually after first comma following LoRAs)
                lora_end = visual_desc_clean.rfind('>') if '<lora:' in visual_desc_clean else -1
                if lora_end > 0:
                    # Get everything after the last LoRA
                    after_loras = visual_desc_clean[lora_end+1:].strip()
                    # If it starts with comma, remove it
                    if after_loras.startswith(","):
                        after_loras = after_loras[1:].strip()
                    # If it still has score_9, take everything after it
                    if "score_9" in after_loras:
                        score_pos = after_loras.find("score_9")
                        # Find where score section ends (look for comma after score_8_up or similar)
                        search_start = score_pos + 10
                        next_comma = after_loras.find(",", search_start)
                        if next_comma > 0:
                            visual_desc_clean = after_loras[next_comma+1:].strip()
                        else:
                            visual_desc_clean = after_loras
                    else:
                        visual_desc_clean = after_loras
        
        # Build positive prompt - BASE_PROMPTS first (LoRAs must be at start)
        positive_parts = [
            character_base,  # SACRED: Contains LoRAs and core quality tags (if not already in visual_description)
        ]
        
        # V4.9: Add outfit using unified method (same as UI!)
        if outfit:
            outfit_prompt = outfit.to_sd_prompt(include_weight=False)
            if outfit_prompt:
                positive_parts.append(outfit_prompt)
                logger.debug(f"    [ImagePromptBuilder Outfit] Using unified: '{outfit_prompt[:60]}...'")
        
        # Add visual description (now cleaned of duplicates)
        if visual_desc_clean:
            positive_parts.append(visual_desc_clean)
        
        # Add tags if any (filter out quality tags and outfit-conflicting tags)
        if tags:
            # V4.6: Filter tags to avoid duplicating quality tags from base_prompt
            quality_tags = ['masterpiece', 'best quality', 'score_9', 'score_8_up', 'ultra detailed']
            filtered_tags = [t for t in tags if not any(qt in t.lower() for qt in quality_tags)]
            
            # V4.6 CRITICAL: Filter tags that conflict with current outfit
            # If outfit is nightwear/pajamas, remove conflicting tags like 'teacher suit', 'classroom', etc.
            if outfit and outfit.style:
                outfit_style_lower = outfit.style.lower()
                conflicting_tags = []
                
                # Define conflicts: if outfit is X, remove tags suggesting Y
                if outfit_style_lower in ['nightwear', 'pajamas', 'sleepwear', 'home', 'casual']:
                    # At home - remove work/school related tags
                    conflicting_tags = ['teacher suit', 'teacher', 'classroom', 'school uniform', 'office', 'work']
                elif outfit_style_lower in ['teacher_suit', 'professional', 'uniform_mod']:
                    # At work - remove home/sleep related tags
                    conflicting_tags = ['pajamas', 'sleepwear', 'nightgown', 'bedroom', 'home clothes']
                elif outfit_style_lower in ['gym_teacher', 'cheerleader', 'athletic', 'sportswear']:
                    # At gym - remove classroom/office tags
                    conflicting_tags = ['classroom', 'teacher suit', 'office', 'desk']
                
                if conflicting_tags:
                    original_count = len(filtered_tags)
                    filtered_tags = [t for t in filtered_tags if not any(ct in t.lower() for ct in conflicting_tags)]
                    if len(filtered_tags) < original_count:
                        logger.debug(f"    [ImagePromptBuilder] Removed {original_count - len(filtered_tags)} conflicting tags for outfit '{outfit.style}'")
            
            # V4.6: Remove tags that are already in visual_desc (avoid duplicates)
            if filtered_tags:
                visual_lower = visual_desc_clean.lower()
                unique_tags = []
                for tag in filtered_tags:
                    # Check if tag content is already in visual description
                    tag_normalized = tag.lower().replace('-', ' ')
                    if tag_normalized not in visual_lower and tag.lower() not in visual_lower:
                        unique_tags.append(tag)
                    else:
                        logger.debug(f"    [ImagePromptBuilder] Removing duplicate tag: '{tag}' (already in visual)")
                
                if unique_tags:
                    positive_parts.append(", ".join(unique_tags))
        
        # Add composition hints ONLY if visual description doesn't already contain composition
        # V4.6: Respect LLM/DoP choice - don't override with hardcoded composition
        composition_keywords = ['close-up', 'close up', 'medium shot', 'cowboy shot', 'wide shot', 
                                'full body', 'portrait', 'upper body', 'waist up',
                                'from below', 'from above', 'low angle', 'high angle',
                                'dutch angle', 'birds eye view', 'worm eye view']
        visual_lower = visual_desc_clean.lower()
        visual_has_composition = any(kw in visual_lower for kw in composition_keywords)
        
        logger.debug(f"    [ImagePromptBuilder] Visual has composition: {visual_has_composition}")
        logger.debug(f"    [ImagePromptBuilder] Visual desc (first 80 chars): {visual_desc_clean[:80]}...")
        
        if not visual_has_composition:
            # Only add default composition if LLM didn't specify one AND we have a default
            if composition:
                composition_hints = {
                    "close_up": "close-up portrait, face focus, detailed face",
                    "medium_shot": "medium shot",
                    "cowboy_shot": "cowboy shot, framing from knees up",
                    "wide_shot": "wide shot, full body, environmental",
                    "from_below": "shot from below, low angle",
                    "from_above": "shot from above, high angle",
                }
                if composition in composition_hints:
                    positive_parts.append(composition_hints[composition])
                    logger.debug(f"    [ImagePromptBuilder] Added default composition: {composition}")
            else:
                logger.warning(f"    [ImagePromptBuilder] No default composition specified, skipping")
        else:
            logger.warning(f"    [ImagePromptBuilder] Visual already has composition, skipping default")
        
        positive = ", ".join(filter(None, positive_parts))
        
        # V4.6: Final cleanup - remove duplicate consecutive words and excessive commas
        # Fix double commas and trim
        positive = re.sub(r',\s*,', ',', positive)  # Fix double commas
        positive = re.sub(r',\s*$', '', positive)   # Remove trailing comma
        positive = positive.strip()
        
        # V4.6: Aggiungi LoRA dinamici dal mapping (clothing/NSFW) se disponibili
        if lora_mapping and lora_mapping.is_enabled():
            # Crea outfit state dict
            outfit_state = None
            if outfit:
                outfit_state = {
                    "description": getattr(outfit, 'description', ''),
                    "style": getattr(outfit, 'style', ''),
                    "components": getattr(outfit, 'components', {})
                }
            
            # Seleziona LoRA extra
            extra_loras = lora_mapping.select_loras(tags or [], character_name, outfit_state)
            
            if extra_loras:
                # Costruisce stringa LoRA: <lora:name:weight>
                lora_tokens = [f"<lora:{name}:{weight:.2f}>" for name, weight in extra_loras]
                lora_string = " ".join(lora_tokens)
                
                # Aggiunge all'inizio del prompt (prima del resto)
                positive = f"{lora_string}, {positive}"
                logger.debug(f"[ImagePromptBuilder] LoRA attivi: {[n for n, _ in extra_loras]}")
        
        # V4.6: Removed automatic pantyhose feet fix - too aggressive
        # Only add feet tags if explicitly requested by LLM or player
        
        # Build negative prompt
        negative = NEGATIVE_PROMPTS["standard"]
        
        return ImagePrompt(
            positive=positive,
            negative=negative,
            width=width,
            height=height,
            composition=composition,
            aspect_ratio=aspect_ratio,
            dop_reasoning=dop_reasoning,
            steps=24,
            cfg_scale=7.0,
            sampler="euler",
            seed=None,
        )
    
    def _fix_pantyhose_feet(self, prompt: str) -> str:
        """Fix pantyhose prompt to ensure feet are covered.
        
        SD often renders feet as bare even when pantyhose/stockings are mentioned.
        This adds explicit feet coverage tags when pantyhose are detected.
        
        Args:
            prompt: Original prompt
            
        Returns:
            Corrected prompt
        """
        prompt_lower = prompt.lower()
        
        # Check if pantyhose or stockings are mentioned
        pantyhose_keywords = ['pantyhose', 'stockings', 'collant', 'tights']
        has_pantyhose = any(kw in prompt_lower for kw in pantyhose_keywords)
        
        if has_pantyhose:
            # Check if feet are already explicitly mentioned as covered
            feet_covered_phrases = [
                'feet covered', 'covered feet', 'pantyhose on feet',
                'stockings on feet', 'feet in pantyhose', 'feet in stockings'
            ]
            already_fixed = any(phrase in prompt_lower for phrase in feet_covered_phrases)
            
            if not already_fixed:
                # Add explicit feet coverage
                prompt += ", feet covered by pantyhose, sheer pantyhose on feet"
                logger.debug(f"[ImagePromptBuilder] Pantyhose detected - added explicit feet coverage")
        
        return prompt
