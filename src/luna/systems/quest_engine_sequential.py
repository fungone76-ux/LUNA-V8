"""Sequential Quest Engine — extends QuestEngine with v8 rules.

Changes over base QuestEngine:
- One quest active at a time (including hidden quests)
- _required_quests_done() checks completed_quests UNION failed_quests
- fail_conditions evaluated each turn before exit_conditions
- _fail_quest() executes on_fail actions and populates failed_quests
- Stage timeout aligned with failed_quests
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from luna.core.models import GameState, QuestStatus
from luna.systems.quest_engine import QuestEngine, QuestUpdateResult

from typing import NamedTuple


class QuestJournalSnapshot(NamedTuple):
    """Minimal quest data for the Journal UI widget."""
    active_quest_title: str  # "" if no active quest
    active_stage_title: str  # title of current stage
    active_stage_hint: str   # player_hint of current stage
    next_quest_title: str    # title of next quest to unlock
    is_hidden: bool          # if True, quest title should not be shown in UI

if TYPE_CHECKING:
    from luna.core.models import QuestDefinition, QuestInstance

logger = logging.getLogger(__name__)


class SequentialQuestEngine(QuestEngine):
    """QuestEngine with sequential (one-at-a-time) quest rules."""

    # -------------------------------------------------------------------------
    # One quest at a time
    # -------------------------------------------------------------------------

    def _find_eligible_quests(
        self, game_state: GameState, user_input: str
    ) -> list:
        """Block new activations while any quest is active."""
        if game_state.active_quests:
            return []
        return super()._find_eligible_quests(game_state, user_input)

    # -------------------------------------------------------------------------
    # Unlock on COMPLETED or FAILED
    # -------------------------------------------------------------------------

    def _required_quests_done(
        self, quest_def: "QuestDefinition", game_state: GameState
    ) -> bool:
        terminated = set(game_state.completed_quests) | set(game_state.failed_quests)
        return all(q in terminated for q in quest_def.required_quests)

    # -------------------------------------------------------------------------
    # fail_conditions evaluated each turn
    # -------------------------------------------------------------------------

    def _update_active_quest(
        self, quest_id: str, game_state: GameState, user_input: str
    ) -> Optional[QuestUpdateResult]:
        instance = self._instances.get(quest_id)
        quest_def = self.world.quests.get(quest_id)
        if not instance or not quest_def or instance.status != QuestStatus.ACTIVE:
            return None

        stage_id = instance.current_stage_id or quest_def.start_stage
        stage = quest_def.stages.get(stage_id)
        if not stage:
            return None

        # 1. Stage timeout → FAILED
        if stage.max_turns is not None:
            turns_in_stage = game_state.turn_count - instance.stage_entered_at
            if turns_in_stage >= stage.max_turns:
                return self._fail_quest(quest_id, instance, quest_def, stage_id, game_state, timed_out=True)

        # 2. fail_conditions → FAILED (new)
        if stage.fail_conditions:
            if self._evaluator.evaluate_all(stage.fail_conditions, game_state, user_input):
                logger.info(
                    "[SequentialQuestEngine] Quest '%s' stage '%s' failed via fail_conditions",
                    quest_id, stage_id,
                )
                return self._fail_quest(quest_id, instance, quest_def, stage_id, game_state)

        # 3. Location gate: block exit_conditions if player not at required location
        if stage.location and game_state.current_location != stage.location:
            return None

        # 4. exit_conditions → advance stage or COMPLETED
        if self._evaluator.evaluate_all(stage.exit_conditions, game_state, user_input):
            return self._advance_stage(quest_id, instance, quest_def, stage_id, game_state)

        return None

    # -------------------------------------------------------------------------
    # _fail_quest
    # -------------------------------------------------------------------------

    def get_journal_snapshot(self, game_state: GameState) -> QuestJournalSnapshot:
        """Return minimal quest data for the Journal UI widget."""
        active_quest_title = ""
        active_stage_title = ""
        active_stage_hint = ""
        next_quest_title = ""
        is_hidden = False

        if game_state.active_quests:
            quest_id = game_state.active_quests[0]
            quest_def = self.world.quests.get(quest_id)
            instance = self._instances.get(quest_id)

            if quest_def and instance:
                active_quest_title = quest_def.title
                is_hidden = quest_def.hidden
                stage_id = instance.current_stage_id or quest_def.start_stage
                stage = quest_def.stages.get(stage_id)
                if stage:
                    active_stage_title = stage.title
                    active_stage_hint = stage.player_hint

                # Find next quest whose required_quests contains this one
                # M2: Sort by priority to respect quest ordering
                sorted_quests = sorted(
                    self.world.quests.items(),
                    key=lambda item: getattr(item[1], 'priority', 5)
                )
                for qid, qdef in sorted_quests:
                    if quest_id in qdef.required_quests:
                        next_quest_title = qdef.title
                        break

        return QuestJournalSnapshot(
            active_quest_title=active_quest_title,
            active_stage_title=active_stage_title,
            active_stage_hint=active_stage_hint,
            next_quest_title=next_quest_title,
            is_hidden=is_hidden,
        )

    def _fail_quest(
        self,
        quest_id: str,
        instance: "QuestInstance",
        quest_def: "QuestDefinition",
        stage_id: str,
        game_state: GameState,
        timed_out: bool = False,
    ) -> QuestUpdateResult:
        stage = quest_def.stages.get(stage_id)

        action_hints: List[str] = []
        if stage and stage.on_fail:
            action_hints = self.execute_actions(stage.on_fail, game_state, self._engine)

        instance.status = QuestStatus.FAILED
        if quest_id in game_state.active_quests:
            game_state.active_quests.remove(quest_id)
        if quest_id not in game_state.failed_quests:
            game_state.failed_quests.append(quest_id)

        logger.info(
            "[SequentialQuestEngine] Quest '%s' FAILED at stage '%s' (timeout: %s)",
            quest_id, stage_id, timed_out,
        )

        return QuestUpdateResult(
            quest_id=quest_id,
            quest_failed=True,
            timed_out=timed_out,
            old_stage=stage_id,
            action_hints=action_hints,
        )
