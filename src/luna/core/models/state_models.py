"""Luna RPG - State Models.

Game state, player state, NPC state, and outfit state models.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from pydantic import ConfigDict, Field, field_validator

from .base import LunaBaseModel
from .enums import OutfitComponent, TimeOfDay


class OutfitModification(LunaBaseModel):
    """Single overlay modification applied on top of base outfit."""
    component: str
    state: str      # removed, wet, lifted, torn, added, partial_unbuttoned, lowered
    description: str = ""
    sd_description: str = ""
    applied_at_turn: int = Field(default=0, ge=0)


class OutfitState(LunaBaseModel):
    """Complete outfit state for a character.

    Priority for SD prompt (M4 - Outfit Coherence Engine):
    1. Explicit user input (via OutfitModification)
    2. LLM outfit_update
    3. Persistent scene outfit
    4. Schedule outfit (only on: companion switch, phase change, remote sync)
    """
    style: str = Field(default="default")
    description: str = Field(default="")
    components: Dict[str, str] = Field(default_factory=dict)
    is_special: bool = Field(default=False)
    last_updated_turn: int = Field(default=0, ge=0)

    # Base layer (from wardrobe YAML)
    base_description: str = Field(default="")
    base_sd_prompt: str = Field(default="")

    # LLM generated override
    llm_generated_description: Optional[str] = Field(default=None)
    llm_generated_sd_prompt: Optional[str] = Field(default=None)
    generated_at_turn: int = Field(default=0, ge=0)

    # Overlay modifications (component key -> modification)
    modifications: Dict[str, OutfitModification] = Field(default_factory=dict)

    def get_component(self, component: OutfitComponent | str, default: str = "") -> str:
        key = component.value if isinstance(component, OutfitComponent) else component
        return self.components.get(key, default)

    def set_component(self, component: OutfitComponent | str, value: str) -> None:
        key = component.value if isinstance(component, OutfitComponent) else component
        self.components[key] = value

    def to_prompt_string(self) -> str:
        """Human-readable description for LLM context."""
        import logging
        logger = logging.getLogger(__name__)
        
        if self.is_special:
            return f"[Special: {self.description}]"
        base = (
            self.llm_generated_description
            or self.base_description
            or self.description
            or f"wearing {self.style} clothes"
        )
        if self.modifications:
            mod_descs = [m.description for m in self.modifications.values() if m.description]
            if mod_descs:
                result = f"{base}, {', '.join(mod_descs)}"
                logger.info(f"[OutfitState.to_prompt_string] With mods: {result}")
                return result
        return base

    def to_sd_prompt(self, include_weight: bool = True) -> str:
        """Build SD prompt with M4 coherence rules.

        Rules:
        - Components are authoritative (override description)
        - Modifications overlay on top of components
        - shoes=none + pantyhose → suppress barefoot (feet covered)
        - Contradictions resolved: last modification wins per component
        """
        import logging
        logger = logging.getLogger(__name__)
        
        parts: List[str] = []

        has_pantyhose = self._has_pantyhose()
        shoes_handled = False

        # DEBUG: Log outfit state
        logger.info(f"[OutfitState.to_sd_prompt] style={self.style}, components={self.components}, base_sd_prompt={self.base_sd_prompt[:50] if self.base_sd_prompt else 'None'}...")

        # Priority 1: components from wardrobe/LLM
        if self.components:
            for key, value in self.components.items():
                if not value or value.lower() in ["n/a", "", "default"]:
                    continue
                if key == "shoes" and value.lower() in ["none", "barefoot", "removed"]:
                    shoes_handled = True
                    if not has_pantyhose:
                        parts.append("(barefoot:1.1)")
                    # if pantyhose → skip barefoot silently
                    continue
                if value.lower() == "none":
                    continue
                # Include component name in prompt for clarity (e.g., "white pantyhose" not just "white")
                # FIX: Avoid duplication if value already contains component name
                if key in ["pantyhose", "stockings", "tights"]:
                    if key.lower() not in value.lower():
                        parts.append(f"({value} {key}:1.1)")
                    else:
                        parts.append(f"({value}:1.1)")
                else:
                    parts.append(f"({value}:1.1)")

        # Priority 2: base sd_prompt (if no components defined)
        if not self.components and self.base_sd_prompt:
            parts.append(self.base_sd_prompt)

        # Priority 3: overlay modifications
        for mod_key, mod in self.modifications.items():
            if mod.state == "removed":
                # Remove the corresponding component from parts
                parts = [p for p in parts if mod_key not in p.lower()]
                if mod_key == "shoes" and not has_pantyhose:
                    parts.append("(barefoot:1.1)")
            elif mod.sd_description:
                parts.append(f"({mod.sd_description}:1.1)")

        if not parts:
            # Check if nude/special outfit - don't add casual clothes
            if self.style and self.style.lower() in ["nude", "naked", "lingerie", "nightwear"]:
                # Return base_sd_prompt for special outfits, or empty for nude
                if self.base_sd_prompt:
                    logger.info(f"[OutfitState.to_sd_prompt] Special outfit '{self.style}', using base_sd_prompt")
                    return self.base_sd_prompt
                logger.info(f"[OutfitState.to_sd_prompt] Nude outfit, returning empty")
                return ""
            logger.info(f"[OutfitState.to_sd_prompt] No parts generated, returning default")
            return "(casual clothes:1.1)"

        result = ", ".join(parts)
        logger.info(f"[OutfitState.to_sd_prompt] Generated: {result}")
        # MARKER_V2
        return result

    def _has_pantyhose(self) -> bool:
        pantyhose_words = ["pantyhose", "stockings", "tights", "calze", "collant"]
        check_in = (
            self.components.get("pantyhose", "")
            + self.description
            + self.base_sd_prompt
        ).lower()
        return any(w in check_in for w in pantyhose_words)


class PlayerState(LunaBaseModel):
    """Player character state."""
    name: str = Field(default="Protagonist")
    age: int = Field(default=18, ge=16, le=99)
    background: str = Field(default="")
    strength: int = Field(default=10, ge=0, le=100)
    mind: int = Field(default=10, ge=0, le=100)
    charisma: int = Field(default=10, ge=0, le=100)
    gold: int = Field(default=0, ge=0)
    hp: int = Field(default=20, ge=0)
    max_hp: int = Field(default=20, ge=1)
    inventory: List[str] = Field(default_factory=list)
    flags: Dict[str, Any] = Field(default_factory=dict)


class NPCState(LunaBaseModel):
    """NPC runtime state."""
    name: str
    location: str = Field(default="Unknown")
    outfit: OutfitState = Field(default_factory=OutfitState)
    affinity: int = Field(default=0, ge=0, le=100)
    emotional_state: str = Field(default="default")
    # v8: TTL tracking — turn when emotional_state was last forced by quest/guardian
    emotional_state_set_turn: int = Field(default=0, ge=0)
    last_interaction_turn: int = Field(default=0, ge=0)
    flags: Dict[str, Any] = Field(default_factory=dict)


class GameState(LunaBaseModel):
    """Complete runtime state of a game session.

    If you serialize this, you've saved everything.
    If you deserialize it, you've restored the exact game moment.
    """
    model_config = ConfigDict(from_attributes=True)

    session_id: Optional[int] = None
    world_id: str

    # Time & Space
    turn_count: int = Field(default=0, ge=0)
    time_of_day: TimeOfDay = Field(default=TimeOfDay.MORNING)
    current_location: str = Field(default="Unknown")

    # Companion
    active_companion: str
    companion_outfits: Dict[str, OutfitState] = Field(default_factory=dict)

    # V5: Companion persistence flags
    companion_staying_with_player: bool = Field(default=False)
    companion_invited_to_location: Optional[str] = Field(default=None)

    # NPC actual locations (overrides schedule when set)
    npc_locations: Dict[str, str] = Field(default_factory=dict)
    # Optional TTL for each override: npc_name -> turn at which override expires (0 = permanent)
    npc_location_expires: Dict[str, int] = Field(default_factory=dict)

    # Player
    player: PlayerState = Field(default_factory=PlayerState)
    npc_states: Dict[str, NPCState] = Field(default_factory=dict)

    # Relationships
    affinity: Dict[str, int] = Field(default_factory=dict)

    # Quests
    active_quests: List[str] = Field(default_factory=list)
    completed_quests: List[str] = Field(default_factory=list)
    failed_quests: List[str] = Field(default_factory=list)
    quest_flags: Dict[str, Any] = Field(default_factory=dict)

    # General flags
    flags: Dict[str, Any] = Field(default_factory=dict)

    # Metadata
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @field_validator("time_of_day", mode="before")
    @classmethod
    def parse_time_of_day(cls, v: Any) -> TimeOfDay:
        """Convert string to TimeOfDay enum during deserialization."""
        if isinstance(v, str):
            return TimeOfDay(v)
        return v

    @field_validator("affinity")
    @classmethod
    def clamp_affinity(cls, v: Dict[str, int]) -> Dict[str, int]:
        return {k: max(0, min(100, val)) for k, val in v.items()}

    # --- Outfit helpers ---

    def get_outfit(self, companion_name: Optional[str] = None) -> OutfitState:
        name = companion_name or self.active_companion
        if name not in self.companion_outfits:
            self.companion_outfits[name] = OutfitState()
        return self.companion_outfits[name]

    def set_outfit(self, outfit: OutfitState, companion_name: Optional[str] = None) -> None:
        name = companion_name or self.active_companion
        self.companion_outfits[name] = outfit

    def get_active_outfit_description(self) -> str:
        return self.get_outfit().to_prompt_string()

    # --- NPC location helpers ---

    def get_npc_location(self, npc_name: str) -> Optional[str]:
        """Get location override for NPC (invited/summoned). None = use schedule."""
        return self.npc_locations.get(npc_name)

    def set_npc_location(self, npc_name: str, location: str, ttl_turns: int = 0) -> None:
        """Set location override. ttl_turns > 0 means it expires after that many turns from now."""
        if ttl_turns > 0:
            self.npc_location_expires[npc_name] = self.turn_count + ttl_turns
        else:
            self.npc_location_expires.pop(npc_name, None)
        self.npc_locations[npc_name] = location

    def clear_npc_location(self, npc_name: str) -> None:
        self.npc_locations.pop(npc_name, None)
        self.npc_location_expires.pop(npc_name, None)

    def purge_expired_npc_locations(self) -> List[str]:
        """Remove location overrides whose TTL has elapsed. Returns list of purged NPC names."""
        expired = [
            npc for npc, expires_at in self.npc_location_expires.items()
            if expires_at > 0 and self.turn_count >= expires_at
        ]
        for npc in expired:
            self.npc_locations.pop(npc, None)
            self.npc_location_expires.pop(npc, None)
        return expired
