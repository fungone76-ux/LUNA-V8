"""Luna RPG v6 - Narrative Engine Agent.

Generates the narrative text response for a game turn.
This is the core LLM call — produces a SMALL JSON with just
narrative + state updates, separate from visual generation.

v6 key improvement: smaller JSON = fewer parse failures.
The visual_en field is a hint for the VisualDirector,
not a full SD prompt (that's built by the VisualDirector agent).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from luna.core.models import (
    CompanionDefinition, GameState, NarrativeOutput,
    OutfitState, WorldDefinition,
)

logger = logging.getLogger(__name__)


# JSON schema the LLM must produce — intentionally small
_NARRATIVE_SCHEMA = """{
  "text": "Narrative in Italian. MAX 3 sentences total (actions + dialogue combined). Be concise. Character MUST speak at least one line.",
  
  "visual_en": "Natural language scene description (20-35 words). Focus: ACTION, POSE, CHARACTERS. NAME specific characters if visible. Outfit handled by system - do NOT describe clothes unless changing. NO glasses/hats/sunglasses. NO facial expressions (sad, happy, smiling, angry). NO movement verbs (walking, running, turning). NO emotional states (nervous, excited). Static poses only: standing, seated, leaning, arms crossed, hand on hip. DESCRIBE EXPLICIT SEXUAL ACTS with graphic anatomical details when warranted.",
  
  "tags_en": ["shot_type", "angle", "pose", "body_focus", "gaze", "quality", "explicit_terms"],
  "aspect_ratio": "portrait|landscape|square",
  "body_focus": "optional: face|legs|breasts|hands|feet|ass|pussy|cock|tits|nipples",
  
  "updates": {
    "affinity_change": {"CompanionName": 2},
    "outfit_update": {"modify_components": {"shoes": "none"}},
    "set_flags": {},
    "new_fact": null,
    "new_promise": null,
    "resolve_promise": null,
    "promise_weight": null,
    "invite_accepted": false,
    "photo_requested": false,
    "npc_emotion": null
  }
}"""

_SOLO_COMPANION = "_solo_"


class NarrativeEngine:
    """Builds the system prompt and calls the LLM to get narrative output.

    Responsibilities:
    - Build context-rich system prompt
    - Call LLMManager with retry
    - Convert LLMResponse → NarrativeOutput
    """

    def __init__(
        self,
        world: WorldDefinition,
        voice_builder: Optional[Any] = None,
        personality_engine: Optional[Any] = None,
    ) -> None:
        self.world = world
        self._voice_builder = voice_builder
        self._personality_engine = personality_engine

    async def generate(
        self,
        user_input: str,
        game_state: GameState,
        llm_manager: Any,
        context: Dict[str, Any],
    ) -> NarrativeOutput:
        """Generate narrative for this turn.

        Args:
            user_input:   Raw player input
            game_state:   Current game state
            llm_manager:  LLMManager instance
            context:      Extra context dict with keys:
                          memory_context, conversation_history,
                          quest_context, story_context,
                          activity_context, initiative_context,
                          multi_npc_context, forced_poses,
                          personality_context, event_context,
                          switched_from, is_temporary,
                          in_remote_comm, remote_target

        Returns:
            NarrativeOutput with text + state updates
        """
        companion = self.world.companions.get(game_state.active_companion)
        system_prompt = self._build_prompt(game_state, companion, context)

        llm_response, provider = await llm_manager.generate(
            system_prompt=system_prompt,
            user_input=user_input,
            history=self._build_history(context),
            json_mode=True,
            companion_name=companion.name if companion else "NPC",
        )

        return self._to_narrative_output(llm_response, provider)

    # -------------------------------------------------------------------------
    # Prompt building
    # -------------------------------------------------------------------------

    def _build_prompt(
        self,
        game_state: GameState,
        companion: Optional[CompanionDefinition],
        context: Dict[str, Any],
    ) -> str:
        sections: List[str] = []

        sections += self._header()
        sections += self._authority_scene_context(context)  # PRIORITÀ MASSIMA — sovrascrive scena default
        sections += self._world_context()
        sections += self._companion_context(companion, game_state, context)
        sections += self._situation(game_state, companion)
        sections += self._outfit_context(game_state, companion)
        sections += self._time_atmosphere(game_state)
        sections += self._schedule_context(context)
        sections += self._world_directive(context)       # v7: WorldSimulator context
        sections += self._scene_direction(context)       # v7: DirectorAgent beats
        sections += self._initiative_context(context)
        sections += self._personality_context(context, game_state)
        sections += self._event_context(context)
        sections += self._story_beat(context)
        sections += self._gm_agenda(context)
        sections += self._activity_context(context)
        sections += self._npc_presence_context(context)  # Metodo 7: stato accumulato NPC
        sections += self._npc_secret_hint(context)
        sections += self._multi_npc_context(context)
        sections += self._quest_context(context)
        sections += self._memory_context(context)
        sections += self._forced_poses(context)
        sections += self._body_focus_hint(context.get("user_input", ""))
        sections += self._visual_director(game_state)
        sections += self._output_format()

        return "\n".join(sections)

    def _header(self) -> List[str]:
        return [
            "=== LUNA RPG v7 — GAME MASTER ===",
            "",
            f"Genre: {self.world.genre}",
            f"World: {self.world.name}",
            "",
            "You are the Game Master. NARRATE in ITALIAN.",
            "",
            "=== CRITICAL RULES ===",
            "1. NEVER repeat the player's input.",
            "2. NEVER describe player actions — only NPC reactions.",
            "3. NPC dialogue in quotes: \"Cosa vuoi?\"",
            "4. NPC actions in asterisks: *Luna si avvicina.*",
            "5. NEVER use first person (I/me/my).",
            "6. Player addressed as YOU.",
            "7. LENGTH: MAX 3 sentences total. One action beat + one spoken line is ideal. DO NOT write paragraphs.",
            "8. MIRROR input length: short player input = short response. Long input = still max 3 sentences.",
            "",
            "=== NARRATIVE COHERENCE RULES ===",
            "9. REACT TO IMMEDIATE CONTEXT: If player's previous action was physical/provocative (lifting skirt, intimate touching, etc),",
            "   NPC MUST react to THAT action, not jump to unrelated topics like backstory/confessions.",
            "10. MAINTAIN SCENE CONTINUITY: Scene should flow naturally from previous turn's emotional state.",
            "11. ESCALATION RULE: Intimate/provocative actions require immediate emotional reaction (embarrassment, arousal, anger, etc),",
            "    NOT sudden topic changes to backstory/career/personal history.",
            "12. IF outfit is disarrayed (skirt lifted, underwear exposed), NPC notices and reacts to exposure in next turn.",
            "13. INDIRECT ACTIONS: If player's action is directed at a secondary NPC (whisper, gesture, note), PRIMARY NPC reacts ONLY if",
            "    directly and visibly disrupted. Otherwise: a brief ambient reaction (glance, pause) at most. NO speeches, NO lectures.",
            "",
            "=== ADULT CONTENT RULES (18+ EXTREME) ===",
            "14. HARDCORE EROTIC: This is a hardcore erotic visual novel. Describe EXPLICIT sexual acts in GRAPHIC DETAIL.",
            "15. FULL EXPLICIT: Describe full nudity, genitalia, penetration, fluids, intimate acts with PORNOGRAPHIC precision.",
            "16. NEVER FADE TO BLACK: Never cut away. Describe everything raw, visceral, and explicit.",
            "17. NO EUPHEMISMS: Use direct, explicit language. When characters fuck, describe the fucking in detail.",
            "18. DIALOGUE MANDATORY: Character MUST SPEAK in EVERY turn. MINIMUM 2-3 lines of quoted dialogue per response.",
            "19. NAME THE CHARACTER: You MUST name the active character explicitly in your narration.",
            "20. OUTFIT PERSISTENCE: Characters DO NOT magically redress. If outfit is 'Nude' or 'Lingerie', it STAYS that way.",
            "21. NO GLASSES: Characters NEVER wear glasses/sunglasses unless explicitly requested.",
            "",
        ]

    def _world_context(self) -> List[str]:
        return [
            "=== WORLD ===",
            self.world.lore or self.world.description or self.world.name,
            "",
        ]

    def _npc_speaker_context(
        self,
        npc_id: str,
        npc_def: Any,
        companion: Optional[CompanionDefinition],
    ) -> List[str]:
        """Build context when an NPC template is the active speaker (not the companion)."""
        get = lambda key, default="": (
            npc_def.get(key, default) if isinstance(npc_def, dict)
            else getattr(npc_def, key, default)
        )
        name = get("name", npc_id)
        role = get("role", "")
        physical = get("physical_description", "")
        personality = get("personality", "")
        companion_name = companion.name if companion else "the companion"

        lines = [
            "=== ACTIVE SPEAKER: NPC ===",
            f"⚠️ {name} IS THE ONLY CHARACTER SPEAKING THIS TURN.",
            f"⚠️ DO NOT write {companion_name}'s dialogue. {companion_name} is NOT at this location.",
            f"Speak ONLY as {name}. Every quoted line must come from {name}.",
            "",
            f"Name: {name}",
            f"Role: {role}",
        ]
        if physical:
            lines.append(f"Physical: {physical}")
        if personality:
            lines.append(f"Personality: {personality[:400]}")
        lines.append("")
        return lines

    def _companion_context(
        self,
        companion: Optional[CompanionDefinition],
        game_state: GameState,
        context: Dict[str, Any],
    ) -> List[str]:
        # If an NPC template is the active speaker, replace companion context entirely
        active_npc_id = context.get("active_npc_speaker")
        if active_npc_id:
            npc_def = self.world.npc_templates.get(active_npc_id)
            if npc_def:
                return self._npc_speaker_context(active_npc_id, npc_def, companion)

        if not companion or game_state.active_companion == _SOLO_COMPANION:
            return [
                "=== SOLO MODE ===",
                "Player is ALONE. No NPC speaks or appears.",
                "Describe only the location atmosphere.",
                "",
            ]

        affinity = game_state.affinity.get(companion.name, 0)
        lines = [
            "=== ACTIVE COMPANION ===",
            f"Name: {companion.name}",
            f"Role: {companion.role}",
            f"Age: {companion.age}",
            f"Personality: {companion.base_personality}",
            f"Affinity: {affinity}/100",
        ]

        if companion.background:
            lines.append(f"Background: {companion.background}")
        if companion.relationship_to_player:
            lines.append(f"Relationship: {companion.relationship_to_player}")

        # Affinity tier behavior
        tier = self._get_affinity_tier(companion, affinity)
        if tier:
            lines += ["", "=== BEHAVIOR TIER ==="] + tier

        # Active emotional state (from NPCState runtime tracking)
        npc_state = game_state.npc_states.get(companion.name)
        emotional_state_key = (npc_state.emotional_state if npc_state else None) or "default"
        emotional_state_data = companion.emotional_states.get(emotional_state_key, {})
        if emotional_state_data:
            es_desc = (
                emotional_state_data.get("description", "")
                if isinstance(emotional_state_data, dict)
                else getattr(emotional_state_data, "description", "")
            )
            es_tone = (
                emotional_state_data.get("dialogue_tone", "")
                if isinstance(emotional_state_data, dict)
                else getattr(emotional_state_data, "dialogue_tone", "")
            )
            if es_desc or es_tone:
                lines += ["", "=== EMOTIONAL STATE ==="]
                if es_desc:
                    lines.append(f"Current state: {es_desc}")
                if es_tone:
                    lines.append(f"Dialogue tone (MANDATORY): {es_tone}")

        # Companion switch notice
        switched_from = context.get("switched_from")
        if switched_from:
            lines += [
                "",
                f"NOTE: Just switched from {switched_from} to {companion.name}.",
                f"{switched_from} is no longer present.",
                f"Focus ONLY on {companion.name}.",
            ]

        # Remote communication
        if context.get("in_remote_comm"):
            target = context.get("remote_target", companion.name)
            lines += [
                "",
                "=== REMOTE COMMUNICATION ===",
                f"Player is messaging/calling {target} remotely.",
                "No physical contact. Text/call only.",
            ]

        lines.append("")
        return lines

    def _situation(
        self,
        game_state: GameState,
        companion: Optional[CompanionDefinition],
    ) -> List[str]:
        time_str = (
            game_state.time_of_day.value
            if hasattr(game_state.time_of_day, "value")
            else str(game_state.time_of_day)
        )
        loc_def  = self.world.locations.get(game_state.current_location)
        loc_name = loc_def.name if loc_def else game_state.current_location

        return [
            "=== CURRENT SITUATION ===",
            f"Location: {loc_name} ({game_state.current_location})",
            f"Time: {time_str}",
            f"Turn: {game_state.turn_count}",
            "",
        ]

    def _outfit_context(
        self,
        game_state: GameState,
        companion: Optional[CompanionDefinition],
    ) -> List[str]:
        if not companion or game_state.active_companion == _SOLO_COMPANION:
            return []
        # Skip companion outfit when an NPC template is the active speaker
        if game_state.flags.get("_active_npc_speaker"):
            return []
        outfit = game_state.get_outfit(companion.name)
        outfit_desc = outfit.to_prompt_string()
        
        # DEBUG logging
        logger.info(f"[Narrative._outfit_context] {companion.name}: {outfit_desc}")
        if outfit.modifications:
            for mod_key, mod in outfit.modifications.items():
                logger.info(f"[Narrative._outfit_context] Mod: {mod_key}={mod.state} ({mod.description})")
        
        lines = [
            "=== OUTFIT (PERSIST ACROSS TURNS) ===",
            f"Current: {outfit_desc}",
            "RULES:",
            "1. Describe actual clothing in visual_en — never the style key.",
            "2. DO NOT change outfit unless player explicitly requests it.",
            "3. If altered, update visual_en AND updates.outfit_update.",
            "4. Shoes removed + pantyhose = feet covered, NOT barefoot.",
        ]
        
        # Check for disarrayed state (modifications that expose)
        if outfit.modifications:
            exposed_parts = []
            for mod_key, mod in outfit.modifications.items():
                if mod.state in ["lifted", "pulled_down", "exposed", "visible", "removed", "partial_unbuttoned"]:
                    exposed_parts.append(mod.description or mod_key)
            if exposed_parts:
                lines.append(f"!!! CRITICAL: Clothing is disarrayed - {', '.join(exposed_parts)}.")
                lines.append("!!! NPC MUST NOTICE and REACT to this exposure in her response.")
                lines.append("!!! DO NOT ignore or change topic — react to the exposed body parts.")
        
        lines.append("")
        return lines

    def _time_atmosphere(self, game_state: GameState) -> List[str]:
        ts = self.world.time_slots.get(game_state.time_of_day)
        if not ts:
            return []
        lines = ["=== ATMOSPHERE ==="]
        if isinstance(ts, dict):
            if ts.get("ambient_description"):
                lines.append(f"Atmosphere: {ts['ambient_description']}")
            if ts.get("lighting"):
                lines.append(f"Lighting: {ts['lighting']}")
        else:
            if getattr(ts, "ambient_description", ""):
                lines.append(f"Atmosphere: {ts.ambient_description}")
            if getattr(ts, "lighting", ""):
                lines.append(f"Lighting: {ts.lighting}")
        lines.append("")
        return lines

    def _schedule_context(self, context: Dict[str, Any]) -> List[str]:
        """Inject atmosphere and schedule hints from ScheduleAgent."""
        schedule = context.get("schedule_context", "")
        if not schedule:
            return []
        return [schedule, ""]

    def _initiative_context(self, context: Dict[str, Any]) -> List[str]:
        """Inject NPC initiative — woven into narrative, no system headers."""
        initiative = context.get("initiative_context", "")
        if not initiative:
            return []
        return [initiative, ""]

    def _npc_secret_hint(self, context: Dict[str, Any]) -> List[str]:
        """Inject NPC pending secret/goal into narrative (pull channel)."""
        hint = context.get("npc_secret_hint", "")
        if not hint:
            return []
        return [
            "=== NPC INIZIATIVA ===",
            hint,
            "",
        ]

    def _cross_npc_hint(self, context: Dict[str, Any]) -> List[str]:
        """Inject cross-location hint from a non-active NPC (Fix 3)."""
        hint = context.get("cross_npc_hint", "")
        if not hint:
            return []
        return [
            "=== MESSAGGIO DA ALTROVE ===",
            hint,
            "Includi questo elemento diegetico nella tua risposta in modo naturale.",
            "",
        ]

    def _npc_presence_context(self, context: Dict[str, Any]) -> List[str]:
        """Metodo 7: inietta stato accumulato dell'NPC nel prompt.

        Descrive quanto tempo è rimasto solo, il suo umore attuale,
        cosa stava facendo. L'LLM usa questo per calibrare organicamente
        il comportamento dell'NPC senza trigger meccanici.
        """
        presence = context.get("npc_presence_context", "")
        if not presence:
            return []
        return [
            "=== STATO ATTUALE DELL'NPC ===",
            presence,
            "Usa questo contesto per calibrare il tono e il comportamento dell'NPC.",
            "Non citare mai esplicitamente questi dati — lascia che emergano naturalmente.",
            "",
        ]

    def _personality_context(
        self, context: Dict[str, Any], game_state: GameState
    ) -> List[str]:
        # v8: CharacterVoiceBuilder integration - use behavioral directives if available
        if self._voice_builder and self._personality_engine:
            companion = self.world.companions.get(game_state.active_companion)
            if companion:
                present_npcs = context.get("present_npcs", [])
                voice_ctx = self._voice_builder.build(
                    companion=companion,
                    personality_engine=self._personality_engine,
                    game_state=game_state,
                    present_npcs=present_npcs,
                    presence_tracker=None,  # Could be passed if needed
                )
                if voice_ctx:
                    return [voice_ctx, ""]

        # Fallback to legacy personality context
        ctx = context.get("personality_context", "")
        if not ctx:
            return []
        return [
            "=== PSYCHOLOGICAL CONTEXT ===",
            ctx,
            "",
            "Use impressions to guide behavior:",
            "TRUST high → vulnerable, shares secrets.",
            "ATTRACTION high → flirtatious, seeks proximity.",
            "FEAR high → nervous, seeks approval.",
            "",
        ]

    def _event_context(self, context: Dict[str, Any]) -> List[str]:
        ctx = context.get("event_context", "")
        if not ctx:
            return []
        return [ctx, ""]

    def _story_beat(self, context: Dict[str, Any]) -> List[str]:
        ctx = context.get("story_context", "")
        if not ctx:
            return []
        return [
            "=== MANDATORY NARRATIVE BEAT ===",
            ctx,
            "You MUST include this event in your response, BUT:",
            "- If player's previous action was physical/intimate (lifting skirt, touching, etc),",
            "  you MUST first react to that immediate action, THEN incorporate the story beat.",
            "- NEVER ignore physical intimacy to jump straight to backstory/confession.",
            "- Integrate the story beat NATURALLY into the current intimate moment.",
            "",
        ]

    def _gm_agenda(self, context: Dict[str, Any]) -> List[str]:
        """v7: GM Agenda section — narrative intent for this turn."""
        ctx = context.get("gm_agenda_context", "")
        if not ctx:
            return []
        return [ctx, ""]

    def _activity_context(self, context: Dict[str, Any]) -> List[str]:
        lines = []
        activity = context.get("activity_context", "")
        initiative = context.get("initiative_context", "")
        if activity:
            lines += ["=== CURRENT ACTIVITY ===", f"NPC is currently: {activity}", ""]
        if initiative:
            lines += ["=== NPC INITIATIVE ===", f"NPC wants to: {initiative}", ""]
        return lines

    def _world_directive(self, context: Dict[str, Any]) -> List[str]:
        """v7: Inject WorldSimulator context (NPC mind state, ambient, pressure)."""
        ctx = context.get("world_directive_context", "")
        if not ctx:
            return []
        driver = context.get("turn_driver", "player")
        lines = [ctx]
        if driver == "npc":
            lines.extend([
                "⚠️ THIS TURN: The NPC drives the scene. DO NOT wait for the player.",
                "The NPC must ACT FIRST, speak first, and TAKE INITIATIVE.",
                "",
            ])
        elif driver == "ambient":
            lines.extend([
                "💡 THIS TURN: Enrich the scene with atmosphere and ambient details.",
                "Something should HAPPEN — a sound, a person passing by, a change.",
                "",
            ])
        return lines

    def _authority_scene_context(self, context: Dict[str, Any]) -> List[str]:
        """Inietta il contesto della scena con authority NPC (preside, ispettore...).

        Garantisce che quando si switcha da NPC → companion, il companion
        ricordi di essere ancora nella scena e non torni allo stato default.
        """
        scene = context.get("active_authority_scene", "")
        if not scene:
            return []
        # Usa la location specifica dell'NPC se disponibile nel contesto
        # (viene iniettata da phase_handlers insieme alla scena)
        npc_location = context.get("active_authority_npc_location", "")
        location_warning = (
            f"⚠️ La scena si svolge in: {npc_location}."
            if npc_location
            else "⚠️ La scena NON è in classe — segui il contesto qui sotto."
        )
        return [
            "=== CONTESTO SCENA ATTIVA — PRIORITÀ ASSOLUTA ===",
            "⚠️ IGNORA qualsiasi contesto di default (aula, studenti, lavagna, Stella, classe).",
            location_warning,
            scene,
            "Il companion DEVE rispondere tenendo conto di questa scena. NON ignorarla.",
            "",
        ]

    def _scene_direction(self, context: Dict[str, Any]) -> List[str]:
        """v7: Inject DirectorAgent scene beats."""
        ctx = context.get("scene_direction_context", "")
        if not ctx:
            return []
        return [ctx, ""]

    def _multi_npc_context(self, context: Dict[str, Any]) -> List[str]:
        ctx = context.get("multi_npc_context", "")
        if not ctx:
            return []
        return [ctx, ""]

    def _quest_context(self, context: Dict[str, Any]) -> List[str]:
        ctx = context.get("quest_context", "")
        if not ctx:
            return []
        return ["=== ACTIVE QUESTS ===", ctx, ""]

    def _memory_context(self, context: Dict[str, Any]) -> List[str]:
        memory = context.get("memory_context", "")
        history = context.get("conversation_history", "")
        lines = []
        if memory:
            lines += [memory, ""]
        if history:
            lines += [history, ""]
        return lines

    def _forced_poses(self, context: Dict[str, Any]) -> List[str]:
        poses = context.get("forced_poses", "")
        if not poses:
            return []
        return [
            "=== FORCED POSES (MANDATORY) ===",
            f"Player requested: {poses}",
            "MUST include in visual_en and tags_en.",
            "",
        ]

    def _body_focus_hint(self, user_input: str) -> List[str]:
        if not user_input:
            return []
        preview = user_input[:100]
        return [
            "=== BODY FOCUS ===",
            f"Input: '{preview}'",
            "If player mentions a body part, set body_focus and describe explicitly in visual_en.",
            "",
        ]

    def _visual_director(self, game_state: GameState) -> List[str]:
        # Rotate composition suggestion to force variety
        compositions = [
            "cowboy_shot (thighs up)",
            "close_up (face and shoulders)",
            "full_body (head to feet)",
            "from_below (low angle, imposing)",
            "medium_shot (waist up)",
            "dutch_angle (tilted frame)",
            "profile (side view)",
            "over_shoulder (from behind protagonist)",
        ]
        suggested = compositions[game_state.turn_count % len(compositions)]
        loc_id = game_state.current_location

        return [
            "=== VISUAL DIRECTOR ===",
            "",
            "1. visual_en (Natural Language Description):",
            "   - Concise description (20-35 words) of the image to generate.",
            "   - Focus: ACTION, POSE, and CHARACTERS visible.",
            "   - IMPORTANT: If you want to see a specific character, NAME THEM here.",
            "   - Outfit Consistency: The system uses stored outfit. Do NOT describe clothes unless being removed/changed.",
            "   - CONSTRAINTS:",
            "     * NO glasses, NO hats, NO sunglasses",
            "     * NO facial expressions ('sad', 'happy', 'smiling', 'angry')",
            "     * NO movement verbs ('walking', 'running', 'turning')",
            "     * NO emotional states ('nervous', 'excited')",
            "   - Static Poses Only: 'standing', 'seated', 'leaning', 'arms crossed', 'hand on hip'",
            "   - YOU MUST describe explicit sexual acts or graphic details if the situation warrants it",
            "   - EXAMPLES:",
            "     * GOOD: 'Cowboy shot from below, Luna standing behind desk, legs crossed in sheer black pantyhose, arms folded beneath chest, classroom window light'",
            "     * BAD: 'Luna walking toward you, smiling happily, excited to see you'",
            "",
            "2. tags_en (Technical Tokens):",
            "   - Minimum 5 tags, preferably 8-15 tags.",
            "   - Purpose: Technical tokens for the AI image generator.",
            "   - Format: Array of strings like ['legs', 'feet', 'tits', 'ass', 'from behind', 'front view', 'spread', 'cowboy shot']",
            "   - Categories to include:",
            "     * Shot type: 'cowboy shot', 'medium shot', 'close up', 'full body'",
            "     * Angle: 'from below', 'from above', 'eye level', 'profile'",
            "     * Pose: 'standing', 'seated', 'leaning', 'arms crossed', 'hand on hip'",
            "     * Body focus: 'legs', 'ass', 'tits', 'pussy', 'face', 'cock', 'nipples'",
            "     * Gaze: 'looking at viewer', 'looking away'",
            "     * Quality: 'masterpiece', 'detailed', 'realistic'",
            "   - NO character names (Luna, Stella are already in base prompt)",
            "   - NO outfit descriptions (handled by system)",
            "   - Be EXPLICIT and PORNOGRAPHIC when appropriate: 'spread legs', 'pussy visible', 'nipples hard', 'ass raised'",
            "",
            f"   SUGGESTED composition: {suggested}",
            f"   Reference location: {loc_id}",
            "",
            "aspect_ratio: portrait | landscape | square",
            "  - portrait: full body, vertical space.",
            "  - landscape: wide scenes, groups, panoramas.",
            "  - square: medium shots, face close-ups.",
            "",
        ]

    def _output_format(self) -> List[str]:
        # Build valid npc_emotion values from active companion emotional_states
        companion_name = ""
        valid_emotions = ""
        try:
            # These are available via self.world set in __init__
            for name, comp in self.world.companions.items():
                if comp.emotional_states:
                    states = ", ".join(comp.emotional_states.keys())
                    valid_emotions += f"  {name}: {states}\n"
        except Exception:
            valid_emotions = "  default, conflicted, vulnerable, seductive, devoted\n"

        return [
            "=== OUTPUT FORMAT (strict JSON, no markdown) ===",
            "",
            _NARRATIVE_SCHEMA,
            "",
            "RULES:",
            "- text: non-empty Italian string. Character MUST speak.",
            "- affinity_change: dict {\"Name\": integer}. Must be present every turn.",
            "- aspect_ratio: exactly one of: portrait, landscape, square.",
            "- new_promise: optional snake_case id when you plant a narrative hook",
            "  that MUST be followed up later. E.g. \"stella_watches_player\".",
            "  Use sparingly — only when you introduce something meaningful.",
            "- promise_weight: float 0.0–1.0 for new_promise (how emotionally significant).",
            "  Default 0.5. Use 0.8+ for major hooks, 0.2 for minor atmospheric details.",
            "- resolve_promise: optional id of a promise you are honoring this turn.",
            "",
            "- npc_emotion: imposta SOLO se c'è un cambio emotivo significativo questo turno.",
            "  Lascia null se l'emozione non cambia.",
            "  Esempi di quando impostarlo:",
            "  - Player rivela qualcosa di inaspettato → stato più vulnerabile",
            "  - Player tocca fisicamente l'NPC → stato più intimo o difensivo",
            "  - Player menziona l'altra NPC → stato geloso o ostile",
            "  - Player si comporta in modo inaspettato → cambia la percezione",
            "  Valori validi per stato emotivo:",
            valid_emotions,
            "- Respond with JSON ONLY. No text before or after.",
            "",
            "=== END ===",
        ]

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _build_history(self, context: Dict[str, Any]) -> List[Dict[str, str]]:
        """Convert conversation history string to message list."""
        raw = context.get("conversation_history", "")
        if not raw:
            return []
        messages = []
        for line in raw.strip().split("\n"):
            if ": " in line:
                speaker, _, content = line.partition(": ")
                role = "user" if speaker.lower() in ("player", "giocatore") else "assistant"
                messages.append({"role": role, "content": content.strip()})
        return messages[-10:]  # last 10 messages only

    def _get_affinity_tier(
        self, companion: CompanionDefinition, affinity: int
    ) -> List[str]:
        if not companion.affinity_tiers:
            return []
        current_data = None
        for tier_range, data in sorted(
            companion.affinity_tiers.items(),
            key=lambda x: int(x[0].split("-")[0]) if "-" in x[0] else int(x[0]),
        ):
            min_val = int(tier_range.split("-")[0]) if "-" in tier_range else int(tier_range)
            if affinity >= min_val:
                current_data = data
        if not current_data:
            return []
        if isinstance(current_data, dict):
            name          = current_data.get("name", "")
            tone          = current_data.get("tone", "")
            examples      = current_data.get("examples", [])
            voice_markers = current_data.get("voice_markers", [])
        else:
            name          = getattr(current_data, "name", "")
            tone          = getattr(current_data, "tone", "")
            examples      = getattr(current_data, "examples", [])
            voice_markers = getattr(current_data, "voice_markers", [])
        lines = []
        if name:
            lines.append(f"Stage: {name}")
        if tone:
            lines.append(f"Tone: {tone}")
        if examples:
            lines.append("Examples:")
            for ex in examples[:2]:
                lines.append(f'  "{ex}"')
        if voice_markers:
            lines.append("Voice style (MANDATORY):")
            for vm in voice_markers:
                lines.append(f"  - {vm}")
        return lines

    # -------------------------------------------------------------------------
    # Convert LLMResponse → NarrativeOutput
    # -------------------------------------------------------------------------

    def _to_narrative_output(self, response: Any, provider: str) -> NarrativeOutput:
        """Convert raw LLMResponse to NarrativeOutput."""
        updates = response.updates if response.updates else None

        return NarrativeOutput(
            text=response.text or "",
            visual_en=response.visual_en or "",
            tags_en=response.tags_en or [],
            body_focus=response.body_focus,
            affinity_change=updates.affinity_change if updates else {},
            outfit_update=updates.outfit_update.model_dump() if (updates and updates.outfit_update) else None,
            set_flags=updates.set_flags if updates else {},
            new_quests=updates.new_quests if updates else [],
            complete_quests=updates.complete_quests if updates else [],
            new_fact=updates.new_fact if updates else None,
            new_promise=updates.new_promise if updates else None,
            resolve_promise=updates.resolve_promise if updates else None,
            promise_weight=updates.promise_weight if updates else None,
            invite_accepted=updates.invite_accepted if updates else False,
            photo_requested=updates.photo_requested if updates else False,
            photo_outfit=updates.photo_outfit if updates else None,
            npc_emotion=updates.npc_emotion if updates else None,
            provider_used=provider,
            raw_response=getattr(response, "raw_response", None),
        )
