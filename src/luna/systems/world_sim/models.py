"""World Simulator — data classes output from each turn."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from luna.systems.npc_mind import TurnDriver


@dataclass
class NPCInitiative:
    """What an NPC wants to do on their own."""
    npc_id: str
    npc_name: str
    action: str
    goal_context: str
    emotional_state: str
    urgency: str            # "low" | "medium" | "high" | "critical"
    goal_type: str

    def to_prompt(self) -> str:
        urgency_markers = {
            "low": "[NPC initiative]",
            "medium": "[NPC INITIATIVE]",
            "high": "[IMPORTANT INITIATIVE]",
            "critical": "[⚠️ CRITICAL INITIATIVE]",
        }
        marker = urgency_markers.get(self.urgency, "[NPC INITIATIVE]")
        lines = [
            f"\n{marker} {self.npc_name.upper()} TAKES INITIATIVE",
            f"Action: {self.action}",
        ]
        if self.goal_context:
            lines.append(f"Context: {self.goal_context}")
        if self.emotional_state and self.emotional_state != "neutral":
            lines.append(f"Emotional state: {self.emotional_state}")
        lines.extend([
            "",
            f"⚠️ {self.npc_name} MUST act first this turn.",
            f"DO NOT wait for the player to do something.",
            f"{self.npc_name} drives the scene.",
            "",
        ])
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "npc_id": self.npc_id,
            "npc_name": self.npc_name,
            "action": self.action,
            "goal_context": self.goal_context,
            "emotional_state": self.emotional_state,
            "urgency": self.urgency,
            "goal_type": self.goal_type,
        }


@dataclass
class AmbientDetail:
    description: str
    source: str = ""
    importance: float = 0.3


@dataclass
class NPCScenePresence:
    npc_id: str
    npc_name: str
    role: str = "present"   # "active" | "present" | "passing_by" | "background"
    doing: str = ""


@dataclass
class NarrativePressure:
    pressure_type: str      # "foreshadowing" | "buildup" | "trigger"
    hint: str
    building_towards: str
    pressure_level: float


@dataclass
class TurnDirective:
    """Output of WorldSimulator.tick() — what should happen this turn."""

    driver: TurnDriver = TurnDriver.PLAYER
    npc_initiative: Optional[NPCInitiative] = None
    ambient: List[AmbientDetail] = field(default_factory=list)
    npcs_in_scene: List[NPCScenePresence] = field(default_factory=list)
    narrative_pressure: Optional[NarrativePressure] = None
    injected_context: str = ""
    needs_director: bool = False
    initiative_event: Optional[Dict[str, Any]] = None

    def build_context(self) -> str:
        parts = []
        if self.npc_initiative:
            parts.append(self.npc_initiative.to_prompt())
        if self.ambient:
            parts.append("=== AMBIENT DETAILS ===")
            for detail in self.ambient:
                parts.append(f"- {detail.description}")
            parts.append("")
        if self.npcs_in_scene:
            secondary = [n for n in self.npcs_in_scene if n.role != "active"]
            if secondary:
                parts.append("=== OTHER CHARACTERS PRESENT ===")
                for npc in secondary:
                    doing = f" — {npc.doing}" if npc.doing else ""
                    parts.append(f"- {npc.npc_name} ({npc.role}){doing}")
                parts.append("")
        if self.narrative_pressure:
            np = self.narrative_pressure
            if np.pressure_type == "foreshadowing":
                parts.append(f"[ATMOSPHERE] {np.hint}")
            elif np.pressure_type == "buildup":
                parts.append(f"[ATMOSPHERE — BUILDING] {np.hint}")
            elif np.pressure_type == "trigger":
                # v8: trigger phase must produce a narrative event — explicit instruction
                parts.append(
                    f"[TENSION EVENT — {np.building_towards.upper()} TRIGGERED] "
                    f"{np.hint} "
                    f"Something must happen NOW. Do not delay this moment further."
                )
            parts.append("")
        if self.injected_context:
            parts.append(self.injected_context)
        return "\n".join(parts)

    def to_summary(self) -> Dict[str, Any]:
        return {
            "driver": self.driver.value if hasattr(self.driver, "value") else str(self.driver),
            "npc_initiative": self.npc_initiative.to_dict() if self.npc_initiative else None,
            "initiative_event": self.initiative_event,
            "ambient_count": len(self.ambient),
            "npcs_in_scene": [npc.npc_id for npc in self.npcs_in_scene],
            "needs_director": self.needs_director,
        }
