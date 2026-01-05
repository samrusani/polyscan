from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime
from collections import defaultdict

class Portfolio:
    def __init__(self):
        self.history: List[Dict] = []
        # Position tracking
        self.positions: Dict[str, float] = defaultdict(float) # token_id -> quantity
        self.avg_cost: Dict[str, float] = defaultdict(float) # token_id -> avg entry price
        self.realized_pnl: Dict[str, float] = defaultdict(float) # token_id -> realized pnl
        
    def add_trade(self, trade: Dict):
        # trade: {order_id, token_id, price, size, side, timestamp}
        self.history.append(trade)
        
        tid = trade['token_id']
        size = float(trade['size'])
        price = float(trade['price'])
        side = trade['side'].upper() # BUY or SELL
        
        # Update Position logic (FIFO or Avg Cost?)
        # Simple Avg Cost for PnL
        
        current_pos = self.positions[tid]
        current_avg = self.avg_cost[tid]
        
        if side == "BUY":
            # Just adding to inventory
            new_pos = current_pos + size
            # Update weighted average cost
            # (old_pos * old_avg + new_shares * new_price) / new_pos
            if new_pos > 0:
                self.avg_cost[tid] = ((current_pos * current_avg) + (size * price)) / new_pos
            else:
                # Closing short partially? if we supported shorting.
                # Polymarket "Selling" usually means Selling Long Position (if binary).
                # But if we treat it as generic asset.
                pass
            self.positions[tid] = new_pos
            
        elif side == "SELL":
            # Realize PnL
            # PnL = (Sell Price - Avg Cost) * Size
            if current_pos > 0:
                # Closing long
                realized = (price - current_avg) * size
                self.realized_pnl[tid] += realized
                self.positions[tid] = current_pos - size
                # Avg Cost stays same for remaining shares? Yes.
                if self.positions[tid] <= 0:
                    self.positions[tid] = 0
                    self.avg_cost[tid] = 0
            else:
                # Short selling? Not supported usually for basic binary token.
                pass

    def get_live_pnl(self, current_prices: Dict[str, float]) -> Dict[str, float]:
        """
        Returns {token_id: {realized, unrealized, total, position}}
        """
        report = {}
        for tid, pos in self.positions.items():
            realized = self.realized_pnl[tid]
            unrealized = 0.0
            price = current_prices.get(tid, 0.0)
            avg = self.avg_cost[tid]
            
            if pos > 0 and price > 0:
                unrealized = (price - avg) * pos
            
            report[tid] = {
                "position": pos,
                "avg_entry": avg,
                "realized": realized,
                "unrealized": unrealized,
                "total": realized + unrealized
            }
        return report

    def get_summary_text(self, current_prices: Dict[str, float]) -> str:
        data = self.get_live_pnl(current_prices)
        if not data:
            return "No positions."
            
        total_pnl = sum(d['total'] for d in data.values())
        total_realized = sum(d['realized'] for d in data.values())
        
        lines = [f"Total PnL: ${total_pnl:.2f} (Realized: ${total_realized:.2f})"]
        lines.append("-" * 40)
        lines.append(f"{'Token':<15} {'Pos':<8} {'Avg':<8} {'Last':<8} {'Unreal':<8} {'Real':<8}")
        
        for tid, d in data.items():
            price = current_prices.get(tid, 0.0)
            lines.append(f"{tid[:12]:<15} {d['position']:<8.1f} {d['avg_entry']:<8.3f} {price:<8.3f} {d['unrealized']:<8.2f} {d['realized']:<8.2f}")
            
        return "\n".join(lines)

    def get_summary(self) -> str:
        if not self.history:
             return "No trades executed."
        df = pd.DataFrame(self.history)
        total_vol = df['size'].sum()
        count = len(df)
        total_realized = sum(self.realized_pnl.values())
        return f"Trades: {count}, Volume: {total_vol}, Realized PnL: ${total_realized:.2f}"
        
    def export_csv(self, filepath: str):
        if self.history:
            df = pd.DataFrame(self.history)
            df.to_csv(filepath, index=False)
