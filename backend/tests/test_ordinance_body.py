"""`modules/law/ordinances/body`: a dated edition's whole text, accepted only as the edition asked for. Fixture records."""
import pytest

from backend.app.modules.law.ordinances import body

RECORD = {'LawService': {
    '자치법규기본정보': {'자치법규명': '을시 주차장 설치 및 관리 조례', '자치법규ID': '77', '자치법규일련번호': '4000', '시행일자': '20210101', '공포일자': '20201220', '공포번호': '12', '지자체기관명': '갑도 을시'},
    '조문': {'조': [{'조문번호': ['000000', '000000'], '조문여부': 'N', '조제목': '', '조내용': '제1장 총칙'},
                  {'조문번호': ['000100', '000100'], '조문여부': 'Y', '조제목': '목적', '조내용': '제1조(목적) 이 조례는\r\n 목적으로 한다.'},
                  {'조문번호': ['000302', '000302'], '조문여부': 'Y', '조제목': '가지', '조내용': '제3조의2(가지) 내용'},
                  {'조문번호': ['000400', '000400'], '조문여부': 'Y', '조제목': '빈', '조내용': ''}]},
    '별표': {'별표단위': [{'별표번호': '0001', '별표제목': '[별표 1] 주차요금표', '별표구분': '서식', '별표첨부파일구분': 'hwpx',
                        '별표첨부파일명': 'http://www.law.go.kr/flDownload.do?OC=secret&flSeq=1', '별표내용': ''}]},
    '부칙': {'부칙공포일자': '20201220', '부칙공포번호': '12', '부칙내용': ['부칙 <제12호,2020.12.20>', '이 조례는 2021년 1월 1일부터 시행한다.']},
}}


@pytest.fixture(autouse=True)
def fresh():
    body.clear_cache()
    yield
    body.clear_cache()


def test_the_verified_edition_keeps_every_article_annex_and_supplement():
    out = body.ordinance_body('을시 주차장 설치 및 관리 조례', '4000', '2026-10-09', fetch_service=lambda mst: RECORD)
    assert out['status'] == {'identity': 'body_verified', 'applicability': 'unknown'}
    assert out['ordinance'] == {'name': '을시 주차장 설치 및 관리 조례', 'ordinance_id': '77', 'edition_id': '4000', 'effective_date': '2021-01-01',
                                'promulgated': '2020-12-20', 'promulgation_no': '12', 'issuer': '갑도 을시', 'url': body.ORDINANCE_URL + '4000'}
    assert [(a['article'], a['heading'], a['content']) for a in out['articles']] == [
        ('', True, '제1장 총칙'), ('제1조', False, '제1조(목적) 이 조례는\n 목적으로 한다.'), ('제3조의2', False, '제3조의2(가지) 내용')]
    assert out['annexes'] == [{'number': '1', 'title': '[별표 1] 주차요금표', 'kind': '서식', 'file_kind': 'hwpx', 'file_url': 'http://www.law.go.kr/flDownload.do?flSeq=1', 'content': None}]
    assert out['supplement'] == {'promulgated': '2020-12-20', 'no': '12', 'content': '부칙 <제12호,2020.12.20>\n이 조례는 2021년 1월 1일부터 시행한다.'}
    assert 'secret' not in str(out)


def test_a_record_that_is_not_the_edition_asked_for_is_refused():
    wrong_name = body.ordinance_body('을시 주차장 조례', '4000', '2026-10-09', fetch_service=lambda mst: RECORD)
    assert wrong_name['error'] == 'identity_mismatch' and 'name' in wrong_name['reason']
    wrong_edition = body.ordinance_body('을시 주차장 설치 및 관리 조례', '4001', '2026-10-09', fetch_service=lambda mst: RECORD)
    assert 'edition' in wrong_edition['reason']
    too_early = body.ordinance_body('을시 주차장 설치 및 관리 조례', '4000', '2020-06-01', fetch_service=lambda mst: RECORD)
    assert 'date' in too_early['reason'] and too_early['record']['effective_date'] == '2021-01-01'
    assert body.ordinance_body('x', '1', '2026-10-09', fetch_service=lambda mst: {'nope': 1})['error'] == 'invalid_record'


def test_failures_are_reported_without_the_credential_and_records_are_cached():
    def fail(mst):
        raise OSError('lawService.do?OC=secret&MST=1 down')
    out = body.ordinance_body('x', '1', '2026-10-09', fetch_service=fail)
    assert out['error'] == 'external_failure' and 'secret' not in out['reason']
    calls = []

    def fetch(mst):
        calls.append(mst)
        return RECORD
    body.ordinance_body('을시 주차장 설치 및 관리 조례', '4000', '2026-10-09', fetch_service=fetch)
    body.ordinance_body('을시 주차장 설치 및 관리 조례', '4000', '2026-10-09', fetch_service=fetch)
    assert calls == ['4000']


def test_an_error_body_is_not_kept_for_the_cache_ttl():
    answers = [{'LawService': {'에러': '일일 요청 한도 초과'}}, RECORD]
    fetch = lambda mst: answers.pop(0)  # noqa: E731
    assert body.ordinance_body('을시 주차장 설치 및 관리 조례', '4000', '2026-10-09', fetch_service=fetch)['error'] == 'invalid_record'
    assert body.ordinance_body('을시 주차장 설치 및 관리 조례', '4000', '2026-10-09', fetch_service=fetch)['status']['identity'] == 'body_verified'
