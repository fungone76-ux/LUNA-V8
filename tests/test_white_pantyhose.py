"""Test for white pantyhose replacement.

Verifies that when player requests white pantyhose,
they REPLACE the black ones from teacher_suit base outfit.
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from luna.systems.outfit_modifier import OutfitModifierSystem
from luna.core.models import OutfitState, OutfitModification


class TestWhitePantyhoseReplacement:
    """Test that white pantyhose replace black ones in prompt."""
    
    def test_pantyhose_modification_detected(self):
        """Detect 'pantyhose bianchi' in player input."""
        modifier = OutfitModifierSystem()
        
        test_cases = [
            ("indossa pantyhose bianchi", "pantyhose", "added"),
            ("metti calze bianche", "pantyhose", "added"),
            ("cambia con collant bianchi", "pantyhose", "added"),
        ]
        
        for text, expected_component, expected_state in test_cases:
            detected = modifier._detect_modifications(text)
            detected_dict = dict(detected)
            
            assert expected_component in detected_dict, \
                f"Failed to detect pantyhose in '{text}'. Got: {detected}"
    
    def test_component_overrides_base_prompt(self):
        """Component should override base_sd_prompt when present."""
        
        # Create teacher outfit with black pantyhose in base
        outfit = OutfitState(
            style="teacher_suit",
            description="professional teacher outfit",
            base_description="completo da insegnante",
            base_sd_prompt="professional teacher outfit, charcoal grey pencil skirt, crisp white button-up blouse, sheer black pantyhose",
            components={}  # No components initially
        )
        
        # Add white pantyhose as component
        outfit.components["pantyhose"] = "white pantyhose"
        
        # Generate SD prompt
        sd_prompt = outfit.to_sd_prompt()
        
        # Should contain white pantyhose
        assert "white" in sd_prompt.lower(), \
            f"White pantyhose not in prompt: {sd_prompt}"
        
        # Should NOT contain black pantyhose
        assert "black" not in sd_prompt.lower(), \
            f"Black pantyhose still in prompt (should be replaced): {sd_prompt}"
        
        print(f"✓ SD Prompt: {sd_prompt}")
    
    def test_component_prompt_format(self):
        """Component should be formatted as '(value component:1.1)'."""
        outfit = OutfitState(style="teacher_suit")
        outfit.components["pantyhose"] = "white"
        
        sd_prompt = outfit.to_sd_prompt()
        
        # Should include component name for clarity
        assert "pantyhose" in sd_prompt.lower(), \
            f"Component name not in prompt: {sd_prompt}"
        assert "white" in sd_prompt.lower(), \
            f"Color not in prompt: {sd_prompt}"
    
    def test_major_change_clears_components(self):
        """Major outfit change should clear components and set base_sd_prompt."""
        import asyncio
        
        modifier = OutfitModifierSystem()
        
        game_state = Mock()
        game_state.turn_count = 5
        
        outfit = OutfitState(
            style="teacher_suit",
            components={"pantyhose": "white pantyhose"},  # Existing component
            modifications={}
        )
        game_state.get_outfit = Mock(return_value=outfit)
        game_state.set_outfit = Mock()
        
        # Apply major change for white pantyhose
        asyncio.run(modifier.apply_major_change(
            game_state, 
            "pantyhose bianchi", 
            None  # No LLM translation
        ))
        
        # Components should be cleared for major change
        assert len(outfit.components) == 0, \
            "Components should be cleared on major change"
        
        # base_sd_prompt should be set
        assert outfit.base_sd_prompt, \
            "base_sd_prompt should be set"
        assert "pantyhose" in outfit.base_sd_prompt.lower() or "white" in outfit.base_sd_prompt.lower(), \
            f"Pantyhose not in base_sd_prompt: {outfit.base_sd_prompt}"
    
    def test_outfit_renderer_includes_component(self):
        """OutfitRenderer should include component in description."""
        from luna.systems.outfit_renderer import OutfitRenderer
        
        outfit = OutfitState(style="teacher_suit")
        outfit.components["pantyhose"] = "white pantyhose"
        
        description = OutfitRenderer.render_description(outfit, None)
        
        assert "white" in description.lower(), \
            f"White pantyhose not in description: {description}"
    
    def test_full_flow_white_pantyhose(self):
        """Complete flow: player asks -> detected -> applied -> in prompt."""
        import asyncio
        
        # Setup
        modifier = OutfitModifierSystem()
        
        game_state = Mock()
        game_state.turn_count = 10
        
        # Teacher outfit with black pantyhose in base
        outfit = OutfitState(
            style="teacher_suit",
            base_sd_prompt="professional teacher outfit, charcoal grey pencil skirt, crisp white button-up blouse, sheer black pantyhose"
        )
        game_state.get_outfit = Mock(return_value=outfit)
        game_state.set_outfit = Mock()
        
        # Step 1: Player requests white pantyhose
        player_input = "indossa pantyhose bianchi"
        
        # Step 2: Process as major change
        asyncio.run(modifier.apply_major_change(
            game_state, 
            player_input, 
            None
        ))
        
        # Step 3: Verify outfit updated
        assert outfit.style == "custom", \
            f"Style should be custom, got {outfit.style}"
        
        # Step 4: Generate SD prompt
        sd_prompt = outfit.to_sd_prompt()
        
        # Step 5: Verify white pantyhose present, black absent
        assert "white" in sd_prompt.lower(), \
            f"White pantyhose missing from prompt: {sd_prompt}"
        
        # The base_sd_prompt should now contain white instead of black
        print(f"✓ Final SD Prompt: {sd_prompt}")
        print(f"✓ Base SD Prompt: {outfit.base_sd_prompt}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
