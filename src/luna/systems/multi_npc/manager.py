"""Multi-NPC Manager - Main coordinator for multi-NPC interactions.

This is the main entry point for the multi-NPC dialogue system.
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

from typing import Dict, List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from luna.core.models import WorldDefinition, TimeOfDay
    from luna.systems.personality import PersonalityEngine

from luna.systems.multi_npc.interaction_rules import (
    InteractionRuleset,
    InteractionType,
    InteractionRule,
)
from luna.systems.multi_npc.dialogue_sequence import (
    DialogueSequence,
    DialogueTurn,
    SpeakerType,
)


class MultiNPCManager:
    """Manages multi-NPC dialogue interactions.
    
    Coordinates when and how secondary NPCs intervene in conversations,
    respecting relationship dynamics and configuration settings.
    
    CRITICAL: Multi-NPC triggers are now CONSERVATIVE:
    - Player must have affinity >= 20 with secondary NPC
    - NPC relationship must be extreme (strong friends or enemies)
    - Cooldown between interventions (same NPC can't interrupt twice in a row)
    - Player must mention NPC or have strong bond
    
    Attributes:
        world: World definition for NPC data
        personality_engine: For accessing NPC relationships
        enabled: Global toggle for the system
        ruleset: Rules for determining interactions
    """
    
    # Minimum affinity player must have with secondary NPC for them to intervene
    # V3.1: Lowered from 20 to 5 to make multi-NPC interactions more frequent
    MIN_PLAYER_AFFINITY = 5
    
    # Cooldown: NPC can't intervene again for this many turns after intervening
    INTERVENTION_COOLDOWN = 3
    
    def __init__(
        self,
        world: Optional["WorldDefinition"] = None,
        personality_engine: Optional["PersonalityEngine"] = None,
        enabled: bool = True,
    ):
        """Initialize the multi-NPC manager.
        
        Args:
            world: World definition containing NPC data
            personality_engine: Personality engine for relationship data
            enabled: Global toggle for the system
        """
        self.world = world
        self.personality_engine = personality_engine
        self.enabled = enabled
        self.ruleset = InteractionRuleset()
        
        # Track interventions per turn to enforce limits
        self._intervention_counts: Dict[str, int] = {}
        
        # Track last intervention turn per NPC for cooldown
        self._last_intervention_turn: Dict[str, int] = {}
    
    def is_enabled_for_scene(
        self,
        game_state: Optional[Any] = None,
        active_npc: Optional[str] = None,
    ) -> bool:
        """Check if multi-NPC is enabled for current scene.
        
        Checks multiple levels:
        1. Global enabled flag
        2. Scene flag (disable_multi_npc)
        3. Per-NPC setting (allow_multi_npc_interrupts)
        
        Args:
            game_state: Current game state for flag checking
            active_npc: Currently active NPC name
            
        Returns:
            True if multi-NPC interactions are enabled
        """
        # Global toggle
        if not self.enabled:
            return False
        
        # Scene flag check
        if game_state and hasattr(game_state, 'flags'):
            if game_state.flags.get("disable_multi_npc", False):
                return False
        
        # Per-NPC check (case-insensitive lookup)
        if active_npc and self.world:
            npc_lower = active_npc.lower().strip()
            companion = self.world.companions.get(active_npc) or next(
                (v for k, v in self.world.companions.items() if k.lower() == npc_lower), None
            )
            if companion:
                allow = getattr(companion, 'allow_multi_npc_interrupts', True)
                if not allow:
                    return False
        
        return True
    
    def get_present_npcs(
        self,
        active_npc: str,
        game_state: Optional[Any] = None,
    ) -> List[str]:
        """Get list of NPCs present in the current scene.
        
        V4.5: Now filters by location using schedule manager.
        Only NPCs at the same location as player are considered present.
        
        Args:
            active_npc: Currently active NPC
            game_state: Current game state
            
        Returns:
            List of NPC names present at current location
        """
        if not self.world or not game_state:
            return []
        
        # Get all companions + npc_templates except active
        all_npcs = list(self.world.companions.keys()) + list(self.world.npc_templates.keys())
        active_npc_lower = active_npc.lower().strip()
        potential_npcs = [n for n in all_npcs if n.lower().strip() != active_npc_lower]
        
        # V4.5: Filter by location using schedule manager
        present = []
        player_location = game_state.current_location
        
        for npc_name in potential_npcs:
            # Get NPC definition (companions or templates)
            npc_def = self.world.companions.get(npc_name) or self.world.npc_templates.get(npc_name)
            if not npc_def:
                continue
            
            # V4.9: Check game_state first for location override (invited NPCs)
            npc_location = None
            if game_state:
                npc_location = game_state.get_npc_location(npc_name)
            
            # If no override, check schedule - first try companion's own schedule, then npc_schedules
            if not npc_location and hasattr(npc_def, 'schedule') and npc_def.schedule:
                time_of_day = game_state.time_of_day
                if isinstance(time_of_day, str):
                    from luna.core.models import TimeOfDay
                    try:
                        time_of_day = TimeOfDay(time_of_day)
                    except ValueError:
                        time_of_day = TimeOfDay.MORNING
                
                # Handle both dict (YAML) and object (parsed) schedules
                schedule = npc_def.schedule
                if isinstance(schedule, dict):
                    schedule_entry = schedule.get(time_of_day)
                    if schedule_entry:
                        # Handle both dict and object schedule entries
                        if isinstance(schedule_entry, dict):
                            npc_location = schedule_entry.get('location', '')
                        else:
                            npc_location = getattr(schedule_entry, 'location', '')
            
            # Try world.npc_schedules (for separate schedule files)
            if not npc_location and hasattr(self.world, 'npc_schedules') and npc_name in self.world.npc_schedules:
                npc_schedule = self.world.npc_schedules[npc_name]
                time_of_day = game_state.time_of_day
                if isinstance(time_of_day, str):
                    from luna.core.models import TimeOfDay
                    try:
                        time_of_day = TimeOfDay(time_of_day)
                    except ValueError:
                        time_of_day = TimeOfDay.MORNING
                
                # Handle both dict and object schedules
                # companion_schedules.yaml stores keys as lowercase ("morning", "afternoon", ...)
                # while TimeOfDay enum values are capitalized ("Morning", ...)
                if isinstance(time_of_day, str):
                    time_key = time_of_day.lower()
                else:
                    time_key = time_of_day.value.lower() if hasattr(time_of_day, 'value') else str(time_of_day).lower()

                if isinstance(npc_schedule, dict):
                    # Direct dict: {"morning": {...}, "afternoon": {...}, ...}
                    schedule_entry = npc_schedule.get(time_key)
                    if schedule_entry:
                        npc_location = schedule_entry.get('location', '') if isinstance(schedule_entry, dict) else getattr(schedule_entry, 'location', '')
                else:
                    schedule_entry = npc_schedule.schedules.get(time_of_day)
                    if schedule_entry:
                        npc_location = schedule_entry.location
            
            # H2: Check spawn_locations as fallback (with dict/object support)
            if not npc_location:
                def _get_value(obj, key, default=None):
                    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
                spawn_locs = _get_value(npc_def, 'spawn_locations', [])
                if spawn_locs:
                    if player_location in spawn_locs:
                        npc_location = player_location
                    else:
                        # Use first spawn location as NPC's default location
                        npc_location = spawn_locs[0]
            
            # NPC is present if at same location as player
            if npc_location == player_location:
                present.append(npc_name)
                logger.debug(f"[MultiNPC] {npc_name} is present at {player_location}")
        
        logger.debug(f"[MultiNPC] Present NPCs at {player_location}: {present}")
        return present
    
    def check_intervention(
        self,
        active_npc: str,
        secondary_npc: str,
    ) -> Optional[InteractionType]:
        """Check if a secondary NPC should intervene.
        
        Args:
            active_npc: NPC currently speaking
            secondary_npc: NPC that might intervene
            
        Returns:
            InteractionType or None if no intervention
        """
        if not self.personality_engine:
            return None
        
        # Get relationship from personality engine
        state = self.personality_engine._ensure_state(secondary_npc)
        links = state.npc_links.get(active_npc, {})
        rapport = links.get("rapport", 0) if isinstance(links, dict) else 0
        
        # Get current intervention count for this turn
        count = self._intervention_counts.get(secondary_npc, 0)
        
        return self.ruleset.check_interaction(rapport, count)
    
    def process_turn(
        self,
        player_input: str,
        active_npc: str,
        present_npcs: Optional[List[str]] = None,
        game_state: Optional[Any] = None,
    ) -> Optional[DialogueSequence]:
        """Process a player turn and determine if multi-NPC interaction occurs.
        
        This is the main entry point. Returns a DialogueSequence if multi-NPC
        interaction should happen, or None if standard single-NPC flow.
        
        Args:
            player_input: Player's input text
            active_npc: NPC player is addressing
            present_npcs: List of other NPCs present (auto-detected if None)
            game_state: Current game state
            
        Returns:
            DialogueSequence with interaction plan, or None
        """
        logger.debug(f"[MultiNPC DEBUG] process_turn called with player_input='{player_input[:50]}...', active_npc={active_npc}")

        # Check if enabled
        enabled = self.is_enabled_for_scene(game_state, active_npc)
        logger.debug(f"[MultiNPC DEBUG] is_enabled_for_scene returned: {enabled}")
        if not enabled:
            logger.debug("[MultiNPC DEBUG] Disabled, returning None")
            return None

        # Reset intervention counts only if this is a new game turn
        current_turn = getattr(game_state, 'turn_count', 0)
        if not hasattr(self, '_last_reset_turn') or self._last_reset_turn != current_turn:
            self._intervention_counts = {}
            self._last_reset_turn = current_turn
            logger.debug(f"[MultiNPC DEBUG] Reset intervention counts for turn {current_turn}")

        # Get present NPCs
        if present_npcs is None:
            present_npcs = self.get_present_npcs(active_npc, game_state)

        logger.debug(f"[MultiNPC DEBUG] Present NPCs found: {present_npcs}")

        if not present_npcs:
            logger.debug("[MultiNPC DEBUG] No present NPCs, skipping MultiNPC")
            return None
        
        # NOTE: Location filtering is already handled by get_present_npcs() above,
        # which uses game_state.npc_locations and ScheduleManager as sources of truth.
        # The redundant filter that was here has been removed.

        # Check which NPCs might intervene
        # ADDITIONAL CONSTRAINTS for conservative triggering:
        # 1. Player must have min affinity with secondary NPC
        # 2. Player must mention the NPC OR have high affinity
        # 3. NPC must not be on cooldown
        
        potential_candidates = []
        player_input_lower = player_input.lower()
        current_turn = getattr(game_state, 'turn_count', 0)
        player_location = getattr(game_state, 'current_location', None) if game_state else None
        active_npc_lower = (active_npc or "").lower().strip()
        
        for npc_name in present_npcs:
            if npc_name.lower().strip() == active_npc_lower:
                continue
            
            # Check cooldown
            last_turn = self._last_intervention_turn.get(npc_name, -999)
            if current_turn - last_turn < self.INTERVENTION_COOLDOWN:
                logger.debug(f"[MultiNPC] {npc_name} on cooldown ({current_turn - last_turn} turns)")
                continue
            
            # Check player affinity with this NPC
            player_affinity = 0
            if self.personality_engine and game_state:
                state = self.personality_engine._ensure_state(npc_name)
                # Get average of trust and attraction as "bond"
                player_affinity = (state.impression.trust + state.impression.attraction) / 2
            elif game_state and hasattr(game_state, 'affinity') and isinstance(game_state.affinity, dict):
                player_affinity = game_state.affinity.get(npc_name, 0)
            
            # Check if player mentioned this NPC
            is_mentioned = npc_name.lower() in player_input_lower
            
            # DEBUG: Log mention check
            if is_mentioned:
                logger.debug(f"[MultiNPC DEBUG] {npc_name} WAS MENTIONED in input: '{player_input[:50]}...'")
            
            # Check if NPC is in same location (for logging only)
            is_in_same_location = False
            if game_state and hasattr(game_state, 'get_npc_location'):
                npc_location = game_state.get_npc_location(npc_name)
                if npc_location and player_location and npc_location == player_location:
                    is_in_same_location = True
            
            # NPC can intervene ONLY if:
            # - Player mentioned them explicitly, OR
            # - Player has sufficient affinity (knows them well)
            # NOTE: Being in same location is NOT enough - player must mention them or know them
            can_intervene = is_mentioned or (player_affinity >= self.MIN_PLAYER_AFFINITY)
            logger.debug(f"[MultiNPC DEBUG] {npc_name}: mentioned={is_mentioned}, same_loc={is_in_same_location}, affinity={player_affinity:.0f}, can_intervene={can_intervene}")

            if not can_intervene:
                logger.debug(
                    f"[MultiNPC] {npc_name} skipped: not mentioned, not co-located, affinity "
                    f"{player_affinity:.0f} < {self.MIN_PLAYER_AFFINITY}"
                )
                continue
            
            potential_candidates.append(npc_name)
        
        logger.debug(f"[MultiNPC DEBUG] potential_candidates before ruleset: {potential_candidates}")

        if not potential_candidates:
            logger.debug("[MultiNPC DEBUG] No potential candidates, returning None")
            return None

        # Build npc_links dict
        npc_links_dict = {}
        if self.personality_engine:
            for npc in potential_candidates:
                state = self.personality_engine._ensure_state(npc)
                npc_links_dict[npc] = state.npc_links

        logger.debug(f"[MultiNPC DEBUG] npc_links_dict: {npc_links_dict}")

        # Now check relationships between these candidates and active NPC
        # force_interaction=True because we already filtered by mention/location/affinity above
        candidates = self.ruleset.get_npcs_that_might_intervene(
            active_npc,
            potential_candidates,
            npc_links_dict,
            force_interaction=True,  # Already filtered above, force interaction
        )

        logger.debug(f"[MultiNPC DEBUG] Candidates after ruleset filter: {candidates}")

        if not candidates:
            logger.debug("[MultiNPC DEBUG] No candidates after ruleset filter, skipping MultiNPC")
            return None
        
        # Risolvi il display name dell'NPC attivo (usa il name dal template se disponibile)
        def _display_name(npc_id: str) -> str:
            if self.world:
                tmpl = self.world.npc_templates.get(npc_id)
                if tmpl:
                    return (tmpl.get("name", npc_id) if isinstance(tmpl, dict)
                            else getattr(tmpl, "name", npc_id))
                comp = self.world.companions.get(npc_id)
                if comp:
                    return getattr(comp, "name", npc_id)
            return npc_id

        active_npc_label = _display_name(active_npc)

        # Build sequence - only take the most likely intervener (first in sorted list)
        # Max 1 intervention per sequence (total 3 turns: active, secondary, active)
        sequence = DialogueSequence(
            player_input=player_input,
            active_npc=active_npc,
        )

        # First turn: Active NPC responds to player (foreground focus)
        sequence.add_turn(DialogueTurn(
            speaker=active_npc_label,
            speaker_type=SpeakerType.ACTIVE_NPC,
            focus_position="foreground",
        ))
        
        # Second turn: Secondary NPC intervention (if qualifies)
        if candidates and sequence.can_add_intervention():
            npc_name, interaction_type, rapport = candidates[0]
            
            sequence.add_turn(DialogueTurn(
                speaker=npc_name,
                speaker_type=SpeakerType.SECONDARY_NPC,
                interaction_type=interaction_type,
                target_npc=active_npc,
                focus_position="foreground",  # Secondary NPC now in focus
            ))
            
            # Track intervention
            self._intervention_counts[npc_name] = 1
            
            # Track cooldown
            current_turn = getattr(game_state, 'turn_count', 0)
            self._last_intervention_turn[npc_name] = current_turn
            logger.debug(f"[MultiNPC] {npc_name} intervenes (cooldown starts, turn {current_turn})")
            
            # Third turn: Active NPC responds to intervention (back to focus)
            sequence.add_turn(DialogueTurn(
                speaker=active_npc_label,
                speaker_type=SpeakerType.ACTIVE_NPC,
                is_final=True,
                focus_position="foreground",
            ))
        
        return sequence
    
    def format_prompt_for_llm(
        self,
        sequence: DialogueSequence,
        npc_personalities: Dict[str, str],
    ) -> str:
        """Format a prompt section for the LLM explaining multi-NPC context.
        
        Args:
            sequence: Dialogue sequence with planned interactions
            npc_personalities: Dict of npc_name -> personality description
            
        Returns:
            Formatted prompt section
        """
        lines = [
            "=== MULTI-NPC SCENE ===",
            f"Active: {sequence.active_npc}",
            "Present:",
        ]
        
        for turn in sequence.turns:
            if turn.speaker_type == SpeakerType.SECONDARY_NPC:
                lines.append(f"  - {turn.speaker} ({turn.interaction_type.name})")
                
                if turn.speaker in npc_personalities:
                    lines.append(f"    Personality: {npc_personalities[turn.speaker]}")
        
        lines.extend([
            "",
            "INSTRUCTIONS:",
            "1. First, respond as the Active NPC to the player",
        ])
        
        if any(t.speaker_type == SpeakerType.SECONDARY_NPC for t in sequence.turns):
            lines.extend([
                "2. Then, have the Secondary NPC interrupt/react",
                "3. Finally, have the Active NPC respond to the interruption",
            ])
        
        lines.append("4. Use character names in dialogue tags for clarity")
        
        return "\n".join(lines)

    def _extract_pose_from_visual(self, visual_desc: str, npc_name: str, is_speaker: bool) -> tuple:
        """Extract pose and emotion from visual description using keyword matching.
        
        Args:
            visual_desc: Visual description from LLM
            npc_name: Name of the NPC
            is_speaker: Whether this NPC is the current speaker
            
        Returns:
            Tuple of (pose, emotion) strings
        """
        if not visual_desc:
            return "", ""
        
        visual_lower = visual_desc.lower()
        
        # Keywords for poses/positions
        sitting_keywords = ['sitting', 'seated', 'on chair', 'at desk', 'on lap']
        standing_keywords = ['standing', 'on feet', 'upright']
        leaning_keywords = ['leaning', 'against', 'on wall', 'bent over']
        kneeling_keywords = ['kneeling', 'on knees']
        lying_keywords = ['lying', 'on back', 'on stomach', 'reclining']
        
        # Keywords for actions (romantic, sensual, dynamic)
        kissing_keywords = ['kissing', 'kiss', 'lip lock', 'making out']
        embracing_keywords = ['hugging', 'embracing', 'cuddling', 'holding close', 'arms around']
        touching_keywords = ['touching', 'caressing', 'stroking', 'hand on', 'fingers on', 'groping']
        gesturing_keywords = ['gesturing', 'pointing', 'waving', 'hands on hips']
        phone_keywords = ['phone', 'cellular', 'texting', 'looking at device']
        undressing_keywords = ['undressing', 'unbuttoning', 'removing', 'pulling down', 'sliding off']
        
        # Keywords for emotions
        angry_keywords = ['angry', 'furious', 'mad', 'annoyed', 'irritated', 'stern', 'severe']
        happy_keywords = ['happy', 'smiling', 'cheerful', 'laughing', 'joyful']
        sad_keywords = ['sad', 'crying', 'tears', 'depressed', 'upset']
        bored_keywords = ['bored', 'distracted', 'disinterested', 'looking away', 'slouching']
        surprised_keywords = ['surprised', 'shocked', 'astonished', 'wide eyes']
        serious_keywords = ['serious', 'focused', 'concentrated', 'professional', 'stern']
        aroused_keywords = ['aroused', 'blushing', 'flushed', 'breathless', 'biting lip', 'seductive']
        nervous_keywords = ['nervous', 'anxious', 'trembling', 'hesitant', 'flustered']
        
        # Determine base position
        pose = ""
        if any(k in visual_lower for k in lying_keywords):
            pose = "lying down"
        elif any(k in visual_lower for k in kneeling_keywords):
            pose = "kneeling"
        elif any(k in visual_lower for k in sitting_keywords):
            pose = "sitting"
        elif any(k in visual_lower for k in leaning_keywords):
            pose = "leaning"
        elif any(k in visual_lower for k in standing_keywords):
            pose = "standing"
        
        # Add specific actions (these can combine)
        actions = []
        if any(k in visual_lower for k in kissing_keywords):
            actions.append("kissing passionately")
        if any(k in visual_lower for k in embracing_keywords):
            actions.append("embracing closely")
        if any(k in visual_lower for k in touching_keywords):
            actions.append("touching intimately")
        if any(k in visual_lower for k in undressing_keywords):
            actions.append("undressing")
        if any(k in visual_lower for k in gesturing_keywords):
            actions.append("gesturing")
        if any(k in visual_lower for k in phone_keywords):
            actions.append("holding phone")
        
        if actions:
            pose += ", " + ", ".join(actions) if pose else ", ".join(actions)
        
        # Determine emotion
        emotion = ""
        if any(k in visual_lower for k in aroused_keywords):
            emotion = "flushed expression, aroused look"
        elif any(k in visual_lower for k in nervous_keywords):
            emotion = "nervous expression, hesitant"
        elif any(k in visual_lower for k in angry_keywords):
            emotion = "angry expression"
        elif any(k in visual_lower for k in happy_keywords):
            emotion = "smiling happily"
        elif any(k in visual_lower for k in sad_keywords):
            emotion = "sad expression"
        elif any(k in visual_lower for k in bored_keywords):
            emotion = "bored expression"
        elif any(k in visual_lower for k in surprised_keywords):
            emotion = "surprised expression"
        elif any(k in visual_lower for k in serious_keywords):
            emotion = "serious expression"
        
        # If no specific pose/emotion found, use the visual description as action
        if not pose and not emotion:
            # Return truncated visual description as pose
            pose = visual_desc[:100] if len(visual_desc) > 100 else visual_desc
        
        return pose, emotion

    def prepare_characters_for_builder(
        self,
        turn: DialogueTurn,
        all_present_npcs: List[str],
        outfit_data: Dict[str, Any],
        visual_description: str = "",
    ) -> List[Dict[str, str]]:
        """Prepare character list for MultiCharacterBuilder.
        
        Creates position mapping where the speaking NPC is in foreground
        and others are positioned in background.
        
        Args:
            turn: Current dialogue turn
            all_present_npcs: All NPCs present in scene
            outfit_data: Dict of npc_name -> outfit info
            
        Returns:
            List of character dicts for MultiCharacterBuilder
        """
        characters = []
        speaker = turn.speaker
        
        # Define position based on focus
        # Speaker always in foreground/center
        # Others distributed in background
        positions = {
            "foreground": "center foreground",
            "center": "center",
            "background": "background",
        }
        
        # Background positions for non-speakers
        bg_positions = ["left background", "right background", "far background"]
        bg_idx = 0
        
        # Determine scene context based on interaction type
        interaction_type = getattr(turn, 'interaction_type', None)
        speaker_type = getattr(turn, 'speaker_type', None)
        
        # Build dynamic poses based on who is speaking and the interaction
        for npc in all_present_npcs:
            is_speaker = (npc == speaker)
            
            # Position: speaker in foreground, others in background
            if is_speaker:
                position = positions.get(turn.focus_position, "center foreground")
            else:
                position = bg_positions[bg_idx % len(bg_positions)]
                bg_idx += 1
            
            # Get base prompt from world
            base_prompt = ""
            if self.world and npc in self.world.companions:
                companion = self.world.companions[npc]
                base_prompt = getattr(companion, 'base_prompt', '')
            
            # Get outfit
            outfit = outfit_data.get(npc, {})
            outfit_desc = outfit.get('description', '') if isinstance(outfit, dict) else str(outfit)
            
            # Determine pose and emotion
            # First try to extract from visual description (LLM-generated scene context)
            pose, emotion = self._extract_pose_from_visual(visual_description, npc, is_speaker)
            
            # DEBUG: Log extraction result
            logger.info(f"[MultiNPC POSE] {npc}: extracted pose='{pose[:50]}...' emotion='{emotion[:50]}...' from visual='{visual_description[:80]}...'")
            
            # Fallback to role-based defaults if extraction failed
            # Use separate checks so we keep extracted pose even if emotion failed
            if not pose:
                if is_speaker:
                    pose = "standing, gesturing" if speaker_type and speaker_type.name != "SECONDARY_NPC" else "sitting at desk"
                else:
                    pose = "sitting at desk, slouching"
                logger.info(f"[MultiNPC POSE] {npc}: using FALLBACK pose='{pose}'")
            
            if not emotion:
                if is_speaker:
                    emotion = "serious expression" if speaker_type and speaker_type.name != "SECONDARY_NPC" else "bored expression"
                else:
                    emotion = "neutral expression, listening"
                logger.info(f"[MultiNPC POSE] {npc}: using FALLBACK emotion='{emotion}'")
            
            characters.append({
                'name': npc,
                'position': position,
                'outfit': outfit_desc,
                'base_prompt': base_prompt,
                'pose': pose,
                'emotion': emotion,
            })
        
        return characters

    # =========================================================================
    # V2: MultiNPC Expanded - Messaggi separati
    # =========================================================================

    async def generate_single_turn(
        self,
        turn: DialogueTurn,
        previous_turns: List[DialogueTurn],
        player_input: str,
        game_state: Any,
        llm_manager: Any,
    ) -> DialogueTurn:
        """Generate a single NPC message with context from previous turns.
        
        Args:
            turn: The current turn to generate (contains speaker info)
            previous_turns: List of already completed turns in this sequence
            player_input: Original player input
            game_state: Current game state
            llm_manager: LLM manager for generation
            
        Returns:
            Completed DialogueTurn with text, visual_en, tags_en
        """
        import asyncio
        import time
        
        start_time = time.time()
        
        # Build conversation context
        context_lines = [f"Input del player: {player_input}"]
        for prev in previous_turns:
            if prev.text:  # Skip empty turns
                context_lines.append(f"{prev.speaker}: {prev.text}")
        
        # Get NPC definition — check companions first, then npc_templates
        npc_def = None
        if self.world:
            npc_def = self.world.companions.get(turn.speaker) or self.world.npc_templates.get(turn.speaker)

        def _npc_val(key: str, default=""):
            if npc_def is None:
                return default
            if isinstance(npc_def, dict):
                return npc_def.get(key, default)
            return getattr(npc_def, key, default)

        npc_role = _npc_val('role')

        # Per i companion (oggetti) prova prima personality_system.base_personality
        # che è più ricca di base_personality top-level; fallback a personality
        if not isinstance(npc_def, dict):
            ps = getattr(npc_def, 'personality_system', None)
            ps_personality = getattr(ps, 'base_personality', '') if ps else ''
            npc_personality = (
                ps_personality
                or _npc_val('base_personality')
                or _npc_val('personality')
            )
        else:
            # npc_templates sono dict — usa 'personality' (campo completo)
            npc_personality = _npc_val('personality') or _npc_val('base_personality')

        # --- Emotional state context ---
        emotional_state_block = ""
        if npc_def and game_state:
            # Get current emotional state key
            npc_state = game_state.npc_states.get(turn.speaker)
            es_key = (npc_state.emotional_state if npc_state else None) or \
                     game_state.flags.get(f"emotional_state_{turn.speaker}") or "default"
            es_data = _npc_val('emotional_states', {}).get(es_key, {})
            if es_data:
                es_desc = es_data.get('description', '') if isinstance(es_data, dict) else getattr(es_data, 'description', '')
                es_tone = es_data.get('dialogue_tone', '') if isinstance(es_data, dict) else getattr(es_data, 'dialogue_tone', '')
                if es_desc or es_tone:
                    parts = []
                    if es_desc:
                        parts.append(f"Stato attuale: {es_desc}")
                    if es_tone:
                        parts.append(f"Tono di dialogo (OBBLIGATORIO): {es_tone}")
                    emotional_state_block = "\n".join(parts)

        # --- Affinity tier + voice markers ---
        affinity_block = ""
        if npc_def and game_state:
            affinity = game_state.affinity.get(turn.speaker, 0)
            tiers = _npc_val('affinity_tiers', {})
            current_tier = None
            for tier_range, data in sorted(tiers.items(),
                    key=lambda x: int(x[0].split("-")[0]) if "-" in x[0] else int(x[0])):
                min_val = int(tier_range.split("-")[0]) if "-" in tier_range else int(tier_range)
                if affinity >= min_val:
                    current_tier = data
            if current_tier:
                tier_tone = current_tier.get('tone', '') if isinstance(current_tier, dict) else getattr(current_tier, 'tone', '')
                voice_markers = current_tier.get('voice_markers', []) if isinstance(current_tier, dict) else getattr(current_tier, 'voice_markers', [])
                parts = []
                if tier_tone:
                    parts.append(f"Comportamento attuale: {tier_tone}")
                if voice_markers:
                    parts.append("Stile vocale (OBBLIGATORIO):")
                    parts.extend(f"  - {vm}" for vm in voice_markers)
                if parts:
                    affinity_block = "\n".join(parts)

        # --- Relationship context for secondary NPC ---
        relationship_block = ""
        from luna.systems.multi_npc.dialogue_sequence import SpeakerType
        if turn.speaker_type == SpeakerType.SECONDARY_NPC and npc_def and turn.target_npc:
            npc_rels = _npc_val('npc_relationships', {})
            rel = npc_rels.get(turn.target_npc, {})
            if rel:
                rel_type = rel.get('type', '') if isinstance(rel, dict) else getattr(rel, 'type', '')
                rel_desc = rel.get('description_it', rel.get('description', '')) if isinstance(rel, dict) else ''
                if rel_type:
                    relationship_block = f"Rapporto con {turn.target_npc}: {rel_type}"
                    if rel_desc:
                        relationship_block += f"\n{rel_desc}"

        # Build focused prompt for single NPC
        recent_context = ' | '.join(context_lines[-5:])

        # Determine scene context for visual description guidance
        scene_context = "classroom setting with desks"  # default
        if game_state and hasattr(game_state, 'current_location'):
            loc = game_state.current_location
            if loc:
                scene_context = getattr(loc, 'description', str(loc))[:50]

        # Assemble character block
        character_sections = [f"CARATTERE:\n{npc_personality}"]
        if emotional_state_block:
            character_sections.append(f"STATO EMOTIVO:\n{emotional_state_block}")
        if affinity_block:
            character_sections.append(f"COMPORTAMENTO:\n{affinity_block}")
        if relationship_block:
            character_sections.append(f"RELAZIONE:\n{relationship_block}")
        character_block = "\n\n".join(character_sections)

        # Build previous-turns-only context (player input goes in user_input)
        prev_context_lines = []
        for prev in previous_turns:
            if prev.text:
                prev_context_lines.append(f"{prev.speaker}: {prev.text}")
        prev_context = " | ".join(prev_context_lines[-4:]) if prev_context_lines else ""

        system_prompt = f"""Sei {turn.speaker}, {npc_role}.

{character_block}

SCENA ATTUALE:
{scene_context}
{f"SCAMBI PRECEDENTI:{chr(10)}{prev_context}" if prev_context else ""}
REGOLE:
- Rispondi SOLO come {turn.speaker}
- Max 2-3 frasi concise
- Rispetta OBBLIGATORIAMENTE il tono di dialogo e lo stile vocale definiti sopra
- Tono naturale, reattivo alla conversazione precedente
- Non ripetere ciò che hai già detto
- Rispondi in italiano

DESCRIZIONE VISIVA (visual_en):
Descrivi la scena in inglese includendo:
1. POSA: standing, sitting, leaning, kneeling, lying down, etc.
2. EMOZIONE: smiling, angry, blushing, nervous, bored, etc.
3. AZIONE: gesturing, holding phone, writing on board, looking away, etc.
4. Posizione relativa: in foreground, in background, at desk, near window

Esempi di visual_en:
- "standing near the window, arms crossed, angry expression, glaring at the class"
- "sitting at desk, leaning back, bored expression, looking at phone"
- "standing at blackboard, gesturing with chalk, serious expression, teaching"
- "leaning against wall, blushing slightly, nervous smile, watching secretly"

Produci un JSON con questa struttura esatta:
{{"text": "risposta narrativa in italiano", "visual_en": "description with pose, emotion, action in English"}}

Rispondi come {turn.speaker}:"""

        try:
            # Generate with JSON mode for structured output
            # llm_manager.generate() returns (LLMResponse, provider_name)
            response_tuple = await asyncio.wait_for(
                llm_manager.generate(
                    system_prompt=system_prompt,
                    user_input=player_input,
                    history=[],
                    json_mode=True,
                ),
                timeout=15.0  # Max 15s per LLM (Vertex AI latency)
            )
            response, _ = response_tuple  # unpack (LLMResponse, provider)

            # Parse response
            if hasattr(response, 'text') and response.text:
                turn.text = response.text.strip()
                turn.visual_en = getattr(response, 'visual_en', '')
                turn.tags_en = getattr(response, 'tags_en', [])
                
                # DEBUG: Log what we got from LLM
                logger.info(f"[MultiNPC] {turn.speaker} generated visual_en: '{turn.visual_en[:100]}...' " if len(str(turn.visual_en)) > 100 else f"[MultiNPC] {turn.speaker} generated visual_en: '{turn.visual_en}'")
            else:
                # Fallback se response è stringa o malformed
                turn.text = str(response) if response else f"*{turn.speaker} ti guarda in silenzio*"
                turn.visual_en = ""
                turn.tags_en = []
                logger.warning(f"[MultiNPC] {turn.speaker} had no response.text, using fallback")
                
        except asyncio.TimeoutError:
            logger.warning(f"[MultiNPC] Timeout for {turn.speaker}, using fallback")
            _gender = getattr(npc_def, "gender", "female") if npc_def else "female"
            _adj = "assorto" if _gender == "male" else "assorta"
            turn.text = f"*{turn.speaker} sembra {_adj} nei propri pensieri*"
            turn.visual_en = ""
            turn.tags_en = []
            
        except Exception as e:
            logger.error(f"[MultiNPC] Failed to generate turn for {turn.speaker}: {e}")
            turn.text = f"*{turn.speaker} ti guarda in silenzio*"
            turn.visual_en = ""
            turn.tags_en = []
        
        elapsed = time.time() - start_time
        logger.debug(f"[MultiNPC] Generated turn for {turn.speaker} in {elapsed:.2f}s")
        
        return turn

    def check_interruption(self, game_state: Any) -> bool:
        """Check if user requested interruption.
        
        Args:
            game_state: Current game state with flags
            
        Returns:
            True if interruption requested
        """
        if not game_state or not hasattr(game_state, 'flags'):
            return False
        return game_state.flags.get("_user_interrupt_multi_npc", False)

    def clear_interruption_flag(self, game_state: Any) -> None:
        """Clear the interruption flag."""
        if game_state and hasattr(game_state, 'flags'):
            game_state.flags.pop("_user_interrupt_multi_npc", None)
            game_state.flags.pop("_multi_npc_in_progress", None)
