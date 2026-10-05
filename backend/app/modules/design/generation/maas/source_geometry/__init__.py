"""ARR-native source geometry compiler for MAAS grammar sequences."""

from backend.app.modules.design.generation.maas.source_geometry.compiler import compile_component_graph_to_source_mass, compile_sequence_to_source_mass, source_mass_to_variant
from backend.app.modules.design.generation.maas.source_geometry.coherence import COHERENCE_SCHEMA_VERSION, evaluate_source_volume_coherence
from backend.app.modules.design.generation.maas.source_geometry.formal_principles import CANONICAL_FORMAL_PRINCIPLES, normalize_formal_principle
from backend.app.modules.design.generation.maas.source_geometry.genome import GENOME_SCHEMA_VERSION, MassingGenome, build_massing_genome
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceVolume, VerbTrace
from backend.app.modules.design.generation.maas.source_geometry.polygon_quality import POLYGON_QUALITY_SCHEMA_VERSION, evaluate_polygon_quality, repair_source_polygon

__all__ = [
    "CANONICAL_FORMAL_PRINCIPLES",
    "COHERENCE_SCHEMA_VERSION",
    "GENOME_SCHEMA_VERSION",
    "MassingGenome",
    "POLYGON_QUALITY_SCHEMA_VERSION",
    "SourceMass",
    "SourceVolume",
    "VerbTrace",
    "build_massing_genome",
    "compile_sequence_to_source_mass",
    "compile_component_graph_to_source_mass",
    "evaluate_source_volume_coherence",
    "evaluate_polygon_quality",
    "normalize_formal_principle",
    "repair_source_polygon",
    "source_mass_to_variant",
]
