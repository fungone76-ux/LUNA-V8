"""Luna RPG V5 - M4: Outfit Coherence Engine.

Single authority for outfit state. Resolves all outfit changes with
explicit priority rules. No contradictions in SD prompt output.

Priority (highest → lowest):
1. Explicit user input (OutfitOverlayIntent from user)
2. LLM outfit_update in response
3. Persistent scene outfit (no change)
4. Schedule outfit (ONLY on: companion switch, phase change, remote sync)

Anti-contradiction rules:
- shoes=removed + pantyhose → suppress barefoot (feet covered)
- shoes=removed, no pantyhose → add barefoot
- special outfit (towel, nude) → clear all other components
- modifications accumulate (overlay), components replace

All SD prompt building goes through OutfitEngine.to_sd_prompt().
No other module may build outfit SD prompts directly.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from luna.core.models import (
    CompanionDefinition,
    GameState,
    OutfitModification,
    OutfitState,
    OutfitUpdate,
    WardrobeDefinition,
)
from luna.systems.input_intent import OutfitOverlayIntent, OutfitMajorIntent

logger = logging.getLogger(__name__)


# =============================================================================
# Component modification descriptions (Italian + SD)
# =============================================================================

_MOD_DESCRIPTIONS = {
    ("shoes", "removed"): ("piedi nudi", "barefoot"),
    ("pantyhose", "removed"): ("senza calze", "no pantyhose, bare legs"),
    ("bottom", "removed"): ("senza gonna/pantaloni", "bottomless"),
    ("top", "removed"): ("senza camicia", "topless"),
    ("bra", "removed"): ("senza reggiseno", "no bra"),
    ("panties", "removed"): ("senza mutande", "no panties"),
    ("bottom", "lifted"): ("gonna sollevata", "skirt lifted, thighs exposed"),
    ("top", "partial_unbuttoned"): ("camicia sbottonata", "partially unbuttoned shirt, visible cleavage"),
    ("top", "wet"): ("camicia bagnata", "wet shirt, see-through"),
    ("pantyhose", "torn"): ("calze strappate", "torn stockings, runs on thighs"),
    ("bottom", "lowered"): ("pantaloni abbassati", "pants lowered"),
}


class OutfitEngine:
    """Manages outfit state with explicit priority and coherence rules.

    One instance per GameEngine. Stateless between turns - all state
    lives in GameState.companion_outfits.
    """

    def __init__(self) -> None:
        pass

    # -------------------------------------------------------------------------
    # Priority 1: Apply user overlay intent
    # -------------------------------------------------------------------------

    def apply_overlay_intent(
        self,
        intent: OutfitOverlayIntent,
        game_state: GameState,
        turn_number: int,
    ) -> OutfitState:
        """Apply a partial modification from user input."""
        outfit = game_state.get_outfit()
        key = f"{intent.component}_{intent.state}"
        desc_it, desc_sd = _MOD_DESCRIPTIONS.get(
            (intent.component, intent.state),
            (f"{intent.component} {intent.state}", f"{intent.component} {intent.state}"),
        )
        mod = OutfitModification(
            component=intent.component,
            state=intent.state,
            description=desc_it,
            sd_description=desc_sd,
            applied_at_turn=turn_number,
        )
        outfit.modifications[intent.component] = mod
        outfit.last_updated_turn = turn_number
        logger.debug("Overlay applied: %s → %s (turn %d)", intent.component, intent.state, turn_number)
        return outfit

    # -------------------------------------------------------------------------
    # Priority 2: Apply LLM outfit_update
    # -------------------------------------------------------------------------

    def apply_llm_update(
        self,
        update: OutfitUpdate,
        game_state: GameState,
        companion_def: Optional[CompanionDefinition],
        turn_number: int,
    ) -> OutfitState:
        """Apply outfit changes from LLM response."""
        outfit = game_state.get_outfit()

        if update.style and companion_def:
            # Switch to a wardrobe style
            wardrobe_entry = self._get_wardrobe(companion_def, update.style)
            if wardrobe_entry:
                outfit.style = update.style
                outfit.base_description = wardrobe_entry.description
                outfit.base_sd_prompt = wardrobe_entry.sd_prompt
                outfit.is_special = wardrobe_entry.special
                outfit.modifications.clear()  # New outfit → clear overlays
                outfit.llm_generated_description = None
                outfit.llm_generated_sd_prompt = None
                logger.debug("LLM outfit style → %s", update.style)

        if update.description:
            outfit.llm_generated_description = update.description

        if update.modify_components:
            for component, value in update.modify_components.items():
                outfit.set_component(component, value)

        if update.is_special is not None:
            outfit.is_special = update.is_special

        outfit.last_updated_turn = turn_number
        return outfit

    # -------------------------------------------------------------------------
    # Priority 4: Apply schedule outfit (only on allowed triggers)
    # -------------------------------------------------------------------------

    def apply_schedule_outfit(
        self,
        style: str,
        companion_def: CompanionDefinition,
        game_state: GameState,
        turn_number: int,
        respect_modifications: bool = False,
    ) -> OutfitState:
        """Apply outfit from schedule. Clears modifications unless respect_modifications=True.

        respect_modifications=True: skip reset if the outfit has explicit player/LLM changes.
        Use this on companion-switch and summon so nakedness/modifications survive re-focus.
        Use False (default) on location-change so the NPC dresses appropriately for the new place.
        """
        outfit = game_state.get_outfit(companion_def.name)

        # If modifications exist and we should respect them, keep current outfit as-is
        if respect_modifications and (outfit.modifications or outfit.llm_generated_description):
            logger.debug(
                "Schedule outfit skipped for %s (modifications active, respect_modifications=True)",
                companion_def.name,
            )
            return outfit

        wardrobe_entry = self._get_wardrobe(companion_def, style)
        if wardrobe_entry:
            outfit.style = style
            outfit.base_description = wardrobe_entry.description
            outfit.base_sd_prompt = wardrobe_entry.sd_prompt
            outfit.is_special = wardrobe_entry.special
            outfit.modifications.clear()
            outfit.llm_generated_description = None
            outfit.llm_generated_sd_prompt = None
        else:
            outfit.style = style
        outfit.last_updated_turn = turn_number
        logger.debug("Schedule outfit applied: %s (turn %d)", style, turn_number)
        return outfit

    # -------------------------------------------------------------------------
    # SD Prompt Builder (single authority)
    # -------------------------------------------------------------------------

    def to_sd_prompt(self, outfit: OutfitState) -> str:
        """Build SD prompt with coherence rules.

        This is the ONLY place that converts OutfitState to an SD string.
        No other module should build outfit SD prompts.
        """
        if outfit.is_special:
            return outfit.base_sd_prompt or outfit.description or "(special outfit:1.1)"

        parts: List[str] = []
        has_pantyhose = self._has_pantyhose(outfit)
        handled_components: set = set()

        # Check for removal modifications first
        removed_components = {
            mod.component
            for mod in outfit.modifications.values()
            if mod.state == "removed"
        }

        # Build from base_sd_prompt if no structured components
        if outfit.base_sd_prompt and not outfit.components:
            base = outfit.base_sd_prompt
            # Remove references to removed components
            for comp in removed_components:
                base = self._remove_component_from_prompt(base, comp)
            if base.strip():
                parts.append(base.strip())
        else:
            # Build from structured components
            for key, value in outfit.components.items():
                if key in removed_components:
                    continue
                if not value or value.lower() in ["n/a", "", "default", "none"]:
                    continue
                if key == "shoes" and value.lower() in ["none", "barefoot", "removed"]:
                    handled_components.add("shoes")
                    if not has_pantyhose:
                        parts.append("(barefoot:1.1)")
                    continue
                parts.append(f"({value}:1.1)")
                handled_components.add(key)

        # Apply non-removal modifications
        for comp, mod in outfit.modifications.items():
            if mod.state == "removed":
                if comp == "shoes" and not has_pantyhose and "barefoot" not in " ".join(parts):
                    parts.append("(barefoot:1.1)")
            elif mod.sd_description:
                # Remove the original component if present
                parts = [p for p in parts if comp.lower() not in p.lower()]
                parts.append(f"({mod.sd_description}:1.1)")

        # Pantyhose anti-contradiction: if shoes are removed but pantyhose present
        if "shoes" in removed_components and has_pantyhose:
            # Remove any barefoot that slipped in
            parts = [p for p in parts if "barefoot" not in p.lower()]

        if not parts:
            # Check if nude outfit based on description or base_sd_prompt
            outfit_text = (outfit.description + " " + outfit.base_sd_prompt).lower()
            if any(word in outfit_text for word in ["nude", "naked", "nudo", "nuda", "spogli", "senza vestiti"]):
                return "nude, naked, completely naked"  # Return nude prompt
            return "(casual clothes:1.1)"

        return ", ".join(parts)

    # -------------------------------------------------------------------------
    # LLM Context String
    # -------------------------------------------------------------------------

    def to_context_string(self, outfit: OutfitState) -> str:
        """Human-readable description for LLM prompt context."""
        return outfit.to_prompt_string()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_wardrobe(
        self, companion_def: CompanionDefinition, style: str
    ) -> Optional[WardrobeDefinition]:
        entry = companion_def.wardrobe.get(style)
        if entry is None:
            return None
        if isinstance(entry, dict):
            try:
                return WardrobeDefinition(**entry)
            except Exception:
                return None
        if isinstance(entry, WardrobeDefinition):
            return entry
        return None

    def _has_pantyhose(self, outfit: OutfitState) -> bool:
        pantyhose_words = ["pantyhose", "stockings", "tights", "calze", "collant"]
        # Check if pantyhose is explicitly removed
        if outfit.modifications.get("pantyhose", None):
            if outfit.modifications["pantyhose"].state == "removed":
                return False
        check_in = (
            outfit.components.get("pantyhose", "")
            + " " + outfit.base_sd_prompt
            + " " + outfit.description
        ).lower()
        return any(w in check_in for w in pantyhose_words)

    def _remove_component_from_prompt(self, prompt: str, component: str) -> str:
        """Remove references to a component from a free-text SD prompt."""
        component_keywords = {
            "shoes": ["high heels", "heels", "shoes", "boots", "sandals", "sneakers"],
            "top": ["blouse", "shirt", "top", "sweater"],
            "bottom": ["skirt", "pants", "trousers", "shorts"],
            "bra": ["bra"],
            "panties": ["panties", "underwear"],
            "pantyhose": ["pantyhose", "stockings", "tights"],
        }
        keywords = component_keywords.get(component, [component])
        for kw in keywords:
            prompt = re.sub(rf"\b{re.escape(kw)}\b[^,]*,?\s*", "", prompt, flags=re.IGNORECASE)
        return re.sub(r",\s*,", ",", prompt).strip(", ")
