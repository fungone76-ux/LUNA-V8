"""Luna RPG v8 - Poker Game Handler.

Texas Hold'em poker with strip progression.
v8: Uses engine_v2 for real poker (no more random.choice).
    Player sees their cards, can fold/call/raise/all-in each street.
    RiskAgent handles NPC AI decisions.
    Strip events at key levels use LLM-generated dialogue.
"""
from __future__ import annotations

import logging
import random
import re
from typing import TYPE_CHECKING, Dict, List, Optional, Any, Tuple

if TYPE_CHECKING:
    from luna.core.models import GameState, TurnResult
    from luna.core.engine import GameEngine

from .engine_v2 import GameState as PokerState, GameConfig, Player
from .agents import RiskAgent, AgentContext, RiskProfile, DEFAULT_PROFILES
from .simple_strip_manager import SimpleStripManager
from .poker_renderer import PokerRenderer

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Intent parsing: "vedo" → call, "rilancio 400" → raise 400, etc.
# ─────────────────────────────────────────────────────────────────────────────

_FOLD_RE      = re.compile(r"^(fold|mi ritiro|passo|abbandono|esco dal pot)$", re.I)
_CALL_RE      = re.compile(r"^(call|vedo|seguo|chiamo)$", re.I)
_CHECK_RE     = re.compile(r"^(check|passo|batto|stacco)$", re.I)
_ALLIN_RE     = re.compile(r"^(all.?in|tutto|vado tutto|all in)$", re.I)
_BET_RE       = re.compile(r"^(?:punto|bet)\s+(\d+)$", re.I)
_RAISE_RE     = re.compile(r"^(?:rilancio|raise|alzo|reraise)\s+(\d+)$", re.I)
_EXIT_RE      = re.compile(r"^(esci|esci dal poker|abbandona|quit|exit)$", re.I)
# /d [@Nome] testo  — dialogue channel
_DIALOGUE_RE  = re.compile(r"^/d(?:\s+@(\w+))?\s+(.+)$", re.I | re.S)

# Strip levels that use LLM-generated dialogue (the important ones)
_LLM_STRIP_LEVELS = {3, 4, 5}

# Max history entries kept in memory (12 exchanges ≈ 6 turns each side)
_DIALOGUE_HISTORY_MAX = 12

# v8: AI strip personality modifiers per level
_STRIP_PERSONALITY_MODIFIERS: Dict[int, Dict[str, float]] = {
    0: {},
    1: {},
    2: {"aggression": -0.05},
    3: {"aggression": -0.15, "bluff": -0.05},    # embarrassed → plays worse
    4: {"aggression": -0.20, "bluff": -0.10},
    5: {"aggression": +0.25, "bluff": +0.15},     # desperate → aggressive
}

_NEXT_HAND_READY_NOTE = (
    "\n_Nuova mano pronta. L'anteprima strip resta visibile: puoi continuare a giocare._\n"
)


def parse_poker_action(text: str) -> Optional[Dict[str, Any]]:
    """Parse player text into a poker action dict.
    Returns None if not a valid poker action.
    """
    t = text.strip()
    if _EXIT_RE.match(t):
        return {"action": "exit"}
    if _FOLD_RE.match(t):
        return {"action": "fold"}
    if _CALL_RE.match(t):
        return {"action": "call"}
    if _CHECK_RE.match(t):
        return {"action": "check"}
    if _ALLIN_RE.match(t):
        return {"action": "allin"}
    m = _BET_RE.match(t)
    if m:
        return {"action": "bet", "amount": int(m.group(1))}
    m = _RAISE_RE.match(t)
    if m:
        return {"action": "raise", "amount": int(m.group(1))}
    return None


def parse_poker_input(text: str) -> Dict[str, Any]:
    """Unified parser: returns dict with 'kind' key.

    Kinds:
      {"kind": "system",   "action": "exit"}
      {"kind": "poker",    "action": ..., ...}
      {"kind": "dialogue", "target": str|None, "text": str}
      {"kind": "unknown"}   — unrecognized, caller shows hint

    Priority: system > dialogue (/d prefix) > poker > unknown.
    Input is sanitized (max 280 chars) before parsing.
    """
    t = text.strip()[:280]

    # System commands (exit) — highest priority
    if _EXIT_RE.match(t):
        return {"kind": "system", "action": "exit"}

    # Dialogue channel: /d [@Nome] testo
    m = _DIALOGUE_RE.match(t)
    if m:
        target = m.group(1)   # None if no @Nome
        msg    = m.group(2).strip()
        return {"kind": "dialogue", "target": target, "text": msg}

    # Poker actions
    action = parse_poker_action(t)
    if action:
        return {"kind": "poker", **action}

    return {"kind": "unknown"}


class PokerGame:
    """Texas Hold'em poker mini-game with strip progression.

    v8 changes vs v7:
    - Uses engine_v2 for real poker (was random.choice)
    - Player sees their hole cards and board
    - Player actions: fold/call/check/bet/raise/allin
    - RiskAgent with Monte Carlo equity for NPC AI
    - AI personality changes after each strip level
    - Strip events lvl 3-5 use NarrativeEngine for dialogue (if available)
    """

    def __init__(
        self,
        engine: "GameEngine",
        companion_names: List[str],
        initial_stack: int = 2000,
    ):
        self.engine = engine
        self.companion_names = companion_names
        self.initial_stack = initial_stack

        # Strip managers
        self.companions: Dict[str, Dict[str, Any]] = {}
        for name in companion_names:
            profile = DEFAULT_PROFILES.get(name, DEFAULT_PROFILES["_AI_"])
            self.companions[name] = {
                "strip_level": 0,
                "eliminated": False,
                "strip_manager": SimpleStripManager(name, initial_stack),
                "profile": RiskProfile(aggression=profile.aggression, bluff=profile.bluff),
                "prev_stack": initial_stack,   # tracks stack between hands for strip detection
            }

        # Build engine_v2 players list: [Player(user), Player(npc1), ...]
        players: List[Player] = [
            Player(name="Player", is_user=True, stack=initial_stack)
        ]
        self._npc_player_indices: Dict[str, int] = {}
        for i, name in enumerate(companion_names):
            players.append(Player(name=name, stack=initial_stack))
            self._npc_player_indices[name] = i + 1   # 0 = user

        cfg = GameConfig(
            small_blind=initial_stack // 40,
            big_blind=initial_stack // 20,
            initial_stack=initial_stack,
        )
        self._poker = PokerState(players=players, cfg=cfg)
        self._poker.rotate_dealer()

        # Build AI agents
        self._agents: Dict[str, RiskAgent] = {}
        for name in companion_names:
            profile = self.companions[name]["profile"]
            ctx = AgentContext(name=name, profile=profile, rng=random.Random())
            self._agents[name] = RiskAgent(ctx)

        self.hand_number = 0
        self.game_active = True
        self._waiting_for_player = False
        self._pending_custom_focus: Optional[Dict[str, Any]] = None
        self._renderer = PokerRenderer()
        # Dialogue history for /d channel (shared across all NPC targets)
        self._dialog_history: List[Dict[str, Any]] = []

    # =========================================================================
    # Start
    # =========================================================================

    async def start_game(self, game_state: "GameState") -> "TurnResult":
        """Start poker game and deal first hand."""
        from luna.core.models import TurnResult

        players_text = (
            f"Tu vs {self.companion_names[0]}"
            if len(self.companion_names) == 1
            else f"Tu vs {', '.join(self.companion_names)}"
        )

        narrative = (
            f"**POKER — Texas Hold'em**\n\n"
            f"Giocatori: {players_text}\n"
            f"Stack iniziale: {self.initial_stack:,} chips ciascuno\n"
            f"Blinds: {self._poker.cfg.small_blind}/{self._poker.cfg.big_blind}\n\n"
            f"*Comandi: `vedo` `fold` `check` `punto X` `rilancio X` `all-in` `esci`*\n\n"
        )

        for name in self.companion_names:
            intro = self.companions[name]["strip_manager"].get_hot_dialogue(0)
            narrative += f"{name}: \"{intro}\"\n"

        # Deal first hand
        hand_text, image_path = await self._deal_new_hand(game_state)
        narrative += "\n" + hand_text

        game_state.flags["poker_active"] = True
        game_state.flags["poker_game"] = self.to_dict()

        logger.info("[Poker] Game started: %s", players_text)
        return TurnResult(text=narrative, image_path=image_path, turn_number=game_state.turn_count)

    # =========================================================================
    # Main action handler (called every turn while poker is active)
    # =========================================================================

    async def process_action(
        self,
        player_input: str,
        game_state: "GameState",
    ) -> "TurnResult":
        """Process one player action and advance the hand.

        Supports three input kinds:
          - Poker action  (fold/call/check/bet/raise/allin)
          - Dialogue      (/d [@Nome] messaggio) — doesn't advance game state
          - System        (esci) — ends game
        """
        from luna.core.models import TurnResult

        # If we are waiting for a custom focus input (old_level == 5)
        if self._pending_custom_focus:
            npc_name = self._pending_custom_focus["npc_name"]
            level = self._pending_custom_focus["level"]
            focus_text = player_input.strip()
            
            # Use /d input naturally if they typed it
            if focus_text.startswith("/d"):
                m = _DIALOGUE_RE.match(focus_text)
                if m: focus_text = m.group(2).strip()

            self._pending_custom_focus = None
            
            comp = self.companions.get(npc_name)
            if comp:
                base_desc = comp["strip_manager"].get_visual_description(level)
            else:
                base_desc = "completely naked"

            # Costruisci una prompt visuale forte che combini il livello 5 e il focus richiesto dall'utente
            visual_en = f"{base_desc}, extreme detailed close-up focus on {focus_text}, centered on {focus_text}"
            
            narrative = f"Hai chiesto di concentrarti su: **{focus_text}**.\n"
            
            img, vid = await self._generate_strip_media(npc_name, visual_en, level, game_state)
            image_path = img
            if img:
                game_state.flags.setdefault("poker_strip_images", []).append({
                    "path": img,
                    "npc_name": npc_name,
                    "level": level,
                })
            
            # Deal next hand
            hand_text, hand_image = await self._deal_new_hand(game_state)
            narrative += "\n" + hand_text
            if img:
                narrative += _NEXT_HAND_READY_NOTE
            
            if hand_image and not img:
                image_path = hand_image
                
            game_state.flags["poker_game"] = self.to_dict()
            return TurnResult(
                text=narrative, image_path=image_path, turn_number=game_state.turn_count
            )

        parsed = parse_poker_input(player_input)
        kind   = parsed["kind"]

        # System command
        if kind == "system":
            return await self.end_game(game_state, "Hai abbandonato la partita.")

        # Dialogue channel — reply without advancing poker state
        if kind == "dialogue":
            return await self._handle_dialogue_turn(
                target=parsed.get("target"),
                text=parsed["text"],
                game_state=game_state,
            )

        # Unknown input
        if kind == "unknown":
            legal = self._poker.legal_actions()
            hints = self._legal_hints(legal)
            return TurnResult(
                text=(
                    f"_Azione non riconosciuta. {hints}_\n"
                    f"_Per parlare con un NPC usa `/d messaggio` o `/d @Nome messaggio`._\n\n"
                    f"{self._board_summary()}"
                ),
                turn_number=game_state.turn_count,
            )

        # Poker action
        action = {k: v for k, v in parsed.items() if k != "kind"}

        # Apply player action to engine
        narrative, image_path, strip_events = await self._apply_player_action(
            action, game_state
        )

        # If hand ended → summarize + strip events + deal next hand
        if self._poker.street == "showdown":
            narrative += await self._resolve_showdown(game_state)
            strip_events += self._check_strip_after_hand(game_state)

            # Check if any NPC just hit the custom focus trigger (old_level == 5 and lost)
            focus_event = next((e for e in strip_events if e.get("old_level") == 5 and e.get("lost_hand")), None)
            if focus_event:
                self._pending_custom_focus = {
                    "npc_name": focus_event["npc_name"],
                    "level": 5
                }
                
                narrative += f"\n**{focus_event['npc_name']} ha perso ancora!**\n"
                narrative += "_Cosa vuoi vedere in particolare ora? (Scrivi es. 'i piedi', 'le mani', 'ritratto', ecc.)_\n"
                
                game_state.flags["poker_game"] = self.to_dict()
                return TurnResult(
                    text=narrative, image_path=None, turn_number=game_state.turn_count
                )

            # Process strip events
            strip_text, strip_image = await self._process_strip_events(
                strip_events, game_state
            )
            narrative += strip_text
            if strip_image:
                image_path = strip_image

            # Check if game over
            if self._is_game_over():
                return await self.end_game(game_state, "Fine della partita!")

            # Deal next hand
            hand_text, hand_image = await self._deal_new_hand(game_state)
            narrative += "\n" + hand_text
            if strip_image:
                narrative += _NEXT_HAND_READY_NOTE
            # Keep strip image in preview when a strip event happened.
            if hand_image and not strip_image:
                image_path = hand_image
        else:
            # Hand still in progress: run NPC actions if it's their turn
            npc_text, npc_strip, npc_image = await self._run_npc_actions(game_state)
            narrative += npc_text
            if npc_image:
                image_path = npc_image

            # If after NPC actions the hand ended → showdown
            if self._poker.street == "showdown":
                narrative += await self._resolve_showdown(game_state)
                all_strip = npc_strip + self._check_strip_after_hand(game_state)

                # Check if any NPC just hit the custom focus trigger
                focus_event = next((e for e in all_strip if e.get("old_level") == 5 and e.get("lost_hand")), None)
                if focus_event:
                    self._pending_custom_focus = {
                        "npc_name": focus_event["npc_name"],
                        "level": 5
                    }
                    narrative += f"\n**{focus_event['npc_name']} ha perso ancora!**\n"
                    narrative += "_Cosa vuoi vedere in particolare ora? (Scrivi es. 'i piedi', 'le mani', 'ritratto', ecc.)_\n"
                    
                    game_state.flags["poker_game"] = self.to_dict()
                    return TurnResult(
                        text=narrative, image_path=None, turn_number=game_state.turn_count
                    )

                strip_text, strip_image = await self._process_strip_events(
                    all_strip, game_state
                )
                narrative += strip_text
                if strip_image:
                    image_path = strip_image

                if self._is_game_over():
                    return await self.end_game(game_state, "Fine della partita!")

                hand_text, hand_image = await self._deal_new_hand(game_state)
                narrative += "\n" + hand_text
                if strip_image:
                    narrative += _NEXT_HAND_READY_NOTE
                # Keep strip image in preview when a strip event happened.
                if hand_image and not strip_image:
                    image_path = hand_image
            else:
                narrative += f"\n{self._board_summary()}"

        game_state.flags["poker_game"] = self.to_dict()
        return TurnResult(
            text=narrative, image_path=image_path, turn_number=game_state.turn_count
        )

    # =========================================================================
    # Internal engine helpers
    # =========================================================================

    def _render_table(self, reveal_npc: bool = False) -> Optional[str]:
        """Render the current poker table to an image and return its path."""
        try:
            state = self._poker.public_state()
            return self._renderer.render(
                public_state=state,
                hand_number=self.hand_number,
                reveal_npc_cards=reveal_npc,
            )
        except Exception as exc:
            logger.warning("[Poker] Table render failed: %s", exc)
            return None

    async def _deal_new_hand(self, game_state: "GameState") -> Tuple[str, Optional[str]]:
        """Deal a new hand. Returns (narrative_text, image_path)."""
        self.hand_number += 1
        self._poker.rotate_dealer()
        self._poker.start_hand()

        # Let NPCs act first if they're before the player
        npc_text, _, _ = await self._run_npc_actions(game_state)

        user_idx = 0
        me = self._poker.players[user_idx]
        hole = " ".join(self._format_card(c) for c in me.hole)

        blind_info = (
            f"SB: {self._poker.cfg.small_blind} | BB: {self._poker.cfg.big_blind}"
        )
        pot = sum(p.amount for p in self._poker.pots) + sum(
            p.committed_in_street for p in self._poker.players
        )

        # Strip progress per NPC
        strip_status = ""
        for name in self.companion_names:
            npc_idx = self._npc_player_indices[name]
            npc_stack = self._poker.players[npc_idx].stack
            pct = int((npc_stack / self.initial_stack) * 100)
            lvl = self.companions[name]["strip_level"]
            if lvl < 5:
                strip_status += (
                    f"{name}: {npc_stack} chips ({pct}%) — strip lvl {lvl}/5 "
                    f"[prossimo al prossimo colpo perso]\n"
                )
            else:
                strip_status += f"{name}: {npc_stack} chips ({pct}%) — strip lvl {lvl}/5\n"

        text = (
            f"\n**{'─' * 30}**\n"
            f"**Mano #{self.hand_number}** | {blind_info}\n"
            f"Le tue carte: **{hole}**\n"
            f"Pot: {pot} chips | {strip_status.strip()}\n"
        )

        if npc_text:
            text += npc_text

        legal = self._poker.legal_actions()
        text += f"\n{self._legal_hints(legal)}\n"

        # Render table image showing player's hole cards
        image_path = self._render_table(reveal_npc=False)
        return text, image_path

    async def _apply_player_action(
        self,
        action: Dict[str, Any],
        game_state: "GameState",
    ) -> Tuple[str, Optional[str], List[Dict]]:
        """Apply player action to engine. Returns (text, image_path, strip_events)."""
        act = action["action"]
        legal = self._poker.legal_actions()
        image_path = None
        strip_events: List[Dict] = []

        action_names = {
            "fold": "Hai fatto **fold**",
            "call": "Hai **visto**",
            "check": "Hai fatto **check**",
            "allin": "Sei andato **all-in**",
            "bet":   f"Hai **puntato {action.get('amount', 0)}**",
            "raise": f"Hai **rilanciato a {action.get('amount', 0)}**",
        }

        if act == "fold" and legal.get("fold"):
            self._poker.act_fold()
            text = action_names["fold"] + "\n"
        elif act == "call" and legal.get("call"):
            self._poker.act_call()
            text = action_names["call"] + "\n"
        elif act == "check" and legal.get("check"):
            self._poker.act_check()
            text = action_names["check"] + "\n"
        elif act == "allin" and legal.get("allin"):
            self._poker.act_allin()
            text = action_names["allin"] + "\n"
        elif act == "bet" and legal.get("bet"):
            amount = max(action.get("amount", self._poker.cfg.big_blind),
                         self._poker.cfg.big_blind)
            self._poker.act_bet(amount)
            text = f"Hai **puntato {amount}**\n"
        elif act == "raise" and legal.get("raise"):
            amount = action.get("amount", self._poker.current_bet + self._poker.min_raise_size)
            self._poker.act_raise(amount)
            text = f"Hai **rilanciato a {amount}**\n"
        else:
            legal_hints = self._legal_hints(legal)
            text = f"_Azione non valida in questo momento. {legal_hints}_\n"
            return text, image_path, strip_events

        self._poker.settle_and_next_street_if_needed()
        street_text = self._street_header()
        if street_text:
            text += street_text

        # Render updated table after player action
        image_path = self._render_table(reveal_npc=(self._poker.street == "showdown"))
        return text, image_path, strip_events

    async def _run_npc_actions(
        self, game_state: "GameState"
    ) -> Tuple[str, List[Dict], Optional[str]]:
        """Run all NPC actions until it's the player's turn or hand ends."""
        text = ""
        strip_events: List[Dict] = []
        image_path = None
        user_idx = 0

        iterations = 0
        while (
            self._poker.street not in ("showdown", "init")
            and self._poker.to_act is not None
            and self._poker.to_act != user_idx
            and iterations < 20  # safety cap
        ):
            iterations += 1
            npc_idx = self._poker.to_act
            npc = self._poker.players[npc_idx]
            if npc.folded or npc.all_in:
                self._poker._advance_turn()
                self._poker.settle_and_next_street_if_needed()
                continue

            npc_name = npc.name
            agent = self._agents.get(npc_name)
            if not agent:
                self._poker.act_fold()
                continue

            decision = agent.decide(self._poker, npc_idx)
            act = decision.get("action", "fold")

            action_desc = self._apply_npc_action(npc_name, act, decision)
            text += action_desc

            self._poker.settle_and_next_street_if_needed()
            street_text = self._street_header()
            if street_text:
                text += street_text

        return text, strip_events, image_path

    def _apply_npc_action(
        self, npc_name: str, act: str, decision: Dict
    ) -> str:
        """Apply NPC action. Returns description string."""
        npc_idx = self._poker.to_act
        if npc_idx is None:
            return ""

        if act == "fold":
            self._poker.act_fold()
            return f"♠️ {npc_name} decide di fare **Fold (Passare)** buttando via le carte.\n"
        elif act == "call":
            self._poker.act_call()
            return f"♠️ {npc_name} batte le fiches sul tavolo e fa **Call (Vedere)** per pareggiare la tua puntata.\n"
        elif act == "check":
            self._poker.act_check()
            return f"♠️ {npc_name} dà due leggeri colpetti sul panno verde: **Check (Bussare)**.\n"
        elif act == "allin":
            self._poker.act_allin()
            return f"♠️ {npc_name} ti guarda dritta negli occhi e spinge avanti tutte le sue fiches: **ALL-IN**!\n"
        elif act == "bet":
            amount = decision.get("amount", self._poker.cfg.big_blind)
            self._poker.act_bet(amount)
            return f"♠️ {npc_name} prende l'iniziativa e sceglie di **Puntare (Bet)** **{amount} chips**.\n"
        elif act == "raise":
            amount = decision.get("amount",
                                  self._poker.current_bet + self._poker.min_raise_size)
            self._poker.act_raise(amount)
            return f"♠️ {npc_name} decide di alzare la posta e fa **Raise (Rilancio)** fino a **{amount} chips**!\n"
        else:
            self._poker.act_fold()
            return f"♠️ {npc_name} guarda la sua mano, sospira e fa **Fold (Passare)**.\n"

    async def _resolve_showdown(self, game_state: "GameState") -> str:
        """Run showdown, distribute pot, return summary."""
        winners, payouts = self._poker.showdown()
        text = "\n🌟 **— SHOWDOWN (Rivelazione delle carte) —** 🌟\n\n"

        # Show all hands
        for i, p in enumerate(self._poker.players):
            if p.hole:
                cards = " ".join(self._format_card(c) for c in p.hole)
                if p.name == "Player":
                    text += f"🃏 **Le tue carte**: {cards}\n"
                else:
                    text += f"🃏 **{p.name} gira le sue carte mostrando**: {cards}\n"

        if self._poker.board:
            board = " ".join(self._format_card(c) for c in self._poker.board)
            text += f"\n🎲 **Carte sul tavolo (Board)**: {board}\n"

        text += "\n"
        for w_idx in winners:
            winner_name = self._poker.players[w_idx].name
            won = payouts.get(w_idx, 0)
            if winner_name == "Player":
                text += f"🎉 **CONGRATULAZIONI! Hai vinto la mano e intascato {won:,} chips!** 🎉\n"
            else:
                text += f"💔 **{winner_name} ha vinto la mano portandosi via {won:,} chips...** 💔\n"

        text += "\n**💰 Stack Attuale:**\n"
        for p in self._poker.players:
            text += f"  - {p.name}: {p.stack:,} chips\n"

        return text

    def _check_strip_after_hand(self, game_state: "GameState") -> List[Dict]:
        """Advance strip by one level for each NPC that lost chips this hand."""
        strip_events = []
        for name, comp in self.companions.items():
            if comp["eliminated"]:
                continue
            npc_idx = self._npc_player_indices[name]
            current_stack = self._poker.players[npc_idx].stack
            prev_stack    = comp["prev_stack"]
            old_level = comp["strip_level"]
            lost_hand = current_stack < prev_stack
            leveled = lost_hand and old_level <= 5
            new_level = min(5, old_level + 1) if lost_hand else old_level
            # Always update prev_stack for next hand
            comp["prev_stack"] = current_stack

            if lost_hand:
                comp["strip_level"] = new_level
                strip_events.append({
                    "npc_name": name,
                    "old_level": old_level,
                    "new_level": new_level,
                    "current_stack": current_stack,
                    "lost_hand": True,
                })
                # Modify AI personality after strip
                modifier = _STRIP_PERSONALITY_MODIFIERS.get(new_level, {})
                if modifier and leveled and old_level < 5:
                    prof = comp["profile"]
                    prof.aggression = max(0.1, min(0.9,
                        prof.aggression + modifier.get("aggression", 0)
                    ))
                    prof.bluff = max(0.0, min(0.5,
                        prof.bluff + modifier.get("bluff", 0)
                    ))
                    # Rebuild agent with new profile
                    ctx = AgentContext(
                        name=name, profile=prof, rng=random.Random()
                    )
                    self._agents[name] = RiskAgent(ctx)
                    logger.info(
                        "[Poker] %s strip lvl %d → AI: aggression=%.2f bluff=%.2f",
                        name, new_level, prof.aggression, prof.bluff,
                    )

            # Check elimination
            if current_stack <= 0 and not comp["eliminated"]:
                comp["eliminated"] = True
                comp["strip_level"] = 5
                strip_events.append({
                    "npc_name": name,
                    "old_level": old_level if leveled else comp["strip_level"],
                    "new_level": 5,
                    "current_stack": 0,
                    "eliminated": True,
                    "lost_hand": True
                })

        return strip_events

    # =========================================================================
    # Dialogue channel (/d command)
    # =========================================================================

    async def _handle_dialogue_turn(
        self,
        target: Optional[str],
        text: str,
        game_state: "GameState",
    ) -> "TurnResult":
        """Handle a /d dialogue input without advancing poker state."""
        from luna.core.models import TurnResult

        # Resolve target NPC
        if target:
            # Match by name (case-insensitive)
            npc = next(
                (n for n in self.companion_names if n.lower() == target.lower()),
                self.companion_names[0],
            )
        else:
            npc = self.companion_names[0]

        reply = await self._generate_poker_dialogue_reply(npc, text, game_state)

        # Persist (game state unchanged, but save history snapshot)
        game_state.flags["poker_game"] = self.to_dict()

        return TurnResult(
            text=f"[DIALOGO] {npc}: \"{reply}\"",
            turn_number=game_state.turn_count,
        )

    async def _generate_poker_dialogue_reply(
        self,
        npc_name: str,
        user_text: str,
        game_state: "GameState",
    ) -> str:
        """Generate NPC poker-table dialogue reply (LLM + deterministic fallback)."""
        affinity    = game_state.affinity.get(npc_name, 50)
        comp        = self.companions.get(npc_name, {})
        strip_level = comp.get("strip_level", 0)
        npc_idx     = self._npc_player_indices.get(npc_name, 1)
        npc_stack   = self._poker.players[npc_idx].stack if npc_idx < len(self._poker.players) else 0

        street = self._poker.street.upper()
        board  = (
            " ".join(self._format_card(c) for c in self._poker.board)
            if self._poker.board else "nessun board"
        )

        # Build recent history snippet (last 6 entries)
        history_snippet = ""
        for entry in self._dialog_history[-6:]:
            speaker = "Tu" if entry["role"] == "user" else entry.get("npc", npc_name)
            history_snippet += f"{speaker}: {entry['text']}\n"

        # Record player message
        self._dialog_history.append({"role": "user", "text": user_text})
        if len(self._dialog_history) > _DIALOGUE_HISTORY_MAX:
            self._dialog_history = self._dialog_history[-_DIALOGUE_HISTORY_MAX:]

        if self.engine.llm_manager:
            try:
                system = (
                    f"Sei {npc_name}, una ragazza in una partita di strip poker. "
                    f"Strip level attuale: {strip_level}/5. "
                    f"Stack: {npc_stack} chips. Street: {street}. Board: {board}. "
                    f"Affinità con il giocatore: {affinity}/100. "
                    "Rispondi in italiano con una battuta breve (max 25 parole), "
                    "in carattere, naturale durante una partita. "
                    "Rispondi SOLO con la battuta, senza prefissi o virgolette."
                )
                user_prompt = (
                    f"Storico recente:\n{history_snippet}\n"
                    f"Giocatore: {user_text}"
                ) if history_snippet else user_text

                result, _ = await self.engine.llm_manager.generate(
                    system_prompt=system,
                    user_input=user_prompt,
                    history=[],
                    json_mode=False,
                    companion_name=npc_name,
                )
                reply = (getattr(result, "text", "") or "").strip().strip('"')[:220]
                if reply:
                    self._dialog_history.append(
                        {"role": "npc", "npc": npc_name, "text": reply}
                    )
                    return reply
            except Exception as exc:
                logger.warning("[Poker] Dialogue LLM failed: %s", exc)

        # Deterministic fallback
        reply = self._dialogue_fallback(npc_name, strip_level, affinity)
        self._dialog_history.append({"role": "npc", "npc": npc_name, "text": reply})
        return reply

    def _dialogue_fallback(
        self, npc_name: str, strip_level: int, affinity: int
    ) -> str:
        """Deterministic fallback replies based on context."""
        if strip_level >= 4:
            pool = (
                [
                    "Non distrarmi ora... anche se ci tengo.",
                    "Concentrati sul gioco, non su di me.",
                    "Sono quasi senza parole... e quasi senza vestiti.",
                ]
                if affinity >= 60
                else [
                    "Smettila di fissarmi e gioca.",
                    "Non ho niente da dirti in questo momento.",
                    "Parleremo dopo. Se rimane qualcosa da dire.",
                ]
            )
        elif strip_level >= 2:
            pool = [
                "Puoi chiedere quello che vuoi, tanto non mi distrai.",
                "Uhm. Interessante. Ora gioca.",
                "Tienimi il punto se vuoi, ma non mi fermi.",
            ]
        else:
            pool = (
                [
                    "Sei divertente. Ma attento alle carte.",
                    "Certo! Però prima decidi cosa fare.",
                    "Ah sì? Vedremo chi ride alla fine.",
                ]
                if affinity >= 50
                else [
                    "Concentrati sul gioco.",
                    "Non ti conosco abbastanza per risponderti.",
                    "Interessante. No.",
                ]
            )
        return random.choice(pool)

    async def _process_strip_events(
        self, strip_events: List[Dict], game_state: "GameState"
    ) -> Tuple[str, Optional[str]]:
        """Generate strip event narratives and images."""
        if not strip_events:
            return "", None

        text = "\n"
        image_path = None

        for event in strip_events:
            name = event["npc_name"]
            new_level = event["new_level"]
            old_level = event.get("old_level", 0)
            comp = self.companions[name]
            strip_mgr = comp["strip_manager"]

            # Decide dialogue source
            if new_level in _LLM_STRIP_LEVELS and self.engine.llm_manager:
                dialogue = await self._generate_strip_dialogue_llm(
                    name, new_level, game_state
                )
            else:
                dialogue = strip_mgr.get_hot_dialogue(new_level)

            if event.get("eliminated"):
                text += f"\n**{name} è ELIMINATA — completamente nuda!**\n"
            elif new_level > old_level:
                text += f"\n**STRIP EVENT** — {name} livello {new_level}\n"
            else:
                text += f"\n**{name}** livello {new_level}\n"

            text += f"{name}: \"{dialogue}\"\n"

            # Visual description
            visual_en = strip_mgr.get_visual_description(new_level)

            # Update outfit in game state
            outfit = game_state.get_outfit(name)
            outfit = strip_mgr.apply_to_outfit(outfit, new_level)
            game_state.set_outfit(outfit, name)

            # Generate image
            img, vid = await self._generate_strip_media(name, visual_en, new_level, game_state)
            if img:
                image_path = img
                # Save to game_state flags so PokerWindow gallery can pick it up
                game_state.flags.setdefault("poker_strip_images", []).append({
                    "path": img,
                    "npc_name": name,
                    "level": new_level,
                })
            if vid:
                game_state.flags.setdefault("poker_strip_videos", []).append({
                    "path": vid,
                    "image_path": img,
                    "npc_name": name,
                    "level": new_level,
                })

        return text, image_path

    async def _generate_strip_dialogue_llm(
        self, companion_name: str, level: int, game_state: "GameState"
    ) -> str:
        """Generate personalized strip dialogue using LLM for levels 3-5."""
        try:
            affinity = game_state.affinity.get(companion_name, 50)
            npc_state = game_state.npc_states.get(companion_name)
            emotional_state = npc_state.emotional_state if npc_state else "default"

            strip_mgr = self.companions[companion_name]["strip_manager"]
            level_desc = strip_mgr.LEVELS[level].description_it

            system = (
                "Sei un assistente per un gioco RPG adulto. Genera UN'unica battuta "
                "di dialogo in italiano, in prima persona, per un personaggio NPC che "
                "durante una partita a strip poker perde l'ennesimo indumento. "
                "Mantieni il tono coerente con l'affinità con il giocatore e "
                "lo stato emotivo corrente. Battuta breve (max 30 parole), diretta, "
                "nessuna censura. Rispondi SOLO con la battuta, senza virgolette."
            )
            user = (
                f"Personaggio: {companion_name}\n"
                f"Situazione: {level_desc}\n"
                f"Affinità con giocatore: {affinity}/100\n"
                f"Stato emotivo: {emotional_state}\n"
                f"Genera la battuta."
            )

            result, _ = await self.engine.llm_manager.generate(
                system_prompt=system,
                user_input=user,
                history=[],
                json_mode=False,
                companion_name=companion_name,
            )
            text = getattr(result, "text", "") or ""
            if text:
                return text.strip().strip('"')

        except Exception as e:
            logger.warning("[Poker] LLM strip dialogue failed: %s", e)

        # Fallback to hardcoded
        return self.companions[companion_name]["strip_manager"].get_hot_dialogue(level)

    async def _generate_strip_media(
        self,
        companion_name: str,
        visual_en: str,
        level: int,
        game_state: "GameState",
    ) -> Tuple[Optional[str], Optional[str]]:
        """Generate strip media via media pipeline.

        Returns:
            (image_path, video_path)
        """
        if not self.engine.media_pipeline:
            logger.info("[Poker] Nessun media_pipeline disponibile — immagine strip skippata")
            return None, None
        if self.engine.no_media:
            logger.info("[Poker] no_media=True — immagine strip skippata")
            return None, None
        # Check debug_no_media in settings
        if getattr(getattr(self.engine.media_pipeline, "settings", None), "debug_no_media", False):
            logger.info("[Poker] debug_no_media=True — immagine strip skippata")
            return None, None

        try:
            outfit = game_state.get_outfit(companion_name)
            generate_video = bool(
                getattr(self.engine.media_pipeline.settings, "video_available", False)
            )
            video_action = (
                "slowly removes a clothing layer, then holds a confident still pose"
            )

            logger.info(
                "[Poker] Generazione immagine strip: %s livello %d — %s",
                companion_name, level, visual_en[:60],
            )
            result = await self.engine.media_pipeline.generate_all(
                text="",
                visual_en=visual_en,
                tags=[f"strip_level_{level}", "poker_game", "playing_cards"],
                companion_name=companion_name,
                outfit=outfit,
                generate_video=generate_video,
                video_action=video_action,
                location_id=game_state.current_location,
            )
            if not result:
                logger.warning("[Poker] generate_all ha restituito None")
                return None, None
            img = result.image_path
            vid = result.video_path
            logger.info("[Poker] Immagine strip generata: %s | video: %s", img, vid)
            return img, vid
        except Exception as e:
            logger.error("[Poker] Generazione media strip fallita: %s", e, exc_info=True)
            return None, None

    # =========================================================================
    # End game
    # =========================================================================

    async def end_game(
        self, game_state: "GameState", reason: str = "Game ended"
    ) -> "TurnResult":
        from luna.core.models import TurnResult

        game_state.flags["poker_active"] = False
        game_state.flags.pop("poker_game", None)

        # Clear live reference on the engine so a new game can start clean
        if hasattr(self.engine, "_active_poker_game"):
            self.engine._active_poker_game = None

        # Flush any NPC initiative turns that queued up during poker
        if hasattr(self.engine, "_pending_initiatives"):
            flushed = len(self.engine._pending_initiatives)
            self.engine._pending_initiatives.clear()
            if flushed:
                logger.info("[Poker] Flushed %d pending initiatives on game end", flushed)

        narrative = f"**GAME OVER**\n\n{reason}\n\n"
        narrative += "**Statistiche finali:**\n"
        narrative += f"  Mani giocate: {self.hand_number}\n"
        for p in self._poker.players:
            result = "vincitore" if p.stack > self.initial_stack else (
                "eliminato" if p.stack <= 0 else "ancora in gioco"
            )
            narrative += f"  {p.name}: {p.stack:,} chips ({result})\n"

        for name, comp in self.companions.items():
            level = comp["strip_level"]
            status = "completamente nuda" if comp["eliminated"] else f"livello {level}/5"
            narrative += f"  {name} strip: {status}\n"

        logger.info("[Poker] Game ended: %s", reason)
        return TurnResult(text=narrative, turn_number=game_state.turn_count)

    # =========================================================================
    # UI helpers
    # =========================================================================

    def _compact_status(self) -> str:
        """Compact one-liner status for mid-hand display."""
        ps = self._poker
        pot = sum(p.amount for p in ps.pots) + sum(
            p.committed_in_street for p in ps.players
        )
        user = ps.players[0]
        hole = " ".join(self._format_card(c) for c in user.hole) if user.hole else "?"
        legal = ps.legal_actions()
        board_str = ""
        if ps.board:
            board_str = " | Board: " + " ".join(self._format_card(c) for c in ps.board)
        return (
            f"Pot: {pot:,}{board_str} | Tue carte: {hole}\n"
            f"{self._legal_hints(legal)}"
        )

    def _board_summary(self) -> str:
        """Full board state — used only for error messages."""
        return self._compact_status()

    def _street_header(self) -> str:
        """Return a header line when street changes, else empty string."""
        ps = self._poker
        if ps.street == "showdown":
            return ""
        if ps.board:
            board = " ".join(self._format_card(c) for c in ps.board)
            return f"\n**{ps.street.upper()}** — Board: {board}\n"
        return ""

    @staticmethod
    def _legal_hints(legal: Dict[str, bool]) -> str:
        actions = []
        if legal.get("check"):  actions.append("`check`")
        if legal.get("call"):   actions.append("`vedo`")
        if legal.get("bet"):    actions.append("`punto X`")
        if legal.get("raise"):  actions.append("`rilancio X`")
        if legal.get("fold"):   actions.append("`fold`")
        if legal.get("allin"):  actions.append("`all-in`")
        if not actions:
            return "_In attesa..._"
        return "Azioni disponibili: " + " | ".join(actions)

    @staticmethod
    def _format_card(card: str) -> str:
        """Convert 'Ah' to A♥, 'Td' to T♦, etc."""
        suits = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
        if len(card) == 2:
            return card[0] + suits.get(card[1], card[1])
        return card

    def _is_game_over(self) -> bool:
        active = [p for p in self._poker.players if p.stack > 0]
        return len(active) <= 1

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        return {
            "companion_names": self.companion_names,
            "initial_stack": self.initial_stack,
            "hand_number": self.hand_number,
            "legal_actions": self._poker.legal_actions(),
            "current_bet": self._poker.current_bet,
            "min_raise_size": self._poker.min_raise_size,
            "big_blind": self._poker.cfg.big_blind,
            "companions": {
                name: {
                    "strip_level": comp["strip_level"],
                    "eliminated": comp["eliminated"],
                    "profile_aggression": comp["profile"].aggression,
                    "profile_bluff": comp["profile"].bluff,
                    "prev_stack": comp["prev_stack"],
                }
                for name, comp in self.companions.items()
            },
            "poker_stacks": {
                p.name: p.stack for p in self._poker.players
            },
            "pending_custom_focus": self._pending_custom_focus,
            # Keep last _DIALOGUE_HISTORY_MAX entries to avoid large payloads
            "dialog_history": self._dialog_history[-_DIALOGUE_HISTORY_MAX:],
        }

    @classmethod
    def from_dict(
        cls, data: Dict[str, Any], engine: "GameEngine"
    ) -> "PokerGame":
        game = cls(
            engine=engine,
            companion_names=data["companion_names"],
            initial_stack=data["initial_stack"],
        )
        game.hand_number = data.get("hand_number", 0)
        game._dialog_history = data.get("dialog_history", [])
        game._pending_custom_focus = data.get("pending_custom_focus", None)

        for name, comp_data in data.get("companions", {}).items():
            if name in game.companions:
                game.companions[name]["strip_level"] = comp_data.get("strip_level", 0)
                game.companions[name]["eliminated"] = comp_data.get("eliminated", False)
                game.companions[name]["prev_stack"] = comp_data.get(
                    "prev_stack", data["initial_stack"]
                )
                prof = game.companions[name]["profile"]
                prof.aggression = comp_data.get("profile_aggression", prof.aggression)
                prof.bluff = comp_data.get("profile_bluff", prof.bluff)

        # Restore stacks
        stacks = data.get("poker_stacks", {})
        for p in game._poker.players:
            if p.name in stacks:
                p.stack = stacks[p.name]

        return game
