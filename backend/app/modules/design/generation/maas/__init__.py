"""ARR-local MAAS generator.

MAAS is organized as legal-envelope-first generation:

1. ``legal_envelope`` converts ARR constraints into the buildable/capacity
   boundary.
2. ``seed_library`` treats legacy ARR mass algorithms as seed/operator sources.
3. ``legal_mesh_optimizer`` repairs, validates, ranks, and returns candidates.

OpenSCAD export remains an output adapter, not the mass-generation source.
"""

from importlib import import_module

# Importing a pure mesh exporter must not initialize the legal optimizer,
# database driver, or their memory-heavy dependencies.
_EXPORT_MODULES = {
    "export_mass_geojson_to_scad": ".geometry_exporter",
    "mass_geojson_to_scad": ".geometry_exporter",
    "build_legal_envelope": ".legal_envelope",
    "generate_legal_mass_variants": ".legal_mesh_optimizer",
    "SCHEMA_VERSION": ".evidence",
    "build_maas_evidence_bundle": ".evidence",
}


def __getattr__(name):
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value

__all__ = [
    "SCHEMA_VERSION",
    "build_legal_envelope",
    "build_maas_evidence_bundle",
    "export_mass_geojson_to_scad",
    "generate_legal_mass_variants",
    "mass_geojson_to_scad",
]
