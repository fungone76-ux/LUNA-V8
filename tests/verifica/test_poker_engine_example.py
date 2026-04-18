"""Example unit tests for Poker Engine v2.

This file demonstrates how to write tests for the poker system.
Run with: pytest tests/verifica/test_poker_engine_example.py -v
"""
import pytest
from luna.systems.mini_games.poker.engine_v2 import GameState, GameConfig, Player


class TestPokerEngineBasics:
    """Basic poker engine tests - these should all pass."""

    def test_game_config_creation(self, poker_config):
        """Test poker configuration is valid."""
        assert poker_config.small_blind == 50
        assert poker_config.big_blind == 100
        assert poker_config.initial_stack == 1000
        assert poker_config.big_blind == poker_config.small_blind * 2

    def test_player_creation(self):
        """Test creating poker players."""
        player = Player(name="test_player", stack=1000, is_user=True)

        assert player.name == "test_player"
        assert player.stack == 1000
        assert player.folded is False
        assert player.committed_in_hand == 0
        assert player.committed_in_street == 0

    def test_game_state_initialization(self, poker_config, poker_players):
        """Test initializing a poker game state (before start_hand)."""
        state = GameState(cfg=poker_config, players=poker_players)

        assert state.cfg == poker_config
        assert len(state.players) == 2
        assert state.street == "init"
        assert len(state.board) == 0

    def test_start_hand_deals_cards(self, poker_config, poker_players):
        """Test that start_hand() deals 2 cards to each player."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        # Each player should have 2 cards
        assert len(state.players[0].hole) == 2
        assert len(state.players[1].hole) == 2

        # Cards should be valid strings (e.g. "Ts", "Kc")
        for card in state.players[0].hole:
            assert isinstance(card, str) and len(card) == 2

        # Board should be empty preflop
        assert len(state.board) == 0

    def test_blinds_posted_correctly(self, poker_config, poker_players):
        """Test that blinds are posted correctly."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        # Both players should have committed chips (blinds)
        total_committed = sum(p.committed_in_street for p in state.players)
        assert total_committed >= poker_config.small_blind + poker_config.big_blind

        # Both players should have decreased stacks
        for player in state.players:
            assert player.stack < poker_config.initial_stack


class TestPokerActions:
    """Test poker actions (call, raise, fold, check, all-in)."""

    def test_call_action(self, poker_config, poker_players):
        """Test calling a bet."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        acting_player = state.players[state.to_act]
        stack_before = acting_player.stack
        total_committed_before = sum(p.committed_in_hand for p in state.players)

        state.act_call()

        total_committed_after = sum(p.committed_in_hand for p in state.players)
        assert total_committed_after > total_committed_before
        assert acting_player.stack < stack_before

    def test_raise_action(self, poker_config, poker_players):
        """Test raising a bet."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        acting_player = state.players[state.to_act]
        total_committed_before = sum(p.committed_in_hand for p in state.players)

        state.act_raise(300)

        assert acting_player.committed_in_street == 300
        total_committed_after = sum(p.committed_in_hand for p in state.players)
        assert total_committed_after > total_committed_before

    def test_fold_action(self, poker_config, poker_players):
        """Test folding a hand."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        acting_player = state.players[state.to_act]
        state.act_fold()

        assert acting_player.folded is True

    def test_check_action(self, poker_config, poker_players):
        """Test checking (no bet) on flop."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        # SB/BTN calls, BB checks to close preflop action
        state.act_call()
        state.act_check()
        state.settle_and_next_street_if_needed()

        assert state.street == "flop"

        # Both check on flop — committed_in_street should stay 0
        state.act_check()
        state.act_check()

        assert all(p.committed_in_street == 0 for p in state.players)

    def test_all_in_action(self, poker_config):
        """Test all-in with remaining stack."""
        players = [
            Player(name="player", stack=500, is_user=True),
            Player(name="luna", stack=1000),
        ]
        state = GameState(cfg=poker_config, players=players)
        state.start_hand()

        acting_player = state.players[state.to_act]
        state.act_allin()

        assert acting_player.stack == 0
        assert acting_player.all_in is True


class TestStreetProgression:
    """Test progression through streets (preflop → flop → turn → river)."""

    def test_preflop_to_flop(self, poker_config, poker_players):
        """Test advancing from preflop to flop."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        assert state.street == "preflop"
        assert len(state.board) == 0

        state.act_call()
        state.act_check()
        state.settle_and_next_street_if_needed()

        assert state.street == "flop"
        assert len(state.board) == 3

    def test_flop_to_turn(self, poker_config, poker_players):
        """Test advancing from flop to turn."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        state.act_call()
        state.act_check()
        state.settle_and_next_street_if_needed()

        assert state.street == "flop"

        state.act_check()
        state.act_check()
        state.settle_and_next_street_if_needed()

        assert state.street == "turn"
        assert len(state.board) == 4

    def test_turn_to_river(self, poker_config, poker_players):
        """Test advancing from turn to river."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        state.act_call()
        state.act_check()
        state.settle_and_next_street_if_needed()  # flop
        state.act_check()
        state.act_check()
        state.settle_and_next_street_if_needed()  # turn

        assert state.street == "turn"

        state.act_check()
        state.act_check()
        state.settle_and_next_street_if_needed()

        assert state.street == "river"
        assert len(state.board) == 5

    def test_river_to_showdown(self, poker_config, poker_players):
        """Test advancing from river to showdown."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        state.act_call()
        state.act_check()
        state.settle_and_next_street_if_needed()  # flop
        state.act_check()
        state.act_check()
        state.settle_and_next_street_if_needed()  # turn
        state.act_check()
        state.act_check()
        state.settle_and_next_street_if_needed()  # river
        state.act_check()
        state.act_check()
        state.settle_and_next_street_if_needed()  # showdown

        assert state.street == "showdown"


class TestLegalActions:
    """Test legal action detection."""

    def test_legal_actions_preflop(self, poker_config, poker_players):
        """Test legal actions on preflop."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        legal = state.legal_actions()

        # SB/BTN can call, raise, or fold — cannot check (there's a bet to match)
        assert legal.get("call") is True
        assert legal.get("raise") is True
        assert legal.get("fold") is True

    def test_legal_actions_after_check(self, poker_config, poker_players):
        """Test legal actions when opponent checks (on flop)."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        state.act_call()
        state.act_check()
        state.settle_and_next_street_if_needed()  # flop

        legal = state.legal_actions()
        assert legal.get("check") is True


class TestShowdown:
    """Test showdown and winner determination."""

    def test_showdown_determines_winner(self, poker_config, poker_players):
        """Test that showdown correctly determines a winner."""
        state = GameState(cfg=poker_config, players=poker_players)
        state.start_hand()

        state.act_call()
        state.act_check()
        state.settle_and_next_street_if_needed()  # flop
        state.act_check()
        state.act_check()
        state.settle_and_next_street_if_needed()  # turn
        state.act_check()
        state.act_check()
        state.settle_and_next_street_if_needed()  # river
        state.act_check()
        state.act_check()
        state.settle_and_next_street_if_needed()  # showdown

        assert state.street == "showdown"

        winner_indices, payouts = state.showdown()

        # Should have at least one winner
        assert len(winner_indices) > 0

        # Winner indices should be valid player positions
        for idx in winner_indices:
            assert 0 <= idx < len(state.players)
            assert payouts[idx] > 0


@pytest.mark.benchmark
class TestPokerPerformance:
    """Performance tests for poker engine."""

    def test_hand_simulation_performance(self, poker_config, poker_players, benchmark):
        """Benchmark a complete hand simulation."""

        def play_hand():
            state = GameState(cfg=poker_config, players=poker_players)
            state.start_hand()
            state.act_call()
            state.act_check()
            state.settle_and_next_street_if_needed()
            state.act_check()
            state.act_check()
            state.settle_and_next_street_if_needed()
            state.act_check()
            state.act_check()
            state.settle_and_next_street_if_needed()
            state.act_check()
            state.act_check()
            state.settle_and_next_street_if_needed()
            winner_indices, payouts = state.showdown()
            return winner_indices

        result = benchmark(play_hand)
        assert len(result) > 0


if __name__ == "__main__":
    # Allow running directly
    pytest.main([__file__, "-v"])
