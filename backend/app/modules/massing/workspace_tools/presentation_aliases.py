"""Group verified delivered forms for presentation, retaining every scored row."""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime

from copy import deepcopy

from backend.app.modules.massing.workspace_tools.solid_presentation import SolidPresentationRegistry
from backend.app.modules.massing.workspace_tools.vlm_shortlist import certificate_digest, shape_id


def row_identity(row):
    return (row.get('track'), row.get('round'), row.get('name'),
            row.get('shape_id'), row.get('certificate_id'))


def group_presentations(curated, ledger, source_for_row):
    """Keep a curated representative and record all exact form-equivalent inputs.

    Source loading must reproduce the actually judged geometry AND certificate.
    Scores are never transferred or averaged. A failure keeps the row separate.
    """
    registry = SolidPresentationRegistry()
    rows, seen = [], set()
    for row in [*curated, *ledger]:
        identity = row_identity(row)
        if identity not in seen:
            seen.add(identity)
            rows.append(row)
    curated_ids = {row_identity(row) for row in curated}
    representatives, output, audit = {}, [], []
    for index, row in enumerate(rows):
        token = f'form-{index + 1}'
        certificate = None
        try:
            source, certificate = source_for_row(row)
            if source is None or not isinstance(certificate, dict):
                raise ValueError('delivered source or certificate unavailable')
            if (not row.get('shape_id') or shape_id(source) != row['shape_id']
                    or certificate.get('shape_id') != row['shape_id']
                    or certificate.get('name') != row['name']
                    or certificate.get('certificate_id') != row.get('certificate_id')
                    or certificate_digest(certificate) != row['certificate_id']):
                raise ValueError('current geometry/certificate does not match its scored row')
            result = registry.find_or_add(token, source)
        except (ValueError, TypeError, AttributeError, RuntimeError) as error:
            result = dict(status='unsupported', duplicate_of=None, reason=str(error))
        group = result.get('duplicate_of') or token
        entry = dict(row=deepcopy(row), certificate=deepcopy(certificate),
                     group_id=group, comparison=deepcopy(result),
                     curated=row_identity(row) in curated_ids)
        audit.append(entry)
        if group in representatives:
            representatives[group].setdefault('solid_form_aliases', []).append(entry)
        elif entry['curated']:
            representative = deepcopy(row)
            representative['presentation_group'] = group
            representative['presentation_comparison'] = deepcopy(result)
            output.append(representative)
            representatives[group] = representative
    return output, dict(schema='mass.solid_presentation_groups.v1',
                        policy='one image per verified occupied form; original scores and dimensions retained',
                        entries=audit)


def current_source_loader():
    from backend.app.modules.massing.workspace_tools.book_import import entry_for_judged_row
    from backend.app.modules.massing.workspace_tools.board_render import _korea_schedule
    from backend.app.modules.massing.workspace_tools.vlm_shortlist import rebuild_seat, seat_context, seat_certificate

    book, site, buildable, axis, base = seat_context()
    korea = _korea_schedule()

    def load(row):
        entry = entry_for_judged_row(row) if row['name'].startswith('book:') else None
        if row.get('track') == 'K' and korea is None:
            raise ValueError('Korean programme schedule unavailable')
        source, _ = rebuild_seat(row['name'], book, site, buildable, axis, base,
                                 schedule=korea if row.get('track') == 'K' else None,
                                 book_entry=entry)
        if source is None:
            return None, None
        return source, seat_certificate(row['name'], source, book, site, book_entry=entry)
    return load
