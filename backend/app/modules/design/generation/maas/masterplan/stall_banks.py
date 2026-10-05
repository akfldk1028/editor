"""Trim parking demand without leaving one isolated bay from a larger bank."""
import math
from shapely.geometry import shape


def banks(stalls):
    geometries=[s.get('polygon') if 'polygon' in s else shape(s['geometry']) for s in stalls]
    lengths=[];edges=[];bounds=[]
    for s,g in zip(stalls,geometries):
        points=[p[:2] for p in g.exterior.coords]
        length=float((s.get('properties') or s).get('length_m') or
                     max(math.dist(a,b) for a,b in zip(points,points[1:])))
        lengths.append(length);bounds.append(g.bounds)
        edges.append([(a,b) for a,b in zip(points,points[1:]) if math.dist(a,b)>=length-1e-5])
    def shared_side(i,j):
        for a,b in edges[i]:
            dx,dy=b[0]-a[0],b[1]-a[1];span=math.hypot(dx,dy)
            if span<1e-8:continue
            ux,uy=dx/span,dy/span
            for c,d in edges[j]:
                if any(abs((p[0]-a[0])*uy-(p[1]-a[1])*ux)>1e-5 for p in (c,d)):
                    continue
                x,y=sorted((p[0]-a[0])*ux+(p[1]-a[1])*uy for p in (c,d))
                if min(span,y)-max(0,x)>=min(lengths[i],lengths[j])-1e-4:return True
        return False
    adjacent={i:[] for i in range(len(stalls))}
    for i,a in enumerate(bounds):
        for j in range(i+1,len(geometries)):
            b=bounds[j]
            if a[2]<b[0]-1e-5 or b[2]<a[0]-1e-5 or a[3]<b[1]-1e-5 or b[3]<a[1]-1e-5:
                continue
            if shared_side(i,j):
                adjacent[i].append(j);adjacent[j].append(i)
    unseen=set(adjacent);out=[]
    while unseen:
        todo=[min(unseen)];group=[]
        while todo:
            i=todo.pop()
            if i not in unseen:continue
            unseen.remove(i);group.append(i);todo.extend(adjacent[i])
        # In a straight bay bank a principal coordinate orders adjacent bays.
        centres=[geometries[i].centroid for i in group]
        use_x=max(p.x for p in centres)-min(p.x for p in centres) >= max(p.y for p in centres)-min(p.y for p in centres)
        group.sort(key=lambda i:geometries[i].centroid.x if use_x else geometries[i].centroid.y)
        out.append(group)
    return out


def select_complete_banks(stalls, required):
    if required<=0:return []
    if required==1:return stalls[:1]
    dp={0:((0,0),[])}
    for group in banks(stalls):
        choices={0:((0,0),[])}
        for length in range(2,min(len(group),required)+1):
            for start in range(len(group)-length+1):
                chosen=[stalls[i] for i in group[start:start+length]]
                score=(sum(s['type']=='accessible' for s in chosen),sum(s['type']=='expanded' for s in chosen))
                if length not in choices or score>choices[length][0]:choices[length]=(score,chosen)
        nxt={}
        for count,(score,chosen) in dp.items():
            for n,(extra,items) in choices.items():
                if count+n>required:continue
                rank=(score[0]+extra[0],score[1]+extra[1])
                if count+n not in nxt or rank>nxt[count+n][0]:nxt[count+n]=(rank,chosen+items)
        dp=nxt
    return dp[max(dp)][1]
