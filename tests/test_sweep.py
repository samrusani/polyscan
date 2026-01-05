from src.backtest.sweep import run_sweep


def test_run_sweep_outputs_rows():
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
                "book": {"bids": [{"price": 0.50}], "asks": [{"price": 0.52}]}
            },
            "trades": [{"price": 0.45, "size": 1}]
        }
    ]
    config_data = {
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
            "close_at_end": True
        }
    }
    sweep = {"strategy.epsilon": [0.01, 0.02]}
    results = run_sweep(config_data, ticks, ["tokenA"], sweep)
    assert len(results) == 2
    assert "param_strategy.epsilon" in results[0]
