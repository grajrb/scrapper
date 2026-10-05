"""Adapter package: auto-loads every adapter module as a plugin.

Drop a new ``*.py`` file defining a :class:`SourceAdapter` subclass
decorated with ``@register`` into this package and it becomes available
to ``config/sources.yaml`` - no changes to the core application needed.
"""
from __future__ import annotations

import importlib
import pkgutil

from .base import (  # noqa: F401  (re-exported for convenience)
    SourceAdapter,
    available_sources,
    create_adapter,
    get_adapter_class,
    register,
)

_SKIP = {"base", "http"}


def load_all_adapters() -> list[str]:
    """Import every adapter module so its @register decorator runs."""
    for module in pkgutil.iter_modules(__path__):
        if module.name in _SKIP:
            continue
        importlib.import_module(f"{__name__}.{module.name}")
    return available_sources()


# Load built-in adapters on package import.
load_all_adapters()
