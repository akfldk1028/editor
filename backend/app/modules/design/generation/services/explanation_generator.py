"""
B7 — Explanation Generator (Phase 2)

원리 (Principle):
    SSIEA가 *최적 매스* 를 찾았을 때, 사용자에게 *왜 이 매스인가* 자연어 설명.

    구조: (수치 결과 + 법규 검증 + typology 추천 + 비슷한 사례) → 한국어 paragraph

    LLM 모드 (gpt-4o-mini): 자연스러운 자연어 (OPENAI_API_KEY 필요)
    Template 모드 (fallback): 정해진 문장 구조 + 동적 수치 삽입

데이터 소스:
    - mass_evaluator outputs (BCR/FAR/daylight/height/setback ...)
    - typology_recommender 추천 결과
    - precedent_rag 검색 결과 (B3)
    - core_planner CorePlan (B6)

용례:
    Frontend Land 페이지에서 SSIEA 결과 카드 클릭 → 설명 패널 펼침
    예: "강남구 역삼동 일반상업지역 부지에 5층 subtractive 매스를 추천합니다.
         BCR 56% (한도 80% 이내), FAR 451% (한도 1300% 이내) 로 법규 통과.
         정북일조 §86①제2호 사선 충족하며, 일조 점수 87점.
         비슷한 사례: 강남 테헤란로 'tower_podium'."

사용법:
    from design.services.explanation_generator import generate_explanation
    text = generate_explanation(metrics={...}, typology='subtractive',
                                 site={'zone': '일반상업지역', ...},
                                 precedent={'name': ...}, core=core_plan)
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExplanationContext:
    """LLM/template 가 받는 통합 입력."""
    metrics: dict           # mass_evaluator outputs
    typology: str           # 추천된 typology
    site: dict              # 부지 정보 (zone, bcr_limit 등)
    precedent: dict | None  # B3 RAG top-1 사례 (optional)
    core: object | None     # B6 CorePlan (optional)


def _safe(d: dict, key: str, default=0):
    """dict.get with type-safe default."""
    v = d.get(key, default)
    return v if v is not None else default


def template_explanation(ctx: ExplanationContext) -> str:
    """
    LLM 미사용 — 정해진 문장 구조 + 수치 삽입.
    한국어 자연스러움 유지하기 위해 구조화된 paragraph.
    """
    m = ctx.metrics
    s = ctx.site
    typology_kr = {
        "additive": "박스 적층형",
        "subtractive": "박스 제거형",
        "grid": "격자형",
        "lshape": "L자형",
        "ushape": "U자형",
        "cross": "십자형",
        "courtyard": "중정형",
        "tower_podium": "타워+포디움형",
        "hshape": "H자형",
        "radial": "방사형",
    }.get(ctx.typology, ctx.typology)

    bcr = _safe(m, "bcr", 0)
    far = _safe(m, "far", 0)
    height = _safe(m, "height", 0)
    floor_area = _safe(m, "floor_area", 0)
    daylight = _safe(m, "daylight_score", 0)
    setback = _safe(m, "min_setback", 0)
    num_floors = round(height / 3.0) if height > 0 else 0

    bcr_limit = _safe(s, "bcr_limit", 60)
    far_limit = _safe(s, "far_limit", 200)
    height_limit = _safe(s, "height_limit_m", 25)
    zone = s.get("zone", "주거지역")

    paragraphs = []

    # 1. 도입 — 무엇을 추천하는가
    paragraphs.append(
        f"본 부지({zone})에 **{typology_kr}** 매스를 {num_floors}층 규모로 추천합니다."
    )

    # 2. 수치 — BCR / FAR / 높이 + 법규 통과 여부
    bcr_pass = "✅" if bcr <= bcr_limit else "⚠️"
    far_pass = "✅" if far <= far_limit else "⚠️"
    h_pass = "✅" if height <= height_limit else "⚠️"
    paragraphs.append(
        f"규제 검증: 건폐율 {bcr:.1f}% (한도 {bcr_limit}%) {bcr_pass}, "
        f"용적률 {far:.1f}% (한도 {far_limit}%) {far_pass}, "
        f"높이 {height:.1f}m (한도 {height_limit}m) {h_pass}, "
        f"인접대지 이격 {setback:.2f}m."
    )

    # 3. 면적 + 일조
    paragraphs.append(
        f"총 연면적 {floor_area:,.0f}m², 일조 점수 {daylight:.0f}/100점."
    )

    # 4. 정북일조 (§86①) 언급 — 주거지역만
    if "주거" in zone:
        paragraphs.append(
            "정북일조 사선 (건축법 §86①제1호 base 1.5m + 제2호 sloped) 충족."
        )

    # 5. 코어 위치 (B6)
    if ctx.core is not None and getattr(ctx.core, "inside_footprint", False):
        paragraphs.append(
            f"서비스 코어({ctx.core.typology_strategy}) 배치 — "
            f"footprint boundary 까지 {ctx.core.distance_to_boundary:.1f}m 마진."
        )

    # 6. 비슷한 사례 (B3)
    if ctx.precedent:
        p = ctx.precedent
        paragraphs.append(
            f"비슷한 사례: {p.get('name', '?')} — {p.get('description', '')[:80]}..."
        )

    return "\n\n".join(paragraphs)


def llm_explanation(ctx: ExplanationContext, model: str = "gpt-4o-mini") -> str | None:
    """OpenAI LLM 호출. 실패/미설정 시 None."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import openai
    except ImportError:
        return None

    try:
        client = openai.OpenAI(api_key=api_key)
        prompt = _build_llm_prompt(ctx)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content":
                 "당신은 건축사 자격을 가진 한국 건축 설계 전문가입니다. "
                 "매스 최적화 결과를 한국어로 설명합니다. "
                 "법규 (건축법, 국토계획법) 용어를 정확히 사용하고, "
                 "수치를 명확히 표시합니다. 4~6 문장 paragraph 1개로 작성합니다."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        # Code review fix: content가 None일 수 있음 (content_filter 등)
        content = resp.choices[0].message.content
        if content is None:
            logger.warning("LLM returned None content (content_filter?), using template fallback")
            return None
        return content.strip() or None
    except Exception as e:
        logger.warning(f"LLM explanation failed: {e}")
        return None


def _build_llm_prompt(ctx: ExplanationContext) -> str:
    """LLM 입력 prompt 구성."""
    parts = [
        f"용도지역: {ctx.site.get('zone', '?')}",
        f"규제 한도: BCR {ctx.site.get('bcr_limit', '?')}%, "
        f"FAR {ctx.site.get('far_limit', '?')}%, 높이 {ctx.site.get('height_limit_m', '?')}m",
        f"추천 매스: {ctx.typology}",
        f"매스 결과: BCR {ctx.metrics.get('bcr', 0):.1f}%, "
        f"FAR {ctx.metrics.get('far', 0):.1f}%, "
        f"높이 {ctx.metrics.get('height', 0):.1f}m, "
        f"연면적 {ctx.metrics.get('floor_area', 0):.0f}m², "
        f"일조 {ctx.metrics.get('daylight_score', 0):.0f}/100",
    ]
    if ctx.precedent:
        parts.append(f"비슷한 사례: {ctx.precedent.get('name')}")
    if ctx.core is not None and getattr(ctx.core, "inside_footprint", False):
        parts.append(f"코어 배치: {getattr(ctx.core, 'typology_strategy', '?')}")
    return "\n".join(parts) + "\n\n위 정보로 4~6문장 한국어 설명을 작성하세요."


def generate_explanation(metrics: dict, typology: str, site: dict,
                         precedent: dict | None = None, core=None,
                         use_llm: bool = True) -> str:
    """
    매스 결과 → 자연어 설명.

    Args:
        metrics: mass_evaluator output dict (bcr/far/daylight/...)
        typology: 추천된 매스 형태
        site: {zone, bcr_limit, far_limit, height_limit_m}
        precedent: B3 PrecedentRAG top-1 (optional)
        core: B6 CorePlan (optional)
        use_llm: True면 OpenAI 시도, 실패 시 template fallback

    Returns:
        한국어 설명 문자열 (paragraphs, \n\n separated)
    """
    ctx = ExplanationContext(metrics=metrics, typology=typology, site=site,
                              precedent=precedent, core=core)

    if use_llm:
        llm_result = llm_explanation(ctx)
        if llm_result:
            return llm_result

    # Fallback to template
    return template_explanation(ctx)


__all__ = [
    "ExplanationContext",
    "template_explanation",
    "llm_explanation",
    "generate_explanation",
]
