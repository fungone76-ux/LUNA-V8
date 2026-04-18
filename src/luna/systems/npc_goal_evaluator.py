"""NPC Goal Evaluator — M2 of NPC Secondary Activation System.

Evaluates goal_templates from npc_templates to generate hints for the player.
Respects cooldowns and returns only 1 hint per turn (highest urgency).
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Set

if TYPE_CHECKING:
    from luna.core.models import GameState, WorldDefinition

logger = logging.getLogger(__name__)


def _get_value(obj, key: str, default=None):
    """Safely get value from object or dict.
    
    Handles both object attributes (via getattr) and dict access (via .get).
    This is needed because npc_templates can be loaded as either objects or dicts.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@dataclass
class GoalHint:
    """A hint to be injected into the narrative."""
    npc_id: str
    npc_display_name: str
    goal_text: str  # narrative text to inject
    urgency: float  # 0.0-1.0
    goal_type: str  # "task", "social", "confrontation"
    goal_id: str
    initiative_style: str  # "friendly" | "authority" | "secret_keeper"
    location_display: str
    time_display: str
    secret_subject: str = ""       # only for secret_keeper
    completion_flag: str = ""      # flag to set when goal is fulfilled


@dataclass
class NpcAction:
    """Action for the NpcActionsWidget UI."""
    goal_id: str
    npc_id: str
    npc_display_name: str
    initiative_style: str
    location_display: str
    time_display: str
    secret_subject: str = ""
    urgency: float = 0.0


class NpcGoalEvaluator:
    """Evaluates NPC goals and generates hints for the player.

    Rules:
    - Only 1 hint per turn (highest urgency wins)
    - One NPC cannot have multiple pending actions
    - Cooldown between activations of the same goal
    - Actions persist until completion_flag is set
    - Authority NPCs: max 3 per session, min 35 turns between any two, mutual exclusion
    """

    AUTHORITY_GLOBAL_COOLDOWN = 35   # min turns between any two authority appearances
    AUTHORITY_SESSION_MAX     = 3    # max authority appearances per game session

    def __init__(self, world: "WorldDefinition") -> None:
        self.world = world
        # Track cooldowns: (npc_id, goal_id) -> turn_when_available_again
        self._cooldowns: Dict[tuple, int] = {}
        # Authority appearance tracking
        self._last_authority_turn: int = -999
        self._authority_session_count: int = 0

    def evaluate(
        self,
        game_state: "GameState"
    ) -> Optional[GoalHint]:
        """Evaluate all NPC goals and return the single best hint.

        Args:
            game_state: Current game state

        Returns:
            GoalHint with highest urgency, or None if no goals active
        """
        if not self.world or not game_state:
            return None

        # H3: Ensure active_npc_actions is initialized first
        if not hasattr(game_state, 'active_npc_actions') or game_state.active_npc_actions is None:
            game_state.active_npc_actions = set()

        hints: List[GoalHint] = []
        current_turn = game_state.turn_count

        # Get set of NPCs already with pending actions
        active_npcs: Set[str] = game_state.active_npc_actions

        # Mutual exclusion: if any authority NPC is already active, block all others
        authority_already_active = any(
            _get_value(self.world.npc_templates.get(npc_id), 'initiative_style', '') == 'authority'
            for npc_id in active_npcs
        )

        for npc_id, npc_def in self.world.npc_templates.items():
            # Skip if NPC already has pending action
            if npc_id in active_npcs:
                continue

            # Skip reactive NPCs - they don't generate hints
            initiative_style = _get_value(npc_def, 'initiative_style', 'reactive')
            if initiative_style == 'reactive':
                continue

            # Authority limits
            if initiative_style == 'authority':
                # Mutual exclusion: another authority is already active
                if authority_already_active:
                    logger.debug("[GoalEvaluator] Authority %s skipped: another authority already active", npc_id)
                    continue
                # Global cooldown between any two authority appearances
                if current_turn - self._last_authority_turn < self.AUTHORITY_GLOBAL_COOLDOWN:
                    logger.debug(
                        "[GoalEvaluator] Authority %s skipped: global cooldown (%d/%d turns)",
                        npc_id, current_turn - self._last_authority_turn, self.AUTHORITY_GLOBAL_COOLDOWN,
                    )
                    continue
                # Session cap
                if self._authority_session_count >= self.AUTHORITY_SESSION_MAX:
                    logger.debug("[GoalEvaluator] Authority %s skipped: session cap reached (%d)", npc_id, self.AUTHORITY_SESSION_MAX)
                    continue

            # Check goal templates
            goal_templates = _get_value(npc_def, 'goal_templates', [])
            if not goal_templates:
                continue

            for goal in goal_templates:
                hint = self._evaluate_single_goal(
                    npc_id, npc_def, goal, game_state, current_turn
                )
                if hint:
                    hints.append(hint)

        if not hints:
            return None

        # Select highest urgency hint
        best = max(hints, key=lambda h: h.urgency)

        # Mark this NPC as having pending action
        if not hasattr(game_state, 'active_npc_actions') or game_state.active_npc_actions is None:
            game_state.active_npc_actions = set()
        game_state.active_npc_actions.add(best.npc_id)

        # Update authority tracking
        if best.initiative_style == 'authority':
            self._last_authority_turn = current_turn
            self._authority_session_count += 1
            logger.info(
                "[GoalEvaluator] Authority appearance %d/%d for %s (next allowed at turn %d)",
                self._authority_session_count, self.AUTHORITY_SESSION_MAX,
                best.npc_id, current_turn + self.AUTHORITY_GLOBAL_COOLDOWN,
            )

        # Set cooldown for this goal (cooldown is stored in the goal template, not in hint)
        # The cooldown was already calculated in _evaluate_single_goal via _check_conditions
        # which returns cooldown_expiry including cooldown_turns
        # Here we just ensure it's set if not already
        if (best.npc_id, best.goal_id) not in self._cooldowns:
            self._cooldowns[(best.npc_id, best.goal_id)] = current_turn + 5

        logger.info(
            "[GoalEvaluator] Selected hint: %s (%s, urgency=%.2f)",
            best.npc_display_name, best.goal_id, best.urgency
        )
        return best
    
    def _evaluate_single_goal(
        self,
        npc_id: str,
        npc_def,
        goal,
        game_state: "GameState",
        current_turn: int
    ) -> Optional[GoalHint]:
        """Evaluate a single goal template."""
        goal_id = _get_value(goal, 'id', '') or str(id(goal))
        
        # Check cooldown
        cooldown_key = (npc_id, goal_id)
        if cooldown_key in self._cooldowns:
            if current_turn < self._cooldowns[cooldown_key]:
                return None
        
        # Check completion flag - if set, goal is already done
        completion_flag = _get_value(goal, 'completion_flag', '')
        if completion_flag and game_state.flags.get(completion_flag):
            return None
        
        # Check conditions
        conditions = _get_value(goal, 'conditions', {})
        if not self._check_conditions(conditions, game_state, npc_def):
            return None
        
        # Goal is active - create hint
        initiative_style = _get_value(npc_def, 'initiative_style', 'friendly')
        
        # Get display text
        narrative_hint = _get_value(goal, 'narrative_hint', '')
        if not narrative_hint:
            narrative_hint = _get_value(goal, 'goal', '')
        
        # Format with NPC name and active companion
        npc_name = _get_value(npc_def, 'name', npc_id)
        active_companion = getattr(game_state, 'active_companion', '') or ''
        # Resolve active_companion display name via world (available on evaluator)
        companion_name = active_companion
        if self.world:
            comp = self.world.companions.get(active_companion)
            if comp:
                companion_name = getattr(comp, 'name', active_companion)

        def _fmt(s: str) -> str:
            return (s
                    .replace('{npc_display_name}', npc_name)
                    .replace('{active_companion}', companion_name))

        goal_text = _fmt(narrative_hint)
        secret_subject = _fmt(_get_value(goal, 'secret_subject', '') or '')
        
        # Get location/time for UI
        location_display = self._get_location_display(npc_def, game_state)
        time_display = self._get_time_display(goal, game_state)
        
        # secret_subject already resolved above via _fmt(); fallback if empty
        if initiative_style == 'secret_keeper' and not secret_subject:
            secret_subject = "Sa qualcosa di interessante"
        
        # Calculate urgency (authority gets boosted)
        urgency_start = _get_value(goal, 'urgency_start', 0.5)
        if initiative_style == 'authority':
            urgency = 1.0  # Authority always max priority
        else:
            urgency = urgency_start
        
        return GoalHint(
            npc_id=npc_id,
            npc_display_name=npc_name,
            goal_text=goal_text,
            urgency=urgency,
            goal_type=_get_value(goal, 'goal_type', 'social'),
            goal_id=goal_id,
            initiative_style=initiative_style,
            location_display=location_display,
            time_display=time_display,
            secret_subject=secret_subject,
            completion_flag=completion_flag,
        )
    
    def _check_conditions(
        self, 
        conditions: dict, 
        game_state: "GameState",
        npc_def
    ) -> bool:
        """Check if all conditions are met."""
        if not conditions:
            return True
        
        # Check random_chance
        random_chance = conditions.get('random_chance', 0.0)
        if random_chance > 0:
            if random.random() > random_chance:
                return False
        
        # Check time
        allowed_times = conditions.get('time', [])
        if allowed_times:
            current_time = game_state.time_of_day
            time_str = current_time.value if hasattr(current_time, 'value') else str(current_time)
            if time_str not in allowed_times:
                return False
        
        # Check flags
        required_flag = conditions.get('flag', '')
        if required_flag:
            if not game_state.flags.get(required_flag):
                return False
        
        # Check flag_not (flag must NOT be set)
        forbidden_flags = conditions.get('flag_not', [])
        if isinstance(forbidden_flags, str):
            forbidden_flags = [forbidden_flags]
        for flag in forbidden_flags:
            if game_state.flags.get(flag):
                return False
        
        # Check affinity (if specified)
        affinity_gte = conditions.get('affinity_gte')
        if affinity_gte is not None:
            companion = _get_value(npc_def, 'name', '')
            current_affinity = game_state.affinity.get(companion, 0)
            if current_affinity < affinity_gte:
                return False
        
        affinity_lt = conditions.get('affinity_lt')
        if affinity_lt is not None:
            companion = _get_value(npc_def, 'name', '')
            current_affinity = game_state.affinity.get(companion, 0)
            if current_affinity >= affinity_lt:
                return False
        
        return True
    
    def _get_location_display(self, npc_def, game_state: "GameState") -> str:
        """Get human-readable location for UI."""
        spawn_locs = getattr(npc_def, 'spawn_locations', [])
        if spawn_locs:
            # Try to get nice name from world locations
            loc_id = spawn_locs[0]
            if hasattr(self.world, 'locations') and loc_id in self.world.locations:
                loc = self.world.locations[loc_id]
                return getattr(loc, 'name', loc_id)
            return loc_id.replace('_', ' ').title()
        return "Da qualche parte"
    
    def _get_time_display(self, goal, game_state: "GameState") -> str:
        """Get human-readable time for UI."""
        conditions = getattr(goal, 'conditions', {})
        allowed_times = conditions.get('time', [])
        if allowed_times:
            return "/".join(allowed_times)
        return "Ora"
    
    def check_completions(self, game_state: "GameState") -> List[str]:
        """Check and remove completed actions.

        Two completion triggers:
        1. completion_flag set in game_state.flags  (e.g. after initiative turn)
        2. Player is currently at the NPC's spawn_location (pull channel visit)

        Returns list of resolved npc_ids.
        """
        if not hasattr(game_state, 'active_npc_actions'):
            return []

        resolved = []
        to_remove = []
        player_loc = getattr(game_state, 'current_location', None)

        for npc_id in game_state.active_npc_actions:
            npc_def = self.world.npc_templates.get(npc_id)
            if not npc_def:
                to_remove.append(npc_id)
                continue

            done = False
            for goal in _get_value(npc_def, 'goal_templates', []):
                completion_flag = _get_value(goal, 'completion_flag', '')

                # Trigger 1: flag already set (e.g. set by initiative turn)
                if completion_flag and game_state.flags.get(completion_flag):
                    done = True
                    break

                # Trigger 2: player visited the NPC's location (pull channel)
                spawn_locs = _get_value(npc_def, 'spawn_locations', [])
                if player_loc and spawn_locs and player_loc in spawn_locs:
                    # Auto-set the flag so future check sees it done
                    if completion_flag:
                        game_state.flags[str(completion_flag)] = True
                        logger.info(
                            "[GoalEvaluator] Location-based completion: %s visited %s → %s",
                            npc_id, player_loc, completion_flag,
                        )
                    done = True
                    break

            if done:
                resolved.append(npc_id)
                to_remove.append(npc_id)

        for npc_id in to_remove:
            if npc_id in game_state.active_npc_actions:
                game_state.active_npc_actions.remove(npc_id)

        return resolved
    
    def create_npc_action(self, hint: GoalHint) -> NpcAction:
        """Convert GoalHint to NpcAction for UI."""
        return NpcAction(
            goal_id=hint.goal_id,
            npc_id=hint.npc_id,
            npc_display_name=hint.npc_display_name,
            initiative_style=hint.initiative_style,
            location_display=hint.location_display,
            time_display=hint.time_display,
            secret_subject=hint.secret_subject,
            urgency=hint.urgency
        )
