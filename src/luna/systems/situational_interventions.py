"""Situational Interventions System - NPCs react proactively to situations.

V4.3 FEATURE: Allows NPCs to intervene based on context without player explicitly
addressing them. Examples:
- Teacher catching you talking in class
- Guard catching you sneaking
- Parent catching misbehavior
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Any, TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from luna.core.models import GameState
    from luna.core.engine import GameEngine


class SituationType(Enum):
    """Types of situations that can trigger interventions."""
    TALKING_IN_CLASS = "talking_in_class"
    SNEAKING = "sneaking"
    CHEATING = "cheating"
    BEING_LATE = "being_late"
    INAPPROPRIATE_BEHAVIOR = "inappropriate_behavior"
    SPYING = "spying"


@dataclass
class SituationalTrigger:
    """A trigger condition for situational intervention."""
    situation_type: SituationType
    location_patterns: List[str]
    behavior_patterns: List[str]
    required_roles: List[str]
    priority: int = 1  # Higher = checked first


class SituationalInterventionSystem:
    """System for proactive NPC interventions based on context."""
    
    def __init__(self, engine: GameEngine, world, state_manager, 
                 multi_npc_manager, llm_manager, state_memory):
        """Initialize the situational intervention system.
        
        Args:
            engine: GameEngine reference
            world: World definition
            state_manager: State manager
            multi_npc_manager: Multi-NPC manager
            llm_manager: LLM manager for generating responses
            state_memory: State memory manager
        """
        self.engine = engine
        self.world = world
        self.state_manager = state_manager
        self.multi_npc_manager = multi_npc_manager
        self.llm_manager = llm_manager
        self.state_memory = state_memory
        
        # Define situational triggers
        self._triggers = self._setup_triggers()
    
    def _setup_triggers(self) -> List[SituationalTrigger]:
        """Setup all situational triggers."""
        return [
            # 1. Insegnante becca lo studente a parlare in classe
            SituationalTrigger(
                situation_type=SituationType.TALKING_IN_CLASS,
                location_patterns=[
                    "classroom", "aula", "classe", "school_classroom",
                    "school_office_luna", "ufficio_luna", "laboratorio"
                ],
                behavior_patterns=[
                    r"\b(parlo\s+con|discuto\s+con|chiacchiero\s+con|sussurro\s+a)\b",
                    r"\b(guardo\s+stella|guardo\s+luna|osservo\s+la\s+classe)\b",
                    r"\b(rido|sorriso|sghignazzo|ridacchio)\b",
                    r"\b(passo\s+un\s+biglietto|bigliettino|messaggio\s+a)\b",
                    r"\b(distratto|non\s+ascolto|ignoro\s+la\s+lezione)\b",
                ],
                required_roles=["teacher", "professoressa", "professore", "insegnante di matematica"],
                priority=10,
            ),

            # 2. Studente in ritardo — Luna o chiunque lo nota all'ingresso
            SituationalTrigger(
                situation_type=SituationType.BEING_LATE,
                location_patterns=[
                    "school_entrance", "school_corridor", "school_classroom",
                    "corridoio", "ingresso", "aula"
                ],
                behavior_patterns=[
                    r"\b(arrivo\s+tardi|sono\s+in\s+ritardo|entro\s+in\s+ritardo)\b",
                    r"\b(entro\s+di\s+corsa|mi\s+precipito|arrivo\s+ansimando)\b",
                    r"\b(scusa\s+il\s+ritardo|mi\s+sono\s+svegliato\s+tardi|ho\s+perso\s+il\s+bus)\b",
                    r"\b(entro\s+in\s+classe|mi\s+siedo\s+di\s+nascosto|cerco\s+di\s+non\s+farmi\s+notare)\b",
                ],
                required_roles=["insegnante di matematica", "professoressa", "teacher"],
                priority=9,
            ),

            # 3. Studente che copia — Luna lo becca durante un compito
            SituationalTrigger(
                situation_type=SituationType.CHEATING,
                location_patterns=[
                    "school_classroom", "aula", "classroom", "school_office_luna"
                ],
                behavior_patterns=[
                    r"\b(copio\s+da|guardo\s+il\s+compito\s+di|spio\s+il\s+foglio)\b",
                    r"\b(copio|sto\s+copiando|cerco\s+di\s+copiare)\b",
                    r"\b(passo\s+le\s+risposte|dico\s+le\s+risposte\s+a|suggerisco\s+a)\b",
                    r"\b(guardo\s+il\s+telefono\s+di\s+nascosto|uso\s+il\s+cellulare\s+durante)\b",
                    r"\b(leggo\s+i\s+promemoria|guardo\s+gli\s+appunti\s+di\s+nascosto)\b",
                ],
                required_roles=["insegnante di matematica", "professoressa", "teacher"],
                priority=10,
            ),

            # 4. Comportamento inappropriato nei corridoi — Maria la bidella interviene
            SituationalTrigger(
                situation_type=SituationType.INAPPROPRIATE_BEHAVIOR,
                location_patterns=[
                    "school_corridor", "school_entrance", "school_cafeteria",
                    "school_storage", "corridoio", "mensa", "ingresso"
                ],
                behavior_patterns=[
                    r"\b(corro\s+nel\s+corridoio|corro\s+a\s+scuola|mi\s+metto\s+a\s+correre)\b",
                    r"\b(urlo|grido|faccio\s+casino|faccio\s+rumore)\b",
                    r"\b(lancio|tiro|butto\s+qualcosa)\b",
                    r"\b(entro\s+nel\s+magazzino|frugare\s+nel\s+magazzino|apro\s+porte\s+chiuse)\b",
                    r"\b(imbratto|scrivo\s+sul\s+muro|rompo|danneggio)\b",
                ],
                required_roles=["bidella", "custode", "personale scolastico"],
                priority=7,
            ),

            # 5. Spiare/sbirciare — chiunque lo scopre reagisce
            SituationalTrigger(
                situation_type=SituationType.SPYING,
                location_patterns=[
                    "school_corridor", "school_locker_room", "school_bathroom_female",
                    "school_bathroom_male", "school_office_luna", "school_storage",
                    "school_classroom", "park", "maria_home", "corridoio"
                ],
                behavior_patterns=[
                    r"\b(spio|sbircio|sbirciare|spiare)\b",
                    r"\b(guardo\s+dal\s+buco|guardo\s+dalla\s+serratura|spio\s+dal\s+buco)\b",
                    r"\b(mi\s+nascondo\s+per\s+guardare|osservo\s+di\s+nascosto|guardo\s+di\s+nascosto)\b",
                    r"\b(cerco\s+di\s+vedere|provo\s+a\s+spiare|cerco\s+di\s+spiare)\b",
                    r"\b(sbirci|dai\s+uno\s+sguardo\s+furtivo|occhio\s+alla\s+serratura)\b",
                    r"\b(guardo\s+attraverso|spio\s+attraverso|guardo\s+da\s+dietro)\b",
                ],
                required_roles=[
                    "insegnante di matematica", "professoressa", "teacher",
                    "bidella", "studentessa"
                ],
                priority=11,  # Alta priorità — situazione imbarazzante
            ),
        ]
    
    async def check_and_intervene(
        self,
        user_input: str,
        game_state: GameState,
    ) -> Optional[Any]:  # Returns TurnResult or None
        """Check if any NPC should intervene and generate response.
        
        Args:
            user_input: Player's input text
            game_state: Current game state
            
        Returns:
            TurnResult if intervention triggered, None otherwise
        """
        text_lower = user_input.lower()
        current_location = game_state.current_location
        
        # Get present NPCs
        present_npcs = self._get_present_npcs(game_state, user_input)
        
        # Check each trigger
        for trigger in sorted(self._triggers, key=lambda t: t.priority, reverse=True):
            if self._matches_trigger(trigger, text_lower, current_location):
                # Find appropriate NPC to intervene
                intervener = self._find_intervener(
                    trigger.required_roles, 
                    present_npcs, 
                    game_state.active_companion
                )
                
                if intervener:
                    logger.debug(f"[Situational] {intervener} intervenes for {trigger.situation_type.value}")
                    return await self._generate_intervention(
                        game_state,
                        trigger.situation_type,
                        intervener,
                        user_input
                    )
        
        return None
    
    def _matches_trigger(
        self, 
        trigger: SituationalTrigger, 
        text: str, 
        location: str
    ) -> bool:
        """Check if current situation matches a trigger.
        
        Args:
            trigger: The trigger to check
            text: Lowercase user input
            location: Current location
            
        Returns:
            True if matches
        """
        # Check location
        location_match = any(
            pat in location.lower() for pat in trigger.location_patterns
        )
        if not location_match:
            return False
        
        # Check behavior patterns
        behavior_match = any(
            re.search(pat, text) for pat in trigger.behavior_patterns
        )
        
        return behavior_match
    
    def _get_present_npcs(self, game_state: GameState, user_input: str) -> List[str]:
        """Get NPCs present at current location."""
        # Use multi_npc_manager if available
        if self.multi_npc_manager:
            # Get from multi_npc_manager
            all_npcs = self.multi_npc_manager.get_present_npcs(
                game_state.active_companion,
                game_state
            )
            # Filter by location
            return [npc for npc in all_npcs if npc != "_solo_"]
        return []
    
    def _find_intervener(
        self,
        required_roles: List[str],
        present_npcs: List[str],
        active_companion: str
    ) -> Optional[str]:
        """Find an NPC with appropriate role to intervene.
        
        Args:
            required_roles: List of acceptable roles
            present_npcs: NPCs present at location
            active_companion: Currently active companion
            
        Returns:
            Name of intervener or None
        """
        # Check present NPCs first
        for npc_name in present_npcs:
            npc_def = self.world.companions.get(npc_name)
            if npc_def and npc_def.role:
                if npc_def.role.lower() in required_roles:
                    return npc_name
        
        # Check active companion
        active_def = self.world.companions.get(active_companion)
        if active_def and active_def.role:
            if active_def.role.lower() in required_roles:
                return active_companion
        
        return None
    
    async def _generate_intervention(
        self,
        game_state: GameState,
        situation_type: SituationType,
        intervener: str,
        context: str,
    ) -> Optional[Any]:  # TurnResult
        """Generate intervention response.
        
        Args:
            game_state: Current game state
            situation_type: Type of situation
            intervener: Name of intervening NPC
            context: User input that triggered this
            
        Returns:
            TurnResult with intervention
        """
        from luna.core.models import TurnResult
        
        npc_def = self.world.companions.get(intervener)
        if not npc_def:
            return None
        
        # Build prompt based on situation
        prompts = {
            SituationType.TALKING_IN_CLASS: f"""You are {intervener}, {npc_def.base_personality[:200]}...

SITUATION: You just noticed a student talking/chatting during your lesson instead of listening.

REQUIRED BEHAVIOR:
- You are strict, authoritative, professional
- You do not tolerate disrespect
- Interrupt the student's conversation
- You can be sarcastic or intimidating
- Threaten consequences if necessary
- You want to restore order

RESPOND as if speaking directly to the student. Use *actions* between asterisks.

JSON FORMAT:
{{
    "text": "Your stern dialogue here with *actions*",
    "visual_en": "English description for the image",
    "tags_en": ["tag1", "tag2"]
}}""",

            SituationType.BEING_LATE: f"""Sei {intervener}, {npc_def.base_personality[:200]}...

SITUAZIONE: Uno studente è appena entrato in ritardo in classe mentre stai facendo lezione.
Tutti gli altri studenti si voltano a guardare.

COMPORTAMENTO RICHIESTO:
- Sei seccata, interrompi la spiegazione
- Puoi essere sarcastica ("Che piacere ricevere la sua presenza...")
- Chiedi una giustificazione con tono freddo
- Minaccia di segnare il ritardo sul registro
- Non lasciare correre, imponi la tua autorità

Rispondi direttamente allo studente. Usa *azioni* tra asterischi. Scrivi in italiano.

FORMATO JSON:
{{
    "text": "Il tuo dialogo severo con *azioni*",
    "visual_en": "English description: teacher interrupting lesson, pointing at late student",
    "tags_en": ["1girl", "teacher", "classroom", "stern_expression", "pointing"]
}}""",

            SituationType.CHEATING: f"""Sei {intervener}, {npc_def.base_personality[:200]}...

SITUAZIONE: Durante una verifica hai appena sorpreso uno studente che stava copiando.
Hai visto tutto. Non c'è via di scampo.

COMPORTAMENTO RICHIESTO:
- Avvicinati lentamente senza dire nulla prima
- Poi confrontalo con tono gelido e tagliente
- Ritira il compito o minaccia di farlo
- Puoi umiliarlo davanti alla classe
- Annuncia conseguenze serie (segnalazione, voto zero)
- Sii implacabile — questo è inaccettabile per te

Rispondi direttamente allo studente. Usa *azioni* tra asterischi. Scrivi in italiano.

FORMATO JSON:
{{
    "text": "Il tuo dialogo duro con *azioni*",
    "visual_en": "English description: teacher catching student cheating, leaning over desk",
    "tags_en": ["1girl", "teacher", "classroom", "angry_expression", "leaning_forward"]
}}""",

            SituationType.INAPPROPRIATE_BEHAVIOR: f"""Sei {intervener}, {npc_def.base_personality[:200]}...

SITUAZIONE: Nei corridoi della scuola hai appena visto uno studente comportarsi in modo
inappropriato — correre, urlare, fare casino o toccare cose che non dovrebbe.

COMPORTAMENTO RICHIESTO:
- Sei la bidella, la scuola è casa tua e non tolleri il disordine
- Fermalo con voce decisa e burbera
- Richiama le regole della scuola
- Puoi essere colorita e pittoresca nel linguaggio
- Minaccia di portarlo dal preside
- Fai capire che hai gli occhi ovunque

Rispondi direttamente allo studente. Usa *azioni* tra asterischi. Scrivi in italiano.

FORMATO JSON:
{{
    "text": "Il tuo dialogo burbero con *azioni*",
    "visual_en": "English description: school janitor scolding student in corridor, hands on hips",
    "tags_en": ["1girl", "janitor", "corridor", "scolding", "hands_on_hips"]
}}""",

            SituationType.SPYING: f"""Sei {intervener}, {npc_def.base_personality[:200]}...

SITUAZIONE: Hai appena sorpreso uno studente che ti stava spiando o sbirciando —
guardava dal buco della serratura, si nascondeva per osservarti, o ti fissava di nascosto.

COMPORTAMENTO RICHIESTO:
- Reagisci con forza — sei indignata, sorpresa, furiosa
- Mostrati nella tua piena autorità e fisicità
- Puoi essere minacciosa, glaciale oppure provocatoria a seconda del tuo carattere
- Se sei Luna (insegnante): fredda e tagliente, umilia con le parole
- Se sei Maria (bidella): burbera e diretta, minaccia il preside
- Se sei Stella (studentessa): imbarazzata poi arrabbiata, reagisce con veemenza
- NON minimizzare — è una violazione della privacy, reagisci con intensità
- Descrivi la tua reazione fisica con dettaglio (voltarti di scatto, avvicinarti, bloccare l'uscita)

Rispondi direttamente allo studente. Usa *azioni* tra asterischi. Scrivi in italiano.
Sii vivida, intensa, non banale.

FORMATO JSON:
{{
    "text": "La tua reazione intensa con *azioni fisiche dettagliate*",
    "visual_en": "English description: woman caught someone spying, turning sharply with intense expression, confrontational pose",
    "tags_en": ["1girl", "intense_expression", "confrontational", "dynamic_pose", "surprised_then_angry"]
}}""",
        }
        
        system_prompt = prompts.get(
            situation_type,
            f"You are {intervener}. Intervene in an inappropriate situation."
        )
        
        try:
            # Generate response
            # llm_manager.generate() returns (LLMResponse, provider_name)
            llm_response_tuple = await self.llm_manager.generate(
                system_prompt=system_prompt,
                user_input=f"The student just did: '{context}'",
                history=[],
                json_mode=True,
            )
            llm_response, _ = llm_response_tuple  # unpack (LLMResponse, provider)
            
            response_text = getattr(llm_response, 'text', '') or getattr(llm_response, 'raw_response', '')
            
            if response_text:
                # Format with dramatic header
                full_text = f"**{intervener} ti interrompe improvvisamente:**\n\n{response_text}"
                
                # Switch to intervener
                old_companion = game_state.active_companion
                switched = intervener != old_companion
                
                if switched:
                    self.state_manager.switch_companion(intervener)
                    self.engine.companion = intervener
                
                # Save to memory
                await self.state_memory.add_message(
                    role="user",
                    content=context,
                    turn_number=game_state.turn_count,
                    session_id=game_state.session_id,
                    companion=game_state.active_companion,
                )
                await self.state_memory.add_message(
                    role="assistant",
                    content=response_text,
                    turn_number=game_state.turn_count,
                    session_id=game_state.session_id,
                    companion=game_state.active_companion,
                    visual_en=getattr(llm_response, 'visual_en', ''),
                    tags_en=getattr(llm_response, 'tags_en', []),
                )
                
                # Advance and save
                self.state_manager.advance_turn()
                await self.state_memory.save_all()

                # Early-return path: generate media here because orchestrator
                # will not reach _phase_finalize for situational interventions.
                media: Dict[str, Optional[str]] = {
                    "image_path": None,
                    "audio_path": None,
                    "video_path": None,
                }
                if not self.engine.no_media and self.engine.media_pipeline:
                    try:
                        media_result = await self.engine.media_pipeline.generate_all(
                            text=response_text,
                            visual_en=getattr(llm_response, "visual_en", "") or "",
                            tags=getattr(llm_response, "tags_en", []) or [],
                            companion_name=intervener,
                            base_prompt=getattr(npc_def, "base_prompt", "") or "",
                            location_id=game_state.current_location,
                        )
                        if media_result:
                            media["image_path"] = getattr(media_result, "image_path", None)
                            media["audio_path"] = getattr(media_result, "audio_path", None)
                            media["video_path"] = getattr(media_result, "video_path", None)
                    except Exception as media_err:
                        logger.warning(
                            "[Situational] Media generation failed (early return): %s",
                            media_err,
                        )
                
                # Build result
                return TurnResult(
                    text=full_text,
                    user_input=context,
                    image_path=media.get("image_path"),
                    audio_path=media.get("audio_path"),
                    video_path=media.get("video_path"),
                    turn_number=game_state.turn_count,
                    provider_used="situational_intervention",
                    switched_companion=switched,
                    previous_companion=old_companion if switched else None,
                    current_companion=intervener,
                )
                
        except Exception as e:
            logger.error(f"[Situational] Error generating intervention: {e}")
            import traceback
            traceback.print_exc()
        
        return None
