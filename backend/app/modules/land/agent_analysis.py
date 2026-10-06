"""The /law "AI 심화 분석" stream: quick analysis, then a team run in-process.

The event contract is the one the frontend already consumes (ported from ARR's
land/views.py agent_analyze_stream): `status` discriminates analyzing, quick_done,
agent, complete and error events.
"""
import asyncio
import json
import sqlite3
import time

from backend.app.adapters.workspace_team import close_team, load_team


QUICK_PHASES = (('reverse', '필지 조회', 0.05), ('land_use', '토지이용 조회', 0.10),
                ('regulations', '규제 계산', 0.20))


def sse(event):
    return 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'


def task_prompt(result, pnu, address):
    pnu_info = result.get('pnu') if isinstance(result, dict) else None
    pnu_text = pnu_info.get('pnu', pnu) if isinstance(pnu_info, dict) else (pnu or address)
    return (f'다음 토지를 분석하세요.\n\nPNU: {pnu_text}\n주소: {address or "(미확인)"}\n\n'
            'land_analyst는 analyze_land 도구로 규제 데이터를 조회하고, '
            'legal_interpreter는 search_laws 도구로 관련 법조항을 검색하세요.')


def configured_team(team, environment):
    """The saved land team and environment, falling back to the shipped literal."""
    from backend.app.modules.workspace.catalog import CatalogRepository
    from backend.app.modules.workspace.seeds import LAND_TEAM, LAND_TEAM_LABEL
    from backend.app.modules.workspace.settings import SettingsRepository
    from backend.app.modules.workspace.storage import resolve_directory

    directory = resolve_directory()
    if directory is None:
        return team or LAND_TEAM, list(environment or [])
    try:
        saved = CatalogRepository(directory).find_team(LAND_TEAM_LABEL)
        saved_environment = SettingsRepository(directory).get()['config'].get('environment', [])
    except (OSError, sqlite3.Error):
        return team or LAND_TEAM, list(environment or [])
    return team or saved or LAND_TEAM, list(environment or saved_environment)


async def agent_analysis_events(*, pnu, address, zones, services, team, environment, timeout=300):
    for phase, name, progress in QUICK_PHASES:
        yield {'status': 'analyzing', 'phase': phase, 'phase_name': name, 'progress': progress}
    try:
        result = await services.analyze_land(pnu, address, zones)
    except Exception:
        yield {'status': 'error', 'message': '빠른 분석 중 오류가 발생했습니다.', 'fallback_to_quick': False}
        return
    yield {'status': 'analyzing', 'phase': 'law_search', 'phase_name': '법조항 검색', 'progress': 0.25}
    yield {'status': 'quick_done', 'regulations': result, 'progress': 0.30}
    yield {'status': 'analyzing', 'phase': 'agent_connect', 'phase_name': '에이전트 팀 연결', 'progress': 0.32}

    started = time.monotonic()
    deadline = started + timeout
    turn, tokens, report, loaded, stream, timer = 0, 0, '', None, None, None
    try:
        from autogen_agentchat.base import TaskResult
        from autogen_agentchat.messages import BaseChatMessage
        from autogen_core import CancellationToken

        loaded = load_team(team, None, environment)
        # The token reaches the model calls, so the deadline aborts an in-flight request
        # instead of waiting for the team to finish on its own; wait_for below only turns
        # the abort into the error event (asyncio.timeout around the yields would cancel
        # the SSE consumer rather than this generator).
        token = CancellationToken()
        timer = asyncio.get_running_loop().call_later(timeout, token.cancel)
        stream = loaded.run_stream(task=task_prompt(result, pnu, address), cancellation_token=token)
        while True:
            try:
                event = await asyncio.wait_for(anext(stream), max(0.0, deadline - time.monotonic()))
            except StopAsyncIteration:
                break
            if isinstance(event, TaskResult):
                break
            if not isinstance(event, BaseChatMessage) or event.source == 'user':
                continue
            content = event.to_text()
            if not isinstance(content, str) or not content.strip():
                continue
            usage = getattr(event, 'models_usage', None)
            if usage is not None:
                tokens += usage.prompt_tokens + usage.completion_tokens
            turn += 1
            report = content
            yield {'status': 'agent', 'agent': event.source, 'content': content,
                   'progress': round(min(0.35 + turn * 0.08, 0.92), 2), 'turn': turn}
    except Exception:
        # Provider errors can embed credentials; the message stays generic.
        yield {'status': 'error', 'message': '에이전트 실행 중 오류가 발생했습니다. 빠른 분석 결과만 표시합니다.',
               'fallback_to_quick': True}
        return
    finally:
        if timer is not None:
            timer.cancel()
        if stream is not None:
            try:
                await stream.aclose()
            except Exception:
                pass
        if loaded is not None:
            await close_team(loaded)
    yield {'status': 'complete', 'report': report,
           'run_summary': {'duration': round(time.monotonic() - started, 2), 'total_tokens': tokens,
                           'turn_count': turn}}
