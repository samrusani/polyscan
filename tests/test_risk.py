from src.bot.risk import RiskEngine


class DummyConfig:
    def __init__(self, risk):
        self.risk = risk


def test_daily_loss_blocks_orders():
    config = DummyConfig({
        "daily_max_loss_usd": 50.0,
        "market_max_loss_usd": 10.0,
        "max_total_inventory": 100,
        "cooldown_after_flip_sec": 0
    })
    risk = RiskEngine(config)
    risk.update_pnl("tokA", -60.0, 0.0)
    assert risk.check_new_order("tokA", "BUY", 1, 0.5) is False


def test_market_loss_blocks_orders():
    config = DummyConfig({
        "daily_max_loss_usd": 50.0,
        "market_max_loss_usd": 10.0,
        "max_total_inventory": 100,
        "cooldown_after_flip_sec": 0
    })
    risk = RiskEngine(config)
    risk.update_pnl("tokA", -5.0, -6.0)
    assert risk.check_new_order("tokA", "BUY", 1, 0.5) is False


def test_inventory_limits_enforced():
    config = DummyConfig({
        "daily_max_loss_usd": 50.0,
        "market_max_loss_usd": 10.0,
        "max_total_inventory": 5,
        "cooldown_after_flip_sec": 0
    })
    risk = RiskEngine(config)
    risk.inventory["tokA"] = 4
    assert risk.check_new_order("tokA", "BUY", 2, 0.5) is False


def test_limit_breaches_reported():
    config = DummyConfig({
        "daily_max_loss_usd": 50.0,
        "market_max_loss_usd": 10.0,
        "max_total_inventory": 100,
        "cooldown_after_flip_sec": 0
    })
    risk = RiskEngine(config)
    risk.update_pnl("tokA", -5.0, -6.0)
    risk.update_pnl("tokB", -60.0, 0.0)
    halt_all, market_breaches = risk.get_limit_breaches()
    assert halt_all is True
    assert "tokA" in market_breaches
