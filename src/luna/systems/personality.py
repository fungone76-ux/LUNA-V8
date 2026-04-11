"""Personality Engine - Psychological tracking system.

Analyzes player behavior and tracks NPC impressions.
Integrates with QuestEngine and StoryDirector.
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from luna.core.models import (
    BehavioralMemory,
    BehaviorType,
    GameState,
    Impression,
    NPCLink,
    PersonalityState,
    TraitIntensity,
)
from luna.core.state import StateManager

# Optional LLM analyzer
# from luna.ai.personality_analyzer import PersonalityAnalyzer


@dataclass
class BehavioralUpdate:
    """Result of behavior analysis."""
    detected_traits: List[Tuple[BehaviorType, TraitIntensity]]
    impression_changes: Dict[str, int]  # dimension -> delta
    archetype_hint: Optional[str] = None


class PersonalityEngine:
    """Tracks player behavior and NPC psychological states.
    
    Features:
    - Behavioral pattern detection from user input
    - 5-dimensional impression tracking per NPC
    - NPC relationship matrix (jealousy/gossip)
    - Dynamic archetype detection
    """
    
    # Patterns for behavior detection
    BEHAVIOR_PATTERNS: Dict[BehaviorType, List[str]] = {
        BehaviorType.AGGRESSIVE: [
            r"\b(attack|hit|force|threat|angry|mad|shout|yell)\b",
            r"(ordina|comanda|minacci|colp|attacc|urlo|grido|rabbia|arrabbia|violento)",
        ],
        BehaviorType.SHY: [
            r"\b(awkward|nervous|blush|stutter|look away|hesitate)\b",
            r"(imbarazz|nervos|arross|balbett|distogli|timid|esit|vergogn)",
        ],
        BehaviorType.ROMANTIC: [
            r"\b(love|kiss|hug|caress|beautiful|stunning|compliment)\b",
            r"(amo|baci|abbracc|carezz|bell|stupend|meraviglio|ti voglio|ti amo|sorrid|compli)",
        ],
        BehaviorType.DOMINANT: [
            r"\b(obey|submit|control|command|dominate|order)\b",
            r"(obbedi|sottomett|controll|comand|domin|impon|pretend|esig)",
        ],
        BehaviorType.SUBMISSIVE: [
            r"\b(sorry|please|thank|grateful|obey|yield|apologize)\b",
            r"(scus|perdon|prego|grazie|capito|certo|non mancherò|sarò|ubbidi|ced|molto bravo)",
        ],
        BehaviorType.CURIOUS: [
            r"\b(why|how|what|question|wonder|ask|investigate)\b",
            r"(perch[eé]|come mai|cosa|domand|chied|indaga|vorrei sapere|mi chiedo|capire)",
        ],
        BehaviorType.TEASING: [
            r"\b(teas|joke|mock|playful|smirk|flirt)\b",
            r"(stuzzic|scherz|flirt|gioc|sorrid|occhiolinacc|ammicca|provocat|scherzoso)",
        ],
        BehaviorType.PROTECTIVE: [
            r"\b(protect|defend|shield|save|help|rescue)\b",
            r"(protegg|difend|salv|aiut|soccorr|sto con te|sono qui)",
        ],
    }
    
    # Impression modifiers based on behavior
    IMPACT_MATRIX: Dict[BehaviorType, Dict[str, int]] = {
        BehaviorType.AGGRESSIVE: {
            "trust": -10,
            "attraction": -5,
            "fear": 15,
            "dominance_balance": -10,  # Player dominant
        },
        BehaviorType.SHY: {
            "trust": 5,
            "attraction": 10,
            "fear": -5,
            "dominance_balance": 5,  # NPC dominant
        },
        BehaviorType.ROMANTIC: {
            "trust": 5,
            "attraction": 15,
            "curiosity": 5,
        },
        BehaviorType.DOMINANT: {
            "attraction": 5,
            "fear": 10,
            "dominance_balance": -20,  # Player very dominant
        },
        BehaviorType.SUBMISSIVE: {
            "trust": 5,
            "fear": -10,
            "dominance_balance": 15,  # NPC dominant
        },
        BehaviorType.CURIOUS: {
            "trust": 5,
            "curiosity": 10,
        },
        BehaviorType.TEASING: {
            "attraction": 10,
            "curiosity": 5,
            "dominance_balance": -5,
        },
        BehaviorType.PROTECTIVE: {
            "trust": 15,
            "attraction": 5,
            "fear": -10,
        },
    }
    
    def __init__(
        self,
        state_manager: StateManager,
        world: Any = None,
        use_llm_analysis: bool = False,
        llm_analysis_interval: int = 3,
    ) -> None:
        """Initialize personality engine.
        
        Args:
            state_manager: For accessing game state
            world: World definition for starting impression values
            use_llm_analysis: Enable LLM-based deep analysis
            llm_analysis_interval: Analyze every N turns (if LLM enabled)
        """
        self.state_manager = state_manager
        self.world = world
        self._states: Dict[str, PersonalityState] = {}
        self._use_llm = use_llm_analysis
        self._llm_interval = llm_analysis_interval
        self._conversation_buffer: List[Dict[str, str]] = []
        
        # Lazy init LLM analyzer
        self._llm_analyzer = None
    
    def load_states(self, states: List[PersonalityState]) -> None:
        """Load saved personality states.
        
        Args:
            states: List of personality states from DB
        """
        for state in states:
            self._states[state.character_name] = state
    
    def get_all_states(self) -> List[PersonalityState]:
        """Get all states for saving.
        
        Returns:
            List of personality states
        """
        return list(self._states.values())
    
    def analyze_player_action(
        self,
        companion_name: str,
        user_input: str,
        turn_count: int,
        is_temporary: bool = False,
    ) -> BehavioralUpdate:
        """Analyze player action for behavioral patterns.
        
        Args:
            companion_name: Active companion
            user_input: Player's input text
            turn_count: Current turn
            is_temporary: If True, skip analysis (for generic NPCs)
            
        Returns:
            Analysis result with detected traits and impression changes
        """
        # Skip analysis for temporary/generic NPCs
        if is_temporary:
            logger.warning(f"[Personality] Skipping analysis for temporary NPC: {companion_name}")
            return BehavioralUpdate(
                detected_traits=[],
                impression_changes={},
                archetype_hint=None,
            )
        
        detected: List[Tuple[BehaviorType, TraitIntensity]] = []
        impression_changes: Dict[str, int] = {}
        
        logger.debug(f"[Personality] Analyzing input for {companion_name}: '{user_input[:50]}...' )")
        
        # Check each behavior pattern
        for behavior_type, patterns in self.BEHAVIOR_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, user_input, re.IGNORECASE):
                    # Found match
                    self._record_behavior(companion_name, behavior_type, turn_count)
                    intensity = self._get_behavior_intensity(
                        companion_name, behavior_type
                    )
                    detected.append((behavior_type, intensity))
                    
                    # Accumulate impression changes
                    impacts = self.IMPACT_MATRIX.get(behavior_type, {})
                    for dim, delta in impacts.items():
                        impression_changes[dim] = impression_changes.get(dim, 0) + delta
                    
                    break  # Only count once per behavior type
        
        # Apply impression changes
        self._apply_impression_changes(companion_name, impression_changes)
        
        # Update NPC links (other companions may notice)
        self._update_npc_awareness(companion_name, detected)
        
        # Check for archetype hint
        archetype = self._detect_archetype_hint(companion_name)
        
        # V4: Debug logging
        logger.debug(f"[Personality] Analysis complete:")
        logger.debug(f"  - Detected traits: {[t[0].value for t in detected]}")
        logger.debug(f"  - Impression changes: {impression_changes}")
        logger.debug(f"  - Archetype hint: {archetype}")
        
        return BehavioralUpdate(
            detected_traits=detected,
            impression_changes=impression_changes,
            archetype_hint=archetype,
        )
    
    async def analyze_with_llm(
        self,
        companion_name: str,
        user_input: str,
        assistant_response: str,
        turn_count: int,
    ) -> Optional[BehavioralUpdate]:
        """Analyze using LLM for deeper understanding (periodic).
        
        This runs every N turns for more accurate behavioral analysis.
        
        Args:
            companion_name: Active companion
            user_input: Player's input
            assistant_response: Companion's response
            turn_count: Current turn
            
        Returns:
            Analysis result or None if not running this turn
        """
        if not self._use_llm:
            return None
        
        # Buffer conversation
        self._conversation_buffer.append({"role": "user", "content": user_input})
        self._conversation_buffer.append({"role": "assistant", "content": assistant_response})
        
        # Keep last 6 messages (3 exchanges)
        if len(self._conversation_buffer) > 6:
            self._conversation_buffer = self._conversation_buffer[-6:]
        
        # Check if analysis should run
        if turn_count % self._llm_interval != 0:
            return None
        
        # Initialize analyzer if needed
        if self._llm_analyzer is None:
            from luna.ai.personality_analyzer import PersonalityAnalyzer
            self._llm_analyzer = PersonalityAnalyzer(self._llm_interval)
        
        # Get current affinity
        current_affinity = self.state_manager.get_affinity(companion_name)
        
        # Run analysis
        try:
            result = await self._llm_analyzer.analyze_behavior(
                companion_name=companion_name,
                history=self._conversation_buffer.copy(),
                current_affinity=current_affinity,
            )
            
            # Convert to BehavioralUpdate
            detected = []
            for trait_data in result.get("traits", []):
                detected.append((
                    trait_data["type"],
                    trait_data["intensity"],
                ))
            
            impression_changes = result.get("impression_changes", {})
            
            # V4.5 FIX: Only apply LLM changes if not empty (don't overwrite regex changes)
            if impression_changes:
                # Apply LLM changes (more nuanced than regex)
                self._apply_impression_changes(companion_name, impression_changes)
                logger.debug(f"[PersonalityEngine] LLM analysis applied changes: {impression_changes}")
            else:
                logger.debug(f"[PersonalityEngine] LLM analysis returned no changes, keeping regex results")
            
            return BehavioralUpdate(
                detected_traits=detected,
                impression_changes=impression_changes,
                archetype_hint=result.get("archetype_hint"),
            )
            
        except Exception as e:
            logger.warning(f"[PersonalityEngine] LLM analysis failed: {e}")
            return None
    
    def get_psychological_context(
        self,
        companion_name: str,
        include_behavioral: bool = True,
        include_impressions: bool = True,
        include_links: bool = True,
    ) -> str:
        """Build psychological context for LLM prompt.
        
        Args:
            companion_name: Target companion
            include_behavioral: Include behavior patterns
            include_impressions: Include impression scores
            include_links: Include NPC relations
            
        Returns:
            Formatted context string
        """
        state = self._ensure_state(companion_name)
        lines: List[str] = []
        
        # V4: Debug logging
        logger.debug(f"[Personality] Building context for {companion_name}:")
        logger.debug(f"  - Behavioral memories: {len(state.behavioral_memory)}")
        logger.debug(f"  - Impression: T={state.impression.trust} A={state.impression.attraction} F={state.impression.fear} C={state.impression.curiosity}")
        logger.debug(f"  - Archetype: {state.detected_archetype}")
        
        if include_behavioral and state.behavioral_memory:
            lines.append("=== BEHAVIORAL PATTERNS ===")
            for trait, memory in state.behavioral_memory.items():
                trait_str = trait.value if hasattr(trait, 'value') else str(trait)
                intensity_str = memory.intensity.value if hasattr(memory.intensity, 'value') else str(memory.intensity)
                lines.append(
                    f"- {trait_str}: {intensity_str} "
                    f"({memory.occurrences} times)"
                )
            lines.append("")
        
        if include_impressions:
            lines.append("=== IMPRESSION OF PLAYER ===")
            imp = state.impression
            lines.append(f"Trust: {imp.trust} ({self._describe_score(imp.trust)})")
            lines.append(f"Attraction: {imp.attraction} ({self._describe_score(imp.attraction)})")
            lines.append(f"Fear: {imp.fear} ({self._describe_score(imp.fear)})")
            lines.append(f"Curiosity: {imp.curiosity} ({self._describe_score(imp.curiosity)})")
            lines.append(
                f"Power Balance: {imp.dominance_balance} "
                f"({'Player Dominant' if imp.dominance_balance < -20 else 'NPC Dominant' if imp.dominance_balance > 20 else 'Equal'})"
            )
            lines.append("")
        
        if include_links and state.npc_links:
            lines.append("=== RELATIONSHIPS ===")
            for target, link in state.npc_links.items():
                lines.append(
                    f"- {target}: Rapport {link.rapport}, "
                    f"Awareness {link.awareness_of_player}%"
                )
            lines.append("")
        
        return "\n".join(lines)
    
    def detect_archetype(self, companion_name: str) -> Optional[str]:
        """Detect player's archetype for this companion.
        
        Args:
            companion_name: Target companion
            
        Returns:
            Archetype name or None
        """
        state = self._ensure_state(companion_name)
        
        # Use cached if recent
        if (state.archetype_cache_turn >= 0 and 
            state.archetype_cache_turn > self.state_manager.current.turn_count - 5):
            return state.detected_archetype
        
        # Calculate archetype
        archetype = self._calculate_archetype(state)
        
        state.detected_archetype = archetype
        state.archetype_cache_turn = self.state_manager.current.turn_count
        
        return archetype
    
    def get_power_dynamic(self, companion_name: str) -> str:
        """Get power dynamic description.
        
        Args:
            companion_name: Target companion
            
        Returns:
            Power dynamic description
        """
        state = self._ensure_state(companion_name)
        balance = state.impression.dominance_balance
        
        if balance < -40:
            return "PLAYER_DOMINANT"
        elif balance > 40:
            return "NPC_DOMINANT"
        return "EQUAL"
    
    def initialize_npc_links(
        self,
        companion_name: str,
        other_companions: List[str],
        link_data: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        """Initialize relationships with other NPCs.
        
        Args:
            companion_name: Target companion
            other_companions: List of other companion names
            link_data: Optional preset link data
        """
        state = self._ensure_state(companion_name)
        
        for other in other_companions:
            if other == companion_name:
                continue
            
            if other not in state.npc_links:
                # Use preset data or defaults
                preset = link_data.get(other, {}) if link_data else {}
                state.npc_links[other] = NPCLink(
                    target_npc=other,
                    rapport=preset.get("rapport", 0),
                    jealousy_sensitivity=preset.get("jealousy_sensitivity", 0.5),
                    awareness_of_player=preset.get("awareness", 0),
                )
    
    # ========================================================================
    # Private methods
    # ========================================================================
    
    def _ensure_state(self, companion_name: str) -> PersonalityState:
        """Get or create personality state."""
        if companion_name not in self._states:
            # Check if world defines starting impression values
            starting_impression = None
            companion_def = None
            if self.world and hasattr(self.world, 'companions'):
                companion_def = self.world.companions.get(companion_name)
                if companion_def and hasattr(companion_def, 'starting_impression'):
                    starting_impression = companion_def.starting_impression

            # Create state with custom or default impression
            self._states[companion_name] = PersonalityState(
                character_name=companion_name,
                impression=starting_impression if starting_impression else Impression(),
            )

            # Auto-populate npc_links from npc_relationships YAML data.
            # base_tension (0.0=friendly … 1.0=hostile) → rapport (-100…+100):
            #   rapport = clamp(int((0.5 - base_tension) * 200), -100, 100)
            # Examples: 0.9 tension → -80 (hostile), 0.1 tension → +80 (supportive)
            if companion_def and hasattr(companion_def, 'npc_relationships'):
                npc_rels = companion_def.npc_relationships or {}
                for target_npc, rel_data in npc_rels.items():
                    if not isinstance(rel_data, dict):
                        continue
                    base_tension = float(rel_data.get("base_tension", 0.5))
                    rapport_val = max(-100, min(100, int((0.5 - base_tension) * 200)))
                    self._states[companion_name].npc_links[target_npc] = NPCLink(
                        target_npc=target_npc,
                        rapport=rapport_val,
                    )
                    logger.debug(
                        "[Personality] %s→%s: base_tension=%.2f → rapport=%d",
                        companion_name, target_npc, base_tension, rapport_val,
                    )

        return self._states[companion_name]
    
    def _record_behavior(
        self,
        companion_name: str,
        behavior: BehaviorType,
        turn: int,
    ) -> None:
        """Record a behavior occurrence."""
        state = self._ensure_state(companion_name)
        
        if behavior not in state.behavioral_memory:
            state.behavioral_memory[behavior] = BehavioralMemory(
                trait=behavior,
                occurrences=0,
                last_turn=0,
                intensity=TraitIntensity.SUBTLE,
            )
        
        state.behavioral_memory[behavior].update(turn)
    
    def _get_behavior_intensity(
        self,
        companion_name: str,
        behavior: BehaviorType,
    ) -> TraitIntensity:
        """Get current intensity of a behavior."""
        state = self._ensure_state(companion_name)
        
        if behavior in state.behavioral_memory:
            return state.behavioral_memory[behavior].intensity
        return TraitIntensity.SUBTLE
    
    # DEBUG: Log impression changes
    def _apply_impression_changes(
        self,
        companion_name: str,
        changes: Dict[str, int],
    ) -> None:
        """Apply impression changes with clamping."""
        state = self._ensure_state(companion_name)
        imp = state.impression
        
        # Apply with clamping -100 to +100
        imp.trust = max(-100, min(100, imp.trust + changes.get("trust", 0)))
        imp.attraction = max(-100, min(100, imp.attraction + changes.get("attraction", 0)))
        imp.fear = max(-100, min(100, imp.fear + changes.get("fear", 0)))
        imp.curiosity = max(-100, min(100, imp.curiosity + changes.get("curiosity", 0)))
        imp.dominance_balance = max(-100, min(100, imp.dominance_balance + changes.get("dominance_balance", 0)))
        import logging
        logging.getLogger("LunaDebug").debug(f"IMPRESSION CHANGE: {companion_name} - {changes}")
    
    def _update_npc_awareness(
        self,
        active_companion: str,
        detected_traits: List[Tuple[BehaviorType, TraitIntensity]],
    ) -> None:
        """Update other NPCs' awareness of player actions."""
        if not detected_traits:
            return
        
        # Other companions may notice significant behaviors
        significant = any(
            intensity in (TraitIntensity.MODERATE, TraitIntensity.STRONG)
            for _, intensity in detected_traits
        )
        
        if not significant:
            return
        
        for name, state in self._states.items():
            if name == active_companion:
                continue
            
            if active_companion in state.npc_links:
                link = state.npc_links[active_companion]
                # Increase awareness based on jealousy sensitivity
                increase = int(5 * link.jealousy_sensitivity)
                link.awareness_of_player = min(100, link.awareness_of_player + increase)
    
    def _detect_archetype_hint(self, companion_name: str) -> Optional[str]:
        """Get archetype hint without full calculation."""
        state = self._ensure_state(companion_name)
        return state.detected_archetype
    
    def _calculate_archetype(self, state: PersonalityState) -> Optional[str]:
        """Calculate player archetype."""
        if not state.behavioral_memory:
            return None
        
        # Count occurrences by category
        counts: Dict[BehaviorType, int] = {}
        for trait, memory in state.behavioral_memory.items():
            counts[trait] = memory.occurrences
        
        if not counts:
            return None
        
        # Find dominant traits
        sorted_traits = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        dominant, count = sorted_traits[0]
        
        # Need at least 3 occurrences to have an archetype
        if count < 3:
            return None
        
        # Map to archetype names
        ARCHETYPE_MAP = {
            BehaviorType.ROMANTIC: "The Romantic",
            BehaviorType.DOMINANT: "The Dominant",
            BehaviorType.SHY: "The Shy Strategist",
            BehaviorType.AGGRESSIVE: "The Aggressor",
            BehaviorType.CURIOUS: "The Investigator",
            BehaviorType.TEASING: "The Playful Tease",
            BehaviorType.PROTECTIVE: "The Guardian",
            BehaviorType.SUBMISSIVE: "The Submissive",
        }
        
        return ARCHETYPE_MAP.get(dominant)
    
    def _describe_score(self, score: int) -> str:
        """Describe an impression score."""
        if score >= 50:
            return "Very High"
        elif score >= 20:
            return "High"
        elif score > -20:
            return "Neutral"
        elif score > -50:
            return "Low"
        return "Very Low"


# Import dataclass
from dataclasses import dataclass