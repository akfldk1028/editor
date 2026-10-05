"""Deterministic MASS-to-elevation execution adapter.

The shared agent repository owns identity and long-lived private memory. This
MAAS-owned adapter is the deployable geometry boundary used by the compiler
pipeline, so a checkout of ARR never depends on an unpinned nested repository.
"""

from backend.app.modules.design.generation.maas.agents.elevation_agent.facade_strategy import select_facade_strategy
from backend.app.modules.design.generation.maas.agents.elevation_agent.image_proposal import generate_elevation_image_proposal
from backend.app.modules.design.generation.maas.agents.elevation_agent.multi_view_consistency import evaluate_multi_view_consistency
from backend.app.modules.design.generation.maas.agents.elevation_agent.multi_view_contract import FACADE_VIEWS, MultiViewCritic, proposal_identity
from backend.app.modules.design.generation.maas.agents.elevation_agent.multi_view_proposal import generate_multi_view_elevation_proposal
from backend.app.modules.design.generation.maas.agents.elevation_agent.runtime import generate_elevation_bundle

__all__ = [
    "generate_elevation_bundle",
    "generate_elevation_image_proposal",
    "generate_multi_view_elevation_proposal",
    "evaluate_multi_view_consistency",
    "FACADE_VIEWS",
    "MultiViewCritic",
    "proposal_identity",
    "select_facade_strategy",
]
