"""Bind the Law Agent's ordinance provenance to its review references by instrument name."""
import re


def bind_ordinance_sources(review, caps):
    if not isinstance(review, dict):
        return
    sources = ((caps or {}).get('ordinance') or {}).get('sources') or []
    refs = [ref for item in review.get('items') or [] for ref in item.get('refs') or [] if ref.get('kind') == 'ordinance']
    names = {re.sub(r'\s+', '', name): name for name in [
        *(ref.get('instrument') for ref in refs), *(source.get('name') for source in sources)
    ] if isinstance(name, str) and name.strip()}
    for ref in refs:
        name = re.sub(r'\s+', '', ref.get('instrument') or '')
        # Calculators may say only "건축조례". Resolve that shorthand from this
        # review's named ordinance, without borrowing another article or municipality.
        if name == '건축조례':
            matches = [full for key, full in names.items() if key != name and key.endswith(name)]
            if len(matches) == 1:
                ref['instrument'] = matches[0]
    for item in review.get('items') or []:
        for ref in item.get('refs') or []:
            if ref.get('kind') != 'ordinance':
                continue
            name = re.sub(r'\s+', '', ref.get('instrument') or '')
            matches = [s for s in sources if name and re.sub(r'\s+', '', s.get('name') or '') == name]
            if len(matches) != 1:
                continue
            for key in ('edition_id', 'effective_date', 'url'):
                if matches[0].get(key):
                    ref[key] = matches[0][key]
