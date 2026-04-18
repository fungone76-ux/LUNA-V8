"""Tests for deterministic core systems — NPCMind, TurnDirector, TurnDirective, NPCStateManager."""
from __future__ import annotations

import sys
import os
from typing import Any
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from luna.core.models import TimeOfDay
from luna.systems.npc_mind import (
    NPCMind, NPCGoal, NPCMindManager, Emotion, EmotionType,
    GoalType, UnspokenItem, OffScreenEvent, TurnDriver,
    _DEFAULT_GOAL_TTL, _DEFAULT_UNSPOKEN_TTL,
    _MAX_EMOTIONS, _MAX_UNSPOKEN, _MAX_OFF_SCREEN,
)
from luna.systems.world_sim.turn_director import TurnDirector, is_low_energy_input
from luna.systems.world_sim.models import (
    TurnDirective, NPCInitiative, AmbientDetail, NPCScenePresence, NarrativePressure,
)
from luna.systems.npc_state_manager import NPCStateManager, NPCSnapshot
from luna.systems.world import WorldLoader, _normalize_time_key


# =============================================================================
# Helpers
# =============================================================================

def _game_state(
    active_companion: str = "luna",
    location: str = "classroom",
    npc_locations: dict | None = None,
    affinity: dict | None = None,
    turn: int = 1,
) -> Any:
    """Minimal GameState stub with the fields used by our systems."""
    gs = MagicMock()
    gs.active_companion = active_companion
    gs.current_location = location
    gs.npc_locations = npc_locations or {}
    gs.npc_location_expires = {}
    gs.affinity = affinity or {}
    gs.turn_count = turn
    # set_npc_location delegates to the dict
    def _set(name, loc, ttl=0):
        gs.npc_locations[name] = loc
    gs.set_npc_location.side_effect = _set
    gs.get_npc_location.side_effect = lambda n: gs.npc_locations.get(n)
    def _clear(name):
        gs.npc_locations.pop(name, None)
    gs.clear_npc_location.side_effect = _clear
    return gs


def _mind(npc_id: str = "luna", name: str = "Luna") -> NPCMind:
    return NPCMind(npc_id=npc_id, name=name)


# =============================================================================
# is_low_energy_input
# =============================================================================

class TestIsLowEnergyInput:
    def test_empty_string(self):
        assert is_low_energy_input("") is True

    def test_whitespace_only(self):
        assert is_low_energy_input("   ") is True

    def test_three_chars_or_fewer(self):
        assert is_low_energy_input("ok") is True
        assert is_low_energy_input("no") is True
        assert is_low_energy_input("mh") is True
        # exactly 3 chars
        assert is_low_energy_input("sì.") is True

    def test_affirmative_patterns(self):
        assert is_low_energy_input("ok") is True
        assert is_low_energy_input("okay") is True
        assert is_low_energy_input("va bene") is True
        assert is_low_energy_input("bene.") is True
        assert is_low_energy_input("sì") is True
        assert is_low_energy_input("si") is True

    def test_filler_patterns(self):
        assert is_low_energy_input("continua") is True
        assert is_low_energy_input("prosegui") is True
        assert is_low_energy_input("avanti") is True
        assert is_low_energy_input("dimmi") is True

    def test_greeting_patterns(self):
        assert is_low_energy_input("ciao") is True
        assert is_low_energy_input("hey") is True
        assert is_low_energy_input("ehi") is True

    def test_dots_only(self):
        assert is_low_energy_input("...") is True
        assert is_low_energy_input(".") is True

    def test_substantive_input_returns_false(self):
        assert is_low_energy_input("vado in classe") is False
        assert is_low_energy_input("parliamo del preside") is False
        assert is_low_energy_input("cosa è successo ieri?") is False
        assert is_low_energy_input("voglio sapere di Stella") is False

    def test_case_insensitive(self):
        assert is_low_energy_input("OK") is True
        assert is_low_energy_input("CONTINUA") is True
        assert is_low_energy_input("Ciao") is True


# =============================================================================
# TurnDirector.decide()
# =============================================================================

class TestTurnDirectorDecide:
    def _make_director(self, cooldown: int = 3) -> TurnDirector:
        mm = NPCMindManager()
        return TurnDirector(mm, cooldown=cooldown)

    def _intent(self, primary: str = "chat") -> Any:
        intent = MagicMock()
        intent.primary.value = primary
        return intent

    def test_specific_intent_always_player(self):
        director = self._make_director()
        gs = _game_state()
        for name in ("movement", "invitation", "outfit_major", "farewell"):
            intent = self._intent(name)
            driver, initiative = director.decide("ok", intent, gs, 1)
            assert driver == TurnDriver.PLAYER
            assert initiative is None

    def test_substantive_input_drives_player(self):
        director = self._make_director()
        gs = _game_state()
        intent = self._intent("chat")
        driver, initiative = director.decide("parliamo del torneo di pallavolo", intent, gs, 1)
        assert driver == TurnDriver.PLAYER

    def test_npc_takes_initiative_when_critical_goal_and_cooldown_ok(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        mind.current_goal = NPCGoal(
            description="test", goal_type=GoalType.CONFRONTATION, urgency=0.95
        )
        mind.turns_since_last_initiative = 10  # cooldown satisfied
        director = TurnDirector(mm, cooldown=3)
        gs = _game_state(active_companion="luna")
        intent = self._intent("chat")
        driver, initiative = director.decide("ok", intent, gs, 1)
        assert driver == TurnDriver.NPC
        assert initiative is not None
        assert initiative.npc_id == "luna"

    def test_npc_initiative_blocked_by_cooldown(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        mind.current_goal = NPCGoal(
            description="test", goal_type=GoalType.CONFRONTATION, urgency=0.95
        )
        mind.turns_since_last_initiative = 1  # cooldown NOT satisfied (need >= 3)
        director = TurnDirector(mm, cooldown=3)
        gs = _game_state(active_companion="luna")
        intent = self._intent("chat")
        driver, initiative = director.decide("ok", intent, gs, 1)
        # Critical goal but cooldown not met → player drives
        assert driver == TurnDriver.PLAYER

    def test_ambient_enrichment_after_many_quiet_turns(self):
        mm = NPCMindManager()
        director = TurnDirector(mm, cooldown=3)
        director._turns_since_event = 6  # > 5
        gs = _game_state()
        intent = self._intent("chat")
        driver, initiative = director.decide("ok", intent, gs, 1)
        assert driver == TurnDriver.AMBIENT

    def test_ambient_not_triggered_below_threshold(self):
        mm = NPCMindManager()
        director = TurnDirector(mm, cooldown=3)
        director._turns_since_event = 4  # ≤ 5
        gs = _game_state()
        intent = self._intent("chat")
        driver, _ = director.decide("ok", intent, gs, 1)
        # No active NPC goal, no burning unspoken → player
        assert driver == TurnDriver.PLAYER

    def test_make_initiative_urgency_labels(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        director = TurnDirector(mm)

        for urgency, expected_label in [
            (0.95, "critical"),
            (0.75, "high"),
            (0.5, "medium"),
            (0.2, "low"),
        ]:
            goal = NPCGoal(
                description="test goal", goal_type=GoalType.SOCIAL, urgency=urgency
            )
            initiative = director._make_initiative(mind, goal)
            assert initiative.urgency == expected_label

    def test_increment_event_counter(self):
        mm = NPCMindManager()
        director = TurnDirector(mm)
        assert director._turns_since_event == 0
        director.increment_event_counter()
        director.increment_event_counter()
        assert director._turns_since_event == 2

    def test_reset_event_counter(self):
        mm = NPCMindManager()
        director = TurnDirector(mm)
        director._turns_since_event = 10
        director.reset_event_counter()
        assert director._turns_since_event == 0


# =============================================================================
# TurnDirective.build_context() and to_summary()
# =============================================================================

class TestTurnDirective:
    def _initiative(self, urgency: str = "medium") -> NPCInitiative:
        return NPCInitiative(
            npc_id="luna", npc_name="Luna",
            action="Vuole parlare",
            goal_context="contesto test",
            emotional_state="frustrated",
            urgency=urgency,
            goal_type="confrontation",
        )

    def test_build_context_empty_directive(self):
        d = TurnDirective()
        ctx = d.build_context()
        assert ctx == ""

    def test_build_context_with_initiative(self):
        d = TurnDirective(npc_initiative=self._initiative("high"))
        ctx = d.build_context()
        assert "LUNA" in ctx
        assert "Vuole parlare" in ctx
        assert "IMPORTANT INITIATIVE" in ctx

    def test_build_context_ambient_section(self):
        d = TurnDirective()
        d.ambient = [
            AmbientDetail(description="Studenti nel corridoio", source="time"),
            AmbientDetail(description="Sole dalle finestre", source="location"),
        ]
        ctx = d.build_context()
        assert "AMBIENT DETAILS" in ctx
        assert "Studenti nel corridoio" in ctx
        assert "Sole dalle finestre" in ctx

    def test_build_context_secondary_npcs_exclude_active(self):
        d = TurnDirective()
        d.npcs_in_scene = [
            NPCScenePresence(npc_id="luna", npc_name="Luna", role="active"),
            NPCScenePresence(npc_id="stella", npc_name="Stella", role="present"),
        ]
        ctx = d.build_context()
        assert "Stella" in ctx
        # Active NPC should NOT appear in the OTHER CHARACTERS section
        assert "OTHER CHARACTERS" in ctx
        # Luna is active so not listed as secondary
        lines = ctx.splitlines()
        secondary_lines = [l for l in lines if "Luna" in l and "active" in l.lower()]
        assert len(secondary_lines) == 0

    def test_build_context_narrative_pressure_foreshadowing(self):
        d = TurnDirective()
        d.narrative_pressure = NarrativePressure(
            pressure_type="foreshadowing",
            hint="Qualcosa sta per succedere",
            building_towards="confronto",
            pressure_level=0.6,
        )
        ctx = d.build_context()
        assert "[ATMOSPHERE]" in ctx
        assert "Qualcosa sta per succedere" in ctx

    def test_build_context_narrative_pressure_buildup(self):
        d = TurnDirective()
        d.narrative_pressure = NarrativePressure(
            pressure_type="buildup",
            hint="La tensione cresce",
            building_towards="scontro",
            pressure_level=0.8,
        )
        ctx = d.build_context()
        assert "BUILDING" in ctx
        assert "La tensione cresce" in ctx

    def test_build_context_injected_context(self):
        d = TurnDirective()
        d.injected_context = "=== LUNA — STATO INTERNO ===\n[GOAL] test"
        ctx = d.build_context()
        assert "STATO INTERNO" in ctx

    def test_to_summary_structure(self):
        d = TurnDirective(driver=TurnDriver.NPC, npc_initiative=self._initiative())
        summary = d.to_summary()
        assert summary["driver"] == "npc"
        assert summary["npc_initiative"] is not None
        assert summary["npc_initiative"]["npc_id"] == "luna"
        assert summary["ambient_count"] == 0
        assert summary["needs_director"] is False

    def test_to_summary_with_scene_npcs(self):
        d = TurnDirective()
        d.npcs_in_scene = [
            NPCScenePresence(npc_id="luna", npc_name="Luna", role="active"),
            NPCScenePresence(npc_id="stella", npc_name="Stella", role="present"),
        ]
        summary = d.to_summary()
        assert "luna" in summary["npcs_in_scene"]
        assert "stella" in summary["npcs_in_scene"]

    def test_npc_initiative_to_prompt_urgency_markers(self):
        for urgency, marker in [
            ("low", "[NPC initiative]"),
            ("medium", "[NPC INITIATIVE]"),
            ("high", "[IMPORTANT INITIATIVE]"),
            ("critical", "[⚠️ CRITICAL INITIATIVE]"),
        ]:
            init = self._initiative(urgency)
            prompt = init.to_prompt()
            assert marker in prompt

    def test_should_use_director_many_npcs(self):
        from luna.systems.world_sim.turn_director import TurnDirector
        mm = NPCMindManager()
        td = TurnDirector(mm)
        d = TurnDirective()
        d.npcs_in_scene = [
            NPCScenePresence(npc_id=f"npc{i}", npc_name=f"NPC{i}", role="present")
            for i in range(3)
        ]
        assert td.should_use_director(d) is True

    def test_should_use_director_high_urgency(self):
        from luna.systems.world_sim.turn_director import TurnDirector
        mm = NPCMindManager()
        td = TurnDirector(mm)
        d = TurnDirective(npc_initiative=self._initiative("high"))
        assert td.should_use_director(d) is True

    def test_should_use_director_false_when_calm(self):
        from luna.systems.world_sim.turn_director import TurnDirector
        mm = NPCMindManager()
        td = TurnDirector(mm)
        d = TurnDirective()
        d.npcs_in_scene = [
            NPCScenePresence(npc_id="luna", npc_name="Luna", role="active"),
        ]
        assert td.should_use_director(d) is False


# =============================================================================
# NPCMind — emotions
# =============================================================================

class TestNPCMindEmotions:
    def test_add_emotion_basic(self):
        mind = _mind()
        mind.add_emotion(EmotionType.FRUSTRATED, intensity=0.6, cause="test", turn=1)
        assert len(mind.emotions) == 1
        assert mind.emotions[0].emotion == EmotionType.FRUSTRATED
        assert mind.emotions[0].intensity == 0.6

    def test_add_same_emotion_keeps_higher_intensity(self):
        mind = _mind()
        mind.add_emotion(EmotionType.HAPPY, intensity=0.4, turn=1)
        mind.add_emotion(EmotionType.HAPPY, intensity=0.8, turn=2)
        assert len(mind.emotions) == 1
        assert mind.emotions[0].intensity == 0.8

    def test_add_same_emotion_does_not_lower_intensity(self):
        mind = _mind()
        mind.add_emotion(EmotionType.HAPPY, intensity=0.8, turn=1)
        mind.add_emotion(EmotionType.HAPPY, intensity=0.3, turn=2)
        assert mind.emotions[0].intensity == 0.8

    def test_dominant_emotion_is_highest_intensity(self):
        mind = _mind()
        mind.add_emotion(EmotionType.SAD, intensity=0.3, turn=1)
        mind.add_emotion(EmotionType.ANGRY, intensity=0.9, turn=1)
        mind.add_emotion(EmotionType.NERVOUS, intensity=0.5, turn=1)
        dom = mind.dominant_emotion
        assert dom.emotion == EmotionType.ANGRY

    def test_dominant_emotion_none_when_empty(self):
        mind = _mind()
        assert mind.dominant_emotion is None

    def test_emotion_decay_tick(self):
        e = Emotion(emotion=EmotionType.NERVOUS, intensity=0.1, decay_rate=0.05)
        alive = e.tick()
        # 0.1 - 0.05 = 0.05, which is NOT > 0.05, so it returns False
        assert alive is False

    def test_emotion_decays_to_zero_not_negative(self):
        e = Emotion(emotion=EmotionType.SAD, intensity=0.03, decay_rate=0.1)
        e.tick()
        assert e.intensity == 0.0

    def test_emotion_cap_enforced_on_tick(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        # Add more than _MAX_EMOTIONS emotions
        for i, emo in enumerate([
            EmotionType.HAPPY, EmotionType.SAD, EmotionType.FRUSTRATED,
            EmotionType.NERVOUS, EmotionType.ANGRY, EmotionType.LONELY,
            EmotionType.EXCITED, EmotionType.JEALOUS, EmotionType.VULNERABLE,
            EmotionType.FLIRTY, EmotionType.TIRED,  # 11 > _MAX_EMOTIONS (10)
        ]):
            mind.emotions.append(Emotion(emotion=emo, intensity=0.6 + i * 0.01, decay_rate=0.001))
        gs = _game_state()
        mm._tick_one(mind, False, gs, 1)
        assert len(mind.emotions) <= _MAX_EMOTIONS


# =============================================================================
# NPCMind — unspoken items
# =============================================================================

class TestNPCMindUnspoken:
    def test_add_unspoken_basic(self):
        mind = _mind()
        mind.add_unspoken("ha visto qualcosa", turn=1, weight=0.4)
        assert len(mind.unspoken) == 1
        assert mind.unspoken[0].emotional_weight == 0.4

    def test_add_unspoken_no_duplicate(self):
        mind = _mind()
        mind.add_unspoken("stesso contenuto", turn=1)
        mind.add_unspoken("stesso contenuto", turn=2)
        assert len(mind.unspoken) == 1

    def test_is_burning_threshold(self):
        mind = _mind()
        mind.add_unspoken("qualcosa di pesante", turn=1, weight=0.65)
        assert mind.has_burning_unspoken is False
        mind.unspoken[0].emotional_weight = 0.7
        assert mind.has_burning_unspoken is True

    def test_unspoken_weight_grows_on_tick(self):
        mind = _mind()
        mind.add_unspoken("aspettando", turn=1, weight=0.3)
        item = mind.unspoken[0]
        item.tick()
        assert item.emotional_weight > 0.3

    def test_unspoken_weight_capped_at_1(self):
        mind = _mind()
        mind.add_unspoken("pesante", turn=1, weight=0.99)
        item = mind.unspoken[0]
        item.tick()
        assert item.emotional_weight <= 1.0

    def test_unspoken_ttl_expiry_on_manager_tick(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        # Add item with TTL of 5, created at turn 1
        item = UnspokenItem(content="scadrà presto", since_turn=1, ttl_turns=5, emotional_weight=0.5)
        mind.unspoken.append(item)
        gs = _game_state()
        # Tick at turn 6 → age = 5 >= ttl_turns 5 → should expire
        mm._tick_one(mind, False, gs, turn_number=6)
        assert all(u.content != "scadrà presto" for u in mind.unspoken)

    def test_unspoken_ttl_zero_never_expires(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        item = UnspokenItem(content="permanente", since_turn=1, ttl_turns=0, emotional_weight=0.5)
        mind.unspoken.append(item)
        gs = _game_state()
        # Tick 100 turns later — should still be there
        mm._tick_one(mind, False, gs, turn_number=101)
        assert any(u.content == "permanente" for u in mind.unspoken)

    def test_unspoken_cap_keeps_highest_weight(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        # Add more than _MAX_UNSPOKEN items
        for i in range(_MAX_UNSPOKEN + 5):
            item = UnspokenItem(
                content=f"item {i}", since_turn=1,
                emotional_weight=0.1 + i * 0.01, ttl_turns=0,
            )
            mind.unspoken.append(item)
        gs = _game_state()
        mm._tick_one(mind, False, gs, turn_number=2)
        assert len(mind.unspoken) <= _MAX_UNSPOKEN
        # Should keep highest weight items
        weights = [u.emotional_weight for u in mind.unspoken]
        assert min(weights) > 0.1  # lower-weight items dropped


# =============================================================================
# NPCMind — goals and TTL
# =============================================================================

class TestNPCMindGoals:
    def test_goal_urgency_grows_on_tick(self):
        goal = NPCGoal(
            description="test", goal_type=GoalType.SOCIAL,
            urgency=0.5, growth_rate=0.1
        )
        goal.tick()
        assert abs(goal.urgency - 0.6) < 0.001

    def test_goal_urgency_capped_at_max(self):
        goal = NPCGoal(
            description="test", goal_type=GoalType.SOCIAL,
            urgency=0.98, max_urgency=1.0, growth_rate=0.1
        )
        goal.tick()
        assert goal.urgency == 1.0

    def test_is_urgent_threshold(self):
        goal = NPCGoal(description="test", goal_type=GoalType.SOCIAL, urgency=0.69)
        assert goal.is_urgent is False
        goal.urgency = 0.7
        assert goal.is_urgent is True

    def test_is_critical_threshold(self):
        goal = NPCGoal(description="test", goal_type=GoalType.SOCIAL, urgency=0.89)
        assert goal.is_critical is False
        goal.urgency = 0.9
        assert goal.is_critical is True

    def test_goal_ttl_expiry_clears_goal(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        mind.current_goal = NPCGoal(
            description="scadrà", goal_type=GoalType.SOCIAL,
            urgency=0.3, created_at_turn=1, ttl_turns=5,
        )
        gs = _game_state()
        # At turn 6 age = 5 >= ttl_turns 5 → expires
        mm._tick_one(mind, False, gs, turn_number=6)
        # Goal should be cleared (or replaced by a new generated one)
        # If regenerated, it won't be the same goal
        if mind.current_goal:
            assert mind.current_goal.description != "scadrà"
        assert "scadrà" in mind.goal_history

    def test_goal_ttl_zero_never_expires(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        # Disable goal generation so we can test TTL in isolation
        mind.current_goal = NPCGoal(
            description="permanente", goal_type=GoalType.SOCIAL,
            urgency=0.3, max_urgency=0.95,  # won't hit max
            created_at_turn=1, ttl_turns=0, growth_rate=0.0,
        )
        gs = _game_state()
        mm._tick_one(mind, False, gs, turn_number=100)
        assert mind.current_goal is not None
        assert mind.current_goal.description == "permanente"


# =============================================================================
# NPCMind — needs
# =============================================================================

class TestNPCMindNeeds:
    def test_social_need_decreases_when_with_player(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        mind.needs["social"] = 0.5
        gs = _game_state(active_companion="luna")
        mm._tick_one(mind, is_with_player=True, game_state=gs, turn_number=1)
        assert mind.needs["social"] < 0.5

    def test_recognition_need_decreases_when_with_player(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        mind.needs["recognition"] = 0.5
        gs = _game_state(active_companion="luna")
        mm._tick_one(mind, is_with_player=True, game_state=gs, turn_number=1)
        assert mind.needs["recognition"] < 0.5

    def test_needs_grow_when_away_from_player(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        before = dict(mind.needs)
        gs = _game_state(active_companion="stella")  # not luna
        mm._tick_one(mind, is_with_player=False, game_state=gs, turn_number=1)
        # All needs should have grown (or stayed if already at 1.0)
        for need, val in mind.needs.items():
            assert val >= before[need]

    def test_needs_capped_at_1(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        for k in mind.needs:
            mind.needs[k] = 1.0
        gs = _game_state(active_companion="stella")
        mm._tick_one(mind, is_with_player=False, game_state=gs, turn_number=1)
        for val in mind.needs.values():
            assert val <= 1.0

    def test_social_need_not_below_zero(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        mind.needs["social"] = 0.02
        gs = _game_state(active_companion="luna")
        mm._tick_one(mind, is_with_player=True, game_state=gs, turn_number=1)
        assert mind.needs["social"] >= 0.0


# =============================================================================
# NPCMind — off-screen events
# =============================================================================

class TestNPCMindOffScreen:
    def test_add_off_screen_appends_event(self):
        mind = _mind()
        mind.add_off_screen("ha litigato col preside", turn=1, importance=0.6)
        assert len(mind.off_screen_log) == 1

    def test_add_off_screen_adds_emotion_when_significant(self):
        mind = _mind()
        mind.add_off_screen(
            "situazione stressante", turn=1,
            importance=0.7, emotional_impact="frustrated"
        )
        assert any(e.emotion == EmotionType.FRUSTRATED for e in mind.emotions)

    def test_add_off_screen_no_emotion_below_threshold(self):
        mind = _mind()
        mind.add_off_screen(
            "evento minore", turn=1,
            importance=0.3, emotional_impact="happy"
        )
        # importance 0.3 < 0.4 → no emotion added
        assert len(mind.emotions) == 0

    def test_untold_events_filters_told(self):
        mind = _mind()
        mind.add_off_screen("già detto", turn=1, importance=0.5)
        mind.off_screen_log[-1].told_to_player = True
        mind.add_off_screen("da dire", turn=2, importance=0.5)
        untold = mind.untold_events
        assert len(untold) == 1
        assert untold[0].description == "da dire"

    def test_clear_old_events_removes_old_told(self):
        mind = _mind()
        # Old told event (age > 30)
        mind.add_off_screen("vecchio e detto", turn=1, importance=0.5)
        mind.off_screen_log[-1].told_to_player = True
        # Old untold event — should be kept
        mind.add_off_screen("vecchio non detto", turn=1, importance=0.5)
        mind.clear_old_events(current_turn=40, max_age=30)
        descriptions = [e.description for e in mind.off_screen_log]
        assert "vecchio e detto" not in descriptions
        assert "vecchio non detto" in descriptions

    def test_off_screen_cap_prioritizes_untold(self):
        mm = NPCMindManager()
        mind = mm.get_or_create("luna", name="Luna")
        # Fill above cap: half told, half untold
        for i in range(_MAX_OFF_SCREEN + 10):
            mind.add_off_screen(
                description=f"evento {i}", turn=1,
                importance=0.5 + (i % 3) * 0.1,
            )
            if i % 2 == 0:
                mind.off_screen_log[-1].told_to_player = True
        gs = _game_state()
        mm._tick_one(mind, False, gs, turn_number=2)
        assert len(mind.off_screen_log) <= _MAX_OFF_SCREEN
        # Untold events should be prioritized
        untold_count = sum(1 for e in mind.off_screen_log if not e.told_to_player)
        assert untold_count > 0


# =============================================================================
# NPCMind — serialization round-trip
# =============================================================================

class TestNPCMindSerialization:
    def test_round_trip_preserves_basics(self):
        mind = _mind("luna", "Luna")
        mind.needs["social"] = 0.8
        mind.add_emotion(EmotionType.NERVOUS, intensity=0.7, cause="test", turn=5)
        mind.add_unspoken("segreto", turn=3, weight=0.6)
        mind.add_off_screen("evento", turn=2, importance=0.4)

        data = mind.to_dict()
        mind2 = _mind("tmp", "tmp")
        mind2.from_dict(data)

        # from_dict() is a partial update — npc_id stays as-is
        assert mind2.npc_id == "tmp"
        assert mind2.needs["social"] == 0.8
        assert len(mind2.emotions) == 1
        assert mind2.emotions[0].intensity == 0.7
        assert len(mind2.unspoken) == 1
        assert mind2.unspoken[0].content == "segreto"

    def test_round_trip_preserves_goal_ttl(self):
        mind = _mind()
        mind.current_goal = NPCGoal(
            description="test goal", goal_type=GoalType.SOCIAL,
            urgency=0.6, created_at_turn=5, ttl_turns=15,
        )
        data = mind.to_dict()
        mind2 = _mind("tmp", "tmp")
        mind2.from_dict(data)
        assert mind2.current_goal.ttl_turns == 15
        assert mind2.current_goal.created_at_turn == 5


# =============================================================================
# NPCStateManager
# =============================================================================

class TestNPCStateManager:
    def _setup(self, world=None):
        mm = NPCMindManager()
        mm.get_or_create("luna", name="Luna", is_companion=True)
        mm.get_or_create("stella", name="Stella", is_companion=True)
        mm.get_or_create("prof", name="Professore", is_companion=False)
        mgr = NPCStateManager(mind_manager=mm, world=world)
        return mgr, mm

    def test_location_of_returns_none_when_not_set(self):
        mgr, mm = self._setup()
        gs = _game_state(npc_locations={})
        assert mgr.location_of("luna", gs) is None

    def test_location_of_returns_value(self):
        mgr, mm = self._setup()
        gs = _game_state(npc_locations={"luna": "library"})
        assert mgr.location_of("luna", gs) == "library"

    def test_npcs_at_returns_matching_npcs(self):
        mgr, mm = self._setup()
        gs = _game_state(npc_locations={
            "luna": "classroom",
            "stella": "library",
            "prof": "classroom",
        })
        at_classroom = mgr.npcs_at("classroom", gs)
        assert "luna" in at_classroom
        assert "prof" in at_classroom
        assert "stella" not in at_classroom

    def test_npcs_at_exclude_active(self):
        mgr, mm = self._setup()
        gs = _game_state(
            active_companion="luna",
            npc_locations={"luna": "classroom", "prof": "classroom"},
        )
        at_classroom = mgr.npcs_at("classroom", gs, exclude_active=True)
        assert "luna" not in at_classroom
        assert "prof" in at_classroom

    def test_npcs_near_with_world(self):
        # Mock WorldDefinition with connected_to
        world = MagicMock()
        loc_def = MagicMock()
        loc_def.connected_to = ["library"]
        world.locations.get.return_value = loc_def

        mgr, mm = self._setup(world=world)
        gs = _game_state(npc_locations={"stella": "library", "prof": "gym"})
        near = mgr.npcs_near("classroom", gs)
        assert "stella" in near
        assert "prof" not in near

    def test_npcs_near_no_world_returns_empty(self):
        mgr, mm = self._setup(world=None)
        gs = _game_state(npc_locations={"stella": "library"})
        near = mgr.npcs_near("classroom", gs)
        assert near == []

    def test_npcs_offscreen_excludes_active_and_player_location(self):
        mgr, mm = self._setup()
        gs = _game_state(
            active_companion="luna",
            location="classroom",
            npc_locations={
                "luna": "classroom",   # active companion → excluded
                "stella": "library",   # off-screen
                "prof": "classroom",   # at player location → excluded
            },
        )
        offscreen = mgr.npcs_offscreen(gs)
        assert "stella" in offscreen.get("library", [])
        assert "luna" not in str(offscreen)
        assert "prof" not in str(offscreen)

    def test_snapshot_with_mind(self):
        mgr, mm = self._setup()
        mm.get("luna").add_emotion(EmotionType.HAPPY, intensity=0.8, turn=1)
        mm.get("luna").current_goal = NPCGoal(
            description="un obiettivo", goal_type=GoalType.SOCIAL, urgency=0.5
        )
        gs = _game_state(
            active_companion="luna",
            npc_locations={"luna": "classroom"},
            affinity={"luna": 60},
        )
        snap = mgr.snapshot("luna", gs)
        assert snap.npc_id == "luna"
        assert snap.name == "Luna"
        assert snap.location == "classroom"
        assert snap.affinity == 60
        assert snap.is_active_companion is True
        assert snap.current_goal == "un obiettivo"
        assert snap.dominant_emotion == "happy"

    def test_snapshot_missing_mind(self):
        mgr, mm = self._setup()
        gs = _game_state(npc_locations={})
        snap = mgr.snapshot("unknown_npc", gs)
        assert snap.npc_id == "unknown_npc"
        assert snap.location is None
        assert snap.current_goal is None
        assert snap.dominant_emotion is None

    def test_move_updates_game_state(self):
        mgr, mm = self._setup()
        gs = _game_state(npc_locations={})
        mgr.move("luna", "library", gs)
        assert gs.npc_locations.get("luna") == "library"

    def test_clear_removes_location(self):
        mgr, mm = self._setup()
        gs = _game_state(npc_locations={"luna": "library"})
        mgr.clear("luna", gs)
        assert gs.npc_locations.get("luna") is None

    def test_all_snapshots_returns_one_per_mind(self):
        mgr, mm = self._setup()
        gs = _game_state()
        snaps = mgr.all_snapshots(gs)
        ids = {s.npc_id for s in snaps}
        assert "luna" in ids
        assert "stella" in ids


# =============================================================================
# WorldLoader normalization
# =============================================================================


class TestWorldTimeNormalization:
    def test_normalize_time_key_strips_and_matches(self):
        assert _normalize_time_key("  Morning ") == TimeOfDay.MORNING

    def test_normalize_time_key_alias(self):
        assert _normalize_time_key("sera") == TimeOfDay.EVENING

    def test_process_companion_uses_normalized_schedule(self, tmp_path):
        loader = WorldLoader(worlds_path=tmp_path)
        companion = loader._process_companion(
            "Luna",
            {
                "schedule": {
                    " night ": {
                        "location": "player_home",
                        "outfit": "pajamas",
                        "activity": "rest",
                    }
                }
            },
        )

        assert TimeOfDay.NIGHT in companion.schedule
        entry = companion.schedule[TimeOfDay.NIGHT]
        assert entry.location == "player_home"
        assert entry.outfit == "pajamas"
