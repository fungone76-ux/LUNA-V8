"""Dialogue sequence management for Multi-NPC system.

Handles turn sequencing with max 3 exchanges per player turn.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Dict, Any

from luna.systems.multi_npc.interaction_rules import InteractionType


class SpeakerType(Enum):
    """Type of speaker in dialogue."""
    
    PLAYER = auto()
    ACTIVE_NPC = auto()      # NPC the player is addressing
    SECONDARY_NPC = auto()   # NPC that intervenes


@dataclass
class DialogueTurn:
    """A single turn in the dialogue sequence.
    
    Attributes:
        speaker: Name of the speaking character
        speaker_type: Type of speaker
        text: Dialogue text
        visual_en: Dialogue-specific visual description
        tags_en: SD tags for this turn
        interaction_type: For secondary NPCs, type of intervention
        target_npc: For interventions, who they're responding to
        is_final: True if this ends the sequence
        focus_position: Camera focus: "foreground", "center", "background"
    """
    speaker: str
    speaker_type: SpeakerType
    text: str = ""
    visual_en: str = ""
    tags_en: List[str] = field(default_factory=list)
    interaction_type: Optional[InteractionType] = None
    target_npc: Optional[str] = None
    is_final: bool = False
    focus_position: str = "center"  # "foreground", "center", "background"


@dataclass 
class DialogueSequence:
    """Complete dialogue sequence for one player turn.
    
    Max 3 NPC messages per sequence:
    1. Active NPC response to player
    2. Secondary NPC intervention (if triggered)
    3. Active NPC response to intervention (closure)
    """
    
    MAX_TURNS: int = 10  # Class constant - V2: Espanso per 5 scambi (10 messaggi max)
    
    player_input: str = ""
    active_npc: str = ""
    turns: List[DialogueTurn] = field(default_factory=list)
    current_turn: int = 0
    
    def __post_init__(self):
        """Validate sequence."""
        if len(self.turns) > self.MAX_TURNS:
            raise ValueError(f"Max {self.MAX_TURNS} turns allowed per sequence")
    
    def add_turn(self, turn: DialogueTurn) -> bool:
        """Add a turn to the sequence.
        
        Args:
            turn: DialogueTurn to add
            
        Returns:
            True if added successfully, False if max reached
        """
        if len(self.turns) >= self.MAX_TURNS:
            return False
        
        self.turns.append(turn)
        return True
    
    def can_add_intervention(self) -> bool:
        """Check if we can add another intervention.
        
        Returns:
            True if under max turns and not already intervened
        """
        if len(self.turns) >= self.MAX_TURNS:
            return False
        
        # Check if we already have an intervention
        interventions = sum(
            1 for t in self.turns 
            if t.speaker_type == SpeakerType.SECONDARY_NPC
        )
        return interventions < 1  # Max 1 intervention per sequence
    
    def get_npc_turn_count(self) -> int:
        """Get number of NPC turns in sequence.
        
        Returns:
            Count of NPC turns (active + secondary)
        """
        return sum(
            1 for t in self.turns 
            if t.speaker_type != SpeakerType.PLAYER
        )
    
    def get_turns_for_generation(self) -> List[DialogueTurn]:
        """Get turns that need image generation.
        
        Returns:
            List of turns with visual_en that need images
        """
        return [
            t for t in self.turns 
            if t.visual_en and not t.is_final
        ]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation
        """
        return {
            "player_input": self.player_input,
            "active_npc": self.active_npc,
            "turns": [
                {
                    "speaker": t.speaker,
                    "speaker_type": t.speaker_type.name,
                    "text": t.text,
                    "visual_en": t.visual_en,
                    "tags_en": t.tags_en,
                    "interaction_type": t.interaction_type.name if t.interaction_type else None,
                    "target_npc": t.target_npc,
                    "is_final": t.is_final,
                }
                for t in self.turns
            ],
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DialogueSequence":
        """Create from dictionary.
        
        Args:
            data: Dictionary data
            
        Returns:
            DialogueSequence instance
        """
        turns = []
        for t_data in data.get("turns", []):
            turn = DialogueTurn(
                speaker=t_data["speaker"],
                speaker_type=SpeakerType[t_data["speaker_type"]],
                text=t_data["text"],
                visual_en=t_data.get("visual_en", ""),
                tags_en=t_data.get("tags_en", []),
                interaction_type=InteractionType[t_data["interaction_type"]] if t_data.get("interaction_type") else None,
                target_npc=t_data.get("target_npc"),
                is_final=t_data.get("is_final", False),
            )
            turns.append(turn)
        
        return cls(
            player_input=data.get("player_input", ""),
            active_npc=data.get("active_npc", ""),
            turns=turns,
        )
