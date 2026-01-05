import asyncio
import logging
import json
import os
import signal
import time
from datetime import datetime

from src.infra.config import load_config
from src.infra.logger import setup_logger
from src.bot.data_feed import DataFeed
from src.bot.strategy import Strategy
from src.bot.risk import RiskEngine
from src.bot.paper_sim import PaperExecutor
from src.bot.portfolio import Portfolio

from src.bot.live import LiveExecutor

logger = setup_logger("bot")

def _force_flatten_portfolio_token(portfolio: Portfolio, risk: RiskEngine, token_id: str, price: float) -> bool:
    position = portfolio.positions.get(token_id, 0)
    if position == 0:
        return False
    if price <= 0:
        logger.error(f"Cannot flatten {token_id}: missing price.")
        return False

    side = "SELL" if position > 0 else "BUY"
    size = abs(position)
    fill = {
        "order_id": f"flatten-{token_id}-{int(time.time())}",
        "token_id": token_id,
        "price": price,
        "size": size,
        "side": side,
        "timestamp": time.time()
    }
    portfolio.add_trade(fill)
    risk.update_fill(token_id, side, size, price)
    logger.warning(f"Flattened {token_id} position {position} @ {price}")
    return True

def apply_risk_limits(
    risk: RiskEngine,
    executor,
    portfolio: Portfolio,
    current_prices: dict,
    all_token_ids: list,
    mode: str,
    blocked_tokens: set
) -> tuple[bool, set]:
    halt_all, market_breaches = risk.get_limit_breaches()
    halted = False

    if halt_all:
        logger.error("Daily loss limit breached. Halting trading and cancelling orders.")
        for tid in all_token_ids:
            executor.cancel_all(tid)
        if mode == "paper":
            for tid in list(portfolio.positions.keys()):
                _force_flatten_portfolio_token(portfolio, risk, tid, current_prices.get(tid, 0))
        halted = True
        return halted, blocked_tokens

    if market_breaches:
        for tid in market_breaches:
            if tid in blocked_tokens:
                continue
            logger.warning(f"Market loss limit breached for {tid}. Cancelling orders and blocking token.")
            executor.cancel_all(tid)
            if mode == "paper":
                _force_flatten_portfolio_token(portfolio, risk, tid, current_prices.get(tid, 0))
            blocked_tokens.add(tid)

    return halted, blocked_tokens

async def shutdown(stop_event: asyncio.Event, signal=None):
    if signal:
        logger.info(f"Received exit signal {signal.name}...")
    stop_event.set()

async def _sleep_or_stop(stop_event: asyncio.Event, delay: float) -> bool:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=delay)
        return True
    except asyncio.TimeoutError:
        return False

def load_watchlist():
    path = "data/watchlist.json"
    if not os.path.exists(path):
        logger.error("No watchlist.json found. Run scanner first.")
        return []
    with open(path, 'r') as f:
        data = json.load(f)
        return data.get("markets", [])

async def main():
    config = load_config()
    markets = load_watchlist()
    if not markets:
        return

    # Subscribe to ALL tokens (YES and NO) for all markets
    all_token_ids = []
    market_map = {} # token_id -> market info
    for m in markets:
        ids = m.get("clob_token_ids", [])
        all_token_ids.extend(ids)
        for tid in ids:
            market_map[tid] = m
            
    logger.info(f"Loaded {len(markets)} markets, {len(all_token_ids)} tokens.")

    # Components
    feed = DataFeed(all_token_ids)
    strategy = Strategy(config, feed)
    risk = RiskEngine(config)
    blocked_tokens = set()
    signal_stats = {
        "total": 0,
        "buy_yes": 0,
        "buy_no": 0,
        "neutral": 0,
        "edge_sum": 0.0,
        "edge_count": 0,
        "eval_total": 0,
        "eval_wins": 0,
        "eval_losses": 0,
        "eval_move_sum": 0.0
    }
    pending_evals = {}
    last_live_poll = 0.0
    last_live_fill_ts = None
    live_poll_interval = config.execution.get("live_fill_poll_interval_sec", 5)
    
    # Mode check
    mode = config.mode
    executor = None
    if mode == "live":
        if os.getenv("ENABLE_LIVE_TRADING") != "true":
             logger.error("Live trading enabled in config but ENABLE_LIVE_TRADING env var not set. Exiting.")
             return
        logger.warning("!!! STARTING LIVE TRADING !!!")
        try:
            executor = LiveExecutor(risk, config._data)
        except Exception as e:
            logger.error(f"Failed to init Live Executor: {e}")
            return
    else:
        executor = PaperExecutor(risk)
        
    portfolio = Portfolio()
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        try:
            loop.add_signal_handler(
                s, lambda s=s: asyncio.create_task(shutdown(stop_event, signal=s)))
        except NotImplementedError:
            logger.warning("Signal handlers not supported in this environment.")
            break
    
    # Start Feed
    await feed.start()
    
    # Main Loop
    try:
        while True:
            if await _sleep_or_stop(stop_event, config.strategy.get("refresh_interval_sec", 1)):
                break
            now = time.time()
            
            # 1. Update Paper Sim with latest feed data (Simulate Fills)
            if mode == "paper":
                for tid in all_token_ids:
                    ob = feed.get_orderbook(tid)
                    if not ob: continue
                    best_bid = float(ob['bids'][0]['price']) if ob['bids'] else 0
                    best_ask = float(ob['asks'][0]['price']) if ob['asks'] else 0
                    trades = feed.get_trades(tid)
                    # PaperExecutor handles incremental trade processing.
                    executor.process_updates(tid, best_bid, best_ask, trades)

            # Check fills and update Portfolio
            if mode == "paper":
                # Collect fills from PaperExecutor
                while executor.fills:
                    fill = executor.fills.pop(0)
                    portfolio.add_trade(fill)
                    # logger.info(f"Portfolio Trade: {fill}")
            elif mode == "live" and hasattr(executor, "poll_fills"):
                if now - last_live_poll >= live_poll_interval:
                    live_fills = executor.poll_fills()
                    for fill in live_fills:
                        portfolio.add_trade(fill)
                        risk.update_fill(fill["token_id"], fill["side"], fill["size"], fill["price"])
                        last_live_fill_ts = fill.get("timestamp", last_live_fill_ts)
                    last_live_poll = now

            # 2. Update PnL + Risk (paper + live fills)
            current_prices = {}
            market_data = []
            for tid in all_token_ids:
                ob = feed.get_orderbook(tid)
                if ob and ob['bids'] and ob['asks']:
                    best_bid = float(ob['bids'][0]['price'])
                    best_ask = float(ob['asks'][0]['price'])
                    mid = (best_bid + best_ask) / 2
                    current_prices[tid] = mid
                    market_data.append({
                        "token_id": tid,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "mid": mid,
                        "spread": best_ask - best_bid
                    })

            pnl_data = portfolio.get_live_pnl(current_prices)
            for tid, data in pnl_data.items():
                risk.update_pnl(tid, data["realized"], data["unrealized"])

            halted, blocked_tokens = apply_risk_limits(
                risk,
                executor,
                portfolio,
                current_prices,
                all_token_ids,
                mode,
                blocked_tokens
            )
            if halted:
                break
            
            # 3. Strategy Validation (evaluate prior signals)
            eval_window_sec = config.strategy.get("evaluation_window_sec", 60)
            for token_id, entry in list(pending_evals.items()):
                if now - entry["timestamp"] < eval_window_sec:
                    continue
                current_mid = current_prices.get(token_id)
                if current_mid is None:
                    continue
                delta = current_mid - entry["entry_mid"]
                win = delta > 0 if entry["signal"] == "BUY_YES" else delta < 0
                signal_stats["eval_total"] += 1
                if win:
                    signal_stats["eval_wins"] += 1
                else:
                    signal_stats["eval_losses"] += 1
                signal_stats["eval_move_sum"] += delta
                del pending_evals[token_id]

            # 4. Strategy & Execution
            for m in markets:
                # Identify YES/NO tokens (required)
                yes_id = m.get("yes_token_id")
                no_id = m.get("no_token_id")
                if not yes_id or not no_id:
                    logger.warning(f"Skipping market {m.get('id')}: missing YES/NO token mapping. Re-run scanner.")
                    continue
                if yes_id in blocked_tokens or no_id in blocked_tokens:
                    continue
                
                # We analyze YES token for the "Fair Value" usually?
                # Or we analyze the spread?
                # Strategy logic was: "mid > fair + epsilon" -> Buy YES.
                # Use YES token for signal.
                details = strategy.get_signal_details(yes_id)
                raw_signal = details["signal"]
                edge = details.get("edge")
                mid = details.get("mid")

                min_edge_to_trade = config.strategy.get("min_edge_to_trade", 0.0)
                signal = raw_signal
                if signal != "NEUTRAL" and (edge is None or edge < min_edge_to_trade):
                    signal = "NEUTRAL"

                if signal == "BUY_YES":
                    signal_stats["buy_yes"] += 1
                elif signal == "BUY_NO":
                    signal_stats["buy_no"] += 1
                else:
                    signal_stats["neutral"] += 1
                signal_stats["total"] += 1

                if edge is not None:
                    signal_stats["edge_sum"] += edge
                    signal_stats["edge_count"] += 1

                eval_min_edge = config.strategy.get("min_edge_to_evaluate", min_edge_to_trade)
                if (
                    signal != "NEUTRAL"
                    and edge is not None
                    and edge >= eval_min_edge
                    and mid is not None
                    and yes_id not in pending_evals
                ):
                    pending_evals[yes_id] = {
                        "signal": signal,
                        "entry_mid": mid,
                        "timestamp": now
                    }
                
                target_token = None
                side = "BUY" # We always Accumulate (Buy) the winner
                
                if signal == "BUY_YES":
                    target_token = yes_id
                elif signal == "BUY_NO":
                    target_token = no_id
                else:
                     # Neutral. Cancel orders?
                     executor.cancel_all(yes_id)
                     executor.cancel_all(no_id)
                     continue

                # Prepare Quote
                # We want to Buy Target Token. 
                # Price? 
                # Strategy.get_quote_params returns (bid, ask) for specific token.
                # If we want to BUY target_token, we act as Bidder.
                # We can also be Market Maker -> Place Both Bid and Ask?
                # "accumulate winner" -> implies taking position in ONE direction.
                # But as MM we usually quote both?
                # Requirement: "biased market-making bot".
                # "skew quotes: aggressive buy, passive sell at premium".
                # So we DO quote both sides, but skewed.
                # If signal == BUY_YES -> Bid Aggressive on YES, Sell Passive on YES.
                # What about NO token?
                # If we are bullish YES, we are bearish NO.
                # So we could Sell NO Aggressive?
                # Let's stick to trading YES token for now to keep it simple, 
                # OR trade the target token (Accumulate meaning Net Long).
                
                # If Target is YES:
                # We Quote on YES token:
                #   Bid: Aggressive (High)
                #   Ask: Passive (High)
                
                quote_signal = "BUY_YES"
                # Always quote as BUY_YES on the selected token (accumulate winner).
                my_bid, my_ask = strategy.get_quote_params(target_token, quote_signal, edge=edge)
                # Wait, `get_quote_params` took Token ID and Signal. 
                # If I pass yes_id and BUY_YES -> it gives aggressive bid params.
                # If I pass no_id and BUY_NO -> (which means signal for YES was BUY_NO, so I pass BUY_NO to no_id?)
                # Actually logic in strategy:
                # `if signal == "BUY_YES": ...`
                # If I am processing `no_id` and signal is `BUY_NO` (aka YES is bad), does that mean `BUY_YES` for NO token?
                # Yes. (1 - P).
                # So if signal is BUY_NO (for YES token), it is effectively BUY_YES for NO token.
                
                # Refined Logic:
                # If Signal is BUY_YES -> Active on YES token.
                # If Signal is BUY_NO -> Active on NO token.
                
                # Cancel existing on target
                # (Simple cancel/replace)
                # Cancel existing on target if price/size logic requires update
                # (Simple cancel/replace with idempotency check)
                existing_orders = executor.get_open_orders(target_token)
                
                size = config.execution.get("order_size_shares", 10)
                
                # Check Buys
                if my_bid:
                    current_buy = next((o for o in existing_orders if o.side == "BUY"), None)
                    if current_buy:
                        # Check if we need to update
                        if abs(float(current_buy.price) - my_bid) < 0.001 and float(current_buy.size) == size:
                            # Same price and size, skip
                            pass
                        else:
                            # Cancel and Replace
                            executor.cancel_order(current_buy.id)
                            executor.place_order(target_token, "BUY", my_bid, size)
                    else:
                        # No existing buy, place new
                        executor.place_order(target_token, "BUY", my_bid, size)

                # Check Sells
                if my_ask:
                    current_sell = next((o for o in existing_orders if o.side == "SELL"), None)
                    if current_sell:
                         if abs(float(current_sell.price) - my_ask) < 0.001 and float(current_sell.size) == size:
                             pass
                         else:
                             executor.cancel_order(current_sell.id)
                             executor.place_order(target_token, "SELL", my_ask, size)
                    else:
                         executor.place_order(target_token, "SELL", my_ask, size)
            
            # 5. Live Dashboard
            # Print summary every 10 seconds or so? 
            # Or just every loop since refresh is 1s? 
            # Maybe too spammy. Let's do every 10 iterations.
            
            # Using a static counter embedded in loop or time check
            if not hasattr(main, "last_print"):
                main.last_print = 0
            
            if datetime.now().timestamp() - main.last_print > 5:
                # Dashboard Export
                try:
                    # Export state
                    all_open_orders = []
                    order_cache_state = {}
                    # Gather open orders (simulated or live)
                    # Executor methods need to support getting all? 
                    # Right now we only get by Token ID.
                    # We can iterate markets or just use `executor.orders.values()` if paper.
                    # Let's verify what executor supports.
                    # PaperExecutor has self.orders. LiveExecutor needs API call?
                    # For Live, getting all open orders might be expensive.
                    # But if we track them locally...
                    # Let's stick to Paper mode support for now easily:
                    if mode == "paper":
                        all_open_orders = [o.__dict__ for o in executor.orders.values() if o.status == "OPEN"]
                    elif mode == "live" and hasattr(executor, "refresh_open_orders"):
                        refresh_interval = config.execution.get("live_order_cache_refresh_sec", 30)
                        executor.refresh_open_orders(all_token_ids, min_interval_sec=refresh_interval)
                        all_open_orders = [o.__dict__ for o in executor.get_cached_open_orders()]
                        if hasattr(executor, "get_order_cache_state"):
                            order_cache_state = executor.get_order_cache_state()
                    
                    eval_total = signal_stats["eval_total"]
                    eval_win_rate = (signal_stats["eval_wins"] / eval_total) if eval_total else 0.0
                    avg_edge = (
                        signal_stats["edge_sum"] / signal_stats["edge_count"]
                        if signal_stats["edge_count"]
                        else 0.0
                    )
                    avg_eval_move = (
                        signal_stats["eval_move_sum"] / eval_total if eval_total else 0.0
                    )

                    state = {
                        "timestamp": datetime.now().isoformat(),
                        "status": "RUNNING",
                        "market_mode": mode,
                        "pnl_summary": {
                            "total": sum(d['total'] for d in pnl_data.values()),
                            "realized": sum(d['realized'] for d in pnl_data.values()),
                            "unrealized": sum(d['unrealized'] for d in pnl_data.values())
                        },
                        "positions": [
                            {
                                "token_id": tid,
                                "position": d['position'],
                                "avg_entry": d['avg_entry'],
                                "current_price": current_prices.get(tid, 0),
                                "pnl": d['total']
                            }
                            for tid, d in pnl_data.items() if d['position'] != 0 or d['total'] != 0
                        ],
                        "recent_trades": portfolio.history[-50:], # Last 50 trades
                        "open_orders": all_open_orders,
                        "market_data": market_data,
                        "strategy_stats": {
                            "signals_total": signal_stats["total"],
                            "signals_buy_yes": signal_stats["buy_yes"],
                            "signals_buy_no": signal_stats["buy_no"],
                            "signals_neutral": signal_stats["neutral"],
                            "avg_edge": avg_edge,
                            "eval_total": eval_total,
                            "eval_wins": signal_stats["eval_wins"],
                            "eval_losses": signal_stats["eval_losses"],
                            "eval_win_rate": eval_win_rate,
                            "eval_avg_move": avg_eval_move,
                            "pending_evals": len(pending_evals)
                        },
                        "live_reconciliation": {
                            "last_poll_ts": last_live_poll,
                            "last_fill_ts": last_live_fill_ts,
                            "poll_interval_sec": live_poll_interval
                        },
                        "live_order_cache": order_cache_state
                    }
                    
                    with open("data/live_state.json", "w") as f:
                        json.dump(state, f, indent=2)
                        
                except Exception as e:
                    logger.error(f"Failed to export state: {e}")

                status = portfolio.get_summary_text(current_prices)
                if "No positions" not in status: # Only print if interesting
                    print("\n=== LIVE PnL REPORT ===")
                    print(status)
                    print("=======================\n")
                main.last_print = datetime.now().timestamp()

    except asyncio.CancelledError:
        logger.info("Main loop cancelled")
    finally:
        await feed.stop()
        # Export
        portfolio.export_csv(f"data/session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        logger.info(portfolio.get_summary())

if __name__ == "__main__":
    asyncio.run(main())
