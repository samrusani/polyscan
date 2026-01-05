import copy
import itertools
import json
from typing import Any, Dict, Iterable, List, Optional

from src.backtest.runner import run_backtest, run_backtest_multi, MultiBacktestResult


class ConfigView:
    def __init__(self, data: Dict[str, Any]):
        self._data = data

    @property
    def mode(self) -> str:
        return self._data.get("mode", "paper")

    @property
    def scanner(self) -> Dict[str, Any]:
        return self._data.get("scanner", {})

    @property
    def strategy(self) -> Dict[str, Any]:
        return self._data.get("strategy", {})

    @property
    def risk(self) -> Dict[str, Any]:
        return self._data.get("risk", {})

    @property
    def execution(self) -> Dict[str, Any]:
        return self._data.get("execution", {})


def load_sweep(path: str) -> Dict[str, List[Any]]:
    with open(path, "r") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("Sweep file must be a JSON object of param -> list.")
    normalized: Dict[str, List[Any]] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            normalized[key] = value
        else:
            normalized[key] = [value]
    if not normalized:
        raise ValueError("Sweep file contains no parameters.")
    return normalized


def run_sweep(
    config_data: Dict[str, Any],
    ticks: List[Dict[str, Any]],
    token_ids: List[str],
    sweep: Dict[str, List[Any]],
    max_runs: Optional[int] = None
) -> List[Dict[str, Any]]:
    param_keys = sorted(sweep.keys())
    value_lists = [sweep[key] for key in param_keys]
    results: List[Dict[str, Any]] = []

    run_index = 0
    for combo in itertools.product(*value_lists):
        if max_runs is not None and run_index >= max_runs:
            break
        overrides = dict(zip(param_keys, combo))
        cfg_data = _apply_overrides(config_data, overrides)
        cfg = ConfigView(cfg_data)
        if len(token_ids) == 1:
            result = run_backtest(cfg, token_ids[0], ticks)
            summary = _summarize_result(result, token_ids, run_index)
        else:
            result = run_backtest_multi(cfg, token_ids, ticks)
            summary = _summarize_result(result, token_ids, run_index)
        for key in param_keys:
            summary[f"param_{key}"] = overrides[key]
        results.append(summary)
        run_index += 1
    return results


def _apply_overrides(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    data = copy.deepcopy(base)
    for path, value in overrides.items():
        _set_nested(data, path, value)
    return data


def _set_nested(data: Dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    cursor = data
    for key in keys[:-1]:
        if key not in cursor or not isinstance(cursor[key], dict):
            cursor[key] = {}
        cursor = cursor[key]
    cursor[keys[-1]] = value


def _summarize_result(result: Any, token_ids: List[str], run_index: int) -> Dict[str, Any]:
    summary = {
        "run_id": run_index,
        "tokens": ",".join(token_ids),
        "total_ticks": result.total_ticks,
        "buy_yes": result.buy_yes,
        "buy_no": result.buy_no,
        "neutral": result.neutral,
        "avg_edge": result.avg_edge,
        "total_trades": result.total_trades,
        "win_rate": result.win_rate,
        "total_pnl": result.total_pnl,
        "avg_pnl_per_trade": result.avg_pnl_per_trade,
        "fees_paid": result.fees_paid
    }
    if isinstance(result, MultiBacktestResult):
        summary["tokens"] = ",".join(sorted(result.per_token.keys()))
    return summary
