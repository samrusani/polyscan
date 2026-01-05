import json
import os
import tempfile

from src.backtest.runner import load_ticks, run_backtest


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
        config = type("DummyConfig", (), {"strategy": {
            "fair_value_window_trades": 1,
            "epsilon": 0.01,
            "tick_size": 0.01,
            "buy_aggression_ticks": 1,
            "sell_offset": 1,
            "taker_mode": False,
            "taker_max_spread": 0.03,
            "taker_min_edge": 0.01
        }})()
        result = run_backtest(config, "tokenA", load_ticks(path))
    finally:
        os.unlink(path)
    assert result.total_ticks == 2
    assert result.total_trades == 1
    assert len(result.trades) == 1
    assert len(result.equity_curve) == 2
