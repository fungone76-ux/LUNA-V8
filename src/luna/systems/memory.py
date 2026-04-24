"""Memory management system for long-term narrative memory.

Handles:
- Important facts storage (from LLM responses)
- History compression/summarization
- Context retrieval for LLM prompts
- Keyword-based and semantic search (optional)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import delete

from luna.core.database import DatabaseManager
from luna.core.models import ConversationMessage, MemoryEntry

def _deserialize_tags(tags_en) -> list:
    """Deserialize tags_en from DB — handles both list and JSON string."""
    if tags_en is None:
        return []
    if isinstance(tags_en, list):
        return tags_en
    if isinstance(tags_en, str):
        import json as _json
        try:
            result = _json.loads(tags_en)
            return result if isinstance(result, list) else []
        except Exception:
            return []
    return []


logger = logging.getLogger(__name__)


@dataclass
class MemorySearchResult:
    """Result from a memory search operation."""
    
    memory: MemoryEntry
    score: float
    match_type: str  # "keyword", "semantic", "importance"


class KeywordExtractor:
    """Extract keywords from text for matching."""
    
    # Common stop words in Italian and English
    STOP_WORDS: Set[str] = {
        # Italian
        "il", "lo", "la", "i", "gli", "le", "un", "uno", "una",
        "di", "del", "della", "dei", "delle", "a", "al", "alla",
        "ai", "alle", "da", "dal", "dalla", "dai", "dalle",
        "in", "nel", "nella", "nei", "nelle", "con", "su",
        "per", "tra", "fra", "è", "sono", "era", "erano",
        "ho", "hai", "ha", "abbiamo", "avete", "hanno",
        # English
        "the", "a", "an", "is", "are", "was", "were", "be",
        "been", "being", "have", "has", "had", "do", "does",
        "did", "will", "would", "could", "should", "may",
        "might", "must", "can", "this", "that", "these",
        "those", "i", "you", "he", "she", "it", "we", "they",
        "me", "him", "her", "us", "them", "my", "your", "his",
        "in", "on", "at", "to", "for", "of", "with", "about",
    }
    
    @classmethod
    def extract(cls, text: str, min_length: int = 3) -> Set[str]:
        """Extract significant keywords from text.
        
        Args:
            text: Input text
            min_length: Minimum keyword length
            
        Returns:
            Set of keywords
        """
        # Lowercase and extract words
        words = re.findall(r'\b[a-zA-Zàèéìòóù]+\b', text.lower())
        
        # Filter stop words and short words
        keywords = {
            w for w in words 
            if w not in cls.STOP_WORDS and len(w) >= min_length
        }
        
        return keywords
    
    @classmethod
    def calculate_similarity(cls, text1: str, text2: str) -> float:
        """Calculate keyword overlap similarity between two texts.
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Similarity score 0.0-1.0
        """
        keywords1 = cls.extract(text1)
        keywords2 = cls.extract(text2)
        
        if not keywords1 or not keywords2:
            return 0.0
        
        intersection = keywords1 & keywords2
        union = keywords1 | keywords2
        
        return len(intersection) / len(union)


class SemanticMemoryStore:
    """Optional semantic memory storage using ChromaDB."""
    
    def __init__(self, session_id: int, storage_path: Path) -> None:
        """Initialize semantic memory store.
        
        Args:
            session_id: Session identifier
            storage_path: Path for vector storage
        """
        self.session_id = session_id
        self.storage_path = storage_path
        self._client: Optional[Any] = None
        self._collection: Optional[Any] = None
        self._embedder: Optional[Any] = None
        self._available = False
        
    def initialize(self) -> bool:
        """Initialize ChromaDB and embedder.
        
        Returns:
            True if successfully initialized
        """
        try:
            import chromadb
            from chromadb.config import Settings
            from sentence_transformers import SentenceTransformer

            # Create storage directory
            db_path = self.storage_path / "vectors"
            db_path.mkdir(parents=True, exist_ok=True)

            # Initialize embedder (lightweight model)
            logger.info("Loading embedding model...")
            self._embedder = SentenceTransformer('all-MiniLM-L6-v2')

            # Initialize ChromaDB (telemetry disabled — posthog compat bug)
            self._client = chromadb.PersistentClient(
                path=str(db_path),
                settings=Settings(anonymized_telemetry=False),
            )
            
            # Get or create collection for this session
            collection_name = f"session_{self.session_id}"
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"session_id": self.session_id}
            )
            
            self._available = True
            # V4: Verify collection is working
            try:
                test_count = self._collection.count()
                logger.debug(f"[SemanticMemory] ✅ Initialized for session {self.session_id}")
                logger.debug(f"[SemanticMemory] 📊 Existing memories in collection: {test_count}")
            except Exception as e:
                logger.warning(f"[SemanticMemory] ⚠️ Warning: Could not verify collection: {e}")
            
            logger.info(f"Semantic memory initialized for session {self.session_id}")
            return True
            
        except ImportError as e:
            logger.warning(f"Semantic memory dependencies not available: {e}")
            logger.debug(f"[SemanticMemory] ❌ Dependencies not available: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize semantic memory: {e}")
            logger.warning(f"[SemanticMemory] ❌ Failed to initialize: {e}")
            return False
    
    @property
    def is_available(self) -> bool:
        """True if semantic search is available."""
        return self._available and self._collection is not None
    
    def add_memory(self, memory_id: str, content: str, metadata: Dict[str, Any], companion_name: Optional[str] = None) -> bool:
        """Add memory to semantic store.
        
        Args:
            memory_id: Unique memory identifier
            content: Memory content to embed
            metadata: Associated metadata
            companion_name: Optional companion name for memory isolation
            
        Returns:
            True if added successfully
        """
        if not self.is_available:
            return False
        
        try:
            embedding = self._embedder.encode(content).tolist()
            
            # V4.6: Add companion_name to metadata for isolation
            if companion_name:
                metadata = {**metadata, "companion": companion_name}
            
            self._collection.add(
                ids=[memory_id],
                embeddings=[embedding],
                documents=[content],
                metadatas=[metadata]
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add semantic memory: {e}")
            return False
    
    def search(self, query: str, k: int = 5, companion_name: Optional[str] = None) -> List[Tuple[str, float, str]]:
        """Search memories by semantic similarity.
        
        Args:
            query: Search query
            k: Number of results
            companion_name: Optional filter by companion for memory isolation (V4.6)
            
        Returns:
            List of (memory_id, score, content) tuples
        """
        if not self.is_available:
            return []
        
        try:
            query_embedding = self._embedder.encode(query).tolist()
            
            # V4.6: Request more results to allow for post-filtering
            fetch_k = k * 3 if companion_name and companion_name != "_solo_" else k
            
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=fetch_k,
                include=["documents", "distances", "metadatas"]
            )
            
            # Convert distances to similarity scores and filter by companion
            memories = []
            for i, memory_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i]
                content = results["documents"][0][i]
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                similarity = 1.0 - distance  # Convert to similarity
                
                # V4.6: Filter by companion if specified
                if companion_name and companion_name != "_solo_":
                    # Get companion info from metadata (can be 'companion' or 'npc')
                    mem_companion = metadata.get("companion") or metadata.get("npc")
                    # Include if: matches companion, is solo mode, or has no companion (legacy)
                    if mem_companion and mem_companion not in (companion_name, "_solo_"):
                        continue  # Skip memories from other companions
                
                memories.append((memory_id, similarity, content))
                
                # Stop once we have k results
                if len(memories) >= k:
                    break
            
            return memories
            
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []
    
    def delete_session(self) -> bool:
        """Delete all memories for this session.
        
        Returns:
            True if deleted successfully
        """
        if not self.is_available:
            return False
        
        try:
            self._client.delete_collection(f"session_{self.session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete semantic memories: {e}")
            return False
    
    def delete_all_sessions(self) -> bool:
        """Delete ALL semantic memory collections (for new game).
        
        V4.9: Critical for ensuring clean slate between games.
        
        Returns:
            True if deleted successfully
        """
        if not self.is_available:
            return False
        
        try:
            # Get all collections and delete those starting with "session_"
            collections = self._client.list_collections()
            deleted_count = 0
            for collection_name in collections:
                if collection_name.startswith("session_"):
                    try:
                        self._client.delete_collection(collection_name)
                        deleted_count += 1
                        logger.debug(f"[SemanticMemory] Deleted collection: {collection_name}")
                    except Exception as e:
                        logger.debug(f"[SemanticMemory] Note: Could not delete {collection_name}: {e}")
            
            logger.debug(f"[SemanticMemory] Deleted {deleted_count} session collections")
            return True
        except Exception as e:
            logger.error(f"Failed to delete all semantic memories: {e}")
            return False


class MemoryManager:
    """Manages long-term memories and conversation history.
    
    Features:
    - Store important facts from gameplay
    - Compress old history when too long
    - Retrieve relevant memories using keyword or semantic search
    - Hybrid scoring combining multiple match types
    """
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        session_id: int,
        history_limit: int = 50,
        enable_semantic: bool = False,
        storage_path: Optional[Path] = None,
        llm_manager = None,
    ) -> None:
        """Initialize memory manager.
        
        Args:
            db_manager: Database manager
            session_id: Current session ID
            history_limit: Max messages to keep in recent history
            enable_semantic: Enable semantic search (requires ChromaDB)
            storage_path: Path for vector storage (required if semantic enabled)
            llm_manager: Optional LLM manager for intelligent summarization
        """
        self.db = db_manager
        self.session_id = session_id
        self.history_limit = history_limit
        self.enable_semantic = enable_semantic
        self._llm_manager = llm_manager
        
        # Cache
        self._recent_messages: List[ConversationMessage] = []
        self._facts: List[MemoryEntry] = []
        self._loaded = False
        self._active_companion: Optional[str] = None
        
        # Keyword extractor
        self._keyword_extractor = KeywordExtractor()
        
        # Semantic store (optional)
        self._semantic_store: Optional[SemanticMemoryStore] = None
        if enable_semantic and storage_path:
            self._semantic_store = SemanticMemoryStore(session_id, storage_path)
    
    async def load(self, active_companion: Optional[str] = None) -> None:
        """Load memories from database.
        
        Args:
            active_companion: Filter memories for specific companion (isolation)
        """
        if self._loaded and self._active_companion == active_companion:
            return
        
        self._active_companion = active_companion
        
        # Initialize semantic store if enabled
        if self._semantic_store and not self._semantic_store.initialize():
            logger.warning("Failed to initialize semantic memory, falling back to keyword search")
            self.enable_semantic = False
        
        async with self.db.session() as db_session:
            # Load recent messages
            db_messages = await self.db.get_messages(
                db_session, self.session_id, limit=self.history_limit
            )
            
            self._recent_messages = [
                ConversationMessage(
                    role=msg.role,
                    content=msg.content,
                    turn_number=msg.turn_number,
                    visual_en=msg.visual_en,
                    tags_en=_deserialize_tags(msg.tags_en),
                    companion=getattr(msg, 'companion', None),
                )
                for msg in db_messages
            ]
            
            # V5: Filter messages by active companion for memory isolation
            if active_companion:
                self._recent_messages = [
                    msg for msg in self._recent_messages
                    if msg.companion == active_companion or msg.companion is None
                ]
                logger.debug(f"[Memory] Filtered for {active_companion}: {len(self._recent_messages)} messages")
            
            # Load facts
            db_memories = await self.db.get_memories(
                db_session, self.session_id, memory_type="fact", limit=100
            )
            
            self._facts = [
                MemoryEntry(
                    id=mem.id,
                    type="fact",
                    content=mem.content,
                    turn_count=mem.turn_number,
                    importance=mem.importance,
                    companion=getattr(mem, 'companion', ''),  # V5: Load companion
                )
                for mem in db_memories
            ]
            
            # V5: Filter facts by active companion for memory isolation
            if active_companion:
                self._facts = [
                    f for f in self._facts
                    if f.companion == active_companion or not f.companion
                ]
                logger.debug(f"[Memory] Filtered for {active_companion}: {len(self._facts)} facts")
            
            # Add to semantic store if available
            if self._semantic_store and self._semantic_store.is_available:
                for fact in self._facts:
                    if fact.id:  # Only add if has ID
                        meta: Dict[str, Any] = {
                            "turn": fact.turn_count,
                            "importance": fact.importance,
                            "type": fact.type,
                        }
                        if fact.companion:
                            meta["companion"] = fact.companion
                        self._semantic_store.add_memory(
                            memory_id=str(fact.id),
                            content=fact.content,
                            metadata=meta,
                        )
        
        self._loaded = True
        logger.debug(f"[Memory] ✅ Loaded: {len(self._recent_messages)} messages, {len(self._facts)} facts, semantic={self.enable_semantic}")
        logger.info(
            f"Memory loaded: {len(self._recent_messages)} messages, "
            f"{len(self._facts)} facts, semantic={self.enable_semantic}"
        )
    
    async def add_message(
        self,
        role: str,
        content: str,
        turn_number: int,
        visual_en: str = "",
        tags_en: Optional[List[str]] = None,
        companion_name: Optional[str] = None,
    ) -> None:
        """Add message to history.
        
        Args:
            role: user/assistant/system
            content: Message text
            turn_number: Game turn
            visual_en: Visual description
            tags_en: SD tags
            companion_name: Companion name for memory isolation (V4.6)
        """
        # Add to cache
        message = ConversationMessage(
            role=role,
            content=content,
            turn_number=turn_number,
            visual_en=visual_en,
            tags_en=tags_en or [],
            companion=companion_name,  # V4.9: Track companion for memory isolation
        )
        self._recent_messages.append(message)
        
        # Save to DB
        async with self.db.session() as db_session:
            await self.db.add_message(
                db_session,
                self.session_id,
                role,
                content,
                turn_number,
                visual_en,
                tags_en or [],
                companion_name or "",  # V4.9: Save companion for isolation
            )
        
        # V4.6: Also add to semantic store with companion metadata for isolation
        if self._semantic_store and self._semantic_store.is_available and companion_name:
            self._semantic_store.add_memory(
                memory_id=f"msg_{self.session_id}_{turn_number}_{role}_{len(self._recent_messages)}",
                content=f"[{role.upper()}]: {content}",
                metadata={
                    "turn": turn_number,
                    "role": role,
                    "type": "message",
                },
                companion_name=companion_name
            )
        
        # V4: Log message addition
        companion_tag = f" [{companion_name}]" if companion_name else ""
        logger.debug(f"[Memory] 📝 Added {role} message{companion_tag} (turn {turn_number}): {content[:50]}...")
        
        # Check if compression needed
        if len(self._recent_messages) > self.history_limit:
            await self._compress_history(self._llm_manager)
    
    async def add_fact(
        self,
        content: str,
        turn_number: int,
        importance: int = 5,
        associated_npc: Optional[str] = None,
        context_tags: Optional[List[str]] = None,
    ) -> None:
        """Store important fact.
        
        Args:
            content: Fact description
            turn_number: When it happened
            importance: 1-10 importance score
            associated_npc: NPC associated with this memory
            context_tags: Additional context tags (e.g., ["conflict", "gift"])
        """
        # Add to cache
        fact = MemoryEntry(
            type="fact",
            content=content,
            turn_count=turn_number,
            importance=importance,
            companion=associated_npc or "",
        )
        self._facts.append(fact)
        
        # Save to DB
        async with self.db.session() as db_session:
            mem = await self.db.add_memory(
                db_session,
                self.session_id,
                "fact",
                content,
                turn_number,
                importance,
                companion=associated_npc or "",
            )
            fact.id = mem.id
        
        # Add to semantic store if available
        if self._semantic_store and self._semantic_store.is_available and fact.id:
            metadata: Dict[str, Any] = {
                "turn": turn_number,
                "importance": importance,
                "type": "fact",
            }
            if associated_npc:
                metadata["npc"] = associated_npc
            if context_tags:
                metadata["tags"] = ",".join(context_tags)
            
            self._semantic_store.add_memory(
                memory_id=str(fact.id),
                content=content,
                metadata=metadata
            )
        
        logger.debug(f"[Memory] 💡 Added fact (importance={importance}): {content[:60]}...")
        logger.debug(f"Added fact (importance={importance}): {content[:50]}...")
    
    def get_recent_history(
        self, 
        limit: Optional[int] = None,
        companion_filter: Optional[str] = None,
    ) -> List[ConversationMessage]:
        """Get recent conversation history.
        
        Args:
            limit: Max messages to return
            companion_filter: Filter by companion for isolation
            
        Returns:
            List of recent messages
        """
        limit = limit or self.history_limit
        messages = self._recent_messages
        
        # V5: Filter by companion if specified
        if companion_filter:
            messages = [
                msg for msg in messages
                if msg.companion == companion_filter or msg.companion is None
            ]
        
        return messages[-limit:]
    
    def get_important_facts(
        self, 
        min_importance: int = 5, 
        limit: int = 20,
        companion_filter: Optional[str] = None,
    ) -> List[MemoryEntry]:
        """Get important facts sorted by importance.
        
        Args:
            min_importance: Minimum importance threshold
            limit: Maximum number of facts
            companion_filter: Filter by companion for isolation
            
        Returns:
            List of important facts
        """
        filtered = [f for f in self._facts if f.importance >= min_importance]
        
        # V5: Filter by companion if specified
        if companion_filter:
            filtered = [
                f for f in filtered
                if f.companion == companion_filter or not f.companion
            ]
        
        sorted_facts = sorted(filtered, key=lambda f: f.importance, reverse=True)
        return sorted_facts[:limit]
    
    def search_memories(
        self,
        query: str,
        k: int = 5,
        min_importance: int = 1,
        use_semantic: Optional[bool] = None,
        companion_filter: Optional[str] = None,
    ) -> List[MemorySearchResult]:
        """Search memories using keyword and/or semantic matching.
        
        Args:
            query: Search query
            k: Number of results to return
            min_importance: Minimum importance threshold
            use_semantic: Force semantic search (None = auto)
            companion_filter: Filter by companion name for isolation (V4.6)
            
        Returns:
            List of search results sorted by relevance
        """
        if not self._facts:
            return []
        
        # Determine search strategy
        use_semantic = use_semantic if use_semantic is not None else self.enable_semantic
        
        # Collect scores from different methods
        memory_scores: Dict[int, Tuple[MemoryEntry, float, str]] = {}
        
        # 1. Keyword-based search (always run)
        query_keywords = self._keyword_extractor.extract(query)
        
        for fact in self._facts:
            if fact.importance < min_importance:
                continue
            
            # Calculate keyword similarity
            keyword_sim = self._keyword_extractor.calculate_similarity(query, fact.content)
            
            # Boost for exact keyword matches
            fact_keywords = self._keyword_extractor.extract(fact.content)
            keyword_overlap = query_keywords & fact_keywords
            if keyword_overlap:
                keyword_sim += len(keyword_overlap) * 0.1  # Boost per matching keyword
            
            if keyword_sim > 0:
                memory_scores[fact.id or 0] = (fact, keyword_sim, "keyword")
        
        # 2. Semantic search (if available and requested)
        if use_semantic and self._semantic_store and self._semantic_store.is_available:
            semantic_results = self._semantic_store.search(query, k=k * 2, companion_name=companion_filter)
            
            for memory_id, score, _ in semantic_results:
                try:
                    fact_id = int(memory_id)
                    # Find the fact
                    for fact in self._facts:
                        if fact.id == fact_id and fact.importance >= min_importance:
                            # Combine scores if already present from keyword search
                            if fact_id in memory_scores:
                                existing_fact, existing_score, existing_type = memory_scores[fact_id]
                                # Weighted combination
                                combined_score = max(existing_score, score * 0.9) + 0.1
                                memory_scores[fact_id] = (fact, combined_score, "hybrid")
                            else:
                                memory_scores[fact_id] = (fact, score, "semantic")
                            break
                except ValueError:
                    continue
        
        # 3. Add importance-boosted facts (if we have few results)
        if len(memory_scores) < k:
            for fact in self._facts:
                if fact.id not in memory_scores and fact.importance >= min_importance + 3:
                    # Add with small score based on importance
                    importance_boost = (fact.importance - 5) / 100  # 0.03 to 0.05 boost
                    memory_scores[fact.id or 0] = (fact, importance_boost, "importance")
        
        # Sort by score and return top-k
        sorted_results = sorted(
            memory_scores.values(),
            key=lambda x: x[1],
            reverse=True
        )[:k]
        
        return [
            MemorySearchResult(memory=fact, score=score, match_type=match_type)
            for fact, score, match_type in sorted_results
        ]
    
    def get_memory_context(
        self,
        query: Optional[str] = None,
        max_facts: int = 10,
        min_importance: int = 4,
        companion_filter: Optional[str] = None,
    ) -> str:
        """Build memory context for LLM prompt.
        
        Args:
            query: Optional query to find relevant memories
            max_facts: Max facts to include
            min_importance: Minimum importance threshold
            companion_filter: Filter by companion for memory isolation (V4.6)
            
        Returns:
            Formatted memory context
        """
        lines = ["=== IMPORTANT MEMORY ==="]
        
        # V4.6: Debug logging with companion filter
        companion_tag = f" [companion={companion_filter}]" if companion_filter else ""
        query_preview = query[:30] if query else "(none)"
        logger.debug(f"[Memory] Query: '{query_preview}...' | Semantic: {self.enable_semantic} | Total facts: {len(self._facts)}{companion_tag}")
        
        if query and (self.enable_semantic or len(self._facts) > 20):
            # Use search for targeted retrieval with companion filter
            results = self.search_memories(query, k=max_facts, min_importance=min_importance, companion_filter=companion_filter)
            memories = [r.memory for r in results]
            logger.debug(f"[Memory] Search returned {len(memories)} results")
            for r in results[:3]:
                logger.debug(f"  - [{r.match_type}] score={r.score:.2f}: {r.memory.content[:40]}...")
        else:
            # Fall back to importance-based selection
            memories = self.get_important_facts(min_importance, max_facts, companion_filter=companion_filter)
            logger.debug(f"[Memory] Importance-based selection: {len(memories)} facts")
        
        if memories:
            for mem in memories:
                # Optional: add importance indicator for high-value memories
                prefix = ""
                if mem.importance >= 8:
                    prefix = "[IMPORTANT] "
                lines.append(f"• {prefix}{mem.content}")
        else:
            lines.append("(No significant memories yet)")
        
        lines.append("=== END MEMORY ===")
        
        return "\n".join(lines)
    
    async def _compress_history(self, llm_manager=None) -> None:
        """Compress old history into summary.
        
        V4: Now with optional LLM-based intelligent summarization.
        
        Args:
            llm_manager: Optional LLM manager for intelligent summarization
        """
        # V4.1: Lowered threshold for faster compression
        if len(self._recent_messages) < self.history_limit + 5:
            return
        
        # Get oldest messages to compress (5 instead of 10 for more aggressive compression)
        to_compress = self._recent_messages[:5]
        
        # Create a meaningful summary
        start_turn = to_compress[0].turn_number
        end_turn = to_compress[-1].turn_number
        
        # V4: Try LLM-based summary if available
        summary_text = None
        if llm_manager:
            try:
                summary_text = await self._generate_llm_summary(to_compress, llm_manager)
                logger.debug(f"[Memory] 🤖 LLM summary generated: {summary_text[:60]}...")
            except Exception as e:
                logger.warning(f"[Memory] LLM summary failed, falling back to keywords: {e}")
        
        # Fallback to keyword-based summary
        if not summary_text:
            all_content = " ".join([m.content for m in to_compress])
            keywords = self._keyword_extractor.extract(all_content)
            key_topics = ", ".join(list(keywords)[:5]) if keywords else "general conversation"
            
            summary_text = (
                f"Summary of turns {start_turn}-{end_turn}: "
                f"Discussed topics: {key_topics}. "
                f"({len(to_compress)} messages)"
            )
        
        # Add as summary memory with higher importance
        async with self.db.session() as db_session:
            mem = await self.db.add_memory(
                db_session,
                self.session_id,
                "fact",  # V4.1 FIX: Changed from "summary" to "fact" for long-term memory
                summary_text,
                end_turn,
                importance=6,  # V4: Higher importance for summaries
            )
            
            # V4.1 FIX: Add to facts list immediately for live use
            fact = MemoryEntry(
                id=mem.id,
                type="fact",
                content=summary_text,
                turn_count=end_turn,
                importance=6,
            )
            self._facts.append(fact)
            
            # Add to semantic store if available
            if self._semantic_store and self._semantic_store.is_available and mem.id:
                self._semantic_store.add_memory(
                    memory_id=str(mem.id),
                    content=summary_text,
                    metadata={
                        "turn": end_turn,
                        "importance": 6,
                        "type": "fact",
                    }
                )
        
        # V4.1 FIX: Actually remove compressed messages from memory!
        self._recent_messages = self._recent_messages[len(to_compress):]
        logger.debug(f"[Memory] 🗑️ Removed {len(to_compress)} compressed messages, {len(self._recent_messages)} remaining")
        logger.debug(f"[Memory] 💡 Added summary fact: {summary_text[:60]}...")
    
    async def _generate_llm_summary(
        self,
        messages: List[ConversationMessage],
        llm_manager,
    ) -> Optional[str]:
        """Generate intelligent summary using LLM.
        
        Args:
            messages: Messages to summarize
            llm_manager: LLM manager for generation
            
        Returns:
            Summary text or None if failed
        """
        if not llm_manager:
            return None
        
        # Build conversation text
        conversation_lines = []
        for msg in messages:
            role = "Player" if msg.role == "user" else "NPC"
            conversation_lines.append(f"{role}: {msg.content}")
        
        conversation_text = "\n".join(conversation_lines)
        
        # Create prompt for summary
        prompt = f"""Summarize the following conversation in 1-2 sentences.
Focus on:
- What happened
- Any decisions made
- Any promises or threats
- Relationship changes

Keep it concise but include specific details that would be important to remember later.

Conversation:
{conversation_text}

Summary:"""
        
        try:
            # Call LLM
            response = await llm_manager.generate_simple(
                prompt=prompt,
                max_tokens=100,
                temperature=0.3,  # Low temperature for consistent summaries
            )
            
            if response and response.strip():
                # V4.1: Filter out error messages from LLM
                error_phrases = [
                    "errore di comunicazione",
                    "error",
                    "unable to",
                    "cannot",
                    "non posso",
                    "mi dispiace",
                    "mi scusi",
                ]
                response_lower = response.lower()
                if any(phrase in response_lower for phrase in error_phrases):
                    logger.warning(f"[Memory] LLM returned error message, using fallback: {response[:50]}...")
                    return None
                return response.strip()
            
            return None
        except Exception as e:
            logger.warning(f"[Memory] LLM summary generation error: {e}")
            return None
        
        # Remove old messages from cache
        self._recent_messages = self._recent_messages[10:]
        
        # Delete old messages from DB
        async with self.db.session() as db_session:
            await self.db.delete_old_messages(
                db_session, self.session_id, self.history_limit
            )
        
        logger.debug(f"Compressed history: {summary_text}")
    
    async def get_memories_by_npc(self, npc_name: str) -> List[MemoryEntry]:
        """Get all memories associated with a specific NPC.
        
        Args:
            npc_name: Name of the NPC
            
        Returns:
            List of memories associated with the NPC
        """
        # For now, do simple keyword search on content
        # In future, could use semantic search with metadata filtering
        npc_lower = npc_name.lower()
        return [
            f for f in self._facts
            if npc_lower in f.content.lower()
        ]
    
    async def get_memories_by_tag(self, tag: str) -> List[MemoryEntry]:
        """Get memories by context tag.
        
        Args:
            tag: Context tag to search for
            
        Returns:
            List of matching memories
        """
        # Simple keyword search for now
        tag_lower = tag.lower()
        return [
            f for f in self._facts
            if tag_lower in f.content.lower()
        ]
    
    async def clear(self) -> None:
        """Clear all memories for this session (use with caution).
        
        V4.5: Used when starting a new game to ensure clean slate.
        """
        logger.debug(f"[Memory] Clearing all data for session {self.session_id}")
        
        # Clear in-memory caches
        self._recent_messages.clear()
        self._facts.clear()
        
        # Clear semantic store (ChromaDB) - V4.9: Delete ALL sessions for clean slate
        if self._semantic_store and self._semantic_store.is_available:
            try:
                self._semantic_store.delete_all_sessions()
                logger.debug(f"[Memory] All semantic memory cleared")
            except Exception as e:
                logger.debug(f"[Memory] Note: Could not clear semantic memory: {e}")
        
        # Clear database records (SQLite)
        try:
            async with self.db.session() as db_session:
                # Delete messages
                from luna.core.database import ConversationMessageModel
                await db_session.execute(
                    delete(ConversationMessageModel).where(
                        ConversationMessageModel.session_id == self.session_id
                    )
                )
                
                # Delete facts
                from luna.core.database import MemoryEntryModel
                await db_session.execute(
                    delete(MemoryEntryModel).where(
                        MemoryEntryModel.session_id == self.session_id
                    )
                )
                
                await db_session.commit()
                logger.debug(f"[Memory] Database records cleared")
        except Exception as e:
            logger.warning(f"[Memory] Warning: Could not clear database: {e}")
        
        self._loaded = False
        logger.debug(f"[Memory] All memory cleared for session {self.session_id}")
    
    @property
    def stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        return {
            "recent_messages": len(self._recent_messages),
            "total_facts": len(self._facts),
            "high_importance_facts": len([f for f in self._facts if f.importance >= 7]),
            "semantic_enabled": self.enable_semantic,
            "semantic_available": (
                self._semantic_store.is_available if self._semantic_store else False
            ),
        }
