"""Shared prompt constants for Luna RPG media builders."""
from __future__ import annotations

BASE_PROMPTS = {
    "Luna": (
        "score_9, score_8_up, masterpiece, photorealistic, detailed, atmospheric, "
        "stsdebbie, dynamic pose, 1girl, mature woman, brown hair, shiny skin, head tilt, "
        "massive breasts, cleavage"
    ),
    "Stella": (
        "score_9, score_8_up, masterpiece, NSFW, photorealistic, 1girl, "
        "alice_milf_catchers, massive breasts, cleavage, blonde hair, beautiful blue eyes, "
        "shapely legs, hourglass figure, skinny body, narrow waist, wide hips, "
        "<lora:alice_milf_catchers_lora:0.7> <lora:Expressive_H:0.2>"
    ),
    "Maria": (
        "score_9, score_8_up, stsSmith, ultra-detailed, realistic lighting, 1girl, "
        "mature female, (middle eastern woman:1.5), veiny breasts, black hair, short hair, "
        "evil smile, glowing magic, "
        "<lora:stsSmith-10e:0.65> <lora:Expressive_H:0.2> <lora:FantasyWorldPonyV2:0.40>"
    ),
}

NPC_BASE = (
    "score_9, score_8_up, masterpiece, photorealistic, 1girl, "
    "detailed face, cinematic lighting, 8k, realistic skin texture"
)

NPC_MALE_BASE = (
    "score_9, score_8_up, masterpiece, photorealistic, 1boy, "
    "male npc, detailed face, cinematic lighting, 8k"
)

NEGATIVE_BASE = (
    "score_5, score_4, low quality, worst quality, "
    "anime, manga, cartoon, 3d render, cgi, illustration, painting, drawing, sketch, "
    "monochrome, grayscale, "
    "deformed, bad anatomy, worst face, extra fingers, mutated, "
    "text, watermark, signature, logo, "
    "glasses, sunglasses, eyewear, spectacles, monocle, goggles, eyeglasses, "
    "blurry face, messy face, spotted face, blotched skin, skin blemishes, "
    "uneven eyes, crossed eyes, disfigured face, bad face"
)

ANTI_FUSION_NEGATIVE = (
    "fused bodies, merged anatomy, conjoined twins, shared limbs, "
    "identical faces, same face, cloned appearance, mirror image, "
    "symmetrical poses, same pose, same angle, "
    "monochrome hair, uniform hairstyle, matching outfits, "
    "ambiguous identity, unclear which is which, blended silhouettes, "
    "overlapping bodies without depth, twin, clone, duplicate"
)

DIFFERENTIATION_BOOSTERS = [
    "different hair color",
    "different hair style",
    "different outfits",
    "distinct faces",
    "separate bodies",
    "individual poses",
    "clearly separated",
    "side by side",
    "distinctive appearance",
]

NEGATIVE_PROMPTS = {
    "standard": NEGATIVE_BASE,
    "multi_character": NEGATIVE_BASE + ", " + ANTI_FUSION_NEGATIVE,
}

__all__ = [
    "BASE_PROMPTS",
    "NPC_BASE",
    "NPC_MALE_BASE",
    "NEGATIVE_BASE",
    "NEGATIVE_PROMPTS",
    "DIFFERENTIATION_BOOSTERS",
]

