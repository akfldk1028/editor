"""Eligibility of local source snapshots, without certifying current completeness."""
from datetime import date, datetime
from urllib.parse import urlparse


def assessment_day(value=None):
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def source_eligibility(document, code, assessment_date=None):
    day = assessment_day(assessment_date)
    if not isinstance(document, dict):
        return False, 'missing_ordinance_snapshot'
    comment = str(document.get('__comment', '')).lower()
    if any(word in comment for word in ('예시', 'example', 'sample', '교체 필요')) or document.get('example'):
        return False, 'example_not_legal_evidence'
    if str(document.get('sigungu_code') or document.get('code') or '') != code:
        return False, 'jurisdiction_mismatch'
    source = document.get('ordinance') or {}
    if not isinstance(source, dict) or not source.get('id') or not source.get('name'):
        return False, 'missing_source_identity'
    url = source.get('url') or document.get('source_url') or ''
    host = urlparse(url).hostname or ''
    # Existing imports carry the official publisher in their generation record
    # and an ordinance edition ID; a free-form name alone is not provenance.
    if not (host == 'law.go.kr' or host.endswith('.law.go.kr') or 'law.go.kr' in comment):
        return False, 'missing_official_provenance'
    try:
        effective = datetime.strptime(str(source.get('effective', '')).replace('-', ''), '%Y%m%d').date()
        fetched = date.fromisoformat(str(document['fetched_at'])[:10])
        expiry = source.get('valid_until') or source.get('repealed_on')
        if expiry and day >= assessment_day(expiry):
            return False, 'edition_expired'
    except (KeyError, TypeError, ValueError):
        return False, 'missing_or_invalid_source_dates'
    if effective > day:
        return False, 'edition_not_yet_effective'
    if fetched < effective:
        return False, 'snapshot_predates_effective_edition'
    return True, 'eligible_snapshot'
