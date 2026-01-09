import json
import os
from dataclasses import dataclass
from typing import Dict, List, Any, Iterable, Optional

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
    fees: float
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
    fees_paid: float
    trades: List[BacktestTrade]
    equity_curve: List[Dict[str, Any]]


class BacktestFeed:
    def __init__(self, ticks: List[Dict], trade_history_limit: int = 100):
        self.ticks = ticks
        self.index = -1
        self._orderbooks: Dict[str, Dict] = {}
        self._trades_by_token: Dict[str, List[Dict]] = {}
        self._trade_history_limit = trade_history_limit
        self._timestamp = None

    def step(self) -> bool:
        self.index += 1
        if self.index >= len(self.ticks):
            return False
        tick = self.ticks[self.index]
        self._timestamp = tick.get("timestamp")
        self._orderbooks = {}
        new_trades: Dict[str, List[Dict]] = {}

        for token_id, book in _extract_orderbooks(tick):
            if token_id and book:
                self._orderbooks[token_id] = book

        for token_id, trades in _extract_trades(tick, self._orderbooks):
            if not token_id or not trades:
                continue
            bucket = new_trades.setdefault(token_id, [])
            bucket.extend(trades)

        for token_id, trades in new_trades.items():
            history = self._trades_by_token.setdefault(token_id, [])
            history.extend(trades)
            if self._trade_history_limit and len(history) > self._trade_history_limit:
                self._trades_by_token[token_id] = history[-self._trade_history_limit:]
        return True

    def get_orderbook(self, token_id: str):
        return self._orderbooks.get(token_id)

    def get_trades(self, token_id: str):
        return self._trades_by_token.get(token_id, [])

    @property
    def timestamp(self) -> Optional[str]:
        return self._timestamp


def load_ticks(path: str) -> List[Dict]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Backtest data not found: {path}")
    with open(path, "r") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Backtest data must be a list of ticks")
    return data


def infer_token_ids(ticks: List[Dict[str, Any]]) -> List[str]:
    token_ids: List[str] = []
    for tick in ticks:
        for token_id, _ in _extract_orderbooks(tick):
            if token_id and token_id not in token_ids:
                token_ids.append(token_id)
        for token_id, _ in _extract_trades(tick, {}):
            if token_id and token_id not in token_ids:
                token_ids.append(token_id)
    return token_ids


@dataclass
class MultiBacktestResult:
    total_ticks: int
    buy_yes: int
    buy_no: int
    neutral: int
    avg_edge: float
    total_trades: int
    win_rate: float
    total_pnl: float
    avg_pnl_per_trade: float
    fees_paid: float
    trades: List[BacktestTrade]
    equity_curve: List[Dict[str, Any]]
    per_token: Dict[str, BacktestResult]


def run_backtest(config: Config, token_id: str, ticks: List[Dict]) -> BacktestResult:
    multi = run_backtest_multi(config, [token_id], ticks)
    single = multi.per_token[token_id]
    single.equity_curve = multi.equity_curve
    return single


def run_backtest_multi(config: Config, token_ids: Iterable[str], ticks: List[Dict]) -> MultiBacktestResult:
    token_list = [t for t in token_ids if t]
    if not token_list:
        raise ValueError("At least one token_id is required for backtest.")

    backtest_cfg = _get_config_section(config, "backtest")
    execution_cfg = _get_config_section(config, "execution")
    strategy_cfg = _get_config_section(config, "strategy")
    strategy_cfg_override = dict(strategy_cfg)

    epsilon_override = backtest_cfg.get("epsilon_override")
    if epsilon_override is not None:
        strategy_cfg_override["epsilon"] = float(epsilon_override)

    trade_history_limit = int(backtest_cfg.get("trade_history_limit", 100))
    feed = BacktestFeed(ticks, trade_history_limit=trade_history_limit)
    strategy_config = config
    if epsilon_override is not None:
        strategy_config = type("StrategyConfigView", (), {"strategy": strategy_cfg_override})()
    strategy = Strategy(strategy_config, feed)

    buy_yes_total = 0
    buy_no_total = 0
    neutral_total = 0
    edge_sum_total = 0.0
    edge_count_total = 0
    total_ticks = 0
    total_pnl = 0.0
    total_fees = 0.0
    trades_all: List[BacktestTrade] = []
    equity_curve: List[Dict[str, Any]] = []

    position_size = backtest_cfg.get("position_size", execution_cfg.get("order_size_shares", 10))
    price_mode = backtest_cfg.get("price_mode", "mid")
    close_at_end = backtest_cfg.get("close_at_end", True)
    fee_bps = float(backtest_cfg.get("fee_bps", 0.0))
    slippage_bps = float(backtest_cfg.get("slippage_bps", 0.0))
    slippage_ticks = float(backtest_cfg.get("slippage_ticks", 0.0))
    tick_size = float(strategy_cfg_override.get("tick_size", 0.01))
    min_edge_to_trade = strategy_cfg_override.get("min_edge_to_trade", 0.0)
    min_edge_override = backtest_cfg.get("min_edge_override")
    if min_edge_override is not None:
        min_edge_to_trade = float(min_edge_override)
    strategy_mode = backtest_cfg.get("strategy_mode", "live")
    mid_window = int(backtest_cfg.get("mid_fair_value_window", 20))

    token_state: Dict[str, Dict[str, Any]] = {}
    for token_id in token_list:
        token_state[token_id] = {
            "buy_yes": 0,
            "buy_no": 0,
            "neutral": 0,
            "edge_sum": 0.0,
            "edge_count": 0,
            "trades": [],
            "current_position": 0.0,
            "entry_price": None,
            "entry_ts": None,
            "entry_signal": None,
            "open_fee": 0.0,
            "realized_pnl": 0.0,
            "fees_paid": 0.0,
            "last_prices": None,
            "last_mid": None
        }

    while feed.step():
        total_ticks += 1
        tick = feed.ticks[feed.index]
        total_realized = 0.0
        total_unrealized = 0.0

        for token_id in token_list:
            state = token_state[token_id]
            if strategy_mode == "mid":
                signal, edge = _get_mid_signal(state, token_id, feed, mid_window, strategy_cfg_override)
            else:
                details = strategy.get_signal_details(token_id)
                signal = details["signal"]
                edge = details.get("edge")

            if signal != "NEUTRAL" and (edge is None or edge < min_edge_to_trade):
                signal = "NEUTRAL"

            if signal == "BUY_YES":
                state["buy_yes"] += 1
                buy_yes_total += 1
            elif signal == "BUY_NO":
                state["buy_no"] += 1
                buy_no_total += 1
            else:
                state["neutral"] += 1
                neutral_total += 1

            if edge is not None:
                state["edge_sum"] += edge
                state["edge_count"] += 1
                edge_sum_total += edge
                edge_count_total += 1

            orderbook = feed.get_orderbook(token_id)
            if not orderbook or not orderbook.get("bids") or not orderbook.get("asks"):
                unrealized = 0.0
                if state["current_position"] != 0 and state["entry_price"] is not None and state["last_mid"] is not None:
                    unrealized = (state["last_mid"] - state["entry_price"]) * state["current_position"]
                    unrealized -= state["open_fee"]
                total_realized += state["realized_pnl"]
                total_unrealized += unrealized
                continue

            best_bid = float(orderbook["bids"][0]["price"])
            best_ask = float(orderbook["asks"][0]["price"])
            state["last_prices"] = (best_bid, best_ask, tick.get("timestamp"))

            desired_position = 0.0
            if signal == "BUY_YES":
                desired_position = float(position_size)
            elif signal == "BUY_NO":
                desired_position = -float(position_size)

            current_position = state["current_position"]
            entry_price = state["entry_price"]

            if current_position != desired_position:
                if current_position != 0 and entry_price is not None:
                    exit_side = "SELL" if current_position > 0 else "BUY"
                    exit_price = _price_for(exit_side, best_bid, best_ask, price_mode)
                    exit_price = _apply_slippage(exit_price, exit_side, slippage_bps, slippage_ticks, tick_size)
                    exit_fee = _calc_fee(exit_price, abs(current_position), fee_bps)
                    entry_fee = state["open_fee"]
                    fees_paid = entry_fee + exit_fee
                    pnl = (exit_price - entry_price) * current_position - fees_paid
                    total_pnl += pnl
                    total_fees += fees_paid
                    state["realized_pnl"] += pnl
                    state["fees_paid"] += fees_paid
                    trade = BacktestTrade(
                        token_id=token_id,
                        side="LONG" if current_position > 0 else "SHORT",
                        size=abs(current_position),
                        entry_price=entry_price,
                        exit_price=exit_price,
                        pnl=pnl,
                        fees=fees_paid,
                        entry_ts=state["entry_ts"] or "",
                        exit_ts=str(tick.get("timestamp") or ""),
                        signal=state["entry_signal"] or "UNKNOWN"
                    )
                    state["trades"].append(trade)
                    trades_all.append(trade)

                if desired_position != 0:
                    entry_side = "BUY" if desired_position > 0 else "SELL"
                    entry_price = _price_for(entry_side, best_bid, best_ask, price_mode)
                    entry_price = _apply_slippage(entry_price, entry_side, slippage_bps, slippage_ticks, tick_size)
                    entry_fee = _calc_fee(entry_price, abs(desired_position), fee_bps)
                    state["entry_price"] = entry_price
                    state["entry_ts"] = str(tick.get("timestamp") or "")
                    state["entry_signal"] = signal
                    state["open_fee"] = entry_fee
                else:
                    state["entry_price"] = None
                    state["entry_ts"] = None
                    state["entry_signal"] = None
                    state["open_fee"] = 0.0

                state["current_position"] = desired_position

            mid = (best_bid + best_ask) / 2
            state["last_mid"] = mid
            unrealized = 0.0
            if state["current_position"] != 0 and state["entry_price"] is not None:
                unrealized = (mid - state["entry_price"]) * state["current_position"]
                unrealized -= state["open_fee"]
            total_realized += state["realized_pnl"]
            total_unrealized += unrealized

        equity_curve.append({
            "timestamp": tick.get("timestamp"),
            "realized_pnl": total_realized,
            "unrealized_pnl": total_unrealized,
            "equity": total_realized + total_unrealized
        })

    if close_at_end:
        for token_id in token_list:
            state = token_state[token_id]
            current_position = state["current_position"]
            entry_price = state["entry_price"]
            last_prices = state["last_prices"]
            if current_position == 0 or entry_price is None or not last_prices:
                continue
            best_bid, best_ask, ts = last_prices
            exit_side = "SELL" if current_position > 0 else "BUY"
            exit_price = _price_for(exit_side, best_bid, best_ask, price_mode)
            exit_price = _apply_slippage(exit_price, exit_side, slippage_bps, slippage_ticks, tick_size)
            exit_fee = _calc_fee(exit_price, abs(current_position), fee_bps)
            entry_fee = state["open_fee"]
            fees_paid = entry_fee + exit_fee
            pnl = (exit_price - entry_price) * current_position - fees_paid
            total_pnl += pnl
            total_fees += fees_paid
            state["realized_pnl"] += pnl
            state["fees_paid"] += fees_paid
            trade = BacktestTrade(
                token_id=token_id,
                side="LONG" if current_position > 0 else "SHORT",
                size=abs(current_position),
                entry_price=entry_price,
                exit_price=exit_price,
                pnl=pnl,
                fees=fees_paid,
                entry_ts=state["entry_ts"] or "",
                exit_ts=str(ts or ""),
                signal=state["entry_signal"] or "UNKNOWN"
            )
            state["trades"].append(trade)
            trades_all.append(trade)
            state["current_position"] = 0.0
            state["entry_price"] = None
            state["entry_ts"] = None
            state["entry_signal"] = None
            state["open_fee"] = 0.0

    per_token: Dict[str, BacktestResult] = {}
    for token_id in token_list:
        state = token_state[token_id]
        avg_edge = state["edge_sum"] / state["edge_count"] if state["edge_count"] else 0.0
        total_trades = len(state["trades"])
        wins = len([t for t in state["trades"] if t.pnl > 0])
        win_rate = wins / total_trades if total_trades else 0.0
        avg_pnl = state["realized_pnl"] / total_trades if total_trades else 0.0
        per_token[token_id] = BacktestResult(
            total_ticks=total_ticks,
            buy_yes=state["buy_yes"],
            buy_no=state["buy_no"],
            neutral=state["neutral"],
            avg_edge=avg_edge,
            total_trades=total_trades,
            win_rate=win_rate,
            total_pnl=state["realized_pnl"],
            avg_pnl_per_trade=avg_pnl,
            fees_paid=state["fees_paid"],
            trades=state["trades"],
            equity_curve=[]
        )

    avg_edge_total = edge_sum_total / edge_count_total if edge_count_total else 0.0
    total_trades = len(trades_all)
    wins_total = len([t for t in trades_all if t.pnl > 0])
    win_rate_total = wins_total / total_trades if total_trades else 0.0
    avg_pnl_total = total_pnl / total_trades if total_trades else 0.0
    return MultiBacktestResult(
        total_ticks=total_ticks,
        buy_yes=buy_yes_total,
        buy_no=buy_no_total,
        neutral=neutral_total,
        avg_edge=avg_edge_total,
        total_trades=total_trades,
        win_rate=win_rate_total,
        total_pnl=total_pnl,
        avg_pnl_per_trade=avg_pnl_total,
        fees_paid=total_fees,
        trades=trades_all,
        equity_curve=equity_curve,
        per_token=per_token
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


def _apply_slippage(price: float, side: str, slippage_bps: float, slippage_ticks: float, tick_size: float) -> float:
    slippage = 0.0
    if slippage_bps:
        slippage += price * slippage_bps / 10000.0
    if slippage_ticks:
        slippage += slippage_ticks * tick_size
    if side == "BUY":
        return price + slippage
    return price - slippage


def _calc_fee(price: float, size: float, fee_bps: float) -> float:
    if not fee_bps:
        return 0.0
    return abs(price * size) * fee_bps / 10000.0


def _get_mid_signal(state: Dict[str, Any], token_id: str, feed: BacktestFeed, window: int, strategy_cfg: Dict[str, Any]) -> tuple[str, Optional[float]]:
    orderbook = feed.get_orderbook(token_id)
    if not orderbook or not orderbook.get("bids") or not orderbook.get("asks"):
        return "NEUTRAL", None

    best_bid = float(orderbook["bids"][0]["price"])
    best_ask = float(orderbook["asks"][0]["price"])
    mid = (best_bid + best_ask) / 2

    history = state.setdefault("mid_history", [])
    history.append(mid)
    if window and len(history) > window:
        del history[:-window]

    if not history:
        return "NEUTRAL", None

    fair = sum(history) / len(history)
    epsilon = float(strategy_cfg.get("epsilon", 0.02))
    edge = abs(mid - fair)

    if mid > fair + epsilon:
        return "BUY_YES", edge
    if mid < fair - epsilon:
        return "BUY_NO", edge
    return "NEUTRAL", edge


def _extract_orderbooks(tick: Dict[str, Any]) -> List[tuple]:
    results = []
    if "orderbook" in tick and isinstance(tick["orderbook"], dict):
        ob = tick["orderbook"]
        results.append((ob.get("token_id"), ob.get("book")))
    if "orderbooks" in tick and isinstance(tick["orderbooks"], list):
        for ob in tick["orderbooks"]:
            if not isinstance(ob, dict):
                continue
            results.append((ob.get("token_id"), ob.get("book")))
    return results


def _extract_trades(tick: Dict[str, Any], orderbooks: Dict[str, Dict]) -> List[tuple]:
    results = []
    default_token = None
    if orderbooks and len(orderbooks) == 1:
        default_token = next(iter(orderbooks.keys()))
    if isinstance(tick.get("token_id"), str):
        default_token = default_token or tick.get("token_id")

    if isinstance(tick.get("trades_by_token"), dict):
        for token_id, trades in tick["trades_by_token"].items():
            if isinstance(trades, list):
                results.append((token_id, trades))

    trades = tick.get("trades", [])
    if isinstance(trades, list):
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            token_id = trade.get("token_id") or default_token
            results.append((token_id, [trade]))

    return results
