import hashlib
import json
from pathlib import Path

import pytest

from backend.app.modules.land.analysis import analyze_zones

FIXTURE = json.loads((Path(__file__).with_name('fixtures') / 'land_analysis_parity.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case: case['name'])
def test_complete_raw_response_equals_preserved_source(case):
    result = analyze_zones({'input_type': 'raw', 'input': '', 'zones': case['zones'],
                            'assessment_date': FIXTURE['assessment_date']})
    result.pop('storage')
    # Legacy sets introduce arbitrary article ordering, not different evidence.
    article = result['regulations']['landscaping']['article']
    result['regulations']['landscaping']['article'] = '; '.join(sorted(article.split('; ')))
    digest = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':')).encode()).hexdigest()
    assert digest == case['response_sha256']
