"""Luna RPG - Orchestrator State Manager Mixin.

State persistence methods.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from luna.core.models import GameState

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class StateManagerMixin:
    """Mixin providing state persistence methods for TurnOrchestrator.
    
    Contains _save method for persisting game state.
    """

    async def _save(
        self,
        game_state: GameState,
        user_input: str,
        narrative: NarrativeOutput,
        changes: Dict[str, Any],
    ) -> None:
        """Save memory + full state."""
        if self.engine.memory_manager:
            try:
                await self.engine.memory_manager.add_message(
                    role="user",
                    content=user_input,
                    turn_number=game_state.turn_count,
                    companion_name=game_state.active_companion,
                )
                await self.engine.memory_manager.add_message(
                    role="assistant",
                    content=narrative.text,
                    turn_number=game_state.turn_count,
                    companion_name=game_state.active_companion,
                    visual_en=narrative.visual_en,
                    tags_en=narrative.tags_en,
                )
                # Save new fact if any
                new_fact = changes.get("new_fact")
                if new_fact:
                    await self.engine.memory_manager.add_fact(
                        new_fact,
                        turn_number=game_state.turn_count,
                        associated_npc=game_state.active_companion,
                    )
            except Exception as e:
                logger.warning("[Orchestrator] Memory save failed: %s", e)

        if self.engine.state_memory:
            try:
                await self.engine.state_memory.save_all()
            except Exception as e:
                logger.warning("[Orchestrator] State save failed: %s", e)

    # =========================================================================
    # Step 10: Media
    # =========================================================================

