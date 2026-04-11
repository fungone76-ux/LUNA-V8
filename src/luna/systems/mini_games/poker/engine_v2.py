# app/game_modes/poker/engine_v2.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple
import logging
import random
import eval7  # pip install eval7

_log = logging.getLogger(__name__)

# ------------------------------------------------------------
# Util carte
# ------------------------------------------------------------
RANKS = "23456789TJQKA"
SUITS = "shdc"

def fresh_deck() -> List[str]:
    """Crea un mazzo ordinato di 52 carte in formato 'As','Td', ecc."""
    return [r + s for r in RANKS for s in SUITS]

def to_eval7(cards: List[str]) -> List[eval7.Card]:
    return [eval7.Card(c) for c in cards]

# ------------------------------------------------------------
# Config, Player, Pot
# ------------------------------------------------------------
@dataclass
class GameConfig:
    small_blind: int = 50
    big_blind: int = 100
    initial_stack: int = 2000
    betting_structure: str = "NL"  # No-Limit

@dataclass
class Player:
    name: str
    is_user: bool = False
    stack: int = 0
    hole: List[str] = field(default_factory=list)

    folded: bool = False
    all_in: bool = False

    committed_in_street: int = 0  # chip impegnati in questa street
    committed_in_hand: int = 0    # chip impegnati nell’intera mano (per side-pot)

@dataclass
class Pot:
    amount: int = 0
    eligible_players: Set[int] = field(default_factory=set)  # indici giocatori che possono vincerlo

# ------------------------------------------------------------
# Game State (engine v2)
# ------------------------------------------------------------
@dataclass
class GameState:
    players: List[Player]
    cfg: GameConfig = field(default_factory=GameConfig)

    # posizione e flusso
    dealer_pos: int = -1
    sb_pos: Optional[int] = None
    bb_pos: Optional[int] = None
    to_act: Optional[int] = None

    # round/stato
    street: str = "init"          # init/preflop/flop/turn/river/showdown
    board: List[str] = field(default_factory=list)
    deck: List[str] = field(default_factory=fresh_deck)

    # puntate
    current_bet: int = 0          # bet/raise totale da pareggiare in questa street
    min_raise_size: int = 0       # incremento minimo per riaprire l’azione
    last_aggressor: Optional[int] = None

    # preflop heads-up
    bb_option_open: bool = False  # opzione della BB non ancora esercitata (solo preflop HU)

    # piatti
    pots: List[Pot] = field(default_factory=list)

    # tracking azioni per chiusura street quando current_bet==0
    acted_this_street: Set[int] = field(default_factory=set)

    # --------------------------------------------------------
    # Init / dealer / start hand
    # --------------------------------------------------------
    def __post_init__(self):
        for p in self.players:
            if p.stack <= 0:
                p.stack = self.cfg.initial_stack

    def rotate_dealer(self):
        n = len(self.players)
        if n == 0:
            return
        start = (self.dealer_pos + 1) % n
        i = start
        while True:
            if self.players[i].stack > 0:
                self.dealer_pos = i
                return
            i = (i + 1) % n
            if i == start:
                self.dealer_pos = 0
                return

    def _next_index(self, idx: int) -> int:
        return (idx + 1) % len(self.players)

    def _next_can_act(self, idx: int) -> Optional[int]:
        n = len(self.players)
        if n == 0:
            return None
        i = idx
        for _ in range(n):
            i = self._next_index(i)
            p = self.players[i]
            if (not p.folded) and (not p.all_in):
                return i
        return None

    def start_hand(self):
        """Reset, posti blind, carte, preflop pronto a parlare."""
        # reset base
        self.board.clear()
        self.deck = fresh_deck()
        random.shuffle(self.deck)
        self.pots = [Pot(amount=0, eligible_players=set(i for i, p in enumerate(self.players) if p.stack > 0))]
        self.street = "preflop"
        self.current_bet = 0
        self.min_raise_size = 0
        self.last_aggressor = None
        self.bb_option_open = False
        self.acted_this_street = set()

        # reset player state e hole
        for p in self.players:
            p.folded = (p.stack <= 0)
            p.all_in = False
            p.committed_in_street = 0
        for p in self.players:
            p.committed_in_hand = 0
            p.hole = [self.deck.pop(), self.deck.pop()] if p.stack > 0 else []

        # posizioni
        n = len(self.players)
        if n == 2:
            self.sb_pos = self.dealer_pos
            self.bb_pos = self._next_index(self.dealer_pos)
        else:
            self.sb_pos = self._next_index(self.dealer_pos)
            self.bb_pos = self._next_index(self.sb_pos)

        # post blind
        if self.sb_pos is not None:
            self._commit(self.sb_pos, self.cfg.small_blind)
        if self.bb_pos is not None:
            self._commit(self.bb_pos, self.cfg.big_blind)

        # baseline
        self.current_bet = max(p.committed_in_street for p in self.players)
        self.min_raise_size = self.cfg.big_blind  # preflop: primo raise minimo = BB
        self.last_aggressor = None

        # bb option aperta in HU preflop
        self.bb_option_open = (len([p for p in self.players if not p.folded]) == 2 and self.street == "preflop")

        # chi parla: il primo a sinistra della BB (in HU: SB)
        self.to_act = self._next_index(self.bb_pos)

        import logging as _log
        _log.getLogger(__name__).debug(
            "[Poker] Hand started. Dealer=%d SB=%d BB=%d current_bet=%d to_act=%s",
            self.dealer_pos, self.sb_pos, self.bb_pos, self.current_bet, self.to_act,
        )

    # --------------------------------------------------------
    # Commit e costruzione pots
    # --------------------------------------------------------
    def _commit(self, idx: int, amount: int) -> int:
        pl = self.players[idx]
        if amount <= 0 or pl.folded or pl.all_in:
            return 0
        put = min(pl.stack, int(amount))
        pl.stack -= put
        pl.committed_in_street += put
        pl.committed_in_hand += put
        if pl.stack == 0:
            pl.all_in = True
        import logging as _log
        _log.getLogger(__name__).debug(
            "[Poker] Player %d (%s) posts %d → stack=%d street_commit=%d",
            idx, pl.name, put, pl.stack, pl.committed_in_street,
        )
        return put

    def _rebuild_pots(self):
        # FIX: include tutti i chip (anche dei foldati) nel calcolo del pot.
        # Solo i non-foldati sono eligible a vincere.
        all_committed = [(i, p) for i, p in enumerate(self.players) if p.committed_in_hand > 0]
        if not all_committed:
            self.pots = [Pot(amount=0, eligible_players=set(i for i, p in enumerate(self.players) if not p.folded))]
            return
        levels = sorted(set(p.committed_in_hand for _, p in all_committed))
        prev = 0
        pots: List[Pot] = []
        for L in levels:
            contributors = {i for i, p in all_committed if p.committed_in_hand >= L}
            elig = {i for i in contributors if not self.players[i].folded}
            if elig:
                layer_amount = (L - prev) * len(contributors)
                pots.append(Pot(amount=layer_amount, eligible_players=elig))
            prev = L
        self.pots = pots if pots else [Pot(amount=0, eligible_players=set(i for i, p in enumerate(self.players) if not p.folded))]

    def _collect_street_and_reset(self):
        self._rebuild_pots()
        for p in self.players:
            p.committed_in_street = 0
        # nuova street → nessuno ha ancora agito
        self.acted_this_street = set()

    # --------------------------------------------------------
    # Legal actions
    # --------------------------------------------------------
    def _to_call(self, idx: int) -> int:
        me = self.players[idx]
        want = self.current_bet - me.committed_in_street
        return max(0, want)

    def legal_actions(self) -> Dict[str, bool]:
        if self.to_act is None:
            return {"check": False, "call": False, "bet": False, "raise": False, "fold": False, "allin": False}

        me = self.players[self.to_act]
        if me.folded or me.all_in:
            return {"check": False, "call": False, "bet": False, "raise": False, "fold": False, "allin": False}

        to_call = self._to_call(self.to_act)
        can_check = (to_call == 0)
        can_call = (to_call > 0) and (me.stack > 0)
        can_bet = (self.current_bet == 0) and (me.stack > 0)
        can_raise = False
        if self.current_bet > 0 and me.stack > 0:
            min_raise_to = self.current_bet + self.min_raise_size
            can_raise = (me.committed_in_street + me.stack) >= min_raise_to and (to_call < me.stack + 1)
        can_fold = (to_call > 0)
        can_allin = (me.stack > 0)

        return {
            "check": can_check,
            "call": can_call,
            "bet": can_bet,
            "raise": can_raise,
            "fold": can_fold,
            "allin": can_allin
        }

    # --------------------------------------------------------
    # Azioni (tutte marcano "ha agito" per questa street)
    # --------------------------------------------------------
    def _mark_acted(self):
        if self.to_act is not None:
            self.acted_this_street.add(self.to_act)

    def act_check(self):
        legal = self.legal_actions()
        if not legal["check"]:
            _log.warning("[Poker] Illegal CHECK by idx=%s", self.to_act)
            return
        self._mark_acted()
        if self.street == "preflop" and self.bb_option_open and self.to_act == self.bb_pos:
            self.bb_option_open = False
        self._advance_turn()

    def act_call(self):
        legal = self.legal_actions()
        if not legal["call"]:
            _log.warning("[Poker] Illegal CALL by idx=%s", self.to_act)
            return
        self._mark_acted()
        me = self.players[self.to_act]
        to_call = self._to_call(self.to_act)
        put = min(me.stack, to_call)
        self._commit(self.to_act, put)
        if self.street == "preflop" and self.bb_option_open and self.to_act == self.bb_pos:
            self.bb_option_open = False
        self._advance_turn()

    def act_bet(self, amount: int):
        legal = self.legal_actions()
        if not legal["bet"]:
            _log.warning("[Poker] Illegal BET by idx=%s", self.to_act)
            return
        self._mark_acted()
        me = self.players[self.to_act]
        amount = max(amount, self.cfg.big_blind)
        to_post = min(me.stack, amount)
        self.current_bet = to_post
        self.min_raise_size = to_post
        self.last_aggressor = self.to_act
        self._commit(self.to_act, to_post)
        if self.street == "preflop" and self.bb_option_open:
            self.bb_option_open = False
        self._advance_turn()

    def act_raise(self, to_amount: int):
        legal = self.legal_actions()
        if not legal["raise"]:
            _log.warning("[Poker] Illegal RAISE by idx=%s", self.to_act)
            return
        self._mark_acted()
        me = self.players[self.to_act]
        to_amount = max(to_amount, self.current_bet + self.min_raise_size)
        need = to_amount - me.committed_in_street
        put = min(me.stack, need)
        self._commit(self.to_act, put)
        new_total = me.committed_in_street
        raise_size = new_total - self.current_bet
        if raise_size >= self.min_raise_size:
            self.min_raise_size = raise_size
            self.current_bet = new_total
            self.last_aggressor = self.to_act
        if self.street == "preflop" and self.bb_option_open:
            self.bb_option_open = False
        self._advance_turn()

    def act_allin(self):
        legal = self.legal_actions()
        if not legal["allin"]:
            _log.warning("[Poker] Illegal ALL-IN by idx=%s", self.to_act)
            return
        self._mark_acted()
        me = self.players[self.to_act]
        if self.current_bet == 0:
            target_total = me.committed_in_street + me.stack
            self.act_bet(target_total)
            return
        target_total = me.committed_in_street + me.stack
        need = target_total - me.committed_in_street
        self._commit(self.to_act, need)
        min_raise_to = self.current_bet + self.min_raise_size
        if (me.committed_in_street >= min_raise_to):
            raise_size = me.committed_in_street - self.current_bet
            self.min_raise_size = raise_size
            self.current_bet = me.committed_in_street
            self.last_aggressor = self.to_act
        if self.street == "preflop" and self.bb_option_open:
            self.bb_option_open = False
        self._advance_turn()

    def act_fold(self):
        if self.to_act is None:
            _log.warning("[Poker] Illegal FOLD (no to_act)")
            return
        me = self.players[self.to_act]
        self._mark_acted()
        me.folded = True
        if self.street == "preflop" and self.bb_option_open and self.to_act == self.bb_pos:
            self.bb_option_open = False
        self._advance_turn()

    # --------------------------------------------------------
    # Turno e chiusura street
    # --------------------------------------------------------
    def _someone_can_act(self) -> bool:
        return any((not p.folded) and (not p.all_in) for p in self.players)

    def _all_matched(self) -> bool:
        needed = []
        for i, p in enumerate(self.players):
            if p.folded or p.all_in:
                continue
            need = self.current_bet - p.committed_in_street
            if need > 0:
                needed.append(i)
        return len(needed) == 0

    def _active_can_act_idxs(self) -> List[int]:
        return [i for i, p in enumerate(self.players) if not p.folded and not p.all_in]

    def _action_closed(self) -> bool:
        """Azione chiusa:
           - se current_bet == 0: TUTTI i giocatori che possono agire hanno agito (check o altro) in questa street
           - se current_bet  > 0: tutti hanno pareggiato e (in preflop) BB option è chiusa
        """
        if not self._someone_can_act():
            return True

        if self.current_bet == 0:
            # Serve che tutti gli attivi abbiano agito almeno una volta (check o altro)
            actives = set(self._active_can_act_idxs())
            return len(actives) > 0 and actives.issubset(self.acted_this_street)

        # c'è stata puntata: basta che tutti abbiano pareggiato e l'opzione BB sia chiusa
        return self._all_matched() and (not self.bb_option_open)

    def settle_and_next_street_if_needed(self) -> bool:
        # Caso A: rimane 1 attivo → mano finita
        # FIX: calcola pot da committed_in_hand di tutti (inclusi foldati)
        alive = [i for i, p in enumerate(self.players) if not p.folded]
        if len(alive) == 1:
            winner = alive[0]
            total = sum(p.committed_in_hand for p in self.players)
            total += sum(pot.amount for pot in self.pots if pot.amount > 0)
            self.players[winner].stack += total
            for p in self.players:
                p.committed_in_hand = 0
                p.committed_in_street = 0
                p.all_in = False
                p.folded = False
            self.pots = [Pot(amount=0, eligible_players=set())]
            self.street = "showdown"
            self.to_act = None
            return True

        # Caso C: nessuno può agire (tutti all-in/fold) → runout + showdown
        if not self._someone_can_act():
            while len(self.board) < 5:
                if self.street == "preflop":
                    self.street = "flop"; self.board.extend([self.deck.pop() for _ in range(3)])
                elif self.street == "flop":
                    self.street = "turn"; self.board.append(self.deck.pop())
                elif self.street == "turn":
                    self.street = "river"; self.board.append(self.deck.pop())
                else:
                    break
            self._collect_street_and_reset()
            self.street = "showdown"
            self.to_act = None
            return True

        _log.debug(
            "[Poker] street_end_check: to_act=%s aggressor=%s all_matched=%s bb_opt=%s closed=%s",
            self.to_act, self.last_aggressor, self._all_matched(),
            self.bb_option_open, self._action_closed(),
        )
        if self._action_closed():
            self._collect_street_and_reset()
            self.last_aggressor = None
            self.current_bet = 0
            self.min_raise_size = self.cfg.big_blind
            # advance street
            if self.street == "preflop":
                self.street = "flop"; self.board.extend([self.deck.pop() for _ in range(3)])
            elif self.street == "flop":
                self.street = "turn"; self.board.append(self.deck.pop())
            elif self.street == "turn":
                self.street = "river"; self.board.append(self.deck.pop())
            elif self.street == "river":
                self.street = "showdown"; self.to_act = None; return True

            # nuova street: parla il non-dealer
            self.bb_option_open = False
            self.to_act = self._next_index(self.dealer_pos)
            _log.debug("[Poker] Street -> %s to_act=%s", self.street, self.to_act)
            return False

        return False

    def _advance_turn(self):
        nxt = self._next_can_act(self.to_act if self.to_act is not None else -1)
        self.to_act = nxt

    # --------------------------------------------------------
    # Showdown
    # --------------------------------------------------------
    def showdown(self) -> Tuple[List[int], Dict[int, int]]:
        if self.street != "showdown":
            if self._someone_can_act():
                return ([], {})
            while len(self.board) < 5:
                if self.street == "preflop":
                    self.board.extend([self.deck.pop() for _ in range(3)]);
                    self.street = "flop"
                elif self.street == "flop":
                    self.board.append(self.deck.pop());
                    self.street = "turn"
                elif self.street == "turn":
                    self.board.append(self.deck.pop());
                    self.street = "river"
                else:
                    break
            self._collect_street_and_reset()
            self.street = "showdown"

        self._rebuild_pots()

        payouts: Dict[int, int] = {i: 0 for i in range(len(self.players))}
        overall_winners: Set[int] = set()
        if not self.pots:
            return ([], payouts)

        alive = {i for i, p in enumerate(self.players) if not p.folded and p.hole}

        for idx, pot in enumerate(self.pots):
            contenders = sorted(list(pot.eligible_players.intersection(alive)))
            if len(contenders) == 0 or pot.amount <= 0:
                continue
            scores: Dict[int, int] = {}
            board_cards = to_eval7(self.board)
            for pi in contenders:
                hole_cards = to_eval7(self.players[pi].hole)
                score = eval7.evaluate(board_cards + hole_cards)
                scores[pi] = score
                _log.debug("[Poker] Pot%d player %s score=%d", idx+1, self.players[pi].name, score)
            best = max(scores.values())
            winners = [pi for pi, sc in scores.items() if sc == best]
            share = pot.amount // len(winners)
            remainder = pot.amount - share * len(winners)
            for w in winners:
                payouts[w] += share
                self.players[w].stack += share
                overall_winners.add(w)
            if remainder > 0:
                payouts[winners[0]] += remainder
                self.players[winners[0]].stack += remainder

        # ⛔️ NON svuotiamo le hole qui: restano visibili in UI a showdown
        for p in self.players:
            p.committed_in_street = 0
            p.committed_in_hand = 0
            p.all_in = False
            p.folded = False
            # p.hole = []  # <-- rimosso

        self.pots = [Pot(amount=0, eligible_players=set())]
        self.board = []
        self.to_act = None
        winners_sorted = sorted(list(overall_winners))
        return (winners_sorted, payouts)

    # --------------------------------------------------------
    # Stato pubblico per UI/debug
    # --------------------------------------------------------
    def public_state(self) -> Dict[str, any]:
        players_out = []
        for i, p in enumerate(self.players):
            players_out.append({
                "name": p.name,
                "stack": p.stack,
                "comm_street": p.committed_in_street,
                "comm_hand": p.committed_in_hand,
                "folded": p.folded,
                "all_in": p.all_in,
                "is_dealer": (i == self.dealer_pos),
                "is_to_act": (i == self.to_act),
                "hole": list(p.hole)
            })
        return {
            "street": self.street,
            "board": list(self.board),
            "pot_total": sum(p.amount for p in self.pots),
            "pots_details": [{"amount": p.amount, "eligible": sorted(list(p.eligible_players))} for p in self.pots],
            "dealer_pos": self.dealer_pos,
            "to_act": self.to_act,
            "players": players_out
        }
