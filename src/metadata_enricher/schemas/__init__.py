"""Schema abstractions and implementations."""

from .base import SchemaRegistry
from .datacite import DataCiteSchema46

_registry = SchemaRegistry()
_registry.register(DataCiteSchema46())


def get_registry() -> SchemaRegistry:
    return _registry
