"""Tests for narrative coherence and outfit modification tracking.

Verifies that:
1. Outfit modifications are correctly detected and applied
2. Narrative context includes outfit state
3. Story beats don't override immediate physical context
4. NPC reactions respect scene continuity
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from luna.systems.outfit_modifier import OutfitModifierSystem
from luna.systems.outfit_renderer import MODIFICATION_DESCRIPTIONS_IT
from luna.systems.input_intent import InputIntentAnalyzer, IntentType
from luna.core.models import (
    GameState, OutfitState, OutfitModification, 
    CompanionDefinition
)


class TestOutfitModificationDetection:
    """Test that outfit modifications are correctly detected from input."""
    
    def test_detect_skirt_lift(self):
        """Detect 'gonna sollevata' pattern."""
        modifier = OutfitModifierSystem()
        
        test_cases = [
            ("la gonna è sollevata", "bottom", "lifted"),
            ("upskirt", "bottom", "lifted"),
            ("gonna alzata", "bottom", "lifted"),
            ("sotto la gonna", "bottom", "lifted"),
        ]
        
        for text, expected_component, expected_state in test_cases:
            detected = modifier._detect_modifications(text)
            assert (expected_component, expected_state) in detected, \
                f"Failed to detect '{text}' -> {expected_component}:{expected_state}"
    
    def test_detect_pantyhose_torn(self):
        """Detect when pantyhose is torn."""
        modifier = OutfitModifierSystem()
        
        test_cases = [
            ("le calze sono strappate", ["pantyhose"]),
            ("collant strappato", ["pantyhose"]),
        ]
        
        for text, expected_components in test_cases:
            detected = modifier._detect_modifications(text)
            detected_components = [comp for comp, _ in detected]
            for comp in expected_components:
                assert comp in detected_components, \
                    f"Failed to detect '{comp}' in '{text}'"


class TestOutfitStateTracking:
    """Test that outfit state correctly tracks modifications."""
    
    def test_outfit_to_prompt_string_with_mods(self):
        """to_prompt_string includes modification descriptions."""
        outfit = OutfitState(
            style="teacher_suit",
            description="professional teacher outfit",
            base_description="completo da insegnante",
        )
        
        # Add a modification
        outfit.modifications["bottom"] = OutfitModification(
            component="bottom",
            state="lifted",
            description="gonna sollevata, cosce scoperte",
            sd_description="skirt lifted high, thighs exposed",
            applied_at_turn=5,
        )
        
        prompt_str = outfit.to_prompt_string()
        
        assert "gonna sollevata" in prompt_str.lower(), \
            f"Modification not in prompt string: {prompt_str}"
        assert "cosce scoperte" in prompt_str.lower(), \
            f"Exposed state not in prompt string: {prompt_str}"
    
    def test_disarrayed_outfit_detection(self):
        """Detect when outfit is in disarrayed state."""
        outfit = OutfitState(style="teacher_suit")
        
        # Add multiple exposing modifications
        outfit.modifications["bottom"] = OutfitModification(
            component="bottom", state="lifted",
            description="gonna sollevata",
            sd_description="skirt lifted",
            applied_at_turn=1,
        )
        outfit.modifications["pantyhose"] = OutfitModification(
            component="pantyhose", state="pulled_down",
            description="collant abbassati",
            sd_description="pantyhose pulled down",
            applied_at_turn=1,
        )
        
        # Check for disarrayed states
        disarrayed_states = ["lifted", "pulled_down", "exposed", "visible", "removed"]
        exposed_parts = []
        
        for mod_key, mod in outfit.modifications.items():
            if mod.state in disarrayed_states:
                exposed_parts.append(mod.description or mod_key)
        
        assert len(exposed_parts) == 2, f"Expected 2 exposed parts, got {exposed_parts}"
        assert "gonna sollevata" in exposed_parts


class TestNarrativeContextBuilding:
    """Test that narrative context correctly includes outfit state."""
    
    def test_outfit_context_includes_modifications(self):
        """_outfit_context should highlight disarrayed clothing."""
        from luna.agents.narrative import NarrativeEngine
        
        world = Mock()
        world.name = "Test World"
        world.genre = "School Romance"
        world.lore = "A school setting"
        world.time_slots = {}
        world.locations = {}
        
        engine = NarrativeEngine(world)
        
        # Create game state with modified outfit
        game_state = Mock()
        game_state.active_companion = "Luna"
        
        outfit = OutfitState(style="teacher_suit")
        outfit.modifications["bottom"] = OutfitModification(
            component="bottom", state="lifted",
            description="gonna sollevata, cosce scoperte",
            sd_description="skirt lifted",
            applied_at_turn=1,
        )
        
        game_state.get_outfit = Mock(return_value=outfit)
        
        companion = Mock()
        companion.name = "Luna"
        
        # Get outfit context
        context_lines = engine._outfit_context(game_state, companion)
        context_str = "\n".join(context_lines)
        
        # Verify modifications are mentioned
        assert "gonna sollevata" in context_str.lower() or "CRITICAL" in context_str, \
            f"Disarrayed state not highlighted in context: {context_str}"


class TestInputIntentAnalysis:
    """Test that input intents correctly detect physical actions."""
    
    def test_intimate_action_detection(self):
        """Detect intimate/physical actions from player input."""
        world = Mock()
        world.companions = {}
        
        analyzer = InputIntentAnalyzer(world)
        
        # These are physical actions that should be detected
        test_inputs = [
            ("*gonna sollevata*", "outfit modification"),  # skirt lifted
            ("*calze strappate*", "outfit modification"),   # pantyhose torn
            ("*camicia sbottonata*", "outfit modification"),  # shirt unbuttoned
        ]
        
        for text, expected_type in test_inputs:
            bundle = analyzer.analyze(
                user_input=text,
                game_state=Mock(),
            )
            
            # Check that it detects outfit overlay
            has_detection = (
                len(bundle.secondary) > 0 or 
                bundle.outfit_overlay is not None
            )
            assert has_detection, \
                f"Input '{text}' ({expected_type}) not detected as physical action"


class TestStoryBeatCoherence:
    """Test that story beats don't override immediate context."""
    
    def test_story_beat_prompt_includes_continuity_rules(self):
        """Story beat context should include continuity rules."""
        from luna.agents.narrative import NarrativeEngine
        
        world = Mock()
        world.name = "Test"
        world.genre = "Romance"
        world.lore = ""
        world.time_slots = {}
        world.locations = {}
        
        engine = NarrativeEngine(world)
        
        # Create context with story beat
        context = {
            "story_context": "Luna wants to confess her divorce",
        }
        
        lines = engine._story_beat(context)
        context_str = "\n".join(lines)
        
        # Verify continuity rules are present
        assert "BUT" in context_str or "physical" in context_str.lower() or "intimate" in context_str.lower(), \
            f"Story beat doesn't include continuity rules: {context_str}"


class TestNarrativeFlowIntegration:
    """Integration tests for complete narrative flow."""
    
    @pytest.mark.asyncio
    async def test_narrative_respects_outfit_state(self):
        """Complete flow: outfit mod -> narrative context -> NPC reaction."""
        
        # Setup
        modifier = OutfitModifierSystem()
        
        game_state = Mock()
        game_state.turn_count = 10
        
        outfit = OutfitState(style="teacher_suit")
        game_state.get_outfit = Mock(return_value=outfit)
        game_state.set_outfit = Mock()
        
        # Step 1: Player lifts skirt (use pattern that system recognizes)
        player_input = "*la gonna è sollevata*"
        modified, is_major, desc = modifier.process_turn(
            player_input, game_state, None
        )
        
        assert modified, "Outfit modification should be detected"
        assert "bottom" in outfit.modifications, "Skirt should be marked as lifted"
        
        # Step 2: Verify modification is in outfit description
        outfit_desc = outfit.to_prompt_string()
        assert "sollevata" in outfit_desc.lower(), \
            f"Lifted state not in description: {outfit_desc}"
        
        # Step 3: Verify narrative context would include it
        from luna.agents.narrative import NarrativeEngine
        
        world = Mock()
        world.name = "Test"
        world.genre = "Romance"
        world.lore = ""
        world.time_slots = {}
        world.locations = {}
        
        engine = NarrativeEngine(world)
        
        companion = Mock()
        companion.name = "Luna"
        
        context_lines = engine._outfit_context(game_state, companion)
        context_str = "\n".join(context_lines)
        
        # The context should alert about disarrayed clothing
        assert "CRITICAL" in context_str or "gonna" in context_str.lower(), \
            f"Outfit disarray not highlighted: {context_str}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
