"""NPC Message System — Metodo 2: Messaggi Asincroni.

Gestisce canali di comunicazione a distanza (es. SMS, Note, Convocazioni).
Previene interruzioni forzate usando il canale appropriato invece del teletrasporto.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from luna.core.models import GameState

logger = logging.getLogger(__name__)


@dataclass
class NpcMessage:
    """Rappresenta un messaggio asincrono (SMS, nota, voce) da un NPC."""
    sender_id: str
    text: str
    turn_received: int
    is_read: bool = False
    urgency: float = 0.5
    reply_expected: bool = False
    valid_until_turn: Optional[int] = None
    channel: str = "sms"  # "sms", "note", "gossip"
    
    def is_expired(self, current_turn: int) -> bool:
        if self.valid_until_turn is None:
            return False
        return current_turn > self.valid_until_turn


class MessageChannel:
    """Canale che contiene la coda dei messaggi."""
    def __init__(self):
        self.inbox: List[NpcMessage] = []
        
    def add(self, message: NpcMessage) -> None:
        self.inbox.append(message)
        # Ordina per urgenza (decrescente) poi per id (recente prima)
        self.inbox.sort(key=lambda m: (-m.urgency, -m.turn_received))
        
    def get_unread(self) -> List[NpcMessage]:
        return [m for m in self.inbox if not m.is_read]
        
    def mark_all_read(self) -> None:
        for m in self.inbox:
            m.is_read = True
            
    def remove_expired(self, current_turn: int) -> int:
        initial = len(self.inbox)
        self.inbox = [m for m in self.inbox if not m.is_expired(current_turn)]
        return initial - len(self.inbox)


class NpcMessageSystem:
    """Manager globale per la messaggistica asincrona (no interruzioni UI)."""
    
    def __init__(self):
        self.channels: Dict[str, MessageChannel] = {
            "sms": MessageChannel(),
            "note": MessageChannel(),
            "gossip": MessageChannel(),
        }
        
    def send_message(self, message: NpcMessage, game_state: "GameState") -> None:
        """Invia un messaggio, salvandolo nel log e nello stato del gioco se necessario."""
        if message.channel not in self.channels:
            self.channels[message.channel] = MessageChannel()
            
        self.channels[message.channel].add(message)
        logger.info(f"[{message.channel.upper()}] Da {message.sender_id}: {message.text[:30]}...")

        # Facoltativo: inserire flag nel game_state per persisterli
        # game_state.flags["_npc_messages"] = self.serialize()
        
    def get_unread_messages(self, channel: Optional[str] = None) -> List[NpcMessage]:
        """Ritorna i messaggi non letti (tutti se channel=None)."""
        unread = []
        if channel:
            if channel in self.channels:
                unread.extend(self.channels[channel].get_unread())
        else:
            for ch in self.channels.values():
                unread.extend(ch.get_unread())
        return unread
    
    def cleanup_expired(self, current_turn: int) -> None:
        """Pulisce i messaggi scaduti da tutti i canali."""
        for name, channel in self.channels.items():
            removed = channel.remove_expired(current_turn)
            if removed > 0:
                logger.debug(f"[MessageSystem] Rimosse {removed} vecchie {name}")

