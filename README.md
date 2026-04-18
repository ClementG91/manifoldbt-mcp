# manifoldbt-mcp

[![PyPI](https://img.shields.io/pypi/v/manifoldbt-mcp.svg)](https://pypi.org/project/manifoldbt-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/manifoldbt-mcp.svg)](https://pypi.org/project/manifoldbt-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

> **Model Context Protocol (MCP) server for
> [manifoldbt](https://github.com/Jimmy7892/manifoldbt)** — the Rust-powered
> backtesting engine for quantitative research.

Expose the full manifoldbt backtesting engine to any MCP-compatible client
(Claude Desktop, Claude Code, Cursor, Devin, VS Code, Windsurf, …). Let an LLM
author strategies, run backtests, sweep parameters, and generate tearsheets —
without the user writing a line of Python.

This package is **not affiliated with the manifoldbt authors**; it is a thin
adapter that imports the published `manifoldbt` wheel and wraps its Python
API behind an MCP server. All heavy lifting is done by the underlying Rust
engine.

---

## Install

```bash
pip install manifoldbt-mcp
```

This pulls in `manifoldbt` and the reference `mcp` Python SDK as
dependencies. Python 3.10+ is required.

Optional extras:

```bash
pip install "manifoldbt-mcp[plot]"   # matplotlib, for plot_tearsheet
pip install "manifoldbt-mcp[dev]"    # pytest, ruff, matplotlib
```

## Run

```bash
manifoldbt-mcp                          # stdio transport (default)
manifoldbt-mcp --http --port 8765       # streamable-HTTP transport
manifoldbt-mcp --http --host 0.0.0.0    # remote deployment
```

---

## Client configuration

### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`
(or `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "manifoldbt": {
      "command": "manifoldbt-mcp"
    }
  }
}
```

### Claude Code

```bash
claude mcp add manifoldbt -- manifoldbt-mcp
```

### Cursor / Windsurf

```json
{
  "mcpServers": {
    "manifoldbt": {
      "command": "manifoldbt-mcp"
    }
  }
}
```

### VS Code (Continue, Cline, …)

Any MCP-over-stdio client will work — just point it at the `manifoldbt-mcp`
binary that `pip` installed on your `PATH`.

### Remote (HTTP)

```bash
manifoldbt-mcp --http --host 0.0.0.0 --port 8765
```

Then connect your MCP client to `http://<host>:8765/mcp`.

---

## What is exposed

### 20 tools

| Tool | Purpose |
|------|---------|
| `get_version` | Return manifoldbt version + license tier (Community / Pro). |
| `activate_license` | Activate a Pro license key for the running process. |
| `list_indicators_tool` | Enumerate all 45+ indicators with their Python signatures. |
| `list_examples`, `get_example` | Browse / fetch bundled example strategies. |
| `list_symbols`, `resolve_symbol` | Inspect a DataStore, resolve tickers. |
| `ingest_data` | Pull bars from Binance / Hyperliquid (Databento / Massive on Pro). |
| `build_strategy` | Compile a Python DSL snippet → StrategyDef JSON + params. |
| `validate_strategy` | Validate a StrategyDef JSON through the Rust compiler. |
| `run_backtest` | Run a single backtest and return metrics + summary. |
| `run_batch` | Run many strategies in parallel on a shared data load. |
| `run_sweep` | Cartesian parameter sweep, ranked by any metric. |
| `run_sweep_2d` | 2-D parameter heatmap. |
| `run_walk_forward` | Walk-forward optimisation (Pro). |
| `run_stability` | Parameter stability analysis. |
| `run_monte_carlo` | Trade-permutation Monte Carlo on a fresh backtest. |
| `run_stochastic` | SDE path simulation (GBM, Heston, Merton, GARCH-JD, or custom). |
| `run_portfolio` | Multi-strategy portfolio with risk rules & rebalancing. |
| `plot_tearsheet` | Render a full tearsheet PNG from a backtest. |

### 3 resources + 1 template

| URI | Content |
|-----|---------|
| `manifoldbt://reference/api` | Quick API tour. |
| `manifoldbt://reference/indicators` | Full indicator reference (Markdown). |
| `manifoldbt://reference/strategy-authoring` | The strategy authoring guide shipped with manifoldbt. |
| `manifoldbt://examples/{filename}` | Source of a bundled example (e.g. `01_trend_following.py`). |

### 2 prompts

- **`write_strategy(description, universe="BTC-USDT:perp")`** — scaffold a new
  strategy from a natural-language description.
- **`analyze_result(metrics_json)`** — turn a `run_backtest` metrics payload
  into a research note.

---

## Ergonomics

Every tool is JSON-friendly so LLM clients don't have to think about types:

- **Dates** — ISO strings: `"2022-01-01"` or `"2022-01-01 09:30:00"`.
- **Intervals** — shorthand: `"1h"`, `"5m"`, `"15s"`, `"1d"`.
- **Fees** — preset names: `"binance_perps"`, `"binance_spot"`, `"zero"`; or
  a dict with individual overrides.
- **Slippage** — `{"kind": "fixed_bps", "bps": 2}`,
  `{"kind": "volume_impact", "impact_coeff": 0.1, "exponent": 1.5}`, etc.

### Writing a strategy from a client

Strategies are authored as **Python DSL snippets** executed in a namespace
that pre-imports every manifoldbt symbol — so the LLM never has to write
`import` statements:

```python
fast = ema(close, 12)
slow = ema(close, 26)

strategy = (
    Strategy.create("ema_cross")
    .signal("fast", fast)
    .signal("slow", slow)
    .size(when(fast > slow, lit(0.5), lit(0.0)))
    .stop_loss(pct=3.0)
)
```

Or, if the client prefers, send the already-serialised `StrategyDef` JSON
through `strategy_json` on any tool.

### Example `run_backtest` payload

```json
{
  "strategy_code": "fast = ema(close, 12)\nslow = ema(close, 26)\nstrategy = Strategy.create('ema_cross').signal('fast', fast).signal('slow', slow).size(when(fast > slow, lit(0.5), lit(0.0))).stop_loss(pct=3.0)",
  "config": {
    "universe": {"binance": ["BTC-USDT:perp"]},
    "start": "2022-01-01",
    "end": "2024-01-01",
    "bar_interval": "1h",
    "initial_capital": 10000,
    "fees": "binance_perps",
    "slippage": {"kind": "fixed_bps", "bps": 2},
    "warmup_bars": 60
  },
  "store": {
    "data_root": "data",
    "metadata_db": "metadata/metadata.sqlite"
  }
}
```

---

## Typical LLM session

1. `list_indicators_tool` → discover available indicators.
2. Use the `write_strategy` prompt → draft a strategy.
3. `build_strategy(strategy_code=…)` → validated StrategyDef + declared parameters.
4. `run_backtest(…)` → metrics + summary.
5. `run_sweep(…)` ranked by Sharpe → find the best variant.
6. `plot_tearsheet(…)` → PNG tearsheet on disk.
7. Use the `analyze_result` prompt → research note.

---

## Security

- The server runs with the permissions of the launching process.
- `strategy_code` is executed in-process by the Python interpreter — **there
  is no sandbox**. The DSL namespace is convenient (pre-imported manifoldbt
  symbols), but nothing prevents arbitrary Python from running. Only use this
  server with trusted clients, or run it isolated (dedicated venv, container,
  restricted user).
- No inbound network unless you explicitly enable `--http`.

---

## Development

```bash
git clone https://github.com/ClementG91/manifoldbt-mcp
cd manifoldbt-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```

---

## Related

- Upstream engine: <https://github.com/Jimmy7892/manifoldbt>
- Model Context Protocol: <https://modelcontextprotocol.io>
- Reference Python SDK: <https://github.com/modelcontextprotocol/python-sdk>

---

## License

MIT — see [LICENSE](./LICENSE).
