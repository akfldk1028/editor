"""협업 장부 → one readable folder per conversation, written when a question is answered."""
import json

from backend.app.modules.ledger import Ledger
from backend.app.modules.ledger.transcript import outcome, render


def wait_for(found, tries=100):
    import time
    for _ in range(tries):
        if found():
            return
        time.sleep(0.05)


def test_an_answered_question_writes_the_conversations_folder_with_every_call_and_the_unsettled_ones_first(tmp_path):
    ledger = Ledger(tmp_path)
    turn = ledger.begin(from_agent='user', to_agent='orchestrator', tool='conversation', conversation_id='conv-1',
                        input_text='684-1 건폐율 알려줘', project='p', branch='main')
    hop = ledger.begin(from_agent='orchestrator', to_agent='law', tool='law_review_district_plan', conversation_id='conv-1',
                       input_text=json.dumps({'site_evidence': {'search_radius_m': 0.0}}))
    ledger.finish(hop, output_text=json.dumps({'status': 'needs_evidence', 'code': 'district_source_invalid',
                                               'missing_evidence': ['district_source_hash_mismatch']}))
    ok = ledger.begin(from_agent='orchestrator', to_agent='law', tool='law_ordinance', conversation_id='conv-1', input_text='{}')
    ledger.finish(ok, output_text=json.dumps({'ordinance': {'name': '조례'}}))
    assert not (tmp_path / 'conversations').exists()  # nothing until the question is answered
    ledger.finish(turn, output_text='건폐율은 60%입니다.')
    wait_for(lambda: list((tmp_path / 'conversations').glob('*/*/transcript.md')))  # written in the background

    folders = list((tmp_path / 'conversations').glob('*/*'))
    assert len(folders) == 1 and '684-1' in folders[0].name and folders[0].name.endswith('conv-1')
    text = (folders[0] / 'transcript.md').read_text(encoding='utf-8')
    assert text.startswith('# 684-1 건폐율 알려줘') and '에이전트 호출 2번 · 살펴볼 호출 1번' in text
    flagged = text.split('## 살펴볼 호출')[1].split('## 질문 1')[0]
    assert 'law_review_district_plan' in flagged and 'district_source_hash_mismatch' in flagged and 'law_ordinance' not in flagged
    assert '"search_radius_m": 0.0' in text and '### 최종 답\n\n건폐율은 60%입니다.' in text
    calls = [json.loads(line) for line in (folders[0] / 'calls.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [row['tool'] for row in calls] == ['conversation', 'law_review_district_plan', 'law_ordinance']


def test_a_call_is_flagged_by_what_its_own_reply_says_and_long_texts_point_to_the_full_record():
    base = {'ts_start': '2026-10-13T10:00:00Z', 'ts_end': '2026-10-13T10:00:01Z', 'status': 'OK', 'state': 'completed'}
    reply = lambda text: [{'role': 'assistant', 'parts': [{'type': 'text', 'content': text}]}]
    assert outcome({**base, 'output_messages': reply('{"status": "available"}')}) == ('완료', False)
    assert outcome({**base, 'output_messages': reply('{"error": "boom"}')})[1]
    assert outcome({**base, 'ts_end': None}) == ('끝나지 않음', True)
    assert outcome({**base, 'status': 'ERROR', 'error_type': 'Timeout'}) == ('실패 (Timeout)', True)
    rows = [{**base, 'id': 1, 'operation': 'invoke_agent', 'from_agent': 'user', 'to_agent': 'orchestrator', 'tool': 'ask'},
            {**base, 'id': 2, 'operation': 'invoke_agent', 'from_agent': 'orchestrator', 'to_agent': 'site', 'tool': 'site_x',
             'ts_start': '2026-10-13T10:00:00.5Z', 'output_messages': reply('x' * 9000)}]
    text = render('c', rows, 'user')
    assert '5,000자 더, calls.jsonl에 전체' in text


def test_conversations_sharing_an_id_in_different_projects_get_their_own_folders(tmp_path):
    ledger = Ledger(tmp_path)
    for project, question in (('p1', '첫 프로젝트 질문'), ('p2', '둘째 프로젝트 질문')):
        turn = ledger.begin(from_agent='user', to_agent='orchestrator', tool='conversation', conversation_id='main',
                            input_text=question, project=project, branch='main')
        ledger.finish(turn, output_text='답')
    wait_for(lambda: len(list((tmp_path / 'conversations').glob('*/*/transcript.md'))) == 2)
    texts = [path.read_text(encoding='utf-8') for path in (tmp_path / 'conversations').glob('*/*/transcript.md')]
    assert len(texts) == 2 and all(text.count('## 질문 1') == 1 and '## 질문 2' not in text for text in texts)
