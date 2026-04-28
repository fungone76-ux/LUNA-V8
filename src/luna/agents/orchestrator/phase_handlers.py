"""Luna RPG — Phase Handlers (compatibility shim).

Questo file è mantenuto solo per compatibilità backward con import esterni.
Tutta la logica è stata spostata nei 5 mixin specializzati:

  turn_pipeline.py       → TurnPipelineMixin   (5 fasi + _build_result)
  agenda_handler.py      → AgendaHandlerMixin  (_run_gm_agenda)
  social_engine.py       → SocialEngineMixin   (_run_home_scene, _run_multi_npc)
  narrative_processor.py → NarrativeProcessorMixin (_phase_narrative)
  time_manager.py        → TimeManagerMixin    (_apply_phase_event, _run_phase_clock,
                                                execute_phase_advance)
"""
from .turn_pipeline import TurnPipelineMixin
from .agenda_handler import AgendaHandlerMixin
from .social_engine import SocialEngineMixin
from .narrative_processor import NarrativeProcessorMixin
from .time_manager import TimeManagerMixin


class PhaseHandlersMixin(
    TurnPipelineMixin,
    AgendaHandlerMixin,
    SocialEngineMixin,
    NarrativeProcessorMixin,
    TimeManagerMixin,
):
    """Aggregato di tutti i mixin di fase — usato solo per compatibilità backward."""
