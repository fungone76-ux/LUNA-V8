"""Luna RPG v8 — PresenceTracker.

Traccia quali NPC sono in scena ogni turno e scrive flag nel GameState.
Usato da EmotionalStateEngine e CharacterVoiceBuilder.

Leggerissimo — nessuna dipendenza da LLM, nessun I/O.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from luna.core.models import GameState, WorldDefinition

logger = logging.getLogger(__name__)

# Flag scritti in game_state.flags ogni turno
_FLAG_PRESENT_NPCS = "present_npcs"          # List[str]
_FLAG_TEMPLATE     = "{name}_in_scene"        # bool per ogni NPC


class PresenceTracker:
    """Traccia la presenza degli NPC in scena e scrive flag nel GameState.

    Chiamato in TurnOrchestrator Step 0.4, prima di EmotionalStateEngine.

    Flag scritti (sovrascrivono il turno precedente):
      game_state.flags["present_npcs"]     = ["Stella", "Maria"]
      game_state.flags["stella_in_scene"]  = True
      game_state.flags["luna_in_scene"]    = False
      game_state.flags["maria_in_scene"]   = False
    """

    def __init__(self, world: Optional["WorldDefinition"] = None) -> None:
        self.world = world

    def update(
        self,
        game_state: "GameState",
        present_npcs: List[str],
        active_npc: str,
    ) -> None:
        """Aggiorna i flag di presenza nel GameState.

        Args:
            game_state:   Stato corrente del gioco
            present_npcs: NPC non-attivi rilevati in scena dal MultiNPCManager
            active_npc:   NPC attivo nel turno corrente
        """
        # Tutti gli NPC in scena = attivo + presenti
        all_in_scene = list({active_npc} | set(present_npcs))

        # Scrivi lista completa
        game_state.flags[_FLAG_PRESENT_NPCS] = all_in_scene

        # Scrivi flag per nome — prima azzera tutti i conosciuti
        if self.world:
            for npc_name in self.world.companions:
                flag_key = _FLAG_TEMPLATE.format(name=npc_name.lower())
                game_state.flags[flag_key] = (npc_name in all_in_scene)
        else:
            # Fallback: aggiorna solo quelli noti dalla chiamata
            for npc_name in all_in_scene:
                game_state.flags[_FLAG_TEMPLATE.format(name=npc_name.lower())] = True

        logger.debug(
            "[PresenceTracker] In scena: %s (attivo: %s)",
            all_in_scene,
            active_npc,
        )

    def get_relationship_context(
        self,
        active_npc: str,
        present_npcs: List[str],
        location: Optional[str] = None,
    ) -> str:
        """Stringa con le relazioni tra gli NPC in scena.

        Usata da CharacterVoiceBuilder._presence_directives().

        Returns:
            Es. "Stella è in scena. Rapporto con Luna: odio viscerale (tensione 0.9)."
            Stringa vuota se nessun NPC presente o world non disponibile.
        """
        if not present_npcs or not self.world:
            return ""

        active_def = self.world.companions.get(active_npc)
        if not active_def:
            return ""

        lines = []
        for npc_name in present_npcs:
            rel = active_def.npc_relationships.get(npc_name, {})
            if not rel:
                lines.append(f"{npc_name} è in scena.")
                continue

            # Location-specific override takes priority
            if location and isinstance(rel, dict):
                loc_behaviors = rel.get("location_behaviors", {})
                loc_override = loc_behaviors.get(location, "")
                if loc_override:
                    lines.append(f"{npc_name} è in scena. {loc_override}")
                    continue

            rel_type    = rel.get("type", "") if isinstance(rel, dict) else ""
            rel_desc    = rel.get("description_it", rel.get("description", "")) if isinstance(rel, dict) else ""
            tension     = rel.get("base_tension", 0.0) if isinstance(rel, dict) else 0.0

            tension_label = (
                "alta tensione" if tension >= 0.7
                else "tensione moderata" if tension >= 0.4
                else "bassa tensione"
            )

            parts = [f"{npc_name} è in scena."]
            if rel_type:
                parts.append(f"Rapporto: {rel_type} ({tension_label}).")
            if rel_desc:
                parts.append(rel_desc)

            lines.append(" ".join(parts))

        return "\n".join(lines)
