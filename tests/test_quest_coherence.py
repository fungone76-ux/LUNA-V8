"""Tests for quest coherence - no forced teleportation.

Verifies that:
1. Quests set flags instead of forcing location/outfit changes
2. Global events trigger when player moves to location
3. NPC reacts naturally to player's presence
"""

import pytest
from unittest.mock import Mock, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestQuestNoForcedTeleport:
    """Test that quests don't teleport player or force outfit."""
    
    def test_luna_gym_substitute_quest_sets_flag(self):
        """Luna gym quest should only set flag, not force location."""
        import yaml
        
        # Load the quest definition
        quest_file = os.path.join(
            os.path.dirname(__file__), '..', 
            'worlds', 'school_life_complete', 'luna.yaml'
        )
        
        with open(quest_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        quest = data.get('quests', {}).get('luna_gym_substitute', {})
        stages = quest.get('stages', {})
        
        # Check that on_enter only sets flag, doesn't force location
        for stage_name, stage in stages.items():
            on_enter = stage.get('on_enter', [])
            
            for action in on_enter:
                action_type = action.get('action', '')
                # Should NOT have set_location or set_outfit
                assert action_type != 'set_location', \
                    f"Stage '{stage_name}' forces location - should use flag instead"
                assert action_type != 'set_outfit', \
                    f"Stage '{stage_name}' forces outfit - should use flag instead"
    
    def test_luna_private_tutoring_quest_sets_flag(self):
        """Luna tutoring quest should only set flag."""
        import yaml
        
        quest_file = os.path.join(
            os.path.dirname(__file__), '..', 
            'worlds', 'school_life_complete', 'luna.yaml'
        )
        
        with open(quest_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        quest = data.get('quests', {}).get('luna_private_tutoring', {})
        stages = quest.get('stages', {})
        
        # Check that on_enter only sets flag
        for stage_name, stage in stages.items():
            on_enter = stage.get('on_enter', [])
            
            for action in on_enter:
                action_type = action.get('action', '')
                assert action_type != 'set_location', \
                    f"Stage '{stage_name}' forces location"
                assert action_type != 'set_outfit', \
                    f"Stage '{stage_name}' forces outfit"


class TestGlobalEventTriggers:
    """Test that global events trigger on conditions, not forced."""
    
    def test_luna_gym_event_requires_flag_and_location(self):
        """Gym event should require both flag and location."""
        import yaml
        
        events_file = os.path.join(
            os.path.dirname(__file__), '..', 
            'worlds', 'school_life_complete', 'global_events.yaml'
        )
        
        with open(events_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        events = data.get('global_events', {})
        gym_event = events.get('luna_gym_substitute_event', {})
        
        trigger = gym_event.get('trigger', {})
        conditions = trigger.get('conditions', [])
        
        # Must have flag condition
        flag_conditions = [c for c in conditions if 'flag' in c]
        assert len(flag_conditions) > 0, \
            "Gym event should require flag to be set"
        
        # Must have location condition
        location_conditions = [c for c in conditions if 'location' in c]
        assert len(location_conditions) > 0, \
            "Gym event should require specific location"
    
    def test_luna_private_lesson_event_requires_flag_and_location(self):
        """Private lesson event should require both flag and location."""
        import yaml
        
        events_file = os.path.join(
            os.path.dirname(__file__), '..', 
            'worlds', 'school_life_complete', 'global_events.yaml'
        )
        
        with open(events_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        events = data.get('global_events', {})
        lesson_event = events.get('luna_private_lesson_event', {})
        
        trigger = lesson_event.get('trigger', {})
        conditions = trigger.get('conditions', [])
        
        # Must have flag condition
        flag_conditions = [c for c in conditions if 'flag' in c]
        assert len(flag_conditions) > 0, \
            "Lesson event should require flag to be set"
        
        # Must have location condition
        location_conditions = [c for c in conditions if 'location' in c]
        assert len(location_conditions) > 0, \
            "Lesson event should require specific location"


class TestQuestInvitationFlow:
    """Test that quest flow is: invite -> player chooses -> scene triggers."""
    
    def test_luna_gym_quest_has_invitation_narrative(self):
        """Quest narrative should invite player, not force them."""
        import yaml
        
        quest_file = os.path.join(
            os.path.dirname(__file__), '..', 
            'worlds', 'school_life_complete', 'luna.yaml'
        )
        
        with open(quest_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        quest = data.get('quests', {}).get('luna_gym_substitute', {})
        stages = quest.get('stages', {})
        
        # Check narrative_prompt invites player
        for stage_name, stage in stages.items():
            narrative = stage.get('narrative_prompt', '')
            # Should contain invitation language
            is_invitation = any(word in narrative.lower() for word in [
                'potresti', 'vuoi', 'viene', 'passare', 'aspetto', 'aspetta',
                'se vuoi', 'ti aspetto', 'vieni', 'verrai'
            ])
            assert is_invitation, \
                f"Stage '{stage_name}' should invite player, not force them: {narrative[:100]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
