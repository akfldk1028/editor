"""Inspect every building-use clause in the pinned official annex.

This is a lossless source index, not a legal classification or area-rule engine.
Raw whitespace is preserved; only query matching removes layout whitespace.
"""

from backend.app.modules.design.generation import paths as _design_paths
import hashlib
import json
from pathlib import Path
import re


SOURCE_PATH = _design_paths.package_root('law') / 'data/facility_sources/building_decree_annex_1.json'
_FAMILY = re.compile(r'^(?P<indent>[ \t]*)(?P<id>\d+(?:의\d+)?)\. +(?P<heading>[^\r\n]+)', re.MULTILINE)
_NOTES = re.compile(r'^[ \t]*비고[ \t]*\r?$', re.MULTILINE)
_CLAUSE_LABELS = '가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허'
_EXPECTED_IDS = [str(n) for n in range(1, 24)] + ['23의2'] + [str(n) for n in range(24, 30)]


def _search_text(text: str) -> str:
    return re.sub(r'\s+', '', text).casefold()


def parse_building_use_source(source: dict, query: str = '') -> dict:
    """Validate and index an official source document; reject incomplete coverage.

    Each family's ``text`` is an exact source slice, including its heading and
    introductory exclusions. Clauses include their labels and nested conditions.
    Query results retain the whole matching family to keep shared qualifiers in
    context; ``matched_clause_ids`` identifies literal text matches, not a verdict.
    """
    text = source['annex_text']
    actual_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if actual_hash != source['annex_text_sha256']:
        raise ValueError('Building-use source hash mismatch; catalog not available')
    notes = list(_NOTES.finditer(text))
    if len(notes) != 1:
        raise ValueError('Building-use coverage issue: expected one annex notes section')
    body_end = notes[0].start()
    headers = list(_FAMILY.finditer(text, 0, body_end))
    if [header['id'] for header in headers] != _EXPECTED_IDS:
        raise ValueError('Building-use coverage issue: expected all 30 families (1–29, including 23의2) in order')
    needle = _search_text(query)
    families = []
    total_clause_count = 0
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else body_end
        family_text = text[header.start():end]
        family_id = header['id']
        # In this official layout, 목 headings are indented one column deeper
        # than 호 headings. Wrapped prose uses the 호 indentation, even when a
        # split Korean sentence happens to begin with "다.".
        indent = re.escape(header['indent'] + ' ')
        clause_pattern = re.compile(r'^' + indent + r'(?P<label>[가-힣])\. +', re.MULTILINE)
        clause_headers = list(clause_pattern.finditer(family_text))
        labels = ''.join(clause['label'] for clause in clause_headers)
        if labels and labels != _CLAUSE_LABELS[:len(labels)]:
            raise ValueError(f'Building-use coverage issue: unexpected clause sequence in family {family_id}')
        clauses = []
        for clause_index, clause_header in enumerate(clause_headers):
            clause_end = clause_headers[clause_index + 1].start() if clause_index + 1 < len(clause_headers) else len(family_text)
            clauses.append({
                'clause_id': family_id + clause_header['label'],
                'text': family_text[clause_header.start():clause_end],
            })
        intro_text = family_text[:clause_headers[0].start()] if clause_headers else ''
        if not clauses:
            clauses = [{'clause_id': family_id, 'text': family_text}]
        name = re.split(r'[\[(:]', header['heading'], maxsplit=1)[0].strip()
        total_clause_count += len(clauses)
        matching_clauses = [clause['clause_id'] for clause in clauses
                            if not needle or needle in _search_text(clause['text'])]
        if not needle or needle in _search_text(family_text):
            families.append({
                'family_id': family_id,
                'name': name,
                'text': family_text,
                'intro_text': intro_text,
                'clauses': clauses,
                'matched_clause_ids': matching_clauses,
            })
    source_keys = (
        'source_id', 'law_title', 'law_id', 'source_url', 'selected_mst',
        'selected_effective_date', 'selected_promulgation_date', 'selection_as_of',
        'retrieved_at_utc', 'annex_number', 'annex_title', 'annex_revision_date',
        'annex_pdf_url', 'annex_text_sha256', 'source_edition_confirmed',
        'confirmation_basis',
    )
    return {
        'purpose': 'source_clause_inspection',
        'query': query,
        'family_count': len(headers),
        'clause_count': total_clause_count,
        'matched_family_count': len(families),
        'source': {key: source[key] for key in source_keys},
        'preamble_text': text[:headers[0].start()],
        'notes_text': text[body_end:],
        'families': families,
    }


def get_building_use_catalog(query: str = '') -> dict:
    """Load and verify the pinned official annex, optionally searching Korean text."""
    source = json.loads(SOURCE_PATH.read_text(encoding='utf-8'))
    return parse_building_use_source(source, query)
