"""Second-stage preference distillation for MAAS candidates.

This package must not decide legality. It only scores already legal, rendered,
or reviewable candidates for architectural preference.
"""

from backend.app.modules.design.generation.maas.preference.concept_schema import PREFERENCE_SCHEMA_VERSION, build_preference_distillation
from backend.app.modules.design.generation.maas.preference.generation_feedback import GENERATION_FEEDBACK_SCHEMA_VERSION, build_vlm_generation_feedback
from backend.app.modules.design.generation.maas.preference.loop import PreferenceLoopCallbacks, apply_preference_loop, preference_loop_config, preference_score, preference_vlm_scored
from backend.app.modules.design.generation.maas.preference.reranker import RERANK_SCHEMA_VERSION, rerank_candidates

__all__ = [
    "GENERATION_FEEDBACK_SCHEMA_VERSION",
    "PREFERENCE_SCHEMA_VERSION",
    "PreferenceLoopCallbacks",
    "RERANK_SCHEMA_VERSION",
    "apply_preference_loop",
    "build_preference_distillation",
    "build_vlm_generation_feedback",
    "preference_loop_config",
    "preference_score",
    "preference_vlm_scored",
    "rerank_candidates",
]
