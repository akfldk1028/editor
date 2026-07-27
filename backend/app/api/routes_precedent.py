from __future__ import annotations

from backend.app.modules.precedent_retriever.service import rank_precedents
from backend.app.schemas.precedent import PrecedentCase, RankedPrecedent


def rank_precedents_route(
    cases: list[PrecedentCase],
    use_type: str,
    target_area: float,
    floors: int,
    tags: list[str],
) -> list[RankedPrecedent]:
    return rank_precedents(cases, use_type=use_type, target_area=target_area, floors=floors, tags=tags)
