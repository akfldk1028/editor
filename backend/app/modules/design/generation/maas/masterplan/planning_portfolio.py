"""Retain solved layouts for downstream architectural comparison, without a total score."""
from copy import deepcopy
from .geometry import digest


def policy(options):
    name=options.get('selection_policy', 'siting_portfolio_v1' if options.get('planning_stage')=='placement' else 'legacy_parking_v1')
    if name not in ('legacy_parking_v1','siting_portfolio_v1'):
        raise ValueError('unsupported planning selection_policy')
    limit=options.get('max_planning_candidates',3)
    if type(limit) is not int or not 1<=limit<=8:
        raise ValueError('max_planning_candidates must be an integer in 1..8')
    return name,limit


def retain(layouts, primary, *, limit):
    policy({'max_planning_candidates':limit})
    kept,excluded,pending,seen=[],[],[],set()
    primary_hash=digest(primary['features'])
    for index,layout in enumerate(layouts):
        geometry_hash=digest(layout['features'])
        identity={'id':'placement-'+geometry_hash[:16], 'geometry_hash':geometry_hash,'source_index':index}
        if layout['validation']['geometry_status']!='passed':
            excluded.append({**identity,'reason':'geometry_failure'})
            continue
        if geometry_hash in seen:
            excluded.append({**identity,'reason':'same_geometry'})
            continue
        seen.add(geometry_hash)
        upper=[f['geometry'] for f in layout['features'] if f.get('properties',{}).get('layer')=='building_footprint']
        pending.append({**identity,'family_id':digest(upper),'layout':deepcopy(layout)})
    pending.sort(key=lambda v:(v['geometry_hash']!=primary_hash,v['source_index']))
    families=set()
    for item in pending:
        if item['family_id'] not in families and len(kept)<limit:
            kept.append(item)
            families.add(item['family_id'])
    for item in pending:
        if item not in kept and len(kept)<limit:
            kept.append(item)
    for item in pending:
        if item not in kept:
            excluded.append({k:v for k,v in item.items() if k!='layout'} | {'reason':'candidate_budget'})
    return {'candidates':kept,'excluded':excluded,'limit':limit,
            'policy':'siting_portfolio_v1',
            'scope':'Completed layouts only; footprint grouping is not architectural diversity or owner acceptance. Primary is a compatibility choice, not the architectural winner.'}
