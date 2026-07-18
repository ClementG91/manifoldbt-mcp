"""Smoke tests for manifoldbt-mcp.

These run without hitting the Rust engine end-to-end: they exercise
strategy compilation, config parsing, and FastMCP tool registration.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("mcp")
pytest.importorskip("manifoldbt")

from manifoldbt_mcp.config_helpers import build_backtest_config, parse_interval
from manifoldbt_mcp.dsl import compile_strategy_code
from manifoldbt_mcp.reference import list_indicators, render_indicators_markdown
from manifoldbt_mcp.server import (
    _combo_at,
    _grid_size,
    _rank_indices,
    _rank_rows,
    build_server,
)


def _rows(metric: str, values):
    return [{"metrics": {metric: v}, "tag": i} for i, v in enumerate(values)]


def test_parse_interval_shorthands():
    assert parse_interval("1h") == {"Hours": 1}
    assert parse_interval("5m") == {"Minutes": 5}
    assert parse_interval("30s") == {"Seconds": 30}
    assert parse_interval("1d") == {"Days": 1}
    assert parse_interval({"Minutes": 15}) == {"Minutes": 15}
    assert parse_interval(None) is None


def test_parse_interval_rejects_garbage():
    with pytest.raises(ValueError):
        parse_interval("later")


def test_build_backtest_config_maps_dates_and_presets():
    cfg = build_backtest_config({
        "universe": [1],
        "start": "2022-01-01",
        "end": "2023-01-01",
        "bar_interval": "1h",
        "initial_capital": 5000,
        "fees": "binance_perps",
        "slippage": {"kind": "fixed_bps", "bps": 2.5},
    })
    assert cfg.time_range_start > 0
    assert cfg.time_range_end > cfg.time_range_start
    assert cfg.bar_interval == {"Hours": 1}
    assert cfg.initial_capital == 5000
    assert cfg.fees.taker_fee_bps == 5.0
    assert cfg.slippage == {"FixedBps": {"bps": 2.5}}


def test_compile_strategy_code_roundtrip():
    code = (
        "fast = ema(close, 12)\n"
        "slow = ema(close, 26)\n"
        "strategy = (\n"
        "    Strategy.create('ema_cross')\n"
        "    .signal('fast', fast)\n"
        "    .signal('slow', slow)\n"
        "    .size(when(fast > slow, lit(0.5), lit(0.0)))\n"
        ")\n"
    )
    strat = compile_strategy_code(code)
    assert strat.name == "ema_cross"
    payload = strat.to_json_dict()
    assert set(payload["signals"].keys()) == {"fast", "slow"}
    assert json.loads(json.dumps(payload))["name"] == "ema_cross"


def test_compile_strategy_code_errors_without_strategy_binding():
    with pytest.raises(ValueError):
        compile_strategy_code("x = 1 + 1\n")


def test_list_indicators_contains_core_set():
    items = list_indicators()
    names = {item["name"] for item in items}
    for core in ("sma", "ema", "rsi", "macd", "bollinger_bands", "atr", "close"):
        assert core in names


def test_render_indicators_markdown_has_groups():
    md = render_indicators_markdown()
    assert "# manifoldbt indicator reference" in md
    assert "## Trend / Moving averages" in md
    assert "`ema" in md


def test_rank_rows_puts_best_sharpe_first():
    ranked = _rank_rows(_rows("sharpe", [0.4, 2.1, 1.0]), "sharpe")
    assert [r["tag"] for r in ranked] == [1, 2, 0]


def test_rank_rows_minimises_positive_risk_metrics():
    # ulcer_index and volatility are positive magnitudes: smallest wins.
    ranked = _rank_rows(_rows("ulcer_index", [0.30, 0.05, 0.12]), "ulcer_index")
    assert [r["tag"] for r in ranked] == [1, 2, 0]

    ranked = _rank_rows(_rows("volatility", [0.9, 0.2, 0.5]), "volatility")
    assert [r["tag"] for r in ranked] == [1, 2, 0]


def test_rank_rows_treats_max_drawdown_as_signed():
    # The engine reports eq/peak - 1, so -0.05 is a shallower drawdown
    # than -0.40 and must rank first. Ranking it ascending would invert the
    # whole leaderboard.
    ranked = _rank_rows(_rows("max_drawdown", [-0.40, -0.05, -0.22]), "max_drawdown")
    assert [r["tag"] for r in ranked] == [1, 2, 0]


def test_rank_rows_pushes_missing_and_nan_last_in_both_directions():
    ranked = _rank_rows(_rows("sharpe", [1.0, float("nan"), None, 2.0]), "sharpe")
    assert [r["tag"] for r in ranked][:2] == [3, 0]
    assert set(r["tag"] for r in ranked[2:]) == {1, 2}

    ranked = _rank_rows(
        _rows("ulcer_index", [0.2, float("nan"), None, 0.1]), "ulcer_index"
    )
    assert [r["tag"] for r in ranked][:2] == [3, 0]
    assert set(r["tag"] for r in ranked[2:]) == {1, 2}


def test_rank_indices_matches_row_ranking():
    np = pytest.importorskip("numpy")

    col = np.array([0.4, 2.1, 1.0])
    assert _rank_indices(col, lower_is_better=False) == [1, 2, 0]
    assert _rank_indices(col, lower_is_better=True) == [0, 2, 1]


def test_rank_indices_keeps_nan_last_in_both_directions():
    np = pytest.importorskip("numpy")

    col = np.array([1.0, np.nan, 2.0])
    assert _rank_indices(col, lower_is_better=False) == [2, 0, 1]
    assert _rank_indices(col, lower_is_better=True) == [0, 2, 1]


def test_combo_at_matches_the_engine_enumeration():
    # Golden sequence captured from manifoldbt 0.13.0 itself: this exact grid
    # was swept, then each index re-run as a 1-combo sweep, and all 12
    # final_equity values matched. Insertion order is zz-then-aa while the
    # engine sorts alphabetically, so a decoder that trusted insertion order
    # would transpose the whole leaderboard.
    grid = {"zz": [50, 80, 120], "aa": [5, 10, 15, 20]}
    decoded = [_combo_at(grid, i) for i in range(12)]

    assert decoded[0] == {"aa": 5, "zz": 50}
    assert decoded[1] == {"aa": 5, "zz": 80}
    assert decoded[3] == {"aa": 10, "zz": 50}
    assert decoded[11] == {"aa": 20, "zz": 120}
    # The alphabetically last axis varies fastest.
    assert [c["zz"] for c in decoded[:4]] == [50, 80, 120, 50]
    assert [c["aa"] for c in decoded[:4]] == [5, 5, 5, 10]


def test_combo_at_agrees_with_itertools_product():
    import itertools

    grid = {"beta": ["x", "y"], "alpha": [1, 2, 3], "gamma": [True, False]}
    names = sorted(grid)
    expected = [
        dict(zip(names, values, strict=True))
        for values in itertools.product(*(grid[n] for n in names))
    ]
    assert [_combo_at(grid, i) for i in range(len(expected))] == expected


def test_combo_at_handles_degenerate_grids():
    assert _combo_at({"only": [7, 8, 9]}, 2) == {"only": 9}
    assert _combo_at({}, 0) == {}


def test_grid_size_is_the_cartesian_product():
    assert _grid_size({"a": [1, 2, 3], "b": [1, 2]}) == 6
    assert _grid_size({}) == 1
    assert _grid_size({"a": []}) == 0


def test_build_server_registers_core_tools():
    server = build_server()
    tools = getattr(server, "_tool_manager", None) or getattr(server, "tool_manager", None)
    assert tools is not None
    registered = set(tools._tools.keys())  # type: ignore[attr-defined]
    for name in (
        "get_version",
        "list_indicators",
        "list_examples",
        "build_strategy",
        "validate_strategy",
        "run_backtest",
        "run_batch",
        "run_sweep",
        "run_sweep_2d",
        "run_walk_forward",
        "run_stability",
        "run_monte_carlo",
        "run_stochastic",
        "run_portfolio",
        "plot_tearsheet",
    ):
        assert name in registered, f"tool '{name}' not registered"


def test_server_registers_resources_and_prompts():
    server = build_server()
    rm = server._resource_manager
    pm = server._prompt_manager
    resource_uris = {str(uri) for uri in rm._resources.keys()}
    assert "manifoldbt://reference/api" in resource_uris
    assert "manifoldbt://reference/indicators" in resource_uris
    assert "manifoldbt://reference/strategy-authoring" in resource_uris
    assert "manifoldbt://examples/{slug}" in rm._templates
    prompts = set(pm._prompts.keys())
    assert {"write_strategy", "analyze_result"} <= prompts
