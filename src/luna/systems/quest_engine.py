"""Luna RPG V5 - Quest Engine.

Improvements over V4:
- Typed condition evaluator (no eval())
- Priority-based activation (no ambiguous simultaneous activations)
- Mutex groups (mutually exclusive quests)
- pending_choice timeout (auto-decline after N turns)
- Stage timeout (max_turns per stage)
- Explicit QuestStatus.PENDING_CHOICE state
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from luna.core.models import (
    GameState,
    QuestCondition,
    QuestDefinition,
    QuestInstance,
    QuestStatus,
    WorldDefinition,
)

logger = logging.getLogger(__name__)

# Default turns before a pending_choice quest is auto-declined
_DEFAULT_CHOICE_TIMEOUT = 10


@dataclass
class QuestActivationResult:
    quest_id: str
    title: str
    requires_choice: bool = False
    narrative_context: str = ""
    hidden: bool = False


@dataclass
class QuestUpdateResult:
    quest_id: str
    stage_changed: bool = False
    old_stage: Optional[str] = None
    new_stage: Optional[str] = None
    quest_completed: bool = False
    quest_failed: bool = False
    timed_out: bool = False
    narrative_context: str = ""
    action_hints: list = None

    def __post_init__(self):
        if self.action_hints is None:
            self.action_hints = []


class ConditionEvaluator:
    """Evaluates QuestConditions against GameState.

    No eval(). All condition types are handled explicitly.
    """

    def evaluate(
        self,
        condition: QuestCondition,
        game_state: GameState,
        user_input: str = "",
    ) -> bool:
        try:
            return self._eval(condition, game_state, user_input)
        except Exception as e:
            logger.warning("Condition eval error (%s): %s", condition.type, e)
            return False

    def evaluate_all(
        self,
        conditions: List[QuestCondition],
        game_state: GameState,
        user_input: str = "",
    ) -> bool:
        return all(self.evaluate(c, game_state, user_input) for c in conditions)

    def _eval(self, c: QuestCondition, gs: GameState, user_input: str) -> bool:
        t = c.type

        if t == "affinity":
            target = c.target or gs.active_companion
            actual = gs.affinity.get(target, 0)
            return self._compare(actual, c.operator, self._int(c.value))

        if t == "location":
            actual = gs.current_location
            return self._compare(actual, c.operator, c.value)

        if t == "time":
            actual = gs.time_of_day.value if hasattr(gs.time_of_day, "value") else str(gs.time_of_day)
            return self._compare(actual, c.operator, str(c.value))

        if t == "flag":
            target = c.target or str(c.value)
            actual = gs.flags.get(target, False)
            if isinstance(c.value, bool):
                return bool(actual) == c.value
            return self._compare(actual, c.operator, c.value)

        if t == "turn_count":
            return self._compare(gs.turn_count, c.operator, self._int(c.value))

        if t == "inventory":
            return c.value in gs.player.inventory

        if t == "companion":
            return gs.active_companion == c.value

        if t == "quest_status":
            target_quest = c.target
            if not target_quest:
                return False
            if target_quest in gs.completed_quests:
                actual_status = QuestStatus.COMPLETED.value
            elif target_quest in gs.active_quests:
                actual_status = QuestStatus.ACTIVE.value
            else:
                actual_status = QuestStatus.NOT_STARTED.value
            return self._compare(actual_status, c.operator, str(c.value))

        if t == "action":
            pattern = c.pattern if hasattr(c, "pattern") and c.pattern else str(c.value)
            if not pattern:
                return False
            import re as _re
            player_input = gs.flags.get("_last_player_input", "")
            if player_input and _re.search(pattern, player_input, _re.IGNORECASE):
                return True
            narrative_text = gs.flags.get("_last_narrative_text", "")
            if narrative_text and _re.search(pattern, narrative_text, _re.IGNORECASE):
                return True
            return False

        if t == "player_action":
            pattern = c.pattern if hasattr(c, "pattern") and c.pattern else str(c.value)
            if not pattern:
                return False
            import re as _re
            player_input = gs.flags.get("_last_player_input", "")
            return bool(player_input and _re.search(pattern, player_input, _re.IGNORECASE))

        logger.warning("Unknown condition type: %s", t)
        return False

    def _compare(self, actual: Any, operator: str, expected: Any) -> bool:
        try:
            if operator == "eq":
                return actual == expected
            if operator == "not_eq":
                return actual != expected
            if operator == "gt":
                return float(actual) > float(expected)
            if operator == "lt":
                return float(actual) < float(expected)
            if operator == "gte":
                return float(actual) >= float(expected)
            if operator == "lte":
                return float(actual) <= float(expected)
            if operator == "contains":
                return str(expected).lower() in str(actual).lower()
        except (TypeError, ValueError):
            pass
        return False

    def _int(self, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class QuestEngine:
    """Quest lifecycle management.

    Responsibilities:
    - Evaluate activation conditions each turn
    - Manage stage transitions
    - Handle choice timeouts
    - Enforce mutex groups
    """

    def __init__(self, world: WorldDefinition, engine: Any = None) -> None:
        self.world    = world
        self._engine  = engine
        self._evaluator = ConditionEvaluator()
        # quest_id → QuestInstance (runtime state)
        self._instances: Dict[str, QuestInstance] = {}

    # -------------------------------------------------------------------------
    # Initialization from saved state
    # -------------------------------------------------------------------------

    def load_instances(self, instances: Dict[str, QuestInstance]) -> None:
        self._instances = instances

    def get_instance(self, quest_id: str) -> Optional[QuestInstance]:
        return self._instances.get(quest_id)

    def get_all_instances(self) -> Dict[str, QuestInstance]:
        return dict(self._instances)

    def get_all_states(self) -> list:
        """Alias per UI - restituisce lista di QuestInstance attive."""
        return list(self._instances.values())

    def activate_quest(
        self, quest_id: str, game_state: GameState
    ) -> Optional[QuestActivationResult]:
        """Manually activate a quest (UI/debug use). Bypasses activation conditions."""
        quest_def = self.world.quests.get(quest_id)
        if not quest_def:
            return None
        instance = self._instances.get(quest_id)
        if instance and instance.status == QuestStatus.ACTIVE:
            return None  # already active
        return self._activate_quest(quest_def, game_state)

    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Action executor
    # -------------------------------------------------------------------------

    def execute_actions(
        self,
        actions: List[Any],
        game_state: "GameState",
        engine: Any = None,
    ) -> List[str]:
        """Execute a list of QuestActions. Returns list of narrative hints."""
        hints = []
        for action in actions:
            try:
                hints += self._execute_action(action, game_state, engine)
            except Exception as e:
                logger.warning("[QuestEngine] Action failed: %s — %s", action, e)
        return hints

    def _execute_action(
        self,
        action: Any,
        game_state: "GameState",
        engine: Any,
    ) -> List[str]:
        act = action.action if hasattr(action, "action") else action.get("action", "")
        target = action.target if hasattr(action, "target") else action.get("target")
        value  = action.value  if hasattr(action, "value")  else action.get("value")
        key    = action.key    if hasattr(action, "key")    else action.get("key")
        outfit = action.outfit if hasattr(action, "outfit") else action.get("outfit")
        char   = action.character if hasattr(action, "character") else action.get("character")

        if act == "set_flag":
            game_state.flags[key or str(target)] = value if value is not None else True
            logger.debug("[QuestAction] set_flag %s = %s", key, value)

        elif act == "add_flag":
            existing = game_state.flags.get(key, [])
            if isinstance(existing, list):
                existing.append(value)
            game_state.flags[key] = existing

        elif act == "set_location":
            if target and target in (getattr(engine, "world", None) and engine.world.locations or {}):
                game_state.current_location = target
                logger.info("[QuestAction] set_location → %s", target)
                return [f"[Scene moves to: {target}]"]

        elif act == "set_outfit":
            companion = char or game_state.active_companion
            outfit_name = outfit or str(value)
            comp_def = engine.world.companions.get(companion) if engine else None
            if comp_def and engine and engine.outfit_engine:
                engine.outfit_engine.apply_schedule_outfit(
                    outfit_name, comp_def, game_state, game_state.turn_count
                )
                logger.info("[QuestAction] set_outfit %s → %s", companion, outfit_name)
                return [f"[{companion} changes to {outfit_name} outfit]"]

        elif act == "set_emotional_state":
            companion = char or game_state.active_companion
            state_value = str(value)
            # Primary: update npc_states (read by narrative.py _companion_context)
            from luna.core.models import NPCState
            if companion not in game_state.npc_states:
                game_state.npc_states[companion] = NPCState(name=companion)
            npc = game_state.npc_states[companion]
            game_state.npc_states[companion] = npc.model_copy(
                update={"emotional_state": state_value}
            )
            # Backward compat: keep flag for any legacy readers
            game_state.flags[f"emotional_state_{companion}"] = state_value
            # Mark as quest-forced so EmotionalStateEngine respects TTL
            game_state.flags[f"emotional_state_forced_{companion}"] = True
            game_state.flags[f"emotional_state_forced_turn_{companion}"] = game_state.turn_count
            logger.info("[QuestAction] set_emotional_state %s → %s (quest-forced)", companion, state_value)

        elif act == "change_affinity":
            companion_raw = char or game_state.active_companion
            # Normalize to canonical key (case-insensitive match against world companions)
            companion = companion_raw
            if engine:
                companions = getattr(getattr(engine, "world", None), "companions", {})
                lower = companion_raw.lower().strip()
                companion = next((k for k in companions if k.lower() == lower), companion_raw)
            delta = int(value) if value else 0
            current = game_state.affinity.get(companion, 0)
            game_state.affinity[companion] = max(0, min(100, current + delta))
            logger.info("[QuestAction] change_affinity %s %+d", companion, delta)

        elif act == "start_quest":
            qid = key or str(value)
            quest_def = self.world.quests.get(qid)
            if quest_def and qid not in game_state.active_quests:
                self._activate_quest(quest_def, game_state)

        elif act == "complete_quest":
            qid = key or str(value)
            if qid in game_state.active_quests:
                game_state.active_quests.remove(qid)
            if qid not in game_state.completed_quests:
                game_state.completed_quests.append(qid)

        elif act == "set_secondary_npc":
            npc_id = str(value or char or "")
            if npc_id:
                game_state.flags["_secondary_npc"] = npc_id
                game_state.flags["_scene_mode"] = "multi_char"
                logger.info("[QuestAction] set_secondary_npc → %s", npc_id)

        elif act == "clear_secondary_npc":
            game_state.flags.pop("_secondary_npc", None)
            game_state.flags["_scene_mode"] = "single_char"
            logger.info("[QuestAction] clear_secondary_npc")

        elif act == "time_advance":
            try:
                from luna.systems.phase_clock import PhaseAdvanceReason
                phase_clock = getattr(engine, "phase_clock", None) if engine else None
                if phase_clock:
                    event = phase_clock.force_advance(
                        PhaseAdvanceReason.FORCED, game_state.turn_count
                    )
                    if event:
                        game_state.time_of_day = event.new_phase
                        logger.info("[QuestAction] time_advance: %s -> %s", event.old_phase, event.new_phase)
                        return [event.message]
            except Exception as e:
                logger.warning("[QuestAction] time_advance failed: %s", e)

        return []

    # Per-turn update
    # -------------------------------------------------------------------------

    def update(
        self,
        game_state: GameState,
        user_input: str = "",
    ) -> Tuple[str, List[QuestActivationResult], List[QuestUpdateResult], str]:
        """Main per-turn entry point.

        Returns:
            (narrative_context, new_activations, stage_updates)

        narrative_context is a two-element tuple internally built by _build_context:
            (quest_narrative: str, companion_situation_override: str)
        The orchestrator unpacks companion_situation_override to replace activity_context
        when an active quest stage defines a companion_situation.
        """
        new_activations: List[QuestActivationResult] = []
        stage_updates: List[QuestUpdateResult] = []

        # 1. Check for choice timeouts
        self._check_choice_timeouts(game_state, stage_updates)

        # 2. Progress active quests
        for quest_id in list(game_state.active_quests):
            result = self._update_active_quest(quest_id, game_state, user_input)
            if result:
                stage_updates.append(result)

        # 3. Check new activations (sorted by priority)
        eligible = self._find_eligible_quests(game_state, user_input)
        for quest_def in eligible:
            result = self._activate_quest(quest_def, game_state)
            if result:
                new_activations.append(result)

        # 4. Build narrative context + companion situation override
        narrative_ctx, situation_override = self._build_context(game_state)

        return narrative_ctx, new_activations, stage_updates, situation_override

    # -------------------------------------------------------------------------
    # Choice resolution
    # -------------------------------------------------------------------------

    def resolve_choice(
        self,
        quest_id: str,
        accepted: bool,
        game_state: GameState,
    ) -> Optional[str]:
        """Player responded to a choice quest. Returns narrative or None."""
        instance = self._instances.get(quest_id)
        if not instance or instance.status != QuestStatus.PENDING_CHOICE:
            return None

        quest_def = self.world.quests.get(quest_id)
        if not quest_def:
            return None

        if accepted:
            instance.status = QuestStatus.ACTIVE
            instance.pending_since_turn = None
            instance.started_at = game_state.turn_count
            instance.current_stage_id = quest_def.start_stage
            instance.stage_entered_at = game_state.turn_count
            if quest_id not in game_state.active_quests:
                game_state.active_quests.append(quest_id)
            logger.info("Quest '%s' accepted", quest_id)
            return f"✅ Hai accettato: {quest_def.title}"
        else:
            instance.status = QuestStatus.NOT_STARTED
            instance.pending_since_turn = None
            logger.info("Quest '%s' declined", quest_id)
            return f"❌ Hai rifiutato: {quest_def.title}"

    # -------------------------------------------------------------------------
    # Context for LLM prompt
    # -------------------------------------------------------------------------

    def _build_context(self, game_state: GameState) -> Tuple[str, str]:
        """Build narrative context and companion situation override for active quests.

        Returns:
            (narrative_context, companion_situation_override)

        narrative_context   — injected as quest_context into the LLM prompt.
        companion_situation_override — replaces activity_context when set, making the
            companion self-aware of their quest-driven role (e.g. gym substitute).
            Only the first active quest with companion_situation wins.
        """
        parts: List[str] = []
        situation_override = ""
        for quest_id in game_state.active_quests:
            instance = self._instances.get(quest_id)
            quest_def = self.world.quests.get(quest_id)
            if not instance or not quest_def:
                continue
            stage_id = instance.current_stage_id or quest_def.start_stage
            stage = quest_def.stages.get(stage_id)
            if not stage:
                continue
            if stage.narrative_prompt:
                parts.append(f"[Quest: {quest_def.title}] {stage.narrative_prompt}")
            if stage.companion_situation and not situation_override:
                situation_override = stage.companion_situation
            if stage.llm_context:
                ctx = stage.llm_context
                if ctx.get("scene"):
                    parts.append(f"=== SCENE INSTRUCTIONS ===\n{ctx['scene']}")
                if ctx.get("tone"):
                    parts.append(f"[Scene tone: {ctx['tone']}]")
                if ctx.get("pacing"):
                    parts.append(f"[Pacing: {ctx['pacing']}]")
                if ctx.get("explicit_permission"):
                    parts.append(f"[Explicit content permitted: {ctx['explicit_permission']}]")
                if ctx.get("voyeur_mechanic"):
                    parts.append(f"[Voyeur mechanic: {ctx['voyeur_mechanic']}]")
                if ctx.get("dual_character"):
                    parts.append(f"[Dual character scene: {ctx['dual_character']}]")
                if ctx.get("outfit_note"):
                    parts.append(f"[Outfit/image note: {ctx['outfit_note']}]")
        return "\n".join(parts), situation_override

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _find_eligible_quests(
        self, game_state: GameState, user_input: str
    ) -> List[QuestDefinition]:
        """Find quests eligible for activation, sorted by priority."""
        # One quest at a time: don't activate new quests while one is active
        if game_state.active_quests:
            return []

        eligible = []
        active_mutex_groups = self._get_active_mutex_groups(game_state)

        for quest_id, quest_def in self.world.quests.items():
            instance = self._instances.get(quest_id)
            status = instance.status if instance else QuestStatus.NOT_STARTED

            if status not in (QuestStatus.NOT_STARTED,):
                continue
            if quest_def.activation_type == "manual":
                continue
            if quest_def.mutex_group and quest_def.mutex_group in active_mutex_groups:
                continue
            if not self._required_quests_done(quest_def, game_state):
                continue
            if self._evaluator.evaluate_all(quest_def.activation_conditions, game_state, user_input):
                eligible.append(quest_def)

        eligible.sort(key=lambda q: q.priority)
        return eligible

    def _activate_quest(
        self, quest_def: QuestDefinition, game_state: GameState
    ) -> Optional[QuestActivationResult]:
        quest_id = quest_def.id

        if quest_def.requires_player_choice:
            instance = QuestInstance(
                quest_id=quest_id,
                status=QuestStatus.PENDING_CHOICE,
                pending_since_turn=game_state.turn_count,
            )
            self._instances[quest_id] = instance
            logger.info("Quest '%s' pending player choice", quest_id)
            return QuestActivationResult(
                quest_id=quest_id,
                title=quest_def.title,
                requires_choice=True,
                hidden=quest_def.hidden,
            )
        else:
            instance = QuestInstance(
                quest_id=quest_id,
                status=QuestStatus.ACTIVE,
                current_stage_id=quest_def.start_stage,
                started_at=game_state.turn_count,
                stage_entered_at=game_state.turn_count,
            )
            self._instances[quest_id] = instance
            if quest_id not in game_state.active_quests:
                game_state.active_quests.append(quest_id)
            logger.info("Quest '%s' activated (auto)", quest_id)
            # Execute on_enter for start stage
            start_stage = quest_def.stages.get(quest_def.start_stage)
            if start_stage and start_stage.on_enter:
                self.execute_actions(start_stage.on_enter, game_state, self._engine)
            return QuestActivationResult(
                quest_id=quest_id,
                title=quest_def.title,
                requires_choice=False,
                hidden=quest_def.hidden,
            )

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

        # Check stage timeout
        if stage.max_turns is not None:
            turns_in_stage = game_state.turn_count - instance.stage_entered_at
            if turns_in_stage >= stage.max_turns:
                logger.info("Quest '%s' stage '%s' timed out", quest_id, stage_id)
                return self._fail_quest(quest_id, instance, quest_def, stage_id, game_state, timed_out=True)

        # Check fail conditions
        if stage.fail_conditions and self._evaluator.evaluate_all(
            stage.fail_conditions, game_state, user_input
        ):
            logger.info("Quest '%s' stage '%s' fail conditions met", quest_id, stage_id)
            return self._fail_quest(quest_id, instance, quest_def, stage_id, game_state)

        # Check exit conditions
        if self._evaluator.evaluate_all(stage.exit_conditions, game_state, user_input):
            return self._advance_stage(quest_id, instance, quest_def, stage_id, game_state)

        return None

    def _advance_stage(
        self,
        quest_id: str,
        instance: QuestInstance,
        quest_def: QuestDefinition,
        current_stage_id: str,
        game_state: GameState,
    ) -> QuestUpdateResult:
        stage = quest_def.stages.get(current_stage_id)
        stages = list(quest_def.stages.keys())
        current_idx = stages.index(current_stage_id) if current_stage_id in stages else -1

        if current_idx == -1 or current_idx >= len(stages) - 1:
            # Complete quest
            instance.status = QuestStatus.COMPLETED
            instance.completed_at = game_state.turn_count
            if quest_id in game_state.active_quests:
                game_state.active_quests.remove(quest_id)
            if quest_id not in game_state.completed_quests:
                game_state.completed_quests.append(quest_id)
            self._apply_rewards(quest_def, game_state)
            if quest_def.on_complete:
                self.execute_actions(quest_def.on_complete, game_state, self._engine)
                logger.info("[QuestEngine] on_complete for '%s': %d actions", quest_id, len(quest_def.on_complete))
            logger.info("Quest '%s' completed", quest_id)
            return QuestUpdateResult(
                quest_id=quest_id,
                quest_completed=True,
                old_stage=current_stage_id,
            )
        else:
            next_stage_id = stages[current_idx + 1]
            instance.current_stage_id = next_stage_id
            instance.stage_entered_at = game_state.turn_count
            logger.info("Quest '%s': %s → %s", quest_id, current_stage_id, next_stage_id)
            # Execute on_enter actions for new stage
            next_stage = quest_def.stages.get(next_stage_id)
            action_hints = []
            if next_stage and next_stage.on_enter:
                action_hints = self.execute_actions(
                    next_stage.on_enter, game_state, self._engine
                )
                logger.info("[QuestEngine] on_enter for stage '%s': %d actions", 
                            next_stage_id, len(next_stage.on_enter))
            return QuestUpdateResult(
                quest_id=quest_id,
                stage_changed=True,
                old_stage=current_stage_id,
                new_stage=next_stage_id,
                action_hints=action_hints,
            )

    def _fail_quest(
        self,
        quest_id: str,
        instance: QuestInstance,
        quest_def: QuestDefinition,
        current_stage_id: str,
        game_state: GameState,
        timed_out: bool = False,
    ) -> QuestUpdateResult:
        """Fail a quest: execute on_fail actions, update state."""
        instance.status = QuestStatus.FAILED
        if quest_id in game_state.active_quests:
            game_state.active_quests.remove(quest_id)
        if quest_id not in game_state.failed_quests:
            game_state.failed_quests.append(quest_id)

        # Execute on_fail actions for the current stage
        stage = quest_def.stages.get(current_stage_id)
        action_hints = []
        if stage and stage.on_fail:
            action_hints = self.execute_actions(stage.on_fail, game_state, self._engine)
            logger.info(
                "[QuestEngine] on_fail for stage '%s': %d actions",
                current_stage_id, len(stage.on_fail),
            )

        logger.info("Quest '%s' failed (stage: %s, timeout: %s)", quest_id, current_stage_id, timed_out)
        return QuestUpdateResult(
            quest_id=quest_id,
            quest_failed=True,
            timed_out=timed_out,
            old_stage=current_stage_id,
            action_hints=action_hints,
        )

    def _check_choice_timeouts(
        self, game_state: GameState, results: List[QuestUpdateResult]
    ) -> None:
        for quest_id, instance in self._instances.items():
            if instance.status != QuestStatus.PENDING_CHOICE:
                continue
            quest_def = self.world.quests.get(quest_id)
            if not quest_def:
                continue
            timeout = quest_def.choice_timeout_turns or _DEFAULT_CHOICE_TIMEOUT
            if instance.pending_since_turn is not None:
                turns_pending = game_state.turn_count - instance.pending_since_turn
                if turns_pending >= timeout:
                    instance.status = QuestStatus.NOT_STARTED
                    instance.pending_since_turn = None
                    logger.info("Quest '%s' choice timed out after %d turns", quest_id, turns_pending)
                    results.append(QuestUpdateResult(
                        quest_id=quest_id,
                        quest_failed=True,
                        timed_out=True,
                    ))

    def _apply_rewards(self, quest_def: QuestDefinition, game_state: GameState) -> None:
        rewards = quest_def.rewards
        for companion, delta in rewards.affinity.items():
            current = game_state.affinity.get(companion, 0)
            game_state.affinity[companion] = max(0, min(100, current + delta))
        for item in rewards.items:
            if item not in game_state.player.inventory:
                game_state.player.inventory.append(item)
        for flag, value in rewards.flags.items():
            game_state.flags[flag] = value

    def _get_active_mutex_groups(self, game_state: GameState) -> set:
        groups = set()
        for quest_id in game_state.active_quests:
            quest_def = self.world.quests.get(quest_id)
            if quest_def and quest_def.mutex_group:
                groups.add(quest_def.mutex_group)
        return groups

    def _required_quests_done(self, quest_def: QuestDefinition, game_state: GameState) -> bool:
        terminated = set(game_state.completed_quests) | set(game_state.failed_quests)
        return all(q in terminated for q in quest_def.required_quests)
