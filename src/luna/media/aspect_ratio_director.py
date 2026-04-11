"""Director of Photography (DoP) - Aspect Ratio Decision System.

An intelligent system that analyzes scene descriptions and decides the optimal
aspect ratio for image and video generation, mimicking a real cinematographer's
creative decisions.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Tuple, Optional, Any
from dataclasses import dataclass


class AspectRatio(Enum):
    """Supported aspect ratios for image/video generation."""
    LANDSCAPE = "landscape"  # 736x512 - Cinemascope, wide scenes
    PORTRAIT = "portrait"    # 512x736 - Vertical, full body, portraits
    SQUARE = "square"        # 1024x1024 - Balanced, medium shots


@dataclass
class AspectRatioChoice:
    """Result of aspect ratio decision."""
    ratio: AspectRatio
    width: int
    height: int
    reason: str  # Explanation of the cinematographic choice


class DirectorOfPhotography:
    """Expert cinematographer AI that decides framing and composition.
    
    This class analyzes scene context and makes professional cinematography
    decisions about aspect ratio based on:
    - Composition (number of elements)
    - Scene dynamics (horizontal vs vertical action)
    - Intimacy level (close-up vs wide context)
    - Architecture/location (wide spaces vs tall structures)
    """
    
    # Resolution mappings (all divisible by 16 for WanVideo compatibility)
    RESOLUTIONS: Dict[AspectRatio, Tuple[int, int]] = {
        AspectRatio.LANDSCAPE: (736, 512),  # ~1.44:1 - Wide cinematic
        AspectRatio.PORTRAIT: (512, 736),   # ~0.69:1 - Tall vertical
        AspectRatio.SQUARE: (1024, 1024),   # 1:1 - Balanced
    }
    
    # Keywords that suggest landscape orientation
    LANDSCAPE_INDICATORS = [
        # Environment types
        "panorama", "landscape", "horizon", "vista", "scenery", "outdoor",
        "street", "avenue", "plaza", "courtyard", "garden", "park",
        # Wide spaces
        "wide", "broad", "expansive", "vast", "open space", "field",
        "hall", "corridor", "alley", "path", "road", "beach", "shore",
        # Group shots
        "group", "crowd", "audience", "classroom", "assembly", "gathering",
        "multiple people", "several characters", "ensemble",
        # Horizontal action
        "walking side", "running across", "chase", "pursuit", "flee",
        "driving", "riding", "moving horizontally", "panning",
        # Architectural wide
        "building exterior", "cityscape", "skyline", "architecture wide",
        "living room", "classroom wide", "gymnasium", "cafeteria",
    ]
    
    # Keywords that suggest portrait orientation
    PORTRAIT_INDICATORS = [
        # Framing types
        "full body", "standing", "tall", "towering", "looming",
        "vertical", "upright", "column", "pillar", "tower",
        # Portrait types
        "portrait", "headshot", "profile", "silhouette",
        "looking up", "looking down", "from below", "from above",
        # Single subject vertical
        "single figure", "solitary", "alone", "isolated figure",
        # Intimate vertical
        "close intimacy", "personal space", "face to face", "eye contact",
        # Tall architecture
        "staircase", "ladder", "elevator shaft", "clock tower",
        "high ceiling", "atrium", "vertical space", "climbing",
        # Body emphasis
        "legs", "full length", "entire body", "standing pose",
        "stretching", "reaching up", "falling", "jumping up",
    ]
    
    # Keywords that suggest square (balanced/default)
    SQUARE_INDICATORS = [
        # Balanced compositions
        "medium shot", "waist up", "chest up", "half body",
        "balanced", "centered", "symmetrical", "portrait medium",
        # Intimate but balanced
        "intimate", "conversation", "dialogue", "interaction",
        "sitting", "seated", "at desk", "on bench", "at table",
        # Close but not extreme
        "close up", "near", "close", "personal", "warm",
        # Default safe shots
        "standard", "neutral", "default", "safe", "versatile",
    ]
    
    @classmethod
    def analyze_scene(
        cls,
        scene_description: str,
        location_id: Optional[str] = None,
        companion_name: Optional[str] = None,
        pose_hint: Optional[str] = None,
        composition_hint: Optional[str] = None,
    ) -> AspectRatioChoice:
        """Analyze scene and decide optimal aspect ratio.
        
        Args:
            scene_description: Visual description of the scene
            location_id: Current location identifier
            companion_name: Active companion name
            pose_hint: Suggested pose (standing, sitting, etc.)
            composition_hint: Composition type (close_up, medium_shot, etc.)
            
        Returns:
            AspectRatioChoice with ratio, dimensions, and reasoning
        """
        text = scene_description.lower()
        
        # Score each orientation
        landscape_score = cls._calculate_score(text, cls.LANDSCAPE_INDICATORS)
        portrait_score = cls._calculate_score(text, cls.PORTRAIT_INDICATORS)
        square_score = cls._calculate_score(text, cls.SQUARE_INDICATORS)
        
        # Apply contextual modifiers
        landscape_score, portrait_score, square_score = cls._apply_context_modifiers(
            landscape_score, portrait_score, square_score,
            location_id, companion_name, pose_hint, composition_hint, text
        )
        
        # Decide winner
        scores = {
            AspectRatio.LANDSCAPE: landscape_score,
            AspectRatio.PORTRAIT: portrait_score,
            AspectRatio.SQUARE: square_score,
        }
        
        chosen_ratio = max(scores, key=scores.get)
        
        # Generate reasoning
        reason = cls._generate_reasoning(
            chosen_ratio, landscape_score, portrait_score, square_score,
            text, composition_hint
        )
        
        width, height = cls.RESOLUTIONS[chosen_ratio]
        
        return AspectRatioChoice(
            ratio=chosen_ratio,
            width=width,
            height=height,
            reason=reason
        )
    
    @classmethod
    def _calculate_score(cls, text: str, indicators: list) -> int:
        """Calculate match score for a set of indicators."""
        score = 0
        for indicator in indicators:
            if indicator in text:
                # Longer matches get higher scores (more specific)
                score += len(indicator.split()) + 1
        return score
    
    @classmethod
    def _apply_context_modifiers(
        cls,
        landscape: int,
        portrait: int,
        square: int,
        location_id: Optional[str],
        companion_name: Optional[str],
        pose_hint: Optional[str],
        composition_hint: Optional[str],
        text: str
    ) -> Tuple[int, int, int]:
        """Apply contextual modifiers to scores."""
        
        # Composition hint is strong signal
        if composition_hint:
            comp_lower = composition_hint.lower()
            if any(w in comp_lower for w in ["wide", "scene", "group", "establish"]):
                landscape += 5
            elif any(w in comp_lower for w in ["portrait", "full_body", "tall"]):
                portrait += 5
            elif any(w in comp_lower for w in ["medium", "close_up", "waist"]):
                square += 3
        
        # Pose hint
        if pose_hint:
            pose_lower = pose_hint.lower()
            if any(w in pose_lower for w in ["standing", "walking", "tall"]):
                portrait += 2
            elif any(w in pose_lower for w in ["sitting", "seated", "at desk"]):
                square += 2
            elif any(w in pose_lower for w in ["running", "chase", "flee"]):
                landscape += 2
        
        # Location-based hints
        if location_id:
            loc_lower = location_id.lower()
            if any(w in loc_lower for w in ["corridor", "hall", "street", "field", "beach"]):
                landscape += 3
            elif any(w in loc_lower for w in ["tower", "stair", "elevator", "shaft"]):
                portrait += 3
            elif any(w in loc_lower for w in ["office", "classroom", "room", "bathroom"]):
                square += 2  # Interior spaces often work well as square
        
        # Solo character vs group
        if "solo" in text or "single" in text or "alone" in text:
            portrait += 2
        if "group" in text or "crowd" in text or "multiple" in text:
            landscape += 3
        
        return landscape, portrait, square
    
    @classmethod
    def _generate_reasoning(
        cls,
        chosen: AspectRatio,
        landscape: int,
        portrait: int,
        square: int,
        text: str,
        composition_hint: Optional[str]
    ) -> str:
        """Generate human-readable explanation of the choice."""
        
        reasons = {
            AspectRatio.LANDSCAPE: [
                "Ampia inquadratura orizzontale per catturare l'ambiente",
                "Composizione cinematografica Cinemascope per scene dinamiche",
                "Panoramica ideale per location estese e gruppi",
            ],
            AspectRatio.PORTRAIT: [
                "Inquadratura verticale per enfatizzare la figura intera",
                "Ritratto classico che valorizza la verticalità del soggetto",
                "Composizione intima focalizzata sul personaggio",
            ],
            AspectRatio.SQUARE: [
                "Inquadratura bilanciata per medium shot armoniosi",
                "Composizione versatile che bilancia soggetto e contesto",
                "Formato equilibrato ideale per conversazioni e scene intime",
            ],
        }
        
        import random
        base_reason = random.choice(reasons[chosen])
        
        # Add technical details
        if chosen == AspectRatio.LANDSCAPE and landscape > portrait + 3:
            base_reason += " (scena d'azione orizzontale rilevata)"
        elif chosen == AspectRatio.PORTRAIT and portrait > landscape + 3:
            base_reason += " (ritratto verticale privilegiato)"
        elif chosen == AspectRatio.SQUARE:
            base_reason += " (scelta sicura e bilanciata)"
        
        return base_reason
    
    @classmethod
    def get_dimensions(cls, aspect_ratio: AspectRatio) -> Tuple[int, int]:
        """Get width and height for an aspect ratio."""
        return cls.RESOLUTIONS[aspect_ratio]
    
    @classmethod
    def from_string(cls, ratio_str: str) -> AspectRatio:
        """Parse aspect ratio from string."""
        ratio_lower = ratio_str.lower().strip()
        
        if ratio_lower in ["landscape", "wide", "horizontal", "cinemascope"]:
            return AspectRatio.LANDSCAPE
        elif ratio_lower in ["portrait", "vertical", "tall"]:
            return AspectRatio.PORTRAIT
        elif ratio_lower in ["square", "balanced", "1:1"]:
            return AspectRatio.SQUARE
        else:
            # Default to square for safety
            return AspectRatio.SQUARE


# Singleton instance
dop = DirectorOfPhotography()


def analyze_scene(
    scene_description: str,
    location_id: Optional[str] = None,
    companion_name: Optional[str] = None,
    pose_hint: Optional[str] = None,
    composition_hint: Optional[str] = None,
) -> AspectRatioChoice:
    """Convenience function to analyze scene and get aspect ratio."""
    return DirectorOfPhotography.analyze_scene(
        scene_description=scene_description,
        location_id=location_id,
        companion_name=companion_name,
        pose_hint=pose_hint,
        composition_hint=composition_hint,
    )
