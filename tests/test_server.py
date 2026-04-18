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
from manifoldbt_mcp.server import build_server


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


def test_build_server_registers_core_tools():
    server = build_server()
    tools = getattr(server, "_tool_manager", None) or getattr(server, "tool_manager", None)
    assert tools is not None
    registered = set(tools._tools.keys())  # type: ignore[attr-defined]
    for name in (
        "get_version",
        "list_indicators_tool",
        "list_examples",
        "build_strategy",
        "run_backtest",
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
