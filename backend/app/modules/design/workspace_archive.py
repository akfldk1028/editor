"""Read paired, byte-verified MASS images/passports already captured by Editor.

This view does not compile geometry, infer legal approval, or rerun providers.
The original source/run IDs and passport claims remain archival evidence.
"""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode

from .artifacts import ArtifactArchive, ArtifactArchiveError


SOURCE = 'arr-maas-cache'
PAIR = re.compile(r'^executed-masses/([A-Za-z0-9_.-]+)/mass-(\d+)-([a-f0-9]+)\.png\.passport\.json$')


class WorkspaceArchive:
    def __init__(self, directory):
        self.archive = ArtifactArchive(Path(directory) / 'artifacts')

    def index(self):
        entries = self.archive.entries(SOURCE)
        runs = {}
        for name in entries:
            match = PAIR.fullmatch(name)
            image = name.removesuffix('.passport.json')
            if match and image in entries:
                run, number, digest = match.groups()
                items = runs.setdefault(run, {})
                if int(number) in items:
                    raise ArtifactArchiveError('Ambiguous MASS index in captured run')
                items[int(number)] = {'passport': name, 'image': image, 'geometry_prefix': digest}
        return runs, hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()

    def _select(self, run_id, index):
        runs, _ = self.index()
        if not run_id or run_id not in runs or index not in runs[run_id]:
            raise LookupError('Archived MASS not found')
        return runs[run_id][index]

    def passport(self, run_id, index):
        entry = self._select(run_id, index)
        path = self.archive.file(SOURCE, entry['passport'])
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ArtifactArchiveError('Passport exceeds supported size')
        value = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or not isinstance(value.get('geometry_hash'), str)
                or not value['geometry_hash'].startswith(entry['geometry_prefix'])
                or not isinstance(value.get('program_hash'), str)
                or not value['program_hash'] or not isinstance(value.get('activation_graph'), dict)
                or not isinstance(value.get('stages'), list)):
            raise ArtifactArchiveError('Image and passport identity do not match')
        return value

    def preview(self, run_id, index):
        self.passport(run_id, index)
        return self.archive.file(SOURCE, self._select(run_id, index)['image'])

    def manifest(self, run_id=None):
        runs, revision = self.index()
        if not runs:
            raise LookupError('No paired MASS images and passports have been imported')
        selected = run_id or sorted(runs)[-1]
        if selected not in runs:
            raise LookupError('Archived run not found')
        masses = []
        pnu = ''
        for index in sorted(runs[selected]):
            passport = self.passport(selected, index)
            query = urlencode({'run_id': selected})
            base = f'/api/v1/design/maas/executed-masses/{index}'
            graph = passport['activation_graph']
            collaboration = passport.get('agent_collaboration') or {}
            pnu = (collaboration.get('identity') or {}).get('pnu') or pnu
            masses.append({
                'archive_key': runs[selected][index]['passport'], 'index': index,
                'run_id': selected, 'variant_id': passport.get('mass_id') or f'mass-{index}',
                'label': passport.get('program_name') or f'MASS {index}',
                'program_label': passport.get('program_name') or '',
                'program_type': '', 'operation_label': '', 'source_sequence': '',
                'program_hash': passport['program_hash'], 'geometry_hash': passport['geometry_hash'],
                'visual_hash': passport.get('visual_hash', ''),
                'floor_capacity_plan_hash': passport.get('floor_capacity_plan_hash', ''),
                'final_geometry_hash': passport.get('final_legal_geometry_hash', ''),
                'legal_floor_field_hash': passport.get('legal_floor_field_hash', ''),
                'candidate_actual_gfa_stop_hash': passport.get('candidate_actual_gfa_stop_hash', ''),
                'dsl': '', 'node_count': len(graph.get('nodes', [])), 'operator_path': [],
                'book_principle_id': '', 'book_scope': '', 'book_orientation': '',
                'capacity_alternative_id': '', 'capacity_target_utilization': None,
                'capacity_achieved_utilization': None, 'far_pct': None, 'score': None,
                'hard_pass': passport.get('final_hard_pass') is True,
                'vlm_evaluated': any(stage.get('id') == 'vlm' and stage.get('status') not in (None, 'not_evaluated')
                                     for stage in passport['stages']),
                'preview_url': f'{base}?{query}', 'passport_url': f'{base}/passport?{query}',
                'image_role': 'actual_run_candidate_render',
            })
        return {
            'schema_version': 'editor.design.archived_mass_view.v1',
            'run_id': selected, 'selected_run_id': selected, 'pnu': pnu,
            'run_status': 'archived', 'numeric_status': 'not_reverified',
            'source_archive': SOURCE, 'archive_revision': revision,
            'mass_count': len(masses), 'run_count': len(runs), 'masses': masses,
            'book_images_included': False, 'portfolio_vlm_audit': {},
            'image_authority': 'byte-preserved archived image paired with original geometry passport',
            'editor_provenance': {'kind': 'imported_artifacts', 'execution_verified': False},
            'runs': [{'run_id': name, 'created_at': '', 'pnu': '', 'selected_mass_count': len(items),
                      'status': 'unknown', 'replayable': True, 'run_type': 'portfolio'}
                     for name, items in sorted(runs.items())],
        }
