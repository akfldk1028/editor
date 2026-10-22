import asyncio
import httpx
from urllib.parse import urlencode, quote
from pydantic import TypeAdapter, ValidationError

from backend.app.core.agent_network import network_headers
from backend.app.core.tracing import SpanContext
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

    @staticmethod
    def trace_headers(trace: SpanContext | None) -> dict:
        """Every call carries W3C `traceparent`: the caller's span, or a short-lived trace of its own."""
        return {'traceparent': (trace or SpanContext.new()).header()}

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

    async def submit_run(self, body, trace=None):
        """POST the run under `trace` (the editor's `invoke_agent orchestrator` span, see RunService)."""
        if not self.base_url:
            raise OwnerUnavailable()
        try:
            async with httpx.AsyncClient(timeout=8, transport=self.transport, follow_redirects=False,
                                         headers=network_headers()) as client:
                response = await client.post(self.base_url.rstrip('/') + '/editor/v1/runs',
                    json=body, headers={'X-Editor-Client':'local', **self.trace_headers(trace)})
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
        # What a waiting run asks (its fields, a note, and a question that carries its own choices) reaches the
        # editor as the owner wrote it; anything of the wrong shape is dropped, never guessed.
        pending = {'pending_fields': [f for f in value.get('pending_fields') or [] if isinstance(f, str)],
                   'pending_note': value['pending_note'] if isinstance(value.get('pending_note'), str) else None,
                   'pending_request': value['pending_request'] if isinstance(value.get('pending_request'), dict) else None}
        # The parcel the run was asked about, when the door names it (a continuation of a chosen layout has no
        # site call of its own to read it from).
        pnu = {'pnu': value['pnu']} if isinstance(value.get('pnu'), str) and value['pnu'] else {}
        return {**{key:value[key] for key in (*fields,'receipt_task_ids','pending_input')},**pending,**pnu,**communication.model_dump()}

    async def resume_run(self, run_id, project, branch, answer):
        """The person's answer to what a waiting run asked; the owner checks it against the question."""
        if not self.base_url:
            raise OwnerUnavailable()
        try:
            async with httpx.AsyncClient(timeout=8, transport=self.transport, follow_redirects=False,
                                         headers=network_headers()) as client:
                response = await client.post(self.base_url.rstrip('/') + '/editor/v1/runs/' + quote(run_id, safe='') + '/resume',
                    json={'project': project, 'branch': branch, 'input': answer}, headers={'X-Editor-Client': 'local'})
                if response.status_code == 409:
                    # The owner says why: `message` for the person (written where its rule lives), `reason` for the log.
                    try:
                        refusal = response.json()
                    except ValueError:
                        refusal = {}
                    message = refusal.get('message') if isinstance(refusal, dict) else None
                    reason = refusal.get('reason') if isinstance(refusal, dict) else None
                    raise OwnerRejected(message if isinstance(message, str) and message else '',
                                        reason if isinstance(reason, str) else '')
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OwnerUnavailable() from exc
        run = self.bound_run(self.json(response), project, branch)
        if run['run_id'] != run_id:
            raise OwnerContractError()
        return run

    async def list_runs(self, project, branch, prefix, trace=None):
        response = await self.get('/editor/v1/runs?' + urlencode({'project':project,'branch':branch,'prefix':prefix}), trace=trace)
        values = self.json(response)
        if not isinstance(values,list):
            raise OwnerContractError()
        runs = [self.bound_run(value,project,branch) for value in values]
        if any(not run['request_id'].startswith(prefix) for run in runs):
            raise OwnerContractError()
        return runs

    async def get_run(self, run_id, project, branch):
        # The first read of a run after the Orchestrator restarts cuts its replies into previews (30 s for a layout
        # run of 2026-10-16); later reads are instant. Eight seconds made that first read an outage.
        response = await self.get('/editor/v1/runs/' + quote(run_id,safe='') + '?' + urlencode({'project':project,'branch':branch}), missing=True, timeout=60)
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

    async def alternatives(self, run_id, project, branch):
        """The run's selection set: MasterPlan's candidates (each with its drawing and reduced layout) and the pick so far."""
        response = await self.get('/editor/v1/runs/' + quote(run_id, safe='') + '/alternatives?' + urlencode({'project': project, 'branch': branch}),
                                  missing=True, timeout=60)
        value = await asyncio.to_thread(self.json, response)
        # A continuation of a pick answers with its parent's set and the parent's run id (the run a pick is posted
        # to); demanding the asked id refused every set once a candidate was chosen (502, one layout on the map).
        if (not isinstance(value, dict) or not isinstance(value.get('run_id'), str) or not isinstance(value.get('candidates'), list)
                or type(value.get('index_revision')) is not int or type(value.get('selection_revision')) is not int
                or not all(isinstance(c, dict) and isinstance(c.get('candidate_id'), str) for c in value['candidates'])):
            raise OwnerContractError()
        return value

    async def select_alternative(self, run_id, project, branch, candidate_id):
        """The person's pick of a candidate; the owner records the choice and queues its continuation run."""
        if not self.base_url:
            raise OwnerUnavailable()
        try:
            async with httpx.AsyncClient(timeout=30, transport=self.transport, follow_redirects=False,
                                         headers=network_headers()) as client:
                response = await client.post(self.base_url.rstrip('/') + '/editor/v1/runs/' + quote(run_id, safe='') + '/select',
                    json={'project': project, 'branch': branch, 'candidate_id': candidate_id}, headers={'X-Editor-Client': 'local'})
                if response.status_code == 404:
                    raise LookupError('run not found')
                if response.status_code in (400, 409, 422):
                    try:
                        refusal = response.json()
                    except ValueError:
                        refusal = {}
                    raise OwnerRejected(refusal.get('message') or refusal.get('reason') or refusal.get('error') or '')
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OwnerUnavailable() from exc
        value = self.json(response)
        if not isinstance(value, dict) or value.get('candidate_id') != candidate_id or not isinstance(value.get('continuation_request_id'), str):
            raise OwnerContractError()
        return value

    async def layout(self, run_id, project, branch):
        """The branch's current layout (the chosen candidate), reduced to the drawn layers."""
        response = await self.get('/editor/v1/runs/' + quote(run_id, safe='') + '/layout?' + urlencode({'project': project, 'branch': branch}),
                                  missing=True, timeout=60)
        value = await asyncio.to_thread(self.json, response)
        if not isinstance(value, dict) or value.get('run_id') != run_id or not isinstance(value.get('layout'), dict):
            raise OwnerContractError()
        return value

    async def whole_call(self, run_id, row_id, project, branch):
        """A recorded owner reply whole (its parsed payload) from the Orchestrator, for readers that need more than the
        8000-character row once the agent no longer holds its task. A layout runs to tens of MB: a longer wait."""
        response = await self.get('/editor/v1/runs/' + quote(run_id, safe='') + '/calls/' + quote(str(row_id), safe='')
                                  + '?' + urlencode({'project': project, 'branch': branch}), missing=True, timeout=240)
        value = await asyncio.to_thread(self.json, response)   # tens of MB: off the event loop
        if not isinstance(value, dict) or value.get('run_id') != run_id or not isinstance(value.get('payload'), dict):
            raise OwnerContractError()
        return value

    async def get(self, path, *, missing=False, trace=None, timeout=8):
        """Reads carry `traceparent` too; outside a submission that is a short-lived trace, not recorded."""
        if not self.base_url:
            raise OwnerUnavailable()
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self.transport, follow_redirects=False,
                                         headers=network_headers()) as client:
                response = await client.get(self.base_url.rstrip('/') + path, headers=self.trace_headers(trace))
                if missing and response.status_code == 404:
                    raise LookupError('run not found')
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OwnerUnavailable() from exc
        return response
