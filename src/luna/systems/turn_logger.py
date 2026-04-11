"""Turn Logger - Detailed logging system for debugging.

V4.9: Logs EVERYTHING for post-game analysis.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class TurnLogEntry:
    """Complete log of a single turn."""
    
    # Turn info
    turn_number: int
    timestamp: str
    session_id: int
    
    # Player input
    player_input: str
    
    # Game state
    active_companion: str
    current_location: str
    time_of_day: str
    
    # Companion state
    companion_affinity: int
    companion_outfit: Dict[str, Any]
    companion_location: Optional[str]
    companion_staying: bool
    
    # NPC locations (all)
    npc_locations: Dict[str, str]
    
    # Quests
    active_quests: list
    completed_quests: list
    quest_states: Dict[str, Any]
    
    # Memory
    recent_messages_count: int
    facts_count: int
    memory_context_used: str
    
    # System prompt (full)
    system_prompt: str
    
    # LLM response
    llm_response_text: str
    llm_response_visual: str
    llm_response_tags: list
    llm_raw_response: str
    llm_provider: str
    
    # Updates applied
    affinity_changes: Dict[str, int]
    outfit_changes: Dict[str, Any]
    location_changes: Dict[str, Any]
    
    # Events
    active_events: list
    triggered_events: list
    
    # Media
    image_generated: bool
    image_path: str
    image_prompt: str
    
    # Turn directive + initiative telemetry
    turn_directive: Optional[Dict[str, Any]] = None
    initiative_event: Optional[Dict[str, Any]] = None
    
    # Errors
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    
    # Performance
    processing_time_ms: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class TurnLogger:
    """Logger for complete turn data."""
    
    def __init__(self, storage_path: Path, session_id: int):
        """Initialize turn logger.
        
        Args:
            storage_path: Base path for storage
            session_id: Current session ID
        """
        self.session_id = session_id
        self.log_dir = storage_path / "turn_logs" / f"session_{session_id}"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Current turn being built
        self._current_turn: Optional[TurnLogEntry] = None
        self._turn_start_time: Optional[datetime] = None
        
        logger.debug(f"[TurnLogger] Initialized: {self.log_dir}")
    
    def start_turn(self, turn_number: int, player_input: str, game_state: Any):
        """Start logging a new turn.
        
        Args:
            turn_number: Current turn number
            player_input: Player's input text
            game_state: Current game state
        """
        from luna.core.models import GameState
        
        self._turn_start_time = datetime.now()
        
        # Extract NPC locations
        npc_locations = {}
        if hasattr(game_state, 'npc_locations'):
            npc_locations = game_state.npc_locations
        
        self._current_turn = TurnLogEntry(
            turn_number=turn_number,
            timestamp=self._turn_start_time.isoformat(),
            session_id=self.session_id,
            player_input=player_input,
            active_companion=game_state.active_companion,
            current_location=game_state.current_location,
            time_of_day=str(game_state.time_of_day),
            companion_affinity=game_state.affinity.get(game_state.active_companion, 0),
            companion_outfit=self._get_outfit_dict(game_state),
            companion_location=npc_locations.get(game_state.active_companion),
            companion_staying=getattr(game_state, 'companion_staying_with_player', False),
            npc_locations=dict(npc_locations),
            active_quests=list(getattr(game_state, 'active_quests', [])),
            completed_quests=list(getattr(game_state, 'completed_quests', [])),
            quest_states={},
            recent_messages_count=0,
            facts_count=0,
            memory_context_used="",
            system_prompt="",
            llm_response_text="",
            llm_response_visual="",
            llm_response_tags=[],
            llm_raw_response="",
            llm_provider="",
            affinity_changes={},
            outfit_changes={},
            location_changes={},
            active_events=[],
            triggered_events=[],
            image_generated=False,
            image_path="",
            image_prompt="",
            errors=[],
            warnings=[],
            processing_time_ms=0
        )
    
    def _get_outfit_dict(self, game_state: Any) -> Dict[str, Any]:
        """Extract outfit info from game state."""
        try:
            outfit = game_state.get_outfit()
            return {
                'style': outfit.style,
                'description': outfit.description,
                'components': outfit.components,
                'modifications': {k: str(v) for k, v in outfit.modifications.items()},
                'is_special': outfit.is_special
            }
        except Exception:
            return {}
    
    def log_system_prompt(self, prompt: str):
        """Log the complete system prompt."""
        if self._current_turn:
            self._current_turn.system_prompt = prompt
    
    def log_llm_response(self, response: Any, provider: str, raw_response: str = ""):
        """Log LLM response."""
        if self._current_turn:
            self._current_turn.llm_response_text = getattr(response, 'text', str(response))
            self._current_turn.llm_response_visual = getattr(response, 'visual_en', "")
            self._current_turn.llm_response_tags = getattr(response, 'tags_en', [])
            self._current_turn.llm_provider = provider
            self._current_turn.llm_raw_response = raw_response[:2000] if raw_response else ""  # Truncate
    
    def log_memory(self, recent_count: int, facts_count: int, context: str):
        """Log memory usage."""
        if self._current_turn:
            self._current_turn.recent_messages_count = recent_count
            self._current_turn.facts_count = facts_count
            self._current_turn.memory_context_used = context[:500]  # Truncate
    
    def log_updates(self, affinity: Dict = None, outfit: Dict = None, location: Dict = None):
        """Log state updates."""
        if self._current_turn:
            if affinity:
                self._current_turn.affinity_changes = affinity
            if outfit:
                self._current_turn.outfit_changes = outfit
            if location:
                self._current_turn.location_changes = location
    
    def log_image(self, generated: bool, path: str = "", prompt: str = ""):
        """Log image generation."""
        if self._current_turn:
            self._current_turn.image_generated = generated
            self._current_turn.image_path = path
            self._current_turn.image_prompt = prompt[:1000]  # Truncate
    
    def log_turn_directive(self, directive_summary: Dict[str, Any]):
        """Attach TurnDirective summary."""
        if self._current_turn:
            self._current_turn.turn_directive = directive_summary
    
    def log_initiative_event(self, event: Dict[str, Any]):
        """Attach InitiativeAgent telemetry."""
        if self._current_turn:
            self._current_turn.initiative_event = event
    
    def log_error(self, error: str):
        """Log an error."""
        if self._current_turn:
            self._current_turn.errors.append(error)
    
    def log_warning(self, warning: str):
        """Log a warning."""
        if self._current_turn:
            self._current_turn.warnings.append(warning)
    
    def end_turn(self):
        """Finalize and save the turn log."""
        if not self._current_turn:
            return
        
        # Calculate processing time
        if self._turn_start_time:
            duration = (datetime.now() - self._turn_start_time).total_seconds()
            self._current_turn.processing_time_ms = int(duration * 1000)
        
        # Save to file
        filename = f"turn_{self._current_turn.turn_number:04d}.json"
        filepath = self.log_dir / filename
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(self._current_turn.to_dict(), f, indent=2, ensure_ascii=False)
            logger.debug(f"[TurnLogger] Saved: {filepath}")
        except Exception as e:
            logger.error(f"[TurnLogger] Error saving log: {e}")
        
        # Also save latest for quick access
        latest_path = self.log_dir / "latest_turn.json"
        try:
            with open(latest_path, 'w', encoding='utf-8') as f:
                json.dump(self._current_turn.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        
        # Reset for next turn
        self._current_turn = None
        self._turn_start_time = None
    
    def get_log_summary(self) -> str:
        """Get a summary of logged turns."""
        try:
            files = list(self.log_dir.glob("turn_*.json"))
            return f"Session {self.session_id}: {len(files)} turns logged"
        except Exception:
            return "No logs available"
