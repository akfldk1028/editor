"""Program-conditioned architectural massing."""

from backend.app.modules.design.generation.maas.program_massing.profiles import load_program_profiles, program_reference_contract, resolve_program_profile
from backend.app.modules.design.generation.maas.program_massing.research_priors import load_research_search_priors, program_search_prior
from backend.app.modules.design.generation.maas.program_massing.scoring import attach_program_massing_evidence
from backend.app.modules.design.generation.maas.program_massing.sequences import creative_archive_sequences, program_archive_sequences, program_seed_sequences
from backend.app.modules.design.generation.maas.program_massing.creative import attach_creative_mass_evidence, creative_seed_sequences
from backend.app.modules.design.generation.maas.program_massing.spatial_evaluation import attach_program_spatial_evidence
from backend.app.modules.design.generation.maas.program_massing.book_projection import book_operation_variants, book_projection_scope, book_sentence_variants, book_variation_indices, compose_program_with_book_operations
from backend.app.modules.design.generation.maas.program_massing.book_scope import materialize_book_scope, projection_scope
from backend.app.modules.design.generation.maas.program_massing.section_graph import ProgramSectionGraphEdit, apply_program_section_graph_edits, mutate_program_section_sequence, program_section_graph_from_sequence

__all__ = ["ProgramSectionGraphEdit", "apply_program_section_graph_edits", "attach_creative_mass_evidence", "attach_program_massing_evidence", "attach_program_spatial_evidence", "book_operation_variants", "book_projection_scope", "book_sentence_variants", "book_variation_indices", "compose_program_with_book_operations", "creative_archive_sequences", "creative_seed_sequences", "load_program_profiles", "load_research_search_priors", "materialize_book_scope", "mutate_program_section_sequence", "program_archive_sequences", "program_reference_contract", "program_search_prior", "program_section_graph_from_sequence", "program_seed_sequences", "projection_scope", "resolve_program_profile"]
