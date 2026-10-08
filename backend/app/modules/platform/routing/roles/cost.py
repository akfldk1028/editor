"""The Cost Agent's say in routing — construction cost: unit rates, budget, estimate (S1: Seoul 2024 tables)."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='cost',
    label='공사비 (Cost Agent)',
    default_skill=None,
    default_goal='cost',
    keywords=('공사비', '건축비', '비용', '예산', '견적', '평당', '단가', '원가', '얼마나 들', '얼마 들', '사업비'),
)
