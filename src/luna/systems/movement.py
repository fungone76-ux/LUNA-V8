"""Movement System - Player navigation and location transitions.

V4 Refactor: Extracted from engine.py for cleaner architecture.
Handles:
- Movement intent detection from user input
- Location resolution and validation  
- Transition message generation
- Integration with LocationManager
- Post-movement: solo mode image generation
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import re
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

from luna.systems.location import LocationManager
from luna.core.models import GameState, WorldDefinition


@dataclass
class MovementResult:
    """Result of movement processing."""
    success: bool
    target_location_id: Optional[str] = None
    transition_text: str = ""
    error_message: str = ""
    companion_left_behind: bool = False
    companion_message: str = ""


class MovementHandler:
    """Handles player movement detection and execution."""
    
    # Movement keywords (Italian)
    MOVEMENT_PATTERNS = [
        # Prima persona
        "vado ", "vai ", "andiamo ", "muoviti ", "spostati ",
        "entra ", "entriamo ", "entro ",
        "uscire ", "uscite ", "esco ", "esci ", "usciamo ",
        "raggiungi ", "raggiungiamo ", "raggiungo ",
        "torniamo ", "torna ", "torno ",
        # Infinito ("devo andare", "posso entrare")
        "andare ", "andare a ", "andare in ", "andare da ",
        "entrare ", "entrare in ", "entrare a ",
        "uscire ", "uscire da ", "uscire per ",
        "raggiungere ", "raggiungere il ", "raggiungere la ",
        "tornare ", "tornare a ", "tornare in ",
        "andrei ", "entrerei ", "uscirei ",
    ]
    
    # Prepositions to strip
    PREPOSITIONS = ["a ", "in ", "da ", "verso ", "per ", "nel ", "nella ", "nello ", "nei ", "nelle ", "negli ", "al ", "alla ", "allo ", "ai ", "alle ", "agli ", "dal ", "dalla ", "dallo ", "dai ", "dalle ", "dagli ", "all'", "all ", "dall'", "dall "]
    
    def __init__(
        self,
        world: WorldDefinition,
        location_manager: LocationManager,
        game_state: GameState,
    ):
        """Initialize movement handler.
        
        Args:
            world: World definition with locations
            location_manager: Location manager instance
            game_state: Current game state
        """
        self.world = world
        self.location_manager = location_manager
        self.game_state = game_state
    
    # V4.2: Question patterns - if detected, treat as question not movement
    QUESTION_PATTERNS = [
        r'^posso\s',           # "Posso andare..."
        r'^possiamo\s',        # "Possiamo entrare..."
        r'^posso\?',           # "Posso?"
        r'\?$',                # Ends with ?
        r'^mi\s+(?:consenti|lasci|permetti)',  # "Mi consenti di..."
        r'^(?:si|sì)\s+(?:posso|possiamo)',   # "Sì posso..."
    ]
    
    # V4.4: Meta/subject indicators - words that suggest talking ABOUT something, not moving TO it
    META_SUBJECTS = [
        "matematica", "storia", "scienze", "fisica", "chimica", 
        "letteratura", "filosofia", "arte", "musica", "sport",
        "argomento", "tema", "discussione", "conversazione",
        "inglese", "francese", "spagnolo", "tedesco",
        "geografia", "biologia", "informatica", "tecnologia",
    ]
    
    def detect_movement_intent(self, user_input: str) -> bool:
        """Detect if user input contains movement intent.
        
        Uses word boundary matching to avoid false positives like:
        - "riesco" containing "esco"
        - "facciamo" containing "ciamo" (similar to "andiamo")
        
        V4.2: Questions ("Posso entrare?") are NOT treated as movement.
        User must explicitly state the action ("Entro in bagno").
        
        Args:
            user_input: Player's input text
            
        Returns:
            True if movement intent detected
        """
        import re
        text_lower = user_input.lower().strip()
        logger.debug(f"[Movement] detect_movement_intent: input='{user_input}'")
        
        # V4.2: Check if it's a question - skip movement detection
        for pattern in self.QUESTION_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                logger.debug(f"[Movement] Question detected, not treating as movement: '{user_input}'")
                return False
        
        for pattern in self.MOVEMENT_PATTERNS:
            # Use word boundary to avoid partial matches
            # Pattern must be preceded by start of string or non-word char
            # and followed by end of string or non-word char
            pattern_clean = pattern.strip()
            # Create regex with word boundary
            regex = r'(?:^|\s)' + re.escape(pattern_clean) + r'(?:\s|$|[^a-z])'
            if re.search(regex, text_lower):
                logger.debug(f"[Movement] Matched pattern: '{pattern_clean}'")
                return True
        
        logger.debug(f"[Movement] No movement pattern matched")
        return False
    
    def extract_target_name(self, user_input: str) -> Optional[str]:
        """Extract target location name from user input.
        
        Args:
            user_input: Player's input text
            
        Returns:
            Target location name or None
        """
        import re
        text_lower = user_input.lower()
        
        # Fast path: explicit movement with preposition (prefer the LAST mention).
        explicit_patterns = [
            r"\b(?:vado|vai|andiamo|entro|entra|entriamo|esco|esci|usciamo|torno|torna|torniamo|raggiungo|raggiungi|raggiungiamo)\s+(?:a|in|da|verso|nel|nella|nello|nei|nelle|negli|al|alla|allo|ai|alle|agli|all'|all )\s+([^\.,;!?]+)",
            r"\b(?:andare|entrare|uscire|tornare|raggiungere)\s+(?:a|in|da|verso|nel|nella|nello|nei|nelle|negli|al|alla|allo|ai|alle|agli|all'|all )\s+([^\.,;!?]+)",
        ]
        for patt in explicit_patterns:
            matches = list(re.finditer(patt, text_lower, re.IGNORECASE))
            if matches:
                candidate = matches[-1].group(1).strip()
                if candidate:
                    target = candidate
                    # Reuse stop/meta cleanup logic below.
                    break
        else:
            target = None

        # Fallback: find movement keyword position (with word boundary), preferring the LAST match
        keyword_pos = -1
        found_keyword = ""
        if target is None:
            for pattern in self.MOVEMENT_PATTERNS:
                pattern_clean = pattern.strip()
                regex = r'(?:^|\s)' + re.escape(pattern_clean) + r'(?:\s|$|[^a-z])'
                for match in re.finditer(regex, text_lower):
                    pos = match.start()
                    if pos >= keyword_pos:
                        keyword_pos = pos
                        found_keyword = pattern
        
            if keyword_pos == -1:
                return None
        
            # Extract everything after the keyword
            after_keyword = user_input[keyword_pos + len(found_keyword):].strip()
        
            # Remove prepositions
            target_lower = after_keyword.lower()
            for prep in self.PREPOSITIONS:
                if target_lower.startswith(prep):
                    after_keyword = after_keyword[len(prep):].strip()
                    break
        
            target = after_keyword

        # Extract just the first part (location name)
        # Stop at punctuation or common stop words
        # V4.2: Added "così", "cosi", apostrophe and other conversational words
        stop_words = [
            " per ", " con ", " da ", " che ", " e ", " dove ", "?", ".", ",", ";",
            " così ", " cosi ", " cos'", " cosi'",  # così/cosi variants
            " per ", " posso ", " cosa ", " quando ", " perché ", " perche ",
            "?", "!", ".", ",", ";", ":",  # punctuation
        ]
        for stop in stop_words:
            pos = target.lower().find(stop)
            if pos != -1:
                target = target[:pos].strip()
        
        # V4.4: Check if target is a meta-subject (e.g., "matematica" as subject, not location)
        target_first_word = target.split()[0].lower() if target else ""
        if target_first_word in self.META_SUBJECTS:
            logger.warning(f"[Movement] Target '{target}' is a meta-subject (not a location), skipping")
            return None
        
        # V4.2: If target has multiple words and first word alone matches a location, use that
        # (e.g., "classe così studio" -> try "classe" if "classe così studio" doesn't exist)
        if " " in target:
            first_word = target.split()[0]
            # Check if first word alone exists as location
            if self._location_exists(first_word):
                logger.debug(f"[Movement] Using first word only: '{first_word}' (from '{target}')")
                return first_word
        
        return target if target else None
    
    def _location_exists(self, name: str) -> bool:
        """Quick check if a location name exists."""
        name_lower = name.lower()
        # Check direct ID match
        if name_lower in [loc.lower() for loc in self.world.locations.keys()]:
            return True
        # Check name/aliases
        for loc in self.world.locations.values():
            if name_lower == loc.name.lower():
                return True
            if hasattr(loc, 'aliases') and loc.aliases:
                if name_lower in [a.lower() for a in loc.aliases]:
                    return True
        return False
    
    def resolve_location(self, target_name: str) -> Optional[str]:
        """Resolve target name to location ID.
        
        Args:
            target_name: Target location name from user input
            
        Returns:
            Location ID or None if not found
        """
        if not target_name:
            return None
        
        target_lower = target_name.lower().strip()
        
        # V4.4 FIX: Prioritize player_home for "casa" variations
        # This prevents "casa" matching "Casa di Maria" before "Casa Tua"
        home_aliases = ['casa', 'a casa', 'home', 'casa mia', 'a casa mia', 'torno a casa', 'a casa mia']
        if target_lower in home_aliases:
            if 'player_home' in self.world.locations:
                logger.debug(f"[Movement] Target '{target_name}' -> prioritized player_home")
                return 'player_home'
        
        # V4.1: Skip if target is the active companion's name
        # (e.g., "entra Luna" should not move to "school_office_luna")
        active_companion = self.game_state.active_companion
        if active_companion and target_lower == active_companion.lower():
            logger.debug(f"[Movement] Target '{target_name}' is active companion, not a location")
            return None
        
        # Also skip if target matches any companion name (not just active)
        for companion_name in self.world.companions.keys():
            if target_lower == companion_name.lower():
                logger.warning(f"[Movement] Target '{target_name}' matches companion '{companion_name}', skipping")
                return None
        
        # Check all locations
        for loc_id, location in self.world.locations.items():
            # Match against name
            if location.name.lower() == target_lower:
                return loc_id
            
            # Match against aliases
            if hasattr(location, 'aliases') and location.aliases:
                for alias in location.aliases:
                    if alias.lower() == target_lower:
                        return loc_id
            
            # Partial match on name (for longer names)
            if len(target_lower) >= 4 and target_lower in location.name.lower():
                return loc_id
        
        return None
    
    async def handle_movement(self, user_input: str) -> Optional[MovementResult]:
        """Process movement intent and execute if valid.
        
        Args:
            user_input: Player's input text
            
        Returns:
            Movement result or None if no movement detected
        """
        if not self.detect_movement_intent(user_input):
            return None
        
        logger.debug(f"[Movement] Detected intent in: '{user_input}'")
        
        # Extract target
        target_name = self.extract_target_name(user_input)
        logger.debug(f"[Movement] Extracted target: '{target_name}'")
        
        if not target_name:
            logger.debug(f"[Movement] No target extracted")
            return None
        
        # Resolve to location ID
        target_id = self.resolve_location(target_name)
        
        if not target_id:
            # V4.4 FIX: If target is not a valid location, treat as NOT movement
            # This handles cases like "torniamo alla matematica" where "matematica" 
            # refers to a subject, not a physical location
            logger.debug(f"[Movement] Target '{target_name}' is not a valid location, treating as conversation")
            return None
        
        logger.debug(f"[Movement] Resolved to location ID: {target_id}")
        
        # V4.5: Check if already at destination
        if target_id == self.game_state.current_location:
            logger.debug(f"[Movement] Already at {target_id}, treating as conversation")
            return None
        
        # Execute movement via LocationManager
        logger.debug(f"[Movement] Calling LocationManager.move_to({target_id})")
        movement_response = self.location_manager.move_to(target_id)
        logger.debug(f"[Movement] LocationManager response: success={movement_response.success}")
        
        if not movement_response.success:
            return MovementResult(
                success=False,
                error_message=movement_response.block_reason or "Non puoi andare lì."
            )
        
        # V4: Always leave companion behind when moving
        # Get current companion name
        current_companion = self.game_state.active_companion
        companion_left = current_companion and current_companion != "_solo_"
        
        # Build result - companion always stays behind
        result = MovementResult(
            success=True,
            target_location_id=target_id,
            transition_text=movement_response.transition_text or "",
            companion_left_behind=companion_left,  # V4: Always true if has companion
            companion_message=f"{current_companion} rimane indietro." if companion_left else "",
        )
        
        logger.debug(f"[Movement] Success! New location: {target_id}")
        if result.companion_left_behind:
            logger.debug(f"[Movement] Companion stayed behind: {result.companion_message}")
        
        return result
    
    def get_visible_exits_text(self) -> str:
        """Get text description of visible exits.
        
        Returns:
            Formatted exit list
        """
        visible = self.location_manager.get_visible_locations()
        if not visible:
            return "Non ci sono uscite visibili."
        
        exits = []
        for loc_id in visible:
            loc = self.location_manager.get_location(loc_id)
            if loc:
                exits.append(loc.name)
        
        return f"Puoi andare verso: {', '.join(exits)}"
    
    def get_current_location_description(self) -> str:
        """Get current location description for UI.
        
        Returns:
            Location description text
        """
        current = self.location_manager.get_current_location()
        instance = self.location_manager.get_current_instance()
        
        if not current or not instance:
            return "Location sconosciuta"
        
        desc = instance.get_effective_description(
            current, 
            self.game_state.time_of_day
        )
        
        return desc
    
    def get_solo_mode_image_params(self, location_id: str) -> Optional[Dict[str, Any]]:
        """Get image generation parameters for solo mode (empty location).
        
        V4.1: When player is alone in a location, generate image of empty location.
        
        Args:
            location_id: Current location ID
            
        Returns:
            Dict with visual_en, tags, location_visual_style or None
        """
        loc_def = self.world.locations.get(location_id)
        if not loc_def:
            return None
        
        # Get visual style for the location
        visual_style = loc_def.visual_style if loc_def.visual_style else loc_def.name
        
        # Build visual description (English for SD)
        visual_en = f"Empty {loc_def.name.lower()}, no people, atmospheric scene"
        if loc_def.lighting:
            visual_en += f", {loc_def.lighting}"
        
        # Tags for SD
        tags = ["empty", "no_humans", "scenery"]
        if hasattr(loc_def, 'tags') and loc_def.tags:
            tags.extend(loc_def.tags)
        
        return {
            "visual_en": visual_en,
            "tags": tags,
            "location_visual_style": visual_style,
            "location_name": loc_def.name,
        }
