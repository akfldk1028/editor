"""Combine preserved imported evidence and locally generated single executions."""
import hashlib
import json
from pathlib import Path

from .workspace_archive import WorkspaceArchive
from .public_urls import normalize_design_urls


def _catalog():
    from .generation.maas.single_execution import catalog
    return catalog


class ExecutionArchive:
    def __init__(self, directory):
        self.imported = WorkspaceArchive(directory)
        self.local_root = Path(directory) / 'single-executions'

    def _runs(self):
        imported, revision = self.imported.index()
        rows = [{'run_id': name, 'created_at': '', 'pnu': '', 'selected_mass_count': len(items),
                 'status': 'unknown', 'replayable': True, 'run_type': 'portfolio'}
                for name, items in sorted(imported.items())]
        local = _catalog().single_execution_runs(self.local_root)
        return imported, rows + local, revision

    def manifest(self, run_id=None):
        imported, runs, revision = self._runs()
        if run_id is None and not imported:
            if not runs:
                raise LookupError('No imported or local executions found')
            run_id = runs[-1]['run_id']
        if _catalog().is_single_execution_run(run_id):
            try:
                value = _catalog().single_execution_archive_manifest(self.local_root, run_id, other_runs=runs)
            except FileNotFoundError as exc:
                raise LookupError('Local execution not found') from exc
        else:
            value = self.imported.manifest(run_id)
        value['runs'] = sorted(runs, key=lambda row: (row['created_at'], row['run_id']))
        value['run_count'] = len(runs)
        value['archive_revision'] = hashlib.sha256(json.dumps([revision, value.get('archive_revision'), runs], sort_keys=True).encode()).hexdigest()
        return normalize_design_urls(value)

    def passport(self, run_id, index):
        if _catalog().is_single_execution_run(run_id):
            if index != 1:
                raise LookupError('A single execution has exactly one mass')
            try:
                return normalize_design_urls(_catalog().single_execution_passport(self.local_root, run_id))
            except FileNotFoundError as exc:
                raise LookupError('Local passport not found') from exc
        return normalize_design_urls(self.imported.passport(run_id, index))

    def preview(self, run_id, index):
        if _catalog().is_single_execution_run(run_id):
            self.passport(run_id, index)
            try:
                return _catalog().single_execution_preview(self.local_root, run_id)
            except FileNotFoundError as exc:
                raise LookupError('Local preview not found') from exc
        return self.imported.preview(run_id, index)
