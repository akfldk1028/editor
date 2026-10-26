import asyncio

import httpx
import pytest

from backend.app.modules.land.map_ground import sources


@pytest.mark.parametrize('padding,accepted', [(11_300_000, True), (16_100_000, False)])
def test_regional_cover_page_accepts_observed_size_but_remains_bounded(padding, accepted):
    def upstream(request):
        return httpx.Response(200, json={'features': [], 'numberMatched': 0, 'padding': 'x' * padding})

    async def run():
        task = sources.fetch('cover', (126.9, 37.5, 126.91, 37.51), '', transport=httpx.MockTransport(upstream))
        if accepted:
            assert (await task)['rows'] == []
        else:
            with pytest.raises(sources.SourceUnavailable, match='byte budget'):
                await task
    asyncio.run(run())
