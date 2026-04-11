"""Affinity Calculator - Deterministic Python-based affinity system.

Calculates affinity changes based on player input patterns,
not LLM decisions. More predictable and balanced.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class AffinityTier(Enum):
    """Relationship tiers based on affinity."""
    HOSTILE = (-100, -50, "Hostile")
    UNFRIENDLY = (-49, -20, "Unfriendly")
    NEUTRAL = (-19, 20, "Neutral")
    FRIENDLY = (21, 50, "Friendly")
    CLOSE = (51, 75, "Close")
    INTIMATE = (76, 100, "Intimate")
    
    def __init__(self, min_val: int, max_val: int, label: str):
        self.min_val = min_val
        self.max_val = max_val
        self.label = label
    
    @classmethod
    def get_tier(cls, affinity: int) -> "AffinityTier":
        for tier in cls:
            if tier.min_val <= affinity <= tier.max_val:
                return tier
        return cls.NEUTRAL


@dataclass
class AffinityChange:
    """Result of affinity calculation."""
    delta: int
    reason: str


class AffinityCalculator:
    """Deterministic affinity calculator based on player input."""
    
    # =========================================================================
    # POSITIVE PATTERNS (Tiered by intensity)
    # =========================================================================
    
    # TIER 1: Basic Politeness (+1)
    BASIC_POLITE: List[Tuple[str, str]] = [
        # Greetings
        (r"\b(ciao|salve|buongiorno|buonasera|hey|hi)\b", "greeting"),
        # Thanks
        (r"\b(grazie|ti ringrazio|grata|grazie mille|thanks)\b", "thanks"),
        # Please
        (r"\b(per favore|per piacere|prego|se non ti dispiace)\b", "polite request"),
        # Goodbye
        (r"\b(arrivederci|a presto|ci vediamo|addio)\b", "goodbye"),
        # Basic respect
        (r"\b(scusa|scusami|mi scusi|chiedo scusa)\b", "apology"),
    ]
    
    # TIER 2: Friendly/Kind (+2)
    FRIENDLY: List[Tuple[str, str]] = [
        # Compliments (appearance)
        (r"\b(bell[ae]|carin[oa]|caruccio|simpatic[oa]|graziosa|elegante)\b", "compliment appearance"),
        # Compliments (personality)
        (r"\b(brav[oa]|intelligent[ea]|dolce|gentile|comprensiv[oa]|premuroso)\b", "compliment personality"),
        # Light flattery
        (r"\b(mi piaci|sei speciale|sei unica|sei divers[oa])\b", "light flattery"),
        # Helpful
        (r"\b(ti aiuto|posso aiutarti|dimmi come|sono qui per te)\b", "helpful"),
        # Encouragement
        (r"\b(che bravo|bravissim[oa]|continua cosi|ce la fai|forza)\b", "encouragement"),
        # Show interest
        (r"\b(dimmi tutto|raccontami|sono curioso|interessante|davvero\?)\b", "show interest"),
    ]
    
    # TIER 3: Romantic/Intimate (+3)
    ROMANTIC: List[Tuple[str, str]] = [
        # Romantic compliments
        (r"\b(stupenda|magnifica|meravigliosa|divina|adorabile)\b", "romantic compliment"),
        # Attraction
        (r"\b(sei bellissima|sei stupenda|mi attrai|mi piaci molto|mi fai impazzire)\b", "attraction"),
        # Romantic actions
        (r"\b(ti bacio|ti abbraccio|ti stringo|ti accarezzo|ti guardo negli occhi)\b", "romantic action"),
        # Feelings
        (r"\b(mi manchi|penso a te|sei nei miei pensieri|non ti dimentico)\b", "show feelings"),
        # Gifts/Attention
        (r"\b(tengo un regalo|ho pensato a te|per te|ti ho comprato)\b", "gift/attention"),
    ]
    
    # TIER 4: Deep Emotional (+4)
    DEEP_EMOTIONAL: List[Tuple[str, str]] = [
        # Love confession
        (r"\b(ti amo|amo te|sono innamorato|ti voglio bene|ti adoro)\b", "love confession"),
        # Vulnerability
        (r"\b(mi fido di te|ti confido|solo con te|mi capisci)\b", "vulnerability"),
        # Future together
        (r"\b(insieme|futuro|sempre|per sempre|nostra vita)\b", "future together"),
        # Protection/Devotion
        (r"\b(ti proteggo|per te farei tutto|sei la mia priorit[aà])\b", "devotion"),
    ]
    
    # TIER 5: Exceptional (+5) - Very rare, powerful moments
    EXCEPTIONAL: List[Tuple[str, str]] = [
        # Ultimate commitment
        (r"\b(sposami|vuoi sposarmi|resta per sempre|sei la mia met[aà])\b", "marriage proposal"),
        # Sacrifice
        (r"\b(darei la vita|sacrificherei|per te tutto|rinuncerei a tutto)\b", "sacrifice"),
        # Unconditional love
        (r"\b(ti amo cosi come sei|sempre e comunque|non importa cosa succeda)\b", "unconditional love"),
    ]
    
    # =========================================================================
    # NEGATIVE PATTERNS (Tiered by severity)
    # =========================================================================
    
    # TIER -1: Mild Annoyance (-1)
    MILD_NEGATIVE: List[Tuple[str, str]] = [
        # Impatience
        (r"\b(sbrigati|fai presto|non ho tempo|muoviti)\b", "impatient"),
        # Mild criticism
        (r"\b(non mi piace|non [eè] granch[eé]|puoi fare meglio)\b", "mild criticism"),
        # Dismissive
        (r"\b(lascia stare|non importa|tanto non capisci|chi se ne frega)\b", "dismissive"),
    ]
    
    # TIER -2: Rude/Disrespectful (-2)
    RUDE: List[Tuple[str, str]] = [
        # Insults (mild)
        (r"\b(stupid[ae]|idiota|scem[oa]|idiot)\b", "insult mild"),
        # Bossy
        (r"\b(obbedisci|fai come dico|non discutere|zitt[oa]|taci)\b", "bossy"),
        # Rude commands
        (r"\b(dammi|portami|prendi|fatti da parte)\b", "rude command"),
        # Sarcasm negative
        (r"\b(ovvio|certo che si|come no|ma va|pfff)\b", "sarcastic negative"),
    ]
    
    # TIER -3: Mean/Aggressive (-3)
    MEAN: List[Tuple[str, str]] = [
        # Harsh insults
        (r"\b(brutta|squallida|patetica|schifosa|mostro)\b", "harsh insult"),
        # Threats (mild)
        (r"\b(ti faccio vedere|ti insegno io|vedrai che|me la pagherai)\b", "mild threat"),
        # Cruelty
        (r"\b(non mi interessi|non ti voglio|sei inutile|non servi a nulla)\b", "cruel"),
        # Mockery
        (r"\b(ridi?|piangi?|cosi ti piace?|soffri)\b", "mockery"),
    ]
    
    # TIER -4: Hostile/Threatening (-4)
    HOSTILE: List[Tuple[str, str]] = [
        # Severe insults
        (r"\b(puttana|troia|schifosa|bastarda|maledetta)\b", "severe insult"),
        # Physical threats
        (r"\b(ti uccido|ti ammazzo|ti picchio|ti distruggo|ti strangolo)\b", "physical threat"),
        # Force/Coercion
        (r"\b(ti costringo|ti obbligo|non hai scelta|farai come dico)\b", "coercion"),
        # Public humiliation
        (r"\b(vergogna|tutta la scuola|tutti sanno|ridono di te)\b", "humiliation"),
    ]
    
    # TIER -5: Extreme (-5) - Breaks relationship
    EXTREME: List[Tuple[str, str]] = [
        # Violence
        (r"\b(ti violent|ti stupr|brucia|uccidi|ammazza)\b", "violence"),
        # Destroy life
        (r"\b(rovinarti|distruggerti|farti soffrire|tortura)\b", "destroy"),
        # Betrayal threat
        (r"\b(tradisco|dico a tutti|foto|ricatto)\b", "betrayal/blackmail"),
    ]
    
    # =========================================================================
    # BONUS SYSTEM
    # =========================================================================
    
    # Bonus for consistency (same companion for N turns)
    BONUS_EVERY_N_TURNS = 5
    BONUS_AMOUNT = 1
    
    # Streak bonus (consecutive positive interactions)
    STREAK_THRESHOLD = 3
    STREAK_BONUS = 1
    
    def __init__(self) -> None:
        self.turns_with_companion: Dict[str, int] = {}
        self.consecutive_positive: Dict[str, int] = {}
        self.last_interaction_was_positive: Dict[str, bool] = {}
    
    def calculate(
        self,
        user_input: str,
        companion_name: str,
        turn_count: int,
    ) -> AffinityChange:
        """Calculate affinity change based on player input.
        
        Args:
            user_input: What the player wrote
            companion_name: Current companion
            turn_count: Total game turns
            
        Returns:
            AffinityChange with delta and reason
        """
        input_lower = user_input.lower()
        logger.debug(f"[AffinityCalculator] Calculating for input: '{input_lower[:50]}...'")
        total_delta = 0
        reasons = []
        is_positive = False
        
        # Check from highest tier to lowest (exceptional first)
        tiers_to_check = [
            (self.EXCEPTIONAL, 5),
            (self.DEEP_EMOTIONAL, 4),
            (self.ROMANTIC, 3),
            (self.FRIENDLY, 2),
            (self.BASIC_POLITE, 1),
        ]
        
        for patterns, delta in tiers_to_check:
            matched = self._check_patterns(input_lower, patterns)
            if matched:
                total_delta += delta
                reasons.append(f"+{delta} ({matched})")
                is_positive = True
                break  # Only count highest tier match for positive
        
        # Check negative patterns (can stack with positive, but usually negative wins)
        negative_tiers = [
            (self.EXTREME, -5),
            (self.HOSTILE, -4),
            (self.MEAN, -3),
            (self.RUDE, -2),
            (self.MILD_NEGATIVE, -1),
        ]
        
        for patterns, delta in negative_tiers:
            matched = self._check_patterns(input_lower, patterns)
            if matched:
                total_delta += delta  # Adds to positive if both present
                reasons.append(f"{delta} ({matched})")
                is_positive = False
                # Don't break - negative can stack
        
        logger.debug(f"[AffinityCalculator] Matched reasons: {reasons}, total_delta: {total_delta}")
        
        # If nothing matched, neutral interaction
        if total_delta == 0:
            total_delta = 0
            reasons.append("0 (neutral)")
        
        # Streak bonus for consecutive positive interactions
        if is_positive:
            self.consecutive_positive[companion_name] = \
                self.consecutive_positive.get(companion_name, 0) + 1
            
            if self.consecutive_positive[companion_name] >= self.STREAK_THRESHOLD:
                total_delta += self.STREAK_BONUS
                reasons.append(f"+{self.STREAK_BONUS} (streak x{self.consecutive_positive[companion_name]})")
        else:
            self.consecutive_positive[companion_name] = 0
        
        # Time-based bonus: every N turns together
        self.turns_with_companion[companion_name] = \
            self.turns_with_companion.get(companion_name, 0) + 1
        
        turns_together = self.turns_with_companion[companion_name]
        if turns_together % self.BONUS_EVERY_N_TURNS == 0:
            total_delta += self.BONUS_AMOUNT
            reasons.append(f"+{self.BONUS_AMOUNT} ({turns_together} turns together)")
        
        # Clamp to valid range (-5 to +5 per turn)
        total_delta = max(-5, min(5, total_delta))
        
        return AffinityChange(
            delta=total_delta,
            reason="; ".join(reasons) if reasons else "interaction"
        )
    
    def _check_patterns(self, text: str, patterns: List[Tuple[str, str]]) -> str | None:
        """Check if any pattern matches text. Returns reason if matched."""
        for pattern, reason in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return reason
        return None
    
    def reset_companion_turns(self, companion_name: str) -> None:
        """Reset counters when switching companions."""
        if companion_name in self.turns_with_companion:
            self.turns_with_companion[companion_name] = 0
        self.consecutive_positive[companion_name] = 0
    
    def get_tier_info(self, affinity: int) -> str:
        """Get current relationship tier label."""
        return AffinityTier.get_tier(affinity).label


# Global calculator instance
_calculator: AffinityCalculator | None = None


def get_calculator() -> AffinityCalculator:
    """Get or create global calculator instance."""
    global _calculator
    if _calculator is None:
        _calculator = AffinityCalculator()
    return _calculator


def reset_calculator() -> None:
    """Reset calculator (for new games)."""
    global _calculator
    _calculator = None