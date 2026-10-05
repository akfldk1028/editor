"""Which room lands on which floor, and what the mass cannot carry.

A massing sheet answers "how big and what shape". A competition asks the next
question immediately - what is on each floor - and the 실별 소요면적표 already
holds the answer if the brief's own placement rules are read rather than
guessed. 효돈동's brief writes three of them:

    대회의실 천정고 최소 4m 이상
    공용부는 최소 30% 이상 설계
    일시에 다중이 모이는 공간은 피난층과 인접 배치

So the hall goes low, not on top - this brief is on the 피난 side of the split
the survey found (만수6동 puts its 대강당 on the top floor for structure and
noise; 효돈동 and 고전면 put the crowd next to the escape). Rooms marked
`needs_ground` take the ground floor first, the hall takes the lowest floor
that still has room for it, and the rest fill upward largest first.

Service rooms are reported separately rather than placed. The brief builds
지하1/지상3 and every surveyed competition puts plant and stores in that
basement - twelve of twelve, without exception, because a 5.5 m column-free
span underground drags excavation, shoring, smoke control and escape behind
it. This pipeline has no basement, so the honest line is that these 271 m2
are not in the mass rather than a floor invented for them.

    python tools/floor_programme.py <run>
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import json
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, scheme_of, BUILDING_TYPE  # noqa: E402  (django setup inside)
from backend.app.modules.massing.workspace_tools.floor_areas import storey_areas  # noqa: E402

from backend.app.modules.design.generation.maas.massv2 import program as programme  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()
BOOK = ROOT / "inputs" / "programs-korean.json"


def allocate(schedule, *, areas_m2: list[float], shared_share: float):
    """Rooms per floor, and what did not fit.

    `areas_m2` is each storey's own plan area from the ground up. Dividing
    연면적 by the storey count instead - which this did first - is only true
    of a prism: a_one_bend stands on 652 m2 and was being offered 217, so the
    tool reported three schemes unable to hold a 210 m2 hall that in fact had
    room for it twice over.
    """

    plan = [{"storey": n + 1, "usable_m2": round(a * (1.0 - shared_share), 1),
             "rooms": [], "used_m2": 0.0} for n, a in enumerate(areas_m2 or [1.0])]

    def put(level, room, area):
        plan[level]["rooms"].append({"name": room.name, "area_m2": round(area, 1),
                                     "kind": room.kind, "zone": room.zone})
        plan[level]["used_m2"] = round(plan[level]["used_m2"] + area, 1)

    def fits(level, area):
        return plan[level]["used_m2"] + area <= plan[level]["usable_m2"] + 1e-6

    def tightest(area, levels=None):
        """The floor this room fits on with the least left over.

        First-fit put every room on the lowest floor that could take it, so a
        village with uneven plates - 207, 523, 114, 218 m2 - spent its big
        floor on rooms that would have fitted anywhere and then reported four
        small rooms, 69 m2 together, as not fitting. That is the allocator
        being greedy, not the mass being too small.
        """

        candidates = [n for n in (levels if levels is not None else range(len(plan)))
                      if fits(n, area)]
        if not candidates:
            return None
        return min(candidates,
                   key=lambda n: plan[n]["usable_m2"] - plan[n]["used_m2"] - area)

    basement, unplaced = [], []
    rooms = sorted(schedule.rooms, key=lambda r: -r.total_m2)

    # 지하: plant and stores, as every surveyed brief builds them.
    for room in list(rooms):
        if room.kind == "service":
            basement.append({"name": room.name, "area_m2": round(room.total_m2, 1)})
            rooms.remove(room)

    # 피난층: the counter and anything the brief marks as reachable without
    # passing through the building, then the crowd space next to it.
    for room in list(rooms):
        if room.needs_ground:
            put(0, room, room.total_m2)
            rooms.remove(room)
    for room in list(rooms):
        if room.kind == "large_span":
            # The hall still goes as low as it can - 「다중이 모이는 공간은
            # 피난층과 인접」 - so this one keeps first-fit on purpose.
            level = next((n for n in range(len(plan)) if fits(n, room.total_m2)), None)
            if level is None:
                unplaced.append({"name": room.name, "area_m2": round(room.total_m2, 1),
                                 "why": "어느 층도 이 대공간을 담지 못함"})
            else:
                put(level, room, room.total_m2)
            rooms.remove(room)

    for room in rooms:
        level = tightest(room.total_m2)
        if level is None:
            unplaced.append({"name": room.name, "area_m2": round(room.total_m2, 1),
                             "why": "남은 층 면적 부족"})
        else:
            put(level, room, room.total_m2)

    # The 30% the brief reserves for 공용부 has to land somewhere. Subtracting
    # it from each floor's usable area and then never placing it read as empty
    # floors - twenty of thirty tiles looked a storey too large when what was
    # missing was the corridor. It follows the rooms: a floor with none needs
    # no circulation, and one with a third of them carries a third of the core.
    served = sum(f["used_m2"] for f in plan) or 1.0
    budget = served / max(1.0 - shared_share, 1e-6) - served
    for floor in plan:
        if floor["used_m2"] <= 0.0:
            continue
        floor["shared_m2"] = round(budget * floor["used_m2"] / served, 1)
    return plan, unplaced, basement


def main(run: str, programme_name: str = "효돈동 주민센터") -> int:
    folder = ROOT / "runs" / run
    summary = json.loads((folder / "massv2-summary.json").read_text(encoding="utf-8"))
    picks = json.loads((folder.parent / f"{run}-pick" / "picks.json")
                       .read_text(encoding="utf-8"))["picks"]
    records = {r["name"]: r for r in summary["records"]}

    book = json.loads(BOOK.read_text(encoding="utf-8"))
    share = book.get("shared_area_share_of_gross") or {}
    share = float(share.get("min") or 0.30) if isinstance(share, dict) else float(share)
    record = next(r for r in book["schedules"] if r.get("name") == programme_name)
    schedule = programme.schedule_from_record(record, shared_share_of_gross=share)

    corpus = {}
    for path in sorted((ROOT / "inputs").glob("gen-*.json")):
        for s in json.loads(path.read_text(encoding="utf-8"))["schemes"]:
            corpus[s["name"]] = s
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))

    out = []
    for p in picks:
        rec = records.get(p["name"]) or {}
        scheme = corpus.get(scheme_of(p["name"]))
        if scheme is None:
            continue
        storey = float(rec.get("floor_height_m") or 3.0)
        asked = max((float(op.get("storeys") or 0)
                     for op in scheme.get("ops", [])), default=0.0)
        src = rebuild(p["name"], corpus, site, buildable, axis,
                      max(base, asked * site.floor_height_m), schedule=schedule)
        if src is None:
            continue
        areas = storey_areas(src, height_m=float(p["height_m"] or 0.0),
                             storey_m=storey)
        plan, unplaced, basement = allocate(
            schedule, areas_m2=areas, shared_share=share)
        out.append({"id": p["id"], "family": p["family"], "floors": len(areas),
                    "areas_m2": [round(a, 1) for a in areas],
                    "plan": plan, "unplaced": unplaced, "basement": basement})

    path = folder.parent / f"{run}-pick" / "programme.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    short = [r for r in out if r["unplaced"]]
    print(f"{len(out)} picks, {len(short)} cannot hold the brief")
    for r in short[:8]:
        names = ", ".join(u["name"] for u in r["unplaced"])
        print(f"  #{r['id']:02d} {r['family'][:32]:<32} {r['floors']}층  못 담음: {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], *(sys.argv[2:3] or [])))
