"""
Luna RPG - Poker Mini-Game - COMPLETE CODE
============================================

Questo file contiene TUTTO il codice necessario per il poker mini-game.
Copia i file nella tua struttura come indicato nei commenti.

Struttura file da creare:
src/luna/systems/mini_games/
├── __init__.py
├── poker/
│   ├── __init__.py
│   ├── simple_strip_manager.py  ← CODICE QUI SOTTO
│   └── poker_game.py             ← CODICE QUI SOTTO

"""

# ============================================================================
# FILE 1: simple_strip_manager.py
# Path: src/luna/systems/mini_games/poker/simple_strip_manager.py
# ============================================================================

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
            3: f"{base_desc}, topless wearing lace bra and pantyhose, hands near chest, flushed cheeks, aroused and breathless expression, dramatic side lighting, shallow depth of field",
            4: f"{base_desc}, wearing only matching lace bra and panties, very exposed, seductive and teasing expression, leaning forward, poker cards and chips scattered, moody atmospheric lighting",
            5: f"{base_desc}, completely naked, hands covering strategic areas, vulnerable yet aroused expression, defeated but eager look, scattered chips and cards, dramatic low-key lighting with deep shadows",
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


# ============================================================================
# FILE 2: poker_game.py
# Path: src/luna/systems/mini_games/poker/poker_game.py
# ============================================================================

"""Luna RPG - Poker Game Handler.

Simple poker game with strip progression.
Supports single and multi-companion games.
"""
from typing import TYPE_CHECKING, Dict, List, Optional, Any
import logging
import random

if TYPE_CHECKING:
    from luna.core.models import GameState, TurnResult
    from luna.core.engine import GameEngine

from .simple_strip_manager import SimpleStripManager

logger = logging.getLogger(__name__)


class PokerGame:
    """Poker mini-game with strip progression."""
    
    def __init__(
        self,
        engine: "GameEngine",
        companion_names: List[str],
        initial_stack: int = 1000,
    ):
        """Initialize poker game.
        
        Args:
            engine: Game engine instance
            companion_names: List of companion names playing
            initial_stack: Starting chip stack
        """
        self.engine = engine
        self.companion_names = companion_names
        self.initial_stack = initial_stack
        
        # Player data
        self.player_stack = initial_stack
        
        # Companion data
        self.companions: Dict[str, Dict[str, Any]] = {}
        for name in companion_names:
            self.companions[name] = {
                "stack": initial_stack,
                "strip_level": 0,
                "eliminated": False,
                "strip_manager": SimpleStripManager(name, initial_stack),
            }
        
        # Game tracking
        self.hand_number = 0
        self.total_hands = 0
        self.game_active = True
    
    async def start_game(self, game_state: "GameState") -> "TurnResult":
        """Start poker game.
        
        Args:
            game_state: Current game state
            
        Returns:
            Initial turn result
        """
        from luna.core.models import TurnResult
        
        # Build companion list text
        if len(self.companion_names) == 1:
            players_text = f"Tu vs {self.companion_names[0]}"
        else:
            players_text = f"Tu vs {', '.join(self.companion_names)}"
        
        narrative = (
            f"🎰 **POKER GAME START!** 🎰\n\n"
            f"Giocatori: {players_text}\n"
            f"💰 Stack iniziale: {self.initial_stack} chips ciascuno\n\n"
            f"_Comandi: 'punto X', 'vedo', 'rilancio X', 'fold', 'all-in', 'esci'_\n\n"
        )
        
        # Add companion intro
        for name in self.companion_names:
            intro = self.companions[name]["strip_manager"].get_hot_dialogue(0)
            narrative += f"{name}: \"{intro}\"\n"
        
        # Save state
        game_state.flags["poker_active"] = True
        game_state.flags["poker_game"] = self.to_dict()
        
        logger.info(f"[Poker] Game started with {len(self.companion_names)} companions")
        
        return TurnResult(
            text=narrative,
            turn_number=game_state.turn_count,
        )
    
    async def play_hand(
        self,
        player_action: str,
        game_state: "GameState",
    ) -> "TurnResult":
        """Play a poker hand.
        
        Args:
            player_action: Player's action
            game_state: Current game state
            
        Returns:
            Turn result with outcome
        """
        from luna.core.models import TurnResult
        
        self.hand_number += 1
        
        # Simple win/loss simulation (TODO: integrate full poker engine)
        # For MVP, just random winner
        active_companions = [
            name for name, data in self.companions.items()
            if not data["eliminated"]
        ]
        
        if not active_companions:
            return await self.end_game(game_state, "Player wins - all companions eliminated!")
        
        # Random winner for now (replace with poker logic)
        all_players = ["Player"] + active_companions
        winner = random.choice(all_players)
        
        pot = 200  # Simplified pot
        
        narrative = f"**Mano #{self.hand_number}**\n\n"
        
        image_path = None
        strip_events = []
        
        if winner == "Player":
            # Player wins - companions lose chips
            narrative += "🎉 **HAI VINTO LA MANO!** 🎉\n\n"
            
            chips_per_companion = pot // len(active_companions)
            
            for comp_name in active_companions:
                comp = self.companions[comp_name]
                old_stack = comp["stack"]
                comp["stack"] -= chips_per_companion
                
                # Check strip level
                strip_mgr = comp["strip_manager"]
                leveled, old_level, new_level = strip_mgr.check_level_up(
                    old_stack, comp["stack"]
                )
                
                if leveled:
                    comp["strip_level"] = new_level
                    
                    # Generate strip event
                    strip_event = await self._generate_strip_event(
                        comp_name, new_level, game_state
                    )
                    strip_events.append(strip_event)
                    
                    if strip_event["image_path"]:
                        image_path = strip_event["image_path"]
            
            self.player_stack += pot
        
        else:
            # Companion wins
            narrative += f"😔 **{winner} vince la mano**\n\n"
            self.player_stack -= pot // len(active_companions)
            self.companions[winner]["stack"] += pot
        
        # Show stacks
        narrative += "💰 **Stack:**\n"
        narrative += f"  Tu: {self.player_stack} chips\n"
        for comp_name in active_companions:
            stack = self.companions[comp_name]["stack"]
            level = self.companions[comp_name]["strip_level"]
            narrative += f"  {comp_name}: {stack} chips (Strip Level {level})\n"
        
        # Add strip narratives
        if strip_events:
            narrative += "\n🔥 **STRIP EVENT!** 🔥\n\n"
            for event in strip_events:
                narrative += f"{event['narrative']}\n\n"
        
        # Check eliminations
        for comp_name in active_companions:
            if self.companions[comp_name]["stack"] <= 0:
                self.companions[comp_name]["eliminated"] = True
                self.companions[comp_name]["strip_level"] = 5
                
                elim_event = await self._generate_strip_event(
                    comp_name, 5, game_state
                )
                narrative += f"\n💀 **{comp_name} ELIMINATA - COMPLETAMENTE NUDA!** 💀\n"
                narrative += f"{elim_event['narrative']}\n"
                
                if elim_event["image_path"]:
                    image_path = elim_event["image_path"]
        
        # Save state
        game_state.flags["poker_game"] = self.to_dict()
        
        return TurnResult(
            text=narrative,
            image_path=image_path,
            turn_number=game_state.turn_count,
        )
    
    async def _generate_strip_event(
        self,
        companion_name: str,
        level: int,
        game_state: "GameState",
    ) -> Dict[str, Any]:
        """Generate strip event with image.
        
        Args:
            companion_name: Companion name
            level: New strip level
            game_state: Current game state
            
        Returns:
            Dict with narrative and image_path
        """
        comp = self.companions[companion_name]
        strip_mgr = comp["strip_manager"]
        
        # Get hot dialogue
        dialogue = strip_mgr.get_hot_dialogue(level)
        narrative = f"{companion_name}: {dialogue}"
        
        # Get visual description
        visual_en = strip_mgr.get_visual_description(level)
        
        # Update outfit
        outfit = game_state.get_outfit(companion_name)
        outfit = strip_mgr.apply_to_outfit(outfit, level)
        game_state.set_outfit(outfit, companion_name)
        
        # Generate image
        image_path = None
        if self.engine.media_pipeline and not self.engine.no_media:
            try:
                from luna.core.models import NarrativeOutput
                
                temp_narrative = NarrativeOutput(
                    text=narrative,
                    visual_en=visual_en,
                    tags_en=[f"strip_level_{level}", "poker_game"],
                    provider_used="poker_strip",
                )
                
                result = await self.engine.media_pipeline.generate_all(
                    narrative=temp_narrative,
                    companion_name=companion_name,
                    location_id=game_state.current_location,
                    outfit_state=outfit,
                    session_id=game_state.session_id,
                    turn_count=game_state.turn_count,
                )
                
                image_path = result.get("image_path")
                
                logger.info(f"[Poker] Generated strip image for {companion_name} level {level}")
                
            except Exception as e:
                logger.error(f"[Poker] Failed to generate image: {e}")
        
        return {
            "narrative": narrative,
            "image_path": image_path,
            "level": level,
        }
    
    async def end_game(
        self,
        game_state: "GameState",
        reason: str = "Game ended",
    ) -> "TurnResult":
        """End poker game.
        
        Args:
            game_state: Current game state
            reason: End reason
            
        Returns:
            Final turn result
        """
        from luna.core.models import TurnResult
        
        # Clear state
        game_state.flags["poker_active"] = False
        game_state.flags.pop("poker_game", None)
        
        narrative = f"**GAME OVER**\n\n{reason}\n\n"
        narrative += "📊 **Final Stats:**\n"
        narrative += f"  Mani giocate: {self.hand_number}\n"
        narrative += f"  Stack finale: {self.player_stack} chips\n\n"
        
        for comp_name, comp_data in self.companions.items():
            level = comp_data["strip_level"]
            stack = comp_data["stack"]
            status = "ELIMINATA NUDA" if comp_data["eliminated"] else "ACTIVE"
            narrative += f"  {comp_name}: {stack} chips, Strip Level {level}/5 ({status})\n"
        
        logger.info(f"[Poker] Game ended: {reason}")
        
        return TurnResult(
            text=narrative,
            turn_number=game_state.turn_count,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize game state.
        
        Returns:
            Dict representation
        """
        return {
            "companion_names": self.companion_names,
            "initial_stack": self.initial_stack,
            "player_stack": self.player_stack,
            "companions": {
                name: {
                    "stack": data["stack"],
                    "strip_level": data["strip_level"],
                    "eliminated": data["eliminated"],
                }
                for name, data in self.companions.items()
            },
            "hand_number": self.hand_number,
        }
    
    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        engine: "GameEngine",
    ) -> "PokerGame":
        """Restore from saved state.
        
        Args:
            data: Saved state dict
            engine: Game engine
            
        Returns:
            Restored poker game
        """
        game = cls(
            engine=engine,
            companion_names=data["companion_names"],
            initial_stack=data["initial_stack"],
        )
        
        game.player_stack = data["player_stack"]
        game.hand_number = data["hand_number"]
        
        for name, comp_data in data["companions"].items():
            game.companions[name]["stack"] = comp_data["stack"]
            game.companions[name]["strip_level"] = comp_data["strip_level"]
            game.companions[name]["eliminated"] = comp_data["eliminated"]
        
        return game


# ============================================================================
# FILE 3: __init__.py files
# ============================================================================

# Path: src/luna/systems/mini_games/__init__.py
"""Luna RPG - Mini Games System."""

# Path: src/luna/systems/mini_games/poker/__init__.py
"""Luna RPG - Poker Mini-Game."""
from .poker_game import PokerGame
from .simple_strip_manager import SimpleStripManager

__all__ = ["PokerGame", "SimpleStripManager"]


# ============================================================================
# FINE FILE CODICE
# ============================================================================

print("✅ Tutti i file poker sono pronti!")
print("Vedi INTEGRATION_INSTRUCTIONS.md per le modifiche agli altri file")
