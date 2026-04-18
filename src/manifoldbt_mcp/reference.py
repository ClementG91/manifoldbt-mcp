"""Generated reference material exposed as MCP resources."""
from __future__ import annotations

import inspect

from manifoldbt import indicators as _ind

_INDICATOR_GROUPS = [
    ("Price columns", [
        "open", "high", "low", "close", "volume", "vwap", "timestamp",
    ]),
    ("Trend / Moving averages", [
        "sma", "ema", "dema", "tema", "wma", "hma", "kama",
    ]),
    ("Momentum", [
        "roc", "momentum", "rsi", "macd",
    ]),
    ("Oscillators", [
        "stoch_k", "stochastic_k", "williams_r", "cci", "adx",
    ]),
    ("Volatility / Bands", [
        "bollinger_bands", "bollinger_width", "atr", "true_range",
        "natr", "keltner_channels", "supertrend",
    ]),
    ("Volume", [
        "obv", "vwap", "ad_line", "mfi",
    ]),
    ("Regression", [
        "linreg_slope", "linreg_value", "linreg_r2",
    ]),
    ("Filters / Stochastic", [
        "kalman", "garch",
    ]),
    ("Cross / Compare", [
        "crossover", "crossunder",
    ]),
    ("Math", [
        "abs_val", "sqrt", "log", "exp", "max_val", "min_val",
    ]),
    ("Datetime", [
        "hour", "minute", "day_of_week", "month", "day_of_month",
    ]),
    ("Misc", [
        "rolling_median", "parabolic_sar",
    ]),
]


def _signature(fn) -> str:
    try:
        return str(inspect.signature(fn))
    except (TypeError, ValueError):
        return "(...)"


def _short_doc(fn) -> str:
    doc = inspect.getdoc(fn) or ""
    return doc.split("\n", 1)[0].strip()


def list_indicators() -> list[dict[str, str]]:
    """Return structured indicator metadata."""
    out: list[dict[str, str]] = []
    for group, names in _INDICATOR_GROUPS:
        for name in names:
            obj = getattr(_ind, name, None)
            if obj is None:
                continue
            if callable(obj):
                out.append({
                    "group": group,
                    "name": name,
                    "signature": f"{name}{_signature(obj)}",
                    "summary": _short_doc(obj),
                })
            else:
                out.append({
                    "group": group,
                    "name": name,
                    "signature": f"{name}  # pre-built column reference",
                    "summary": f"Shorthand for col('{name}').",
                })
    return out


def render_indicators_markdown() -> str:
    """Return a Markdown reference for all indicators."""
    lines: list[str] = [
        "# manifoldbt indicator reference",
        "",
        "All indicators live in ``manifoldbt.indicators`` and return ``Expr``",
        "objects that compose into the backtester expression graph.",
        "",
    ]
    for group, names in _INDICATOR_GROUPS:
        lines.append(f"## {group}")
        lines.append("")
        for name in names:
            obj = getattr(_ind, name, None)
            if obj is None:
                continue
            if callable(obj):
                lines.append(f"- `{name}{_signature(obj)}` — {_short_doc(obj) or '—'}")
            else:
                lines.append(f"- `{name}` — shorthand for ``col('{name}')``")
        lines.append("")
    return "\n".join(lines)


def render_api_overview() -> str:
    """Return a Markdown overview of the main ``manifoldbt`` entry points."""
    return (
        "# manifoldbt API overview\n"
        "\n"
        "```python\n"
        "import manifoldbt as mbt\n"
        "from manifoldbt.indicators import close, ema, rsi\n"
        "from manifoldbt.helpers import time_range, Slippage, Interval\n"
        "```\n"
        "\n"
        "## Build a strategy\n"
        "```python\n"
        "fast = ema(close, 12)\n"
        "slow = ema(close, 26)\n"
        "strategy = (\n"
        "    mbt.Strategy.create('ema_crossover')\n"
        "    .signal('fast', fast)\n"
        "    .signal('slow', slow)\n"
        "    .size(mbt.when(fast > slow, 0.5, 0.0))\n"
        "    .stop_loss(pct=3.0)\n"
        ")\n"
        "```\n"
        "\n"
        "## Configure and run\n"
        "```python\n"
        "start, end = time_range('2022-01-01', '2025-01-01')\n"
        "config = mbt.BacktestConfig(\n"
        "    universe=[1],\n"
        "    time_range_start=start,\n"
        "    time_range_end=end,\n"
        "    bar_interval=Interval.hours(12),\n"
        "    initial_capital=10_000,\n"
        "    execution=mbt.ExecutionConfig(allow_short=True, max_position_pct=0.5),\n"
        "    fees=mbt.FeeConfig.binance_perps(),\n"
        "    slippage=Slippage.fixed_bps(2),\n"
        "    warmup_bars=30,\n"
        ")\n"
        "\n"
        "store = mbt.DataStore(data_root='data', metadata_db='metadata/metadata.sqlite')\n"
        "result = mbt.run(strategy, config, store)\n"
        "print(result.summary())\n"
        "```\n"
        "\n"
        "## Research helpers\n"
        "- `mbt.run_sweep(strategy, param_grid, config, store)` — Cartesian grid sweep.\n"
        "- `mbt.run_sweep_2d(strategy, sweep_config, config, store)` — 2D heatmap sweep.\n"
        "- `mbt.run_walk_forward(strategy, wf_config, config, store)` — walk-forward (Pro).\n"
        "- `mbt.run_stability(strategy, stab_config, config, store)` — parameter stability.\n"
        "- `mbt.py_run_monte_carlo(result, mc_config)` — Monte Carlo permutations.\n"
        "- `mbt.run_stochastic(model, ...)` — SDE path simulation (no DataStore needed).\n"
        "- `mbt.run_portfolio(portfolio, config, store)` — multi-strategy portfolio.\n"
    )
