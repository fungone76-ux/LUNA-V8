"""HomeSceneOrchestrator — turni con 2+ companion a casa del giocatore."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_ADDRESS_ALL = [r"\bragazze\b", r"\btutte\b", r"\bentrambe\b", r"\bvoi due\b", r"\bvoi\b"]
_INTER_NPC_PATTERNS = [
    r"\bparlatevi\b", r"\bparlate tra\b", r"\bditevi\b",
    r"\blasciatevi\b", r"\bparlatevi\b",
]


class HomeSceneOrchestrator:
    """Gestisce i turni di dialogo quando 2+ companion sono a casa."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine

    def detect_addressed_npc(
        self,
        player_input: str,
        companions_present: List[str],
        active_companion: str,
    ) -> Tuple[Optional[str], bool]:
        """Rileva a chi il player si rivolge.

        Returns (npc_name, all_addressed).
        npc_name è None se si rivolge a tutte o a nessuna specifica.
        """
        text = player_input.lower()

        for pattern in _ADDRESS_ALL:
            if re.search(pattern, text):
                return None, True

        for npc_name in companions_present:
            npc_lower = npc_name.lower()
            if re.match(rf"^{re.escape(npc_lower)}\b", text):
                return npc_name, False
            if re.search(rf"\b{re.escape(npc_lower)}\s*,", text):
                return npc_name, False

        return None, False

    def is_inter_npc_request(self, player_input: str) -> bool:
        text = player_input.lower()
        return any(re.search(p, text) for p in _INTER_NPC_PATTERNS)

    def build_reaction_prompt(
        self,
        reacting_npc: str,
        primary_text: str,
        primary_speaker: str,
        player_input: str,
        game_state: Any,
        context: Dict[str, Any],
    ) -> str:
        comp_def = self.engine.world.companions.get(reacting_npc)
        personality = getattr(comp_def, "base_personality", "") if comp_def else ""
        aff = game_state.affinity.get(reacting_npc, 0)

        return (
            f"You are {reacting_npc}. Personality: {personality}. "
            f"Affinity with player: {aff}/100.\n\n"
            f"The player said: \"{player_input}\"\n"
            f"{primary_speaker} just replied: \"{primary_text}\"\n\n"
            f"React in ONE short sentence (in Italian) to what {primary_speaker} said. "
            f"Stay in character — agree, disagree, be jealous, ironic, or surprised. "
            f"Do not repeat what {primary_speaker} said. Speak as {reacting_npc} in first person. "
            f"No JSON — only the dialogue line."
        )

    def build_addressed_response_prompt(
        self,
        responding_npc: str,
        addressing_npc: str,
        addressing_text: str,
        player_input: str,
        game_state: Any,
        context: Dict[str, Any],
    ) -> str:
        """Prompt per quando una companion risponde a un'altra che l'ha nominata.

        Più ampio di build_reaction_prompt: 2-3 frasi, risponde direttamente
        a ciò che l'altra companion le ha detto o chiesto.
        """
        comp_def = self.engine.world.companions.get(responding_npc)
        personality = getattr(comp_def, "base_personality", "") if comp_def else ""
        aff = game_state.affinity.get(responding_npc, 0)

        return (
            f"You are {responding_npc}. Personality: {personality}. "
            f"Affinity with player: {aff}/100.\n\n"
            f"The player said: \"{player_input}\"\n"
            f"{addressing_npc} just addressed you directly: \"{addressing_text}\"\n\n"
            f"{addressing_npc} spoke to you or mentioned you explicitly. "
            f"Respond to {addressing_npc} in Italian (2-3 sentences). "
            f"React naturally — agree, push back, deflect, be jealous, playful, etc. "
            f"Stay in character. No JSON — only your dialogue."
        )

    def build_inter_npc_prompt(
        self,
        speaker: str,
        listener: str,
        context_text: str,
        game_state: Any,
    ) -> str:
        comp_def = self.engine.world.companions.get(speaker)
        personality = getattr(comp_def, "base_personality", "") if comp_def else ""
        aff = game_state.affinity.get(speaker, 0)

        return (
            f"You are {speaker}. Personality: {personality}. "
            f"Affinity with player: {aff}/100.\n\n"
            f"{context_text}\n\n"
            f"Say something directly to {listener} (in Italian, ONE sentence). "
            f"Stay in character — friendly, competitive, jealous, or ironic. "
            f"No JSON — only the dialogue line, no outer quotes."
        )
