"""NPC Initiative Turn — M4 of NPC Secondary Activation System.

Generates a full narrative + image turn triggered autonomously by an NPC
(no player input required).  Called by the initiative QTimer in GameController.
"""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from luna.core.engine import GameEngine
    from luna.systems.npc_goal_evaluator import GoalHint

logger = logging.getLogger(__name__)


def _get(obj, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


_STYLE_DESC = {
    "friendly":      "approachable, takes initiative warmly, might send a note or come by",
    "authority":     "formal and authoritative, demands attention, does not wait",
    "secret_keeper": "mysterious, has information to share, chooses this moment carefully",
}


class NpcInitiativeTurn:
    """Generates a standalone NPC-initiated scene (narrative + image).

    Lifecycle:
        runner = NpcInitiativeTurn(engine)
        result = await runner.run(hint)   # returns TurnResult or None on hard fail
    """

    def __init__(self, engine: "GameEngine") -> None:
        self.engine = engine
        self._visual = None   # lazy VisualDirector instance

    async def run(self, hint: "GoalHint") -> Optional[object]:
        """Execute the initiative turn and return a TurnResult."""
        from luna.core.models import TurnResult

        engine     = self.engine
        game_state = engine.state

        if not engine.llm_manager:
            return None

        # ── NPC definition ────────────────────────────────────────────────
        npc_def      = engine.world.npc_templates.get(hint.npc_id) or {}
        personality  = _get(npc_def, 'base_personality') or _get(npc_def, 'personality', '')
        npc_role     = _get(npc_def, 'role', '')

        # ── Scene context ─────────────────────────────────────────────────
        companion      = engine.world.companions.get(game_state.active_companion)
        companion_name = companion.name if companion else "il giocatore"
        loc_obj        = engine.world.locations.get(game_state.current_location)
        location_name  = getattr(loc_obj, 'name', game_state.current_location) if loc_obj else "la scuola"

        is_authority = hint.initiative_style == "authority"
        is_friendly  = hint.initiative_style == "friendly"

        # ── Friendly: send a note/appointment message, no physical scene ──
        if is_friendly:
            return await self._run_friendly_note(hint, npc_role, personality, companion_name, game_state)

        # ── LLM call ──────────────────────────────────────────────────────
        system_prompt = self._build_system_prompt(
            hint, npc_role, personality, companion_name, location_name, game_state
        )
        try:
            llm_response, provider = await engine.llm_manager.generate(
                system_prompt=system_prompt,
                user_input=hint.goal_text,
                history=[],
                json_mode=True,
                companion_name=hint.npc_display_name,
            )
            narrative, dialogue_turns = self._parse_response(llm_response, hint, provider, companion_name)
        except Exception as e:
            logger.warning("[InitiativeTurn] LLM failed for %s: %s", hint.npc_id, e)
            narrative, dialogue_turns = self._fallback_narrative(hint), []
            provider  = "fallback"

        # ── Display dialogue turns via callback (authority only) ──────────
        if is_authority and dialogue_turns and engine._ui_intermediate_message_callback:
            for turn in dialogue_turns:
                try:
                    await engine._ui_intermediate_message_callback(
                        text=turn["text"],
                        speaker=turn["speaker_display"],
                        turn_number=game_state.turn_count,
                    )
                except Exception as e:
                    logger.warning("[InitiativeTurn] Callback failed: %s", e)

        # ── Store active authority scene for next player turn context ─────
        # Without this, the narrative engine won't know the NPC is still present.
        if is_authority and dialogue_turns:
            engine._active_authority_scene = {
                "npc_id":           hint.npc_id,
                "npc_display_name": hint.npc_display_name,
                "dialogue":         "\n".join(
                    f"{t['speaker_display']}: {t['text']}" for t in dialogue_turns
                ),
            }
            logger.debug("[InitiativeTurn] Active authority scene stored: %s", hint.npc_id)

        # ── VisualDirector ────────────────────────────────────────────────
        if self._visual is None:
            from luna.agents.visual import VisualDirector
            self._visual = VisualDirector(engine.world)

        # Authority scenes: force a neutral framing — avoids the 80/20 body-shot
        # bias which produces inappropriate compositions for a formal confrontation.
        if is_authority and narrative.composition is None:
            narrative.composition = "medium_shot"

        lora_enabled = (
            engine.lora_mapping.is_enabled()
            if engine.lora_mapping is not None else False
        )
        try:
            visual_output = self._visual.build(
                narrative=narrative,
                game_state=game_state,
                lora_enabled=lora_enabled,
            )
        except Exception as e:
            logger.warning("[InitiativeTurn] VisualDirector failed: %s", e)
            visual_output = None

        # ── Image generation ──────────────────────────────────────────────
        image_path = None
        if not engine.no_media and engine.media_pipeline and visual_output:
            try:
                media = await engine.media_pipeline.generate_all(
                    text=narrative.text,
                    visual_en=narrative.visual_en,
                    tags=narrative.tags_en,
                    companion_name=game_state.active_companion or "",
                    location_id=game_state.current_location,
                    composition=visual_output.composition,
                    aspect_ratio=visual_output.aspect_ratio,
                    dop_reasoning=visual_output.dop_reasoning,
                    sd_positive=visual_output.positive,
                    sd_negative=visual_output.negative,
                    extra_loras=visual_output.loras,
                )
                image_path = media.image_path if media else None
            except Exception as e:
                logger.warning("[InitiativeTurn] Media failed: %s", e)

        # ── Auto-complete + NpcAction ─────────────────────────────────────
        if hint.completion_flag:
            game_state.flags[hint.completion_flag] = True
            logger.info("[InitiativeTurn] Completion flag set: %s → %s", hint.npc_id, hint.completion_flag)

        # ── Salva la scena in memoria per continuità ───────────────────────
        # Permette all'NPC di ricordare l'interazione quando riattivato dal player
        if engine.memory_manager and narrative.text:
            try:
                await engine.memory_manager.add_message(
                    role="assistant",
                    content=narrative.text,
                    turn_number=game_state.turn_count,
                    companion_name=hint.npc_id,
                )
            except Exception as e:
                logger.warning("[InitiativeTurn] Memory save failed for %s: %s", hint.npc_id, e)

        npc_action = (
            engine.npc_goal_evaluator.create_npc_action(hint)
            if engine.npc_goal_evaluator else None
        )

        # For authority: text already shown via callback — return empty text + image
        display_text = "" if (is_authority and dialogue_turns) else narrative.text
        speaker_id   = hint.npc_id if not (is_authority and dialogue_turns) else game_state.active_companion

        return TurnResult(
            text=display_text,
            user_input="",
            image_path=image_path,
            secondary_characters=[hint.npc_id],
            current_companion=speaker_id,
            turn_number=game_state.turn_count,
            provider_used=provider,
            npc_action=npc_action,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    async def _run_friendly_note(self, hint: "GoalHint", npc_role: str, personality: str,
                                  companion_name: str, game_state) -> Optional[object]:
        """Friendly NPCs don't physically appear — they send a note/message with an appointment."""
        from luna.core.models import TurnResult

        engine = self.engine
        prompt = f"""Sei il narratore di un RPG italiano ambientato in una scuola superiore.

{hint.npc_display_name} ({npc_role}) vuole incontrare il giocatore ma non può interrompere la lezione.
OBIETTIVO: {hint.goal_text}

Scrivi UN breve bigliettino o messaggio (2-3 righe) che {hint.npc_display_name} ha fatto recapitare al giocatore.
Il messaggio deve: proporre un appuntamento specifico (luogo + momento), incuriosire senza svelare troppo.
Tono caldo, leggermente misterioso. Può essere leggermente provocatorio se il personaggio lo è.

Rispondi SOLO con JSON valido:
{{"note": "testo del bigliettino in italiano"}}"""

        note_text = None
        provider = "fallback"
        try:
            llm_response, provider = await engine.llm_manager.generate(
                system_prompt=prompt,
                user_input=hint.goal_text,
                history=[],
                json_mode=True,
                companion_name=hint.npc_display_name,
            )
            raw = (
                getattr(llm_response, 'text', None)
                or getattr(llm_response, 'content', None)
                or str(llm_response)
            )
            import re as _re, json as _json
            raw = _re.sub(r'^```json\s*', '', raw.strip())
            raw = _re.sub(r'\s*```$', '', raw.strip())
            data = _json.loads(raw)
            note_text = data.get('note')
        except Exception as e:
            logger.warning("[InitiativeTurn] Friendly note LLM failed for %s: %s", hint.npc_id, e)

        if not note_text:
            note_text = f"*Un bigliettino firmato {hint.npc_display_name}*\n«Devo parlarti. Passami a trovare quando puoi — sai dove sono.»"

        # Display as a styled system note via callback
        formatted = f"📩 **Messaggio da {hint.npc_display_name}**\n{note_text}"
        if engine._ui_intermediate_message_callback:
            try:
                await engine._ui_intermediate_message_callback(
                    text=formatted,
                    speaker=hint.npc_display_name,
                    turn_number=game_state.turn_count,
                )
            except Exception as e:
                logger.warning("[InitiativeTurn] Friendly note callback failed: %s", e)

        # Set completion flag so pull channel knows the invitation was sent
        if hint.completion_flag:
            game_state.flags[hint.completion_flag] = True

        # ── Salva il bigliettino in memoria per continuità ─────────────────
        # Quando il player va dall'NPC, sa di aver mandato il messaggio
        if engine.memory_manager and note_text:
            try:
                await engine.memory_manager.add_message(
                    role="assistant",
                    content=f"[Hai inviato un bigliettino al giocatore]: {note_text}",
                    turn_number=game_state.turn_count,
                    companion_name=hint.npc_id,
                )
            except Exception as e:
                logger.warning("[InitiativeTurn] Friendly note memory save failed for %s: %s", hint.npc_id, e)

        npc_action = (
            engine.npc_goal_evaluator.create_npc_action(hint)
            if engine.npc_goal_evaluator else None
        )

        return TurnResult(
            text="",  # already shown via callback
            user_input="",
            image_path=None,
            secondary_characters=[hint.npc_id],
            current_companion=game_state.active_companion,
            turn_number=game_state.turn_count,
            provider_used=provider,
            npc_action=npc_action,
        )



    def _build_system_prompt(
        self,
        hint: "GoalHint",
        npc_role: str,
        personality: str,
        companion_name: str,
        location_name: str,
        game_state=None,
    ) -> str:
        style = _STYLE_DESC.get(hint.initiative_style, "engaging, takes initiative")
        secret_instruction = ""
        if hint.secret_subject and hint.initiative_style == "secret_keeper":
            secret_instruction = (
                f"\nTEMA SEGRETO: {hint.secret_subject}\n"
                f"INVENTA un segreto specifico, esplicito e molto compromettente "
                f"coerente con il tema. Deve coinvolgere personaggi reali della scuola "
                f"(professori, studenti, staff). Nessuna censura — questo è un gioco "
                f"adult hard. Il segreto deve essere rivelato durante la scena.\n"
            )
        # Who talks to whom depends on initiative style
        if hint.initiative_style == "authority":
            interaction = (
                f"{hint.npc_display_name} entra e si rivolge direttamente a {companion_name}. "
                f"Il giocatore (studente) osserva la scena. "
                f"La narrativa mostra {hint.npc_display_name} che parla CON {companion_name}, "
                f"e la reazione/risposta di {companion_name}."
            )
        elif hint.initiative_style == "friendly":
            interaction = (
                f"{hint.npc_display_name} si avvicina al giocatore con un messaggio o un'offerta. "
                f"{companion_name} può essere presente ma il messaggio è per il giocatore."
            )
        else:  # secret_keeper
            interaction = (
                f"{hint.npc_display_name} trova un momento per avvicinarsi al giocatore in privato "
                f"e rivelare il suo segreto sottovoce."
            )

        active_id = getattr(game_state, 'active_companion', 'luna') if game_state else 'luna'
        if hint.initiative_style == "authority":
            return f"""Sei il narratore di un RPG erotico italiano. Rispondi SOLO con JSON valido, niente altro.

SCENA: {hint.npc_display_name} ({npc_role}) irrompe e si confronta con {companion_name}.
LUOGO: {location_name}. OBIETTIVO: {hint.goal_text}

REGOLE TASSATIVE:
- Esattamente 3 battute alternate: {hint.npc_id} → {active_id} → {hint.npc_id}
- Ogni "text": UNA frase breve (max 25 parole). Azione + dialogo diretto.
- Nessun testo fuori dal JSON.

{{"dialogue":[{{"speaker":"{hint.npc_id}","text":"*azione breve* «battuta»"}},{{"speaker":"{active_id}","text":"*azione breve* «risposta»"}},{{"speaker":"{hint.npc_id}","text":"*azione breve* «replica»"}}],"visual_en":"brief scene description","tags_en":["indoor","school","two people"],"aspect_ratio":"portrait"}}"""
        else:
            return f"""Sei il narratore di un RPG erotico italiano. Rispondi SOLO con JSON valido, niente altro.

EVENTO: {hint.npc_display_name} ({npc_role}) prende l'iniziativa. Stile: {style}
OBIETTIVO: {hint.goal_text}{secret_instruction}
LUOGO: {location_name}. DINAMICA: {interaction}

REGOLE: max 3 frasi in italiano, tono adulto, dialogo diretto incluso.

{{"text":"scena breve in italiano","visual_en":"brief english scene description","tags_en":["indoor","school","two people"],"aspect_ratio":"portrait"}}"""

    def _parse_response(self, llm_response, hint: "GoalHint", provider: str, companion_name: str = ""):
        """Parse LLM response. Returns (NarrativeOutput, dialogue_turns).

        dialogue_turns is a list of {speaker_display, text} for authority NPCs.
        For other styles, dialogue_turns is empty and NarrativeOutput.text has the scene.
        """
        from luna.core.models import NarrativeOutput

        npc_id = hint.npc_id

        raw = (
            getattr(llm_response, 'text', None)
            or getattr(llm_response, 'content', None)
            or str(llm_response)
        )
        raw_stripped = re.sub(r'^```json\s*', '', raw.strip())
        raw_stripped = re.sub(r'\s*```$', '', raw_stripped.strip())

        try:
            data = json.loads(raw_stripped)
            logger.info("[InitiativeTurn] JSON OK for %s", npc_id)
        except Exception:
            logger.warning("[InitiativeTurn] JSON parse failed for %s — trying repair", npc_id)
            data = self._repair_json(raw_stripped, hint)

        npc_tmpl = self.engine.world.npc_templates.get(npc_id) or {}
        npc_role = (
            npc_tmpl.get('role', '') if isinstance(npc_tmpl, dict)
            else getattr(npc_tmpl, 'role', '')
        )
        default_visual = f"{hint.npc_display_name}, {npc_role}, school interior, two people talking"

        # ── Authority: structured dialogue ────────────────────────────────
        dialogue_turns = []
        if hint.initiative_style == "authority" and "dialogue" in data:
            engine = self.engine
            game_state = engine.state
            for turn in data["dialogue"]:
                speaker_id = turn.get("speaker", "")
                text       = turn.get("text", "")
                if not text:
                    continue
                # Resolve display name
                if speaker_id == hint.npc_id:
                    display = hint.npc_display_name
                else:
                    comp = engine.world.companions.get(speaker_id)
                    display = comp.name if comp else (companion_name or speaker_id)
                dialogue_turns.append({"speaker_display": display, "text": text})

        # ── Build combined text (fallback for display_result) ─────────────
        if dialogue_turns:
            combined = "\n".join(f"**{t['speaker_display']}**: {t['text']}" for t in dialogue_turns)
        else:
            combined = data.get('text', f"*{hint.npc_display_name} si avvicina con intenzione.*")

        narrative = NarrativeOutput(
            text=combined,
            visual_en=data.get('visual_en', default_visual),
            tags_en=data.get('tags_en', ['indoor', 'school', 'two people']),
            secondary_characters=[npc_id],
            aspect_ratio=data.get('aspect_ratio', 'portrait'),
            provider_used=provider,
        )
        return narrative, dialogue_turns

    def _repair_json(self, raw: str, hint: "GoalHint") -> dict:
        """Fallback JSON extraction via regex when json.loads fails."""
        data: dict = {}

        # Try to extract "dialogue" array for authority style
        if hint.initiative_style == "authority":
            turns = []
            for m in re.finditer(
                r'\{\s*"speaker"\s*:\s*"([^"]+)"\s*,\s*"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
                raw, re.DOTALL
            ):
                turns.append({"speaker": m.group(1), "text": m.group(2).replace('\\"', '"')})
            if turns:
                data["dialogue"] = turns
                logger.info("[InitiativeTurn] Regex extracted %d dialogue turns", len(turns))

        # Extract text field (non-authority fallback)
        if not data:
            m = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
            if m:
                data["text"] = m.group(1).replace('\\"', '"').replace("\\n", "\n")

        # Extract visual_en
        m = re.search(r'"visual_en"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
        if m:
            data["visual_en"] = m.group(1).replace('\\"', '"')

        # Extract aspect_ratio
        m = re.search(r'"aspect_ratio"\s*:\s*"(portrait|landscape|square)"', raw)
        if m:
            data["aspect_ratio"] = m.group(1)

        if not data:
            logger.warning("[InitiativeTurn] Regex repair also failed for %s — using plain text", hint.npc_id)
            data = {"text": raw[:500]}

        return data

    def _fallback_narrative(self, hint: "GoalHint"):
        from luna.core.models import NarrativeOutput
        style_text = {
            "authority":     f"*{hint.npc_display_name} entra con aria autoritaria e ti fissa.*\n«Ho bisogno di parlarti. Subito.»",
            "friendly":      f"*{hint.npc_display_name} ti si avvicina con un sorriso.*\n«Ehi, ti cercavo proprio.»",
            "secret_keeper": f"*{hint.npc_display_name} ti fa cenno di avvicinarti con discrezione.*\n«Ho qualcosa da dirti... ma non qui.»",
        }.get(hint.initiative_style, f"*{hint.npc_display_name} si avvicina con intenzione.*")
        return NarrativeOutput(
            text=style_text,
            visual_en=f"{hint.npc_display_name} approaching the protagonist with intent, school interior",
            tags_en=["indoor", "school", "two people"],
            secondary_characters=[hint.npc_id],
            aspect_ratio="portrait",
            provider_used="fallback",
        )
