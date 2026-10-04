import httpx
import math


class LandUnavailable(Exception):
    pass


class LandContractError(Exception):
    pass


class LandRejected(Exception):
    pass


class LandClient:
    def __init__(self, base_url, *, transport=None, analysis_timeout=180):
        self.base_url, self.transport = base_url, transport
        if not math.isfinite(analysis_timeout) or not 150 <= analysis_timeout <= 600:
            raise ValueError('analysis timeout must be between 150 and 600 seconds')
        self.analysis_timeout=analysis_timeout

    async def request(self, operation, body=None):
        if not self.base_url:
            raise LandUnavailable()
        try:
            timeout=self.analysis_timeout if operation=='analyze' else 8
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout,connect=5),transport=self.transport,follow_redirects=False) as client:
                response=await client.request('GET' if body is None else 'POST',
                    self.base_url.rstrip('/')+'/land/'+operation+'/',json=body)
                if response.status_code in (400,422):
                    raise LandRejected()
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LandUnavailable() from exc
        try:
            value=response.json()
        except ValueError as exc:
            raise LandContractError() from exc
        if not isinstance(value,dict):
            raise LandContractError()
        return value

    async def stats(self):
        value=await self.request('stats')
        if not all(type(value.get(k)) in (int,float) and value[k]>=0 for k in
            ('total_queries','avg_response_time_ms','error_count')) or not isinstance(value.get('by_input_type'),list):
            raise LandContractError()
        if not all(isinstance(row,dict) and isinstance(row.get('input_type'),str) and
            type(row.get('count')) is int and row['count']>=0 for row in value['by_input_type']):
            raise LandContractError()
        return {k:value[k] for k in ('total_queries','avg_response_time_ms','error_count','by_input_type')}

    async def analyze(self, body):
        value=await self.request('analyze',body)
        fields=('pnu','regulations','zone_info','land_info','law_articles')
        if any(k not in value or (value[k] is not None and not isinstance(value[k],dict)) for k in fields):
            raise LandContractError()
        if not isinstance(value.get('restrictions'),list) or not all(isinstance(v,str) for v in value['restrictions']):
            raise LandContractError()
        if 'warning' in value and not isinstance(value['warning'],str):
            raise LandContractError()
        if not isinstance(value.get('errors',[]),list) or not all(isinstance(v,str) for v in value.get('errors',[])):
            raise LandContractError()
        assessment=value.get('assessment')
        if assessment is not None and (not isinstance(assessment,dict) or
            not isinstance(assessment.get('status'),str) or type(assessment.get('permit_compliance_verified')) is not bool or
            not isinstance(assessment.get('missing_evidence'),list) or
            not all(isinstance(v,str) for v in assessment['missing_evidence'])):
            raise LandContractError()
        law=value['law_articles']
        if law is not None:
            if not isinstance(law.get('articles'),list) or not isinstance(law.get('errors',[]),list):
                raise LandContractError()
            articles=[]
            for item in law['articles']:
                if not isinstance(item,dict):
                    raise LandContractError()
                values=item.get('results',[item])
                if not isinstance(values,list) or not all(isinstance(a,dict) and
                    all(isinstance(a.get(k),str) for k in ('content','law_name','article')) for a in values):
                    raise LandContractError()
                articles.extend(values)
            if not all(isinstance(e,str) for e in law.get('errors',[])):
                raise LandContractError()
            value['law_articles']={'articles':articles,'total_count':len(articles),'errors':law.get('errors',[])}
        return {k:value[k] for k in (*fields,'restrictions','warning','errors','assessment') if k in value}
