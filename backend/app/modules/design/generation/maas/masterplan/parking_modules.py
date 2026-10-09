"""Whole parking-row/aisle recipes with explicit, unclipped landing connections."""
import math

from shapely.affinity import rotate
from shapely.geometry import box, LineString
from shapely.ops import unary_union

from .geometry import EPS, parts
from .rows_tiling import _fill_row
from .circulation import closed_aisle_loop, full_width_stall_access


RECIPES = {'module16': 'PAP', 'module27': 'PAPPA', 'module32': 'PAPPAP'}


def _runs(host, y, depth):
    x0, _, x1, _ = host.bounds
    excluded = sorted((p.bounds[0], p.bounds[2]) for p in
                      parts(box(x0, y, x1, y + depth).difference(host)))
    cursor = x0
    for lo, hi in excluded:
        if lo > cursor + EPS:
            yield cursor, lo
        cursor = max(cursor, hi)
    if cursor < x1 - EPS:
        yield cursor, x1


def _connection(host, drive, anchors, ports, width):
    result = drive
    for anchor in anchors:
        choices = []
        ax, ay = anchor.centroid.coords[0]
        for px, py in ports:
            for corner in ((ax, py), (px, ay)):
                points = [(ax, ay), corner, (px, py)]
                points = [p for i, p in enumerate(points) if not i or p != points[i-1]]
                corridor = (LineString(points).buffer(width/2, cap_style=2, join_style=2)
                            if len(points) > 1 else anchor)
                joined = unary_union([result, anchor, corridor])
                if joined.geom_type == 'Polygon' and host.buffer(EPS).covers(joined):
                    choices.append(joined)
        if not choices:
            return None
        result = min(choices, key=lambda g: g.area)
    return result


def module_candidates(host, anchors, rules, required, accessible, *, family, angles,
                      field, expanded_needed=None, limit=12):
    if family not in (*RECIPES, 'auto') or field not in ('auto', 'single', 'comb', 'ring'):
        raise ValueError('unsupported module family or circulation')
    if host.is_empty or not anchors or any(a.is_empty for a in anchors):
        return []
    w, length = float(rules['stall_width_m']), float(rules['stall_length_m'])
    aw, al = float(rules['accessible_width_m']), float(rules['accessible_length_m'])
    aisle = float(rules['aisle_width_m'])
    expanded = ((float(rules['expanded_width_m']), float(rules['expanded_length_m']))
                if rules.get('expanded_min_share') else None)
    want_exp = (int(expanded_needed) if expanded_needed is not None else
                math.ceil(float(rules.get('expanded_min_share') or 0) * (required or 0)))
    depth = max(length, al if accessible else length, expanded[1] if expanded and want_exp else length)
    raw, tried = [], 0
    for angle in angles:
        local = rotate(host, -angle, origin=(0,0))
        if not local.is_valid:
            local = local.buffer(0)
        arrival = [rotate(a, -angle, origin=(0,0)) for a in anchors]
        _, ymin, _, ymax = local.bounds
        for name in (RECIPES if family == 'auto' else [family]):
            for recipe in dict.fromkeys([RECIPES[name], RECIPES[name][::-1]]):
                spans, pos = [], 0.
                for kind in recipe:
                    size = depth if kind == 'P' else aisle
                    spans.append((kind, pos, pos + size))
                    pos += size
                if pos > ymax-ymin+EPS or (field == 'single' and recipe.count('A') != 1):
                    continue
                starts = {ymin, ymax-pos}
                starts.update(ymin+i for i in range(int(ymax-ymin-pos)+1))
                for a in arrival:
                    starts.update(a.centroid.y-(lo+hi)/2 for kind,lo,hi in spans if kind=='A')
                for y in sorted(starts):
                    if y < ymin-EPS or y+pos > ymax+EPS:
                        continue
                    for left, right in _runs(local,y,pos):
                        for ring in ([True] if field=='ring' else [False,True] if field=='auto' else [False]):
                            if ring and recipe.count('A') < 2:
                                continue
                            cross = 2 if ring else 1
                            max_bays = int((right-left-cross*aisle+EPS)//w)
                            if max_bays < 2:
                                continue
                            target_bays = math.ceil(((required or 0)*w + accessible*(aw-w)
                                + want_exp*((expanded or (w,))[0]-w))/max(1,recipe.count('P'))/w)
                            for bays in sorted({max_bays, min(max_bays,max(2,target_bays)),
                                                min(max_bays,max(2,target_bays+1))}):
                                width = bays*w + cross*aisle
                                for x in dict.fromkeys([left, right-width]):
                                    for end in ([0] if ring else [0,1]):
                                        tried += 1
                                        envelope=box(x,y,x+width,y+pos)
                                        if not local.buffer(EPS).covers(envelope):
                                            continue
                                        xs = x+aisle if ring or end==0 else x
                                        xe = x+width-aisle if ring or end==1 else x+width
                                        aisles=[box(x,y+lo,x+width,y+hi) for kind,lo,hi in spans if kind=='A']
                                        alo=min(lo for kind,lo,hi in spans if kind=='A')
                                        ahi=max(hi for kind,lo,hi in spans if kind=='A')
                                        cross_x=[x] if end==0 else [x+width-aisle]
                                        if ring:
                                            cross_x=[x,x+width-aisle]
                                        aisles += [box(cx,y+alo,cx+aisle,y+ahi) for cx in cross_x]
                                        drive=unary_union(aisles)
                                        ports=[(cx+aisle/2,y+(lo+hi)/2) for cx in cross_x
                                               for kind,lo,hi in spans if kind=='A']
                                        joined=_connection(local,drive,arrival,ports,aisle)
                                        if joined is None:
                                            continue
                                        raw.append((recipe.count('P')*bays, -joined.area, name, recipe,
                                                    angle, y, xs, xe, pos, spans, joined, arrival, ring, envelope))
    # Limit expensive stall and clearance construction after testing whole field geometry.
    raw.sort(key=lambda c:(min(c[0],required or c[0]),c[1]),reverse=True)
    # Deduplicate before budgeting and reserve every width/family/axis/topology.
    # Nominal capacity can overestimate packing after special bays and connections.
    groups, seen = {}, set()
    for candidate in raw:
        _, _, name, recipe, angle, y, xs, xe, _, _, drive, _, ring, _ = candidate
        key=(angle,recipe,xs,xe,y,drive.wkb)
        if key in seen:
            continue
        seen.add(key)
        group=(name,recipe,angle,ring,round(xe-xs,6))
        groups.setdefault(group,[]).append(candidate)
    shortlist=[]
    for index in range(max((len(g) for g in groups.values()),default=0)):
        shortlist.extend(g[index] for g in groups.values() if index<len(g))
        if len(shortlist)>=max(96,len(groups)):
            break
    results=[]
    for _, _, name, recipe, angle, y, xs, xe, actual_depth, spans, drive, arrival, ring, envelope in shortlist:
        local=rotate(host,-angle,origin=(0,0))
        if not local.is_valid:
            local=local.buffer(0)
        stalls=[]
        for i,(kind,lo,hi) in enumerate(spans):
            if kind!='P':
                continue
            ai=i-1 if i and spans[i-1][0]=='A' else i+1
            _,a0,a1=spans[ai]
            row=_fill_row(local,drive,y+a0,y+a1,xs,xe,w,length,aw,al,
                max(0,accessible-sum(s['type']=='accessible' for s in stalls)),drive,
                1 if ai<i else -1,expanded=expanded,want_expanded=want_exp,
                n_expanded_start=sum(s['type']=='expanded' for s in stalls))
            stalls.extend({**s,'module_row':i} for s in row)
        if not stalls:
            continue
        if required and len(stalls)>required:
            # Keep the short banks balanced, while reserving supplied special-bay quotas.
            row_counts={i:0 for i in range(len(spans))}
            ordered=sorted(stalls,key=lambda s:(s['type']=='standard_90deg',s['polygon'].bounds[0]))
            special=[s for s in ordered if s['type']!='standard_90deg']
            for s in special:
                row_counts[s['module_row']]+=1
            chosen=special[:required]
            ordinary=[s for s in ordered if s['type']=='standard_90deg']
            while ordinary and len(chosen)<required:
                s=min(ordinary,key=lambda s:(row_counts[s['module_row']],s['polygon'].bounds[0]))
                ordinary.remove(s);chosen.append(s);row_counts[s['module_row']]+=1
            stalls=chosen
        if ring and closed_aisle_loop(drive,aisle) is None:
            continue
        if not full_width_stall_access(drive,[s['polygon'] for s in stalls],arrival,aisle):
            continue
        if rules.get('parking_mix')=='parallel_infill':
            from .parallel_parking import infill
            stalls=infill(local,drive,stalls,required or len(stalls),aisle_width=aisle)
        unrot=lambda g:rotate(g,angle,origin=(0,0))
        receipt={'family':name,'recipe':recipe,'depth_m':round(actual_depth,6),
                 'parking_rows':recipe.count('P'),'angle_deg':angle,
                 'circulation':'ring' if ring else 'comb','full_width_connected':True,
                 'swept_path_status':'unverified'}
        results.append({'stalls':[{**s,'polygon':unrot(s['polygon']),'front':unrot(s['front'])} for s in stalls],
            'drive':unrot(drive),'entrance':anchors[0],'provided':len(stalls),
            'accessible':sum(s['type']=='accessible' for s in stalls),
            'pattern':name,'module_layout':receipt,'angle_deg':angle,
            'bands':recipe.count('A'),'cross_aisles':2 if ring else 1,
            'dead_end_stalls':0 if ring else int((xe-xs)//w),
            'score':-drive.area/max(1,len(stalls)),'search_count':tried})
    results.sort(key=lambda p:(min(p['accessible'],accessible),min(p['provided'],required or p['provided']),
        min(sum(s['type']=='expanded' for s in p['stalls']),want_exp),p['score']),reverse=True)
    return results[:limit]
