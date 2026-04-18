"""Unit tests for luna/systems/schedule_manager.py.

Tests NPC schedule loading, location queries, presence detection,
context building, and auto-switch logic.

Run with: pytest tests/unit/test_schedule_manager.py -v
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest
from unittest.mock import MagicMock

from luna.systems.schedule_manager import ScheduleManager, ScheduleEntry, NPCSchedule
from luna.core.models import GameState, TimeOfDay


# =============================================================================
# Helpers
# =============================================================================

def make_game_state(
    time_of_day: TimeOfDay = TimeOfDay.MORNING,
    location: str = "home",
    companion: str = "Luna",
    affinity: dict = None,
) -> GameState:
    return GameState(
        world_id="test",
        active_companion=companion,
        time_of_day=time_of_day,
        current_location=location,
        affinity=affinity or {},
    )


def make_world_with_schedule(npc_name: str = "Luna", schedules: dict = None) -> MagicMock:
    """Build a minimal world mock with npc_schedules."""
    world = MagicMock()
    world.npc_schedules = {
        npc_name: schedules or {
            "morning": {"location": "classroom", "activity": "Teaching", "outfit": "teacher_suit"},
            "afternoon": {"location": "office", "activity": "Grading", "outfit": "teacher_suit"},
            "evening": {"location": "office", "activity": "Preparing", "outfit": "casual"},
            "night": {"location": "luna_home", "activity": "Sleeping", "outfit": "nightwear"},
        }
    }
    world.companions = {}
    world.locations = {}
    return world


# =============================================================================
# ScheduleEntry and NPCSchedule
# =============================================================================

class TestScheduleEntry:
    def test_defaults(self):
        entry = ScheduleEntry(location="classroom", activity="Teaching")
        assert entry.outfit == "default"
        assert entry.urgency == "medium"
        assert entry.available is True

    def test_custom_fields(self):
        entry = ScheduleEntry(
            location="home", activity="Resting", outfit="casual",
            urgency="low", available=False
        )
        assert entry.location == "home"
        assert entry.urgency == "low"
        assert entry.available is False


class TestNPCSchedule:
    def test_get_current_morning(self):
        entry_m = ScheduleEntry(location="classroom", activity="Teaching")
        entry_n = ScheduleEntry(location="home", activity="Sleeping")
        schedule = NPCSchedule(
            npc_name="Luna",
            schedules={TimeOfDay.MORNING: entry_m, TimeOfDay.NIGHT: entry_n}
        )
        assert schedule.get_current(TimeOfDay.MORNING) is entry_m
        assert schedule.get_current(TimeOfDay.NIGHT) is entry_n

    def test_get_current_missing_time_returns_none(self):
        schedule = NPCSchedule(npc_name="Luna", schedules={})
        assert schedule.get_current(TimeOfDay.AFTERNOON) is None

    def test_get_current_string_time(self):
        entry = ScheduleEntry(location="classroom", activity="Teaching")
        schedule = NPCSchedule(
            npc_name="Luna",
            schedules={TimeOfDay.MORNING: entry}
        )
        # String time conversion
        result = schedule.get_current("morning")
        assert result is entry

    def test_get_current_invalid_string_defaults_to_morning(self):
        entry_m = ScheduleEntry(location="classroom", activity="Teaching")
        schedule = NPCSchedule(
            npc_name="Luna",
            schedules={TimeOfDay.MORNING: entry_m}
        )
        result = schedule.get_current("invalid_time")
        assert result is entry_m


# =============================================================================
# ScheduleManager — initialization from world schedules
# =============================================================================

class TestScheduleManagerFromWorld:
    def test_loads_npc_from_world_schedules(self):
        gs = make_game_state()
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)

        assert "Luna" in sm.get_all_scheduled_npcs()

    def test_loads_all_time_slots(self):
        gs = make_game_state()
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)

        for tod in TimeOfDay:
            loc = sm.get_npc_location("Luna", tod)
            assert loc is not None

    def test_ignores_invalid_time_slot(self):
        gs = make_game_state()
        world = MagicMock()
        world.npc_schedules = {
            "Luna": {
                "morning": {"location": "classroom", "activity": "Teaching"},
                "INVALID": {"location": "nowhere", "activity": "Ghost"},
            }
        }
        world.companions = {}
        world.locations = {}
        sm = ScheduleManager(game_state=gs, world=world)
        # Should not crash; Luna should still be loaded
        assert "Luna" in sm.get_all_scheduled_npcs()

    def test_multiple_npcs(self):
        gs = make_game_state()
        world = MagicMock()
        world.npc_schedules = {
            "Luna": {"morning": {"location": "classroom", "activity": "Teaching"}},
            "Stella": {"morning": {"location": "library", "activity": "Reading"}},
        }
        world.companions = {}
        world.locations = {}
        sm = ScheduleManager(game_state=gs, world=world)
        npcs = sm.get_all_scheduled_npcs()
        assert "Luna" in npcs
        assert "Stella" in npcs


# =============================================================================
# ScheduleManager — no world (school_life defaults)
# =============================================================================

class TestScheduleManagerDefaultFallback:
    def test_no_world_loads_school_life_defaults(self):
        gs = make_game_state()
        sm = ScheduleManager(game_state=gs, world=None)
        # Luna should be present from school_life defaults
        assert "Luna" in sm.get_all_scheduled_npcs()

    def test_luna_morning_is_classroom(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        sm = ScheduleManager(game_state=gs, world=None)
        loc = sm.get_npc_location("Luna", TimeOfDay.MORNING)
        assert loc == "school_classroom"

    def test_luna_night_is_home(self):
        gs = make_game_state()
        sm = ScheduleManager(game_state=gs, world=None)
        loc = sm.get_npc_location("Luna", TimeOfDay.NIGHT)
        assert loc == "luna_home"


# =============================================================================
# ScheduleManager — world with companions but no npc_schedules
# =============================================================================

class TestScheduleManagerDefaultWithCompanions:
    def test_creates_default_schedule_for_companions(self):
        gs = make_game_state()
        world = MagicMock()
        world.npc_schedules = {}
        companion = MagicMock()
        companion.is_temporary = False
        companion.default_outfit = "casual"
        companion.spawn_locations = ["plaza"]
        world.companions = {"Maria": companion}
        world.locations = {"plaza": MagicMock()}
        sm = ScheduleManager(game_state=gs, world=world)
        assert "Maria" in sm.get_all_scheduled_npcs()

    def test_skips_solo_companion(self):
        gs = make_game_state()
        world = MagicMock()
        world.npc_schedules = {}
        companion = MagicMock()
        companion.is_temporary = False
        world.companions = {"_solo_": companion}
        world.locations = {}
        sm = ScheduleManager(game_state=gs, world=world)
        assert "_solo_" not in sm.get_all_scheduled_npcs()

    def test_skips_temporary_companion(self):
        gs = make_game_state()
        world = MagicMock()
        world.npc_schedules = {}
        companion = MagicMock()
        companion.is_temporary = True
        world.companions = {"temp_npc": companion}
        world.locations = {}
        sm = ScheduleManager(game_state=gs, world=world)
        assert "temp_npc" not in sm.get_all_scheduled_npcs()


# =============================================================================
# get_npc_location
# =============================================================================

class TestGetNpcLocation:
    def test_returns_location_for_known_npc(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        assert sm.get_npc_location("Luna") == "classroom"

    def test_returns_none_for_unknown_npc(self):
        gs = make_game_state()
        sm = ScheduleManager(game_state=gs, world=None)
        assert sm.get_npc_location("unknown_npc") is None

    def test_uses_game_state_time_when_none_given(self):
        gs = make_game_state(time_of_day=TimeOfDay.AFTERNOON)
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        assert sm.get_npc_location("Luna") == "office"

    def test_explicit_time_overrides_game_state(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        assert sm.get_npc_location("Luna", TimeOfDay.NIGHT) == "luna_home"


# =============================================================================
# get_npc_activity
# =============================================================================

class TestGetNpcActivity:
    def test_returns_activity_for_known_npc(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        activity = sm.get_npc_activity("Luna")
        assert "Teaching" in activity

    def test_returns_empty_string_for_unknown_npc(self):
        gs = make_game_state()
        sm = ScheduleManager(game_state=gs, world=None)
        assert sm.get_npc_activity("nobody") == ""

    def test_returns_activity_for_specific_time(self):
        gs = make_game_state()
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        activity = sm.get_npc_activity("Luna", TimeOfDay.AFTERNOON)
        assert "Grading" in activity


# =============================================================================
# get_present_npcs
# =============================================================================

class TestGetPresentNpcs:
    def test_returns_npc_at_location(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        present = sm.get_present_npcs("classroom")
        assert "Luna" in present

    def test_empty_when_no_npc_at_location(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        present = sm.get_present_npcs("nonexistent_location")
        assert present == []

    def test_multiple_npcs_at_same_location(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = MagicMock()
        world.npc_schedules = {
            "Luna": {"morning": {"location": "classroom", "activity": "Teaching"}},
            "Stella": {"morning": {"location": "classroom", "activity": "Assisting"}},
        }
        world.companions = {}
        world.locations = {}
        sm = ScheduleManager(game_state=gs, world=world)
        present = sm.get_present_npcs("classroom")
        assert "Luna" in present
        assert "Stella" in present

    def test_different_locations_not_mixed(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = MagicMock()
        world.npc_schedules = {
            "Luna": {"morning": {"location": "classroom", "activity": "Teaching"}},
            "Stella": {"morning": {"location": "library", "activity": "Reading"}},
        }
        world.companions = {}
        world.locations = {}
        sm = ScheduleManager(game_state=gs, world=world)
        assert sm.get_present_npcs("classroom") == ["Luna"]
        assert sm.get_present_npcs("library") == ["Stella"]


# =============================================================================
# get_primary_npc
# =============================================================================

class TestGetPrimaryNpc:
    def test_returns_npc_when_one_present(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        assert sm.get_primary_npc("classroom") == "Luna"

    def test_returns_none_when_empty(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        assert sm.get_primary_npc("empty_location") is None

    def test_highest_affinity_wins_when_multiple(self):
        gs = make_game_state(
            time_of_day=TimeOfDay.MORNING,
            affinity={"Luna": 20, "Stella": 80}
        )
        world = MagicMock()
        world.npc_schedules = {
            "Luna": {"morning": {"location": "classroom", "activity": "Teaching"}},
            "Stella": {"morning": {"location": "classroom", "activity": "Assisting"}},
        }
        world.companions = {}
        world.locations = {}
        sm = ScheduleManager(game_state=gs, world=world)
        # Stella has higher affinity → should be primary
        assert sm.get_primary_npc("classroom") == "Stella"


# =============================================================================
# build_schedule_context
# =============================================================================

class TestBuildScheduleContext:
    def test_context_contains_location(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING, location="home")
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        ctx = sm.build_schedule_context("Luna")
        assert "classroom" in ctx

    def test_context_contains_activity(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        ctx = sm.build_schedule_context("Luna")
        assert "Teaching" in ctx

    def test_context_contains_time(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        ctx = sm.build_schedule_context("Luna")
        assert "morning" in ctx.lower()

    def test_player_present_when_same_location(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING, location="classroom")
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        ctx = sm.build_schedule_context("Luna")
        assert "PLAYER IS PRESENT" in ctx

    def test_player_elsewhere_when_different_location(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING, location="home")
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        ctx = sm.build_schedule_context("Luna")
        assert "PLAYER IS ELSEWHERE" in ctx

    def test_returns_empty_for_unknown_npc(self):
        gs = make_game_state()
        sm = ScheduleManager(game_state=gs, world=None)
        assert sm.build_schedule_context("unknown") == ""


# =============================================================================
# should_auto_switch
# =============================================================================

class TestShouldAutoSwitch:
    def test_switches_when_different_npc_at_location(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING, companion="Stella")
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        result = sm.should_auto_switch("classroom", "Stella")
        assert result == "Luna"

    def test_no_switch_when_current_is_primary(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING, companion="Luna")
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        result = sm.should_auto_switch("classroom", "Luna")
        assert result is None

    def test_no_switch_when_no_npc_at_location(self):
        gs = make_game_state(time_of_day=TimeOfDay.MORNING)
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        result = sm.should_auto_switch("empty_room", "Luna")
        assert result is None


# =============================================================================
# get_schedule_summary
# =============================================================================

class TestGetScheduleSummary:
    def test_summary_for_known_npc(self):
        gs = make_game_state()
        world = make_world_with_schedule("Luna")
        sm = ScheduleManager(game_state=gs, world=world)
        summary = sm.get_schedule_summary("Luna")
        assert "Luna" in summary
        assert "classroom" in summary

    def test_summary_for_unknown_npc(self):
        gs = make_game_state()
        sm = ScheduleManager(game_state=gs, world=None)
        summary = sm.get_schedule_summary("nobody")
        assert "No schedule" in summary


# =============================================================================
# get_all_scheduled_npcs
# =============================================================================

class TestGetAllScheduledNpcs:
    def test_returns_list(self):
        gs = make_game_state()
        sm = ScheduleManager(game_state=gs, world=None)
        result = sm.get_all_scheduled_npcs()
        assert isinstance(result, list)

    def test_contains_luna_from_defaults(self):
        gs = make_game_state()
        sm = ScheduleManager(game_state=gs, world=None)
        assert "Luna" in sm.get_all_scheduled_npcs()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
