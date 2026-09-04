"""Schema abstractions and implementations."""

from .base import SchemaRegistry
from .cdif.discovery.cdif_discovery import CDIFDiscoveryProfile
from .datacite import DataCiteSchema46

_registry = SchemaRegistry()
_registry.register(DataCiteSchema46())
_registry.register(CDIFDiscoveryProfile())
# NOTE: DataCiteSchema46 stays registered for now -- config/agents.yaml
# still targets it. Per docs/codata_mcp_croissant_cdifspecs.md sec 3.5,
# CDIFDiscoveryProfile is meant to become the SOLE generation-target
# schema (DataCiteSchema46 deregistered, moved to exporter-only use). That
# cutover is a separate, deliberately atomic change -- it must land
# together with config/agents.yaml's schema_name flip + full prompt
# rewrite + every test asserting on "datacite-4.6" (see
# docs/cdif_pivot_implementation_plan.md Step 2) -- not before. Until
# then, both schemas are registered so CDIFDiscoveryProfile can be
# developed and tested without breaking the live DataCite pipeline.


def get_registry() -> SchemaRegistry:
    return _registry
