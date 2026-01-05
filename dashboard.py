import streamlit as st
import pandas as pd
import json
import time
import os
from datetime import datetime
import plotly.express as px

st.set_page_config(
    page_title="Polymarket Bot Dashboard",
    page_icon="📈",
    layout="wide",
)

STATE_FILE = "data/live_state.json"

@st.cache_data(ttl=2)
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        return {"error": str(e)}

def main():
    st.title("Polymarket Bot Dashboard 🤖")

    # Auto-refresh logic


    state = load_state()
    
    if not state:
        st.warning("Waiting for Bot State... (Is `main_bot.py` running?)")
        return

    if "error" in state:
        st.error(f"Error reading state: {state['error']}")
        return

    # Header Stats
    col1, col2, col3, col4 = st.columns(4)
    
    ts = datetime.fromisoformat(state.get("timestamp", datetime.now().isoformat()))
    ago = (datetime.now() - ts).total_seconds()
    
    with col1:
        st.metric("Status", state.get("status", "UNKNOWN"), f"Last update: {ago:.1f}s ago")
    
    pnl = state.get("pnl_summary", {})
    with col2:
        st.metric("Total PnL", f"${pnl.get('total', 0):.2f}")
    with col3:
        st.metric("Realized PnL", f"${pnl.get('realized', 0):.2f}")
    with col4:
        st.metric("Unrealized PnL", f"${pnl.get('unrealized', 0):.2f}")

    # Staleness banners
    now = time.time()
    recon = state.get("live_reconciliation", {})
    cache_state = state.get("live_order_cache", {})

    poll_interval = recon.get("poll_interval_sec", 5)
    last_poll = recon.get("last_poll_ts")
    last_fill = recon.get("last_fill_ts")
    if last_poll:
        poll_age = now - last_poll
        if poll_age > poll_interval * 3:
            st.warning(f"Live reconciliation poll is stale: {poll_age:.1f}s since last poll.")

    if last_fill:
        fill_age = now - last_fill
        if fill_age > 3600:
            st.warning(f"No live fills in {fill_age / 3600:.1f}h.")

    cache_refresh = cache_state.get("last_refresh_ts")
    if cache_refresh:
        cache_age = now - cache_refresh
        if cache_age > 180:
            st.warning(f"Order cache refresh is stale: {cache_age:.1f}s since last refresh.")

    # Tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
        ["📊 Positions", "⏳ Open Orders", "📈 Market", "🧪 Strategy", "📉 Backtest", "📜 Trades", "🔍 Raw Data"]
    )

    with tab1:
        st.subheader("Active Positions")
        positions = state.get("positions", [])
        if positions:
            df = pd.DataFrame(positions)
            # Formatting
            st.dataframe(
                df.style.format({
                    "position": "{:.1f}",
                    "avg_entry": "${:.3f}",
                    "current_price": "${:.3f}",
                    "pnl": "${:.2f}"
                })
            )
        else:
            st.info("No active positions.")
            
    with tab2:
        st.subheader("Open Orders")
        orders = state.get("open_orders", [])
        market_data = state.get("market_data", [])
        market_map = {m.get("token_id"): m for m in market_data if isinstance(m, dict)}
        if orders:
            df_orders = pd.DataFrame(orders)
            if market_map and not df_orders.empty and "token_id" in df_orders.columns:
                df_orders["best_bid"] = df_orders["token_id"].map(
                    lambda tid: market_map.get(tid, {}).get("best_bid")
                )
                df_orders["best_ask"] = df_orders["token_id"].map(
                    lambda tid: market_map.get(tid, {}).get("best_ask")
                )
                df_orders["mid"] = df_orders["token_id"].map(
                    lambda tid: market_map.get(tid, {}).get("mid")
                )
                df_orders["spread"] = df_orders["token_id"].map(
                    lambda tid: market_map.get(tid, {}).get("spread")
                )
            # Select columns
            cols = ["token_id", "side", "size", "price", "best_bid", "best_ask", "mid", "spread", "status", "id"]
            for col in cols:
                if col not in df_orders.columns:
                    df_orders[col] = None
            if not df_orders.empty:
                st.dataframe(df_orders[cols])
            else:
                st.dataframe(df_orders)
        else:
            st.info("No open orders.")

    with tab3:
        st.subheader("Market Snapshot")
        market_data = state.get("market_data", [])
        if market_data:
            df_market = pd.DataFrame(market_data)
            st.dataframe(
                df_market.style.format({
                    "best_bid": "{:.3f}",
                    "best_ask": "{:.3f}",
                    "mid": "{:.3f}",
                    "spread": "{:.3f}"
                })
            )
        else:
            st.info("No market data yet.")

    with tab4:
        st.subheader("Strategy Stats")
        stats = state.get("strategy_stats", {})
        if stats:
            col_a, col_b, col_c, col_d = st.columns(4)
            with col_a:
                st.metric("Signals Total", stats.get("signals_total", 0))
            with col_b:
                st.metric("BUY_YES", stats.get("signals_buy_yes", 0))
            with col_c:
                st.metric("BUY_NO", stats.get("signals_buy_no", 0))
            with col_d:
                st.metric("NEUTRAL", stats.get("signals_neutral", 0))

            col_e, col_f, col_g, col_h = st.columns(4)
            with col_e:
                st.metric("Avg Edge", f"{stats.get('avg_edge', 0):.4f}")
            with col_f:
                st.metric("Eval Win Rate", f"{stats.get('eval_win_rate', 0) * 100:.1f}%")
            with col_g:
                st.metric("Eval Total", stats.get("eval_total", 0))
            with col_h:
                st.metric("Pending Evals", stats.get("pending_evals", 0))
        else:
            st.info("No strategy stats yet.")

        recon = state.get("live_reconciliation", {})
        if recon:
            last_poll_ts = recon.get("last_poll_ts")
            last_fill_ts = recon.get("last_fill_ts")
            col_i, col_j = st.columns(2)
            with col_i:
                if last_poll_ts:
                    st.metric("Last Live Poll", datetime.fromtimestamp(last_poll_ts).isoformat())
                else:
                    st.metric("Last Live Poll", "N/A")
            with col_j:
                if last_fill_ts:
                    st.metric("Last Live Fill", datetime.fromtimestamp(last_fill_ts).isoformat())
                else:
                    st.metric("Last Live Fill", "N/A")

        cache = state.get("live_order_cache", {})
        if cache:
            last_refresh = cache.get("last_refresh_ts")
            cache_size = cache.get("cache_size", 0)
            col_k, col_l = st.columns(2)
            with col_k:
                if last_refresh:
                    seconds_ago = max(0.0, time.time() - last_refresh)
                    st.metric("Order Cache Refresh", f"{seconds_ago:.1f}s ago")
                else:
                    st.metric("Order Cache Refresh", "N/A")
            with col_l:
                st.metric("Order Cache Size", cache_size)

    with tab5:
        st.subheader("Backtest Equity")
        default_path = "backtest_equity.csv"
        path = st.text_input("Equity CSV Path", value=default_path)
        if not path:
            st.info("Provide a CSV path to display equity.")
        elif not os.path.exists(path):
            st.info("Equity CSV not found.")
        else:
            try:
                df_equity = pd.read_csv(path)
                if "equity" in df_equity.columns:
                    st.line_chart(df_equity.set_index("timestamp")["equity"])
                    st.dataframe(df_equity.tail(50))
                else:
                    st.warning("Equity CSV missing 'equity' column.")
            except Exception as e:
                st.error(f"Failed to read equity CSV: {e}")

    with tab6:
        st.subheader("Trade History")
        trades = state.get("recent_trades", [])
        if trades:
            df_trades = pd.DataFrame(trades)
            # Sort by timestamp desc
            # df_trades = df_trades.sort_values(by="timestamp", ascending=False)
            st.dataframe(df_trades)
        else:
            st.info("No trades executed yet.")

    with tab7:
        st.json(state)

    # Auto-refresh logic (Moved to end to allow rendering first)
    if st.checkbox("Auto Refresh (10s)", value=True):
        time.sleep(10)
        st.rerun()

if __name__ == "__main__":
    main()
