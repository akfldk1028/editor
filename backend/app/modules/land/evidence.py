import asyncio

from backend.app.modules.regulations.zoning_limits import lookup
from .analysis_response import flatten_law_articles


async def collect_evidence(names, *, include_law, law_client=None, extraction_client=None):
    async def search():
        if not include_law:
            return None
        if law_client is None:
            return {'articles': [], 'total_count': 0, 'errors': ['Law search is not configured']}
        return flatten_law_articles(await law_client.search_for_zones(names, include_extended=True))

    async def proposals():
        if extraction_client is None or not extraction_client.enabled:
            return None
        standard = [name for name in names if lookup(name) is not None]
        if not standard:
            return {'status': 'unavailable', 'proposals': {}}
        kinds = ['sunlight', 'adjacent_setback']
        if any('지구단위계획구역' in name for name in names):
            kinds.append('building_designation')
        values = await asyncio.gather(*(extraction_client.extract(standard, kind) for kind in kinds))
        accepted = {kind: value for kind, value in zip(kinds, values) if value}
        return {'status': 'unverified_proposal' if accepted else 'unavailable', 'proposals': accepted}

    tasks = [asyncio.create_task(search()), asyncio.create_task(proposals())]
    try:
        law, advisory = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return law, advisory
