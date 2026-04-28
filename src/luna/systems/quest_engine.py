"""Luna RPG — Quest Engine (compatibility shim).

Il modulo è stato rinominato quest_engine_base.py per chiarire che
QuestEngine è la classe base estesa da SequentialQuestEngine.
Questo shim mantiene la compatibilità backward per tutti gli import esistenti.
"""
from .quest_engine_base import (  # noqa: F401
    QuestEngine,
    QuestUpdateResult,
    ConditionEvaluator,
)
