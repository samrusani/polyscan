import json
import os
import tempfile

from src.backtest.runner import load_ticks, run_backtest, run_backtest_multi


def _write_temp_json(payload):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    tmp.write(json.dumps(payload).encode("utf-8"))
    tmp.close()
    return tmp.name


def test_load_ticks_requires_list():
    path = _write_temp_json({"oops": "not a list"})
    try:
        try:
            load_ticks(path)
            assert False, "expected ValueError"
        except ValueError:
            pass
    finally:
        os.unlink(path)


def test_run_backtest_counts_signals():
    ticks = [
        {
            "orderbook": {
                "token_id": "tokenA",
                "book": {"bids": [{"price": 0.49}], "asks": [{"price": 0.51}]}
            },
            "trades": [{"price": 0.45, "size": 1}]
        },
        {
            "orderbook": {
                "token_id": "tokenA",
                "book": {"bids": [{"price": 0.49}], "asks": [{"price": 0.51}]}
            },
            "trades": [{"price": 0.50, "size": 1}]
        }
    ]
    path = _write_temp_json(ticks)
    try:
        config = type("DummyConfig", (), {
            "strategy": {
                "fair_value_window_trades": 1,
                "epsilon": 0.01,
                "tick_size": 0.01,
                "buy_aggression_ticks": 1,
                "sell_offset": 1,
                "taker_mode": False,
                "taker_max_spread": 0.03,
                "taker_min_edge": 0.01
            },
            "backtest": {
                "position_size": 10,
                "price_mode": "mid",
                "close_at_end": True,
                "fee_bps": 0.0,
                "slippage_bps": 0.0,
                "slippage_ticks": 0.0
            }
        })()
        result = run_backtest(config, "tokenA", load_ticks(path))
    finally:
        os.unlink(path)
    assert result.total_ticks == 2
    assert result.total_trades == 1
    assert len(result.trades) == 1
    assert len(result.equity_curve) == 2


def test_run_backtest_multi_tracks_tokens():
    ticks = [
        {
            "timestamp": "t1",
            "orderbooks": [
                {"token_id": "tokenA", "book": {"bids": [{"price": 0.49}], "asks": [{"price": 0.51}]}},
                {"token_id": "tokenB", "book": {"bids": [{"price": 0.49}], "asks": [{"price": 0.51}]}}
            ],
            "trades": [
                {"token_id": "tokenA", "price": 0.45, "size": 1},
                {"token_id": "tokenB", "price": 0.55, "size": 1}
            ]
        },
        {
            "timestamp": "t2",
            "orderbooks": [
                {"token_id": "tokenA", "book": {"bids": [{"price": 0.52}], "asks": [{"price": 0.54}]}},
                {"token_id": "tokenB", "book": {"bids": [{"price": 0.48}], "asks": [{"price": 0.50}]}}
            ],
            "trades": [
                {"token_id": "tokenA", "price": 0.46, "size": 1},
                {"token_id": "tokenB", "price": 0.54, "size": 1}
            ]
        }
    ]
    config = type("DummyConfig", (), {
        "strategy": {
            "fair_value_window_trades": 1,
            "epsilon": 0.01,
            "tick_size": 0.01,
            "buy_aggression_ticks": 1,
            "sell_offset": 1,
            "taker_mode": False,
            "taker_max_spread": 0.03,
            "taker_min_edge": 0.01
        },
        "backtest": {
            "position_size": 5,
            "price_mode": "mid",
            "close_at_end": True
        }
    })()
    result = run_backtest_multi(config, ["tokenA", "tokenB"], ticks)
    assert result.total_trades == 2
    assert {t.token_id for t in result.trades} == {"tokenA", "tokenB"}
    assert result.per_token["tokenA"].total_trades == 1
    assert result.per_token["tokenB"].total_trades == 1


def test_backtest_fees_and_slippage_reduce_pnl():
    ticks = [
        {
            "timestamp": "t1",
            "orderbook": {
                "token_id": "tokenA",
                "book": {"bids": [{"price": 0.49}], "asks": [{"price": 0.51}]}
            },
            "trades": [{"price": 0.45, "size": 1}]
        },
        {
            "timestamp": "t2",
            "orderbook": {
                "token_id": "tokenA",
                "book": {"bids": [{"price": 0.60}], "asks": [{"price": 0.62}]}
            },
            "trades": [{"price": 0.45, "size": 1}]
        }
    ]
    base_strategy = {
        "fair_value_window_trades": 1,
        "epsilon": 0.01,
        "tick_size": 0.01,
        "buy_aggression_ticks": 1,
        "sell_offset": 1,
        "taker_mode": False,
        "taker_max_spread": 0.03,
        "taker_min_edge": 0.01
    }
    no_fee_cfg = type("DummyConfig", (), {
        "strategy": base_strategy,
        "backtest": {
            "position_size": 10,
            "price_mode": "mid",
            "close_at_end": True,
            "fee_bps": 0.0,
            "slippage_bps": 0.0,
            "slippage_ticks": 0.0
        }
    })()
    fee_cfg = type("DummyConfig", (), {
        "strategy": base_strategy,
        "backtest": {
            "position_size": 10,
            "price_mode": "mid",
            "close_at_end": True,
            "fee_bps": 50.0,
            "slippage_bps": 25.0,
            "slippage_ticks": 1.0
        }
    })()
    result_no_fee = run_backtest(no_fee_cfg, "tokenA", ticks)
    result_fee = run_backtest(fee_cfg, "tokenA", ticks)
    assert result_fee.fees_paid > 0
    assert result_fee.total_pnl < result_no_fee.total_pnl


def test_backtest_epsilon_override_triggers_mid_signal():
    ticks = [
        {
            "timestamp": "t1",
            "orderbook": {
                "token_id": "tokenA",
                "book": {"bids": [{"price": 0.49}], "asks": [{"price": 0.51}]}
            }
        },
        {
            "timestamp": "t2",
            "orderbook": {
                "token_id": "tokenA",
                "book": {"bids": [{"price": 0.50}], "asks": [{"price": 0.52}]}
            }
        }
    ]
    config = type("DummyConfig", (), {
        "strategy": {
            "fair_value_window_trades": 1,
            "epsilon": 0.02,
            "tick_size": 0.01,
            "buy_aggression_ticks": 1,
            "sell_offset": 1,
            "taker_mode": False,
            "taker_max_spread": 0.03,
            "taker_min_edge": 0.01,
            "min_edge_to_trade": 0.0
        },
        "backtest": {
            "position_size": 10,
            "price_mode": "mid",
            "close_at_end": True,
            "strategy_mode": "mid",
            "mid_fair_value_window": 2,
            "epsilon_override": 0.002,
            "min_edge_override": 0.0
        }
    })()
    result = run_backtest(config, "tokenA", ticks)
    assert result.buy_yes == 1
    assert result.total_trades == 1


def test_backtest_min_edge_override_blocks_mid_signal():
    ticks = [
        {
            "timestamp": "t1",
            "orderbook": {
                "token_id": "tokenA",
                "book": {"bids": [{"price": 0.49}], "asks": [{"price": 0.51}]}
            }
        },
        {
            "timestamp": "t2",
            "orderbook": {
                "token_id": "tokenA",
                "book": {"bids": [{"price": 0.50}], "asks": [{"price": 0.52}]}
            }
        }
    ]
    config = type("DummyConfig", (), {
        "strategy": {
            "fair_value_window_trades": 1,
            "epsilon": 0.02,
            "tick_size": 0.01,
            "buy_aggression_ticks": 1,
            "sell_offset": 1,
            "taker_mode": False,
            "taker_max_spread": 0.03,
            "taker_min_edge": 0.01,
            "min_edge_to_trade": 0.0
        },
        "backtest": {
            "position_size": 10,
            "price_mode": "mid",
            "close_at_end": True,
            "strategy_mode": "mid",
            "mid_fair_value_window": 2,
            "epsilon_override": 0.002,
            "min_edge_override": 0.006
        }
    })()
    result = run_backtest(config, "tokenA", ticks)
    assert result.buy_yes == 0
    assert result.total_trades == 0
