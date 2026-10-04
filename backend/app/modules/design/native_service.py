from .native_repository import NativeJobRepository, NativeJobConflict, NativeJobUnavailable


def prepare_job(payload):
    from .job_spec import prepare_job as prepare
    return prepare(payload)


class NativeDesignService:
    def __init__(self, directory):
        self.repository = NativeJobRepository(directory)

    def create(self, actor, project_id, scene_id, scene_revision, request_id, payload):
        return self.repository.create(actor, project_id, scene_id, scene_revision, request_id, payload, prepare_job)

    def list_jobs(self, actor, project_id, limit=20, offset=0):
        return self.repository.list_jobs(actor, project_id, limit, offset)

    def get_job(self, actor, project_id, job_id):
        return self.repository.get_job(actor, project_id, job_id)
