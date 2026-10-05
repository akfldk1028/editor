import json
from copy import deepcopy

from .native_repository import NativeJobRepository, NativeJobUnavailable
from .execution_store import ExecutionStore, ExecutionConflict, digest
from .optimization.evaluator import validate_context
from .optimization.ssiea import resolve_options


class ExecutionService:
    def __init__(self,directory):
        self.jobs=NativeJobRepository(directory)
        self.store=ExecutionStore(directory)

    def enqueue(self,actor,project,job_id,request_id,seed,scene_revision,unverified_search):
        if unverified_search is not True or type(seed) is not int or not 0<=seed<2**64:
            raise ValueError('Explicit unverified search and unsigned 64-bit seed required')
        if not isinstance(request_id,str) or not 1<=len(request_id)<=128:
            raise ValueError('Bounded request identity required')
        job=self.jobs.get_job(actor,project,job_id)
        if job is None:raise LookupError('Native job not found')
        if job['scene_revision']!=scene_revision:raise ExecutionConflict('Stored job scene revision differs')
        validate_context(job['prepared'])
        job=deepcopy(job)
        job['prepared']['job_spec']['options']=resolve_options(job['prepared']['job_spec'].get('options',{}))
        return self.store.enqueue(actor,project,job,request_id,seed,scene_revision)

    def get(self,actor,project,attempt):
        row=self.store.get(actor,project,attempt)
        return self.store.summary(row) if row else None

    def result(self,actor,project,attempt):
        row=self.store.get(actor,project,attempt)
        if not row or row['result'] is None:return None
        if digest(row['result'])!=row['result_sha']:raise NativeJobUnavailable('Execution result checksum mismatch')
        return json.loads(row['result'])

    def events(self,actor,project,attempt,after=0):
        if type(after) is not int or not 0<=after<2**63:raise ValueError('Invalid event cursor')
        if self.get(actor,project,attempt) is None:raise LookupError('Attempt not found')
        return self.store.events(attempt,after)

    def cancel(self,actor,project,attempt):
        return self.store.cancel(actor,project,attempt)
