"""Outfit Renderer - Generates final outfit descriptions from OutfitState.

Combines the base outfit with overlay modifications to produce:
- Italian description for LLM context
- English SD prompt for image generation
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from luna.core.models import OutfitState


MODIFICATION_DESCRIPTIONS_IT: dict[str, dict[str, str]] = {
    "shoes": {
        "removed": "piedi nudi",
        "wet": "scarpe bagnate",
        "added": "scarpe ai piedi",
    },
    "top": {
        "removed": "seno nudo, senza top",
        "partial_unbuttoned": "camicia sbottonata, scollatura visibile",
        "wet": "top bagnato trasparente",
        "added": "top indossato",
    },
    "bra": {
        "removed": "senza reggiseno, seno libero",
        "see_through": "reggiseno visibile sotto il tessuto",
        "added": "reggiseno indossato",
    },
    "outerwear": {
        "removed": "senza giacca",
        "added": "giacca indossata",
    },
    "bottom": {
        "removed": "gambe nude, senza gonna/pantaloni",
        "lifted": "gonna sollevata, cosce scoperte",
        "lowered": "pantaloni abbassati",
        "wet": "gonna/pantaloni bagnati",
        "added": "gonna/pantaloni indossati",
    },
    "panties": {
        "removed": "senza mutande",
        "lowered": "mutande abbassate",
        "added": "mutande indossate",
    },
    "pantyhose": {
        "removed": "gambe nude, senza collant",
        "torn": "collant strappati, smagliature sulle cosce",
        "pulled_down": "collant abbassati attorno alle caviglie",
        "added": "collant indossati",
    },
    "dress": {
        "wet": "vestito bagnato trasparente",
        "open": "vestito aperto sul davanti",
        "lifted": "vestito sollevato, fianchi scoperti",
    },
}


MODIFICATION_DESCRIPTIONS_SD: dict[str, dict[str, str]] = {
    "shoes": {
        "removed": "barefoot, bare feet visible",
        "wet": "wet shoes",
        "added": "shoes on",
    },
    "top": {
        "removed": "topless, bare chest",
        "partial_unbuttoned": "unbuttoned shirt, cleavage visible",
        "wet": "wet shirt, see-through fabric clinging to skin",
        "added": "shirt on",
    },
    "bra": {
        "removed": "no bra, breasts free",
        "see_through": "bra visible through wet fabric",
        "added": "bra on",
    },
    "outerwear": {
        "removed": "no jacket",
        "added": "jacket on",
    },
    "bottom": {
        "removed": "bottomless, bare legs",
        "lifted": "skirt lifted high, thighs exposed",
        "lowered": "pants pulled down",
        "wet": "wet skirt or pants",
        "added": "skirt or pants on",
    },
    "panties": {
        "removed": "no panties",
        "lowered": "panties pulled down",
        "added": "panties on",
    },
    "pantyhose": {
        "removed": "bare legs, no stockings",
        "torn": "torn black pantyhose, runs on thighs",
        "pulled_down": "pantyhose pulled down around ankles",
        "added": "pantyhose on",
    },
    "dress": {
        "wet": "wet dress, see-through clinging fabric",
        "open": "dress unzipped, open front",
        "lifted": "dress lifted up, gathered at waist",
    },
}


COMPONENT_CLEANUP_PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "it": {
        "shoes": (
            r"\btacchi\s+alti\b",
            r"\btacchi\b",
            r"\bscarpe\b",
            r"\bcalzature\b",
            r"\bsandali\b",
            r"\bstivali\b",
            r"\bmocassini\b",
            r"\bsneakers\b",
        ),
        "top": (
            r"\bcamicia\b",
            r"\bcamicetta\b",
            r"\bblusa\b",
            r"\btop\b",
            r"\bblouse\b",
            r"\bshirt\b",
        ),
        "bra": (
            r"\breggiseno\b",
            r"\bbralette\b",
            r"\bbra\b",
        ),
        "outerwear": (
            r"\bgiacca\b",
            r"\bblazer\b",
            r"\bcardigan\b",
            r"\bcappotto\b",
            r"\bgiacchino\b",
        ),
        "bottom": (
            r"\bgonna\b",
            r"\bgonna\s+a\s+tubino\b",
            r"\bpantaloni\b",
            r"\bshorts\b",
            r"\bjeans\b",
            r"\bminigonna\b",
        ),
        "panties": (
            r"\bmutande\b",
            r"\bslip\b",
            r"\bperizoma\b",
        ),
        "pantyhose": (
            r"\bcollant\b",
            r"\bcalze\b",
            r"\bautoreggenti\b",
            r"\bcalze\s+velate\b",
        ),
        "dress": (
            r"\bvestito\b",
            r"\babito\b",
            r"\bdress\b",
            r"\bgown\b",
        ),
    },
    "sd": {
        "shoes": (
            r"\belegant\s+high\s+heels\b",
            r"\bhigh\s+heels\b",
            r"\bheels\b",
            r"\bshoes\b",
            r"\bfootwear\b",
            r"\bboots\b",
            r"\bsandals\b",
            r"\bloafers\b",
            r"\bsneakers\b",
        ),
        "top": (
            r"\bbutton-up\s+blouse\b",
            r"\bblouse\b",
            r"\bshirt\b",
            r"\btop\b",
            r"\bcamisole\b",
            r"\bcrop\s+top\b",
        ),
        "bra": (
            r"\bbra\b",
            r"\bbralette\b",
        ),
        "outerwear": (
            r"\bjacket\b",
            r"\bblazer\b",
            r"\bcardigan\b",
            r"\bcoat\b",
        ),
        "bottom": (
            r"\bpencil\s+skirt\b",
            r"\bskirt\b",
            r"\bpants\b",
            r"\btrousers\b",
            r"\bshorts\b",
            r"\bjeans\b",
            r"\bminiskirt\b",
        ),
        "panties": (
            r"\bpanties\b",
            r"\bunderwear\b",
            r"\bthong\b",
            r"\bbriefs\b",
        ),
        "pantyhose": (
            r"\bpantyhose\b",
            r"\bstockings\b",
            r"\btights\b",
            r"\bnylons\b",
        ),
        "dress": (
            r"\bdress\b",
            r"\bgown\b",
        ),
    },
}

STRIP_BASE_COMPONENT_STATES = {
    "removed",
    "wet",
    "partial_unbuttoned",
    "see_through",
    "lifted",
    "lowered",
    "torn",
    "pulled_down",
    "open",
}


class OutfitRenderer:
    """Renders descriptions by combining base outfit and active modifications."""

    @staticmethod
    def render_description(outfit: "OutfitState", companion_def=None) -> str:
        if outfit.is_special:
            return (
                outfit.llm_generated_description
                or outfit.base_description
                or outfit.description
                or f"special state: {outfit.style}"
            )

        base = OutfitRenderer._get_base_description_it(outfit, companion_def)
        base = OutfitRenderer._strip_removed_component_from_text(base, outfit, language="it")
        
        parts = []
        
        # Include components (e.g., white pantyhose added by player)
        if outfit.components:
            for comp_key, comp_value in outfit.components.items():
                if comp_value and comp_value.lower() not in ["n/a", "none", "", "default"]:
                    # Translate component key to Italian
                    comp_name_it = {
                        "pantyhose": "collant",
                        "shoes": "scarpe",
                        "top": "top",
                        "bottom": "gonna/pantaloni",
                        "bra": "reggiseno",
                        "panties": "mutande",
                    }.get(comp_key, comp_key)
                    parts.append(f"{comp_value} {comp_name_it}")
        
        # Include modifications
        if outfit.modifications:
            mod_parts = OutfitRenderer._build_exposure_summary(outfit, language="it")
            mod_parts.extend(m.description for m in outfit.modifications.values() if m.description)
            parts.extend(mod_parts)
        
        parts = OutfitRenderer._dedupe_parts(parts)
        if parts:
            return OutfitRenderer._join_base_and_parts(base, parts)
        return base

    @staticmethod
    def render_sd_prompt(outfit: "OutfitState", companion_def=None) -> str:
        if outfit.is_special:
            return (
                outfit.llm_generated_sd_prompt
                or outfit.base_sd_prompt
                or outfit.description
                or outfit.style
            )

        base = OutfitRenderer._get_base_sd_prompt(outfit, companion_def)
        base = OutfitRenderer._strip_removed_component_from_text(base, outfit, language="sd")
        
        parts = []
        
        # Include components with proper formatting
        if outfit.components:
            for comp_key, comp_value in outfit.components.items():
                if comp_value and comp_value.lower() not in ["n/a", "none", "", "default"]:
                    # Avoid duplication if value already contains component name
                    if comp_key.lower() not in comp_value.lower():
                        parts.append(f"{comp_value} {comp_key}")
                    else:
                        parts.append(comp_value)
        
        # Include modifications
        if outfit.modifications:
            mod_parts = OutfitRenderer._build_exposure_summary(outfit, language="sd")
            for component, mod in outfit.modifications.items():
                sd_desc = mod.sd_description or MODIFICATION_DESCRIPTIONS_SD.get(component, {}).get(
                    mod.state, mod.description
                )
                if sd_desc:
                    mod_parts.append(sd_desc)
            parts.extend(mod_parts)
        
        parts = OutfitRenderer._dedupe_parts(parts)
        if parts:
            return OutfitRenderer._join_base_and_parts(base, parts)
        return base

    @staticmethod
    def _join_base_and_parts(base: str, parts: list[str]) -> str:
        parts = [part.strip() for part in parts if part and part.strip()]
        if base and parts:
            return f"{base}, {', '.join(parts)}"
        if parts:
            return ", ".join(parts)
        return base

    @staticmethod
    def _dedupe_parts(parts: list[str]) -> list[str]:
        unique_parts: list[str] = []
        seen: set[str] = set()
        for part in parts:
            normalized = re.sub(r"\s+", " ", part.strip().lower())
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_parts.append(part.strip())
        return unique_parts

    @staticmethod
    def _build_exposure_summary(outfit: "OutfitState", language: str = "sd") -> list[str]:
        if not outfit.modifications:
            return []

        states = {component: mod.state for component, mod in outfit.modifications.items()}
        top_removed = states.get("top") == "removed"
        bra_removed = states.get("bra") == "removed"
        bottom_removed = states.get("bottom") == "removed"
        panties_removed = states.get("panties") == "removed"

        upper_nude = top_removed and bra_removed
        lower_nude = bottom_removed and panties_removed

        if language == "it":
            if upper_nude and lower_nude:
                return ["completamente nuda"]
            if upper_nude:
                return ["a torso nudo"]
            if lower_nude:
                return ["parte inferiore completamente nuda"]
            return []

        if upper_nude and lower_nude:
            return ["fully nude", "naked"]
        if upper_nude:
            return ["topless"]
        if lower_nude:
            return ["bottomless"]
        return []

    @staticmethod
    def _get_base_description_it(outfit: "OutfitState", companion_def=None) -> str:
        if outfit.llm_generated_description:
            return outfit.llm_generated_description
        if outfit.base_description:
            return outfit.base_description
        if outfit.description:
            return outfit.description
        if companion_def and getattr(companion_def, "wardrobe", None):
            wardrobe_def = companion_def.wardrobe.get(outfit.style)
            if wardrobe_def is not None:
                if isinstance(wardrobe_def, str):
                    return wardrobe_def
                return getattr(wardrobe_def, "description", "") or outfit.style
        return f"{outfit.style} outfit"

    @staticmethod
    def _get_base_sd_prompt(outfit: "OutfitState", companion_def=None) -> str:
        if outfit.llm_generated_sd_prompt:
            return outfit.llm_generated_sd_prompt
        if outfit.base_sd_prompt:
            return outfit.base_sd_prompt
        if companion_def and getattr(companion_def, "wardrobe", None):
            wardrobe_def = companion_def.wardrobe.get(outfit.style)
            if wardrobe_def is not None:
                if isinstance(wardrobe_def, str):
                    return wardrobe_def
                return (
                    getattr(wardrobe_def, "sd_prompt", "")
                    or getattr(wardrobe_def, "description", "")
                    or outfit.style
                )
        if outfit.description:
            return outfit.description
        return f"{outfit.style} outfit"

    @staticmethod
    def _strip_removed_component_from_text(text: str, outfit: "OutfitState", language: str = "sd") -> str:
        """Remove contradictory base fragments when a component was altered by an overlay."""
        if not text or not outfit.modifications:
            return text

        cleanup_patterns = COMPONENT_CLEANUP_PATTERNS.get(language, COMPONENT_CLEANUP_PATTERNS["sd"])
        joiner = " e " if language == "it" else " and "
        chunks = [chunk.strip() for chunk in re.split(r"[;,]", text) if chunk.strip()]
        filtered_chunks = []

        for chunk in chunks:
            filtered_chunk = OutfitRenderer._filter_chunk_for_modified_components(
                chunk,
                outfit,
                cleanup_patterns,
                joiner,
            )
            if filtered_chunk:
                filtered_chunks.append(filtered_chunk)

        cleaned = ", ".join(filtered_chunks)
        cleaned = re.sub(r"\s*,\s*,+", ", ", cleaned)
        cleaned = re.sub(r"^\s*,\s*", "", cleaned)
        cleaned = re.sub(r"\s*,\s*$", "", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def _filter_chunk_for_modified_components(
        chunk: str,
        outfit: "OutfitState",
        cleanup_patterns: dict[str, tuple[str, ...]],
        joiner: str,
    ) -> str:
        modified_components = {
            component
            for component, mod in outfit.modifications.items()
            if mod.state in STRIP_BASE_COMPONENT_STATES
        }
        if not modified_components:
            return chunk.strip()

        chunk_parts = [part.strip() for part in re.split(r"\s+(?:and|e)\s+", chunk) if part.strip()]
        if len(chunk_parts) > 1:
            kept_parts = [
                part for part in chunk_parts
                if not OutfitRenderer._part_matches_modified_component(part, modified_components, cleanup_patterns)
            ]
            if kept_parts:
                return joiner.join(kept_parts).strip()
            return ""

        if OutfitRenderer._part_matches_modified_component(chunk, modified_components, cleanup_patterns):
            return ""
        return chunk.strip()

    @staticmethod
    def _part_matches_modified_component(
        text: str,
        modified_components: set[str],
        cleanup_patterns: dict[str, tuple[str, ...]],
    ) -> bool:
        for component in modified_components:
            patterns = cleanup_patterns.get(component, ())
            if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
                return True
        return False

