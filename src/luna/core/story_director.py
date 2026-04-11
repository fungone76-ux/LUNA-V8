"""Luna RPG V5 - Story Director.

Controls narrative structure. Evaluates beat triggers WITHOUT eval().
All trigger conditions use the same ConditionEvaluator as QuestEngine.

Beat trigger syntax supported (safe, no eval):
  "turn >= 10"
  "affinity_luna >= 50"
  "location == school_library"
  "flag:luna_attracted == true"
  "turn >= 10 AND affinity_luna >= 30"
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from luna.core.models import (
    BeatExecution, GameState, NarrativeArc, StoryBeat,
)

logger = logging.getLogger(__name__)


class BeatConditionEvaluator:
    """Evaluates StoryBeat trigger strings without eval().

    Supports: turn, affinity_<name>, location, time, flag:<key>
    Operators: >= > <= < == !=
    Connectors: AND (all must be true)
    """

    def evaluate(self, trigger: str, game_state: GameState) -> bool:
        if not trigger or not trigger.strip():
            return True
        try:
            # Split on AND
            parts = [p.strip() for p in re.split(r'\bAND\b', trigger, flags=re.IGNORECASE)]
            return all(self._eval_single(p, game_state) for p in parts)
        except Exception as e:
            logger.warning("Beat trigger eval error '%s': %s", trigger, e)
            return False

    def _eval_single(self, expr: str, gs: GameState) -> bool:
        # Supported operators
        for op_str, op_fn in [
            (">=", lambda a, b: float(a) >= float(b)),
            ("<=", lambda a, b: float(a) <= float(b)),
            (">",  lambda a, b: float(a) > float(b)),
            ("<",  lambda a, b: float(a) < float(b)),
            ("==", lambda a, b: str(a).lower() == str(b).lower()),
            ("!=", lambda a, b: str(a).lower() != str(b).lower()),
        ]:
            if op_str in expr:
                left, right = expr.split(op_str, 1)
                left = left.strip()
                right = right.strip()
                actual = self._resolve(left, gs)
                return op_fn(actual, right)
        # Boolean flag check
        actual = self._resolve(expr.strip(), gs)
        return bool(actual)

    def _resolve(self, key: str, gs: GameState) -> Any:
        if key == "turn" or key == "turn_count":
            return gs.turn_count
        if key == "location":
            return gs.current_location
        if key == "time":
            return gs.time_of_day.value if hasattr(gs.time_of_day, "value") else str(gs.time_of_day)
        if key == "companion":
            return gs.active_companion
        if key.startswith("affinity_"):
            name = key[len("affinity_"):]
            return gs.affinity.get(name, 0)
        if key.startswith("flag:"):
            flag_name = key[len("flag:"):]
            return gs.flags.get(flag_name, False)
        # Try as a flag name directly
        return gs.flags.get(key, 0)


class StoryDirector:
    """Controls narrative beats. Python controls WHEN, AI controls HOW."""

    def __init__(self, narrative_arc: NarrativeArc) -> None:
        self.arc = narrative_arc
        self.beat_history: List[BeatExecution] = []
        self._completed_beats: set = set()
        self._evaluator = BeatConditionEvaluator()

    def get_active_instruction(self, game_state: GameState) -> Optional[Tuple[StoryBeat, str]]:
        """Return (beat, instruction) if a beat should trigger this turn, else None."""
        candidates = []
        for beat in self.arc.beats:
            if beat.once and beat.id in self._completed_beats:
                continue
            if self._evaluator.evaluate(beat.trigger, game_state):
                candidates.append(beat)
        if not candidates:
            return None
        # Sort by priority (lower = higher priority)
        candidates.sort(key=lambda b: b.priority)
        beat = candidates[0]
        instruction = self._build_instruction(beat, game_state)
        return beat, instruction

    def validate_beat_execution(
        self, beat: StoryBeat, llm_response: str
    ) -> Tuple[bool, float, List[str]]:
        """Check if LLM correctly executed the beat."""
        missing = []
        response_lower = llm_response.lower()
        for element in beat.required_elements:
            if element.lower() not in response_lower:
                missing.append(element)
        quality = 1.0 if not beat.required_elements else (
            (len(beat.required_elements) - len(missing)) / len(beat.required_elements)
        )
        return len(missing) == 0, quality, missing

    def mark_completed(self, beat: StoryBeat, narrative_text: str, quality: float = 1.0) -> None:
        execution = BeatExecution(
            beat_id=beat.id,
            triggered_at=0,
            completed=True,
            execution_quality=quality,
            narrative_snapshot=narrative_text[:500],
        )
        self.beat_history.append(execution)
        if beat.once:
            self._completed_beats.add(beat.id)
        logger.info("Beat '%s' marked complete (quality=%.2f)", beat.id, quality)

    def apply_consequences(self, beat: StoryBeat, game_state: GameState) -> None:
        if not beat.consequence:
            return
        try:
            for part in beat.consequence.split(","):
                part = part.strip()
                if "affinity" in part:
                    m = re.search(r'([\w]+)\s*([\+\-])=\s*(\d+)', part)
                    if m:
                        char, op, amount = m.group(1), m.group(2), int(m.group(3))
                        if op == "-":
                            amount = -amount
                        if char in game_state.affinity:
                            game_state.affinity[char] = max(0, min(100, game_state.affinity[char] + amount))
                elif "flag:" in part:
                    m = re.search(r'flag:(\w+)\s*=\s*(\w+)', part)
                    if m:
                        game_state.flags[m.group(1)] = m.group(2).lower() == "true"
        except Exception as e:
            logger.warning("Error applying beat consequences: %s", e)

    def get_narrative_context(self) -> str:
        """Context for regular turns (no active beat)."""
        if not self.arc.premise:
            return ""
        parts = ["=== CONTESTO NARRATIVO ===", "", "PREMESSA:", self.arc.premise]
        if self.arc.themes:
            parts.extend(["", "TEMI:"] + [f"  - {t}" for t in self.arc.themes])
        if self.arc.hard_limits:
            parts.extend(["", "VINCOLI ASSOLUTI:"] + [f"  ✗ {l}" for l in self.arc.hard_limits])
        if self.beat_history:
            parts.extend(["", "EVENTI GIÀ AVVENUTI:"] + [f"  ✓ {e.beat_id}" for e in self.beat_history[-3:]])
        parts.append("\n===========================")
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "beat_history": [b.model_dump() for b in self.beat_history],
            "completed_beats": list(self._completed_beats),
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        self.beat_history = [BeatExecution(**b) for b in data.get("beat_history", [])]
        self._completed_beats = set(data.get("completed_beats", []))

    def _build_instruction(self, beat: StoryBeat, game_state: GameState) -> str:
        parts = [
            "=== MOMENTO NARRATIVO OBBLIGATORIO ===",
            "",
            "Devi narrare ESATTAMENTE questo evento:",
            beat.description,
            "",
        ]
        if beat.tone:
            parts.extend([f"TONO RICHIESTO: {beat.tone}", ""])
        if beat.required_elements:
            parts.append("ELEMENTI OBBLIGATORI:")
            for el in beat.required_elements:
                parts.append(f"  - {el}")
            parts.append("")
        parts.extend([
            "CONTESTO:",
            f"  Turno: {game_state.turn_count}",
            f"  Location: {game_state.current_location}",
            f"  Companion: {game_state.active_companion}",
            f"  Affinità: {game_state.affinity.get(game_state.active_companion, 0)}",
            "",
            "ISTRUZIONE: Includi TUTTI gli elementi obbligatori.",
            "======================================",
        ])
        return "\n".join(parts)
