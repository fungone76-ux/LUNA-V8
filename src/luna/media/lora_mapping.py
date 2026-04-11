"""LoRA Mapping System - Automatic LoRA selection based on tags and outfit state.

V4.6: Added clothing LoRAs for hot/NSFW moments with automatic outfit-based activation.

IMPORTANTE: I nomi LoRA qui sotto sono ESEMPI. Devi cercare i LoRA reali su CivitAI
e aggiornare i nomi file in CLOTHING_LORAS.

Come cercare su CivitAI:
1. Vai su https://civitai.com
2. Cerca le categorie indicate nelle note di ogni LoRA
3. Scarica i file .safetensors
4. Mettili nella cartella models/loras/ di ComfyUI
5. Aggiorna i nomi in questo file
"""

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional, Any
import re


class LoraMapping:
    """
    Wrapper-classe per il servizio di mappatura LoRA.
    Viene istanziato dal Dispatcher e passato ai servizi
    che ne hanno bisogno, come il PromptBuilder.
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.enabled = False  # LoRA mapping disabilitato permanentemente
    
    def toggle(self) -> bool:
        """Attiva/disattiva i LoRA. Ritorna nuovo stato."""
        self.enabled = not self.enabled
        status = "ATTIVATI" if self.enabled else "DISATTIVATI"
        logger.debug(f"[LoraMapping] LoRA {status}")
        return self.enabled
    
    def is_enabled(self) -> bool:
        """Ritorna stato attuale."""
        return self.enabled
    
    def set_enabled(self, value: bool) -> None:
        """Imposta stato esplicitamente."""
        self.enabled = value
        status = "ATTIVATI" if self.enabled else "DISATTIVATI"
        logger.debug(f"[LoraMapping] LoRA {status}")

    def select_loras(self, tags: list[str], character: str = "", outfit_state: Optional[Dict] = None) -> list[tuple[str, float]]:
        """
        Seleziona i LoRA appropriati in base ai tag, al personaggio e allo stato outfit.
        
        Args:
            tags: Lista di tag/tags SD
            character: Nome del personaggio
            outfit_state: Stato outfit opzionale (per attivare LoRA clothing)
        
        Returns:
            Lista di tuple (nome_lora, peso)
        """
        # Se disabilitato, ritorna lista vuota
        if not self.enabled:
            return []
        
        selected = []
        
        # 1. PRIORITÀ: Clothing LoRA basati su outfit (se rilevante)
        clothing_entries = self._select_clothing_loras(tags, outfit_state)
        if clothing_entries:
            # Se abbiamo clothing LoRA rilevanti, usali come primari
            selected.extend(clothing_entries[:2])  # Max 2 clothing
            logger.debug(f"[LoraMapping] Clothing LoRA selected: {[e.name for e in clothing_entries[:2]]}")
        
        # 2. Se non abbiamo abbastanza LoRA, aggiungi dai tags
        if len(selected) < 2:
            remaining_slots = 2 - len(selected)
            entries = pick_loras(tags, visual="", sdxl=False, max_total=remaining_slots, use_fallbacks=False)
            selected.extend(entries)
            if entries:
                logger.debug(f"[LoraMapping] Tag-based LoRA: {[e.name for e in entries]}")
        
        # 3. Se ancora vuoto, usa fallback minimi (solo 1)
        if not selected:
            # Solo 1 fallback, non tutti e 3
            selected.append(LoRAEntry(name="add_detail", weight=0.20, category="utility", keywords=()))
            logger.debug("[LoraMapping] Using minimal fallback")
        
        return [(e.name, float(e.weight)) for e in selected[:MAX_TOTAL_LORAS]]

    def _select_clothing_loras(self, tags: List[str], outfit_state: Optional[Dict]) -> List[LoRAEntry]:
        """Seleziona LoRA clothing basati sullo stato outfit e contesto."""
        if not outfit_state:
            return []
        
        text = " ".join(tags).lower()
        outfit_desc = outfit_state.get("description", "").lower()
        components = outfit_state.get("components", {})
        
        selected = []
        
        # === CLOTHING LoRA SELECTION ===
        
        # Bikini / Swimsuit
        if any(k in text or k in outfit_desc for k in ["bikini", "swimsuit", "costume", "bagno"]):
            if "bikini" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["bikini"])
        
        # Lingerie / Intimo sexy
        if any(k in text or k in outfit_desc for k in ["lingerie", "intimo", "mutande", "reggiseno", "lace", "panties"]):
            if "lingerie" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["lingerie"])
        
        # See-through / Wet / Trasparente
        if any(k in text or k in outfit_desc for k in ["see-through", "trasparente", "bagnato", "wet", "sheer"]):
            if "wet_clothes" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["wet_clothes"])
        
        # Uniforme scolastica
        if any(k in text or k in outfit_desc for k in ["uniforme", "school uniform", "divisa", "studentessa"]):
            if "school_uniform" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["school_uniform"])
        
        # Vestito elegante / Evening dress
        if any(k in text or k in outfit_desc for k in ["dress", "vestito", "abito", "evening", "sera", "elegant"]):
            if "evening_dress" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["evening_dress"])
        
        # Pigiama / Nightwear
        if any(k in text or k in outfit_desc for k in ["pigiama", "pajamas", "sleepwear", "notte", "nightgown"]):
            if "sleepwear" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["sleepwear"])
        
        # Gym / Sportswear
        if any(k in text or k in outfit_desc for k in ["gym", "sportswear", "sportivo", "athletic", "palestra"]):
            if "sportswear" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["sportswear"])
        
        # Micro skirt / Mini
        if any(k in text or k in outfit_desc for k in ["micro skirt", "mini skirt", "minigonna", "short skirt"]):
            if "micro_skirt" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["micro_skirt"])
        
        # Pantyhose / Calze
        if components.get("pantyhose") or any(k in text or k in outfit_desc for k in ["pantyhose", "collant", "calze", "stockings"]):
            if "pantyhose_detail" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["pantyhose_detail"])
        
        # Maid / Maid outfit
        if any(k in text or k in outfit_desc for k in ["maid", "cameriera", "divisa da camera"]):
            if "maid_outfit" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["maid_outfit"])
        
        # Nurse / Nurse uniform
        if any(k in text or k in outfit_desc for k in ["nurse", "infermiera", "doctor", "medico"]):
            if "nurse_uniform" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["nurse_uniform"])
        
        # Yoga pants / Leggings
        if any(k in text or k in outfit_desc for k in ["yoga pants", "leggings", "tight pants", "pantaloni attillati"]):
            if "yoga_pants" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["yoga_pants"])
        
        # Fishnet / Rete
        if any(k in text or k in outfit_desc for k in ["fishnet", "rete", "calze a rete", "fishnet stockings"]):
            if "fishnet_stockings" in CLOTHING_LORAS:
                selected.append(CLOTHING_LORAS["fishnet_stockings"])
        
        return selected

    def lora_prompt_suffix(self, entries: List[LoRAEntry], include_triggers: bool = True) -> str:
        """
        Converte i LoRA in stringa: token <lora:...:...> + (opzionale) richiamo testuale.
        """
        if not entries:
            return ""
        tokens = [f"<lora:{e.name}:{e.weight:.2f}>" for e in entries]
        if include_triggers:
            triggers = [_display_trigger(e) for e in entries]
            parts = tokens + triggers
        else:
            parts = tokens
        return ", " + ", ".join(parts)


# ============================================================================
# DATA CLASSES & CONSTANTS
# ============================================================================

@dataclass(frozen=True)
class LoRAEntry:
    name: str
    weight: float
    category: str
    keywords: Tuple[str, ...]
    sdxl_ok: bool = True
    notes: str = ""
    triggers: Tuple[str, ...] = ()


CATEGORY_LIMITS: Dict[str, int] = {
    "adapter": 1,
    "utility": 2,
    "realism": 1,
    "style": 1,
    "slider": 1,
    "morph": 1,
    "nsfw": 1,
    "clothing": 2,  # Aumentato per permettere più LoRA clothing
}
MAX_TOTAL_LORAS = 3

FALLBACKS: List[Tuple[str, float]] = [
    ("add_detail", 0.20),
    ("flux_realism_lora", 0.30),
    ("detailed_notrigger", 0.25),
]

# ============================================================================
# CLOTHING LoRAs - ESEMPI! Aggiorna con i nomi file reali da CivitAI
# ============================================================================

CLOTHING_LORAS: Dict[str, LoRAEntry] = {
    # --- Bikini & Swimwear ---
    # Scaricato da: https://civitai.com/api/download/models/699239
    # File: Bikini_XL_v2.safetensors (436 MB)
    "bikini": LoRAEntry(
        name="Bikini_XL_v2",  # ✅ File scaricato su RunPod
        weight=0.55, category="clothing",
        keywords=("bikini", "swimsuit", "costume", "bagno", "swimwear", "beach", "spiaggia", "costume da bagno", "mare", "piscina"),
        notes="Bikini LoRA scaricato da CivitAI (ID: 699239). Peso consigliato: 0.5-0.6",
        triggers=("bikini style",)
    ),
    
    # --- Lingerie & Intimo ---
    # Scaricato da: https://civitai.com/api/download/models/762484
    # File: Lingerie_Lace_XL.safetensors
    "lingerie": LoRAEntry(
        name="Lingerie_Lace_XL",  # ✅ File scaricato su RunPod
        weight=0.60, category="clothing",
        keywords=("lingerie", "lace", "intimo", "mutande", "reggiseno", "panties", "bra", "sexy underwear", "perizoma", "tanghe", "pizzo", "biancheria intima", "completino", "body", "corpino"),
        notes="Lingerie LoRA scaricato da CivitAI (ID: 762484). Peso consigliato: 0.5-0.7",
        triggers=("lace lingerie", "detailed lace")
    ),
    
    # --- See-through & Wet / Oily ---
    # Scaricato da: https://civitai.com/api/download/models/528650
    # File: Oily_Black_Silk_OnePiece_XL.safetensors (Oily Black Silk One-Piece)
    "wet_clothes": LoRAEntry(
        name="Oily_Black_Silk_OnePiece_XL",  # ✅ File scaricato su RunPod
        weight=0.55, category="clothing",
        keywords=("wet", "bagnato", "see-through", "trasparente", "sheer", "wet shirt", "wet dress", "oily", "silk", "shiny", "latex", "glossy", "inzuppato", "fradicio", "bagnata", "splendente", "lucido", "seta", "oleoso"),
        notes="Oily Black Silk One-Piece LoRA scaricato da CivitAI (ID: 528650). Effetto bagnato/oleoso/lucido. Peso consigliato: 0.5-0.6",
        triggers=("oily skin", "shiny clothes", "wet look")
    ),
    
    # --- School Uniform ---
    # DISABLED: file non presente in ComfyUI.
    # "school_uniform": LoRAEntry(
    #     name="School_Uniform_XL",
    #     weight=0.55, category="clothing",
    #     keywords=("school uniform", "uniforme scolastica", "studentessa", "schoolgirl", "sailor uniform", "seifuku"),
    #     triggers=("school uniform", "sailor uniform")
    # ),
    
    # --- Evening Dress ---
    # Scaricato da: https://civitai.com/api/download/models/593593
    # File: Dongtan_Dress_XL.safetensors (Dongtan Style Dress)
    "evening_dress": LoRAEntry(
        name="Dongtan_Dress_XL",  # ✅ File scaricato su RunPod
        weight=0.55, category="clothing",
        keywords=("evening dress", "abito da sera", "gown", "elegant dress", "vestito elegante", "formal dress", "dongtan", "dress", "abito", "vestito", "cerimonia", "elegante", "sera", "da sera", "lungo", "scollato"),
        notes="Dongtan Dress LoRA scaricato da CivitAI (ID: 593593). Stile elegante/sera. Peso consigliato: 0.5-0.6",
        triggers=("evening gown", "elegant dress", "dongtan dress")
    ),
    
    # --- Sleepwear & Nightwear / Towel ---
    # Scaricato da: https://civitai.com/api/download/models/631599
    # File: Towel_XL.safetensors (Wrapped in Towel)
    "sleepwear": LoRAEntry(
        name="Towel_XL",  # ✅ File scaricato su RunPod
        weight=0.60, category="clothing",
        keywords=("towel", "asciugamano", "wrapped in towel", "towel only", "bath towel", "after shower", "sleepwear", "nightwear", "avvolta in asciugamano", "solo asciugamano", "dopo doccia", "bagno", "asciugamani", "spogliatoio"),
        notes="Towel LoRA scaricato da CivitAI (ID: 631599). Per scene post-doccia/bagno. Peso consigliato: 0.5-0.7",
        triggers=("wrapped in towel", "towel only")
    ),
    
    # --- Sportswear ---
    # Scaricato da: https://civitai.com/api/download/models/648330
    # File: Sportswear_XL.safetensors
    "sportswear": LoRAEntry(
        name="Sportswear_XL",  # ✅ File scaricato su RunPod
        weight=0.55, category="clothing",
        keywords=("sportswear", "gym clothes", "athletic wear", "tuta sportiva", "palestra", "yoga pants", "leggings", "sport", "ginnastica", "fitness", "tuta", "canotta", "top sportivo"),
        notes="Sportswear LoRA scaricato da CivitAI (ID: 648330). Abbigliamento sportivo. Peso consigliato: 0.5-0.6",
        triggers=("athletic wear", "sportswear", "gym outfit")
    ),
    
    # --- Micro Skirt ---
    # DISABLED: file non presente in ComfyUI.
    # "micro_skirt": LoRAEntry(
    #     name="Micro_Skirt_XL",
    #     weight=0.60, category="clothing",
    #     keywords=("micro skirt", "mini skirt", "minigonna", "short skirt", "microskirt", "ultra short"),
    #     triggers=("micro skirt", "mini skirt")
    # ),
    
    # --- Pantyhose Detail ---
    # Scaricato da: https://civitai.com/api/download/models/602428
    # File: Pantyhose_XL.safetensors
    "pantyhose_detail": LoRAEntry(
        name="Pantyhose_XL",  # ✅ File scaricato su RunPod
        weight=0.50, category="clothing",
        keywords=("pantyhose", "collant", "calze", "stockings", "nylon", "tights", "autoreggenti", "velate", "trasparenti", "rete", "calzini", "gambali"),
        notes="Pantyhose LoRA scaricato da CivitAI (ID: 602428). Dettaglio realistico per collant e calze. Peso consigliato: 0.45-0.6",
        triggers=("sheer pantyhose", "detailed stockings", "pantyhose")
    ),
    
    # --- Maid Outfit ---
    # DISABLED: file non presente in ComfyUI.
    # "maid_outfit": LoRAEntry(
    #     name="Maid_Outfit_Classic_XL",
    #     weight=0.55, category="clothing",
    #     keywords=("maid", "cameriera", "maid uniform", "maid dress", "french maid"),
    #     triggers=("maid outfit", "french maid")
    # ),

    # --- Nurse Uniform ---
    # DISABLED: file non presente in ComfyUI.
    # "nurse_uniform": LoRAEntry(
    #     name="Nurse_Uniform_XL",
    #     weight=0.55, category="clothing",
    #     keywords=("nurse", "infermiera", "nurse uniform", "medical", "doctor", "white coat"),
    #     triggers=("nurse uniform", "medical outfit")
    # ),
    
    # --- Teacher/Office ---
    # DISABLED: file non presente in ComfyUI. Trovare il nome corretto su CivitAI.
    # "teacher_outfit": LoRAEntry(
    #     name="Teacher_Office_Lady_XL",
    #     weight=0.50, category="clothing",
    #     keywords=("teacher", "professoressa", "office lady", "business suit", "tight skirt", "secretary"),
    #     notes="Cerca su CivitAI: teacher, office lady, business suit",
    #     triggers=("office lady", "teacher outfit")
    # ),
    
    # --- Slutty Dress / Vestiti Sexy ---
    # Scaricato da: https://civitai.com/api/download/models/859460
    # File: Slutty_Dress_XL.safetensors
    "slutty_dress": LoRAEntry(
        name="Slutty_Dress_XL",  # ✅ File scaricato su RunPod
        weight=0.60, category="clothing",
        keywords=("slutty dress", "sexy dress", "revealing dress", "provocative dress", "hot dress", "skimpy dress", "vestito sexy", "abito sexy", "vestito troia", "succinto", "cortissimo", "micro vestito", "scollatissimo", "provocante", "sconcio"),
        notes="Slutty Dress LoRA scaricato da CivitAI (ID: 859460). Peso consigliato: 0.5-0.7",
        triggers=("slutty dress", "sexy outfit")
    ),
    
    # --- Yoga Pants / Leggings ---
    # Scaricato da: https://civitai.com/api/download/models/508497
    # File: Yoga_Pants_XL.safetensors
    "yoga_pants": LoRAEntry(
        name="Yoga_Pants_XL",  # ✅ File scaricato su RunPod
        weight=0.55, category="clothing",
        keywords=("yoga pants", "leggings", "tight pants", "pantaloni attillati", "sport pants", "tuta", "palestra", "sportiva", "allenamento", "ginnastica", "compressione", "aderenti"),
        notes="Yoga Pants LoRA scaricato da CivitAI (ID: 508497). Peso consigliato: 0.5-0.6",
        triggers=("yoga pants", "detailed leggings")
    ),
    
    # --- Fishnet Stockings ---
    # DISABLED: file non presente in ComfyUI.
    # "fishnet_stockings": LoRAEntry(
    #     name="Fishnet_Stockings_XL",
    #     weight=0.50, category="clothing",
    #     keywords=("fishnet", "rete", "calze a rete", "fishnet stockings", "fishnets"),
    #     triggers=("fishnet stockings", "fishnets")
    # ),
    
    # --- Sexy Clothing (Generale) ---
    # Scaricato da: https://civitai.com/api/download/models/1148839
    # File: Sexy_Clothing_XL.safetensors
    "sexy_clothing": LoRAEntry(
        name="Sexy_Clothing_XL",  # ✅ File scaricato su RunPod
        weight=0.55, category="clothing",
        keywords=("sexy clothing", "sexy outfit", "revealing clothes", "hot outfit", "sexy attire", "provocative clothing", "abbigliamento sexy", "vestiti sexy", "hot", "provocante", "trasgressivo", "ardente", "sensuale"),
        notes="Sexy Clothing LoRA generico scaricato da CivitAI (ID: 1148839). Peso consigliato: 0.5-0.6",
        triggers=("sexy clothing", "sexy outfit")
    ),
}

# ============================================================================
# GUIDA RICERCA CIVITAI - Categorie da cercare:
# ============================================================================
"""
CATEGORIE PRINCIPALI DA CERCARE SU CIVITAI:

1. BIKINI/SWIMWEAR:
   - Cerca: "bikini", "swimsuit", "beach", "swimwear"
   - Consigliato: qualsiasi LoRA con almeno 4.5 stelle e 50+ download

2. LINGERIE:
   - Cerca: "lingerie", "lace lingerie", "underwear", "bra"
   - Consigliato: cercare "detailed lingerie" o "lace detail"

3. WET/SEE-THROUGH:
   - Cerca: "wet clothes", "wet shirt", "see through", "wet look"
   - Attenzione: alcuni sono NSFW, scegliere in base alle preferenze

4. SCHOOL UNIFORM:
   - Cerca: "school uniform", "seifuku", "sailor uniform"
   - Molti disponibili, cercare "japanese school uniform"

5. PANTYHOSE/STOCKINGS:
   - Cerca: "pantyhose", "stockings", "nylon", "tights"
   - Consigliato: "detailed pantyhose" o "sheer pantyhose"

6. MAID OUTFIT:
   - Cerca: "maid", "french maid", "maid uniform"
   - Classico, molti disponibili

7. YOGA PANTS/LEGGINGS:
   - Cerca: "yoga pants", "leggings", "tight pants"
   - Cercare "detailed" per texture realistiche

8. MICRO SKIRT:
   - Cerca: "micro skirt", "mini skirt", "short skirt"
   - Spesso incluso in "clothing" LoRA generali

SUGGERIMENTI:
- Scarica solo LoRA con formato .safetensors
- Peso consigliato: 0.4-0.7 (da testare)
- Controlla che siano compatibili con il tuo checkpoint SD
- Salva i file nella cartella models/loras/ di ComfyUI
"""

# ============================================================================
# STANDARD LoRAs (utility, realism, etc.)
# ============================================================================

LORAS: List[LoRAEntry] = [
    # --- Adapter ---
    LoRAEntry(
        name="ip-adapter-faceid-plusv2_sdxl_lora",
        weight=0.8, category="adapter",
        keywords=("reference face", "same person", "face match", "face reference", "identity match", "match face", "keep identity"),
        notes="Align face to a reference image (IP-Adapter).",
        triggers=("face id adapter",)
    ),

    # --- Utility / Quality ---
    LoRAEntry(
        name="add_detail",
        weight=0.4, category="utility", sdxl_ok=False,
        keywords=("detail", "details", "high detail", "sharp", "sharpen", "clarity", "texture"),
        notes="Non-XL variant.",
        triggers=("add detail",)
    ),
    LoRAEntry(
        name="Hand v2",
        weight=0.7, category="utility",
        keywords=("hand", "hands", "fingers", "finger", "palm", "palms", "grip", "grasp", "hand pose", "hand gesture", "gestures"),
        notes="Improves hands/fingers.",
        triggers=("hands detail",)
    ),
    LoRAEntry(
        name="detailed_notrigger",
        weight=0.45, category="utility",
        keywords=("detail", "details", "micro detail", "texture", "sharp", "clarity", "crisp"),
        triggers=("detailed helper",)
    ),
    LoRAEntry(
        name="epiRealismHelper",
        weight=0.4, category="utility",
        keywords=("realism helper", "skin detail", "skin texture", "natural skin", "realistic", "pores", "skin pores"),
        triggers=("realism helper",)
    ),

    # --- Realism / Beautify ---
    LoRAEntry(
        name="KrekkovLycoXLV2",
        weight=0.5, category="realism",
        keywords=("xl", "detail", "realism", "texture", "sharp", "crisp", "clarity"),
        triggers=("krekkov xl",)
    ),
    LoRAEntry(
        name="SummertimeSagaXL_Pony",
        weight=0.45, category="realism",
        keywords=("toon realism", "comic realism", "summertime saga", "pony", "mlp", "cel shading realistic"),
        notes="Toon-realism look.",
        triggers=("summertime saga xl",)
    ),
    LoRAEntry(
        name="flux_realism_lora",
        weight=0.5, category="realism",
        keywords=("realism", "photo realism", "photorealistic", "lifelike", "true to life", "natural light", "natural lighting", "soft light", "soft lighting", "cinematic lighting"),
        triggers=("photo realism",)
    ),

    # --- Artistic styles ---
    LoRAEntry(
        name="Abstract Painting - Style [LoRA] - Pony V6",
        weight=0.6, category="style",
        keywords=("painting", "painterly", "abstract", "brush stroke", "oil paint", "oil painting", "canvas texture", "impasto", "pony"),
        triggers=("abstract painting style",)
    ),
    LoRAEntry(
        name="Expressive_H-000001",
        weight=0.2, category="style",
        keywords=("expressive", "emotional", "facial expression", "intense gaze", "expressive face", "expressive eyes"),
        notes="Enhances facial expressiveness; keep low weight.",
        triggers=("expressive face",)
    ),
    LoRAEntry(
        name="perfection style v2d",
        weight=0.5, category="style",
        keywords=("perfect", "beauty perfection", "studio beauty", "beauty retouch", "polished look", "airbrushed"),
        triggers=("perfection style",)
    ),

    # --- Sliders ---
    LoRAEntry(
        name="Pony Realism Slider",
        weight=0.5, category="slider",
        keywords=("pony", "mlp", "realism"),
        triggers=("pony realism slider",)
    ),
    LoRAEntry(
        name="StS_PonyXL_Detail_Slider_v1.4_iteration_3",
        weight=0.5, category="slider",
        keywords=("pony", "xl detail", "pony detail", "texture", "detail slider"),
        triggers=("pony xl detail slider",)
    ),

    # --- Morph (body shape) ---
    LoRAEntry(
        name="huge fake tits XL v3",
        weight=0.5, category="morph",
        keywords=("fake tits", "implants", "very large breasts", "enormous breasts", "huge boobs", "giant breasts"),
        triggers=("huge fake tits",)
    ),
    LoRAEntry(
        name="Penis Size_alpha1.0_rank4_noxattn_last",
        weight=0.6, category="morph",
        keywords=("penis size", "large penis", "male nsfw", "big penis"),
        triggers=("penis size",)
    ),

    # --- NSFW / Poses ---
    # Scaricato da: https://civitai.com/api/download/models/832658
    # File: Masturbation_Pose_XL.safetensors
    LoRAEntry(
        name="Masturbation_Pose_XL",  # ✅ File scaricato su RunPod
        weight=0.60, category="nsfw",
        keywords=("masturbation", "self play", "self pleasure", "fingers in", "solo play", "masturbating", "touching herself", "masturbazione", "si masturba", "si tocca", "dita dentro", "sesso solitario", "autoerotismo", "masturbarsi", "toccare"),
        notes="Masturbation pose LoRA scaricato da CivitAI (ID: 832658). Peso consigliato: 0.55-0.7",
        triggers=("masturbation pose", "solo play")
    ),
    # Scaricato da: https://civitai.com/api/download/models/809818
    # File: Self_Anal_Fisting_XL.safetensors
    LoRAEntry(
        name="Self_Anal_Fisting_XL",  # ✅ File scaricato su RunPod
        weight=0.65, category="nsfw",
        keywords=("anal fisting", "self fisting", "anal penetration", "extreme anal", "fisting", "fisting anale", "auto fisting", "penetrazione anale", "pugno", "estremo", "ano", "dilatazione"),
        notes="Self Anal Fisting LoRA scaricato da CivitAI (ID: 809818). Peso consigliato: 0.6-0.7",
        triggers=("anal fisting", "extreme pose")
    ),
    # Scaricato da: https://civitai.com/api/download/models/556162
    # File: Dildo_Masturbation_XL.safetensors
    LoRAEntry(
        name="Dildo_Masturbation_XL",  # ✅ File scaricato su RunPod
        weight=0.60, category="nsfw",
        keywords=("dildo", "toy", "masturbation", "sex toy", "vibrator", "using dildo", "solo toy", "vibratore", "giocattolo", "oggetto", "fake", "fallo", "godimento", "penetrazione oggetto"),
        notes="Dildo Masturbation LoRA scaricato da CivitAI (ID: 556162). Peso consigliato: 0.55-0.65",
        triggers=("dildo masturbation", "toy play")
    ),
    LoRAEntry(
        name="sex_Flux_5",
        weight=0.55, category="nsfw",
        keywords=("sex scene", "intercourse", "vagina", "penetrative sex", "sexual position", "sex pose"),
        triggers=("sex scene",)
    ),
    # Scaricato da: https://civitai.com/api/download/models/597535
    # File: Table_Humping_XL.safetensors
    LoRAEntry(
        name="Table_Humping_XL",  # ✅ File scaricato su RunPod
        weight=0.60, category="nsfw",
        keywords=("table humping", "humping table", "grinding table", "table sex", "on table", "rubbing table", "sfregare tavolo", "tavolo", "sfregamento", "grinding", "strofinare", "scrivania", "bancone", "mobilio"),
        notes="Table Humping LoRA scaricato da CivitAI (ID: 597535). Peso consigliato: 0.55-0.65",
        triggers=("table humping", "grinding")
    ),
    # Scaricato da: https://civitai.com/api/download/models/619176
    # File: Pillow_Humping_XL.safetensors
    LoRAEntry(
        name="Pillow_Humping_XL",  # ✅ File scaricato su RunPod
        weight=0.60, category="nsfw",
        keywords=("pillow humping", "humping pillow", "grinding pillow", "cushion humping", "riding pillow", "cuscino", "sfregare cuscino", "cavalcando cuscino", "cuscini", "divano", "seduta"),
        notes="Pillow Humping LoRA scaricato da CivitAI (ID: 619176). Peso consigliato: 0.55-0.65",
        triggers=("pillow humping", "grinding pillow")
    ),
    LoRAEntry(
        name="povcun-000015",
        weight=0.45, category="nsfw",
        keywords=("2girls", "two women", "lesbian", "lesbian sex", "intimate moment"),
        triggers=("2girls",)
    ),
]

# Aggiungi i clothing LoRAs anche alla lista LORAS per lookup
LORAS_BY_NAME: Dict[str, LoRAEntry] = {e.name: e for e in LORAS}
LORAS_BY_NAME.update(CLOTHING_LORAS)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _text_corpus(tags: List[str], visual: str) -> str:
    t = " ".join(tags + ([visual] if visual else [])).lower()
    return t.replace("-", " ").replace("_", " ").replace("/", " ")


def _score_entry(text: str, entry: LoRAEntry) -> int:
    """Conta quante keyword (anche parziali) compaiono nel testo."""
    return sum(1 for k in entry.keywords if k and k.lower() in text)


def _strip_version(name: str) -> str:
    s = re.sub(r"[\s_\-]v\d[\w\.\-]*$", "", name, flags=re.IGNORECASE)
    s = re.sub(r"[\s_\-]\d+e$", "", s, flags=re.IGNORECASE)
    return s


def _display_trigger(entry: LoRAEntry) -> str:
    """Sceglie il trigger testuale da aggiungere al prompt."""
    if entry.triggers:
        return entry.triggers[0]
    base = entry.name.replace("_", " ").replace("-", " ")
    base = _strip_version(base).strip()
    return base


def _find_entry_by_name(name: str) -> Optional[LoRAEntry]:
    return LORAS_BY_NAME.get(name)


def pick_loras(tags: List[str], visual: str = "", sdxl: bool = True, max_total: int = MAX_TOTAL_LORAS, use_fallbacks: bool = False) -> List[LoRAEntry]:
    """
    Seleziona i LoRA in base ai tag (versione base, senza outfit state).
    
    Args:
        tags: Lista di tag
        visual: Testo visuale opzionale
        sdxl: Se True, considera solo LoRA compatibili SDXL
        max_total: Numero massimo di LoRA da selezionare
        use_fallbacks: Se False (default), non aggiunge mai fallback LoRAs
    
    Returns:
        Lista di LoRAEntry selezionati
    """
    text = _text_corpus(tags, visual)

    candidates = sorted(
        (e for e in LORAS if (e.sdxl_ok or not sdxl)),
        key=lambda e: (_score_entry(text, e), -0.0001 * e.weight),
        reverse=True
    )

    picked: List[LoRAEntry] = []
    used_per_cat: Dict[str, int] = {k: 0 for k in CATEGORY_LIMITS}

    for e in candidates:
        if len(picked) >= max_total:
            break
        if _score_entry(text, e) == 0:
            continue
        cap = CATEGORY_LIMITS.get(e.category, 1)
        if used_per_cat.get(e.category, 0) >= cap:
            continue
        picked.append(e)
        used_per_cat[e.category] = used_per_cat.get(e.category, 0) + 1

    # V4.6: Fallbacks disabilitati di default - non aggiungere mai LoRAs senza match
    if use_fallbacks and not picked:
        for name, w in FALLBACKS:
            if len(picked) >= max_total:
                break
            e = _find_entry_by_name(name)
            if not e:
                continue
            cap = CATEGORY_LIMITS.get(e.category, 1)
            if used_per_cat.get(e.category, 0) >= cap:
                continue
            picked.append(LoRAEntry(
                name=e.name, weight=w, category=e.category,
                keywords=e.keywords, sdxl_ok=e.sdxl_ok, notes=e.notes, triggers=e.triggers
            ))
            used_per_cat[e.category] = used_per_cat.get(e.category, 0) + 1

    return picked[:max_total]


def select_loras_for_outfit(outfit_state: Dict, tags: List[str] = None) -> List[Tuple[str, float]]:
    """
    Funzione utility per selezionare LoRA specifici per outfit.
    
    Args:
        outfit_state: Dict con 'description', 'components', 'style'
        tags: Tag opzionali aggiuntivi
    
    Returns:
        Lista di tuple (nome_lora, peso)
    """
    mapper = LoraMapping()
    entries = mapper._select_clothing_loras(tags or [], outfit_state)
    return [(e.name, float(e.weight)) for e in entries]


# ============================================================================
# ISTRUZIONI PER L'UTENTE
# ============================================================================
"""
COME CONFIGURARE I LORAs:

1. Cerca su CivitAI le categorie indicate nelle note di ogni CLOTHING_LORA
2. Scarica i file .safetensors
3. Mettili nella cartella models/loras/ di ComfyUI
4. Aggiorna il campo 'name' in CLOTHING_LORAS con il nome file esatto
5. Testa i pesi (se troppo forti, riduci il 'weight' nel codice)

ESEMPIO:
Se su CivitAI trovi un LoRA chiamato "Detailed_Lingerie_XL_v2.safetensors":
- Scaricalo in models/loras/
- Cambia nel codice: name="Detailed_Lingerie_XL_v2"
- Testa con peso 0.6, se troppo forte riduci a 0.5
"""


# ============================================================================
# DEMO
# ============================================================================

if __name__ == "__main__":
    logger.debug("="*60)
    logger.debug("LoRA Mapping System - Demo")
    logger.debug("="*60)
    logger.debug("\nNOTA: I nomi LoRA sono ESEMPI!")
    logger.debug("Devi cercare i LoRA reali su CivitAI e aggiornare i nomi.\n")
    logger.debug("Categorie da cercare:")
    logger.debug("- bikini, swimsuit (beach)")
    logger.debug("- lingerie, lace (intimo sexy)")
    logger.debug("- wet clothes, see-through (bagnato/trasparente)")
    logger.debug("- school uniform, seifuku (uniforme scolastica)")
    logger.debug("- pantyhose, stockings (calze/collant)")
    logger.debug("- maid, french maid (divisa cameriera)")
    logger.debug("- yoga pants, leggings (sportivo)")
    logger.debug("")
    
    # Test base
    demo_tags = ["portrait", "beauty", "hands visible", "sharp", "photorealistic"]
    
    mapper = LoraMapping(config={})
    chosen_entries = pick_loras(demo_tags, "", sdxl=True)

    logger.debug("Test base:")
    logger.debug(f"Tags: {demo_tags}")
    logger.debug(f"LoRA selezionati: {[e.name for e in chosen_entries]}")
    logger.debug(f"Suffix: {mapper.lora_prompt_suffix(chosen_entries)}")
    
    # Test outfit
    logger.debug("\n" + "="*60)
    logger.debug("Test Outfit Lingerie:")
    logger.debug("="*60)
    outfit = {
        "description": "white lace lingerie, see-through",
        "components": {"bra": "none", "panties": "white lace panties"},
        "style": "lingerie"
    }
    clothing_loras = mapper._select_clothing_loras([], outfit)
    logger.debug(f"Outfit: {outfit['description']}")
    if clothing_loras:
        logger.debug(f"LoRA selezionati: {[(e.name, e.weight) for e in clothing_loras]}")
        logger.debug("\nNOTA: Questi sono nomi di esempio!")
        logger.debug("Cerca i LoRA reali su CivitAI e aggiorna i nomi nel codice.")
    else:
        logger.debug("Nessun LoRA clothing configurato (nomi esempio non trovati)")
