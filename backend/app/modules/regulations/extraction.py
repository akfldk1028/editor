import asyncio
import json
import math

from backend.app.modules.regulations.extraction_prompts import EXTRACTION_CONFIG, SYSTEM_PROMPT


_NUMBERS = {'adjacent_setback_m', 'bcr_pct', 'far_pct', 'height_limit_m',
            'building_designation_setback_m', 'setback_m'}
_RULE_LISTS = {'sunlight_rules', 'height_dependent_rules'}
_TEXT_LISTS = {'applies_to_zones', 'exceptions'}


def _valid(value, key=''):
    if key in _NUMBERS:
        return value is None or (type(value) in (int, float) and math.isfinite(value) and value >= 0)
    if key == 'sunlight_applies':
        return type(value) is bool
    if key in _RULE_LISTS:
        return isinstance(value, list) and all(isinstance(item, dict) and _valid(item) for item in value)
    if key in _TEXT_LISTS:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if isinstance(value, dict):
        return all(_valid(item, name) for name, item in value.items())
    if isinstance(value, list):
        return all(_valid(item) for item in value)
    if type(value) in (int, float):
        return math.isfinite(value) and value >= 0
    return value is None or isinstance(value, (str, bool))


class RegulationExtractionClient:
    def __init__(self, search_client, *, enabled=False, api_key='', model='gpt-4o-mini',
                 completion=None, timeout=15):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('extraction timeout must be finite and positive')
        self.search_client = search_client
        self.enabled = enabled
        self.api_key = api_key
        self.model = model
        self.completion = completion
        self.timeout = timeout

    async def _complete(self, messages):
        options = {'model': self.model, 'messages': messages, 'temperature': 0,
                   'response_format': {'type': 'json_object'}}
        if self.completion is not None:
            return await self.completion(**options)
        from openai import AsyncOpenAI
        async with AsyncOpenAI(api_key=self.api_key, timeout=self.timeout, max_retries=0) as client:
            response = await client.chat.completions.create(**options)
            return response.choices[0].message.content

    async def extract(self, zone_names: list[str], kind: str) -> dict | None:
        if not self.enabled or not self.api_key:
            return None
        config = EXTRACTION_CONFIG.get(kind)
        if config is None:
            return None
        try:
            zone = zone_names[0] if zone_names else ''
            queries = [query.format(zone_name=zone) for query in config['queries']]
            response = await self.search_client.search_queries(queries, limit=3, filter_results=False)
            texts, seen = [], set()
            for group in response['articles']:
                for article in group['results']:
                    content = article.get('content', '')
                    identity = article.get('hang_id') or article.get('id') or content[:80]
                    if not content or identity in seen:
                        continue
                    seen.add(identity)
                    name = article.get('law_name', '')
                    header = f"[{name} {article.get('jo_name', '')}]" if name else ''
                    texts.append(f'{header}\n{content}' if header else content)
            if not texts:
                return None
            prompt = config['prompt'].format(article_text='\n\n---\n\n'.join(texts[:5]), zone_name=zone)
            content = await asyncio.wait_for(self._complete([
                {'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': prompt},
            ]), timeout=self.timeout)
            if not isinstance(content, str) or not content:
                return None
            result = json.loads(content)
            if not isinstance(result, dict) or not result or not _valid(result):
                return None
            return result
        except Exception:
            return None
