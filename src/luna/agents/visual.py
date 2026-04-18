"""Luna RPG v6 - Visual Director Agent.

Receives NarrativeOutput and builds the final SD prompt for ComfyUI.

Responsibilities:
- Assemble positive prompt: base_prompt + outfit + visual_en + tags + composition
- Assemble negative prompt (fixed blocks + scene-specific)
- Select LoRA clothing based on outfit state
- Choose image dimensions from aspect_ratio
- Handle multi-character scenes (anti-fusion)

LLM is called ONLY for composition selection when scene context
is complex enough to warrant it. Otherwise deterministic.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from luna.core.models import (
    CompanionDefinition, GameState, NarrativeOutput,
    OutfitState, VisualOutput, WorldDefinition,
)
from luna.media.lora_mapping import CLOTHING_LORAS

logger = logging.getLogger(__name__)


# =============================================================================
# Static negative prompt blocks
# =============================================================================

_NEGATIVE_BASE = (
    "score_1, score_2, score_3, score_4, "
    "(worst quality, low quality:1.4), "
    "(deformed, distorted, disfigured:1.3), "
    "bad anatomy, wrong anatomy, extra limb, missing limb, "
    "(mutated hands and fingers:1.4), disconnected limbs, "
    "mutation, mutated, ugly, disgusting, blurry, amputation, "
    "text, watermark, signature, username, "
    "monochrome, greyscale, "
    "glasses, eyeglasses, spectacles, sunglasses, monocle, goggles, eyewear"
)

_NEGATIVE_MULTI_CHAR = (
    "(merged bodies:1.4), (fused characters:1.4), "
    "(same face:1.3), matching outfits, "
    "extra heads, cloned face, extra limbs"
)

# =============================================================================
# Dimensions by aspect ratio
# =============================================================================

_DIMENSIONS: Dict[str, Tuple[int, int]] = {
    "portrait":  (896, 1152),
    "landscape": (1152, 896),
    "square":    (1024, 1024),
}

# =============================================================================
# Composition → SD tags mapping
# =============================================================================

_COMPOSITION_TAGS: Dict[str, str] = {
    # Body shots — legs
    "cowboy_shot":        "cowboy shot, from thighs up, (legs focus:1.2), shapely legs",
    "from_below":         "from below, low angle shot, (legs focus:1.3), upward view",
    "legs_closeup":       "close-up, (legs focus:1.4), thighs, from waist down",
    "thighs_shot":        "from waist down, (thighs focus:1.3), legs visible",
    "sitting_legs":       "sitting pose, legs crossed, (legs focus:1.2), from knees up",
    # Body shots — ass / rear
    "from_behind":        "from behind, rear view, (ass focus:1.2), (legs focus:1.1)",
    "over_shoulder":      "over shoulder shot, from behind, (ass focus:1.1), rear view",
    "bent_over":          "from behind, bending forward, (ass focus:1.3)",
    # Body shots — breasts / torso
    "medium_shot":        "upper body, (breast focus:1.2), cleavage",
    "chest_closeup":      "close-up, (breast focus:1.3), cleavage, chest focus",
    "three_quarter":      "three quarter view, upper body, (breast focus:1.1)",
    # Body shots — feet
    "full_body":          "full body, full figure, head to toe",
    "feet_focus":         "full body, (feet focus:1.3), bare feet, from below",
    "floor_level":        "floor level shot, feet and legs, (feet focus:1.2)",
    # Dynamic / angles
    "from_behind":        "from behind, rear view, (ass focus:1.2), (legs focus:1.1)",
    "dutch_angle":        "dutch angle, dynamic composition",
    "from_above":         "from above, high angle shot, bird eye view",
    "profile":            "profile, side view, (side view:1.1)",
    "diagonal":           "diagonal composition, three quarter angle",
    # Face / bust (20% pool)
    "close_up":           "close-up, face focus, (face focus:1.2), detailed face",
    "bust_shot":          "bust shot, from shoulders up, (face focus:1.1)",
    "over_shoulder_face": "over shoulder shot, looking back, (face focus:1.1)",
    # Wide
    "wide_shot":          "wide shot, establishing shot, full environment",
}

# Per-companion tags that must NEVER appear in positive prompt
_COMPANION_FORBIDDEN_TAGS: Dict[str, List[str]] = {
    "Luna":  ["glasses", "eyeglasses", "spectacles", "reading glasses",
               "sunglasses", "rimless glasses", "round glasses", "thin glasses"],
    "Stella": [],
    "Maria":  [],
}

# Global forbidden tags for ALL characters (including NPCs) - Rule 8: NO GLASSES
_GLOBAL_FORBIDDEN_TAGS: List[str] = [
    "glasses", "eyeglasses", "spectacles", "reading glasses", "sunglasses",
    "rimless glasses", "round glasses", "thin glasses", "monocle", "goggles"
]

# Per-companion extra negative tags
_COMPANION_EXTRA_NEGATIVE: Dict[str, str] = {
    "Luna":  "glasses, eyeglasses, spectacles, reading glasses",
    "Stella": "",
    "Maria":  "",
}

# =============================================================================
# Clothing LoRA selection
# =============================================================================

# Clothing LoRA selection uses CLOTHING_LORAS from lora_mapping.py (real CivitAI names)


# =============================================================================
# Visual Director
# =============================================================================

class VisualDirector:
    """Builds ComfyUI-ready prompts from NarrativeOutput.

    Single responsibility: take what the NarrativeEngine produced
    and assemble the exact strings ComfyUI needs.
    """

    def __init__(self, world: WorldDefinition) -> None:
        self.world = world
        # Composition continuity — last N compositions per companion
        self._composition_history: Dict[str, List[str]] = {}
        self._max_history = 6  # Max lookback window
        self._max_repeat = 1   # Max times same composition can appear in window

    def build(
        self,
        narrative: NarrativeOutput,
        game_state: GameState,
        llm_manager: Optional[Any] = None,
        lora_enabled: bool = True,
    ) -> VisualOutput:
        """Build VisualOutput from NarrativeOutput + game state.

        Args:
            narrative:    Output from NarrativeEngine
            game_state:   Current game state (outfit, location etc.)
            llm_manager:  Optional LLM for complex composition (not used for basic scenes)

        Returns:
            VisualOutput ready for ComfyUI
        """
        companion = self.world.companions.get(game_state.active_companion)
        outfit    = game_state.get_outfit(game_state.active_companion)
        secondary = narrative.secondary_characters or []

        # Quando active_companion è un NPC template (non companion), il companion
        # reale potrebbe trovarsi tra i secondari. Recuperarlo e swappare i ruoli
        # visivi così il companion rimane il focal point dell'immagine.
        visual_active = game_state.active_companion
        if not companion and self.world.npc_templates.get(game_state.active_companion):
            for sec_name in secondary:
                sec_comp = self.world.companions.get(sec_name)
                if sec_comp:
                    companion = sec_comp
                    outfit    = game_state.get_outfit(sec_name)
                    visual_active = sec_name
                    # NPC attivo diventa secondario se non già presente
                    if game_state.active_companion not in secondary:
                        secondary = [game_state.active_companion] + [
                            s for s in secondary if s != sec_name
                        ]
                    else:
                        secondary = [game_state.active_companion] + [
                            s for s in secondary if s != sec_name and s != game_state.active_companion
                        ]
                    logger.info(
                        "[VisualDirector] NPC active (%s) → swap: companion focal=%s",
                        game_state.active_companion, sec_name,
                    )
                    break

        # DEBUG: Log outfit obtained from game_state
        logger.info(f"[VisualDirector] Outfit for {visual_active}: style={outfit.style if outfit else 'None'}, base_sd_prompt={outfit.base_sd_prompt[:50] if outfit and outfit.base_sd_prompt else 'None'}...")

        # Dimensions
        aspect_ratio = narrative.aspect_ratio or "portrait"
        if aspect_ratio not in _DIMENSIONS:
            aspect_ratio = "portrait"
        width, height = _DIMENSIONS[aspect_ratio]

        # Composition tags
        composition = getattr(narrative, "composition", None) or self._infer_composition(
            narrative, game_state
        )
        # With 3+ characters a close_up will crop someone out — force medium/wide shot
        if len(secondary) >= 2 and composition == "close_up":
            composition = "medium_shot"
        # Use clean composition tags (no body focus conflicts)
        comp_tags = self._CLEAN_COMPOSITION_TAGS.get(composition, "cowboy shot")
        # Record composition for continuity
        self._update_composition_history(visual_active or "_solo_", composition)

        # Extract tags directly from player input (bypasses LLM censorship)
        player_tags = self._extract_player_tags(
            getattr(narrative, "_user_input", "") or ""
        )

        # Build positive prompt
        if secondary and companion:
            positive = self._build_multi_char_prompt(
                companion, outfit, narrative, secondary, game_state, comp_tags
            )
        elif companion:
            positive = self._build_single_char_prompt(
                companion, outfit, narrative, comp_tags, composition=composition
            )
        else:
            # Solo mode — location only
            positive = self._build_location_prompt(narrative, game_state, comp_tags)
        
        # Strip forbidden tags for this companion
        companion_name = visual_active or ""
        forbidden = _COMPANION_FORBIDDEN_TAGS.get(companion_name, [])
        if forbidden:
            import re as _re
            for tag in forbidden:
                # Remove as weighted tag e.g. (glasses:1.2)
                positive = _re.sub(
                    r"\(?" + _re.escape(tag) + r"[^,)]*\)?[:,\s]*",
                    "", positive, flags=_re.IGNORECASE
                )
                # Remove as plain tag
                positive = _re.sub(
                    r"(?:^|,\s*)" + _re.escape(tag) + r"(?=,|$)",
                    "", positive, flags=_re.IGNORECASE
                )
            # Clean up
            positive = _re.sub(r",\s*,+", ",", positive).strip().strip(",").strip()
        
        # CRITICAL RULE 8: Strip GLOBAL forbidden tags (NO GLASSES for anyone including NPCs)
        import re as _re_global
        for tag in _GLOBAL_FORBIDDEN_TAGS:
            # Remove as weighted tag
            positive = _re_global.sub(
                r"\(?" + _re_global.escape(tag) + r"[^,)]*\)?[:,\s]*",
                "", positive, flags=_re_global.IGNORECASE
            )
            # Remove as plain tag
            positive = _re_global.sub(
                r"(?:^|,\s*)" + _re_global.escape(tag) + r"(?=,|$)",
                "", positive, flags=_re_global.IGNORECASE
            )
        # Clean up
        positive = _re_global.sub(r",\s*,+", ",", positive).strip().strip(",").strip()

        # Append player-extracted tags to positive prompt (no duplicates)
        if player_tags:
            positive_lower = positive.lower()
            unique_tags = [
                t for t in player_tags
                if not any(
                    part.strip().lower() in positive_lower
                    for part in t.split(",")
                )
            ]
            if unique_tags:
                positive = positive + ", " + ", ".join(unique_tags)

        # Build negative prompt
        is_solo   = game_state.active_companion in ("_solo_", None)
        negative  = self._build_negative(secondary, solo_mode=is_solo)

        # Select LoRAs (skipped if disabled from UI)
        loras = self._select_loras(companion, outfit, narrative) if lora_enabled else []

        # Add companion-specific extra negative tags
        extra_neg = _COMPANION_EXTRA_NEGATIVE.get(companion_name, "")
        if extra_neg:
            negative = negative + ", " + extra_neg if negative else extra_neg

        return VisualOutput(
            positive=positive,
            negative=negative,
            loras=loras,
            aspect_ratio=aspect_ratio,
            composition=composition,
            width=width,
            height=height,
            dop_reasoning=getattr(narrative, "dop_reasoning", ""),
        )

    # -------------------------------------------------------------------------
    # Positive prompt builders
    # -------------------------------------------------------------------------

    # Mutually exclusive composition groups
    # Tags within the same group conflict — only one should appear
    _COMPOSITION_CONFLICTS = [
        # Angle conflicts
        {"bird eye view", "from above", "high angle shot",
         "from below", "low angle shot", "eye level", "ground level"},
        # Distance conflicts  
        {"close-up", "extreme close-up", "macro",
         "wide shot", "establishing shot", "full body", "long shot"},
        # Direction conflicts
        {"from behind", "rear view", "back view",
         "looking at viewer", "looking_at_viewer", "facing viewer"},
    ]

    # Maps composition keys → canonical SD tags (clean, no conflicts)
    _CLEAN_COMPOSITION_TAGS: Dict[str, str] = {
        "cowboy_shot":        "cowboy shot",
        "from_below":         "from below, low angle shot",
        "legs_closeup":       "from waist down",
        "thighs_shot":        "from waist down",
        "sitting_legs":       "sitting",
        "from_behind":        "from behind, rear view",
        "over_shoulder":      "over the shoulder shot",
        "bent_over":          "from behind",
        "medium_shot":        "upper body",
        "chest_closeup":      "upper body, chest focus",
        "three_quarter":      "three quarter view",
        "full_body":          "full body",
        "feet_focus":         "full body",
        "floor_level":        "from below",
        "dutch_angle":        "dutch angle",
        "from_above":         "from above, high angle shot",
        "profile":            "from the side, profile view",
        "diagonal":           "three quarter angle",
        "close_up":           "close-up",
        "bust_shot":          "upper body",
        "over_shoulder_face": "over the shoulder shot",
        "wide_shot":          "wide shot",
    }

    def _resolve_composition_conflicts(self, visual_en: str, chosen_comp: str) -> str:
        """Remove conflicting composition tags from visual_en.
        
        When we chose e.g. 'from_behind', strip 'bird eye view', 
        'looking at viewer', etc. from visual_en to avoid
        ComfyUI receiving contradictory angle instructions.
        """
        import re

        # Find which conflict group our chosen composition belongs to
        chosen_tags = self._CLEAN_COMPOSITION_TAGS.get(chosen_comp, "").lower()
        active_groups = set()
        for group in self._COMPOSITION_CONFLICTS:
            for tag in group:
                if tag in chosen_tags:
                    active_groups.add(id(group))
                    break

        # Remove conflicting tags from visual_en
        for group in self._COMPOSITION_CONFLICTS:
            if id(group) not in active_groups:
                continue
            for tag in group:
                # Skip tags that match our chosen composition
                if tag in chosen_tags:
                    continue
                # Remove the conflicting tag from visual_en
                pattern = re.escape(tag).replace(r"\ ", r"[_ ]")
                visual_en = re.sub(
                    r"\b" + pattern + r"\b",
                    "",
                    visual_en,
                    flags=re.IGNORECASE,
                )

        return visual_en

    def _clean_visual_en(self, visual_en: str, outfit: Any, composition: str = "") -> str:
        """Clean visual_en from hallucinated clothing, invalid tags, and composition conflicts."""
        import re

        # Remove invalid weighted tags (unknown tags with weights)
        known_weighted = {
            "legs focus", "face focus", "feet focus", "shoulders focus",
            "breast focus", "ass focus", "thighs focus",
        }
        def remove_bad_weighted(text):
            def check_tag(m):
                tag = m.group(1).replace("_", " ").lower()
                if tag in known_weighted:
                    return m.group(0)
                if any(kw in tag for kw in ["focus", "detail", "quality"]):
                    return m.group(0)
                return ""
            return re.sub(r"\(([^)]+):[0-9.]+\)", check_tag, text)

        # Remove conflicting "or" syntax (SD doesn't support it)
        visual_en = re.sub(r"\b(\w[\w\s]+)\s+or\s+(\w[\w\s]+)\b", r"\1", visual_en)

        # Strip specifically removed outfit components from visual_en
        if outfit and hasattr(outfit, "modifications"):
            import re as _re2
            _removed = {
                comp for comp, mod in outfit.modifications.items()
                if hasattr(mod, "state") and mod.state == "removed"
            }
            _comp_kw = {
                "shoes":   ["high heels", "heels", "shoes", "boots", "sandals", "stilettos", "pumps"],
                "top":     ["blouse", "shirt", "top", "sweater"],
                "jacket":  ["jacket", "blazer", "coat", "tailleur", "suit jacket"],
                "bottom":  ["skirt", "pants", "trousers"],
                "bra":     ["bra"],
            }
            for _comp in _removed:
                for _kw in _comp_kw.get(_comp, [_comp]):
                    visual_en = _re2.sub(
                        r"\b" + _re2.escape(_kw) + r"\b[^,\.]*",
                        "", visual_en, flags=_re2.IGNORECASE
                    )
            visual_en = _re2.sub(r",\s*,+", ",", visual_en).strip().strip(",")

        # Strip ALL clothing descriptions — outfit comes from OutfitState
        if outfit and outfit.style and outfit.style != "none":
            clothing_patterns = [
                r"\b(wearing|dressed in|clothed in|sporting|donning)\s+[^,\.\*]+",
                r"\bin\s+a\s+[a-z\s]+(dress|suit|outfit|uniform|skirt|blouse|shirt|top|jacket|coat|gown)[^,\.]*",
                r"\b(elegant\s+)?(formal|evening|cocktail|ball)\s+(dress|gown|attire|wear)[^,\.]*",
                r"\b(tuxedo|dinner\s+jacket|ball\s+gown)[^,\.]*",
                r"\b(her|his)\s+(elegant|formal|professional|casual)\s+(dress|outfit|attire|clothing|suit)[^,\.]*",
                r"\b(teacher['\'']?s?|professor['\'']?s?)\s+(dress|outfit|suit|attire)[^,\.]*",
                r"\bgrey\s+skirt[^,\.]*",  # already in outfit
                r"\bpencil\s+skirt[^,\.]*",
                r"\bpantyhose[^,\.]*",
            ]
            for pat in clothing_patterns:
                visual_en = re.sub(pat, "", visual_en, flags=re.IGNORECASE)

        # Resolve composition conflicts
        if composition:
            visual_en = self._resolve_composition_conflicts(visual_en, composition)

        # Remove bad weighted tags
        visual_en = remove_bad_weighted(visual_en)

        # Clean up extra commas/spaces
        visual_en = re.sub(r",\s*,+", ",", visual_en)
        visual_en = re.sub(r"^[\s,]+", "", visual_en)
        visual_en = visual_en.strip().strip(",").strip()

        return visual_en

    def _infer_pose_from_narrative(self, narrative_text: str, user_input: str) -> str:
        """Map Italian/English narrative actions to SD pose tags."""
        import re
        combined = (narrative_text + " " + user_input).lower()
        pose_map = [
            (r"sedut[ao]|siede|si siede|alla scrivania|al banco|in cattedra",
             "sitting, seated pose, at desk"),
            (r"gambe incrociat[ae]|gambe accavallat[ae]|crossed legs",
             "sitting, legs crossed, seated"),
            (r"si appoggia|appoggiata|leaning|against (the )?(wall|desk|door)",
             "leaning against wall, relaxed pose"),
            (r"incroci[ao] le braccia|braccia conserte|arms crossed",
             "standing, arms crossed, closed posture"),
            (r"si avvicina|si fa avanti|cammina verso|approaches",
             "walking forward, approaching viewer"),
            (r"si gira|si volta|turns around",
             "turning around, three quarter view"),
            (r"scrive alla lavagna|gessetto|chalk|alla lavagna",
             "writing on blackboard, arm raised, back to viewer"),
            (r"corregge|segna sul registro|legge i compiti",
             "sitting, reading papers, looking down"),
            (r"si tocca i capelli|touches her hair|aggiusta i capelli",
             "hand in hair, intimate gesture"),
            (r"si abbassa|si china|bending down|si piega",
             "bending forward, leaning down"),
            (r"si avvicina al banco|si china su di te|leans over",
             "leaning over desk, close to viewer, intimate"),
            (r"gamb[ae]|pantacoll[ae]|pantyhose|calze|piedi",
             "full body, legs visible"),
        ]
        for pattern, pose in pose_map:
            if re.search(pattern, combined):
                return pose
        return ""

    def _build_single_char_prompt(
        self,
        companion: CompanionDefinition,
        outfit: OutfitState,
        narrative: NarrativeOutput,
        comp_tags: str,
        composition: str = "",
    ) -> str:
        parts: List[str] = []

        # 1. Base prompt (LoRA triggers — sacred, DO NOT MODIFY)
        if companion.base_prompt:
            parts.append(companion.base_prompt)

        # 2. Composition
        parts.append(comp_tags)

        # 3. Outfit SD prompt
        outfit_sd = outfit.to_sd_prompt(include_weight=True)
        if outfit_sd:
            parts.append(outfit_sd)

        # 4. Visual description from narrative
        if narrative.visual_en:
            cleaned = self._clean_visual_en(narrative.visual_en, outfit, composition=composition)
            if cleaned:
                parts.append(cleaned)

        # 5. Tags from narrative
        if narrative.tags_en:
            parts.append(", ".join(narrative.tags_en))

        # 6. Body focus (zoom/detail emphasis)
        if narrative.body_focus:
            parts.append(self._body_focus_to_tag(narrative.body_focus))

        return ", ".join(filter(None, parts))

    def _build_multi_char_prompt(
        self,
        companion: CompanionDefinition,
        outfit: OutfitState,
        narrative: NarrativeOutput,
        secondary: List[str],
        game_state: GameState,
        comp_tags: str,
    ) -> str:
        parts: List[str] = []

        # ── Gender-aware count tag ────────────────────────────────────────────
        # Count females (companion) and males (NPC templates with gender=male)
        n_female = 1  # primary companion
        n_male   = 0
        for npc_name in secondary:
            tmpl = self.world.npc_templates.get(npc_name)
            gender = "female"
            if tmpl:
                gender = (
                    tmpl.get("gender", "female") if isinstance(tmpl, dict)
                    else getattr(tmpl, "gender", "female")
                )
            if gender == "male":
                n_male += 1
            else:
                n_female += 1

        _count_label = {1: "1", 2: "2", 3: "3", 4: "4"}
        count_parts: List[str] = []
        if n_female > 0:
            count_parts.append(f"{_count_label.get(n_female, 'multiple')}girl{'s' if n_female > 1 else ''}")
        if n_male > 0:
            count_parts.append(f"{_count_label.get(n_male, 'multiple')}boy{'s' if n_male > 1 else ''}")
        parts.append(", ".join(count_parts))

        # PRIMARY character (in focus — spoke last)
        if companion.base_prompt:
            parts.append(companion.base_prompt)
        outfit_sd = outfit.to_sd_prompt(include_weight=True)
        if outfit_sd:
            parts.append(outfit_sd)

        # SECONDARY characters
        for npc_name in secondary:
            sec_comp = self.world.companions.get(npc_name)
            if sec_comp:
                # Full companion — has outfit state
                sec_outfit = game_state.get_outfit(npc_name)
                sec_base   = sec_comp.base_prompt or ""
                sec_tags   = sec_outfit.to_sd_prompt(include_weight=False)
                if sec_base:
                    parts.append(f"({sec_base}:0.8)")
                if sec_tags:
                    parts.append(f"({sec_tags}:0.7)")
                parts.append(f"({npc_name} in background:0.7)")
            else:
                # NPC template (raw dict) — check initiative_style for prominence
                tmpl = self.world.npc_templates.get(npc_name)
                if not tmpl:
                    continue
                sec_base = (
                    tmpl.get("base_prompt", "") if isinstance(tmpl, dict)
                    else getattr(tmpl, "base_prompt", "")
                )
                is_authority_npc = (
                    (tmpl.get("initiative_style", "") if isinstance(tmpl, dict)
                     else getattr(tmpl, "initiative_style", "")) == "authority"
                )
                if sec_base:
                    weight = 0.9 if is_authority_npc else 0.8
                    parts.append(f"({sec_base}:{weight})")
                placement = "confronting viewer, prominent" if is_authority_npc else "in background"
                weight_pl = 0.85 if is_authority_npc else 0.7
                parts.append(f"({npc_name}, {placement}:{weight_pl})")

        # Composition
        parts.append(comp_tags)

        # Scene description
        if narrative.visual_en:
            parts.append(narrative.visual_en)

        if narrative.tags_en:
            parts.append(", ".join(narrative.tags_en))

        return ", ".join(filter(None, parts))

    def _build_location_prompt(
        self,
        narrative: NarrativeOutput,
        game_state: GameState,
        comp_tags: str,
    ) -> str:
        """Solo mode — location scene without character."""
        import re
        loc = self.world.locations.get(game_state.current_location)
        parts: List[str] = []

        # Solo mode: NO characters, NO people — hard enforced
        parts.append("no humans, empty scene, no people, nobody")
        if loc and loc.visual_style:
            parts.append(loc.visual_style)
        if loc and loc.lighting:
            parts.append(loc.lighting)

        # Use visual_en only for location/atmosphere cues — strip any character descriptions
        if narrative.visual_en:
            visual = narrative.visual_en
            # Remove character descriptions from visual_en
            char_patterns = [
                r"\b(1girl|1boy|1man|1woman|girl|boy|woman|man|person|character|figure)\b[^,\.]*",
                r"\b(she|he|her|his|luna|stella|maria)\b[^,\.]*",
                r"\b(standing|sitting|wearing|dressed|looking|gazing|smiling|holding)\b[^,\.]*",
                r"\b(mature woman|young woman|teacher|student|professor)\b[^,\.]*",
            ]
            for pat in char_patterns:
                visual = re.sub(pat, "", visual, flags=re.IGNORECASE)
            # Keep only location/atmosphere tags
            visual = re.sub(r",\s*,+", ",", visual).strip().strip(",").strip()
            if visual:
                parts.append(visual)

        parts.append(comp_tags)

        return ", ".join(filter(None, parts))

    # -------------------------------------------------------------------------
    # Negative prompt
    # -------------------------------------------------------------------------

    def _build_negative(self, secondary: List[str], solo_mode: bool = False) -> str:
        parts = [_NEGATIVE_BASE]
        if secondary:
            parts.append(_NEGATIVE_MULTI_CHAR)
        if solo_mode:
            parts.append("1girl, 1boy, person, human, woman, man, character, people, figure")
        return ", ".join(parts)

    # -------------------------------------------------------------------------
    # LoRA selection
    # -------------------------------------------------------------------------

    def _select_loras(
        self,
        companion: Optional[CompanionDefinition],
        outfit: OutfitState,
        narrative: NarrativeOutput,
    ) -> List[str]:
        """Select clothing LoRAs based on current outfit state.

        Returns list of strings like "lora_name:weight".
        """
        loras: List[str] = []

        # Extract outfit-relevant text to search for keywords
        outfit_text = " ".join([
            outfit.style,
            outfit.description,
            outfit.base_sd_prompt,
            " ".join(outfit.components.values()),
            narrative.visual_en,
        ]).lower()

        seen: set = set()
        for key, entry in CLOTHING_LORAS.items():
            if key in seen:
                continue
            if any(kw in outfit_text for kw in entry.keywords):
                loras.append(f"{entry.name}:{entry.weight}")
                seen.add(key)

        # Check modifications for wet/special states
        for mod in outfit.modifications.values():
            if mod.state == "wet" and "wet_clothes" not in seen:
                entry = CLOTHING_LORAS.get("wet_clothes")
                if entry:
                    loras.append(f"{entry.name}:{entry.weight}")
                    seen.add("wet_clothes")

        return loras

    # -------------------------------------------------------------------------
    # Composition inference
    # -------------------------------------------------------------------------

    # Body-focused shot pool — 80% of all shots
    # Varied and distributed across all body areas
    _BODY_SHOTS = [
        # Legs (frequent)
        "cowboy_shot",
        "from_below",
        "legs_closeup",
        "thighs_shot",
        "sitting_legs",
        # Ass / rear
        "from_behind",
        "over_shoulder",
        "bent_over",
        # Breasts / torso
        "medium_shot",
        "chest_closeup",
        "three_quarter",
        # Feet
        "full_body",
        "feet_focus",
        "floor_level",
        # Dynamic angles
        "dutch_angle",
        "from_above",
        "profile",
        "diagonal",
    ]
    # Face-focused shots — 20% max
    _FACE_SHOTS = [
        "close_up",
        "bust_shot",
        "over_shoulder_face",
        "wide_shot",
    ]

    def _update_composition_history(self, companion: str, composition: str) -> None:
        """Track composition history per companion."""
        if companion not in self._composition_history:
            self._composition_history[companion] = []
        history = self._composition_history[companion]
        history.append(composition)
        if len(history) > self._max_history:
            history.pop(0)

    def _is_overused(self, companion: str, composition: str) -> bool:
        """Check if composition has been used too many times recently."""
        history = self._composition_history.get(companion, [])
        count = history.count(composition)
        return count >= self._max_repeat

    def _pick_fresh(self, companion: str, pool: list) -> str:
        """Pick a composition not overused recently."""
        import random
        # Try to find a fresh one
        fresh = [c for c in pool if not self._is_overused(companion, c)]
        if fresh:
            return random.choice(fresh)
        # All overused — pick least used
        history = self._composition_history.get(companion, [])
        counts = {c: history.count(c) for c in pool}
        min_count = min(counts.values())
        least_used = [c for c, n in counts.items() if n == min_count]
        return random.choice(least_used)

    def _infer_composition(
        self, narrative: NarrativeOutput, game_state: GameState
    ) -> str:
        """Infer composition with 80% body-focus bias and continuity memory."""
        import random
        companion = game_state.active_companion or "_solo_"
        visual = (narrative.visual_en or "").lower()
        tags   = " ".join(narrative.tags_en or []).lower()
        combined = visual + " " + tags

        # Explicit angle overrides always respected (no history check)
        if any(w in combined for w in ["behind", "spalle", "schiena", "from behind"]):
            return "from_behind"
        if any(w in combined for w in ["above", "dall'alto"]):
            return "from_above"
        if any(w in combined for w in ["below", "dal basso", "low angle", "dal di sotto"]):
            return "from_below"
        if any(w in combined for w in ["full body", "figura intera", "piedi", "feet"]):
            return "full_body"
        if any(w in combined for w in ["profile", "profilo", "side view"]):
            return "profile"
        if any(w in combined for w in ["wide", "panorama", "establishing"]):
            return "wide_shot"
        if any(w in combined for w in ["dutch", "olandese"]):
            return "dutch_angle"

        # 80/20 body vs face bias — with history continuity
        face_words = ["close-up", "face focus", "viso", "occhi", "sorriso", "espressione"]
        if any(w in combined for w in face_words):
            if random.random() < 0.70:
                result = self._pick_fresh(companion, self._BODY_SHOTS)
            else:
                result = self._pick_fresh(companion, self._FACE_SHOTS)
        elif random.random() < 0.80:
            result = self._pick_fresh(companion, self._BODY_SHOTS)
        else:
            result = self._pick_fresh(companion, self._FACE_SHOTS)

        return result

    # -------------------------------------------------------------------------
    # Body focus → SD tag
    # -------------------------------------------------------------------------


    def _extract_player_tags(self, user_input: str) -> List[str]:
        """Extract SD tags directly from player input — bypasses LLM censorship.
        
        If the player explicitly describes a body part or action,
        it gets added to the SD prompt regardless of what the LLM generated.
        """
        import re
        tags = []
        text = user_input.lower()

        # Body parts → SD tags
        body_map = {
            r"mutandin[ae]|slip|intimo|biancheria": "panties visible, upskirt",
            r"gamb[ae]": "legs visible, shapely legs",
            r"cosch[ae]|coscia": "thighs visible",
            r"scollatura|decolt[eè]|seno|tett[ae]|seni": "cleavage, deep neckline",
            r"capezzol[io]": "nipple visible, nip slip",
            r"culo|sedere|natich[ae]": "ass visible",
            r"piedi|piedini": "bare feet, foot focus",
            r"pancia|ventre|ombelico": "bare midriff, navel",
            r"spall[ae]|spalline": "bare shoulders",
            r"cavallo|tra le gambe|inguine": "between legs, crotch",
        }

        for pattern, tag in body_map.items():
            if re.search(pattern, text):
                tags.append(tag)

        # Positions → composition tags
        position_map = {
            r"a carponi|in ginocchio|inginocchiata": "on all fours, kneeling, from behind",
            r"chinandomi|mi chino|si china": "bending over, from below",
            r"sdraiata|sdraiato|sul letto|sul divano": "lying down, recumbent",
            r"in piedi": "standing",
            r"seduta|seduto": "seated, sitting",
            r"da dietro|di spalle": "from behind, rear view",
            r"dal basso|dal di sotto": "from below, low angle shot",
        }

        for pattern, tag in position_map.items():
            if re.search(pattern, text):
                tags.append(tag)

        # Clothing states → tags
        clothing_map = {
            r"si alza la gonna|gonna alzata|gonna sollevata": "skirt lifted, skirt up",
            r"camicia aperta|sbottonata": "open shirt, unbuttoned",
            r"senza reggiseno|senza bra": "no bra, braless",
            r"nuda|spogliata|senza vestiti": "nude, naked",
            r"in lingerie|in intimo": "lingerie, intimate apparel",
            r"bagnata|fradicia": "wet clothes, wet hair",
        }

        for pattern, tag in clothing_map.items():
            if re.search(pattern, text):
                tags.append(tag)

        return tags

    def _body_focus_to_tag(self, focus: str) -> str:
        mapping = {
            "face":    "(face focus:1.2), detailed face",
            "legs":    "(legs focus:1.2), shapely legs",
            "breasts": "(breasts focus:1.2), cleavage",
            "ass":     "(ass focus:1.2)",
            "feet":    "(feet focus:1.2), bare feet",
            "hands":   "(hands focus:1.1)",
            "neck":    "(neck focus:1.1)",
            "midriff": "(midriff focus:1.1), bare midriff",
        }
        return mapping.get(focus.lower(), f"({focus} focus:1.1)")
