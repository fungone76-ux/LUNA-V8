import json
from pathlib import Path

from luna.systems.world_simulator import TurnDirective, TurnDriver
from luna.systems.turn_logger import TurnLogger


def test_turn_directive_summary_includes_initiative_event():
    directive = TurnDirective(driver=TurnDriver.NPC)
    directive.initiative_event = {"status": "fired", "reason": "test"}

    summary = directive.to_summary()

    assert summary["driver"] == TurnDriver.NPC.value
    assert summary["initiative_event"] == {"status": "fired", "reason": "test"}


class _DummyOutfit:
    def __init__(self) -> None:
        self.style = "casual"
        self.description = "t-shirt"
        self.components = {"top": "t-shirt"}
        self.modifications = {}
        self.is_special = False


class _DummyGameState:
    def __init__(self) -> None:
        self.active_companion = "Luna"
        self.current_location = "classroom"
        self.time_of_day = "Morning"
        self.affinity = {"Luna": 5}
        self.npc_locations = {"Luna": "classroom"}
        self.companion_staying_with_player = True
        self.active_quests = []
        self.completed_quests = []

    def get_outfit(self) -> _DummyOutfit:
        return _DummyOutfit()


def test_turn_logger_persists_telemetry(tmp_path: Path):
    game_state = _DummyGameState()
    logger = TurnLogger(tmp_path, session_id=7)

    logger.start_turn(1, "ciao", game_state)
    logger.log_turn_directive({"driver": "npc"})
    logger.log_initiative_event({"status": "accepted"})
    logger.end_turn()

    saved = tmp_path / "turn_logs" / "session_7" / "turn_0001.json"
    with saved.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    assert payload["turn_directive"] == {"driver": "npc"}
    assert payload["initiative_event"] == {"status": "accepted"}

