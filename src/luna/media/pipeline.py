"""Media generation pipeline.

Handles async generation of images, audio, and video.
All operations are non-blocking - content appears when ready.
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass

from luna.core.config import get_settings
from luna.core.models import OutfitState


@dataclass
class MediaResult:
    """Result of media generation."""
    success: bool
    image_path: Optional[str] = None
    audio_path: Optional[str] = None
    video_path: Optional[str] = None
    error: Optional[str] = None
    sd_prompt: Optional[str] = None  # V4.6: The actual positive prompt used


class MediaPipeline:
    """Async media generation pipeline.
    
    Generates content asynchronously:
    - Text → displayed immediately
    - Image → generated in background, displayed when ready
    - Audio → optional, can be muted
    - Video → optional, requires RunPod
    """
    
    def __init__(self, lora_mapping: Optional[Any] = None) -> None:
        """Initialize media pipeline.
        
        Args:
            lora_mapping: Optional LoraMapping for dynamic LoRA selection
        """
        self.settings = get_settings()
        
        # Clients (lazy init)
        self._image_client: Optional[Any] = None
        self._audio_client: Optional[Any] = None
        self._video_client: Optional[Any] = None
        
        # Audio settings (like v3)
        self.audio_enabled = True
        self.audio_muted = False
        
        # V4.6: LoRA mapping for dynamic LoRA selection
        self._lora_mapping = lora_mapping
        
        # Callbacks for async updates
        self._on_image_ready: Optional[Callable[[str], None]] = None
        self._on_audio_ready: Optional[Callable[[str], None]] = None
    
    def set_callbacks(
        self,
        on_image_ready: Optional[Callable[[str], None]] = None,
        on_audio_ready: Optional[Callable[[str], None]] = None,
    ) -> None:
        """Set callbacks for async media completion.
        
        Args:
            on_image_ready: Called when image is generated
            on_audio_ready: Called when audio is generated
        """
        self._on_image_ready = on_image_ready
        self._on_audio_ready = on_audio_ready
    
    async def generate_all(
        self,
        text: str,
        visual_en: str,
        tags: List[str],
        companion_name: str = "companion",
        outfit: Optional[OutfitState] = None,
        generate_video: bool = False,
        video_action: str = "posing",
        base_prompt: Optional[str] = None,
        secondary_characters: Optional[List[Dict[str, str]]] = None,
        location_id: Optional[str] = None,
        location_description: Optional[str] = None,
        location_visual_style: Optional[str] = None,
        composition: Optional[str] = None,
        aspect_ratio: str = "square",
        dop_reasoning: str = "",
        sd_positive: Optional[str] = None,
        sd_negative: Optional[str] = None,
        extra_loras: Optional[List[str]] = None,
    ) -> MediaResult:
        """Generate all media types asynchronously.
        
        Args:
            text: Narrative text (for audio)
            visual_en: Visual description
            tags: SD tags
            companion_name: For character-specific settings
            generate_video: Whether to generate video
            video_action: Action for video generation
            base_prompt: Character base prompt from world YAML (SACRED for visual consistency)
            secondary_characters: Optional list of secondary characters with 'name' and 'base_prompt'
            location_id: Current location ID (e.g., 'luna_home', 'school_classroom')
            location_description: Visual description of location for image generation
            location_visual_style: V4: Visual style of location (used when solo)
            
        Returns:
            Media result (paths may be None if async)
        """
        result = MediaResult(success=True)
        
        # DEBUG MODE: Skip image/video generation
        if self.settings.debug_no_media:
            logger.warning("[MediaPipeline] DEBUG MODE: Skipping image/video generation")
            # Still generate audio if enabled (doesn't require ComfyUI)
            if self.audio_enabled and not self.audio_muted:
                try:
                    audio_path = await self._generate_audio_async(text, companion_name)
                    result.audio_path = audio_path
                except Exception as e:
                    logger.warning(f"[MediaPipeline] Audio generation failed: {e}")
            return result
        
        # Start all generations concurrently
        tasks = []
        
        # Image (always, unless in debug mode checked above)
        # V4.0: Inject location description into visual_en if provided
        visual_en_with_location = self._inject_location_into_visual_en(
            visual_en, location_id, location_description
        )
        
        image_task = asyncio.create_task(
            self._generate_image_async(
                visual_en_with_location, tags, companion_name, outfit, base_prompt,
                secondary_characters, location_visual_style, composition, aspect_ratio, dop_reasoning,
                sd_positive, sd_negative, extra_loras
            )
        )
        tasks.append(("image", image_task))
        
        # Audio (if enabled)
        if self.audio_enabled and not self.audio_muted:
            audio_task = asyncio.create_task(
                self._generate_audio_async(text, companion_name)
            )
            tasks.append(("audio", audio_task))
        
        # Video (optional, RunPod only)
        if generate_video:
            if self.settings.video_available:
                # Video needs image first - wait for it
                video_task = asyncio.create_task(
                    self._generate_video_after_image(image_task, video_action)
                )
                tasks.append(("video", video_task))
            else:
                logger.warning("[MediaPipeline] Video generation skipped: requires RunPod mode")
        
        # Wait for all tasks
        for media_type, task in tasks:
            try:
                task_result = await task
                if media_type == "image":
                    # V4.6: task_result is now (path, prompt) tuple
                    if isinstance(task_result, tuple):
                        result.image_path = task_result[0]
                        result.sd_prompt = task_result[1]
                    else:
                        # Fallback for backward compatibility
                        result.image_path = task_result
                elif media_type == "audio":
                    result.audio_path = task_result
                elif media_type == "video":
                    result.video_path = task_result
            except Exception as e:
                logger.warning(f"[MediaPipeline] {media_type} generation failed: {e}")
                result.success = False
                result.error = str(e)
        
        return result
    
    async def generate_multi_npc_sequence(
        self,
        sequence_turns: List[Dict[str, Any]],
        on_image_ready: Optional[Callable[[int, str], None]] = None,
    ) -> List[Optional[str]]:
        """Generate image sequence for Multi-NPC dialogue.
        
        Generates images sequentially (not concurrently) for each turn
        in a Multi-NPC dialogue sequence. Each image has different focus
        based on who is speaking.
        
        Args:
            sequence_turns: List of turn dicts with:
                - visual_en: Visual description
                - tags: SD tags
                - characters: List of character dicts for MultiCharacterBuilder
                - companion_name: Primary companion name
            on_image_ready: Callback(turn_index, image_path) when each image is ready
            
        Returns:
            List of image paths (one per turn)
        """
        # DEBUG MODE: Skip image generation
        if self.settings.debug_no_media:
            logger.warning("[MediaPipeline] DEBUG MODE: Skipping Multi-NPC image generation")
            return [None] * len(sequence_turns)
        
        image_paths = []
        
        logger.debug(f"[MediaPipeline] Generating {len(sequence_turns)} images for Multi-NPC sequence...")
        
        for idx, turn in enumerate(sequence_turns):
            logger.debug(f"[MediaPipeline] Generating image {idx + 1}/{len(sequence_turns)}...")
            
            try:
                # Generate single image for this turn
                image_result = await self._generate_image_async(
                    visual_en=turn.get("visual_en", ""),
                    tags=turn.get("tags", []),
                    companion_name=turn.get("companion_name", "unknown"),
                    outfit=turn.get("outfit"),
                    base_prompt=turn.get("base_prompt"),
                    secondary_characters=turn.get("characters"),  # For MultiCharacterBuilder
                )
                path = image_result[0] if isinstance(image_result, tuple) else image_result
                
                image_paths.append(path)
                
                # Notify callback if provided
                if on_image_ready and path:
                    on_image_ready(idx, path)
                
            except Exception as e:
                logger.warning(f"[MediaPipeline] Image {idx + 1} generation failed: {e}")
                image_paths.append(None)
        
        logger.debug(f"[MediaPipeline] Multi-NPC sequence complete: {len([p for p in image_paths if p])} images generated")
        return image_paths
    
    def toggle_audio(self) -> bool:
        """Toggle audio mute state.
        
        Returns:
            New mute state (True = muted)
        """
        self.audio_muted = not self.audio_muted
        return self.audio_muted
    
    def set_audio_enabled(self, enabled: bool) -> None:
        """Enable/disable audio completely.
        
        Args:
            enabled: True to enable audio
        """
        self.audio_enabled = enabled
    
    # ========================================================================
    # Private async methods
    # ========================================================================
    
    def _inject_location_into_visual_en(
        self,
        visual_en: str,
        location_id: Optional[str],
        location_description: Optional[str],
    ) -> str:
        """Inject location description into visual_en to ensure correct background.
        
        V4.0 FIX: The LLM often ignores location instructions in the system prompt.
        This forces the location into the visual description.
        
        Args:
            visual_en: Original visual description from LLM
            location_id: Location ID (e.g., 'luna_home')
            location_description: Location visual_style (English) for SD prompt
            
        Returns:
            Modified visual_en with location enforced
        """
        if not location_id:
            return visual_en
        
        # V4.4 FIX: Always inject correct location for player_home (prevent office/school confusion)
        # When at player_home, force bedroom/apartment context regardless of LLM output
        if location_id == 'player_home':
            # Force bedroom context, remove conflicting indicators
            import re
            # Remove conflicting location words
            visual_en = re.sub(r'\b(office|school|classroom|gym|library|corridor)\b', '', visual_en, flags=re.IGNORECASE)
            # Inject bedroom
            if location_description:
                visual_en = f"{location_description}, {visual_en}"
                logger.debug(f"[MediaPipeline] FORCED bedroom location for player_home")
            return visual_en
        
        # Skip if visual_en already contains clear location indicators (for other locations)
        visual_lower = visual_en.lower()
        location_indicators = [
            'classroom', 'bathroom', 'bedroom', 'kitchen', 'office',
            'gym', 'library', 'corridor', 'home', 'house', 'school',
            'room', 'apartment', 'studio', 'background', 'living room',
            'dining room', 'hallway', 'entrance', 'garden', 'park',
            'street', 'shop', 'store', 'restaurant', 'cafe', 'bar',
            'hospital', 'clinic', 'police', 'station', 'bus', 'train',
            'car', 'vehicle', 'beach', 'pool', 'mountain', 'forest',
            'city', 'town', 'village', 'building', 'interior', 'exterior',
        ]
        
        for indicator in location_indicators:
            if indicator in visual_lower:
                # Location already mentioned, trust the LLM
                logger.debug(f"[MediaPipeline] Location already in visual_en: '{indicator}'")
                return visual_en
        
        # No location found in visual_en, inject it
        if location_description:
            # Use provided visual_style (English)
            location_text = location_description
        else:
            # Generate from location_id
            location_text = location_id.replace('_', ' ')
        
        # Inject location at the end of visual_en
        # Format: "...existing description..., in [location]"
        injected = f"{visual_en.rstrip('. ')}, in {location_text}"
        logger.debug(f"[MediaPipeline] INJECTED LOCATION: '{location_text}'")
        logger.debug(f"[MediaPipeline]   Original: {visual_en[:60]}...")
        logger.debug(f"[MediaPipeline]   Modified: {injected[:60]}...")
        
        logger.debug(f"[MediaPipeline] Location injection: '{location_id}' -> added to visual_en")
        return injected
    
    def _detect_generic_npc(self, visual_en: str, companion_name: str, base_prompt: str) -> bool:
        """Detect if the visual description is for a generic NPC, not the main character.
        
        Checks if the description mentions physical traits different from the companion's base prompt.
        
        Args:
            visual_en: Visual description from LLM
            companion_name: Name of active companion
            base_prompt: Base prompt of active companion (contains their defining traits)
            
        Returns:
            True if this appears to be a generic NPC, not the main companion
        """
        if not visual_en or not base_prompt:
            return False
        
        # V3.1 FIX: If base_prompt contains weighted tags (e.g., "(tag:1.1)"), 
        # it's a custom-built prompt for a specific temporary NPC - DON'T override it with generic NPC_BASE
        # Pattern matches (anything:1.x) where x can be a decimal
        if re.search(r'\([^:]+:\d+\.?\d*\)', base_prompt):
            logger.debug(f"[MediaPipeline] Custom weighted base_prompt detected, not treating as generic NPC")
            return False
        
        visual_lower = visual_en.lower()
        base_lower = base_prompt.lower()
        
        # Common hair colors to check
        hair_colors = {
            'red hair': ['brown hair', 'blonde hair', 'black hair', 'white hair', 'grey hair', 'silver hair'],
            'blonde hair': ['brown hair', 'red hair', 'black hair', 'white hair', 'grey hair'],
            'black hair': ['brown hair', 'blonde hair', 'red hair', 'white hair'],
            'white hair': ['brown hair', 'blonde hair', 'red hair', 'black hair'],
            'grey hair': ['brown hair', 'blonde hair', 'red hair', 'black hair'],
            'silver hair': ['brown hair', 'blonde hair', 'red hair', 'black hair'],
            'short hair': ['long hair'],
            'long hair': ['short hair'],
        }
        
        # Check if visual_en mentions hair color that conflicts with companion's base prompt
        for color_key, conflicting_colors in hair_colors.items():
            if color_key in visual_lower:
                # Check if companion's base prompt has a different hair color
                for conflicting in conflicting_colors:
                    if conflicting in base_lower:
                        logger.debug(f"[MediaPipeline] Detected NPC with {color_key} (companion has {conflicting})")
                        return True
        
        # Check for generic NPC indicators
        generic_indicators = [
            'secretary', 'librarian', 'nurse', 'teacher', 'student', 'shopkeeper',
            'receptionist', 'bartender', 'waitress', 'cashier', 'passerby',
            'random woman', 'unknown woman', 'young woman', 'mature woman',
            'redhead', 'brunette', 'blonde woman',
        ]
        
        for indicator in generic_indicators:
            if indicator in visual_lower:
                # V4.4 FIX: NPCs created from templates (name starts with 'npc_') should NEVER be treated as generic
                # They have specific base_prompts with visual traits defined in npc_templates.yaml
                if companion_name.lower().startswith("npc_"):
                    logger.debug(f"[MediaPipeline] NPC template detected ({companion_name}), not treating as generic despite indicator: {indicator}")
                    return False
                # Check if this is NOT the companion's name
                if companion_name.lower() not in visual_lower:
                    logger.debug(f"[MediaPipeline] Detected generic NPC: {indicator}")
                    return True
        
        return False
    
    async def _generate_image_async(
        self,
        visual_en: str,
        tags: List[str],
        companion_name: str,
        outfit: Optional[OutfitState] = None,
        base_prompt: Optional[str] = None,
        secondary_characters: Optional[List[Dict[str, str]]] = None,
        location_visual_style: Optional[str] = None,
        composition_override: Optional[str] = None,
        aspect_ratio: str = "square",
        dop_reasoning: str = "",
        sd_positive: Optional[str] = None,
        sd_negative: Optional[str] = None,
        extra_loras: Optional[List[str]] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Generate image asynchronously.
        
        Args:
            visual_en: Visual description
            tags: SD tags
            companion_name: Character name
            outfit: Character outfit state
            base_prompt: Character base prompt from world YAML (SACRED)
            secondary_characters: Optional list of secondary characters for multi-character scenes
            location_visual_style: V4: Visual style of location (used when solo)
            aspect_ratio: Director of Photography choice (landscape, portrait, square)
            dop_reasoning: Cinematographic reasoning for the aspect ratio choice
            
        Returns:
            Tuple of (path to generated image or None, positive prompt used or None)
        """
        composition_value = composition_override or "medium_shot"
        if self.settings.mock_media:
            # Build prompt anyway for display
            from luna.media.builders import ImagePromptBuilder
            prompt_builder = ImagePromptBuilder()
            
            mock_prompt = prompt_builder.build(
                visual_description=visual_en,
                tags=tags,
                composition=composition_value,
                character_name=companion_name,
                outfit=outfit,
                base_prompt=base_prompt,
                secondary_characters=secondary_characters,
                location_visual_style=location_visual_style,
                aspect_ratio=aspect_ratio,
                dop_reasoning=dop_reasoning,
                lora_mapping=self._lora_mapping,  # V4.6: Dynamic LoRA selection
            )
            return ("storage/images/mock_image.png", mock_prompt.positive if hasattr(mock_prompt, 'positive') else str(mock_prompt))
        
        # Initialize client if needed
        if self._image_client is None:
            self._image_client = self._init_image_client()
        
        # If no client available, return placeholder
        if self._image_client is None:
            logger.warning("[MediaPipeline] No image client available, skipping generation")
            return (None, None)
        
        # v6: Use pre-built prompt from VisualDirector if provided
        # This bypasses generic NPC detection entirely
        if sd_positive:
            from luna.media.builders import ImagePrompt
            neg = sd_negative or (
                "(deformed, distorted, disfigured:1.3), bad anatomy, wrong anatomy, "
                "extra limb, missing limb, (mutated hands and fingers:1.4), "
                "ugly, blurry, text, watermark, score_1, score_2, score_3, score_4, "
                "(worst quality, low quality:1.4), monochrome, greyscale"
            )
            w = 896 if aspect_ratio == "portrait" else (1152 if aspect_ratio == "landscape" else 1024)
            h = 1152 if aspect_ratio == "portrait" else (896 if aspect_ratio == "landscape" else 1024)
            prompt = ImagePrompt(positive=sd_positive, negative=neg, width=w, height=h)
            try:
                path = await self._image_client.generate(
                    prompt=prompt, character_name=companion_name, extra_loras=extra_loras
                )
                if path and self._on_image_ready:
                    self._on_image_ready(str(path))
                return (str(path) if path else None, sd_positive)
            except Exception as e:
                logger.warning(f"[MediaPipeline] Pre-built prompt failed: {e}")
                return (None, None)

        # v6: VisualDirector handles prompt building — no NPC detection needed
        # base_prompt from CompanionDefinition is always correct
        effective_base_prompt = base_prompt

        # Build prompt using ImagePromptBuilder
        try:
            from luna.media.builders import ImagePromptBuilder
            
            prompt_builder = ImagePromptBuilder()
            
            # V4.1 SOLO MODE: If solo, use location_visual_style as the scene description
            # (showing empty location without characters)
            effective_visual = visual_en
            if companion_name == "_solo_" and location_visual_style:
                effective_visual = location_visual_style
                logger.debug(f"[MediaPipeline] SOLO MODE: Using location visual style")
            
            # V4.6: Detect if LLM already specified composition in visual_en
            prompt = prompt_builder.build(
                visual_description=effective_visual,
                tags=tags,
                composition=composition_value,
                character_name=companion_name,
                outfit=outfit,
                base_prompt=effective_base_prompt,
                secondary_characters=secondary_characters,  # Multi-character support
                location_visual_style=location_visual_style,  # V4: Pass for solo mode
                aspect_ratio=aspect_ratio,  # DoP aspect ratio decision
                dop_reasoning=dop_reasoning,  # DoP reasoning
                lora_mapping=self._lora_mapping,  # V4.6: Dynamic LoRA selection
            )
            
            # Generate image
            path = await self._image_client.generate(
                prompt=prompt,
                character_name=companion_name,
            )
            
            # Notify callback
            if path and self._on_image_ready:
                self._on_image_ready(str(path))
            
            return (str(path) if path else None, prompt.positive if hasattr(prompt, 'positive') else str(prompt))
            
        except Exception as e:
            logger.warning(f"[MediaPipeline] Image generation failed: {e}")
            return (None, None)
    
    async def _generate_audio_async(
        self,
        text: str,
        companion_name: str,
    ) -> Optional[str]:
        """Generate audio asynchronously.
        
        Args:
            text: Text to speak
            companion_name: Character name (not used - single voice)
            
        Returns:
            Path to generated audio or None
        """
        if not self.audio_enabled or self.audio_muted:
            return None
        
        if self.settings.mock_media:
            return "storage/audio/mock_audio.mp3"
        
        # Initialize client if needed
        if self._audio_client is None:
            self._audio_client = self._init_audio_client()
        
        if self._audio_client is None:
            logger.debug("[MediaPipeline] Audio client not available")
            return None
        
        try:
            # Use a hash-based filename to avoid permission errors when the
            # previous audio file is still locked by the audio player.
            path = f"storage/audio/narration_{abs(hash(text)) % 100000}.mp3"

            # Generate audio
            audio_path = self._audio_client.synthesize(text, path)
            
            if audio_path and self._on_audio_ready:
                self._on_audio_ready(audio_path)
            
            return audio_path
        except Exception as e:
            logger.warning(f"[MediaPipeline] Audio generation failed: {e}")
            return None
    
    async def _generate_video_after_image(
        self,
        image_task: asyncio.Task,
        action: str,
    ) -> Optional[str]:
        """Generate video after image is ready.
        
        Args:
            image_task: Task that returns image path
            action: Action description for video
            
        Returns:
            Path to generated video or None
        """
        # Wait for image
        image_path = await image_task
        if not image_path:
            return None
        
        if self.settings.mock_media:
            return "storage/videos/mock_video.mp4"
        
        # Initialize client if needed
        if self._video_client is None:
            self._video_client = self._init_video_client()
        
        # Generate (placeholder)
        await asyncio.sleep(0.5)  # Video takes longer
        
        return f"storage/videos/{asyncio.get_event_loop().time()}.mp4"
    
    def _init_image_client(self) -> Any:
        """Initialize image generation client based on execution mode.
        
        LOCAL mode: SD WebUI (Automatic1111)
        RUNPOD mode: ComfyUI
        """
        try:
            if self.settings.is_local:
                # Local mode: Use SD WebUI
                logger.debug("[MediaPipeline] Using SD WebUI (local mode)")
                from luna.media.sd_webui_client import SDWebUIClient
                return SDWebUIClient()
            else:
                # RunPod mode: Use ComfyUI
                logger.debug("[MediaPipeline] Using ComfyUI (RunPod mode)")
                from luna.media.comfy_client import ComfyUIClient
                return ComfyUIClient()
        except Exception as e:
            logger.warning(f"[MediaPipeline] Image client init failed: {e}")
            return None
    
    def _init_audio_client(self) -> Any:
        """Initialize audio/TTS client."""
        try:
            from luna.media.audio_client import AudioClient
            from luna.core.config import get_settings
            
            settings = get_settings()
            return AudioClient(
                credentials_path=str(settings.google_credentials_path),
                language_code="it-IT",
                voice_name="it-IT-Standard-A",
                speaking_rate=1.0,
            )
        except Exception as e:
            logger.warning(f"[MediaPipeline] Audio client init failed: {e}")
            return None
    
    def _init_video_client(self) -> Any:
        """Initialize video generation client."""
        # TODO: Import and init Wan2.1 client
        # from luna.media.video_client import VideoClient
        # return VideoClient()
        return None
