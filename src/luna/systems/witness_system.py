"""Witness System — Metodo 3: Reazioni a Catena.

Traccia chi vede cosa e propaga le informazioni tra NPC.
Maria è il witness primario: vede tutto perché pulisce ovunque.
"""
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING
import random

if TYPE_CHECKING:
    from luna.core.models import GameState
    from luna.systems.npc_state_manager import NPCStateManager


@dataclass
class WitnessEvent:
    """Un evento osservato da un NPC."""
    event_type: str          # "intimate_with_luna", "argument", "kind_act"
    subject_npc: str         # Chi è coinvolto (es. "luna")
    witness_npc: str         # Chi ha visto (es. "maria")
    location: str
    turn: int
    certainty: float         # 1.0 = visto direttamente, 0.5 = sentito
    told_to: List[str] = field(default_factory=list)  # A chi l'ha detto
    covered: bool = False    # Maria ha coperto invece di rivelare


class WitnessSystem:
    """Gestisce witnessing e propagazione gossip."""
    
    # Maria è nella stessa location del giocatore con questa probabilità
    MARIA_PRESENCE_CHANCE = {
        "school_corridor":  0.6,   # Alta: pulisce sempre
        "school_classroom": 0.3,   # Media: entra a pulire
        "school_bathroom":  0.5,   # Alta: va spesso
        "teacher_office":   0.4,   # Media: pulisce uffici
        "school_library":   0.3,
        "school_gym":       0.2,
        "principal_office": 0.1,   # Bassa: il preside non vuole
    }
    
    def __init__(self, npc_state: Optional["NPCStateManager"] = None) -> None:
        self.witness_log: List[WitnessEvent] = []
        self.npc_state = npc_state
    
    def check_maria_witnesses(
        self,
        event_type: str,
        subject_npc: str,
        location: str,
        game_state: "GameState",
    ) -> Optional[WitnessEvent]:
        """Controlla se Maria ha visto qualcosa."""
        if game_state.active_companion == "maria":
            return None
        
        chance = self.MARIA_PRESENCE_CHANCE.get(location, 0.2)
        if random.random() > chance:
            return None
        
        event = WitnessEvent(
            event_type=event_type,
            subject_npc=subject_npc,
            witness_npc="maria",
            location=location,
            turn=game_state.turn_count,
            certainty=0.8,
        )
        self.witness_log.append(event)
        return event
    
    def maria_decides_action(
        self,
        event: WitnessEvent,
        game_state: "GameState",
    ) -> str:
        """Decide cosa fa Maria con quello che ha visto."""
        maria_affinity = game_state.affinity.get("maria", 0)
        
        if maria_affinity >= 60:
            event.covered = True
            return "cover"
        elif maria_affinity >= 30:
            return "keep_secret"
        else:
            if random.random() < 0.3:
                return "gossip_preside"
            return "gossip_npc"
    
    def propagate_gossip(
        self,
        event: WitnessEvent,
        action: str,
        game_state: "GameState",
    ) -> None:
        """Propaga l'informazione ad altri NPC."""
        if action == "cover":
            self._add_to_npc_knowledge("maria", event, game_state)
            return
        
        elif action == "gossip_npc":
            stella_event = WitnessEvent(
                event_type=event.event_type,
                subject_npc=event.subject_npc,
                witness_npc="stella",
                location="school_corridor",
                turn=game_state.turn_count + 1,
                certainty=0.4,
            )
            self.witness_log.append(stella_event)
            self._add_to_npc_knowledge("stella", stella_event, game_state)
            event.told_to.append("stella")
        
        elif action == "gossip_preside":
            current = game_state.flags.get("preside_suspicion", 0)
            game_state.flags["preside_suspicion"] = current + 20
            event.told_to.append("preside")
            if game_state.flags["preside_suspicion"] >= 40:
                game_state.flags["preside_wants_meeting"] = True
    
    def _add_to_npc_knowledge(
        self,
        npc_id: str,
        event: WitnessEvent,
        game_state: "GameState",
    ) -> None:
        """Aggiunge l'evento alla conoscenza dell'NPC via off_screen_log."""
        knowledge_key = f"_knowledge_{npc_id}"
        known = game_state.flags.get(knowledge_key, [])
        known.append({
            "event_type": event.event_type,
            "subject": event.subject_npc,
            "turn": event.turn,
            "certainty": event.certainty,
            "covered": event.covered,
        })
        game_state.flags[knowledge_key] = known
