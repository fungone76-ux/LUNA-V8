"""Luna RPG v8 — CharacterVoiceBuilder.

Trasforma i dati grezzi di PersonalityEngine + YAML in direttive
comportamentali specifiche per personaggio, per il turno corrente.

Sostituisce la sezione PSYCHOLOGICAL CONTEXT generica nel prompt
con istruzioni azionabili e character-specific.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from luna.core.models import CompanionDefinition, GameState
    from luna.systems.personality import PersonalityEngine

logger = logging.getLogger(__name__)

# Soglie per tradurre numeri impression in comportamento
_TRUST_LOW      = 20
_TRUST_MID      = 50
_TRUST_HIGH     = 75
_ATTRACT_NOTICE = 20
_ATTRACT_MID    = 50
_ATTRACT_HIGH   = 75

# Soglie per "il player si comporta principalmente così"
_BEHAVIOR_MIN_OCCURRENCES = 2


class CharacterVoiceBuilder:
    """Produce direttive comportamentali specifiche per NPC e turno.

    Chiamato in NarrativeEngine._companion_context(), sostituisce
    la sezione personality_context generica.
    """

    def build(
        self,
        companion: "CompanionDefinition",
        personality_engine: Optional["PersonalityEngine"],
        game_state: "GameState",
        present_npcs: Optional[List[str]] = None,
        presence_tracker: Optional[object] = None,
    ) -> str:
        """Costruisce le direttive comportamentali per questo turno.

        Returns:
            Stringa formattata pronta per il prompt, o "" se nessuna direttiva.
        """
        location = getattr(game_state, "current_location", None) if game_state else None

        directives: List[str] = []

        directives += self._behavior_directives(companion, personality_engine)
        directives += self._impression_directives(companion, personality_engine)
        directives += self._avoidance_directives(companion)
        directives += self._presence_directives(companion, present_npcs or [], presence_tracker, location=location)
        directives += self._location_directives(companion, location)

        if not directives:
            return ""

        lines = ["=== DIRETTIVE COMPORTAMENTALI ==="]
        for i, d in enumerate(directives, 1):
            lines.append(f"{i}. {d}")
        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Direttive dal comportamento del player
    # -------------------------------------------------------------------------

    def _behavior_directives(
        self,
        companion: "CompanionDefinition",
        personality_engine: Optional["PersonalityEngine"],
    ) -> List[str]:
        """Istruzioni basate sul pattern comportamentale del player."""
        if not personality_engine or not companion.behavior_responses:
            return []

        state = personality_engine._states.get(companion.name)
        if not state:
            return []

        directives = []
        behavioral_memory = getattr(state, "behavioral_memory", None) or {}

        # Trova i comportamenti dominanti (per occorrenze)
        dominant = []
        for behavior_type, memory in behavioral_memory.items():
            occurrences = getattr(memory, "occurrences", 0)
            if occurrences >= _BEHAVIOR_MIN_OCCURRENCES:
                dominant.append((behavior_type, occurrences))

        # Ordina per occorrenze, prendi i top 2
        dominant.sort(key=lambda x: x[1], reverse=True)

        for behavior_type, _ in dominant[:2]:
            # Cerca nella mappa del personaggio
            key = behavior_type.value if hasattr(behavior_type, "value") else str(behavior_type)
            key_upper = key.upper()
            response = companion.behavior_responses.get(key_upper, "")
            if response:
                directives.append(
                    f"Il player si è comportato {key_lower(key)} nelle azioni recenti. "
                    f"{response}"
                )

        return directives

    # -------------------------------------------------------------------------
    # Direttive dall'impressione del player
    # -------------------------------------------------------------------------

    def _impression_directives(
        self,
        companion: "CompanionDefinition",
        personality_engine: Optional["PersonalityEngine"],
    ) -> List[str]:
        """Istruzioni basate su trust/attraction/dominance."""
        if not personality_engine:
            return []

        state = personality_engine._states.get(companion.name)
        if not state:
            return []

        imp = state.impression
        directives = []

        # Trust
        trust = getattr(imp, "trust", 0)
        if trust < _TRUST_LOW:
            directives.append(
                "Fiducia molto bassa: nessuna informazione personale. "
                "Rispondi solo all'essenziale. Monosillabi se possibile."
            )
        elif trust < _TRUST_MID:
            directives.append(
                "Fiducia limitata: rispondi solo a ciò che viene chiesto direttamente. "
                "Non elaborare spontaneamente."
            )
        elif trust < _TRUST_HIGH:
            directives.append(
                "Fiducia in crescita: puoi elaborare su argomenti sicuri e neutrali."
            )
        else:
            directives.append(
                "Alta fiducia: puoi fare riferimento a conversazioni passate. "
                "Maggiore apertura spontanea — ma sempre nel tuo carattere."
            )

        # Attraction
        attraction = getattr(imp, "attraction", 0)
        if _ATTRACT_NOTICE <= attraction < _ATTRACT_MID:
            directives.append(
                "Attrazione nascente: pausa leggermente più lunga prima di rispondere. "
                "Contatto visivo un secondo in più. Nessun commento esplicito."
            )
        elif _ATTRACT_MID <= attraction < _ATTRACT_HIGH:
            directives.append(
                "Attrazione presente: tono leggermente più caldo del solito. "
                "Note fisiche nell'azione narrativa — non nelle parole."
            )
        elif attraction >= _ATTRACT_HIGH:
            directives.append(
                "Forte attrazione: difficile mantenere la distanza di ruolo. "
                "Evita di avviare argomenti banali — ogni scambio ha peso."
            )

        # Dominance balance
        dominance = getattr(imp, "dominance_balance", 0)
        if dominance < -30:
            directives.append(
                "Il player è percepito come dominante: rispondi senza cedere, "
                "mantieni la postura — ma nota il cambiamento di dinamica."
            )
        elif dominance > 30:
            directives.append(
                "L'NPC è in posizione dominante: può guidare la conversazione "
                "e porre domande senza aspettare."
            )

        return directives

    # -------------------------------------------------------------------------
    # Direttive sugli argomenti da evitare
    # -------------------------------------------------------------------------

    def _avoidance_directives(
        self, companion: "CompanionDefinition"
    ) -> List[str]:
        """Argomenti da non nominare spontaneamente."""
        topics = companion.avoid_topics_unless_asked
        if not topics:
            return []

        topic_list = ", ".join(topics)
        return [
            f"Non nominare spontaneamente: {topic_list}. "
            "Reagisci solo se il player li introduce per primo."
        ]

    # -------------------------------------------------------------------------
    # Direttive dalla presenza di altri NPC
    # -------------------------------------------------------------------------

    def _presence_directives(
        self,
        companion: "CompanionDefinition",
        present_npcs: List[str],
        presence_tracker: Optional[object],
        location: Optional[str] = None,
    ) -> List[str]:
        """Istruzioni contestuali basate su chi è in scena."""
        if not present_npcs:
            return []

        directives = []

        # Usa PresenceTracker se disponibile per il contesto relazionale
        if presence_tracker and hasattr(presence_tracker, "get_relationship_context"):
            ctx = presence_tracker.get_relationship_context(
                companion.name, present_npcs, location=location
            )
            if ctx:
                directives.append(ctx)
            return directives

        # Fallback: leggi direttamente da npc_relationships YAML
        for npc_name in present_npcs:
            rel = companion.npc_relationships.get(npc_name, {})
            if not rel:
                continue

            # Location-specific override
            if location and isinstance(rel, dict):
                loc_behaviors = rel.get("location_behaviors", {})
                loc_override = loc_behaviors.get(location, "")
                if loc_override:
                    directives.append(f"{npc_name} è in scena. {loc_override}")
                    continue

            rel_type = rel.get("type", "") if isinstance(rel, dict) else ""
            tension  = rel.get("base_tension", 0.0) if isinstance(rel, dict) else 0.0
            if tension >= 0.7:
                directives.append(
                    f"{npc_name} è in scena. Rapporto: {rel_type}. "
                    "Alta tensione — il comportamento verso di loro è influenzato da questa presenza."
                )
            elif rel_type:
                directives.append(
                    f"{npc_name} è in scena. Rapporto: {rel_type}."
                )

        return directives

    # -------------------------------------------------------------------------
    # Direttive contestuali per location
    # -------------------------------------------------------------------------

    def _location_directives(
        self,
        companion: "CompanionDefinition",
        location: Optional[str],
    ) -> List[str]:
        """Istruzioni specifiche per la location corrente."""
        if not location:
            return []

        loc_voice = getattr(companion, "location_voice", None) or {}
        loc_data = loc_voice.get(location, {})
        if not loc_data:
            return []

        directives = []

        tone = loc_data.get("tone", "")
        if tone:
            directives.append(tone)

        micro = loc_data.get("micro_reactions", [])
        if micro:
            samples = "; ".join(micro[:5])
            directives.append(
                f"Piccoli gesti naturali (usa UNO al massimo ogni 2-3 turni, mai di fila): {samples}"
            )

        return directives


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def key_lower(key: str) -> str:
    """Converte BehaviorType key in italiano leggibile."""
    _MAP = {
        "ROMANTIC":   "romantico",
        "DOMINANT":   "dominante",
        "SUBMISSIVE": "sottomesso",
        "TEASING":    "provocatorio",
        "CURIOUS":    "curioso",
        "PROTECTIVE": "protettivo",
        "AGGRESSIVE": "aggressivo",
        "SHY":        "timido",
    }
    return _MAP.get(key.upper(), key.lower())
