import unittest
from unittest.mock import MagicMock
from src.bot.strategy import Strategy
from src.infra.config import Config

class TestStrategy(unittest.TestCase):
    def setUp(self):
        self.mock_config = MagicMock()
        self.mock_config.strategy = {
            "fair_value_window_trades": 5,
            "epsilon": 0.05,
            "buy_aggression_ticks": 1
        }
        self.mock_feed = MagicMock()
        self.strategy = Strategy(self.mock_config, self.mock_feed)

    def test_fair_value_calculation(self):
        # Mock trades
        # Trades have 'price'
        trades = [
            {'price': 0.50}, {'price': 0.52}, {'price': 0.51},
            {'price': 0.53}, {'price': 0.49}, {'price': 0.60} # 6 trades
        ]
        self.mock_feed.get_trades.return_value = trades
        
        # Window is 5. Should use last 5: 0.52, 0.51, 0.53, 0.49, 0.60
        # Avg: (0.52+0.51+0.53+0.49+0.60)/5 = 2.65 / 5 = 0.53
        
        fv = self.strategy.get_fair_value("tokenA")
        self.assertAlmostEqual(fv, 0.53)

    def test_signal_neutral(self):
        # Fair Value = 0.50
        # Mid = 0.50
        # Epsilon = 0.05
        # Range: 0.45 to 0.55 is Neutral
        
        self.mock_feed.get_trades.return_value = [{'price': 0.50}] * 10
        self.mock_feed.get_orderbook.return_value = {
            'bids': [{'price': 0.49}],
            'asks': [{'price': 0.51}]
        }
        # Mid = 0.50. FV = 0.50.
        signal = self.strategy.get_signal("tokenA")
        self.assertEqual(signal, "NEUTRAL")

    def test_signal_buy_yes(self):
        # Fair = 0.50.
        # Mid > Fair + Epsilon (0.55).
        # Let Mid = 0.60.
        
        self.mock_feed.get_trades.return_value = [{'price': 0.50}] * 10
        self.mock_feed.get_orderbook.return_value = {
            'bids': [{'price': 0.59}],
            'asks': [{'price': 0.61}]
        }
        # Mid = 0.60
        signal = self.strategy.get_signal("tokenA")
        self.assertEqual(signal, "BUY_YES")

    def test_signal_details_edge(self):
        self.mock_feed.get_trades.return_value = [{'price': 0.50}] * 10
        self.mock_feed.get_orderbook.return_value = {
            'bids': [{'price': 0.49}],
            'asks': [{'price': 0.51}]
        }
        details = self.strategy.get_signal_details("tokenA")
        self.assertIn(details["signal"], ["BUY_YES", "BUY_NO", "NEUTRAL"])
        self.assertAlmostEqual(details["mid"], 0.50)
        self.assertAlmostEqual(details["edge"], 0.0)

    def test_quote_params_buy_yes(self):
        self.mock_feed.get_orderbook.return_value = {
            'bids': [{'price': 0.49}],
            'asks': [{'price': 0.51}]
        }
        bid, ask = self.strategy.get_quote_params("tokenA", "BUY_YES")
        self.assertGreater(bid, 0.49)
        self.assertGreater(ask, 0.51)
        self.assertLess(bid, ask)

    def test_quote_params_buy_no(self):
        self.mock_feed.get_orderbook.return_value = {
            'bids': [{'price': 0.49}],
            'asks': [{'price': 0.51}]
        }
        bid, ask = self.strategy.get_quote_params("tokenA", "BUY_NO")
        self.assertLess(bid, 0.49)
        self.assertLess(ask, 0.51)
        self.assertLess(bid, ask)

    def test_taker_mode_edge_gate(self):
        config = MagicMock()
        config.strategy = {
            "fair_value_window_trades": 5,
            "epsilon": 0.01,
            "tick_size": 0.01,
            "buy_aggression_ticks": 1,
            "sell_offset": 5,
            "taker_mode": True,
            "taker_max_spread": 0.031,
            "taker_min_edge": 0.02
        }
        feed = MagicMock()
        feed.get_orderbook.return_value = {
            'bids': [{'price': 0.49}],
            'asks': [{'price': 0.52}]
        }
        strat = Strategy(config, feed)

        bid, ask = strat.get_quote_params("tokenA", "BUY_YES", edge=0.01)
        self.assertAlmostEqual(bid, 0.50)
        self.assertAlmostEqual(ask, 0.57)

        bid, ask = strat.get_quote_params("tokenA", "BUY_YES", edge=0.03)
        self.assertAlmostEqual(bid, 0.52)
        self.assertAlmostEqual(ask, 0.57)

if __name__ == '__main__':
    unittest.main()
