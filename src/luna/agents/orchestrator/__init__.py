"""Luna RPG - Turn Orchestrator Package.

Main game turn orchestration logic.

REFACTORED: TurnOrchestrator eredita da 9 mixin specializzati:
- turn_pipeline.py:       TurnPipelineMixin    — 5 fasi del turno + _build_result
- agenda_handler.py:      AgendaHandlerMixin   — Step 2.9 GM Agenda
- social_engine.py:       SocialEngineMixin    — Step 5.5 MultiNPC + HomeScene
- narrative_processor.py: NarrativeProcessorMixin — Step 6-7.5 LLM + Guardian
- time_manager.py:        TimeManagerMixin     — Step 8 clock + phase advance
- intent_handlers.py:     IntentHandlersMixin  — _handle_* methods
- context_builder.py:     ContextBuilderMixin  — _build_context, _enrich_context
- support.py:             SupportMethodsMixin  — farewell, media, minimal_narrative
- state_manager.py:       StateManagerMixin    — _save

Backward compatibility: All imports from luna.agents.orchestrator
continue to work unchanged.
"""
from .orchestrator import TurnOrchestrator

__all__ = ["TurnOrchestrator"]
