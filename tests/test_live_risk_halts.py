from main_bot import apply_risk_limits
from src.bot.portfolio import Portfolio
from src.bot.risk import RiskEngine
from fakes import FakeLiveExecutor


class DummyConfig:
    def __init__(self, risk):
        self.risk = risk


def _make_risk():
    return RiskEngine(DummyConfig({
        "daily_max_loss_usd": 50.0,
        "market_max_loss_usd": 10.0,
        "max_total_inventory": 100,
        "cooldown_after_flip_sec": 0
    }))


def test_live_daily_halt_cancels_orders():
    risk = _make_risk()
    executor = FakeLiveExecutor()
    portfolio = Portfolio()
    portfolio.positions["tokA"] = 5

    risk.update_pnl("tokA", -60.0, 0.0)
    current_prices = {"tokA": 0.5}
    halted, blocked = apply_risk_limits(
        risk,
        executor,
        portfolio,
        current_prices,
        ["tokA", "tokB"],
        "live",
        set()
    )

    assert halted is True
    assert set(executor.cancel_all_calls) == {"tokA", "tokB"}
    assert portfolio.positions["tokA"] == 5
    assert blocked == set()


def test_live_market_halt_blocks_token():
    risk = _make_risk()
    executor = FakeLiveExecutor()
    portfolio = Portfolio()
    portfolio.positions["tokA"] = 5

    risk.update_pnl("tokA", -5.0, -6.0)
    current_prices = {"tokA": 0.5}
    halted, blocked = apply_risk_limits(
        risk,
        executor,
        portfolio,
        current_prices,
        ["tokA", "tokB"],
        "live",
        set()
    )

    assert halted is False
    assert executor.cancel_all_calls == ["tokA"]
    assert portfolio.positions["tokA"] == 5
    assert "tokA" in blocked
