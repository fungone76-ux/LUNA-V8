"""Luna RPG v6 - Database Manager.

Async SQLite via SQLAlchemy + aiosqlite.
All persistence passes through here.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, func,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from luna.core.models import AppConfig

logger = logging.getLogger(__name__)


# =============================================================================
# ORM Models
# =============================================================================

class Base(DeclarativeBase):
    pass


class GameSessionModel(Base):
    __tablename__ = "game_sessions"

    id:           Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    world_id:     Mapped[str]           = mapped_column(String(64))
    companion:    Mapped[str]           = mapped_column(String(64))
    turn_count:   Mapped[int]           = mapped_column(Integer, default=0)
    time_of_day:  Mapped[str]           = mapped_column(String(16), default="Morning")
    location:     Mapped[str]           = mapped_column(String(64), default="Unknown")
    state_json:   Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at:   Mapped[datetime]      = mapped_column(DateTime, default=func.now())
    updated_at:   Mapped[datetime]      = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class ConversationMessageModel(Base):
    __tablename__ = "conversation_messages"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id:  Mapped[int]           = mapped_column(Integer, ForeignKey("game_sessions.id"))
    role:        Mapped[str]           = mapped_column(String(16))
    content:     Mapped[str]           = mapped_column(Text)
    turn_number: Mapped[int]           = mapped_column(Integer, default=0)
    visual_en:   Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags_en:     Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    companion:   Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at:  Mapped[datetime]      = mapped_column(DateTime, default=func.now())


class MemoryEntryModel(Base):
    __tablename__ = "memory_entries"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id:  Mapped[int]           = mapped_column(Integer, ForeignKey("game_sessions.id"))
    type:        Mapped[str]           = mapped_column(String(16), default="fact")
    content:     Mapped[str]           = mapped_column(Text)
    turn_count:  Mapped[int]           = mapped_column(Integer, default=0)
    importance:  Mapped[int]           = mapped_column(Integer, default=5)
    companion:   Mapped[str]           = mapped_column(String(64), default="")
    created_at:  Mapped[datetime]      = mapped_column(DateTime, default=func.now())


class QuestStateModel(Base):
    __tablename__ = "quest_states"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id:       Mapped[int]           = mapped_column(Integer, ForeignKey("game_sessions.id"))
    quest_id:         Mapped[str]           = mapped_column(String(64))
    status:           Mapped[str]           = mapped_column(String(32), default="not_started")
    current_stage_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    stage_data:       Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at:       Mapped[int]           = mapped_column(Integer, default=0)
    completed_at:     Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pending_since_turn: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stage_entered_at: Mapped[int]           = mapped_column(Integer, default=0)


class NpcMindModel(Base):
    """v8: Persistent NPCMind state. One row per NPC per session.

    Stored as JSON blob so the schema doesn't need updating when NPCMind
    gains new fields — only the serializer/deserializer needs updating.
    """
    __tablename__ = "npc_minds"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id:  Mapped[int]           = mapped_column(Integer, ForeignKey("game_sessions.id"))
    npc_id:      Mapped[str]           = mapped_column(String(64))
    mind_json:   Mapped[str]           = mapped_column(Text, default="{}")
    # ISO timestamp of the last save — used to calculate offline ticks on next load
    saved_at:    Mapped[datetime]      = mapped_column(DateTime, default=func.now(), onupdate=func.now())


# =============================================================================
# Database Manager
# =============================================================================

class DatabaseManager:
    """Async SQLite database manager.

    Usage:
        db = get_db_manager(settings)
        await db.create_tables()
        async with db.session() as s:
            session = await db.create_session(s, world_id, companion)
    """

    def __init__(self, config: Optional[AppConfig] = None) -> None:
        from luna.core.config import get_settings
        self._config = config or get_settings()
        url = self._config.database_url

        # Ensure storage directory exists
        if url.startswith("sqlite"):
            db_path = url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._engine = create_async_engine(url, echo=False)
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def create_tables(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.debug("Database tables created/verified")

    async def drop_tables(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    # -------------------------------------------------------------------------
    # Sessions
    # -------------------------------------------------------------------------

    async def create_session(
        self,
        db: AsyncSession,
        world_id: str,
        companion: str,
        state_json: Optional[str] = None,
    ) -> GameSessionModel:
        row = GameSessionModel(
            world_id=world_id,
            companion=companion,
            state_json=state_json,
        )
        db.add(row)
        await db.flush()
        logger.info("Created game session %d: world=%s, companion=%s", row.id, world_id, companion)
        return row

    async def get_session(self, db: AsyncSession, session_id: int) -> Optional[GameSessionModel]:
        return await db.get(GameSessionModel, session_id)

    async def update_session(self, db: AsyncSession, session_id: int, **kwargs: Any) -> bool:
        row = await db.get(GameSessionModel, session_id)
        if not row:
            return False
        for key, value in kwargs.items():
            if hasattr(row, key):
                setattr(row, key, value)
        return True

    async def list_saves(self, db: AsyncSession, limit: int = 50) -> List[Dict[str, Any]]:
        from sqlalchemy import select
        result = await db.execute(
            select(GameSessionModel)
            .order_by(GameSessionModel.updated_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "id":         r.id,
                "world_id":   r.world_id,
                "companion":  r.companion,
                "turn_count": r.turn_count,
                "time_of_day": r.time_of_day,
                "location":   r.location,
                "created_at": r.created_at.isoformat() if r.created_at else "",
                "updated_at": r.updated_at.isoformat() if r.updated_at else "",
            }
            for r in rows
        ]

    async def delete_save(self, db: AsyncSession, session_id: int) -> bool:
        row = await db.get(GameSessionModel, session_id)
        if not row:
            return False
        await db.delete(row)
        return True

    # -------------------------------------------------------------------------
    # Conversation messages
    # -------------------------------------------------------------------------

    async def add_message(
        self,
        db: AsyncSession,
        session_id: int,
        role: str,
        content: str,
        turn_number: int,
        visual_en: Optional[str] = None,
        tags_en: Optional[str] = None,
        companion: Optional[str] = None,
    ) -> ConversationMessageModel:
        import json as _json
        tags_str = _json.dumps(tags_en) if isinstance(tags_en, list) else (tags_en or "[]")
        row = ConversationMessageModel(
            session_id=session_id,
            role=role,
            content=content,
            turn_number=turn_number,
            visual_en=visual_en,
            tags_en=tags_str,
            companion=companion,
        )
        db.add(row)
        await db.flush()
        return row

    async def get_messages(
        self,
        db: AsyncSession,
        session_id: int,
        limit: int = 50,
        companion_filter: Optional[str] = None,
    ) -> List[ConversationMessageModel]:
        from sqlalchemy import select
        q = (
            select(ConversationMessageModel)
            .where(ConversationMessageModel.session_id == session_id)
            .order_by(ConversationMessageModel.turn_number.desc())
            .limit(limit)
        )
        if companion_filter:
            q = q.where(ConversationMessageModel.companion == companion_filter)
        result = await db.execute(q)
        rows = result.scalars().all()
        return list(reversed(rows))

    async def trim_messages(
        self, db: AsyncSession, session_id: int, keep_count: int = 50
    ) -> int:
        from sqlalchemy import select, delete
        count_result = await db.execute(
            select(func.count(ConversationMessageModel.id))
            .where(ConversationMessageModel.session_id == session_id)
        )
        total = count_result.scalar() or 0
        if total <= keep_count:
            return 0

        cutoff_result = await db.execute(
            select(ConversationMessageModel.id)
            .where(ConversationMessageModel.session_id == session_id)
            .order_by(ConversationMessageModel.turn_number.desc())
            .offset(keep_count)
            .limit(1)
        )
        cutoff_id = cutoff_result.scalar()
        if not cutoff_id:
            return 0

        deleted = await db.execute(
            delete(ConversationMessageModel)
            .where(ConversationMessageModel.session_id == session_id)
            .where(ConversationMessageModel.id <= cutoff_id)
        )
        trimmed = deleted.rowcount
        logger.debug("Trimmed %d old messages for session %d", trimmed, session_id)
        return trimmed

    # -------------------------------------------------------------------------
    # Memory entries
    # -------------------------------------------------------------------------

    async def add_memory(
        self,
        db: AsyncSession,
        session_id: int,
        type: str,
        content: str,
        turn_count: int,
        importance: int = 5,
        companion: str = "",
    ) -> MemoryEntryModel:
        row = MemoryEntryModel(
            session_id=session_id,
            type=type,
            content=content,
            turn_count=turn_count,
            importance=importance,
            companion=companion,
        )
        db.add(row)
        await db.flush()
        return row

    async def get_memories(
        self,
        db: AsyncSession,
        session_id: int,
        companion: Optional[str] = None,
        min_importance: int = 1,
        limit: int = 100,
        memory_type: Optional[str] = None,
    ) -> List[MemoryEntryModel]:
        from sqlalchemy import select
        q = (
            select(MemoryEntryModel)
            .where(MemoryEntryModel.session_id == session_id)
            .where(MemoryEntryModel.importance >= min_importance)
            .order_by(MemoryEntryModel.importance.desc(), MemoryEntryModel.turn_count.desc())
            .limit(limit)
        )
        if companion:
            q = q.where(MemoryEntryModel.companion == companion)
        result = await db.execute(q)
        return result.scalars().all()

    # -------------------------------------------------------------------------
    # Quest states
    # -------------------------------------------------------------------------

    async def save_quest_state(
        self,
        db: AsyncSession,
        session_id: int,
        quest_id: str,
        status: str,
        current_stage_id: Optional[str] = None,
        stage_data: Optional[str] = None,
        started_at: int = 0,
        completed_at: Optional[int] = None,
        pending_since_turn: Optional[int] = None,
        stage_entered_at: int = 0,
    ) -> QuestStateModel:
        from sqlalchemy import select
        result = await db.execute(
            select(QuestStateModel)
            .where(QuestStateModel.session_id == session_id)
            .where(QuestStateModel.quest_id == quest_id)
        )
        row = result.scalar_one_or_none()
        if row:
            row.status           = status
            row.current_stage_id = current_stage_id
            row.stage_data       = stage_data
            row.started_at       = started_at
            row.completed_at     = completed_at
            row.pending_since_turn = pending_since_turn
            row.stage_entered_at = stage_entered_at
        else:
            row = QuestStateModel(
                session_id=session_id,
                quest_id=quest_id,
                status=status,
                current_stage_id=current_stage_id,
                stage_data=stage_data,
                started_at=started_at,
                completed_at=completed_at,
                pending_since_turn=pending_since_turn,
                stage_entered_at=stage_entered_at,
            )
            db.add(row)
        await db.flush()
        return row

    async def get_all_quest_states(
        self, db: AsyncSession, session_id: int
    ) -> List[QuestStateModel]:
        from sqlalchemy import select
        result = await db.execute(
            select(QuestStateModel)
            .where(QuestStateModel.session_id == session_id)
        )
        return result.scalars().all()


    # -------------------------------------------------------------------------
    # v8: NPC Minds persistence
    # -------------------------------------------------------------------------

    async def save_npc_minds(
        self,
        db: AsyncSession,
        session_id: int,
        minds_dict: Dict[str, Any],
    ) -> None:
        """Save all NPCMind states for a session (upsert per npc_id)."""
        import json as _json
        from sqlalchemy import select

        for npc_id, mind_data in minds_dict.items():
            result = await db.execute(
                select(NpcMindModel)
                .where(NpcMindModel.session_id == session_id)
                .where(NpcMindModel.npc_id == npc_id)
            )
            row = result.scalar_one_or_none()
            mind_json = _json.dumps(mind_data, default=str)
            if row:
                row.mind_json = mind_json
                row.saved_at  = datetime.utcnow()
            else:
                row = NpcMindModel(
                    session_id=session_id,
                    npc_id=npc_id,
                    mind_json=mind_json,
                    saved_at=datetime.utcnow(),
                )
                db.add(row)

        await db.flush()
        logger.debug("[DB] Saved %d NPC minds for session %d", len(minds_dict), session_id)

    async def load_npc_minds(
        self,
        db: AsyncSession,
        session_id: int,
    ) -> Dict[str, Any]:
        """Load all NPCMind states for a session.

        Returns dict: {npc_id: {"mind_data": {...}, "saved_at": datetime}}
        """
        import json as _json
        from sqlalchemy import select

        result = await db.execute(
            select(NpcMindModel)
            .where(NpcMindModel.session_id == session_id)
        )
        rows = result.scalars().all()
        out: Dict[str, Any] = {}
        for row in rows:
            try:
                out[row.npc_id] = {
                    "mind_data": _json.loads(row.mind_json),
                    "saved_at": row.saved_at,
                }
            except Exception as e:
                logger.warning("[DB] Failed to load mind for %s: %s", row.npc_id, e)

        logger.debug("[DB] Loaded %d NPC minds for session %d", len(out), session_id)
        return out

    async def save_global_event_states(
        self,
        db: AsyncSession,
        session_id: int,
        events: list,
    ) -> None:
        """Save global event states into session JSON flags."""
        try:
            row = await db.get(GameSessionModel, session_id)
            if row:
                import json as _json
                state_data = _json.loads(row.state_json or "{}")
                state_data["_global_events"] = events
                row.state_json = _json.dumps(state_data)
        except Exception as e:
            logger.debug("save_global_event_states: %s", e)

    async def save_story_director_state(
        self,
        db: AsyncSession,
        session_id: int,
        completed_beats: list = None,
        beat_history: list = None,
    ) -> None:
        """Save story director state into session JSON flags."""
        try:
            row = await db.get(GameSessionModel, session_id)
            if row:
                import json as _json
                state_data = _json.loads(row.state_json or "{}")
                state_data["_story_director"] = {
                    "completed_beats": completed_beats or [],
                    "beat_history": beat_history or [],
                }
                row.state_json = _json.dumps(state_data)
        except Exception as e:
            logger.debug("save_story_director_state: %s", e)


# =============================================================================
# Singleton
# =============================================================================

_db_manager: Optional[DatabaseManager] = None


def get_db_manager(config: Optional[AppConfig] = None) -> DatabaseManager:
    """Get or create DatabaseManager singleton."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(config)
    return _db_manager


def reset_db_manager() -> None:
    """Reset singleton (for testing)."""
    global _db_manager
    _db_manager = None


def get_db_session(config: Optional[AppConfig] = None):
    """Shortcut context manager: async with get_db_session() as db: ..."""
    return get_db_manager(config).session()
