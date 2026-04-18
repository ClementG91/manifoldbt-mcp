"""DataStore handle resolution for MCP tools.

MCP tools are stateless from the client's perspective, so each tool call
takes an optional ``store`` argument describing how to open the parquet
store.  To avoid re-opening the store on every call, handles are cached
in-process keyed by ``(data_root, metadata_db)``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from manifoldbt._native import DataStore

_STORE_CACHE: dict[tuple, DataStore] = {}


def resolve_store(spec: Any) -> DataStore:
    """Open (or fetch from cache) a :class:`DataStore` for the spec.

    Accepts either an existing ``DataStore`` or a dict like::

        {"data_root": "data", "metadata_db": "metadata/metadata.sqlite"}

    When ``metadata_db`` is omitted, ``<data_root>/../metadata/metadata.sqlite``
    is used.
    """
    if isinstance(spec, DataStore):
        return spec
    if spec is None:
        spec = {}
    if not isinstance(spec, Mapping):
        raise TypeError("store must be a dict or DataStore")

    data_root = str(spec.get("data_root", "data"))
    metadata_db = str(spec.get("metadata_db") or "metadata/metadata.sqlite")
    arrow_dir: str | None = spec.get("arrow_dir")

    key = (data_root, metadata_db, arrow_dir)
    cached = _STORE_CACHE.get(key)
    if cached is not None:
        return cached

    if arrow_dir is not None:
        store = DataStore(data_root=data_root, metadata_db=metadata_db, arrow_dir=arrow_dir)
    else:
        store = DataStore(data_root=data_root, metadata_db=metadata_db)
    _STORE_CACHE[key] = store
    return store


def clear_store_cache() -> None:
    """Drop all cached DataStore handles (mostly useful for tests)."""
    _STORE_CACHE.clear()
