"""Luna RPG - Simple Strip Manager for Poker Game.

NO affinity gating, NO exit points.
Pure stack-based progression with increasingly hot dialogue.
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class StripLevel:
    """Single strip level configuration."""
    level: int
    stack_threshold: float  # Percentage (0-100)
    components_removed: List[str]
    description_it: str
    description_en: str
    temperature: str  # "normal", "warm", "hot", "very_hot", "extreme"


class SimpleStripManager:
    """Simple strip progression based only on stack percentage."""

    # Universal strip levels (same thresholds for all companions)
    LEVELS: Dict[int, StripLevel] = {
        0: StripLevel(
            level=0,
            stack_threshold=100,
            components_removed=[],
            description_it="outfit completo",
            description_en="fully dressed, professional outfit",
            temperature="normal",
        ),

        1: StripLevel(
            level=1,
            stack_threshold=75,
            components_removed=["jacket", "blazer", "outerwear"],
            description_it="senza giacca",
            description_en="jacket removed, white shirt visible",
            temperature="warm",
        ),

        2: StripLevel(
            level=2,
            stack_threshold=50,
            components_removed=["jacket", "skirt", "bottom"],
            description_it="senza gonna, gambe visibili",
            description_en="no skirt, legs visible, pantyhose",
            temperature="hot",
        ),

        3: StripLevel(
            level=3,
            stack_threshold=25,
            components_removed=["jacket", "skirt", "shirt", "top"],
            description_it="topless, solo reggiseno",
            description_en="topless, wearing bra and pantyhose",
            temperature="very_hot",
        ),

        4: StripLevel(
            level=4,
            stack_threshold=10,
            components_removed=["all_except_underwear"],
            description_it="solo lingerie",
            description_en="lingerie only, bra and panties",
            temperature="extreme",
        ),

        5: StripLevel(
            level=5,
            stack_threshold=0,
            components_removed=["all"],
            description_it="completamente nuda",
            description_en="completely naked",
            temperature="extreme",
        ),
    }

    # Hot dialogue templates per companion
    HOT_DIALOGUES = {
        "Luna": {
            0: "Pronta a giocare! Non pensare di vincere facilmente! 😊",
            1: "Va bene... ho perso. *si toglie la giacca* Contento adesso? 😏",
            2: "*si alza, sfila gonna lentamente* Mmm... ti piace vedermi così? Le mie gambe... 😳",
            3: "*sbottona camicia con mani tremanti* Oh dio... topless davanti a te... la tua professoressa... questo è così sbagliato ma... mi piace... 🥵",
            4: "*sfila collant, rimane in lingerie* Solo biancheria... quasi nuda per te... ti eccita vedermi così? Vuoi che perda tutto? 💋",
            5: "*si toglie tutto, completamente nuda* Eccomi... la tua professoressa completamente nuda... sono tutta tua... cosa vuoi fare con me? 🔥",
        },
        "Maria": {
            0: "O-okay... giochiamo... *nervosa* 😊",
            1: "*toglie giacca timidamente* Ho perso... ecco... 😳",
            2: "*arrossisce intensamente* N-non posso credere... senza gonna... non guardare troppo... 😰",
            3: "*copre seno mentre si sfila camicia* S-sono topless... davanti a te... è così imbarazzante... ma non riesco a fermarmi... 🥺",
            4: "*in lingerie, cerca di coprirsi* Solo... solo biancheria... mi vedi quasi tutta... questo è... 😢",
            5: "*nuda, nasconde viso* C-completamente nuda... sono così vulnerabile... p-puoi fare quello che vuoi con me... 😭",
        },
        "Stella": {
            0: "Let's go! Preparati a perdere! 😎",
            1: "*toglie giacca con sicurezza* Persa questa. No problem! 😏",
            2: "*sfila gonna, mani sui fianchi* Senza gonna? Ti piacciono le mie gambe? Scommetto di sì... 😈",
            3: "*si spoglia senza vergogna* Topless! *mani sui fianchi* Ammira il mio corpo... ti piace quello che vedi? 🔥",
            4: "*posa in lingerie* Mmm... solo lingerie per te... vuoi toccarmi? Vieni più vicino... 💋",
            5: "*completamente nuda, posa sexy* Eccomi, tutta nuda. Sono tua... prendimi se hai il coraggio! 😈",
        },
    }

    def __init__(self, companion_name: str, initial_stack: int = 1000):
        """Initialize strip manager.

        Args:
            companion_name: Name of companion (Luna, Maria, Stella)
            initial_stack: Starting chip stack
        """
        self.companion_name = companion_name
        self.initial_stack = initial_stack
        self.current_level = 0

    def get_level(self, current_stack: int) -> int:
        """Get strip level based on current stack.

        Args:
            current_stack: Current chip amount

        Returns:
            Strip level (0-5)
        """
        if current_stack <= 0:
            return 5

        percentage = (current_stack / self.initial_stack) * 100

        # Find appropriate level
        for level in range(5, -1, -1):
            if percentage <= self.LEVELS[level].stack_threshold:
                return level

        return 0

    def check_level_up(self, old_stack: int, new_stack: int) -> Tuple[bool, int, int]:
        """Check if strip level increased.

        Args:
            old_stack: Previous stack amount
            new_stack: Current stack amount

        Returns:
            Tuple of (has_leveled_up, old_level, new_level)
        """
        old_level = self.get_level(old_stack)
        new_level = self.get_level(new_stack)

        has_leveled = new_level > old_level

        if has_leveled:
            self.current_level = new_level
            logger.info(
                f"[Strip] {self.companion_name} leveled up: {old_level} → {new_level} "
                f"(stack: {new_stack}/{self.initial_stack})"
            )

        return (has_leveled, old_level, new_level)

    def get_hot_dialogue(self, level: int) -> str:
        """Get hot dialogue for strip level.

        Args:
            level: Strip level (0-5)

        Returns:
            Hot dialogue text
        """
        companion_dialogues = self.HOT_DIALOGUES.get(
            self.companion_name,
            self.HOT_DIALOGUES["Luna"]  # Fallback to Luna
        )

        return companion_dialogues.get(
            level,
            f"{self.companion_name} strip level {level}"
        )

    def get_visual_description(self, level: int) -> str:
        """Get visual description for image generation.

        Args:
            level: Strip level (0-5)

        Returns:
            English visual description for SD
        """
        level_info = self.LEVELS.get(level)
        if not level_info:
            return f"{self.companion_name} at poker table"

        base_desc = f"Cinematic portrait of {self.companion_name} at poker table"

        descriptions = {
            0: f"{base_desc}, fully dressed in professional outfit, confident expression, cards in hand, poker chips, dramatic lighting",
            1: f"{base_desc}, jacket removed and draped over chair, white shirt, slightly flustered expression, cards visible, warm casino lighting",
            2: f"{base_desc}, no skirt, white shirt and sheer pantyhose, legs visible and crossed, embarrassed but excited expression, biting lip, scattered poker chips",
            3: f"{base_desc}, topless wearing lace bra and pantyhose, flushed cheeks, aroused and breathless expression, dramatic side lighting, shallow depth of field",
            4: f"{base_desc}, wearing only matching lace bra and panties, very exposed, seductive and teasing expression, leaning forward, poker cards and chips scattered, moody atmospheric lighting",
            5: f"{base_desc}, completely naked, completely nude, full body visible, vulnerable yet aroused expression, defeated but eager look, scattered chips and cards, dramatic low-key lighting with deep shadows",
        }

        return descriptions.get(level, descriptions[0])

    def apply_to_outfit(self, outfit, level: int):
        """Apply strip level to outfit state.

        Args:
            outfit: OutfitState object
            level: Strip level to apply

        Returns:
            Modified outfit
        """
        if level >= 5:
            # Completely naked
            outfit.components = {}
            outfit.description = "completamente nuda"
        elif level >= 4:
            # Lingerie only
            outfit.components = {
                "bra": "lace bra",
                "panties": "lace panties",
            }
            outfit.description = "solo lingerie"
        elif level >= 3:
            # Topless
            outfit.components = {
                "bra": "lace bra",
                "pantyhose": "sheer pantyhose",
            }
            outfit.description = "topless con collant"
        elif level >= 2:
            # No skirt
            outfit.components = {
                "shirt": "white button-up",
                "pantyhose": "sheer pantyhose",
            }
            outfit.description = "senza gonna"
        elif level >= 1:
            # No jacket
            outfit.components = {
                "shirt": "white button-up",
                "skirt": "pencil skirt",
                "pantyhose": "sheer pantyhose",
            }
            outfit.description = "senza giacca"
        else:
            # Full outfit
            outfit.components = {
                "jacket": "grey blazer",
                "shirt": "white button-up",
                "skirt": "pencil skirt",
                "pantyhose": "sheer pantyhose",
            }
            outfit.description = "outfit completo"

        return outfit
