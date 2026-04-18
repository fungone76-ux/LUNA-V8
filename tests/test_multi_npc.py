from luna.core.models import CompanionDefinition, GameState, WorldDefinition
from luna.systems.multi_npc.interaction_rules import InteractionType
from luna.systems.multi_npc.manager import MultiNPCManager


class _DeterministicRuleset:
    """Ensures predictable interventions for testing."""

    def get_npcs_that_might_intervene(self, active_npc, present_npcs, npc_links, force_interaction=False):
        if not present_npcs:
            return []
        return [(present_npcs[0], InteractionType.NEUTRAL, 0)]


def test_mentioned_npc_can_intervene():
    """NPC interviene se il player la nomina esplicitamente."""
    world = WorldDefinition(
        id="test_world",
        name="Test World",
        locations={},
        companions={
            "Luna": CompanionDefinition(name="Luna"),
            "Stella": CompanionDefinition(name="Stella"),
        },
    )

    state = GameState(
        world_id=world.id,
        active_companion="Luna",
        current_location="luna_home",
        npc_locations={"Stella": "luna_home"},
        affinity={"Stella": 0},
    )

    manager = MultiNPCManager(world=world, enabled=True)
    manager.ruleset = _DeterministicRuleset()

    sequence = manager.process_turn(
        player_input="Parlo con Luna, e saluto anche Stella",  # Stella mentioned
        active_npc="Luna",
        game_state=state,
    )

    assert sequence is not None, "Expected a sequence when NPC is explicitly mentioned"
    assert len(sequence.turns) == 3
    assert sequence.turns[1].speaker == "Stella"


def test_co_located_npc_does_not_intervene_without_mention():
    """NPC co-located NON interviene senza menzione né affinità sufficiente."""
    world = WorldDefinition(
        id="test_world",
        name="Test World",
        locations={},
        companions={
            "Luna": CompanionDefinition(name="Luna"),
            "Stella": CompanionDefinition(name="Stella"),
        },
    )

    state = GameState(
        world_id=world.id,
        active_companion="Luna",
        current_location="luna_home",
        npc_locations={"Stella": "luna_home"},
        affinity={"Stella": 0},
    )

    manager = MultiNPCManager(world=world, enabled=True)
    manager.ruleset = _DeterministicRuleset()

    sequence = manager.process_turn(
        player_input="Parlo con Luna",  # Stella NOT mentioned, affinity 0
        active_npc="Luna",
        game_state=state,
    )

    assert sequence is None, "Co-located NPC with no mention and low affinity should NOT intervene"


def test_high_affinity_npc_can_intervene_without_mention():
    """NPC con affinità alta interviene anche senza essere nominata."""
    world = WorldDefinition(
        id="test_world",
        name="Test World",
        locations={},
        companions={
            "Luna": CompanionDefinition(name="Luna"),
            "Stella": CompanionDefinition(name="Stella"),
        },
    )

    state = GameState(
        world_id=world.id,
        active_companion="Luna",
        current_location="luna_home",
        npc_locations={"Stella": "luna_home"},
        affinity={"Stella": 10},
    )

    manager = MultiNPCManager(world=world, enabled=True)
    manager.ruleset = _DeterministicRuleset()

    sequence = manager.process_turn(
        player_input="Parlo con Luna",  # Stella NOT mentioned, but high affinity
        active_npc="Luna",
        game_state=state,
    )

    assert sequence is not None, "NPC with high affinity should intervene even without mention"
