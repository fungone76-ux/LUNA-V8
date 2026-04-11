"""Luna RPG v7 — Director Agent.

Makes a LIGHT LLM call to decide WHAT should happen in the scene.
Separates narrative DECISIONS from narrative WRITING.

Called only when:
- Scene has 3+ NPCs
- NPC initiative is high/critical urgency
- Narrative pressure >= 0.7

Uses fast/cheap model, max 200 tokens.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from luna.core.models import GameState
    from luna.systems.world_simulator import TurnDirective

logger = logging.getLogger(__name__)


@dataclass
class SceneBeat:
    """A single beat in the scene direction."""
    actor: str              # NPC name
    action: str = ""        # what they do physically
    dialogue_intent: str = ""  # what they want to say (not exact words)
    is_reaction: bool = False  # is this a reaction to something else?


@dataclass
class SceneDirection:
    """Precise instructions for NarrativeEngine."""
    beats: List[SceneBeat] = field(default_factory=list)
    tone: str = "quotidiano"  # "teso", "intimo", "comico", "quotidiano", "drammatico"
    ambient_mandatory: List[str] = field(default_factory=list)
    scene_trajectory: str = ""  # where the scene is heading

    def to_prompt(self) -> str:
        """Format for NarrativeEngine injection."""
        lines = [
            "=== SCENE DIRECTION (from DirectorAgent) ===",
            f"Tone: {self.tone}",
            "",
            "SCENE BEATS (follow this order):",
        ]
        for i, beat in enumerate(self.beats, 1):
            line = f"  {i}. {beat.actor}: "
            if beat.action:
                line += f"*{beat.action}* "
            if beat.dialogue_intent:
                line += f"→ {beat.dialogue_intent}"
            lines.append(line)

        if self.ambient_mandatory:
            lines.extend(["", "MUST INCLUDE:"])
            for detail in self.ambient_mandatory:
                lines.append(f"  - {detail}")

        if self.scene_trajectory:
            lines.extend(["", f"TRAJECTORY: {self.scene_trajectory}"])

        lines.append("")
        return "\n".join(lines)


_DIRECTOR_SYSTEM_PROMPT = """You are a Scene Director for an Italian RPG game.
Given the current situation, decide WHAT happens in this scene.

You do NOT write the narrative. You plan the beats.

Respond ONLY with JSON:
{
  "beats": [
    {"actor": "NPC name", "action": "physical action", "dialogue_intent": "what they want to say"},
  ],
  "tone": "one of: quotidiano/teso/intimo/comico/drammatico",
  "ambient": ["environmental detail to include"],
  "trajectory": "where this scene is heading in 1 sentence"
}

Rules:
- Max 3 beats.
- Actions are physical (stands up, looks away, grabs arm). NOT dialogue.
- dialogue_intent is the INTENT, not exact words. E.g. "wants to ask about the test" not the actual dialogue.
- Think about what would happen naturally given the characters' states.
- Keep it in Italian for character context, English for meta.
"""


class DirectorAgent:
    """Decides WHAT happens in the scene. Light LLM call."""

    def __init__(self) -> None:
        pass

    async def direct(
        self,
        directive: "TurnDirective",
        game_state: "GameState",
        llm_manager: Any,
        context: Dict[str, Any],
    ) -> Optional[SceneDirection]:
        """Generate scene direction.

        Args:
            directive: TurnDirective from WorldSimulator
            game_state: Current game state
            llm_manager: LLM manager for API call
            context: Extra context (memory, personality, etc.)

        Returns:
            SceneDirection or None if not needed / failed
        """
        if not directive.needs_director:
            return None

        # Build compact situation summary for the director
        situation = self._build_situation(directive, game_state, context)

        try:
            # Use fast model with low token count
            response, provider = await llm_manager.generate(
                system_prompt=_DIRECTOR_SYSTEM_PROMPT,
                user_input=situation,
                history=[],
                json_mode=True,
            )

            return self._parse_response(response)

        except Exception as e:
            logger.warning("[DirectorAgent] Failed: %s", e)
            return self._fallback_direction(directive)

    def _build_situation(
        self,
        directive: "TurnDirective",
        game_state: "GameState",
        context: Dict[str, Any],
    ) -> str:
        """Build compact situation description for the director."""
        parts = [
            f"Location: {game_state.current_location}",
            f"Time: {game_state.time_of_day}",
        ]

        # Characters in scene
        if directive.npcs_in_scene:
            chars = []
            for npc in directive.npcs_in_scene:
                role = f" ({npc.role})" if npc.role != "active" else " [MAIN]"
                doing = f" - {npc.doing}" if npc.doing else ""
                chars.append(f"  {npc.npc_name}{role}{doing}")
            parts.extend(["Characters:", *chars])

        # NPC initiative
        if directive.npc_initiative:
            init = directive.npc_initiative
            parts.extend([
                f"\n{init.npc_name} wants to: {init.action}",
                f"Emotional state: {init.emotional_state}",
                f"Urgency: {init.urgency}",
            ])
            if init.goal_context:
                parts.append(f"Because: {init.goal_context}")

        # Narrative pressure
        if directive.narrative_pressure:
            np = directive.narrative_pressure
            parts.append(f"\nAtmosphere: {np.hint} (building towards {np.building_towards})")

        # Injected mind context (truncated)
        if directive.injected_context:
            # Take first 300 chars
            parts.append(f"\n{directive.injected_context[:300]}")

        return "\n".join(parts)

    def _parse_response(self, response: Any) -> Optional[SceneDirection]:
        """Parse LLM response into SceneDirection."""
        try:
            # response might be LLMResponse object or have raw_response
            text = getattr(response, "text", "") or getattr(response, "raw_response", "")
            if not text:
                return None

            # Clean JSON
            text = text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            data = json.loads(text)

            beats = []
            for beat_data in data.get("beats", []):
                beats.append(SceneBeat(
                    actor=beat_data.get("actor", ""),
                    action=beat_data.get("action", ""),
                    dialogue_intent=beat_data.get("dialogue_intent", ""),
                ))

            return SceneDirection(
                beats=beats,
                tone=data.get("tone", "quotidiano"),
                ambient_mandatory=data.get("ambient", []),
                scene_trajectory=data.get("trajectory", ""),
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("[DirectorAgent] Parse failed: %s", e)
            return None

    def _fallback_direction(
        self, directive: "TurnDirective",
    ) -> SceneDirection:
        """Fallback when LLM call fails."""
        beats = []

        if directive.npc_initiative:
            init = directive.npc_initiative
            beats.append(SceneBeat(
                actor=init.npc_name,
                action=init.action,
                dialogue_intent=init.goal_context or init.action,
            ))

        return SceneDirection(
            beats=beats,
            tone="quotidiano",
        )
