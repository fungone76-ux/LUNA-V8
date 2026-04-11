"""Invitation Manager - Handles NPC invitations to player's home.

V4.5: New module for managing NPC invitations via message/chat.

Features:
- Register invitations with scheduled arrival time
- Track accepted invitations
- Trigger arrival events when time comes
- Generate narrative messages when NPCs arrive
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PendingInvitation:
    """An invitation sent to an NPC."""
    npc_name: str
    invited_at_turn: int
    arrival_time: str  # "evening", "night", "afternoon", etc.
    location: str  # V4.8: target location for invitation (player_home, bar, gym, etc.)
    arrived: bool = False
    has_notified: bool = False   # True once the player has seen the arrival message
    waiting_message: str = ""    # Message shown when player returns to location
    

class InvitationManager:
    """Manages invitations to player's home or other locations.
    
    V4.8: Extended to support invitations to any location (gym, bar, park, etc.)
    """
    
    # Time keywords in invitations
    TIME_PATTERNS = {
        "morning": [r'\bmattina\b', r'\bstamattina\b', r'\bdomani\s+mattina\b'],
        "afternoon": [r'\bpomeriggio\b', r'\bsta\s+pomeriggio\b', r'\bdomani\s+pomeriggio\b'],
        "evening": [r'\bsera\b', r'\bstasera\b', r'\bquesta\s+sera\b', r'\bsta\s+sera\b'],
        "night": [r'\bnotte\b', r'\bstanotte\b', r'\bquesta\s+notte\b'],
    }
    
    # Location patterns for detecting where player wants to meet
    LOCATION_PATTERNS = {
        "player_home": [r'\ba\s+casa\b', r'\bcasa\s+mia\b', r'\bda\s+me\b', r'\ba\s+casa\s+mia\b'],
        "bar": [r'\bal\s+bar\b', r'\bbar\b', r'\bpub\b'],
        "gym": [r'\bin\s+palestra\b', r'\balla\s+palestra\b', r'\bpalestra\b'],
        "park": [r'\bal\s+parco\b', r'\bin\s+parco\b', r'\bparco\b'],
        "school_entrance": [r'\bscuola\b', r'\balla\s+scuola\b'],
    }
    
    # V4.9: Acceptance patterns for detecting NPC acceptance in responses
    ACCEPTANCE_PATTERNS = [
        r"\bva\s+bene\b",
        r"\bd'accordo\b",
        r"\bci\s+sto\b",
        r"\bok\b",
        r"\bokay\b",
        r"\bsi\b",
        r"\bsì\b",
        r"\bvolentieri\b",
        r"\bcon\s+piacere\b",
        r"\barrivo\b",
        r"\bvengo\b",
        r"\bpasso\b",
        r"\bti\s+aspetto\b",
        r"\bpasso\s+da\s+te\b",
        r"\bsono\s+contenta\b",
        r"\bmi\s+fa\s+piacere\b",
    ]
    
    def __init__(self, state_manager: Any, world: Any, schedule_manager: Optional[Any] = None):
        """Initialize invitation manager.
        
        Args:
            state_manager: For accessing game state
            world: World definition
            schedule_manager: For NPC locations
        """
        self.state_manager = state_manager
        self.world = world
        self.schedule_manager = schedule_manager
        self._pending_invitations: Dict[str, PendingInvitation] = {}
    
    def detect_invitation_intent(self, user_input: str) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """Detect if user is inviting an NPC to a location.
        
        Args:
            user_input: Player's input text
            
        Returns:
            Tuple of (is_invitation, target_npc, arrival_time, location)
        """
        input_lower = user_input.lower()
        
        # Check for invitation patterns - V4.8: extended patterns
        invitation_patterns = [
            r'\bvieni\s+a\s+casa\b',
            r'\bvieni\s+da\s+me\b',
            r'\bvieni\s+a\s+casa\s+mia\b',
            r'\bperche\s+non\s+vieni\b',
            r'\bpassa\s+a\s+casa\b',
            r'\bvenire\s+a\s+casa\b',
            r'\bti\s+aspetto\s+a\s+casa\b',
            r'\bvieni\s+stasera\b',
            r'\bvieni\s+questa\s+sera\b',
            r'\bvieni\s+oggi\b',
            r'\bvieni\s+domani\b',
            r'\bvenire\b',  # Generic invitation
            r'\bincontrare\b',  # Meet up
            r'\bdai\s+\w+\b',  # "Dai Luna" (come on Luna)
            r'\bti\s+aspetto\b',  # I wait for you
        ]
        
        is_invitation = any(re.search(p, input_lower) for p in invitation_patterns)
        
        if not is_invitation:
            return False, None, None, None
        
        # Find target NPC
        target_npc = self._find_target_npc(input_lower)
        
        # Determine arrival time
        arrival_time = self._detect_arrival_time(input_lower)
        
        # Determine location
        location = self._detect_location(input_lower)
        
        return True, target_npc, arrival_time, location
    
    def detect_acceptance(self, npc_response: str) -> bool:
        """Detect if NPC accepted an invitation from their response.
        
        V4.9: Analyzes NPC response text to determine if they accepted.
        
        Args:
            npc_response: The text response from the NPC
            
        Returns:
            True if acceptance detected, False otherwise
        """
        response_lower = npc_response.lower()
        for pattern in self.ACCEPTANCE_PATTERNS:
            if re.search(pattern, response_lower):
                return True
        return False
    
    def register_invitation(
        self, 
        npc_name: str, 
        current_turn: int,
        arrival_time: Optional[str] = None,
        location: Optional[str] = None
    ) -> bool:
        """Register an invitation for an NPC.
        
        Args:
            npc_name: Name of invited NPC
            current_turn: Current game turn
            arrival_time: When they should arrive (default: next evening)
            location: Where to meet (default: player_home)
            
        Returns:
            True if registered successfully
        """
        if not arrival_time:
            arrival_time = "evening"  # Default to evening
        if not location:
            location = "player_home"  # Default to home
        
        invitation = PendingInvitation(
            npc_name=npc_name,
            invited_at_turn=current_turn,
            arrival_time=arrival_time,
            location=location,
            arrived=False
        )
        
        self._pending_invitations[npc_name] = invitation
        logger.debug(f"[InvitationManager] Registered invitation for {npc_name} at {arrival_time}, location: {location}")
        return True
    
    def check_arrivals(
        self, 
        current_time: str, 
        player_location: str,
        location_manager = None
    ) -> List[PendingInvitation]:
        """Check if any invited NPCs should arrive now.
        
        Args:
            current_time: Current time of day (morning, afternoon, evening, night)
            player_location: Current player location
            location_manager: Optional LocationManager to update NPC presence
            
        Returns:
            List of NPCs arriving now
        """
        arrivals = []

        for npc_name, invitation in list(self._pending_invitations.items()):
            if invitation.arrived:
                continue

            # Arrival is independent of player position: NPC goes to the agreed location.
            if invitation.arrival_time == current_time:
                invitation.arrived = True
                # Set location override with TTL (6 turns ≈ 3 time-phase changes)
                game_state = self._get_game_state()
                if game_state:
                    game_state.set_npc_location(npc_name, invitation.location, ttl_turns=6)
                # Add NPC to location's present list
                if location_manager:
                    location_manager.add_npc_to_location(invitation.location, npc_name)

                # Build message appropriate for where the player currently is
                if invitation.location == player_location:
                    # Player is already there: show arrival immediately
                    invitation.waiting_message = self.build_arrival_message(invitation)
                    invitation.has_notified = True
                else:
                    # Player is elsewhere: store a "waiting" message for when they return
                    npc_def = self.world.companions.get(npc_name) if self.world else None
                    article = "la" if npc_def and getattr(npc_def, 'gender', 'female') == 'female' else "il"
                    loc_name = invitation.location.replace("_", " ")
                    invitation.waiting_message = (
                        f"\n\n*[{article.capitalize()} {npc_name} è arrivat"
                        f"{'a' if article == 'la' else 'o'} {loc_name} e ti sta aspettando.]*"
                    )

                arrivals.append(invitation)
                logger.debug(f"[InvitationManager] {npc_name} arrived at {invitation.location} "
                             f"(player at {player_location})")

        return arrivals

    def get_pending_notifications(self, player_location: str) -> List[str]:
        """Return arrival messages for NPCs waiting at the player's current location."""
        notifications = []
        for invitation in self._pending_invitations.values():
            if (invitation.arrived
                    and not invitation.has_notified
                    and invitation.location == player_location):
                invitation.has_notified = True
                notifications.append(invitation.waiting_message)
        return notifications
    
    def build_arrival_message(self, invitation: PendingInvitation) -> str:
        """Build narrative message for NPC arrival.
        
        Args:
            invitation: The pending invitation
            
        Returns:
            Narrative text
        """
        npc_name = invitation.npc_name
        
        # Get NPC definition for gender/role
        npc_def = self.world.companions.get(npc_name)
        article = "la" if npc_def and getattr(npc_def, 'gender', 'female') == 'female' else "il"
        
        # Build message based on location
        location_contexts = {
            "player_home": {
                "morning": "mentre ti prepari per la giornata",
                "afternoon": "mentre riposi nel pomeriggio", 
                "evening": "mentre ti rilassi in salotto",
                "night": "quando stai per andare a dormire"
            },
            "bar": {
                "evening": "nel locale affollato",
                "night": "alla sera",
            },
            "gym": {
                "afternoon": "in palestra",
                "evening": "durante l'allenamento",
            },
            "park": {
                "afternoon": "al parco",
                "evening": "mentre passeggi",
            },
        }
        
        time_contexts = location_contexts.get(invitation.location, {})
        context = time_contexts.get(invitation.arrival_time, "")
        
        # Different arrival messages based on location
        if invitation.location == "player_home":
            message = f"\n\n*{context.capitalize() if context else 'Improvvisamente'}, senti suonare il campanello. Aprendo la porta, trovi {article} {npc_name} che è venut{'a' if article == 'la' else 'o'} come promesso.*"
        else:
            location_name = invitation.location.replace("_", " ")
            _prep = 'al' if invitation.location in ["bar", "park"] else 'alla' if invitation.location == 'gym' else 'a'
            message = f"\n\n*{context.capitalize() if context else 'Mentre aspetti'}, vedi {article} {npc_name} arrivare {_prep} {location_name}.*"
        
        return message
    
    def clear_arrived_invitations(self):
        """Clear invitations that have been processed."""
        to_remove = [
            name for name, inv in self._pending_invitations.items()
            if inv.arrived
        ]
        for name in to_remove:
            del self._pending_invitations[name]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize pending invitations for save."""
        return {
            "pending": [
                {
                    "npc_name": inv.npc_name,
                    "invited_at_turn": inv.invited_at_turn,
                    "arrival_time": inv.arrival_time,
                    "location": inv.location,
                    "arrived": inv.arrived,
                    "has_notified": inv.has_notified,
                    "waiting_message": inv.waiting_message,
                }
                for inv in self._pending_invitations.values()
            ]
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Restore pending invitations from save."""
        self._pending_invitations.clear()
        for item in data.get("pending", []):
            inv = PendingInvitation(
                npc_name=item["npc_name"],
                invited_at_turn=item["invited_at_turn"],
                arrival_time=item["arrival_time"],
                location=item["location"],
                arrived=item.get("arrived", False),
                has_notified=item.get("has_notified", False),
                waiting_message=item.get("waiting_message", ""),
            )
            self._pending_invitations[inv.npc_name] = inv
    
    def _get_game_state(self):
        """Get current game state from state manager."""
        if self.state_manager:
            return self.state_manager.current
        return None
    
    def _find_target_npc(self, input_lower: str) -> Optional[str]:
        """Find target NPC in user input."""
        for name in self.world.companions.keys():
            name_lower = name.lower()
            if re.search(r'\b' + re.escape(name_lower) + r'\b', input_lower):
                companion = self.world.companions[name]
                if not getattr(companion, 'is_temporary', False):
                    return name
        return None
    
    def _detect_arrival_time(self, input_lower: str) -> Optional[str]:
        """Detect when the NPC should arrive from user input."""
        for time_key, patterns in self.TIME_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, input_lower):
                    return time_key
        return "evening"  # Default
    
    def _detect_location(self, input_lower: str) -> str:
        """Detect where the meeting should happen from user input."""
        for location_key, patterns in self.LOCATION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, input_lower):
                    return location_key
        return "player_home"  # Default
    
    def get_pending_invitations(self) -> Dict[str, PendingInvitation]:
        """Get all pending invitations."""
        return {k: v for k, v in self._pending_invitations.items() if not v.arrived}
