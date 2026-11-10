"""Explicit caller-owned market data for one run, with no built-in fallback.

This is an in-process API, not an import-path/plugin or remote-tool loader.
LangGraph propagates context variables to its tool tasks as for run_config.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import re
from typing import Protocol


class DataAdapter(Protocol):
    name: str

    def get_data(self, method: str, *args, **kwargs) -> str: ...

    def instrument_context(self, ticker: str, asset_type: str, trade_date: str | None) -> str: ...

    def fingerprint(self) -> str: ...


_adapter: ContextVar[DataAdapter | None] = ContextVar("research_data_adapter", default=None)


def get_data_adapter() -> DataAdapter | None:
    return _adapter.get()


@contextmanager
def use_data_adapter(adapter: DataAdapter):
    """Bind a trusted caller adapter; failures never select a default vendor."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", adapter.name):
        raise ValueError("Invalid data adapter name")
    if not re.fullmatch(r"[a-f0-9]{64}", adapter.fingerprint()):
        raise ValueError("Data adapter requires a configuration SHA256 fingerprint")
    token = _adapter.set(adapter)
    try:
        yield
    finally:
        _adapter.reset(token)
