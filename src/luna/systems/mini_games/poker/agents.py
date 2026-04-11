# app/game_modes/poker/agents.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any
import random
import eval7

from .engine_v2 import fresh_deck  # usa lo stesso deck dell'engine

# ------------------------------------------------------------
# Profili rischio (semplici) + default
# ------------------------------------------------------------
@dataclass
class RiskProfile:
    aggression: float = 0.5  # 0..1
    bluff: float = 0.2       # 0..1

DEFAULT_PROFILES: Dict[str, RiskProfile] = {
    "_AI_": RiskProfile(aggression=0.65, bluff=0.30),
    "Luna":   RiskProfile(aggression=0.78, bluff=0.38),   # aggressiva, bluffa spesso
    "Stella": RiskProfile(aggression=0.72, bluff=0.32),   # competitiva
    "Maria":  RiskProfile(aggression=0.68, bluff=0.28),   # equilibrata ma attiva
}

# ------------------------------------------------------------
# Stima equity Monte Carlo multiway (hero vs (players-1) random)
# ------------------------------------------------------------
def sample_equity(hole: list[str], board: list[str], iters: int, players: int) -> float:
    if len(hole) != 2 or players <= 1:
        return 0.5
    known = set(hole + (board or []))
    deck = [c for c in fresh_deck() if c not in known]
    need_board = max(0, 5 - len(board or []))
    opp_cards_needed = 2 * max(0, players - 1)
    draw_need = need_board + opp_cards_needed
    if draw_need > len(deck):
        return 0.5

    rng = random.Random()
    wins = ties = 0.0

    for _ in range(max(200, int(iters))):
        rng.shuffle(deck)
        draw = deck[:draw_need]
        run_board = list(board or []) + draw[:need_board]
        opp_pool = draw[need_board:]
        opp_hands = [opp_pool[2 * i: 2 * (i + 1)] for i in range(players - 1)]

        hero_score = eval7.evaluate([eval7.Card(c) for c in (hole + run_board)])
        opp_best = max(eval7.evaluate([eval7.Card(c) for c in (oh + run_board)]) for oh in opp_hands)

        if hero_score > opp_best:
            wins += 1.0
        elif hero_score == opp_best:
            ties += 1.0

    return (wins + 0.5 * ties) / max(1.0, float(iters))

# ------------------------------------------------------------
# Agente rischio + equity → decide()
# ------------------------------------------------------------
@dataclass
class AgentContext:
    name: str
    profile: RiskProfile
    rng: random.Random

class RiskAgent:
    """Bot: equity Monte Carlo + profilo rischio → check/call/raise/fold/all-in."""
    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    def decide(self, state, my_index: int) -> Dict[str, Any]:
        me = state.players[my_index]
        n_players = sum(1 for p in state.players if not p.folded)

        # Equity stimata
        eq = sample_equity(me.hole, state.board, iters=1200, players=n_players)

        # Calcolo to_call coerente con l'engine
        current_max_commit = max((p.committed_in_street for p in state.players if not p.folded), default=0)
        to_call = max(0, current_max_commit - me.committed_in_street)

        # Pot effettivo = pots già raccolti + puntate sul tavolo in questa street
        pot_already = sum(pot.amount for pot in state.pots) if getattr(state, "pots", None) else 0
        pot_on_table = sum(p.committed_in_street for p in state.players if not p.folded)
        eff_pot = pot_already + pot_on_table

        pot_odds = to_call / max(1, eff_pot + to_call)

        # soglie
        a = self.ctx.profile.aggression
        thresh_call  = pot_odds * (0.9 - 0.2 * a)
        thresh_raise = min(0.75, 0.45 + 0.25 * a)
        jitter = (self.ctx.rng.random() - 0.5) * 0.05
        eq_adj = max(0.0, min(1.0, eq + jitter + self.ctx.profile.bluff * 0.02))

        legal = state.legal_actions()

        # Se non c'è nulla da chiamare
        if to_call == 0:
            # Preferisci bet se equity alta
            if eq_adj > thresh_raise and legal.get("bet"):
                min_bet = state.cfg.big_blind
                amount = max(min_bet, int((eff_pot * 0.6) + self.ctx.rng.random() * state.cfg.big_blind))
                return {"action": "bet", "amount": amount}
            # Altrimenti check
            if legal.get("check"):
                return {"action": "check"}
            # Fallback
            return {"action": "fold"} if legal.get("fold") else {"action": "check"}

        # C'è una puntata davanti
        if eq_adj + 0.02 > thresh_call and (legal.get("call") or legal.get("allin")):
            # Valuta raise/all-in se equity alta
            if eq_adj > thresh_raise and (legal.get("raise") or legal.get("allin")):
                min_add = max(state.min_raise_size, state.cfg.big_blind)
                add = max(min_add, int((eff_pot * 0.4) + self.ctx.rng.random() * state.cfg.big_blind))
                if legal.get("raise") and (me.stack > to_call + add):
                    return {"action": "raise", "amount": add}
                return {"action": "allin"} if legal.get("allin") else {"action": "call"}
            return {"action": "call"} if legal.get("call") else {"action": "allin"}

        # Non conveniente: fold se possibile
        return {"action": "fold"} if legal.get("fold") else {"action": "call"}
