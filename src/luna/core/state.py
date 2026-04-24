"""Luna RPG v6 - State Manager.

Single owner of GameState mutations.
All state changes go through here.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from luna.core.database import DatabaseManager
from luna.core.models import (
    GameState, OutfitState, PlayerState, TimeOfDay,
)

logger = logging.getLogger(__name__)

_SOLO_COMPANION = "_solo_"


class StateManager:
    """Manages the GameState lifecycle.

    Responsibilities:
    - Create new game sessions
    - Load existing sessions
    - Mutate state safely
    - Persist state to database
    """

    def __init__(self, db: DatabaseManager) -> None:
        self._db  = db
        self._state: Optional[GameState] = None

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def current(self) -> GameState:
        if self._state is None:
            raise RuntimeError("No game state loaded. Call create_new() or load() first.")
        return self._state

    @property
    def is_loaded(self) -> bool:
        return self._state is not None

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def create_new(
        self,
        db: Any,
        world_id: str,
        companion: str,
        companions_list: Optional[List[str]] = None,
        player_character: Optional[Dict[str, Any]] = None,
    ) -> GameState:
        """Create a brand new game session."""
        # Build initial affinity for all companions
        affinity: Dict[str, int] = {}
        if companions_list:
            for name in companions_list:
                if name != _SOLO_COMPANION:
                    affinity[name] = 0

        # Build initial player state
        player = PlayerState()
        if player_character:
            stats = player_character.get("starting_stats", {})
            identity = player_character.get("identity", {})
            player = PlayerState(
                name=identity.get("name", "Protagonista"),
                age=identity.get("age", 18),
                background=identity.get("background", ""),
                strength=stats.get("strength", 10),
                mind=stats.get("mind", 10),
                charisma=stats.get("charisma", 15),
                gold=stats.get("gold", 0),
            )

        # Create DB session row
        db_row = await self._db.create_session(
            db=db,
            world_id=world_id,
            companion=companion,
        )

        self._state = GameState(
            session_id=db_row.id,
            world_id=world_id,
            active_companion=companion,
            affinity=affinity,
            player=player,
        )

        logger.info(
            "New game state created: session=%d, world=%s, companion=%s",
            db_row.id, world_id, companion,
        )
        return self._state

    async def load(self, db: Any, session_id: int) -> Optional[GameState]:
        """Load game state from database."""
        row = await self._db.get_session(db, session_id)
        if not row:
            logger.error("Session %d not found", session_id)
            return None

        if not row.state_json:
            logger.error("Session %d has no state_json", session_id)
            return None

        try:
            data = json.loads(row.state_json)
            self._state = GameState.model_validate(data)
            logger.info(
                "Session %d loaded: world=%s, companion=%s, turn=%d",
                session_id, self._state.world_id,
                self._state.active_companion, self._state.turn_count,
            )
            return self._state
        except Exception as e:
            logger.error("Failed to deserialize state for session %d: %s", session_id, e)
            return None

    async def save(
        self,
        db: Any,
        companion_location: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> bool:
        """Persist current state to database."""
        if not self._state:
            return False
        try:
            state_json = self._state.model_dump_json()
            kwargs: Dict[str, Any] = dict(
                db=db,
                session_id=self._state.session_id,
                turn_count=self._state.turn_count,
                time_of_day=self._state.time_of_day.value
                    if hasattr(self._state.time_of_day, "value")
                    else str(self._state.time_of_day),
                location=self._state.current_location,
                companion=self._state.active_companion,
                state_json=state_json,
            )
            if save_name:
                kwargs["name"] = save_name
            await self._db.update_session(**kwargs)
            return True
        except Exception as e:
            logger.error("Failed to save state: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Mutations
    # -------------------------------------------------------------------------

    def advance_turn(self) -> None:
        """Increment turn counter."""
        self.current.turn_count += 1

    def change_affinity(self, character: str, delta: int) -> int:
        """Change affinity with clamping. Returns new value."""
        state = self.current
        old = state.affinity.get(character, 0)
        new = max(0, min(100, old + delta))
        state.affinity[character] = new
        if delta != 0:
            logger.debug("Affinity %s: %d → %d (%+d)", character, old, new, delta)
        return new

    def set_location(self, location_id: str) -> None:
        """Change current location."""
        old = self.current.current_location
        self.current.current_location = location_id
        logger.debug("Location: %s → %s", old, location_id)

    def set_time(self, time_of_day: TimeOfDay) -> None:
        """Change time of day."""
        self.current.time_of_day = time_of_day

    def set_outfit(self, outfit: OutfitState, companion: Optional[str] = None) -> None:
        """Update outfit for a companion."""
        self.current.set_outfit(outfit, companion)

    def set_flag(self, key: str, value: Any) -> None:
        """Set a game flag."""
        self.current.flags[key] = value

    def get_flag(self, key: str, default: Any = None) -> Any:
        return self.current.flags.get(key, default)

    # -------------------------------------------------------------------------
    # Companion management
    # -------------------------------------------------------------------------

    async def switch_companion(self, companion_name: str, game_state: GameState) -> bool:
        """Switch active companion."""
        old = game_state.active_companion
        if companion_name == old:
            return False

        game_state.active_companion = companion_name

        # Reset staying flags when switching
        if companion_name != _SOLO_COMPANION:
            game_state.companion_staying_with_player = False
            game_state.companion_invited_to_location = None

        logger.info("Companion switch: %s → %s", old, companion_name)
        return True

    async def switch_to_solo(self, game_state: GameState) -> bool:
        """Switch to solo mode (no active companion)."""
        return await self.switch_companion(_SOLO_COMPANION, game_state)

    def is_solo(self) -> bool:
        return self.current.active_companion == _SOLO_COMPANION
