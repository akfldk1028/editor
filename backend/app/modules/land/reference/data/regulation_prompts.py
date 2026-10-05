"""
LLM extraction prompts — 법조문 텍스트에서 규제 수치를 structured JSON으로 추출.

각 프롬프트는 {article_text}와 {zone_name} placeholder를 포함.
"""

SYSTEM_PROMPT = (
    "당신은 한국 건축법규 전문가입니다. "
    "법조문 텍스트에서 규제 수치를 정확히 추출하여 JSON으로 반환합니다. "
    "추측하지 말고, 조문에 명시된 수치만 추출하세요. "
    "조문에 없는 정보는 null로 표시하세요."
)

# ── 정북 일조사선 (건축법 §61①, 시행령 §86①) ──────────
SUNLIGHT_PROMPT = """\
다음은 건축법 시행령 제86조(일조 등의 확보를 위한 건축물의 높이 제한) 관련 법조문입니다.

<법조문>
{article_text}
</법조문>

용도지역: {zone_name}

위 조문에서 **정북 일조사선 이격거리** 규정을 추출하세요.
반드시 아래 JSON 형식으로만 답하세요 (설명 없이 JSON만):

{{
  "sunlight_applies": true/false,
  "sunlight_rules": [
    {{"condition": "H <= Xm", "setback_m": Y}},
    {{"condition": "H > Xm", "formula": "H * Z"}}
  ],
  "sunlight_article": "근거 조항 (예: 건축법 시행령 제86조제1항)",
  "applies_to_zones": ["적용되는 용도지역 목록"],
  "exceptions": ["적용 예외 사항"]
}}"""

# ── 인접대지 이격거리 (건축법 §58, 시행령 §80조의2) ────
ADJACENT_SETBACK_PROMPT = """\
다음은 건축법 제58조(대지 안의 공지) 및 시행령 제80조의2 관련 법조문입니다.

<법조문>
{article_text}
</법조문>

용도지역: {zone_name}

위 조문에서 **인접 대지경계선으로부터의 이격거리** 규정을 추출하세요.
반드시 아래 JSON 형식으로만 답하세요 (설명 없이 JSON만):

{{
  "adjacent_setback_m": 최소이격거리(숫자),
  "adjacent_setback_article": "근거 조항",
  "height_dependent_rules": [
    {{"condition": "높이 조건", "setback_m": 이격거리}}
  ],
  "notes": "조례 위임 여부 등 참고사항"
}}"""

# ── 건폐율/용적률 (국토계획법 시행령 §84, §85) ─────────
BCR_FAR_PROMPT = """\
다음은 국토계획법 시행령 제84조(건폐율) 및 제85조(용적률) 관련 법조문입니다.

<법조문>
{article_text}
</법조문>

용도지역: {zone_name}

위 조문에서 해당 용도지역의 **건폐율 상한**과 **용적률 상한**을 추출하세요.
반드시 아래 JSON 형식으로만 답하세요 (설명 없이 JSON만):

{{
  "bcr_pct": 건폐율상한(숫자, 퍼센트),
  "bcr_article": "근거 조항",
  "far_pct": 용적률상한(숫자, 퍼센트),
  "far_article": "근거 조항",
  "notes": "조례 위임 범위 등 참고사항"
}}"""

# ── 높이제한 (건축법 §60, 시행령 §82) ──────────────────
HEIGHT_PROMPT = """\
다음은 건축법 제60조(건축물의 높이 제한) 관련 법조문입니다.

<법조문>
{article_text}
</법조문>

용도지역: {zone_name}

위 조문에서 해당 용도지역의 **건축물 높이 제한** 규정을 추출하세요.
반드시 아래 JSON 형식으로만 답하세요 (설명 없이 JSON만):

{{
  "height_limit_m": 높이제한(숫자, 미터) 또는 null,
  "height_article": "근거 조항",
  "road_width_rule": "도로폭 기반 높이제한 규칙 (예: 도로폭 × 1.5배)",
  "notes": "참고사항"
}}"""

# ── 건축지정선/한계선 (국토계획법 §49-52, 건축법 §46-47) ──
BUILDING_DESIGNATION_PROMPT = """\
다음은 국토계획법 제49조~제52조(지구단위계획) 및 건축법 제46조~제47조(건축선) 관련 법조문입니다.

<법조문>
{article_text}
</법조문>

용도지역: {zone_name}

위 조문에서 **건축지정선/건축한계선 후퇴거리** 규정을 추출하세요.
건축지정선은 지구단위계획에서 건축물이 반드시 맞닿아야 하는 선이고,
건축한계선은 건축물이 넘을 수 없는 선입니다.
반드시 아래 JSON 형식으로만 답하세요 (설명 없이 JSON만):

{{
  "building_designation_setback_m": 후퇴거리(숫자, 미터) 또는 null,
  "building_designation_article": "근거 조항",
  "line_type": "지정선" 또는 "한계선" 또는 null,
  "notes": "참고사항"
}}"""

# regulation_type → (검색 쿼리 목록, 프롬프트 템플릿)
EXTRACTION_CONFIG = {
    "sunlight": {
        "queries": [
            "정북 일조사선 이격거리",
            "건축법 시행령 제86조 일조",
            "정북방향 인접 대지경계선 높이",
        ],
        "prompt": SUNLIGHT_PROMPT,
    },
    "adjacent_setback": {
        "queries": [
            "대지 안의 공지 인접대지 이격거리",
            "건축법 시행령 제80조의2",
            "인접 대지경계선 건축물 이격",
        ],
        "prompt": ADJACENT_SETBACK_PROMPT,
    },
    "bcr_far": {
        "queries": [
            "{zone_name} 건폐율 용적률",
            "국토계획법 시행령 제84조 건폐율",
            "국토계획법 시행령 제85조 용적률",
        ],
        "prompt": BCR_FAR_PROMPT,
    },
    "height": {
        "queries": [
            "건축물 높이제한 가로구역별",
            "건축법 제60조 높이 제한",
        ],
        "prompt": HEIGHT_PROMPT,
    },
    "building_designation": {
        "queries": [
            "건축지정선 건축한계선",
            "지구단위계획 건축선 후퇴",
            "국토계획법 제52조 지구단위계획 건축물",
        ],
        "prompt": BUILDING_DESIGNATION_PROMPT,
    },
}
