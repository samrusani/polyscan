import logging
import math
import statistics
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("market_data.updown_model")


@dataclass
class ReturnStats:
    mean: float
    stdev: float
    samples: int


class UpDownFairValueModel:
    def __init__(self, min_samples: int = 10, clamp_min: float = 0.01, clamp_max: float = 0.99):
        self.min_samples = min_samples
        self.clamp_min = clamp_min
        self.clamp_max = clamp_max

    def fit(self, prices: List[float]) -> Optional[ReturnStats]:
        returns = []
        for idx in range(1, len(prices)):
            prev_price = prices[idx - 1]
            price = prices[idx]
            if prev_price <= 0 or price <= 0:
                continue
            returns.append(math.log(price / prev_price))

        if len(returns) < self.min_samples:
            logger.info("Insufficient return samples (%s) for up/down model.", len(returns))
            return None

        mean = statistics.mean(returns)
        stdev = statistics.pstdev(returns) if len(returns) > 1 else 0.0
        return ReturnStats(mean=mean, stdev=stdev, samples=len(returns))

    def probability_up(self, stats: ReturnStats, horizon_sec: float) -> Optional[float]:
        if stats is None:
            return None
        horizon_minutes = max(horizon_sec / 60.0, 0.0)
        if horizon_minutes <= 0:
            return None

        mean = stats.mean * horizon_minutes
        stdev = stats.stdev * math.sqrt(horizon_minutes)

        if stdev <= 0:
            if mean > 0:
                prob = 1.0
            elif mean < 0:
                prob = 0.0
            else:
                prob = 0.5
        else:
            z = (0.0 - mean) / (stdev * math.sqrt(2.0))
            prob = 0.5 * (1.0 - math.erf(z))

        prob = max(self.clamp_min, min(self.clamp_max, prob))
        return prob
