"""Safe-ish Python DSL execution for strategy authoring via MCP.

The MCP tools accept strategy definitions as Python snippets that use the
public ``manifoldbt`` DSL.  The snippet is executed in a scoped namespace
that pre-imports the DSL symbols.  The snippet must define a ``strategy``
variable holding a :class:`manifoldbt.Strategy` instance.

This is **not** a full sandbox — it is the user's own machine executing
their own code — but the namespace is constructed so a newcomer can write
useful strategies without writing any ``import`` statements.
"""
from __future__ import annotations

from typing import Any

from manifoldbt.strategy import Strategy

# ----------------------------------------------------------------------
# Namespace builder
# ----------------------------------------------------------------------


def build_dsl_namespace() -> dict[str, Any]:
    """Return a dict pre-populated with the manifoldbt DSL symbols.

    Everything exposed here matches what a user would normally have to
    import from ``manifoldbt`` and ``manifoldbt.indicators`` to author a
    strategy.
    """
    import manifoldbt as mbt
    from manifoldbt import expr as expr_mod
    from manifoldbt import indicators as ind

    ns: dict[str, Any] = {
        # top-level package
        "mbt": mbt,
        "manifoldbt": mbt,
        # core DSL
        "Strategy": mbt.Strategy,
        "Portfolio": mbt.Portfolio,
        "col": mbt.col,
        "lit": mbt.lit,
        "when": mbt.when,
        "param": mbt.param,
        "asset": mbt.asset,
        "symbol_ref": mbt.symbol_ref,
        "exo": mbt.exo,
        "hold": mbt.hold,
        "tf": mbt.tf,
        "scan": mbt.scan,
        "s": mbt.s,
        # indicators module + everything public
        "indicators": ind,
        "ind": ind,
    }
    for name in dir(ind):
        if name.startswith("_"):
            continue
        ns[name] = getattr(ind, name)

    # Convenience: bring every non-underscore expr helper too
    for name in dir(expr_mod):
        if name.startswith("_") or name in ns:
            continue
        ns[name] = getattr(expr_mod, name)

    return ns


# ----------------------------------------------------------------------
# Strategy compilation
# ----------------------------------------------------------------------


def compile_strategy_code(code: str, *, name_hint: str | None = None) -> Strategy:
    """Execute a Python DSL snippet and return the resulting Strategy.

    The snippet must either:

    - assign a ``strategy`` variable to a :class:`Strategy` instance, or
    - end with an expression that evaluates to a :class:`Strategy` (this
      form is detected by scanning ``locals()`` after ``exec``).

    Raises :class:`ValueError` if no Strategy is found.
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError("strategy_code must be a non-empty Python snippet")

    ns = build_dsl_namespace()
    locals_: dict[str, Any] = {}
    try:
        exec(compile(code, "<mcp-strategy>", "exec"), ns, locals_)
    except Exception as exc:
        raise ValueError(f"strategy_code failed to execute: {exc}") from exc

    # Prefer an explicit ``strategy`` binding
    strat = locals_.get("strategy") or ns.get("strategy")
    if isinstance(strat, Strategy):
        if name_hint and not strat.name:
            strat.name = name_hint
        return strat

    # Otherwise, scan locals for the last Strategy assigned
    for value in reversed(list(locals_.values())):
        if isinstance(value, Strategy):
            return value

    raise ValueError(
        "strategy_code must assign a Strategy to a variable named 'strategy'. "
        "Example: strategy = mbt.Strategy.create('demo').signal(...).size(...)"
    )
