"""Run the production BOOK delivery owners before admitting a search branch."""

import hashlib
import json

from backend.app.modules.massing.workspace_tools.book_import import candidate_record, _compile_record, _refused


class BookDeliveryProbe:
    def __init__(self, site, *, run_id):
        self.site = site
        self.buildable = site.plan_at(0.0)
        self.run_id = run_id
        self.cache = {}

    def __call__(self, candidate):
        # Program/mesh hashes omit metadata that changes facing and dimensional delivery.
        record = candidate_record(candidate, run_id=self.run_id)
        key = hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if key not in self.cache:
            source, entry = _compile_record(record, self.buildable, self.site)
            reason = str(entry) if source is None else _refused(source, self.site)
            self.cache[key] = {
                'accepted': not bool(reason), 'reason': reason,
                'authority': 'book_import._compile_record + book_import._refused',
                'site_pnu': str(self.site.pnu),
                'delivered_gfa_m2': entry.get('floor_area_m2') if source is not None else None,
                'legal_approval': False, 'structural_capacity_verified': False,
            }
        return dict(self.cache[key])
