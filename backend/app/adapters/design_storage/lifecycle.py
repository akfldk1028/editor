"""Database-owned execution claims and replayable events for design jobs."""
import json
import logging
import threading
import time
import uuid
from datetime import timedelta

from django.db import close_old_connections, connections, transaction
from django.db.models import Q
from django.utils import timezone

from .models import OptimizationJob, OptimizationJobEvent

logger = logging.getLogger(__name__)
TERMINAL = {'complete', 'failed', 'cancelled'}
LEASE_SECONDS = 30
HEARTBEAT_SECONDS = 5


def recover_interrupted(job_id):
    cutoff = timezone.now() - timedelta(seconds=LEASE_SECONDS)
    message = 'Execution interrupted: its worker lease expired. Create a new job to retry.'
    with transaction.atomic():
        changed = OptimizationJob.objects.filter(id=job_id, status='running').filter(
            Q(heartbeat_at__lt=cutoff) | Q(heartbeat_at__isnull=True)
        ).update(status='failed', error=message, completed_at=timezone.now())
        if changed:
            OptimizationJobEvent.objects.create(job_id=job_id, kind='error', payload={
                'type': 'error', 'message': message, 'recovery_required': True,
            })
    return bool(changed)


def owns_job(job_id, token):
    return OptimizationJob.objects.filter(id=job_id, status='running', execution_token=token).exists()


def publish(job_id, token, event, *, persist=None):
    kind = event.get('type', 'update')
    values = {'heartbeat_at': timezone.now()}
    if kind in {'complete', 'error', 'cancelled'}:
        values.update(status={'complete': 'complete', 'error': 'failed', 'cancelled': 'cancelled'}[kind], completed_at=timezone.now())
        if kind == 'error':
            values['error'] = event.get('message', 'Unknown execution error')
    if kind in {'generation', 'complete'}:
        values['generation_count'] = event.get('generations' if kind == 'complete' else 'generation', 0)
    with transaction.atomic():
        # Updating before reading acquires SQLite's write reservation and makes
        # cancellation and completion mutually exclusive across worker processes.
        changed = OptimizationJob.objects.filter(id=job_id, status='running', execution_token=token).update(**values)
        if not changed:
            return False
        if persist is not None:
            persist()
        OptimizationJobEvent.objects.create(job_id=job_id, kind=kind, payload=json.loads(json.dumps(event, default=str)))
    return True


def cancel(job_id):
    with transaction.atomic():
        changed = OptimizationJob.objects.filter(id=job_id, status__in=['pending', 'running']).update(status='cancelled', completed_at=timezone.now())
        if changed:
            OptimizationJobEvent.objects.create(job_id=job_id, kind='cancelled', payload={'type': 'cancelled'})
        return OptimizationJob.objects.get(id=job_id)


def _heartbeat(job_id, token, stopped):
    close_old_connections()
    try:
        while not stopped.wait(HEARTBEAT_SECONDS):
            if not OptimizationJob.objects.filter(id=job_id, status='running', execution_token=token).update(heartbeat_at=timezone.now()):
                return
    except Exception:
        logger.exception('Design execution heartbeat failed for %s', job_id)
    finally:
        connections.close_all()


def _run(job_id, token, producer):
    close_old_connections()
    stopped = threading.Event()
    heartbeat = threading.Thread(target=_heartbeat, args=(job_id, token, stopped), daemon=True)
    try:
        heartbeat.start()
        if owns_job(job_id, token):
            producer(job_id, token)
        if owns_job(job_id, token):
            raise RuntimeError('Optimization ended without a terminal event')
    except Exception as exc:
        logger.exception('Design execution failed for %s', job_id)
        try:
            publish(job_id, token, {'type': 'error', 'message': str(exc)})
        except Exception:
            # A database outage cannot be reported as success; an expired lease
            # becomes an explicit interrupted failure when storage is available.
            logger.exception('Cannot persist design failure for %s', job_id)
    finally:
        stopped.set()
        if heartbeat.is_alive():
            heartbeat.join(timeout=1)
        connections.close_all()


def start(job_id, producer):
    recover_interrupted(job_id)
    token = uuid.uuid4()
    claimed = OptimizationJob.objects.filter(id=job_id, status='pending').update(
        status='running', execution_token=token, heartbeat_at=timezone.now(), error='',
    )
    job = OptimizationJob.objects.get(id=job_id)
    if claimed:
        try:
            threading.Thread(target=_run, args=(job_id, token, producer), daemon=True).start()
        except Exception as exc:
            publish(job_id, token, {'type': 'error', 'message': str(exc)})
            raise
    return job


def replay(job_id, after=0):
    if after < 0:
        raise ValueError('Event cursor must be non-negative')
    try:
        while True:
            recover_interrupted(job_id)
            events = list(OptimizationJobEvent.objects.filter(job_id=job_id, id__gt=after).order_by('id')[:100])
            for event in events:
                after = event.id
                yield f'id: {event.id}\nevent: {event.kind}\ndata: {json.dumps(event.payload)}\n\n'
            status = OptimizationJob.objects.values_list('status', flat=True).get(id=job_id)
            if status in TERMINAL:
                # Completion may commit between the first event read and status
                # read. Drain its journal entry before closing this connection.
                if not OptimizationJobEvent.objects.filter(job_id=job_id, id__gt=after).exists():
                    return
                continue
            if not events:
                yield ': keepalive\n\n'
                time.sleep(.25)
    finally:
        close_old_connections()
