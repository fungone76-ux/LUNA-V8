"""Outfit Modifier System V5.0 - Simplified deterministic clothing changes.

Detects outfit modifications from player input (Italian patterns) and applies
them as overlay modifications (OutfitModification) on top of the base outfit.

Public API:
    process_turn(user_input, game_state, companion_def) -> (modified, is_major, desc_it)
    apply_major_change(game_state, desc_it, llm_manager) -> bool
    change_random_outfit(game_state, companion_def) -> Optional[str]
    change_custom_outfit(game_state, desc_it, llm_manager) -> str
    reset_modifications(game_state) -> None
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

import re
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from luna.core.models import GameState, OutfitState


MOD_TYPE_PATTERNS: Dict[str, List[str]] = {
    "removal": [
        r"\b(senza|scalz[ao]|nud[ao]\s+(ai\s+piedi|in\s+alto|dal\s+busto|dai\s+fianchi))\b",
        r"\b(tolt[oaie]|levat[oaie]|rimoss[oaie]|sfilat[oaie])\b",
        r"\b(si\s+togli[eè]|toglie?|togliti|togliatevi|si\s+sfila?|sfila?|sfilati|si\s+leva|leva|levati)\b",
    ],
    "added": [
        r"\b(rimess[oaie]|indossat[oaie]|mett[eoai]|calzat[oaie])\b",
        r"\b(si\s+rimett[eoa]|rimett[eoa]|indoss[ao]|riprende|si\s+rivest|cambia\s+con|sostituisce)\b",
    ],
    "wet": [
        r"\b(bagnato|bagnata|bagnati|bagnate|inzuppat[oaie]|fradici[ao])\b",
    ],
    "partial_unbuttoned": [
        r"\b(sbottonat[oaie]|slacciat[oaie]|bottoni\s+aperti)\b",
        r"\b(si\s+sbotton[a]|sbotton[a]|apr[ea]\s+(la\s+)?camicia)\b",
    ],
    "lifted": [
        r"\b(sollevat[oaie]|alzat[oaie]|upskirt|sotto\s+la\s+gonna)\b",
        r"\b(si\s+solleva|solleva|si\s+alza|alza)\b",
    ],
    "lowered": [
        r"\b(abbassati?|abbassate?|calati?|calate?|giù\s+(i|le|il|la))\b",
        r"\b(si\s+abbassa|abbassa|si\s+cala|cala)\b",
    ],
    "torn": [
        r"\b(strappat[oaie]|rott[oaie])\b",
    ],
    "pulled_down": [
        r"\b(calate|attorno\s+(alle\s+)?caviglie|arrotolat[oa])\b",
    ],
    "see_through": [
        r"\b(trasparente|trasparenti|see[\s\-]?through|visibile\s+sotto)\b",
    ],
}

MOD_APPLIES_TO: Dict[str, List[str]] = {
    "removal": ["shoes", "top", "bra", "outerwear", "bottom", "panties", "pantyhose"],
    "added": ["shoes", "top", "bra", "outerwear", "bottom", "panties", "pantyhose"],
    "wet": ["top", "bottom", "dress", "shoes"],
    "partial_unbuttoned": ["top"],
    "lifted": ["bottom", "dress"],
    "lowered": ["bottom", "panties"],
    "torn": ["pantyhose"],
    "pulled_down": ["pantyhose"],
    "see_through": ["bra", "top"],
}

COMPONENT_PATTERNS: Dict[str, List[str]] = {
    "shoes": [r"\b(scarpe?|tacchi|calzini|sandali|stivali|mocassini)\b"],
    "top": [r"\b(camicia|maglia|top|blusa|maglietta|canottiera|canotta|t-shirt)\b"],
    "bra": [r"\b(reggiseno|bra|reggipetto)\b"],
    "outerwear": [r"\b(giacca|blazer|cardigan|cappotto|giubbotto)\b"],
    "bottom": [r"\b(gonna|pantaloni|shorts|pantaloncini|jeans|pantalone)\b"],
    "panties": [r"\b(mutande|perizoma|slip|intimo)\b"],
    "pantyhose": [r"\b(calze|collant|autoreggenti|pantyhose)\b"],
    "dress": [r"\b(vestito|abito)\b"],
}

DIRECT_PHRASES: List[Dict] = [
    {"pattern": r"\b(scalz[ao]|piedi\s+nudi|senza\s+scarpe?|nud[ao]\s+ai\s+piedi)\b", "component": "shoes", "state": "removed"},
    {"pattern": r"\b(rimett[eoa]\s+(le\s+)?scarpe?|scarpe?\s+(rimesse?|ai\s+piedi))\b", "component": "shoes", "state": "added"},
    {"pattern": r"\b(upskirt|sotto\s+la\s+gonna|gonna\s+sollevata|gonna\s+alzata)\b", "component": "bottom", "state": "lifted"},
    {"pattern": r"\b(vestito\s+bagnato|abito\s+bagnato|bagnata\s+fradicia)\b", "component": "dress", "state": "wet"},
    {"pattern": r"\b(calze\s+strappate|collant\s+strappato)\b", "component": "pantyhose", "state": "torn"},
    {"pattern": r"\b(calze\s+calate|collant\s+calato|calze\s+alle\s+caviglie)\b", "component": "pantyhose", "state": "pulled_down"},
    {"pattern": r"\b(camicia\s+sbottonata|camicia\s+aperta|scollo\s+aperto)\b", "component": "top", "state": "partial_unbuttoned"},
    {"pattern": r"\b(piedi\s+scalzi|feet\s+bare|barefoot)\b", "component": "shoes", "state": "removed"},
]

# Mapping for narrative observation detection ("in pantyhose bianchi")
_NARRATIVE_COLORS: Dict[str, str] = {
    "bianco": "white", "bianca": "white", "bianchi": "white", "bianche": "white",
    "nero": "black",   "nera": "black",   "neri": "black",   "nere": "black",
    "rosso": "red",    "rossa": "red",    "rossi": "red",    "rosse": "red",
    "blu": "blue",     "azzurro": "light blue", "azzurra": "light blue",
    "verde": "green",  "verdi": "green",
    "grigio": "grey",  "grigia": "grey",  "grigi": "grey",   "grigie": "grey",
    "beige": "beige",  "marrone": "brown",
    "rosa": "pink",    "viola": "purple",
}

_NARRATIVE_COMPONENTS: Dict[str, Tuple[str, str]] = {
    # Italian keyword → (component_key, English SD term)
    "pantyhose":      ("pantyhose", "pantyhose"),
    "calze":          ("pantyhose", "stockings"),
    "collant":        ("pantyhose", "pantyhose"),
    "autoreggenti":   ("pantyhose", "thigh-high stockings"),
    "gonna":          ("bottom",    "skirt"),
    "camicia":        ("top",       "shirt"),
    "blusa":          ("top",       "blouse"),
    "scarpe":         ("shoes",     "shoes"),
    "tacchi":         ("shoes",     "high heels"),
}

MAJOR_CHANGE_PATTERNS: List[str] = [
    # Terza persona (narrazione)
    r"\b(si\s+cambia\s+(il\s+)?(vestito|abito|outfit))\b",
    r"\b(mette\s+(un\s+)?(altro|nuovo|diverso)\s+(vestito|abito|outfit|completo))\b",
    r"\b(indossa\s+(un|una)\s+(?!poco|solo|solo\s+un)(\w+\s+){0,3}(vestito|abito|outfit|completo))\b",
    # V4.9: Comandi imperativi (player dice a NPC)
    r"\b(cambiati|vestiti|rivestiti|spogliati)\b",
    r"\b(mettiti\s+(un|una|il|la|qualcosa|altro))\b",
    r"\b(togli(ti)?\s+(il\s+)?pigiama)\b",
    r"\b(togli(ti)?\s+(il\s+)?vestito)\b",
    r"\b(cambia(ti)?\s+(il\s+)?(vestito|abito|outfit))\b",
    r"\b(indossa(ti)?|metti(ti)?)\s+(il|la|un|una|lo|l['\s])\s+[\w\s]{2,40}",
    # Outfit specifici
    r"\b(vestito\s+da\s+sera|abito\s+da\s+sera|evening\s+gown)\b",
    r"\b(pigiama|pajamas|sleepwear)\b",
    r"\b(bikini|costume\s+da\s+bagno|swimsuit)\b",
    r"\b(lingerie|intimo\s+sexy|biancheria\s+intima)\b",
    r"\b(kimono|accappatoio|vestaglia)\b",
    r"\b(uniforme|divisa)\b",
]


class OutfitModifierSystem:
    """Standalone outfit modification system V5.0."""

    def __init__(self) -> None:
        self._type_compiled: Dict[str, List[re.Pattern]] = {}
        self._comp_compiled: Dict[str, List[re.Pattern]] = {}
        self._direct_compiled: List[Dict] = []
        self._major_compiled: List[re.Pattern] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        for mod_type, patterns in MOD_TYPE_PATTERNS.items():
            self._type_compiled[mod_type] = [re.compile(p, re.IGNORECASE) for p in patterns]
        for component, patterns in COMPONENT_PATTERNS.items():
            self._comp_compiled[component] = [re.compile(p, re.IGNORECASE) for p in patterns]
        for entry in DIRECT_PHRASES:
            self._direct_compiled.append(
                {
                    "pattern": re.compile(entry["pattern"], re.IGNORECASE),
                    "component": entry["component"],
                    "state": entry["state"],
                }
            )
        self._major_compiled = [re.compile(p, re.IGNORECASE) for p in MAJOR_CHANGE_PATTERNS]

    def process_turn(self, user_input: str, game_state: "GameState", companion_def=None) -> Tuple[bool, bool, str]:
        """Process a turn for outfit modifications."""
        is_major, desc_it = self._is_major_change(user_input)
        if is_major:
            return False, True, desc_it

        modified = False
        outfit = game_state.get_outfit()

        # Detect narrative component overrides ("in pantyhose bianchi", "con calze nere")
        narrative = self._detect_narrative_components(user_input)
        if narrative:
            for comp_key, comp_value in narrative.items():
                outfit.components[comp_key] = comp_value
                logger.debug(f"[OutfitModifier] Narrative component: {comp_key}={comp_value}")
            game_state.set_outfit(outfit)
            modified = True

        detected = self._detect_modifications(user_input)
        if detected:
            self._apply_modifications(outfit, detected, game_state.turn_count, companion_def)
            game_state.set_outfit(outfit)
            changed = ", ".join(f"{c}:{s}" for c, s in detected)
            logger.debug(f"[OutfitModifier] Modifications applied: {changed}")
            modified = True

        return modified, False, ""

    def _detect_narrative_components(self, text: str) -> Dict[str, str]:
        """Detect outfit components from narrative observation patterns.

        Catches player descriptions like 'in pantyhose bianchi' or
        'con calze nere' that assert what the NPC is wearing,
        even without an explicit command verb.
        """
        result: Dict[str, str] = {}
        lower = text.lower()

        for comp_word, (comp_key, comp_en) in _NARRATIVE_COMPONENTS.items():
            for color_it, color_en in _NARRATIVE_COLORS.items():
                # "in/con [color] [component]"
                p1 = rf"\b(?:in|con)\s+{re.escape(color_it)}\s+(?:\w+\s+){{0,2}}{re.escape(comp_word)}\b"
                # "in/con [component] [color]"
                p2 = rf"\b(?:in|con)\s+(?:\w+\s+){{0,2}}{re.escape(comp_word)}\s+{re.escape(color_it)}\b"
                if re.search(p1, lower) or re.search(p2, lower):
                    result[comp_key] = f"{color_en} {comp_en}"
                    break  # one color per component

        return result

    def reset_modifications(self, game_state: "GameState") -> None:
        """Clear all overlay modifications (call on phase change)."""
        outfit = game_state.get_outfit()
        if outfit.modifications:
            logger.debug(f"[OutfitModifier] Resetting {len(outfit.modifications)} modifications on phase change")
            outfit.modifications.clear()
            game_state.set_outfit(outfit)

    async def apply_major_change(self, game_state: "GameState", outfit_description_it: str, llm_manager=None) -> bool:
        """Apply a complete outfit change with optional LLM translation."""
        outfit = game_state.get_outfit()
        old_style = outfit.style

        if llm_manager:
            try:
                outfit_description_en = await self._translate_outfit(outfit_description_it, llm_manager)
            except Exception as e:
                logger.warning(f"[OutfitModifier] Translation failed, using original: {e}")
                outfit_description_en = outfit_description_it
        else:
            outfit_description_en = self._basic_translate(outfit_description_it)

        outfit.style = "custom"
        outfit.description = outfit_description_en
        outfit.base_description = outfit_description_it
        outfit.base_sd_prompt = outfit_description_en
        outfit.llm_generated_description = None
        outfit.llm_generated_sd_prompt = None
        outfit.components.clear()
        outfit.modifications.clear()
        outfit.is_special = False

        game_state.set_outfit(outfit)

        logger.info(f"[OutfitModifier] MAJOR CHANGE: {old_style} -> custom")
        logger.info(f"[OutfitModifier] IT: {outfit_description_it}")
        logger.info(f"[OutfitModifier] EN: {outfit_description_en}")
        logger.info(f"[OutfitModifier] base_sd_prompt set to: {outfit.base_sd_prompt}")
        return True

    def change_random_outfit(self, game_state: "GameState", companion_def) -> Optional[str]:
        """Change to a random wardrobe outfit."""
        if not companion_def or not getattr(companion_def, "wardrobe", None):
            return None

        import random

        outfits = list(companion_def.wardrobe.keys())
        current = game_state.get_outfit().style
        available = [o for o in outfits if o != current] or outfits

        new_outfit = random.choice(available)
        self._apply_wardrobe_outfit(game_state, new_outfit, companion_def)
        logger.debug(f"[OutfitModifier] Random change: {current} -> {new_outfit}")
        return new_outfit

    async def change_custom_outfit(self, game_state: "GameState", description_it: str, llm_manager=None) -> str:
        """Change to a custom outfit from a text description."""
        await self.apply_major_change(game_state, description_it, llm_manager)
        return game_state.get_outfit().description

    def _detect_modifications(self, text: str) -> List[Tuple[str, str]]:
        """Detect (component, state) modifications from input text."""
        detected: Dict[str, str] = {}
        lower = text.lower()

        for entry in self._direct_compiled:
            if entry["pattern"].search(lower):
                comp = entry["component"]
                if comp not in detected:
                    detected[comp] = entry["state"]

        for mod_type, type_patterns in self._type_compiled.items():
            if not any(p.search(lower) for p in type_patterns):
                continue
            allowed = MOD_APPLIES_TO.get(mod_type, [])
            for component in allowed:
                if component in detected:
                    continue
                comp_patterns = self._comp_compiled.get(component, [])
                if any(p.search(lower) for p in comp_patterns):
                    detected[component] = mod_type

        return list(detected.items())

    def _apply_modifications(self, outfit: "OutfitState", modifications: List[Tuple[str, str]], turn: int, companion_def=None) -> None:
        """Apply a list of (component, state) modifications to the outfit."""
        from luna.core.models import OutfitModification
        from luna.systems.outfit_renderer import MODIFICATION_DESCRIPTIONS_IT, MODIFICATION_DESCRIPTIONS_SD

        for component, state in modifications:
            normalized_state = "removed" if state == "removal" else state
            desc_it = MODIFICATION_DESCRIPTIONS_IT.get(component, {}).get(normalized_state, f"{component} {normalized_state}")
            desc_sd = MODIFICATION_DESCRIPTIONS_SD.get(component, {}).get(normalized_state, f"{component} {normalized_state}")

            mod = OutfitModification(
                component=component,
                state=normalized_state,
                description=desc_it,
                sd_description=desc_sd,
                applied_at_turn=turn,
            )

            if state == "added" and component in outfit.modifications:
                del outfit.modifications[component]
            else:
                outfit.modifications[component] = mod

        from luna.systems.outfit_renderer import OutfitRenderer

        outfit.description = OutfitRenderer.render_sd_prompt(outfit, companion_def)

    def _apply_wardrobe_outfit(self, game_state: "GameState", outfit_key: str, companion_def) -> None:
        """Apply a wardrobe outfit (by key) to the game state."""
        from luna.core.models import OutfitState

        wardrobe_def = companion_def.wardrobe[outfit_key]

        if isinstance(wardrobe_def, str):
            new_outfit = OutfitState(
                style=outfit_key,
                description=wardrobe_def,
                base_description=wardrobe_def,
                base_sd_prompt=wardrobe_def,
            )
        else:
            desc = getattr(wardrobe_def, "description", "") or outfit_key
            sd = getattr(wardrobe_def, "sd_prompt", "") or desc
            new_outfit = OutfitState(
                style=outfit_key,
                description=desc,
                base_description=desc,
                base_sd_prompt=sd,
                is_special=bool(getattr(wardrobe_def, "special", False)),
            )

        game_state.set_outfit(new_outfit)

    def _is_major_change(self, user_input: str) -> Tuple[bool, str]:
        """Detect if the user wants a complete outfit replacement."""
        lower = user_input.lower()
        for pattern in self._major_compiled:
            if pattern.search(lower):
                desc = self._extract_outfit_description(user_input)
                if not desc:
                    return False, ""
                return True, desc
        return False, ""

    def _extract_outfit_description(self, user_input: str) -> str:
        """Extract a concise outfit description from the user's input.

        Returns empty string if no clean description can be extracted,
        so the caller knows not to apply a major change.
        """
        patterns = [
            r"mette\s+(?:un|una)\s+(?:altro|nuovo|diverso)?\s*([\w\s]+?)(?:\s+(?:abito|vestito|outfit))?[.,!?]?$",
            r"si\s+cambia\s+(?:con\s+|in\s+)?([\w\s]+?)(?:[.,!?]|$)",
            r"vestito\s+([\w\s]+?)(?:[.,!?]|$)",
            r"abito\s+([\w\s]+?)(?:[.,!?]|$)",
            r"indossa\s+(?:un|una)?\s*([\w\s]+?)(?:[.,!?]|$)",
            r"\b(?:mettiti|metti|indossati|indossa)\s+(?:il|la|un|una|lo|l['\s])\s*([\w\s]{2,40}?)(?:[.,!?]|$)",
        ]
        lower = user_input.lower()
        for pattern in patterns:
            match = re.search(pattern, lower, re.IGNORECASE)
            if match:
                desc = match.group(1).strip()
                if len(desc) > 3:
                    return desc

        # Fallback: keyword diretta è già il nome dell'outfit
        direct_keywords = [
            "pigiama", "pajamas", "sleepwear",
            "bikini", "costume da bagno", "swimsuit",
            "lingerie", "intimo sexy", "biancheria intima",
            "kimono", "accappatoio", "vestaglia",
            "uniforme", "divisa",
            "vestito da sera", "abito da sera", "evening gown",
        ]
        for kw in direct_keywords:
            if kw in lower:
                return kw
        return ""

    async def _translate_outfit(self, description_it: str, llm_manager) -> str:
        """Translate Italian outfit description to English using LLM."""
        basic = self._basic_translate(description_it)
        try:
            prompt = (
                "Translate this clothing description from Italian to English.\n"
                "Be concise and use fashion/Stable Diffusion terminology.\n\n"
                f"Italian: {description_it}\nEnglish:"
            )
            # llm_manager.generate() returns (LLMResponse, provider_name)
            response_tuple = await llm_manager.generate(
                system_prompt="Translate Italian clothing descriptions to English concisely.",
                user_input=prompt,
                json_mode=False,
            )
            response, _ = response_tuple  # unpack (LLMResponse, provider)
            if response and response.text:
                translated = response.text.strip()
                error_indicators = [
                    "mi scusi", "errore", "spiacente", "non posso", "i'm sorry", "error", "cannot",
                ]
                if not any(ind in translated.lower() for ind in error_indicators) and len(translated) > 5:
                    return translated
        except Exception as e:
            logger.warning(f"[OutfitModifier] LLM translation failed: {e}")
        return basic

    def _basic_translate(self, text: str) -> str:
        """Basic Italian to English word substitution for common outfit terms."""
        translations = {
            "vestito": "dress",
            "abito": "dress",
            "gonna": "skirt",
            "camicia": "shirt",
            "blusa": "blouse",
            "maglia": "sweater",
            "scarpe": "shoes",
            "tacchi": "high heels",
            "calze": "stockings",
            "collant": "pantyhose",
            "reggiseno": "bra",
            "mutande": "panties",
            "perizoma": "thong",
            "giacca": "jacket",
            "blazer": "blazer",
            "cravatta": "tie",
            "rosso": "red",
            "rossa": "red",
            "blu": "blue",
            "nero": "black",
            "nera": "black",
            "bianco": "white",
            "bianca": "white",
            "bianchi": "white",
            "bianche": "white",
            "verde": "green",
            "giallo": "yellow",
            "rosa": "pink",
            "viola": "purple",
            "arancione": "orange",
            "grigio": "grey",
            "marrone": "brown",
            "elegante": "elegant",
            "sera": "evening",
            "formale": "formal",
            "casual": "casual",
            "sportivo": "sportswear",
            "sexy": "sexy",
            "mini": "mini",
            "corto": "short",
            "corta": "short",
            "lungo": "long",
            "lunga": "long",
            "aderente": "tight",
            "scollato": "low-cut",
            "scollata": "low-cut",
            "trasparente": "see-through",
            "pigiama": "pajamas",
            "bikini": "bikini",
            "kimono": "kimono",
            "lingerie": "lingerie",
            "intimo": "underwear",
            "uniforme": "uniform",
            "costume": "swimsuit",
            "da sera": "evening gown",
            "da bagno": "swimsuit",
            "da notte": "nightgown",
            "strappato": "torn",
            "strappata": "torn",
            "bagnato": "wet",
            "bagnata": "wet",
            "aperto": "open",
            "aperta": "open",
            "sbottonato": "unbuttoned",
            "sbottonata": "unbuttoned",
            "slacciato": "loose",
            "slacciata": "loose",
            "senza": "without",
            "nudo": "nude",
            "nuda": "nude",
        }

        result = text.lower()
        for it_word, en_word in translations.items():
            result = re.sub(rf"\b{re.escape(it_word)}\b", en_word, result, flags=re.IGNORECASE)

        return (result[0].upper() + result[1:]).strip() if result else result


def create_outfit_modifier() -> OutfitModifierSystem:
    """Create a new outfit modifier system instance."""
    return OutfitModifierSystem()
