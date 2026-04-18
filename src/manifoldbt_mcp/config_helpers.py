"""Helpers for building :class:`BacktestConfig` from MCP JSON-friendly dicts.

MCP clients send tool arguments as JSON, so we accept plain dicts with
human-readable dates ("2022-01-01") and intervals ("1h"/"5m") and map
them to the native dataclasses.
"""
from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from manifoldbt.config import BacktestConfig, ExecutionConfig, FeeConfig, OrderConfig
from manifoldbt.helpers import Interval, Slippage, date_to_ns

_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*(s|sec|secs|m|min|mins|h|hr|hrs|d|day|days)\s*$", re.IGNORECASE)


def parse_interval(value: Any) -> dict[str, int] | None:
    """Parse an interval spec → Rust-serializable dict.

    Accepted forms:
      - ``{"Minutes": 1}`` (already native)
      - ``"1h"``, ``"5m"``, ``"15s"``, ``"1d"``
      - ``None`` → ``None``
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise TypeError(f"interval must be a string or dict, got {type(value).__name__}")
    m = _INTERVAL_RE.match(value)
    if not m:
        raise ValueError(
            f"Cannot parse interval '{value}'. Use formats like '1h', '5m', '15s', '1d'."
        )
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("s"):
        return Interval.seconds(n)
    if unit.startswith("m"):
        return Interval.minutes(n)
    if unit.startswith("h"):
        return Interval.hours(n)
    return Interval.days(n)


def _parse_time(value: Any) -> int:
    """Accept either ns int, ISO string, or date string."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return date_to_ns(value)
    raise TypeError(f"time must be int (ns) or str date, got {type(value).__name__}")


def _build_fees(spec: Any) -> FeeConfig:
    if spec is None:
        return FeeConfig()
    if isinstance(spec, FeeConfig):
        return spec
    if isinstance(spec, str):
        preset = spec.lower().replace("-", "_")
        if preset in {"binance_perps", "binance_perp"}:
            return FeeConfig.binance_perps()
        if preset in {"binance_spot", "spot"}:
            return FeeConfig.binance_spot()
        if preset in {"zero", "none"}:
            return FeeConfig.zero()
        raise ValueError(f"unknown fees preset '{spec}'")
    if isinstance(spec, Mapping):
        preset = spec.get("preset")
        base = _build_fees(preset) if preset else FeeConfig()
        for key, val in spec.items():
            if key == "preset":
                continue
            if not hasattr(base, key):
                raise ValueError(f"unknown fees field '{key}'")
            setattr(base, key, val)
        return base
    raise TypeError(f"unsupported fees spec: {type(spec).__name__}")


def _build_slippage(spec: Any) -> dict[str, Any] | None:
    if spec is None:
        return None
    if isinstance(spec, dict) and any(k[:1].isupper() for k in spec):
        # Already native-form, e.g. {"FixedBps": {"bps": 2.0}}
        return spec
    if isinstance(spec, Mapping):
        kind = str(spec.get("kind", "fixed_bps")).lower()
        if kind in {"fixed_bps", "fixed", "bps"}:
            return Slippage.fixed_bps(float(spec.get("bps", 0.0)))
        if kind == "volume_impact":
            return Slippage.volume_impact(
                float(spec.get("impact_coeff", 0.1)),
                float(spec.get("exponent", 1.5)),
            )
        if kind == "spread_based":
            return Slippage.spread_based(float(spec.get("spread_fraction", 1.0)))
        if kind in {"none", "zero"}:
            return Slippage.none()
    if isinstance(spec, (int, float)):
        return Slippage.fixed_bps(float(spec))
    raise TypeError(f"unsupported slippage spec: {type(spec).__name__}")


def _build_orders(spec: Any) -> OrderConfig | None:
    if spec is None:
        return None
    if isinstance(spec, OrderConfig):
        return spec
    if not isinstance(spec, Mapping):
        raise TypeError("orders must be a mapping")
    orders = OrderConfig()
    for key in ("limit_entry", "stop_loss", "take_profit", "trailing_stop"):
        if key in spec and spec[key] is not None:
            setattr(orders, key, dict(spec[key]))
    return orders


def _build_execution(spec: Any) -> ExecutionConfig:
    if spec is None:
        return ExecutionConfig()
    if isinstance(spec, ExecutionConfig):
        return spec
    if not isinstance(spec, Mapping):
        raise TypeError("execution must be a mapping")
    out = ExecutionConfig()
    for key, val in spec.items():
        if key == "orders":
            out.orders = _build_orders(val)
            continue
        if not hasattr(out, key):
            raise ValueError(f"unknown execution field '{key}'")
        setattr(out, key, val)
    return out


def build_backtest_config(spec: BacktestConfig | Mapping[str, Any]) -> BacktestConfig:
    """Convert a JSON dict to a :class:`BacktestConfig`.

    Dates can be strings ("2022-01-01") or ns ints.  Intervals accept
    shorthand like ``"1h"``.  Fees accept a preset name or a dict.
    """
    if isinstance(spec, BacktestConfig):
        return copy.deepcopy(spec)
    if not isinstance(spec, Mapping):
        raise TypeError("config must be a dict or BacktestConfig")

    data: dict[str, Any] = dict(spec)

    # Dates
    if "start" in data and "time_range_start" not in data:
        data["time_range_start"] = _parse_time(data.pop("start"))
    if "end" in data and "time_range_end" not in data:
        data["time_range_end"] = _parse_time(data.pop("end"))
    if "time_range_start" in data:
        data["time_range_start"] = _parse_time(data["time_range_start"])
    if "time_range_end" in data:
        data["time_range_end"] = _parse_time(data["time_range_end"])

    # Intervals
    if "bar_interval" in data:
        data["bar_interval"] = parse_interval(data["bar_interval"])
    if "output_resolution" in data:
        data["output_resolution"] = parse_interval(data["output_resolution"])
    if "resample_to" in data:
        data["resample_to"] = parse_interval(data["resample_to"])
    if "extra_timeframes" in data and isinstance(data["extra_timeframes"], Mapping):
        data["extra_timeframes"] = {
            k: parse_interval(v) for k, v in data["extra_timeframes"].items()
        }

    # Fees / slippage / execution
    if "fees" in data:
        data["fees"] = _build_fees(data["fees"])
    if "slippage" in data:
        data["slippage"] = _build_slippage(data["slippage"])
    if "execution" in data:
        data["execution"] = _build_execution(data["execution"])

    # Universe: accept list[str] or dict[provider, list[str]] as-is
    return BacktestConfig(**data)
