from backend.app.core.tracing import JsonlTraceRecorder, Span, continue_or_start
from backend.app.schemas.platform import ProjectCreate
from backend.app.schemas.specialist_review import specialist_items
from .projects import BindingConflict


class RunService:
    def __init__(self, projects, owner, recorder=None):
        self.projects, self.owner = projects, owner
        self.recorder = recorder or JsonlTraceRecorder()

    def binding(self, actor, project_id):
        binding = self.projects.repository.get(actor, project_id)
        if binding is None:
            raise LookupError('project not found')
        return binding

    async def context(self, actor, project_id):
        binding = self.binding(actor, project_id)
        return {'scene_revision':binding.scene_revision,
            'source_versions':await self.owner.context(binding.owner_project_id, binding.branch_id)}

    async def submit(self, actor, project_id, key, body, traceparent=None):
        """One W3C trace per submission: the caller's `traceparent` when it sent one, else a new one.
        Everything said to the Orchestrator for it (retry probe, binding, POST) is one recorded span,
        `invoke_agent orchestrator`; the answer is the owner's run plus `trace_id` for the card."""
        binding = self.binding(actor, project_id)
        if body.scene_revision != binding.scene_revision:
            raise BindingConflict('scene revision changed')
        for item in specialist_items(body.request):
            for request in (item['args'], item['args'].get('request', {})):
                if isinstance(request, dict) and any(key in request and request[key] != value for key, value in (
                    ('project_id', binding.owner_project_id), ('branch_id', binding.branch_id),
                )):
                    raise BindingConflict('Specialist project binding does not match')
        request_id = f'editor:{project_id}:{key}'
        span = Span.start(self.recorder, continue_or_start(traceparent), agent='orchestrator', conversation_id=request_id)
        try:
            previous = await self.owner.list_runs(binding.owner_project_id,binding.branch_id,request_id, trace=span.context)
            if not any(run['request_id'] == request_id for run in previous):
                await self.projects.create(actor, ProjectCreate(**binding.model_dump(exclude={'project_id'})))
            run = await self.owner.submit_run({'project':binding.owner_project_id,'branch':binding.branch_id,
                'request_id':request_id, 'request':body.request,'source_versions':body.source_versions}, trace=span.context)
        except Exception as exc:
            span.end('error', error_type=type(exc).__name__)
            raise
        span.end('ok', run_id=run['run_id'])
        return {**run, 'trace_id': span.context.trace_id}

    async def list(self, actor, project_id):
        binding = self.binding(actor, project_id)
        return await self.owner.list_runs(binding.owner_project_id,binding.branch_id,f'editor:{project_id}:')

    async def get(self, actor, project_id, run_id):
        binding = self.binding(actor, project_id)
        run = await self.owner.get_run(run_id,binding.owner_project_id,binding.branch_id)
        if not run.get('request_id','').startswith(f'editor:{project_id}:'):
            raise LookupError('run not found in project')
        return run

    async def review_request(self, actor, project_id, run_id):
        binding = self.binding(actor, project_id)
        value = await self.owner.review_request(run_id, binding.owner_project_id, binding.branch_id)
        if not value.get('request_id', '').startswith(f'editor:{project_id}:'):
            raise LookupError('run not found in project')
        return value
