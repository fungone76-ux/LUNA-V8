"""Luna RPG - Character Prompt Builders.

Builders for single characters, multiple characters, and NPCs.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .base import BasePromptBuilder, ImagePrompt
from .constants import BASE_PROMPTS, NPC_BASE, NEGATIVE_PROMPTS, DIFFERENTIATION_BOOSTERS
from ...core.models.media_models import SceneAnalysis
from ...core.models.state_models import OutfitState

if TYPE_CHECKING:
    from luna.core.models import GameState, WorldDefinition

logger = logging.getLogger(__name__)

class SingleCharacterBuilder(BasePromptBuilder):
    """Builder for single character focus scenes.

    Optimized for one main character with detailed rendering.
    Uses BASE_PROMPTS from v3 (string format with embedded LoRAs).

    CRITICAL V3 FEATURE: Detects generic NPCs and uses NPC_BASE without LoRAs
    when the described character doesn't match the active companion.
    """

    base_prompts = BASE_PROMPTS

    # Known companion names (for LoRA detection)
    KNOWN_COMPANIONS = {"Luna", "Stella", "Maria"}
    
    def _is_generic_npc(self, visual_description: str, character_name: str) -> bool:
        """Detect if the scene describes a generic NPC, not the main companion.
        
        V3 Logic: Checks if visual description mentions traits different from companion.
        
        Args:
            visual_description: Visual description from LLM
            character_name: Active companion name
            
        Returns:
            True if this is a generic NPC (use NPC_BASE), False if main companion
        """
        if not visual_description:
            return False
        
        visual_lower = visual_description.lower()
        
        # Check if companion name is explicitly mentioned
        if character_name and character_name.lower() in visual_lower:
            # The description explicitly names the companion - use their LoRA
            return False
        
        # Check for hair color mismatches (companion-specific traits)
        companion_hair = {
            "Luna": ["brown hair", "brunette", "chestnut"],
            "Stella": ["blonde hair", "blond", "golden hair", "yellow hair"],
            "Maria": ["black hair", "dark hair", "grey hair", "gray hair"],
        }
        
        if character_name in companion_hair:
            expected_hair = companion_hair[character_name]
            # Check if visual mentions a DIFFERENT hair color
            hair_colors = {
                "red hair": ["redhead", "ginger", "auburn", "rossi", "rossa"],
                "blonde hair": ["blonde", "blond", "golden", "bionda", "biondo"],
                "brown hair": ["brown", "brunette", "chestnut", "castani", "marrone"],
                "black hair": ["black", "dark", "neri", "nera"],
                "white hair": ["white", "silver", "platinum", "bianchi", "argento"],
                "grey hair": ["grey", "gray", "grigi"],
            }
            
            for color, keywords in hair_colors.items():
                if any(kw in visual_lower for kw in keywords):
                    # This hair color is mentioned - check if it matches companion
                    if color not in expected_hair:
                        logger.debug(f"[SingleCharacterBuilder] Detected hair color mismatch: {color} vs {character_name}'s {expected_hair}")
                        return True
        
        # Check for generic NPC indicators
        generic_indicators = [
            "secretary", "segretaria", "librarian", "bibliotecaria",
            "nurse", "infermiera", "teacher", "professoressa",
            "student", "studentessa", "shopkeeper", "negoziante",
            "receptionist", "bartender", "waitress", "cameriera",
            "cashier", "cassiera", "passerby", "passante",
            "random woman", "unknown woman", "young woman", "mature woman",
            "redhead", "brunette", "blonde woman",
        ]
        
        for indicator in generic_indicators:
            if indicator in visual_lower:
                # Generic NPC indicator found and companion not named
                logger.debug(f"[SingleCharacterBuilder] Detected generic NPC indicator: {indicator}")
                return True
        
        return False
    
    def build_prompt(
        self,
        visual_description: str,
        tags: List[str],
        scene_analysis: Optional[SceneAnalysis] = None,
        character_name: str = "",
        outfit_description: str = "",
        outfit: Optional[OutfitState] = None,
        body_focus: Optional[str] = None,
        base_prompt: Optional[str] = None,  # V3: Explicit base prompt from companion
        **kwargs: Any,
    ) -> ImagePrompt:
        """Build single character prompt.
        
        Args:
            visual_description: Scene description
            tags: SD tags
            scene_analysis: Scene analysis
            character_name: Character name (for LoRA selection)
            outfit_description: Outfit/clothing description (legacy)
            outfit: Structured outfit state (preferred)
            body_focus: Body part in focus (face, hands, etc.)
            base_prompt: Optional explicit base prompt (from companion definition)
            
        Returns:
            Image prompt
        """
        # V3 LOGIC: Use explicit base_prompt if provided (for temporary NPCs)
        is_generic_npc = False
        if base_prompt:
            # Use the provided base prompt (already contains NPC_BASE + gender + type)
            char_prompt = base_prompt
            logger.debug(f"[SingleCharacterBuilder] Using explicit base_prompt for {character_name}")
        else:
            # V3 LOGIC: Detect if this is a generic NPC scene
            is_generic_npc = self._is_generic_npc(visual_description, character_name)
            
            if is_generic_npc:
                # Generic NPC: Use NPC_BASE without character LoRAs
                logger.debug(f"[SingleCharacterBuilder] Using generic NPC base (not {character_name})")
                char_prompt = NPC_BASE
            else:
                # Known companion: Use their specific base prompt with LoRAs
                char_prompt = self.base_prompts.get(character_name, NPC_BASE)
        
        # DEBUG logging
        logger.debug(f"    [DEBUG] character_name: {character_name}")
        logger.debug(f"    [DEBUG] is_generic_npc: {is_generic_npc}")
        logger.debug(f"    [DEBUG] char_prompt[:50]: {char_prompt[:50] if char_prompt else 'None'}...")
        
        # Check if visual_description already contains the base prompt (avoid duplication)
        # This happens when the LLM includes base prompt in visual_en following system prompt instructions
        visual_lower = visual_description.lower()
        
        # Check 1: Contains LoRAs (definite proof of base prompt inclusion)
        if "<lora:" in visual_description:
            logger.warning(f"[SingleCharacterBuilder] Detected LoRAs in visual_description, skipping base prompt")
            char_prompt = ""
        # Check 2: Contains quality tags that are in base prompt
        elif "score_9" in visual_lower and "score_8_up" in visual_lower and "masterpiece" in visual_lower:
            logger.warning(f"[SingleCharacterBuilder] Detected quality tags (score_9 + score_8_up + masterpiece) in visual_description, skipping base prompt")
            char_prompt = ""
        # Check 3: Contains character-specific LoRA triggers
        elif any(kw in visual_lower for kw in ["stsdebbie", "stssmith", "alice_milf_catchers"]):
            logger.warning(f"[SingleCharacterBuilder] Detected character LoRA triggers in visual_description, skipping duplicate")
            char_prompt = ""
        
        # Build additional context
        context_parts = []
        outfit_negative = ""
        
        # V3.5 PATTERN: Use OutfitPromptMapper for component-based outfit generation
        # This ensures clean prompts and proper negative keywords (e.g., barefoot -> no shoes)
        # V4.9: Also use base_sd_prompt when components are empty
        outfit_added = False
        if outfit:
            outfit_pos, outfit_neg = OutfitPromptMapper.map_outfit(outfit)
            if outfit_pos:
                context_parts.append(f"{outfit_pos},")
                logger.info(f"    [DEBUG Outfit] Using mapped outfit: '{outfit_pos[:80]}...'")
                outfit_added = True
            if outfit_neg:
                outfit_negative = outfit_neg
                
        # Fallback to description if map_outfit returned nothing
        if not outfit_added and outfit and outfit.description:
            clean_desc = outfit.description.strip()
            if clean_desc.lower().startswith("wearing "):
                context_parts.append(f"({clean_desc}:1.3),")
            elif "nude" in clean_desc.lower() or "naked" in clean_desc.lower():
                context_parts.append(f"(nude:1.3), {clean_desc},")
            else:
                context_parts.append(f"(wearing {clean_desc}:1.3),")
            logger.debug(f"    [DEBUG Outfit] Using description: '{clean_desc[:60]}...'")
            outfit_added = True
            
        # Legacy fallback
        if not outfit_added and outfit_description:
            clean_desc = outfit_description.strip()
            if clean_desc.lower().startswith("wearing "):
                context_parts.append(f"({clean_desc}:1.3),")
            elif "nude" in clean_desc.lower() or "naked" in clean_desc.lower():
                context_parts.append(f"(nude:1.3), {clean_desc},")
            else:
                context_parts.append(f"(wearing {clean_desc}:1.3),")
        
        # Add visual description
        context_parts.append(visual_description + ",")
        
        # Add tags
        cleaned_tags = self._sanitize_tags(tags)
        # Remove conflicting tags
        cleaned_tags = [t for t in cleaned_tags if t not in ("1girl", "solo")]
        
        # V3 LOGIC: For generic NPCs, remove character-specific tags
        if is_generic_npc:
            character_specific_tags = [
                "stsdebbie", "stssmith", "alice_milf_catchers",
                "brown hair", "blonde hair", "black hair",  # Hair colors from companions
            ]
            cleaned_tags = [t for t in cleaned_tags if t.lower() not in character_specific_tags]
            logger.debug(f"[SingleCharacterBuilder] Removed character-specific tags for generic NPC")
        
        if cleaned_tags:
            context_parts.append(", ".join(cleaned_tags) + ",")
        
        # Add body focus
        if body_focus:
            context_parts.append(f"{body_focus} focus,")
        
        # Combine: BASE_PROMPT (contains LoRAs) + context
        context_str = " ".join(context_parts)
        positive = f"{char_prompt}, {context_str}"
        
        # Apply composition
        if scene_analysis:
            positive = self._apply_composition(positive, scene_analysis.composition_type)
        
        # Parse LoRAs from the base prompt (for workflow building)
        lora_stack = self._parse_loras_from_prompt(char_prompt)
        
        # Build negative prompt with outfit negatives
        negative = NEGATIVE_PROMPTS["standard"]
        if outfit_negative:
            negative = f"{negative}, {outfit_negative}"
        
        return ImagePrompt(
            positive=positive,
            negative=negative,
            lora_stack=lora_stack,
            width=kwargs.get("width", 896),
            height=kwargs.get("height", 896),
            sampler="euler",
            cfg_scale=7.0,
        )

    def build(
        self,
        game_state,
        visual_en: str,
        tags_en: List[str],
        **kwargs: Any,
    ):
        """Build image prompt from game state (required by BasePromptBuilder)."""
        return self.build_prompt(
            visual_description=visual_en,
            tags=tags_en,
            character_name=kwargs.get("character_name", ""),
            outfit=kwargs.get("outfit"),
            base_prompt=kwargs.get("base_prompt"),
            width=kwargs.get("width", 896),
            height=kwargs.get("height", 896),
        )
    
    def _parse_loras_from_prompt(self, prompt: str) -> List[Dict[str, Any]]:
        """Extract LoRA definitions from prompt string.
        
        Args:
            prompt: Prompt containing <lora:name:weight> tags
            
        Returns:
            List of LoRA configs
        """
        import re
        loras = []
        pattern = r'<lora:([^:]+):([\d.]+)>'
        matches = re.findall(pattern, prompt)
        for name, weight in matches:
            loras.append({"name": name, "weight": float(weight)})
        return loras


class MultiCharacterBuilder(BasePromptBuilder):
    """Builder for multi-character scenes (2+ characters).

    Uses ENHANCED anti-fusion techniques from v3 to prevent character merging.
    """

    base_prompts = BASE_PROMPTS
    
    def build_prompt(
        self,
        visual_description: str,
        tags: List[str],
        scene_analysis: Optional[SceneAnalysis] = None,
        characters: Optional[List[Dict[str, str]]] = None,
        **kwargs: Any,
    ) -> ImagePrompt:
        """Build multi-character prompt with ENHANCED anti-fusion.
        
        Args:
            visual_description: Scene description
            tags: SD tags
            scene_analysis: Scene analysis
            characters: List of dicts with 'name', 'position', 'outfit', 'base_prompt'
            
        Returns:
            Image prompt
        """
        characters = characters or []
        
        # Build character-specific prompts with ENHANCED anti-fusion
        char_sections = []
        all_loras = []
        
        for i, char_data in enumerate(characters):
            name = char_data.get("name", f"girl_{i}")
            position = char_data.get("position", "")
            outfit = char_data.get("outfit", "")
            pose = char_data.get("pose", "")
            emotion = char_data.get("emotion", "")
            
            # Get base prompt: prefer explicit base_prompt from char_data, then fall back to dict
            char_base = char_data.get("base_prompt") or self.base_prompts.get(name, NPC_BASE)
            
            # ENHANCED: Individual character section with strong separation
            section_parts = [f"[[Character {i+1}: {name}]]"]
            section_parts.append(char_base)
            
            # Add pose and emotion for dynamic scene
            if emotion:
                section_parts.append(f"{emotion},")
            if pose:
                section_parts.append(f"{pose},")
            
            if outfit:
                section_parts.append(f"wearing {outfit},")
            
            if position:
                section_parts.append(f"positioned {position},")
            
            # ENHANCED: Strong focus on distinct features
            section_parts.append("distinct face, unique appearance,")
            section_parts.append("[[End Character]]")
            
            char_sections.append(" ".join(section_parts))
            
            # Collect LoRAs
            loras = self._parse_loras_from_prompt(char_base)
            all_loras.extend(loras)
        
        # Build main prompt with ENHANCED anti-fusion
        parts = [
            "masterpiece, best quality, highres,",
            f"{len(characters)}girls,",  # Correct girl count
        ]
        
        # ENHANCED: Add differentiation boosters FIRST (higher priority)
        parts.extend(DIFFERENTIATION_BOOSTERS[:4])  # Use top 4 boosters
        
        # Add character sections with clear separation
        parts.append("||")
        parts.extend(char_sections)
        parts.append("||")
        
        # Add scene context - dynamic scene description
        if visual_description:
            parts.append(f"scene: {visual_description},")
        
        # Add dynamic scene keywords based on character poses
        has_standing = any("standing" in c.get("pose", "") for c in characters)
        has_sitting = any("sitting" in c.get("pose", "") for c in characters)
        
        if has_standing and has_sitting:
            parts.append("classroom scene with teacher standing and student sitting,")
        elif len(characters) == 2:
            parts.append("classroom scene, dynamic interaction between teacher and student,")
        
        # Add tags
        cleaned_tags = self._sanitize_tags(tags)
        filtered_tags = [t for t in cleaned_tags if t not in ("1girl", "solo", "2girls", "3girls")]
        if filtered_tags:
            parts.append(", ".join(filtered_tags) + ",")
        
        # ENHANCED: Additional anti-fusion positive keywords
        parts.extend([
            "completely separate individuals,",
            "different hairstyles, different clothing,",
            "spatial separation, distinct silhouettes,",
            "no overlapping, no touching,",
        ])
        
        # Combine
        positive = " ".join(parts)
        
        # Force wide shot for groups
        positive = f"wide shot, {positive}"
        
        # Remove duplicate LoRAs
        unique_loras = []
        seen = set()
        for lora in all_loras:
            if lora["name"] not in seen:
                seen.add(lora["name"])
                unique_loras.append(lora)
        
        return ImagePrompt(
            positive=positive,
            negative=NEGATIVE_PROMPTS["multi_character"],  # Enhanced negative
            lora_stack=unique_loras,
            width=kwargs.get("width", 896),
            height=kwargs.get("height", 896),
            sampler="euler",
            cfg_scale=7.0,
        )

    def build(
        self,
        game_state,
        visual_en: str,
        tags_en: List[str],
        **kwargs: Any,
    ):
        """Build image prompt from game state (required by BasePromptBuilder)."""
        # Get characters from kwargs or build from game_state
        characters = kwargs.get("characters", [])
        
        return self.build_prompt(
            visual_description=visual_en,
            tags=tags_en,
            characters=characters,
            width=kwargs.get("width", 896),
            height=kwargs.get("height", 896),
        )
    
    def _parse_loras_from_prompt(self, prompt: str) -> List[Dict[str, Any]]:
        """Extract LoRA definitions from prompt string."""
        import re
        loras = []
        pattern = r'<lora:([^:]+):([\d.]+)>'
        matches = re.findall(pattern, prompt)
        for name, weight in matches:
            loras.append({"name": name, "weight": float(weight)})
        return loras


class NPCBuilder(BasePromptBuilder):
    """Builder for generic/NPC characters.
    
    No character-specific LoRAs, uses generic high-quality prompts.
    """
    
    def build_prompt(
        self,
        visual_description: str,
        tags: List[str],
        scene_analysis: Optional[SceneAnalysis] = None,
        npc_type: str = "female_student",  # Generic type hint
        **kwargs: Any,
    ) -> ImagePrompt:
        """Build NPC prompt.
        
        Args:
            visual_description: Scene description
            tags: SD tags
            scene_analysis: Scene analysis
            npc_type: Type of NPC (librarian, student, etc.)
            
        Returns:
            Image prompt
        """
        npc_config = self.base_prompts["NPC_BASE"]
        
        parts = [
            "masterpiece, best quality, highres,",
            npc_config["trigger"],
            npc_config["base"],
        ]
        
        # Add NPC type hint
        if npc_type:
            parts.append(f"{npc_type},")
        
        # Add visual description
        parts.append(visual_description + ",")
        
        # Add tags
        cleaned_tags = self._sanitize_tags(tags)
        if cleaned_tags:
            parts.append(", ".join(cleaned_tags) + ",")
        
        # Quality enhancers
        parts.extend([
            "detailed face, detailed eyes,",
            "natural lighting,",
        ])
        
        positive = " ".join(parts)
        
        # Apply composition
        if scene_analysis:
            positive = self._apply_composition(positive, scene_analysis.composition_type)
        
        # No character LoRA, only style
        lora_stack = self.style_loras.copy()
        
        return ImagePrompt(
            positive=positive,
            negative=NEGATIVE_PROMPTS["standard"],
            lora_stack=lora_stack,
            width=kwargs.get("width", 896),
            height=kwargs.get("height", 896),
        )

    def build(
        self,
        game_state,
        visual_en: str,
        tags_en: List[str],
        **kwargs: Any,
    ):
        """Build image prompt from game state (required by BasePromptBuilder)."""
        return self.build_prompt(
            visual_description=visual_en,
            tags=tags_en,
            npc_type=kwargs.get("npc_type", "female_student"),
            width=kwargs.get("width", 896),
            height=kwargs.get("height", 896),
        )


class PromptBuilderFactory:
    """Legacy shim; real factory lives in builders.factory."""
    pass
