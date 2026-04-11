"""Backward-compatibility shim — WorldSimulator moved to world_sim package."""
# ruff: noqa: F401
from luna.systems.world_sim import (  # noqa: F401
    WorldSimulator,
    TurnDirective,
    NarrativePressure,
    TurnDirector,
    AmbientEngine,
    NPCInitiative,
    AmbientDetail,
    NPCScenePresence,
    is_low_energy_input,
)
from luna.systems.npc_mind import TurnDriver  # noqa: F401
