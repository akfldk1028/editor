from backend.app.modules.platform.ask import normalize
from backend.app.modules.platform.ask import clause_route
from backend.app.modules.platform.law_sources import bind_ordinance_sources


def test_name_only_ordinance_resolves_dated_edition_through_agent():
    route = clause_route('원문 보기', {'title': '주차장', 'refs': [
        {'kind': 'ordinance', 'instrument': '갑시 주차장 조례', 'article': None}
    ]}, '2026-10-09')
    assert route.skill == 'law_ordinance'
    assert route.args == {'name': '갑시 주차장 조례', 'article': '', 'limit': 3, 'assessment_date': '2026-10-09'}


def test_selected_article_and_ordinance_are_not_excerpted():
    text = '원문 항호 내용\n' * 1000
    ordinance = {'matches': [{'article': '제42조', 'content': text}]}
    assert normalize('law_ordinance', ordinance, full_text=True)['matches'][0]['text'] == text
    article = {'articles': [{'jo_id': '건축법(법률)::제1조', 'hangs': [{'content': text}]}]}
    assert normalize('law_article', article, full_text=True)['items'][0]['text'] == text
    assert len(normalize('law_ordinance', ordinance)['matches'][0]['text']) == 400


def test_provenance_only_binds_to_the_matching_ordinance():
    refs = [{'kind': 'ordinance', 'instrument': '갑시 도시계획 조례'}, {'kind': 'ordinance', 'instrument': '을시 도시계획 조례'}]
    bind_ordinance_sources({'items': [{'refs': refs}]}, {'ordinance': {'sources': [{'name': '갑시 도시계획조례', 'edition_id': 'edition-a'}]}})
    assert refs[0]['edition_id'] == 'edition-a'
    assert 'edition_id' not in refs[1]


def test_generic_building_ordinance_uses_unique_name_from_same_review_without_borrowing_article():
    generic = {'kind': 'ordinance', 'instrument': '건축조례', 'article': None}
    named = {'kind': 'ordinance', 'instrument': '갑시 건축 조례', 'article': '제29조'}
    bind_ordinance_sources({'items': [{'refs': [generic, named]}]}, None)
    assert generic == {'kind': 'ordinance', 'instrument': '갑시 건축 조례', 'article': None}


def test_generic_building_ordinance_stays_unresolved_without_unique_jurisdiction():
    for names in ([], ['갑시 건축 조례', '을시 건축 조례']):
        generic = {'kind': 'ordinance', 'instrument': '건축조례', 'article': None}
        refs = [generic, *[{'kind': 'ordinance', 'instrument': name} for name in names]]
        bind_ordinance_sources({'items': [{'refs': refs}]}, None)
        assert generic['instrument'] == '건축조례'
