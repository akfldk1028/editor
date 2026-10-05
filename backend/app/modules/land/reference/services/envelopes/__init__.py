"""
3D envelope 생성 모듈.

각 envelope은 **법규 §86① 프로필을 정확히 반영**하는 독립된 함수.
frontend `design/lib/envelope-renderer.ts`에서 대응 renderer로 렌더.

Contract (공통):
  input : shapely 지오메트리 + UTM 좌표 + 법규 파라미터
  output: dict | None — walls/slanted_polygons/profile_polylines/... 구조

수정 전 반드시 `memory/arr/session14/envelope-locked-spec.md` 읽을 것.
"""

from backend.app.modules.land.reference.services.envelopes.sunlight import compute_sunlight_envelope

__all__ = ["compute_sunlight_envelope"]
