import asyncio
import hashlib
import json
import os
from pathlib import Path

from backend.app.core.tracing import EDITOR_ROOT, JsonlTraceRecorder, Span, continue_or_start
from backend.app.schemas.specialist_review import specialist_items
from .projects import BindingConflict
from .run_results import parse_run_results, request_pnu

# `latest` fetches at most this many runs whole to find the one for a parcel.
LATEST_CANDIDATES = 10


# Parsed results by the run's state: (run id, status, each row's id/state/cut), in memory and on disk. Parsing a
# layout run means fetching and reading tens of MB of replies; on the event loop it held every other request of the
# editor (the map's tile and parcel requests waited 7-20 s behind it, 2026-10-17). It runs in a thread, once per run
# state, and the result (a few hundred KB) is kept on disk so a backend restart does not fetch the replies again.
_PARSED: dict[tuple, dict] = {}
_PARSED_MAX = 32


def _results_dir():
    explicit = os.environ.get('EDITOR_RUN_RESULTS_DIR')
    if explicit:
        return Path(explicit)
    data_dir = os.environ.get('EDITOR_PLATFORM_DATA_DIR')
    return Path(data_dir) / 'run-results' if data_dir else EDITOR_ROOT / 'runtime' / 'run-results'


def _run_state(run):
    rows = run.get('communications') if isinstance(run, dict) else None
    return (run.get('run_id'), run.get('status'), run.get('pending_input'),
            tuple((r.get('id'), r.get('state'), r.get('truncated')) for r in rows if isinstance(r, dict)) if isinstance(rows, list) else None)


def _disk_path(key):
    return _results_dir() / (hashlib.sha256(repr(key).encode('utf-8')).hexdigest() + '.json')


def _read_disk(key):
    try:
        return json.loads(_disk_path(key).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write_disk(key, results):
    try:
        path = _disk_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix('.part')
        part.write_text(json.dumps(results, ensure_ascii=False), encoding='utf-8')
        part.replace(path)
    except (OSError, TypeError, ValueError):
        pass   # a cache: the results are recomputed next time


def _remember(key, results):
    while len(_PARSED) >= _PARSED_MAX:
        _PARSED.pop(next(iter(_PARSED)))
    _PARSED[key] = results


async def _parsed(run, whole=None):
    """The run's parsed results. `whole` (async run -> run) completes cut rows; it runs only when nothing is kept."""
    key = _run_state(run) if isinstance(run, dict) and isinstance(run.get('run_id'), str) else None
    if key is not None:
        if key in _PARSED:
            return _PARSED[key]
        kept = await asyncio.to_thread(_read_disk, key)
        if kept is not None:
            _remember(key, kept)
            return kept
    results = await asyncio.to_thread(parse_run_results, await whole(run) if whole else run)
    if key is not None:
        _remember(key, results)
        await asyncio.to_thread(_write_disk, key, results)
    return results


# Whole replies read for a run, by (run id, row id): a layout runs to tens of MB and the 3D view polls every 20 s.
_WHOLE_TEXT: dict[tuple, str] = {}
_WHOLE_MAX = 6


async def _whole_text(fetch):
    """The non-empty `response_text` of what `fetch` returns, else None; a fetch that fails reads as nothing."""
    try:
        whole = await fetch()
    except Exception:
        return None
    text = whole.get('response_text') if isinstance(whole, dict) else None
    return text if isinstance(text, str) and text.strip() else None


class RunService:
    def __init__(self, projects, owner, recorder=None, ledger=None):
        self.projects, self.owner = projects, owner
        self.recorder = recorder or JsonlTraceRecorder()
        # The 협업 장부: a run started from a conversation is linked to it, so its agents' calls belong to that conversation.
        self.ledger = ledger

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
                await self.projects.create(actor, binding.creation())
            run = await self.owner.submit_run({'project':binding.owner_project_id,'branch':binding.branch_id,
                'request_id':request_id, 'request':body.request,'source_versions':body.source_versions}, trace=span.context)
        except Exception as exc:
            span.end('error', error_type=type(exc).__name__)
            raise
        span.end('ok', run_id=run['run_id'])
        if self.ledger is not None and body.conversation_id:
            self.ledger.link_run(conversation_id=body.conversation_id, run_id=run['run_id'], project=binding.owner_project_id, branch=binding.branch_id,
                                 text=json.dumps(body.request, ensure_ascii=False))
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

    async def resume(self, actor, project_id, run_id, answer):
        """Answers what a run of this project waits for (`pending_request`); the owner checks the answer."""
        binding = self.binding(actor, project_id)
        await self.get(actor, project_id, run_id)
        return await self.owner.resume_run(run_id, binding.owner_project_id, binding.branch_id, answer)

    async def results(self, actor, project_id, run_id):
        """The run as `get` returns it, read into the UI shape of run_results.parse."""
        return await _parsed(await self.get(actor, project_id, run_id), self.whole_rows)

    async def whole_rows(self, run, *, task=None, call=None):
        """A communication row the Orchestrator cut at 8000 characters is replaced by the whole reply for the tools the UI
        must read whole (run_results.parse.WHOLE_TOOLS: the layout the 3D view draws, Site's facts): the agent's own A2A
        task first, else the reply the Orchestrator recorded (an agent restart empties its task memory). A reply read
        whole is kept for the next poll; nothing here raises."""
        from backend.app.adapters import a2a_tasks
        from backend.app.modules.platform.run_results.parse import WHOLE_TOOLS
        fetch = task or a2a_tasks.get_task
        fetch_call = call or self._whole_call
        rows = run.get('communications') if isinstance(run, dict) else None
        if not isinstance(rows, list):
            return run
        # A copy: the whole text feeds the parser only; what goes back over the wire stays the cut row (143 MB otherwise).
        rows = [dict(row) if isinstance(row, dict) else row for row in rows]
        run = {**run, 'communications': rows}
        for row in rows:
            if not isinstance(row, dict) or row.get('truncated') is not True or row.get('tool') not in WHOLE_TOOLS:
                continue
            key = (run.get('run_id'), row.get('id')) if isinstance(run.get('run_id'), str) and isinstance(row.get('id'), str) else None
            text = _WHOLE_TEXT.get(key) if key else None
            if text is None:
                # `a2a_task_id` is the agent's own id (what GetTask takes); `task_id` is the Orchestrator's node key.
                task_id = row.get('a2a_task_id') or row.get('task_id')
                text = await _whole_text(lambda: fetch(WHOLE_TOOLS[row['tool']], str(task_id))) if task_id else None
                if text is None:
                    text = await _whole_text(lambda: fetch_call(run, row))
                if text is not None and key:
                    while len(_WHOLE_TEXT) >= _WHOLE_MAX:
                        _WHOLE_TEXT.pop(next(iter(_WHOLE_TEXT)))
                    _WHOLE_TEXT[key] = text
            if text is not None:
                row['response_text'], row['truncated'] = text, False
        return run

    async def _whole_call(self, run, row):
        """The Orchestrator's recorded reply as the text the readers parse (its payload is the owner's answer)."""
        value = await self.owner.whole_call(run['run_id'], str(row['id']), run['owner_project_id'], run['branch_id'])
        return {'response_text': await asyncio.to_thread(json.dumps, value['payload'], ensure_ascii=False)} if value.get('payload') else None

    async def latest(self, actor, project_id, goal, pnu=None, cap=LATEST_CANDIDATES):
        """The newest run of `goal` (the owner lists newest first), for `pnu` when given: the list carries no
        request, so at most `cap` candidates are fetched whole and matched on the parcel they were asked about.
        Answer = that run (as `get`) plus `results`."""
        binding = self.binding(actor, project_id)
        candidates = [run for run in await self.list(actor, project_id) if run['goal'] == goal][:cap]
        if pnu is None:
            if not candidates:
                raise LookupError('no run for goal')
            run = await self.owner.get_run(candidates[0]['run_id'], binding.owner_project_id, binding.branch_id)
            return {**run, 'results': await _parsed(run, self.whole_rows)}
        for candidate in candidates:
            run = await self.owner.get_run(candidate['run_id'], binding.owner_project_id, binding.branch_id)
            if request_pnu(run) == pnu:
                return {**run, 'results': await _parsed(run, self.whole_rows)}
        raise LookupError('no run for parcel')

    async def review_request(self, actor, project_id, run_id):
        binding = self.binding(actor, project_id)
        value = await self.owner.review_request(run_id, binding.owner_project_id, binding.branch_id)
        if not value.get('request_id', '').startswith(f'editor:{project_id}:'):
            raise LookupError('run not found in project')
        return value
