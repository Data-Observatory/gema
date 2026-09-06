"""Schema abstractions and implementations."""

from .base import SchemaRegistry
from .cdif.discovery.cdif_discovery import CDIFDiscoveryProfile

_registry = SchemaRegistry()
_registry.register(CDIFDiscoveryProfile())
# CDIFDiscoveryProfile is the SOLE generation-target schema (the cutover
# described in docs/codata_mcp_croissant_cdifspecs.md sec 3.5 -- and in
# docs/cdif_pivot_implementation_plan.md Step 2 -- has landed:
# config/agents.yaml now targets cdif-discovery). DataCiteSchema46 is
# deliberately NOT registered here -- it is exporter-only going forward
# (see exporters/datacite.py, once it exists) and is still imported
# directly by config/migrate.py's legacy-JSON migration path, which is
# unaffected by this registry.


def get_registry() -> SchemaRegistry:
    return _registry
