import json
import os
from dataclasses import dataclass
from typing import Dict, List, Any

from src.bot.strategy import Strategy
from src.infra.config import Config


@dataclass
class BacktestTrade:
    token_id: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    entry_ts: str
    exit_ts: str
    signal: str


@dataclass
class BacktestResult:
    total_ticks: int
    buy_yes: int
    buy_no: int
    neutral: int
    avg_edge: float
    total_trades: int
    win_rate: float
    total_pnl: float
    avg_pnl_per_trade: float
    trades: List[BacktestTrade]
    equity_curve: List[Dict[str, Any]]


class BacktestFeed:
    def __init__(self, ticks: List[Dict]):
        self.ticks = ticks
        self.index = -1
        self._orderbook = None
        self._trades = []

    def step(self) -> bool:
        self.index += 1
        if self.index >= len(self.ticks):
            return False
        tick = self.ticks[self.index]
        self._orderbook = tick.get("orderbook")
        self._trades = tick.get("trades", [])
        return True

    def get_orderbook(self, token_id: str):
        if not self._orderbook:
            return None
        if self._orderbook.get("token_id") != token_id:
            return None
        return self._orderbook.get("book")

    def get_trades(self, token_id: str):
        if not self._orderbook or self._orderbook.get("token_id") != token_id:
            return []
        return self._trades


def load_ticks(path: str) -> List[Dict]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Backtest data not found: {path}")
    with open(path, "r") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Backtest data must be a list of ticks")
    return data


def run_backtest(config: Config, token_id: str, ticks: List[Dict]) -> BacktestResult:
    feed = BacktestFeed(ticks)
    strategy = Strategy(config, feed)

    buy_yes = 0
    buy_no = 0
    neutral = 0
    edge_sum = 0.0
    edge_count = 0
    total_ticks = 0
    trades: List[BacktestTrade] = []
    total_pnl = 0.0
    realized_pnl = 0.0
    equity_curve: List[Dict[str, Any]] = []

    backtest_cfg = _get_config_section(config, "backtest")
    execution_cfg = _get_config_section(config, "execution")
    position_size = backtest_cfg.get("position_size", execution_cfg.get("order_size_shares", 10))
    price_mode = backtest_cfg.get("price_mode", "mid")
    close_at_end = backtest_cfg.get("close_at_end", True)
    current_position = 0.0
    entry_price = None
    entry_ts = None
    entry_signal = None
    last_prices = None

    strategy_cfg = _get_config_section(config, "strategy")
    min_edge_to_trade = strategy_cfg.get("min_edge_to_trade", 0.0)

    while feed.step():
        total_ticks += 1
        details = strategy.get_signal_details(token_id)
        signal = details["signal"]
        edge = details.get("edge")
        tick = feed.ticks[feed.index]

        if signal != "NEUTRAL" and (edge is None or edge < min_edge_to_trade):
            signal = "NEUTRAL"

        if signal == "BUY_YES":
            buy_yes += 1
        elif signal == "BUY_NO":
            buy_no += 1
        else:
            neutral += 1

        if edge is not None:
            edge_sum += edge
            edge_count += 1

        orderbook = feed.get_orderbook(token_id)
        if not orderbook or not orderbook.get("bids") or not orderbook.get("asks"):
            continue

        best_bid = float(orderbook["bids"][0]["price"])
        best_ask = float(orderbook["asks"][0]["price"])
        last_prices = (best_bid, best_ask, tick.get("timestamp"))

        desired_position = 0.0
        if signal == "BUY_YES":
            desired_position = float(position_size)
        elif signal == "BUY_NO":
            desired_position = -float(position_size)

        if current_position != desired_position:
            if current_position != 0 and entry_price is not None:
                exit_side = "SELL" if current_position > 0 else "BUY"
                exit_price = _price_for(exit_side, best_bid, best_ask, price_mode)
                pnl = (exit_price - entry_price) * current_position
                total_pnl += pnl
                realized_pnl += pnl
                trades.append(BacktestTrade(
                    token_id=token_id,
                    side="LONG" if current_position > 0 else "SHORT",
                    size=abs(current_position),
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=pnl,
                    entry_ts=entry_ts or "",
                    exit_ts=str(tick.get("timestamp") or ""),
                    signal=entry_signal or "UNKNOWN"
                ))

            if desired_position != 0:
                entry_side = "BUY" if desired_position > 0 else "SELL"
                entry_price = _price_for(entry_side, best_bid, best_ask, price_mode)
                entry_ts = str(tick.get("timestamp") or "")
                entry_signal = signal
            else:
                entry_price = None
                entry_ts = None
                entry_signal = None

            current_position = desired_position

        mid = (best_bid + best_ask) / 2
        unrealized = 0.0
        if current_position != 0 and entry_price is not None:
            unrealized = (mid - entry_price) * current_position
        equity_curve.append({
            "timestamp": tick.get("timestamp"),
            "position": current_position,
            "mid": mid,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized,
            "equity": realized_pnl + unrealized
        })

    if close_at_end and current_position != 0 and entry_price is not None and last_prices:
        best_bid, best_ask, ts = last_prices
        exit_side = "SELL" if current_position > 0 else "BUY"
        exit_price = _price_for(exit_side, best_bid, best_ask, price_mode)
        pnl = (exit_price - entry_price) * current_position
        total_pnl += pnl
        realized_pnl += pnl
        trades.append(BacktestTrade(
            token_id=token_id,
            side="LONG" if current_position > 0 else "SHORT",
            size=abs(current_position),
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            entry_ts=entry_ts or "",
            exit_ts=str(ts or ""),
            signal=entry_signal or "UNKNOWN"
        ))

    avg_edge = edge_sum / edge_count if edge_count else 0.0
    total_trades = len(trades)
    wins = len([t for t in trades if t.pnl > 0])
    win_rate = wins / total_trades if total_trades else 0.0
    avg_pnl = total_pnl / total_trades if total_trades else 0.0
    return BacktestResult(
        total_ticks=total_ticks,
        buy_yes=buy_yes,
        buy_no=buy_no,
        neutral=neutral,
        avg_edge=avg_edge,
        total_trades=total_trades,
        win_rate=win_rate,
        total_pnl=total_pnl,
        avg_pnl_per_trade=avg_pnl,
        trades=trades,
        equity_curve=equity_curve
    )


def _get_config_section(config: Any, name: str) -> Dict:
    if hasattr(config, name):
        value = getattr(config, name)
        if isinstance(value, dict):
            return value
    if hasattr(config, "_data"):
        return config._data.get(name, {})
    return {}


def _price_for(side: str, best_bid: float, best_ask: float, mode: str) -> float:
    if mode == "conservative":
        return best_ask if side == "BUY" else best_bid
    return (best_bid + best_ask) / 2
