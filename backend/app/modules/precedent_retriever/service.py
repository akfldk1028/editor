from __future__ import annotations

from backend.app.schemas.precedent import PrecedentCase, RankedPrecedent


def rank_precedents(
    cases: list[PrecedentCase],
    use_type: str,
    target_area: float,
    floors: int,
    tags: list[str],
) -> list[RankedPrecedent]:
    ranked = [
        RankedPrecedent(
            case=case,
            score=_score_case(case, use_type, target_area, floors, tags),
        )
        for case in cases
    ]
    return sorted(ranked, key=lambda item: item.score, reverse=True)


def _score_case(
    case: PrecedentCase,
    use_type: str,
    target_area: float,
    floors: int,
    tags: list[str],
) -> float:
    use_score = 1.0 if case.use_type == use_type else 0.0
    area_gap = abs(case.gross_area - target_area) / max(target_area, 1)
    area_score = max(0.0, 1.0 - area_gap)
    floor_gap = abs(case.floors - floors) / max(floors, 1)
    floor_score = max(0.0, 1.0 - floor_gap)
    tag_score = len(set(case.tags).intersection(tags)) / max(len(set(tags)), 1)
    efficiency = case.metrics.get("efficiency", 0.0)
    return round(use_score * 4 + area_score * 3 + floor_score * 2 + tag_score + efficiency, 4)
