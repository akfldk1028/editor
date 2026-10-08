"""The Revision Agent's say in routing — which agents must run again for the open findings (card: revision_triage)."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='revision',
    label='재검토 판정 (Revision Agent)',
    default_skill=None,
    default_goal='limits',
    keywords=('재검토', '다시 돌려', '다시 검토', '누가 다시', '어떤 에이전트', '되돌아', '열린 이슈', '남은 문제', '찾은 문제', '이슈 정리',
              '다음 라운드', '반복 검토'),
)
