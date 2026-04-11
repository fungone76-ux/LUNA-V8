"""Pose Extractor - Extracts physical poses from user input.

Deterministic regex-based extraction of physical actions that should be
visually represented in the generated image.

Similar to OutfitModifier but for body poses and positions.

Usage:
    extractor = get_pose_extractor()
    poses = extractor.get_forced_visual_description("Luna accavalla le gambe")
    # Returns: "crossed legs, legs crossed"
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExtractedPose:
    """Extracted pose information."""
    pose_desc: str  # English description for SD
    pose_type: str  # Category (seated, standing, legs, arms, etc.)
    confidence: float  # 0.0-1.0


class PoseExtractor:
    """Extracts physical poses from Italian text.
    
    Uses regex patterns to identify pose descriptions that the user
    explicitly requests for the NPC (e.g., "Luna accavalla le gambe").
    
    These poses are then injected into the visual_en as MANDATORY.
    """
    
    # Pose patterns: Italian regex -> (English SD description, pose_type)
    # Organizzati per categoria per facilità di manutenzione
    POSE_PATTERNS: List[Tuple[str, str, str]] = [
        # ===================================================================
        # GAMBE / LEGS (20+ patterns)
        # ===================================================================
        # Crossed legs
        (r"\b(accavalla|incrocia|croccia)\s+(?:le\s+)?gambe\b", "crossed legs, legs crossed", "legs"),
        (r"\bgambe\s+(accavallate|incrociate)\b", "crossed legs, legs crossed", "legs"),
        (r"\buna\s+gamba\s+sull'altra\b", "crossed legs, one leg over other", "legs"),
        
        # Legs spread/open
        (r"\b(gambe\s+)?(aperte|spalancate|divaricate)\b", "legs spread, spread legs", "legs"),
        (r"\b(gambe\s+)?(molto\s+)?aperte\b", "legs spread wide", "legs"),
        (r"\b(apre|spalanca)\s+(?:le\s+)?gambe\b", "spreading legs", "legs"),
        
        # Legs together/closed
        (r"\b(gambe\s+)?(chiuse|vicine|strette)\b", "legs together, closed legs", "legs"),
        (r"\bchiude\s+(?:le\s+)?gambe\b", "closing legs, legs together", "legs"),
        
        # Straddling / sitting astride
        (r"\b(seduta|siede)\s+(?:con\s+)?(?:le\s+)?gambe\s+(?:a|in)\s+cavallo\b", "straddling, sitting astride", "legs"),
        (r"\ba\s+cavallo\b", "straddling position", "legs"),
        
        # Kneeling / on knees
        (r"\b(inginocchiata|inginocchiato|in\s+ginocchio)\b", "kneeling, on knees", "legs"),
        (r"\b(si\s+)?(inginocchia|mette\s+in\s+ginocchio)\b", "kneeling down", "legs"),
        
        # Squatting
        (r"\b(accovacciata|accovacciato)\b", "squatting, crouching", "legs"),
        (r"\b(si\s+)?accovaccia\b", "squatting down", "legs"),
        
        # Legs up
        (r"\bgambe\s+(alzate|sollevate|in\s+alto)\b", "legs up, raised legs", "legs"),
        (r"\balza\s+(?:le\s+)?gambe\b", "raising legs", "legs"),
        
        # One leg
        (r"\bgamba\s+(pie|piegata|sollevata)\b", "one leg bent, leg raised", "legs"),
        
        # Walking/running
        (r"\b(cammina|camminando)\b", "walking", "legs"),
        (r"\b(corre|correndo)\b", "running", "legs"),
        (r"\b(a\s+)?(passo|passi)\s+(di\s+)?(danza|ballo)\b", "dance pose, ballet pose", "legs"),
        
        # ===================================================================
        # BRACCIA / ARMS (20+ patterns)
        # ===================================================================
        # Crossed arms
        (r"\b(braccia\s+)?incrociate\b", "crossed arms, arms crossed", "arms"),
        (r"\b(incrocia|incrociare)\s+(?:le\s+)?braccia\b", "crossed arms, arms crossed", "arms"),
        (r"\bbraccia\s+(al\s+)?(petto|torace)\b", "arms crossed on chest", "arms"),
        
        # Arms down/open
        (r"\bbraccia\s+(aperte|tese)\b", "arms open, arms outstretched", "arms"),
        (r"\b(apre|spalanca)\s+(?:le\s+)?braccia\b", "opening arms wide", "arms"),
        
        # Arms up
        (r"\bbraccia\s+(alzate|sollevate|in\s+alto|su)\b", "arms up, raised arms", "arms"),
        (r"\balza\s+(?:le\s+)?braccia\b", "raising arms", "arms"),
        
        # Behind back
        (r"\b(braccia|mani)\s+dietro\s+(?:la\s+)?schiena\b", "hands behind back, arms behind back", "arms"),
        
        # Hands on hips
        (r"\b(mani\s+)?(?:sui\s+)?fianchi\b", "hands on hips", "arms"),
        (r"\b(mani\s+alla\s+)?(vita|cinghia)\b", "hands on hips", "arms"),
        
        # Hands on thighs/legs
        (r"\b(mani|braccia)\s+sulle\s+(cosce|gambe)\b", "hands on thighs", "arms"),
        
        # Hands together
        (r"\bmani\s+(giunte|unite|insieme)\b", "hands clasped together", "arms"),
        (r"\b(unisce|unire)\s+(?:le\s+)?mani\b", "hands together", "arms"),
        
        # Interlaced fingers
        (r"\bdita\s+intrecciate\b", "interlaced fingers", "arms"),
        (r"\b(intreccia|intrecciare)\s+(?:le\s+)?dita\b", "fingers interlaced", "arms"),
        
        # Waving
        (r"\b(saluta|salutando)\b", "waving hand", "arms"),
        
        # Pointing
        (r"\b(indica|indicando|punta)\b", "pointing finger", "arms"),
        
        # Hugging self
        (r"\b(braccia|mani)\s+(?:attorno|intorno)\s+(?:al\s+)?(corpo|petto)\b", "hugging self", "arms"),
        
        # Leaning on
        (r"\b(appoggia|si\s+appoggia)\s+(?:le\s+)?braccia\b", "leaning on arms", "arms"),
        
        # ===================================================================
        # MANI / HANDS (20+ patterns)
        # ===================================================================
        # Playing with hair
        (r"\b(giocare\s+)?(con\s+)?i\s+capelli\b", "playing with hair, twirling hair", "hands"),
        (r"\b(si\s+)?(gioca\s+)?con\s+(?:i\s+)?capelli\b", "playing with hair", "hands"),
        
        # Touching face
        (r"\b(mano|mani)\s+(?:sul|sulla|sul)\s+(viso|faccia)\b", "hand on face, touching face", "hands"),
        (r"\b(si\s+)?tocca\s+(?:il\s+)?viso\b", "touching face", "hands"),
        
        # Touching neck
        (r"\b(mano|mani)\s+(?:sul|sulla|sul)\s+(collo|gola)\b", "hand on neck, touching neck", "hands"),
        
        # Touching hair
        (r"\b(si\s+)?(sistema|aggiusta|tocca)\s+(?:i\s+)?capelli\b", "touching hair, fixing hair", "hands"),
        
        # On table/desk
        (r"\bmani\s+(?:sul|sulla)\s+(tavolo|scrivania|banco)\b", "hands on table", "hands"),
        
        # Fidgeting
        (r"\b(tripudia|giocherella)\s+(?:con\s+)?(?:le\s+)?mani\b", "fidgeting hands", "hands"),
        
        # Clenched fists
        (r"\bpugni\s+(serrati|chiusi)\b", "clenched fists", "hands"),
        (r"\b(serra|chiude)\s+(?:i\s+)?pugni\b", "clenching fists", "hands"),
        
        # Open palms
        (r"\bmani\s+(aperte|spalancate)\b", "open palms", "hands"),
        
        # Wringing hands
        (r"\b(si\s+)?(torce|strofina)\s+(?:le\s+)?mani\b", "wringing hands", "hands"),
        
        # Finger to lips
        (r"\b(dito\s+)?sulle\s+labbra\b", "finger to lips, shushing", "hands"),
        
        # Holding object
        (r"\b(tiene|tenendo)\s+(?:in\s+)?mano\b", "holding object in hand", "hands"),
        
        # Folding
        (r"\b(piegare|piegata|piegato)\s+(?:il|i\s+)?(?:fazzoletto|foglio|carta|vestito)\b", "folding, hands folding", "hands"),
        
        # Adjusting clothes
        (r"\b(si\s+)?(sistema|aggiusta)\s+(?:il|la|i|le)\s+((?:abito|vestito|gonna|camicia))\b", "adjusting clothes", "hands"),
        
        # ===================================================================
        # POSIZIONI / POSITIONS (15+ patterns)
        # ===================================================================
        # Sitting
        (r"\b(seduta|seduto|siede|siediti)\b", "sitting, seated", "position"),
        (r"\b(si\s+)?siede\b", "sitting down", "position"),
        (r"\bseduta\b", "sitting", "position"),
        
        # Standing
        (r"\b(in\s+)?piedi\b", "standing", "position"),
        (r"\b(in\s+)?pied\b", "standing", "position"),
        (r"\bsta\s+(in\s+)?piedi\b", "standing", "position"),
        
        # Lying down
        (r"\b(sdraiata|sdraiato|sdrada)\b", "lying down, reclining", "position"),
        (r"\b(sdraiata|sdraiato)\s+(?:sul|sulla)\b", "lying on", "position"),
        
        # Leaning
        (r"\b(appoggiata|appoggiato)\s+(?:al|contro|sul|sulla)\b", "leaning against", "position"),
        (r"\b(poggia|si\s+poggia)\s+(?:contro|su)\b", "leaning on", "position"),
        (r"\b(appoggiata|appoggiato)\b", "leaning", "position"),
        
        # Bending over
        (r"\b(piegata|pie|chinata)\s+(?:in\s+)?avanti\b", "bending forward, bent over", "position"),
        
        # Arching back
        (r"\bschiena\s+in\s+arco\b", "arched back, back arched", "position"),
        
        # Stretching
        (r"\b(si\s+)?stira\b", "stretching", "position"),
        
        # Tiptoeing
        (r"\b(sulle|in)\s+punte\b", "tiptoeing, on tiptoes", "position"),
        
        # ===================================================================
        # TESTA / HEAD (15+ patterns)
        # ===================================================================
        # Head tilted
        (r"\b(testa\s+)?(inclinata|chinata|piegata)\b", "head tilted, tilted head", "head"),
        (r"\b(inclina|piega)\s+(?:la\s+)?testa\b", "tilting head", "head"),
        
        # Head down
        (r"\b(testa\s+)?(china|bassa|abbassata)\b", "head down, looking down", "head"),
        (r"\babbassa\s+(?:la\s+)?testa\b", "lowering head", "head"),
        
        # Head up
        (r"\b(testa\s+)?(alzata|sollevata|alta)\b", "head up, looking up", "head"),
        (r"\balza\s+(?:la\s+)?testa\b", "raising head", "head"),
        
        # Head turned
        (r"\b(gira|girata)\s+(?:la\s+)?testa\b", "turning head", "head"),
        
        # Hair flip
        (r"\b(scuote|scuotendo)\s+(?:i\s+)?capelli\b", "hair flip, tossing hair", "head"),
        
        # ===================================================================
        # SGUARDO / GAZE (20+ patterns)
        # ===================================================================
        # Looking down
        (r"\b(guarda|guardando)\s+(?:verso\s+)?(?:il|la|l')?\s+(?:basso|giu|giù)\b", "looking down, gaze down", "gaze"),
        (r"\b(occhi\s+)?(?:al|verso\s+il)\s+basso\b", "looking down", "gaze"),
        
        # Looking up
        (r"\b(guarda|guardando)\s+(?:verso\s+)?(?:l')?\s*alto\b", "looking up, gaze up", "gaze"),
        (r"\b(alza|alzando)\s+(?:lo\s+)?sguardo\b", "looking up, raising gaze", "gaze"),
        (r"\b(occhi\s+)?(?:al|verso\s+l)'alto\b", "looking up", "gaze"),
        
        # Looking to side
        (r"\b(guarda|guardando)\s+(?:di\s+)?(?:lato|fianco)\b", "looking to side, side glance", "gaze"),
        (r"\b(guarda|guardando)\s+(?:da\s+)?(?:una|un')?\s+parte\b", "looking to side", "gaze"),
        
        # Looking back
        (r"\b(guarda|guardando)\s+(?:indietro|dietro)\b", "looking back, looking over shoulder", "gaze"),
        (r"\bsguardo\s+(?:indietro|dietro)\b", "looking back", "gaze"),
        
        # Looking at camera/player
        (r"\b(guarda|fissa)\s+(?:verso\s+)?(?:la\s+)?camera\b", "looking at camera, eye contact", "gaze"),
        (r"\b(guarda|fissa)\s+dritto\b", "looking straight, direct gaze", "gaze"),
        (r"\b(guarda|fissa)\s+(?:nei\s+)?occhi\b", "looking in eyes, eye contact", "gaze"),
        
        # Staring
        (r"\b(fissa|fissando)\b", "staring, intense gaze", "gaze"),
        (r"\bsguardo\s+(fisso|intenso)\b", "intense stare", "gaze"),
        
        # Eyes closed
        (r"\b(occhi\s+)?(chiusi|socchiusi)\b", "eyes closed, half-closed eyes", "gaze"),
        (r"\b(chiude|chiudendo)\s+(?:gli\s+)?occhi\b", "closing eyes", "gaze"),
        
        # Winking
        (r"\b(occhiolino|strizza\s+l'occhio)\b", "winking", "gaze"),
        
        # Rolling eyes
        (r"\b(alza|alzando)\s+(?:gli\s+)?occhi\s+al\s+cielo\b", "rolling eyes", "gaze"),
        
        # Avoiding gaze
        (r"\b(distoglie|distogliendo)\s+(?:lo\s+)?sguardo\b", "looking away, avoiding eye contact", "gaze"),
        
        # ===================================================================
        # BOCCA / MOUTH (15+ patterns)
        # ===================================================================
        # Closed mouth
        (r"\b(labbra\s+)?(serrate|chiuse|premute)\b", "tight lips, closed mouth", "mouth"),
        
        # Open mouth
        (r"\b(labbra\s+)?(aperte|leggermente\s+aperte)\b", "parted lips, slightly open mouth", "mouth"),
        (r"\b(bocca\s+)?aperta\b", "open mouth", "mouth"),
        
        # Biting lip
        (r"\bmordere\s+(?:il\s+)?labbro\b", "biting lip, lip bite", "mouth"),
        (r"\b(si\s+)?morde\s+(?:il\s+)?labbro\b", "biting lip", "mouth"),
        (r"\blabbro\s+tra\s+(?:i\s+)?denti\b", "lip between teeth", "mouth"),
        
        # Pouting
        (r"\bbroncio|fazza\s+broncia\b", "pouting", "mouth"),
        
        # Smiling
        (r"\b(sorride|sorridendo)\s+(?:con\s+)?(?:il\s+)?(?:viso|faccia)\b", "smiling", "mouth"),
        
        # Licking lips
        (r"\b(si\s+)?lecca\s+(?:le\s+)?labbra\b", "licking lips", "mouth"),
        
        # Puckered
        (r"\b(labbra\s+)?(strette|purse)\b", "puckered lips", "mouth"),
        
        # ===================================================================
        # ESPRESSIONI / EXPRESSIONS (15+ patterns)
        # ===================================================================
        # Blushing
        (r"\b(arrossisce|arrossendo)\b", "blushing, flushed cheeks", "expression"),
        (r"\b(viso|guance)\s+(rosse|in\s+fiamme)\b", "red face, blushing", "expression"),
        
        # Angry
        (r"\b(sogghigno|sogghignando)\b", "sneering", "expression"),
        (r"\bbroncio\b", "pouting, sulking", "expression"),
        
        # Surprised
        (r"\b(sorpresa|sorpreso|sbalordita)\b", "surprised expression", "expression"),
        
        # Confident
        (r"\b(sorriso|sorridendo)\s+(sicuro|sicura|fiero|fiera)\b", "confident smile", "expression"),
        
        # Nervous
        (r"\b(nervosa|nervoso|ansiosa|ansioso)\b", "nervous expression", "expression"),
        
        # Sad
        (r"\b(triste|tristezza)\b", "sad expression", "expression"),
        
        # ===================================================================
        # POSE HOT / NSFW (25+ patterns)
        # ===================================================================
        # Spreading legs (explicit)
        (r"\b(gambe\s+)?(spalancate|aperte\s+a\s+90)\b", "legs spread wide, exposed", "nsfw"),
        (r"\b(apre|spalanca)\s+(?:le\s+)?gambe\s+(?:completamente|tutta|del\s+tutto)\b", "spreading legs completely, fully exposed", "nsfw"),
        (r"\bmostra\s+(?:la\s+)?(fica|patatina|vagina)\b", "exposed crotch, showing pussy", "nsfw"),
        (r"\b(senza|no\s+)mutande\b", "no panties, exposed", "nsfw"),
        
        # Bent over / Presenting
        (r"\b(piegata|china)\s+(?:in\s+)?avanti\s+(?:col|con\s+il)\s+(?:culo|sedere)\b", "bent over showing ass", "nsfw"),
        (r"\bmostra\s+(?:il\s+)?(culo|sedere|natiche)\b", "showing ass, presenting ass", "nsfw"),
        (r"\balza\s+(?:la\s+)?gonna\b", "lifting skirt, skirt lift", "nsfw"),
        (r"\b(senza|no\s+)reggiseno\b", "no bra, exposed breasts", "nsfw"),
        (r"\bmostra\s+(?:le\s+)?(tette|tettine|poppe)\b", "showing breasts, exposed breasts", "nsfw"),
        
        # Touching intimate
        (r"\b(tocca|toccare|toccarsi)\s+(?:la\s+)?(fica|patatina|vagina)\b", "touching pussy, masturbating", "nsfw"),
        (r"\b(tocca|toccare|toccarsi)\s+(?:le\s+)?(tette|tettine)\b", "touching breasts, groping breasts", "nsfw"),
        (r"\b(tocca|toccare|toccarsi)\s+(?:il\s+)?(culo|sedere)\b", "touching ass, groping ass", "nsfw"),
        (r"\b(si\s+)?masturba\b", "masturbating, touching herself", "nsfw"),
        
        # On all fours
        (r"\b(quattro\s+)?(zampe|ginocchia\s+e\s+mani)\b", "on all fours, doggy position", "nsfw"),
        (r"\bposizione\s+da\s+cane\b", "doggy style pose, on all fours", "nsfw"),
        
        # Straddling / Riding
        (r"\ba\s+cavallo\s+(?:su|sopra)\b", "straddling, riding position", "nsfw"),
        (r"\b(sale|salendo)\s+(?:su|sopra)\b", "climbing on top, mounting", "nsfw"),
        
        # Exposed
        (r"\bnuda\b", "nude, completely naked", "nsfw"),
        (r"\bcompletamente\s+nuda\b", "fully nude, naked", "nsfw"),
        (r"\bsi\s+(spoglia|sveste)\b", "undressing, stripping", "nsfw"),
        (r"\b(fa|si\s+fa)\s+la\s+doccia\b", "showering, nude shower", "nsfw"),
        (r"\b(in\s+)?bagno\b", "in bath, naked bath", "nsfw"),
        
        # Nipples / Capezzoli (V4.6 - Nuovi pattern)
        (r"\bcapezzol[oi]\s+(semiespost[oi]|semiuscit[oi]|mezzo\s+usci[ot][oi]|visibil[ie]|fuori|scopert[oi]|che\s+esce|che\s+spunta)\b", "nipple visible, exposed nipple, nip slip, nipple popping out", "nsfw"),
        (r"\b(vedo|intravedo|si\s+vede|guardo|noto)\s+(?:il\s+|un\s+)?capezzol[oi]\b", "visible nipple, nip slip", "nsfw"),
        (r"\bcapezzol[oi]\s+(che\s+)?(esce|spunta|esposto|fuori)\b", "nipple popping out, exposed nipple", "nsfw"),
        (r"\bcapezzol[oi]\s+(parzialmente\s+)?scopert[oi]\b", "exposed nipple, nip slip", "nsfw"),
        (r"\bseno\s+(scoperto|esposto|fuori)\b", "exposed breast, bare breast", "nsfw"),
        (r"\bscollatura\s+(profonda|molto\s+profonda)\s+(?:che\s+)?mostra\b", "deep cleavage, plunging neckline", "nsfw"),
        (r"\b(buca|slip|mutande)\s+visibil[ie]\b", "visible panties, panty peek", "nsfw"),
        (r"\bvedo\s+(?:la\s+)?(buca|slip|mutande)\b", "panties visible, upskirt", "nsfw"),
        
        # Teasing
        (r"\bprovocante\b", "provocative pose, teasing", "nsfw"),
        (r"\balluring\b", "alluring pose", "nsfw"),
        (r"\bseductive\b", "seductive pose", "nsfw"),
        (r"\b(ti\s+)?(sballa|sballando)\b", "slutty pose, whorish pose", "nsfw"),
        (r"\bposa\s+da\s+troia\b", "slutty pose, vulgar pose", "nsfw"),
        
        # ===================================================================
        # POSTURA / POSTURE (10+ patterns)
        # ===================================================================
        # Straight
        (r"\b(schiena\s+)?dritta\b", "straight back, upright posture", "posture"),
        (r"\bdritta\s+come\s+un\s+fuso\b", "perfect posture, ramrod straight", "posture"),
        
        # Arched
        (r"\b(schiena\s+)?(in\s+)?arcata\b", "arched back", "posture"),
        (r"\bschiena\s+in\s+arco\b", "back arched", "posture"),
        
        # Slouching
        (r"\b(schiena\s+)?(curva|curvata|pencolante)\b", "slouching, hunched", "posture"),
        
        # Relaxed
        (r"\b(rilassata|rilassato|comoda|comodo)\b", "relaxed posture", "posture"),
        
        # Stiff
        (r"\b(rigida|rigido|tesa|teso)\b", "stiff posture, tense", "posture"),
        
        # ===================================================================
        # AZIONI SPECIFICHE / ACTIONS (15+ patterns)
        # ===================================================================
        # Dance poses
        (r"\b(posa|posizione)\s+da\s+(ballo|danza)\b", "dance pose", "action"),
        
        # Pin-up
        (r"\bposa\s+(da\s+)?pin[-\s]?up\b", "pin-up pose", "action"),
        
        # Model pose
        (r"\bposa\s+da\s+fotomodella\b", "model pose", "action"),
        
        # Presenting
        (r"\b(si\s+)?presenta\b", "presenting pose", "action"),
        
        # Turning around
        (r"\b(gira|girandosi|si\s+gira)\b", "turning around", "action"),
        
        # Bowing
        (r"\b(inchino|inchina|inchinarsi)\b", "bowing", "action"),
        
        # Curtsey
        (r"\b(rverenza)\b", "curtsey", "action"),
        
        # Welcoming
        (r"\b(accoglie|accogliendo)\b", "welcoming gesture", "action"),
        
        # Dismissive
        (r"\b(scaccia|scacciando)\b", "dismissive gesture", "action"),
        
        # Beckoning
        (r"\b(fa\s+)?cenno\b", "beckoning", "action"),
        
        # Silence gesture
        (r"\b(fa\s+)?segno\s+di\s+tatto\b", "silence gesture", "action"),
        
        # Shrugging
        (r"\b(alza|alzando)\s+(?:le\s+)?spalle\b", "shrugging", "action"),
    ]
    
    def __init__(self) -> None:
        """Initialize pose extractor."""
        self._compiled_patterns: List[Tuple[re.Pattern, str, str]] = []
        self._compile_patterns()
    
    def _compile_patterns(self) -> None:
        """Compile regex patterns for performance."""
        for pattern, desc, pose_type in self.POSE_PATTERNS:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                self._compiled_patterns.append((compiled, desc, pose_type))
            except re.error as e:
                logger.warning(f"[PoseExtractor] Invalid pattern '{pattern}': {e}")
    
    def extract_poses(self, text: str) -> List[ExtractedPose]:
        """Extract physical poses from text.
        
        Args:
            text: User input text
            
        Returns:
            List of extracted poses
        """
        poses: List[ExtractedPose] = []
        text_lower = text.lower()
        
        for pattern, desc, pose_type in self._compiled_patterns:
            match = pattern.search(text_lower)
            if match:
                # Check for negation (e.g., "NON incrocia le braccia")
                match_start = match.start()
                context_before = text_lower[max(0, match_start - 20):match_start]
                if "non " in context_before or "non" in context_before[-5:]:
                    continue  # Skip negated poses
                
                pose = ExtractedPose(
                    pose_desc=desc,
                    pose_type=pose_type,
                    confidence=0.9  # High confidence for regex matches
                )
                poses.append(pose)
        
        return poses
    
    def get_forced_visual_description(self, text: str) -> Optional[str]:
        """Get a combined visual description for forced poses.
        
        Args:
            text: User input
            
        Returns:
            Combined English description for SD, or None if no poses found
        """
        poses = self.extract_poses(text)
        if not poses:
            return None
        
        # Combine all pose descriptions
        pose_descs = [p.pose_desc for p in poses]
        
        # Remove duplicates while preserving order
        seen = set()
        unique_descs = []
        for desc in pose_descs:
            if desc not in seen:
                seen.add(desc)
                unique_descs.append(desc)
        
        return ", ".join(unique_descs)
    
    def has_explicit_pose(self, text: str) -> bool:
        """Check if text contains explicit pose instructions.
        
        Args:
            text: User input
            
        Returns:
            True if poses were detected
        """
        return len(self.extract_poses(text)) > 0
    
    def get_poses_by_type(self, text: str, pose_type: str) -> List[ExtractedPose]:
        """Get poses of a specific type.
        
        Args:
            text: User input
            pose_type: Type of pose (legs, arms, head, etc.)
            
        Returns:
            List of matching poses
        """
        all_poses = self.extract_poses(text)
        return [p for p in all_poses if p.pose_type == pose_type]
    
    def get_sd_prompt_from_text(self, text: str) -> str:
        """V4.9: Extract SD prompt from user text for visual bypass.
        
        When LLM censors the scene, use the user's explicit description
        directly for the image prompt.
        
        Args:
            text: User input text
            
        Returns:
            Comma-separated SD prompt from extracted poses
        """
        poses = self.extract_poses(text)
        if not poses:
            return ""
        
        # Build SD prompt from pose descriptions
        descriptions = []
        for pose in poses:
            if pose.pose_desc:
                descriptions.append(pose.pose_desc)
        
        return ", ".join(descriptions) if descriptions else ""


# Singleton instance
_pose_extractor: Optional[PoseExtractor] = None


def get_pose_extractor() -> PoseExtractor:
    """Get singleton pose extractor instance."""
    global _pose_extractor
    if _pose_extractor is None:
        _pose_extractor = PoseExtractor()
    return _pose_extractor
