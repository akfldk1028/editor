"""The templates a fresh workspace starts with, as literal component dicts.

Nothing here instantiates a client or reads a key: models name their provider
only and credentials arrive from saved settings at load time.
"""

LAND_TEAM_LABEL = 'Land Swarm Analysis Team'

OPENAI_MODEL = {'provider': 'autogen_ext.models.openai.OpenAIChatCompletionClient', 'component_type': 'model',
                'label': 'OpenAI gpt-4o-mini', 'config': {'model': 'gpt-4o-mini'}}

TERMINATE_OR_TEN = {'provider': 'autogen_agentchat.base.OrTerminationCondition', 'component_type': 'termination',
                    'label': 'TERMINATE or 10 messages', 'config': {'conditions': [
                        {'provider': 'autogen_agentchat.conditions.TextMentionTermination', 'component_type': 'termination',
                         'config': {'text': 'TERMINATE'}},
                        {'provider': 'autogen_agentchat.conditions.MaxMessageTermination', 'component_type': 'termination',
                         'config': {'max_messages': 10}}]}}

LAND_ANALYZE_TOOL = {'provider': 'backend.app.adapters.workspace_tools.LandAnalyzeTool', 'component_type': 'tool',
                     'label': 'analyze_land', 'config': {}}
LAW_SEARCH_TOOL = {'provider': 'backend.app.adapters.workspace_tools.LawSearchTool', 'component_type': 'tool',
                   'label': 'search_laws', 'config': {}}


def assistant(name, description, system_message, tools=None, workbench=None):
    config = {'name': name, 'description': description, 'system_message': system_message,
              'model_client': OPENAI_MODEL, 'reflect_on_tool_use': bool(tools), 'tool_call_summary_format': '{result}'}
    if tools:
        config['tools'] = tools
    elif workbench is not None:
        config['workbench'] = workbench
    return {'provider': 'autogen_agentchat.agents.AssistantAgent', 'component_type': 'agent', 'label': name,
            'config': config}


ASSISTANT = assistant('assistant', 'A helpful assistant.',
                      'You are a helpful assistant. Reply TERMINATE when the task is done.',
                      workbench=[{'provider': 'autogen_core.tools.StaticStreamWorkbench', 'component_type': 'workbench',
                                  'config': {'tools': []}}])

USER = {'provider': 'autogen_agentchat.agents.UserProxyAgent', 'component_type': 'agent', 'label': 'user',
        'config': {'name': 'user'}}

ROUNDROBIN_ASSISTANT_TEAM = {
    'provider': 'autogen_agentchat.teams.RoundRobinGroupChat', 'component_type': 'team',
    'label': 'RoundRobin Team', 'description': 'An assistant and you, taking turns.',
    'config': {'participants': [ASSISTANT, USER], 'termination_condition': TERMINATE_OR_TEN}}

LAND_ANALYST = assistant(
    'land_analyst', '토지 규제 데이터를 조회하는 분석가.',
    '너는 토지 분석가다. 주어진 PNU 또는 주소로 analyze_land 도구를 한 번 호출하고, 용도지역·건폐율·용적률·높이·'
    '주요 규제를 한국어로 요약하라. 수치는 도구 결과에 있는 것만 쓰고 추측하지 마라.',
    tools=[LAND_ANALYZE_TOOL])
LEGAL_INTERPRETER = assistant(
    'legal_interpreter', '관련 법조항을 찾아 해석하는 법규 해석가.',
    '너는 건축 법규 해석가다. 앞선 분석의 규제 항목마다 search_laws 도구로 근거 조문을 검색하고, 조문 번호와 핵심 문장을 '
    '인용해 한국어로 정리하라. 검색 결과에 없는 조문은 만들지 마라.',
    tools=[LAW_SEARCH_TOOL])
REPORT_WRITER = assistant(
    'report_writer', '분석과 법규 해석을 보고서로 묶는 작성자.',
    '너는 보고서 작성자다. 앞선 두 메시지를 바탕으로 1) 대지 개요 2) 적용 규제 3) 법적 근거 4) 설계 시 유의점 순으로 '
    '한국어 보고서를 쓰고, 마지막 줄에 TERMINATE 를 적어라.')

LAND_TEAM = {
    'provider': 'autogen_agentchat.teams.RoundRobinGroupChat', 'component_type': 'team',
    'label': LAND_TEAM_LABEL, 'description': '필지 규제 조회 → 법조항 검색 → 보고서. /law 의 AI 심화 분석이 쓴다.',
    'config': {'participants': [LAND_ANALYST, LEGAL_INTERPRETER, REPORT_WRITER],
               'termination_condition': {
                   'provider': 'autogen_agentchat.base.OrTerminationCondition', 'component_type': 'termination',
                   'config': {'conditions': [
                       {'provider': 'autogen_agentchat.conditions.TextMentionTermination', 'component_type': 'termination',
                        'config': {'text': 'TERMINATE'}},
                       {'provider': 'autogen_agentchat.conditions.MaxMessageTermination', 'component_type': 'termination',
                        'config': {'max_messages': 8}}]}}}}

DEFAULT_TEAMS = [ROUNDROBIN_ASSISTANT_TEAM, LAND_TEAM]

DEFAULT_GALLERY = {
    'name': 'Editor defaults',
    'metadata': {'description': 'Teams, agents, tools and terminations the editor ships with.', 'author': 'editor',
                 'version': '1.0.0'},
    'components': {'teams': DEFAULT_TEAMS, 'agents': [ASSISTANT, USER, LAND_ANALYST, LEGAL_INTERPRETER, REPORT_WRITER],
                   'models': [OPENAI_MODEL], 'tools': [LAND_ANALYZE_TOOL, LAW_SEARCH_TOOL],
                   'terminations': [TERMINATE_OR_TEN], 'workbenches': []}}
