"""
B5 — Typology Recommender (Phase 2)

원리 (Principle):
    부지 정보 (면적, 용도지역 BCR/FAR/높이 제약, 부지 비율) → *어떤 매스 형태가
    최적일지* 추천. 기존 시스템은 사용자가 algorithm 을 직접 선택해야 했는데,
    본 모듈이 자동 추천.

10 매스 형태 (mass_evaluator.py ALGO_LAYOUT):
    additive / subtractive / grid (3 절차적)
    lshape / ushape / cross / courtyard / tower_podium / hshape / radial (7 typological)

방법:
    1. 각 부지 fixture 에서 10 typology × SSIEA 실행 → HV 측정
    2. (site features → top-K typology) ranking 학습
    3. 새 부지 입력 → top-3 typology + score

구현 단순화 (exp010):
    - 작은 데이터 (3 sites × 10 typo = 30 records) 라 *learning 보다 ranking* 으로 시작
    - 각 site feature 와 가장 비슷한 fixture 의 ranking 반환 (k-NN)
    - 향후 데이터 늘어나면 GP/MLP 로 대체

Site features (5-D, normalized):
    - area_m2 / 1000          (대지 면적)
    - bcr_limit / 100         (건폐율 한도)
    - far_limit / 1000        (용적률 한도)
    - height_limit_m / 50     (높이 한도)
    - aspect_ratio            (대지 가로/세로 비)
"""

import logging
import math
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Polygon

from backend.app.modules.design.generation.services.site_geometry import wgs84_to_utm

logger = logging.getLogger(__name__)


TYPOLOGIES = [
    "additive", "subtractive", "grid",
    "lshape", "ushape", "cross", "courtyard",
    "tower_podium", "hshape", "radial",
]


@dataclass
class SiteFeatures:
    """5-D site feature vector for typology matching."""
    area_m2: float
    bcr_limit: float       # %
    far_limit: float       # %
    height_limit_m: float
    aspect_ratio: float    # bbox width/height

    def to_vector(self) -> np.ndarray:
        return np.asarray([
            self.area_m2 / 1000.0,
            self.bcr_limit / 100.0,
            self.far_limit / 1000.0,
            self.height_limit_m / 50.0,
            self.aspect_ratio,
        ], dtype=np.float64)


def site_features_from_polygon(polygon: Polygon, bcr_limit: float,
                                far_limit: float, height_limit_m: float) -> SiteFeatures:
    """WGS84 polygon → SiteFeatures."""
    utm = wgs84_to_utm(polygon)
    minx, miny, maxx, maxy = utm.bounds
    w, h = max(maxx - minx, 1e-3), max(maxy - miny, 1e-3)
    aspect = w / h
    return SiteFeatures(
        area_m2=utm.area,
        bcr_limit=bcr_limit,
        far_limit=far_limit,
        height_limit_m=height_limit_m,
        aspect_ratio=aspect,
    )


@dataclass
class TypologyRanking:
    """학습된 ranking — fixture site들에 대한 (typology → HV) 결과."""
    fixture_features: list[np.ndarray]  # k×5
    typology_hv: list[dict]              # k × {typo: hv}
    fixture_names: list[str]


_GLOBAL_RANKING: TypologyRanking | None = None


def set_ranking(ranking: TypologyRanking) -> None:
    """학습된 ranking 등록 (exp010 결과)."""
    global _GLOBAL_RANKING
    _GLOBAL_RANKING = ranking


def get_ranking() -> TypologyRanking | None:
    """현재 등록된 ranking."""
    return _GLOBAL_RANKING


def recommend(site_features: SiteFeatures, top_k: int = 3) -> list[dict]:
    """
    부지 features 입력 → top-K typology + score.

    방법: site features 와 가장 가까운 fixture 의 ranking 반환 (k-NN with k=1).

    Returns:
        [{"typology": "additive", "score": 280000, "rank": 1, "rationale": "..."}, ...]
    """
    if _GLOBAL_RANKING is None:
        # Fallback — uniform recommendation (default order)
        return [{"typology": t, "score": 0, "rank": i + 1,
                 "rationale": "ranking not learned, default order"}
                for i, t in enumerate(TYPOLOGIES[:top_k])]

    qv = site_features.to_vector()
    fv = np.asarray(_GLOBAL_RANKING.fixture_features)
    # L2 distance (normalized features)
    distances = np.linalg.norm(fv - qv, axis=1)
    nearest_idx = int(np.argmin(distances))
    nearest_name = _GLOBAL_RANKING.fixture_names[nearest_idx]
    typo_hv = _GLOBAL_RANKING.typology_hv[nearest_idx]
    sorted_typos = sorted(typo_hv.items(), key=lambda x: -x[1])
    return [
        {
            "typology": t,
            "score": round(float(hv), 1),
            "rank": i + 1,
            "rationale": f"가장 비슷한 fixture: {nearest_name} (L2 distance={distances[nearest_idx]:.2f})",
        }
        for i, (t, hv) in enumerate(sorted_typos[:top_k])
    ]


__all__ = [
    "TYPOLOGIES",
    "SiteFeatures",
    "site_features_from_polygon",
    "TypologyRanking",
    "set_ranking",
    "get_ranking",
    "recommend",
]
