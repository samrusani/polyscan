from src.bot.paper_sim import PaperExecutor
from src.bot.risk import RiskEngine


class DummyConfig:
    def __init__(self, risk):
        self.risk = risk


def _make_risk():
    return RiskEngine(DummyConfig({
        "daily_max_loss_usd": 1000.0,
        "market_max_loss_usd": 1000.0,
        "max_total_inventory": 1000,
        "cooldown_after_flip_sec": 0
    }))


def test_paper_sim_fills_once_on_trade_history():
    risk = _make_risk()
    executor = PaperExecutor(risk)

    order = executor.place_order("tokA", "BUY", 0.5, 10)
    assert order is not None

    trades = [{"price": 0.49, "size": 5}]
    executor.process_updates("tokA", best_bid=0.48, best_ask=0.6, trades=trades)
    assert len(executor.fills) == 1

    executor.process_updates("tokA", best_bid=0.48, best_ask=0.6, trades=trades)
    assert len(executor.fills) == 1


def test_paper_sim_fills_on_book_cross():
    risk = _make_risk()
    executor = PaperExecutor(risk)

    order = executor.place_order("tokA", "BUY", 0.5, 10)
    assert order is not None

    executor.process_updates("tokA", best_bid=0.48, best_ask=0.5, trades=[])
    assert len(executor.fills) == 1
