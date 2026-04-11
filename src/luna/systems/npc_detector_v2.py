"""NPC Detector V2 - Modern approach using NLP and whitelists.

V4.9: Complete rewrite to avoid false positives.

Strategy:
1. Only recognize KNOWN companion names (whitelist)
2. For generic NPCs, use explicit patterns only
3. Use context clues ("si chiama X", "una donna X")
4. Dictionary check for Italian common words
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Any, Set


class NPCDetectorV2:
    """Modern NPC detection with minimal false positives."""
    
    # Common Italian words that are NOT names (top 5000 most common)
    ITALIAN_COMMON_WORDS: Set[str] = {
        # Essential words that caused bugs
        'che', 'lato', 'resto', 'solo', 'modo', 'parte', 'tempo', 'anno', 'giorno', 'volta',
        'uomo', 'donna', 'momento', 'mano', 'occhio', 'ora', 'italia', 'senso', 'problema',
        'punto', 'caso', 'citt', 'paese', 'strada', 'motivo', 'storia', 'questo', 'quello',
        'stesso', 'altro', 'primo', 'ultimo', 'nuovo', 'bello', 'brutto', 'grande', 'piccolo',
        # Articles and prepositions
        'il', 'lo', 'la', 'i', 'gli', 'le', 'un', 'uno', 'una', 'del', 'al', 'nel', 'dal',
        'col', 'sul', 'tra', 'fra', 'di', 'a', 'da', 'in', 'con', 'su', 'per',
        # Pronouns
        'io', 'tu', 'lui', 'lei', 'noi', 'voi', 'loro', 'mi', 'ti', 'si', 'ci', 'vi',
        'me', 'te', 'lo', 'la', 'li', 'le', 'ne',
        # Verbs essere/avere (conjugated)
        'sono', 'sei', 'è', 'siamo', 'siete', 'ero', 'eri', 'era', 'eravamo', 'erano',
        'ho', 'hai', 'ha', 'abbiamo', 'avete', 'hanno', 'avevo', 'avevi', 'aveva',
        # Common verbs
        'faccio', 'fai', 'fa', 'facciamo', 'fanno',
        'vado', 'vai', 'va', 'andiamo', 'vanno',
        'dico', 'dici', 'dice', 'diciamo', 'dicono',
        'vedo', 'vedi', 'vede', 'vediamo', 'vedono',
        'parlo', 'parli', 'parla', 'parliamo', 'parlano',
        'penso', 'pensi', 'pensa', 'pensiamo', 'pensano',
        'credo', 'credi', 'crede', 'crediamo', 'credono',
        'sento', 'senti', 'sente', 'sentiamo', 'sentono',
        # Directions
        'destra', 'sinistra', 'davanti', 'dietro', 'sopra', 'sotto', 'dentro', 'fuori',
        'lato', 'fronte', 'retro', 'centro', 'vicino', 'lontano', 'interno', 'esterno',
        # Colors
        'rosso', 'rossa', 'blu', 'verde', 'giallo', 'gialla', 'bianco', 'bianca',
        'nero', 'nera', 'grigio', 'grigia', 'marrone', 'rosa', 'viola', 'arancione',
        # Body parts
        'testa', 'capelli', 'occhio', 'occhi', 'naso', 'bocca', 'labbra', 'viso', 'faccia',
        'mano', 'mani', 'braccio', 'braccia', 'gamba', 'gambe', 'piede', 'piedi', 'schiena',
        'petto', 'spalla', 'spalle', 'ginocchio', 'ginocchia', 'cuore', 'corpo',
        # Abstract concepts
        'amore', 'odio', 'bellezza', 'bruttezza', 'verit', 'bugia', 'sogno', 'realt',
        'giorno', 'notte', 'mattina', 'sera', 'luce', 'buio', 'sole',
        # NOTE: 'luna' removed - it's a companion name
        # Qualities
        'intelligente', 'simpatico', 'simpatica', 'gentile', 'cattivo', 'cattiva',
        'bravo', 'brava', 'forte', 'debole', 'veloce', 'lento', 'lenta', 'giovane', 'vecchio',
        # Common nouns
        'casa', 'scuola', 'lavoro', 'citt', 'paese', 'strada', 'porta', 'finestra',
        'tavolo', 'sedia', 'letto', 'cucina', 'bagno', 'giardino', 'albero', 'fiore',
        # Titles
        'signore', 'signora', 'signorina', 'dottore', 'dottoressa', 'professore', 'professoressa',
        'ingegnere', 'avvocato', 'avvocatessa', 'preside', 'presidente', 'direttore', 'direttrice',
        # More false positives
        'circa', 'senza', 'contro', 'durante', 'mediante', 'nonostante', 'secondo',
        'entro', 'verso', 'tranne', 'eccetto', 'oltre', 'insieme', 'oltre',
    }
    
    def __init__(self, world: Any) -> None:
        """Initialize detector."""
        self.world = world
        # Build whitelist of known companion names (lowercase)
        self.known_names: Set[str] = set()
        if world and hasattr(world, 'companions'):
            for name in world.companions.keys():
                self.known_names.add(name.lower())
    
    def detect(self, user_input: str, game_state: Any = None) -> Optional[str]:
        """Alias for detect_companion_in_input - compatibility with TurnOrchestrator.
        
        Args:
            user_input: Player input text
            game_state: Optional game state (ignored, for compatibility)
            
        Returns:
            Companion name or None
        """
        return self.detect_companion_in_input(user_input)
    
    def detect_companion_in_input(self, user_input: str) -> Optional[str]:
        """Detect if user mentions a KNOWN companion.
        
        V2: Only matches against whitelist of known companions.
        No more false positives like "Che" or "Lato".
        
        Returns:
            Companion name or None
        """
        if not self.world or not user_input:
            return None
        
        # Normalize input
        text = user_input.lower()
        
        # Check each known companion name with word boundaries
        for companion_name in self.known_names:
            # Skip if it's a common word (extra safety)
            if companion_name in self.ITALIAN_COMMON_WORDS:
                continue
            
            # Use word boundary regex
            if re.search(r'\b' + re.escape(companion_name) + r'\b', text):
                return companion_name.capitalize()
        
        return None
    
    def detect_generic_npc_interaction(self, user_input: str) -> Optional[Dict[str, Any]]:
        """Detect interaction with generic/temporary NPC.
        
        V2: Only matches explicit patterns, not single words.
        
        Patterns:
        - "una donna che..." / "una ragazza che..."
        - "un uomo che..." / "un ragazzo che..."
        - "una X con Y" (description pattern)
        
        Returns:
            Dict with 'name', 'description' or None
        """
        if not user_input:
            return None
        
        text = user_input.lower()
        
        # Pattern: "una [adjective] donna/ragazza che/descrizione"
        # Example: "una donna alta con capelli rossi"
        woman_patterns = [
            r'\buna\s+(?:\w+\s+)?(?:donna|ragazza|signora|femmina)\s+(?:con|che|alta|bassa|grassa|magra|giovane|anziana|elegante|bella|brutta)',
        ]
        
        # Pattern: "un [adjective] uomo/ragazzo/signore descrizione"
        man_patterns = [
            r'\bun\s+(?:\w+\s+)?(?:uomo|ragazzo|signore|maschio)\s+(?:con|che|alto|basso|grasso|magro|giovane|anziano|elegante|bello|brutto)',
        ]
        
        # Pattern: "vedo/noto/scorgo una/un..."
        see_patterns = [
            r'\b(?:vedo|noto|scorgo|osservo|incontro)\s+(?:una|un)\s+',
        ]
        
        # Check for explicit "si chiama NAME" pattern (most reliable)
        name_match = re.search(r'\bsi\s+chiama\s+(\w+)', text)
        if name_match:
            name = name_match.group(1).capitalize()
            # If it's a common word, ignore
            if name.lower() not in self.ITALIAN_COMMON_WORDS:
                return {
                    'name': name,
                    'description': f'persona di nome {name}',
                    'gender': 'unknown'
                }
        
        # Check for woman patterns
        for pattern in woman_patterns:
            if re.search(pattern, text):
                # Extract description after the noun
                match = re.search(r'\buna\s+(?:\w+\s+)?(?:donna|ragazza|signora)\s+(.{5,100})', text)
                desc = match.group(1) if match else 'donna'
                return {
                    'name': 'GenericWoman',
                    'description': desc.strip(),
                    'gender': 'female'
                }
        
        # Check for man patterns
        for pattern in man_patterns:
            if re.search(pattern, text):
                match = re.search(r'\bun\s+(?:\w+\s+)?(?:uomo|ragazzo|signore)\s+(.{5,100})', text)
                desc = match.group(1) if match else 'uomo'
                return {
                    'name': 'GenericMan',
                    'description': desc.strip(),
                    'gender': 'male'
                }
        
        return None
    
    def is_likely_name(self, word: str) -> bool:
        """Check if a word is likely to be a proper name.
        
        V2: Conservative check using dictionary and heuristics.
        
        Returns:
            True if word is likely a name
        """
        word_lower = word.lower()
        
        # Must start with uppercase (Italian proper names)
        if not word or not word[0].isupper():
            return False
        
        # Must be at least 3 chars (avoid "Il", "La")
        if len(word) < 3:
            return False
        
        # Must NOT be in common Italian words
        if word_lower in self.ITALIAN_COMMON_WORDS:
            return False
        
        # Must be only letters (no numbers/punctuation)
        if not word.isalpha():
            return False
        
        return True
