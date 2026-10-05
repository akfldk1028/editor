import httpx
from urllib.parse import urlencode, quote
from pydantic import TypeAdapter, ValidationError

from backend.app.schemas.platform import AgentSummary
from backend.app.schemas.communications import RunCommunications


class OwnerUnavailable(Exception):
    pass


class OwnerContractError(Exception):
    pass


class OwnerRejected(Exception):
    pass


class OrchestratorClient:
    def __init__(self, base_url: str | None, *, transport=None):
        self.base_url = base_url
        self.transport = transport

    async def list_agents(self) -> list[AgentSummary]:
        response = await self.get('/editor/v1/agents')
        try:
            return TypeAdapter(list[AgentSummary]).validate_json(response.content)
        except (ValidationError, ValueError) as exc:
            raise OwnerContractError() from exc

    async def list_projects(self):
        response = await self.get('/editor/v1/projects')
        try:
            values = response.json()
            if not isinstance(values, list) or not all(isinstance(value, dict) and
                isinstance(value.get('owner_project_id'), str) and isinstance(value.get('branch_id'), str)
                for value in values):
                raise ValueError('invalid owner projects')
            return values
        except ValueError as exc:
            raise OwnerContractError() from exc

    async def context(self, project, branch):
        response = await self.get('/editor/v1/context?' + urlencode({'project':project,'branch':branch}))
        value = self.json(response)
        if not isinstance(value, dict) or not all(isinstance(k,str) and type(v) is int and v >= 0 for k,v in value.items()):
            raise OwnerContractError()
        return value

    async def submit_run(self, body):
        if not self.base_url:
            raise OwnerUnavailable()
        try:
            async with httpx.AsyncClient(timeout=8, transport=self.transport, follow_redirects=False) as client:
                response = await client.post(self.base_url.rstrip('/') + '/editor/v1/runs',
                    json=body, headers={'X-Editor-Client':'local'})
                if response.status_code == 409:
                    raise OwnerRejected()
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OwnerUnavailable() from exc
        value = self.bound_run(self.json(response), body['project'], body['branch'])
        if value['request_id'] != body['request_id']:
            raise OwnerContractError()
        return value

    @staticmethod
    def json(response):
        try:
            return response.json()
        except ValueError as exc:
            raise OwnerContractError() from exc

    @classmethod
    def bound_run(cls, value, project, branch):
        run = cls.parse_run(value)
        if run['owner_project_id'] != project or run['branch_id'] != branch:
            raise OwnerContractError()
        return run

    @staticmethod
    def parse_run(value):
        fields = ('run_id','owner_project_id','branch_id','request_id','goal','status')
        if not isinstance(value,dict) or not all(isinstance(value.get(key),str) for key in fields):
            raise OwnerContractError()
        if not isinstance(value.get('receipt_task_ids'),list) or not all(isinstance(v,str) for v in value['receipt_task_ids']) or type(value.get('pending_input')) is not bool:
            raise OwnerContractError()
        keys=('communications','communications_available','communications_truncated')
        try:
            communication=RunCommunications.model_validate({key:value[key] for key in keys} if any(key in value for key in keys)
                else dict(communications=[],communications_available=False,communications_truncated=False))
            if not communication.communications_available and (communication.communications or communication.communications_truncated):
                raise ValueError('unavailable communications contain records')
            if len({item.id for item in communication.communications})!=len(communication.communications):
                raise ValueError('duplicate communication identity')
        except (ValidationError, ValueError, KeyError) as exc:
            raise OwnerContractError() from exc
        return {**{key:value[key] for key in (*fields,'receipt_task_ids','pending_input')},**communication.model_dump()}

    async def list_runs(self, project, branch, prefix):
        response = await self.get('/editor/v1/runs?' + urlencode({'project':project,'branch':branch,'prefix':prefix}))
        values = self.json(response)
        if not isinstance(values,list):
            raise OwnerContractError()
        runs = [self.bound_run(value,project,branch) for value in values]
        if any(not run['request_id'].startswith(prefix) for run in runs):
            raise OwnerContractError()
        return runs

    async def get_run(self, run_id, project, branch):
        response = await self.get('/editor/v1/runs/' + quote(run_id,safe='') + '?' + urlencode({'project':project,'branch':branch}), missing=True)
        run = self.bound_run(self.json(response),project,branch)
        if run['run_id'] != run_id:
            raise OwnerContractError()
        return run

    async def review_request(self, run_id, project, branch):
        from backend.app.schemas.specialist_review import validate_specialist_review
        response = await self.get('/editor/v1/runs/' + quote(run_id, safe='') + '/request?' + urlencode({'project': project, 'branch': branch}), missing=True)
        value = self.json(response)
        try:
            if (not isinstance(value, dict) or value.get('run_id') != run_id or value.get('owner_project_id') != project
                    or value.get('branch_id') != branch or not isinstance(value.get('request_id'), str)
                    or not isinstance(value.get('source_versions'), dict) or not isinstance(value.get('reviews'), list)):
                raise ValueError('invalid follow-up binding')
            if not all(isinstance(key, str) and type(revision) is int and revision >= 0 for key, revision in value['source_versions'].items()):
                raise ValueError('invalid versions')
            validate_specialist_review(value['request'])
            if any(value['source_versions'].get(key) != revision for item in value['request']['specialist_reviews']
                   for key, revision in item['source_versions'].items()):
                raise ValueError('follow-up sources differ from original submission')
            for review in value['reviews']:
                if (not isinstance(review, dict) or not isinstance(review.get('needs'), list)
                        or len(review['needs']) > 300 or not all(isinstance(item, str) and len(item) <= 2000 for item in review['needs'])
                        or not all(isinstance(review.get(key), str) for key in ('tool', 'state', 'task_id'))
                        or not (review.get('agent') is None or isinstance(review['agent'], str))
                        or type(review.get('needs_truncated')) is not bool):
                    raise ValueError('invalid owner needs')
            return value
        except (ValueError, KeyError, TypeError) as exc:
            raise OwnerContractError() from exc

    async def get(self, path, *, missing=False):
        if not self.base_url:
            raise OwnerUnavailable()
        try:
            async with httpx.AsyncClient(timeout=8, transport=self.transport, follow_redirects=False) as client:
                response = await client.get(self.base_url.rstrip('/') + path)
                if missing and response.status_code == 404:
                    raise LookupError('run not found')
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OwnerUnavailable() from exc
        return response
