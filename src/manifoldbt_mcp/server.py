"""FastMCP-based server exposing manifoldbt to MCP clients.

Run over stdio (default) or streamable HTTP::

    manifoldbt-mcp                          # stdio
    manifoldbt-mcp --http --port 8765       # streamable HTTP

All tools accept JSON-friendly arguments.  Strategies can either be sent
as the already-serialised ``StrategyDef`` JSON or as a Python DSL snippet
that builds a ``Strategy`` object (see ``build_strategy`` / ``run_backtest``).
"""
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import manifoldbt as mbt
from manifoldbt._native import compile_strategy_json as _compile_native
from manifoldbt._native import license_info as _license_info
from manifoldbt.strategy import Strategy
from mcp.server.fastmcp import FastMCP

from manifoldbt_mcp.config_helpers import build_backtest_config
from manifoldbt_mcp.dsl import compile_strategy_code
from manifoldbt_mcp.reference import (
    list_indicators,
    render_api_overview,
    render_indicators_markdown,
)
from manifoldbt_mcp.store import resolve_store


def _find_examples_dir() -> Path | None:
    """Locate the ``examples`` dir shipped with the installed manifoldbt package."""
    try:
        pkg_root = Path(mbt.__file__).resolve().parent
    except Exception:  # pragma: no cover
        return None
    for candidate in (
        pkg_root / "examples",
        pkg_root.parent / "examples",
        pkg_root.parent.parent / "examples",
    ):
        if candidate.is_dir():
            return candidate
    return None


_EXAMPLES_DIR = _find_examples_dir()


# ----------------------------------------------------------------------
# Helpers shared by tools
# ----------------------------------------------------------------------


def _get_strategy(
    strategy_code: str | None = None,
    strategy_json: str | None = None,
) -> Strategy:
    """Build a Strategy either from DSL code or from already-serialised JSON."""
    if strategy_code and strategy_json:
        raise ValueError("provide either strategy_code or strategy_json, not both")
    if strategy_code:
        return compile_strategy_code(strategy_code)
    if strategy_json:
        if not isinstance(strategy_json, str):
            strategy_json = json.dumps(strategy_json)
        # Validate + round-trip through the Rust compiler
        _compile_native(strategy_json)
        doc = json.loads(strategy_json)
        # Re-hydrate a Strategy wrapper so we get ``to_json()`` back.
        strat = Strategy(name=doc.get("name", "strategy"))
        strat._raw_json = strategy_json  # type: ignore[attr-defined]
        strat.to_json = lambda _raw=strategy_json: _raw  # type: ignore[assignment]
        strat.to_json_dict = lambda _raw=doc: _raw  # type: ignore[assignment]
        return strat
    raise ValueError("provide strategy_code (Python DSL) or strategy_json")


def _result_to_dict(result) -> dict[str, Any]:
    """Best-effort conversion of a Result / BacktestResult to a JSON dict."""
    raw = getattr(result, "raw", result)
    out: dict[str, Any] = {
        "metrics": getattr(raw, "metrics", None),
        "manifest": getattr(raw, "manifest", None),
        "trade_count": getattr(raw, "trade_count", None),
        "warnings": list(getattr(raw, "warnings", []) or []),
    }
    summary_fn = getattr(result, "summary", None)
    if callable(summary_fn):
        try:
            out["summary"] = summary_fn()
        except Exception:
            pass
    return out


def _batch_result_to_dict(item) -> dict[str, Any]:
    return {
        "strategy_name": getattr(item, "strategy_name", None),
        "final_equity": getattr(item, "final_equity", None),
        "trade_count": getattr(item, "trade_count", None),
        "metrics": getattr(item, "metrics", None),
    }


# ----------------------------------------------------------------------
# Server construction
# ----------------------------------------------------------------------


def build_server() -> FastMCP:
    """Create and wire up the FastMCP server instance."""
    mcp = FastMCP(
        "manifoldbt",
        instructions=(
            "Tools for defining, backtesting, and analysing quantitative "
            "trading strategies with the manifoldbt Rust engine. "
            "Strategies can be authored as Python DSL snippets (strategy_code) "
            "or as already-serialised StrategyDef JSON (strategy_json). "
            "Read the 'manifoldbt://reference/strategy-authoring' resource "
            "for the full authoring guide."
        ),
    )

    # ------------------------------------------------------------------
    # Environment / discovery tools
    # ------------------------------------------------------------------

    @mcp.tool(description="Return manifoldbt version and license tier.")
    def get_version() -> dict[str, Any]:
        try:
            tier, email = _license_info()
        except Exception:
            tier, email = ("Community", None)
        return {
            "version": mbt.__version__,
            "license_tier": tier,
            "license_email": email,
        }

    @mcp.tool(
        description=(
            "Activate a manifoldbt Pro license key for this server process."
        ),
    )
    def activate_license(license_key: str) -> dict[str, Any]:
        mbt.activate(license_key)
        tier, email = _license_info()
        return {"license_tier": tier, "license_email": email}

    @mcp.tool(
        description=(
            "List all available technical indicators with their Python "
            "signatures, grouped by category."
        ),
    )
    def list_indicators_tool() -> list[dict[str, str]]:
        return list_indicators()

    @mcp.tool(
        description=(
            "List example strategy scripts bundled with the library. "
            "Returns file names you can pass to get_example."
        ),
    )
    def list_examples() -> list[str]:
        if _EXAMPLES_DIR is None or not _EXAMPLES_DIR.is_dir():
            return []
        return sorted(p.name for p in _EXAMPLES_DIR.glob("*.py"))

    @mcp.tool(description="Read the source of a bundled example strategy.")
    def get_example(name: str) -> dict[str, str]:
        if _EXAMPLES_DIR is None:
            raise ValueError("examples directory not found in manifoldbt install")
        path = (_EXAMPLES_DIR / name).resolve()
        if not str(path).startswith(str(_EXAMPLES_DIR.resolve())) or not path.is_file():
            raise ValueError(f"unknown example '{name}'")
        return {"name": name, "source": path.read_text()}

    # ------------------------------------------------------------------
    # Data store tools
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "List every symbol registered in a DataStore. Pass "
            "{'data_root': 'data', 'metadata_db': 'metadata/metadata.sqlite'}."
        ),
    )
    def list_symbols(store: dict[str, Any]) -> list[dict[str, Any]]:
        s = resolve_store(store)
        return [{"id": sid, "ticker": ticker} for sid, ticker in s.list_symbols()]

    @mcp.tool(description="Resolve a ticker string to its SymbolId in a DataStore.")
    def resolve_symbol(ticker: str, store: dict[str, Any]) -> int:
        return int(resolve_store(store).resolve_symbol(ticker))

    @mcp.tool(
        description=(
            "Ingest bars from a data provider into a parquet DataStore. "
            "Providers: binance, hyperliquid (free); databento, massive (Pro)."
        ),
    )
    def ingest_data(
        provider: str,
        symbol: str,
        symbol_id: int,
        start: str,
        end: str,
        interval: str = "1m",
        *,
        dataset: str | None = None,
        data_root: str = "data",
        metadata_db: str = "metadata/metadata.sqlite",
        exchange: str | None = None,
        asset_class: str = "crypto_spot",
    ) -> dict[str, Any]:
        store = mbt.ingest(
            provider=provider,
            symbol=symbol,
            symbol_id=symbol_id,
            start=start,
            end=end,
            interval=interval,
            dataset=dataset,
            data_root=data_root,
            metadata_db=metadata_db,
            exchange=exchange,
            asset_class=asset_class,
            progress=False,
        )
        return {
            "data_root": store.data_root(),
            "metadata_db": store.metadata_db(),
            "symbols": [
                {"id": sid, "ticker": t} for sid, t in store.list_symbols()
            ],
        }

    # ------------------------------------------------------------------
    # Strategy authoring tools
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Compile a Python DSL snippet into a manifoldbt StrategyDef. "
            "The snippet must assign 'strategy = mbt.Strategy...'. Returns "
            "the serialised JSON plus a list of declared parameters."
        ),
    )
    def build_strategy(strategy_code: str) -> dict[str, Any]:
        strat = compile_strategy_code(strategy_code)
        doc = strat.to_json_dict()
        # Validate with the Rust compiler — raises a clear error if invalid.
        _compile_native(json.dumps(doc))
        return {
            "name": strat.name,
            "strategy_json": doc,
            "signals": list(doc.get("signals", {}).keys()),
            "parameters": doc.get("parameters", {}),
        }

    @mcp.tool(
        description=(
            "Validate a StrategyDef JSON string by running it through the "
            "Rust compiler. Returns the compiled expression plan or an error."
        ),
    )
    def validate_strategy(strategy_json: str) -> dict[str, Any]:
        if not isinstance(strategy_json, str):
            strategy_json = json.dumps(strategy_json)
        plan = _compile_native(strategy_json)
        try:
            plan_obj = json.loads(plan)
        except (TypeError, ValueError):
            plan_obj = plan
        return {"ok": True, "plan": plan_obj}

    # ------------------------------------------------------------------
    # Backtest tools
    # ------------------------------------------------------------------

    @mcp.tool(
        description=(
            "Run a backtest. Supply either a Python DSL snippet "
            "(strategy_code) or a serialised StrategyDef (strategy_json) "
            "plus a config dict and a store descriptor. Returns metrics "
            "and a printable summary."
        ),
    )
    def run_backtest(
        config: dict[str, Any],
        store: dict[str, Any],
        *,
        strategy_code: str | None = None,
        strategy_json: str | None = None,
    ) -> dict[str, Any]:
        strat = _get_strategy(strategy_code, strategy_json)
        cfg = build_backtest_config(config)
        s = resolve_store(store)
        result = mbt.run(strat, cfg, s)
        return _result_to_dict(result)

    @mcp.tool(
        description=(
            "Run many strategies in parallel against a shared config/store. "
            "Each item in strategies is {strategy_code|strategy_json}."
        ),
    )
    def run_batch(
        strategies: list[dict[str, Any]],
        config: dict[str, Any],
        store: dict[str, Any],
        *,
        lite: bool = False,
        max_parallelism: int = 0,
    ) -> list[dict[str, Any]]:
        strats = [
            _get_strategy(s.get("strategy_code"), s.get("strategy_json"))
            for s in strategies
        ]
        cfg = build_backtest_config(config)
        st = resolve_store(store)
        if lite:
            items = mbt.run_batch_lite(strats, cfg, st, max_parallelism=max_parallelism)
            return [_batch_result_to_dict(it) for it in items]
        results = mbt.run_batch(strats, cfg, st, max_parallelism=max_parallelism)
        return [_result_to_dict(r) for r in results]

    @mcp.tool(
        description=(
            "Run a parameter sweep over a Cartesian grid. param_grid maps "
            "parameter names (declared via param('name') in the strategy) "
            "to lists of values."
        ),
    )
    def run_sweep(
        param_grid: dict[str, list[Any]],
        config: dict[str, Any],
        store: dict[str, Any],
        *,
        strategy_code: str | None = None,
        strategy_json: str | None = None,
        lite: bool = True,
        max_parallelism: int = 0,
        top_k: int = 10,
        rank_metric: str = "sharpe",
    ) -> dict[str, Any]:
        strat = _get_strategy(strategy_code, strategy_json)
        cfg = build_backtest_config(config)
        st = resolve_store(store)
        if lite:
            raws = mbt.run_sweep_lite(
                strat, param_grid, cfg, st, max_parallelism=max_parallelism
            )
            rows = [_batch_result_to_dict(r) for r in raws]
        else:
            sweep = mbt.run_sweep(
                strat, param_grid, cfg, st, max_parallelism=max_parallelism
            )
            rows = [_result_to_dict(r) for r in sweep.results]

        ranked = sorted(
            rows,
            key=lambda r: (r.get("metrics") or {}).get(rank_metric) or float("-inf"),
            reverse=True,
        )
        return {
            "total": len(rows),
            "rank_metric": rank_metric,
            "top": ranked[: max(1, int(top_k))],
        }

    @mcp.tool(
        description=(
            "Run a 2D parameter sweep (heatmap). sweep_config must contain "
            "x_param, x_values, y_param, y_values, metric."
        ),
    )
    def run_sweep_2d(
        sweep_config: dict[str, Any],
        config: dict[str, Any],
        store: dict[str, Any],
        *,
        strategy_code: str | None = None,
        strategy_json: str | None = None,
    ) -> dict[str, Any]:
        strat = _get_strategy(strategy_code, strategy_json)
        cfg = build_backtest_config(config)
        st = resolve_store(store)
        return mbt.run_sweep_2d(strat, sweep_config, cfg, st)

    @mcp.tool(
        description=(
            "Walk-forward optimisation (Pro). wf_config needs method, "
            "n_splits, train_ratio, optimize_metric, param_grid."
        ),
    )
    def run_walk_forward(
        wf_config: dict[str, Any],
        config: dict[str, Any],
        store: dict[str, Any],
        *,
        strategy_code: str | None = None,
        strategy_json: str | None = None,
    ) -> dict[str, Any]:
        strat = _get_strategy(strategy_code, strategy_json)
        cfg = build_backtest_config(config)
        st = resolve_store(store)
        return mbt.run_walk_forward(strat, wf_config, cfg, st)

    @mcp.tool(
        description=(
            "Parameter stability analysis: runs a 1D sweep and reports the "
            "mean/std/stability score of a metric."
        ),
    )
    def run_stability(
        stability_config: dict[str, Any],
        config: dict[str, Any],
        store: dict[str, Any],
        *,
        strategy_code: str | None = None,
        strategy_json: str | None = None,
    ) -> dict[str, Any]:
        strat = _get_strategy(strategy_code, strategy_json)
        cfg = build_backtest_config(config)
        st = resolve_store(store)
        return mbt.run_stability(strat, stability_config, cfg, st)

    @mcp.tool(
        description=(
            "Run Monte Carlo permutations on a backtest result. Re-runs the "
            "backtest first, then permutes trade returns."
        ),
    )
    def run_monte_carlo(
        config: dict[str, Any],
        store: dict[str, Any],
        mc_config: dict[str, Any] | None = None,
        *,
        strategy_code: str | None = None,
        strategy_json: str | None = None,
    ) -> dict[str, Any]:
        strat = _get_strategy(strategy_code, strategy_json)
        cfg = build_backtest_config(config)
        st = resolve_store(store)
        result = mbt.run(strat, cfg, st)
        from manifoldbt._native import py_run_monte_carlo
        return py_run_monte_carlo(result.raw, json.dumps(mc_config or {}))

    @mcp.tool(
        description=(
            "Stochastic SDE simulation (no DataStore required). 'model' is "
            "either a preset name ('gbm', 'heston', 'merton', 'garch_jd') "
            "or a dict matching StochasticModel.to_dict()."
        ),
    )
    def run_stochastic(
        model: Any,
        *,
        s0: float = 100.0,
        n_paths: int = 1000,
        n_steps: int = 252,
        dt: float = 1.0 / 252.0,
        params: dict[str, float] | None = None,
        seed: int | None = None,
        confidence_levels: list[float] | None = None,
        store_paths: bool = False,
        device: str = "cpu",
        precision: str = "f64",
    ) -> dict[str, Any]:
        if isinstance(model, Mapping):
            from manifoldbt.stochastic import StochasticModel
            spec = dict(model)
            model_obj = StochasticModel(
                drift=spec.get("drift", "mu"),
                diffusion=spec.get("diffusion", "sigma"),
                state_vars=spec.get("state_vars"),
                state_update=spec.get("state_update"),
                params=spec.get("params", {}),
            )
            return mbt.run_stochastic(
                model_obj,
                s0=s0,
                n_paths=n_paths,
                n_steps=n_steps,
                dt=dt,
                params=params,
                seed=seed,
                confidence_levels=confidence_levels,
                store_paths=store_paths,
                device=device,
                precision=precision,
            )
        return mbt.run_stochastic(
            model,
            s0=s0,
            n_paths=n_paths,
            n_steps=n_steps,
            dt=dt,
            params=params,
            seed=seed,
            confidence_levels=confidence_levels,
            store_paths=store_paths,
            device=device,
            precision=precision,
        )

    @mcp.tool(
        description=(
            "Run a multi-strategy portfolio. 'portfolio' is a dict with "
            "keys strategies (list of {strategy_code|strategy_json, weight}), "
            "risk_rules (list), rebalance (dict)."
        ),
    )
    def run_portfolio(
        portfolio: dict[str, Any],
        config: dict[str, Any],
        store: dict[str, Any],
    ) -> dict[str, Any]:
        pf = mbt.Portfolio()
        for item in portfolio.get("strategies", []):
            strat = _get_strategy(item.get("strategy_code"), item.get("strategy_json"))
            pf.strategy(strat, weight=float(item.get("weight", 1.0)))
        for rule in portfolio.get("risk_rules", []) or []:
            kind = rule.get("type")
            if kind == "MaxDrawdown":
                pf.max_drawdown(pct=float(rule["threshold_pct"]))
            elif kind == "MaxGrossExposure":
                pf.max_gross_exposure(pct=float(rule["max_pct"]))
            elif kind == "MaxNetExposure":
                pf.max_net_exposure(pct=float(rule["max_pct"]))
            elif kind == "StrategyKillSwitch":
                pf.strategy_kill_switch(
                    strategy=rule["strategy"],
                    max_loss_pct=float(rule["max_loss_pct"]),
                )
        reb = portfolio.get("rebalance") or {}
        rtype = reb.get("type")
        if rtype == "Periodic":
            pf.rebalance_periodic(every_n_bars=int(reb["every_n_bars"]))
        elif rtype == "Threshold":
            pf.rebalance_threshold(drift_pct=float(reb["drift_pct"]))
        else:
            pf.no_rebalance()

        cfg = build_backtest_config(config)
        st = resolve_store(store)
        result = mbt.run_portfolio(pf, cfg, st)
        out = _result_to_dict(result)
        out["per_strategy"] = getattr(result, "_per_strategy", None)
        return out

    @mcp.tool(
        description=(
            "Generate a tearsheet PNG from a backtest run. Saves to "
            "output_path (default: ./tearsheet.png) and returns its path."
        ),
    )
    def plot_tearsheet(
        config: dict[str, Any],
        store: dict[str, Any],
        *,
        strategy_code: str | None = None,
        strategy_json: str | None = None,
        output_path: str = "tearsheet.png",
        dpi: int = 150,
    ) -> dict[str, str]:
        strat = _get_strategy(strategy_code, strategy_json)
        cfg = build_backtest_config(config)
        st = resolve_store(store)
        result = mbt.run(strat, cfg, st)
        from manifoldbt.plot.tearsheet import tearsheet  # lazy: requires matplotlib
        tearsheet(result, path=output_path, show=False, dpi=dpi)
        return {"path": os.path.abspath(output_path)}

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    @mcp.resource("manifoldbt://reference/indicators")
    def indicators_reference() -> str:
        """Markdown reference for all built-in indicators."""
        return render_indicators_markdown()

    @mcp.resource("manifoldbt://reference/api")
    def api_reference() -> str:
        """High-level API tour for manifoldbt."""
        return render_api_overview()

    @mcp.resource("manifoldbt://reference/strategy-authoring")
    def strategy_authoring_doc() -> str:
        """Full strategy authoring guide (best-effort from the installed package)."""
        try:
            pkg_root = Path(mbt.__file__).resolve().parent
        except Exception:  # pragma: no cover
            return render_api_overview()
        for candidate in (
            pkg_root.parent.parent / "docs" / "strategy-authoring.md",
            pkg_root.parent / "docs" / "strategy-authoring.md",
        ):
            if candidate.is_file():
                return candidate.read_text()
        return render_api_overview()

    @mcp.resource("manifoldbt://examples/{slug}")
    def example_source(slug: str) -> str:
        """Source of a bundled example strategy by filename."""
        if _EXAMPLES_DIR is None:
            raise ValueError("examples directory not found in manifoldbt install")
        path = (_EXAMPLES_DIR / slug).resolve()
        if not str(path).startswith(str(_EXAMPLES_DIR.resolve())) or not path.is_file():
            raise ValueError(f"unknown example '{slug}'")
        return path.read_text()

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

    @mcp.prompt(description="Scaffold a new manifoldbt strategy from a natural-language description.")
    def write_strategy(description: str, universe: str = "BTC-USDT:perp") -> str:
        return (
            "Write a manifoldbt strategy for the following idea:\n\n"
            f"{description}\n\n"
            "Requirements:\n"
            "- Use the manifoldbt Python DSL only (no manual pandas/NumPy).\n"
            "- Produce a single `strategy` variable built with "
            "`mbt.Strategy.create(...)`.\n"
            "- Define each intermediate series via `.signal(name, expr)` so "
            "it is inspectable.\n"
            f"- Default universe: {universe}. Adjust if the idea implies another instrument.\n"
            "- If the idea mentions parameters, declare them with `param('name', default=..., range=(lo, hi))`.\n"
            "- After the strategy, call the `build_strategy` MCP tool to "
            "validate the output.\n"
        )

    @mcp.prompt(description="Analyse the metrics dict returned by run_backtest.")
    def analyze_result(metrics_json: str) -> str:
        return (
            "The following JSON is the `metrics` payload from manifoldbt's "
            "`run_backtest` tool. Write a concise research note covering:\n"
            "- Overall edge (CAGR vs volatility / Sharpe / Sortino).\n"
            "- Drawdown profile and recovery.\n"
            "- Trade quality (win rate, profit factor, expectancy).\n"
            "- Any red flags (e.g. lookahead warnings, unrealistic Sharpe).\n"
            "- Suggested next experiments.\n\n"
            f"Metrics:\n```json\n{metrics_json}\n```\n"
        )

    return mcp


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: ``manifoldbt-mcp``."""
    parser = argparse.ArgumentParser(
        prog="manifoldbt-mcp",
        description="Run the manifoldbt MCP server.",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Use streamable HTTP transport instead of stdio.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP transport (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for HTTP transport (default: 8765).",
    )
    args = parser.parse_args(argv)

    server = build_server()

    if args.http:
        # FastMCP's streamable HTTP transport.
        server.settings.host = args.host
        server.settings.port = args.port
        server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
