"""The rooms the building is asked to hold, and what they do to its mass.

Two things make a mass, and this package has only ever had one of them. The
form language says which operations and where they aim; nothing said what is
inside. So every volume was the same kind of thing and the only reason one
could be larger than another was a ratio the corpus fixed - which is why the
hierarchy had to be legislated (`MIN_TIER_CONTRAST`) instead of arriving on its
own, and why thirty-six sentences from three offices whose work looks nothing
alike came out at four to six comparable pieces each.

A room schedule gives it for free. A 주민센터 with a 400 m² 다목적실 and a
60 m² 사무실 has a dominant volume because the brief has one, and the large room
needs six metres of clear height where the others need three, which decides
what can sit above what. In Korean competition practice that schedule is not a
designer's choice at all: the 공모지침서 issues 실별 소요면적표 and the entry is
judged partly on matching it.

This module is the second track. It does not replace the form language - a
parti still says stack, shear, carve and where - it supplies the metres those
verbs act on, so the same sentence can be run form-first or programme-first or
anywhere between.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RoomKind = Literal["large_span", "normal", "service"]
Zone = Literal["public", "shared", "private", "service"]


# Clear height a room of each kind needs, before structure. A 다목적실 or
# 체육실 is not a tall normal room, it is a different decision about where it
# can go: nothing sits above it cheaply, and it cannot sit on a normal grid.
CLEAR_HEIGHT_M: dict[str, float] = {
    "large_span": 6.0,
    "normal": 2.7,
    "service": 2.4,
}

# What a floor costs on top of its rooms: circulation, walls, cores, plant.
# Korean 공모지침서 usually issue 소요면적 as net, and the 연면적 in the
# 건축개요 is gross, so a proposal that stacks net areas is short by this much.
GROSS_UP = 1.35


@dataclass(frozen=True)
class Room:
    """One line of the 실별 소요면적표."""

    name: str
    area_m2: float
    count: int = 1
    kind: RoomKind = "normal"
    zone: Zone = "shared"
    # A room the brief says must be reachable without passing through the rest
    # of the building - a 주민센터's 민원실, a library's 어린이실 - which is a
    # reason for it to be on the ground floor rather than a preference.
    needs_ground: bool = False
    note: str = ""

    @property
    def total_m2(self) -> float:
        return self.area_m2 * max(1, self.count)

    @property
    def clear_height_m(self) -> float:
        return CLEAR_HEIGHT_M[self.kind]

    def evidence(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "area_m2": round(self.area_m2, 1),
            "count": self.count,
            "total_m2": round(self.total_m2, 1),
            "kind": self.kind,
            "zone": self.zone,
            "needs_ground": self.needs_ground,
        }


@dataclass(frozen=True)
class Schedule:
    """A 실별 소요면적표, and what it implies about the building."""

    name: str
    rooms: tuple[Room, ...]
    building_type: str = "제1종근린생활시설"
    notes: tuple[str, ...] = field(default_factory=tuple)
    # What the brief itself says the shared part must be, as a share of 연면적.
    # 효돈동, 만수6동, 용당동 and 고전면 all write it - "공용부는 최소 30% 이상",
    # "연면적의 35% 내외" - and it is the number that decides how much building
    # a schedule of net rooms actually asks for. None means the brief is silent
    # and GROSS_UP stands in.
    shared_share_of_gross: float | None = None

    @property
    def net_m2(self) -> float:
        return sum(room.total_m2 for room in self.rooms)

    @property
    def gross_m2(self) -> float:
        """연면적 the schedule implies once circulation and structure are in.

        GROSS_UP is 1.35, which is a shared part of 25.9% of the gross - under
        the 30% minimum these briefs mandate. Where the brief states its own
        share, that share decides: 효돈동's 1,042 m² of net rooms asks for
        1,489 m² at 30%, not the 1,407 m² a flat 1.35 produces, and the
        difference is a storey of this building.
        """

        share = self.shared_share_of_gross
        if share is not None and 0.0 < share < 0.9:
            return self.net_m2 / (1.0 - share)
        return self.net_m2 * GROSS_UP

    def of_kind(self, kind: RoomKind) -> tuple[Room, ...]:
        return tuple(room for room in self.rooms if room.kind == kind)

    @property
    def large_span_m2(self) -> float:
        return sum(room.total_m2 for room in self.of_kind("large_span"))

    def dominance(self) -> float:
        """What share of the building its largest single room is.

        This is the number the form language had to invent. A brief with a
        400 m² hall among 60 m² offices has a dominant volume before anybody
        draws anything; a brief of twenty equal classrooms does not, and no
        amount of tier contrast should manufacture one.
        """

        if not self.rooms:
            return 1.0
        largest = max(room.area_m2 for room in self.rooms)
        return largest / max(self.net_m2, 1e-9)

    def storeys_needed(self, *, ground_capacity_m2: float) -> float:
        """How many floors this schedule needs on the ground the law allows."""

        return self.gross_m2 / max(ground_capacity_m2, 1e-9)

    def fits(self, *, far_capacity_m2: float) -> bool:
        return self.gross_m2 <= far_capacity_m2 + 1e-6

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.massv2_program.v1",
            "name": self.name,
            "building_type": self.building_type,
            "room_count": len(self.rooms),
            "net_m2": round(self.net_m2, 1),
            "gross_m2": round(self.gross_m2, 1),
            "large_span_m2": round(self.large_span_m2, 1),
            "dominance": round(self.dominance(), 3),
            "rooms": [room.evidence() for room in self.rooms],
        }


def schedule_from_record(
    record: dict[str, Any], *, shared_share_of_gross: float | None = None,
) -> Schedule | None:
    """Read a 소요면적표 as issued. Unknown room kinds are normal rooms.

    `shared_share_of_gross` is the book-level rule, passed in because the
    briefs state it once for the whole set rather than per schedule; a
    schedule may override it with its own value.
    """

    shared_share = record.get("shared_area_share_of_gross", shared_share_of_gross)
    if isinstance(shared_share, dict):
        # Written as a range - "최소 30% 이상", "35% 내외". Take the minimum: it
        # is the number the brief makes mandatory, and the rest is latitude.
        shared_share = shared_share.get("min")
    try:
        shared_share = float(shared_share) if shared_share is not None else None
    except (TypeError, ValueError):
        shared_share = None

    rooms: list[Room] = []
    for item in record.get("rooms") or ():
        try:
            area = float(item.get("area_m2"))
        except (TypeError, ValueError):
            continue
        if area <= 0.0:
            continue
        kind = str(item.get("kind") or "normal")
        rooms.append(Room(
            name=str(item.get("name") or "실"),
            area_m2=area,
            count=int(item.get("count") or 1),
            kind=kind if kind in CLEAR_HEIGHT_M else "normal",
            zone=str(item.get("zone") or "shared"),  # type: ignore[arg-type]
            needs_ground=bool(item.get("needs_ground")),
            note=str(item.get("note") or ""),
        ))
    if not rooms:
        return None
    return Schedule(
        name=str(record.get("name") or "unnamed"),
        rooms=tuple(rooms),
        building_type=str(record.get("building_type") or "제1종근린생활시설"),
        notes=tuple(str(n) for n in (record.get("notes") or ())),
        shared_share_of_gross=shared_share,
    )


def volume_shares(schedule: Schedule, *, pieces: int) -> tuple[float, ...]:
    """Split the schedule into as many volumes as the sentence has, by area.

    The large-span rooms come first and stay whole - a hall cannot be divided
    between two volumes and still be a hall - and what is left is grouped by
    zone so the remainder splits along a line the brief already draws rather
    than an arbitrary one. Returned as shares of the whole so the executor can
    keep owning the metres.
    """

    if pieces <= 0 or not schedule.rooms:
        return ()

    large = sorted(
        (room.total_m2 for room in schedule.of_kind("large_span")), reverse=True
    )
    rest = schedule.net_m2 - sum(large)

    groups = list(large[:pieces])
    remaining = pieces - len(groups)
    if remaining > 0 and rest > 0.0:
        # The rest of the brief, split evenly among the volumes left. Evenly
        # here is honest: nothing in the schedule says how the small rooms
        # divide, so the sentence decides, and the caller may still modulate.
        groups.extend([rest / remaining] * remaining)
    if not groups:
        return ()
    total = sum(groups)
    return tuple(value / total for value in groups)


def blended(
    authored: tuple[float, ...],
    programme: tuple[float, ...],
    *,
    weight: float,
) -> tuple[float, ...]:
    """Mix what the sentence asked for with what the brief requires.

    `weight` 0 leaves the form language alone, 1 hands the sizes to the room
    schedule, and between the two the brief pulls the authored proportions
    toward itself. The two tracks are meant to run separately and to be mixed,
    so this is a dial rather than a mode.
    """

    if not authored:
        return programme
    if not programme:
        return authored
    share = max(0.0, min(1.0, weight))
    paired = list(zip(authored, programme))
    mixed = [one * (1.0 - share) + two * share for one, two in paired]
    # Anything the sentence has beyond what the brief describes keeps its own
    # size, scaled down by whatever the mix already spent.
    mixed.extend(value * (1.0 - share) for value in authored[len(paired):])
    total = sum(mixed) or 1.0
    return tuple(value / total for value in mixed)


# 「청사 등의 표준 설계면적 기준」. Korean public procurement does not hand an
# architect a room schedule someone invented - it computes one, and the
# 설계공모지침서 for 파주 법원읍 prints the formulae in a column beside the
# areas. Reproducing them here means a brief can be generated from a staff
# count rather than transcribed.
#
# Checked against a document that was not used to write them: 효돈동's issued
# schedule gives its 민원실 as 150.0 m², and the formula returns 150.1.
DESK_M2_PER_STAFF = 7.2
DESK_M2_PER_TEAM_LEADER = 7.65
HEAD_OFFICE_M2 = 23.0
COUNTER_M2_PER_STAFF = 6.55
COUNTER_CIRCULATION = 1.1
COUNTER_M2_PER_VISITOR = 0.15
CANTEEN_M2_PER_HEAD = 1.63
CANTEEN_SITTINGS = 0.3
LOUNGE_M2_PER_HEAD = 2.0
LOUNGE_SHARE = 0.15
ARCHIVE_M2_PER_HEAD = 0.4
STORE_M2_PER_HEAD = 0.85
SERVER_M2_PER_KEEPER = 9.79
SERVER_CIRCULATION = 1.2
PLANT_SHARE_UNDER_3000 = 0.045
# 공용면적 = (직무 + 부속 + 설비) × 30~40%. Note this is a share of the NET,
# not of the gross - the same "30%" written against 연면적 in 효돈동's brief
# means a different building, and mixing the two is the difference between a
# 76.9% and a 70.0% net-to-gross.
SHARED_SHARE_OF_NET = 0.30


def _meeting_room_m2_per_head(people: int) -> float:
    """회의실 원단위. Larger rooms need less floor a head, as the table says."""

    if people < 25:
        return 2.4
    if people < 50:
        return 1.5
    if people < 100:
        return 1.2
    if people < 150:
        return 1.0
    return 0.9


def _lavatory_m2_per_head(people: int) -> float:
    if people < 100:
        return 0.43
    if people < 200:
        return 0.40
    return 0.33


def civic_centre_schedule(
    *,
    name: str = "행정복지센터",
    staff: int = 25,
    team_leaders: int = 5,
    counter_staff: int = 20,
    daily_visitors: int = 200,
    meeting_seats: int = 31,
    hall_m2: float = 180.0,
    programme_rooms_m2: float = 180.0,
) -> Schedule:
    """Compute a 행정복지센터 brief the way a Korean procurement office does.

    Everything except the two community rooms comes off a head count. The hall
    and the programme rooms do not, because nothing in the standard sizes them
    - 파주 gave its 다목적강당 180 m² and its 문화교실 100+80, and the reason
    written beside them is simply "3개 청사 사례".
    """

    people = staff + team_leaders + 1
    rooms = [
        Room("동장실", HEAD_OFFICE_M2, zone="private"),
        Room("직원실(팀장)", DESK_M2_PER_TEAM_LEADER * team_leaders, zone="private"),
        Room("직원실", DESK_M2_PER_STAFF * staff, zone="private"),
        Room(
            "종합민원실",
            COUNTER_M2_PER_STAFF * counter_staff * COUNTER_CIRCULATION
            + COUNTER_M2_PER_VISITOR * daily_visitors * 0.5,
            zone="public",
            needs_ground=True,
            note=f"{{6.55×{counter_staff}×1.1}}+{{0.15×{daily_visitors}×0.5}}",
        ),
        Room(
            "회의실",
            _meeting_room_m2_per_head(meeting_seats) * meeting_seats,
            zone="shared",
        ),
        Room("식당", CANTEEN_M2_PER_HEAD * people * CANTEEN_SITTINGS, zone="private"),
        Room("휴게실", LOUNGE_M2_PER_HEAD * people * LOUNGE_SHARE, zone="private"),
        Room("자료실", ARCHIVE_M2_PER_HEAD * people, kind="service", zone="service"),
        Room("창고", STORE_M2_PER_HEAD * people, kind="service", zone="service"),
        Room(
            "전산실",
            SERVER_M2_PER_KEEPER * SERVER_CIRCULATION,
            kind="service",
            zone="service",
        ),
        Room("다목적강당", hall_m2, kind="large_span", zone="public"),
        Room("문화교실", programme_rooms_m2 / 2.0, count=2, zone="public"),
    ]
    net = sum(room.total_m2 for room in rooms)
    rooms.append(Room(
        "화장실",
        _lavatory_m2_per_head(daily_visitors) * daily_visitors,
        kind="service",
        zone="service",
        note=f"{_lavatory_m2_per_head(daily_visitors)}㎡×{daily_visitors}명",
    ))
    rooms.append(Room(
        "공조기계실",
        net * PLANT_SHARE_UNDER_3000,
        kind="service",
        zone="service",
        note="연면적 3,000㎡ 이하 구간 4.5%",
    ))

    return Schedule(
        name=name,
        rooms=tuple(rooms),
        building_type="업무시설",
        notes=(
            "「청사 등의 표준 설계면적 기준」 산식으로 생성",
            f"공용면적은 순면적의 {SHARED_SHARE_OF_NET:.0%} (연면적 대비가 아님)",
            "화장실 귀속: 부속공간이 아니라 서비스로 계상 — 자료마다 다르므로 고정함",
        ),
    )


# Where the large room ended up. Korean practice treats this as a discrete
# choice rather than a continuum - the research found the hall at the top in
# three of the winners studied, in the base in three more, in a separate volume
# in others, and underground in none of twelve - and it is the decision that
# settles the massing once a brief has one big room in it.
#
# The fourth documented option, burying the volume in a slope, is not listed
# here because this package has no terrain to bury it in. Saying so is better
# than inventing a category nothing can be classified into.
LARGE_SPAN_STRATEGIES = ("detached", "base", "middle", "crown")


def large_span_strategy(source, *, storey_height_m: float) -> str:
    """Which of the four the delivered mass actually chose.

    Read off the biggest volume, because with a brief attached that is the one
    the schedule gave the hall to.
    """

    volumes = list(getattr(source, "volumes", ()) or ())
    if not volumes:
        return "base"
    height = float(source.metadata.get("authored_height_m") or 0.0)
    if height <= 0.0:
        return "base"

    # By volume, not by plan area. `stack` overlaps its tiers by 2% to avoid a
    # degenerate boolean, and the compiler cuts that overlap out as a band a
    # tenth of a metre thick - which has almost the full plan area of the tier
    # it came from. Picking on area alone chose those slivers as the hall, and
    # a sliver sits at a tier boundary, so every stacked scheme classified as
    # `middle` and no sentence in 888 could reach `crown`.
    hall = max(
        volumes,
        key=lambda v: float(v.footprint.area)
        * max(0.0, v.top_fraction - v.bottom_fraction),
    )

    # 별동 means a volume standing apart at its own level, not a fragment
    # floating free. SMR's workshop and studies are separate blocks with a yard
    # between them; 우암동's are joined by a walking deck. Defined as "touches
    # nothing at all", the category was unreachable by construction - every one
    # of the twenty-four candidates that reached it was refused by the
    # connectivity gate as "2 separate bodies not one building", and the cell
    # stood empty with candidates in it. Two rules of my own contradicting each
    # other.
    #
    # So: apart from what stands beside it, while the building as a whole is
    # still one, which the connectivity gate has already guaranteed by the time
    # anything is classified.
    beside = [
        v for v in volumes
        if v is not hall
        and v.bottom_fraction < hall.top_fraction - 1e-6
        and v.top_fraction > hall.bottom_fraction + 1e-6
    ]
    if beside and not any(v.footprint.intersects(hall.footprint) for v in beside):
        return "detached"

    low = hall.bottom_fraction * height
    high = hall.top_fraction * height
    storey = max(storey_height_m, 0.5)
    if low <= storey * 0.5:
        return "base"
    if high >= height - storey * 0.5:
        return "crown"
    return "middle"


def resized_to(form, schedule: Schedule, *, weight: float, storey_height_m: float = 3.0):
    """Give the sentence's volumes the sizes the brief asks for.

    The composition is untouched: every volume keeps its place, its height and
    its neighbours, and only its plan is scaled about its own centre until the
    volumes stand in the proportions the schedule implies. That is the division
    the two tracks were meant to have - the parti still says which operations
    and where they aim, and the brief says how much of the building each one
    holds.

    Ordered largest-first before matching, because the schedule's own order is
    largest-first: a 400 m² hall is the biggest thing in the brief and should
    land on the biggest thing in the sentence rather than on whichever volume
    happens to be written first.
    """

    from backend.app.modules.design.generation.maas.massv2.legal_fit import _scaled_in_plan

    placements = list(form.placements)
    additive = [
        (index, item) for index, item in enumerate(placements)
        if item.kind == "additive"
    ]
    if not additive or weight <= 0.0:
        return form

    def size_of(item):
        corners = item.corners()
        xs = [x for x, _y, _z in corners]
        ys = [y for _x, y, _z in corners]
        low, high = item.z_span()
        return (max(xs) - min(xs)) * (max(ys) - min(ys)) * max(0.0, high - low)

    sizes = [size_of(item) for _index, item in additive]
    total = sum(sizes) or 1.0
    current = tuple(value / total for value in sizes)

    order = sorted(range(len(additive)), key=lambda i: sizes[i], reverse=True)
    wanted = volume_shares(schedule, pieces=len(additive))
    if not wanted:
        return form
    # Match the brief's largest to the sentence's largest.
    aligned = [0.0] * len(additive)
    for rank, position in enumerate(order):
        aligned[position] = wanted[rank] if rank < len(wanted) else 0.0
    if sum(aligned) <= 0.0:
        return form

    target = blended(current, tuple(aligned), weight=weight)

    from dataclasses import replace as _replace

    for slot, (index, item) in enumerate(additive):
        share = target[slot] if slot < len(target) else current[slot]
        if current[slot] <= 1e-9 or share <= 1e-9:
            continue
        # Plan only: the schedule says how much floor a room needs, and height
        # is the storey count, which the legal fit and the growth loop own.
        factor = (share / current[slot]) ** 0.5
        corners = item.corners()
        xs = [x for x, _y, _z in corners]
        ys = [y for _x, y, _z in corners]
        centre = ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
        placements[index] = _scaled_in_plan(item, factor, centre)

    # A stacked volume rides its carrier. Each volume scaled about its OWN
    # centre, and two volumes shrink by different factors - so an upper unit
    # that bore on a lower one keeps its authored world position while its
    # carrier contracts out from under it, and the brief-resize delivered
    # knife bearings and floaters. The old rule applies: an attachment rides
    # its owner - the upper's centre moves with the carrier's frame
    # (carrier_centre + carrier_factor * authored_offset), bottom-up so a
    # chain rides all the way down. Heights stay untouched; this is plan.
    from shapely.geometry import Polygon as _Polygon

    def _footprint(item):
        corners = item.corners()
        low = item.z_span()[0]
        ring = [(x, y) for x, y, z in corners if abs(z - low) < 1e-6]
        return _Polygon(ring).convex_hull if len(ring) >= 3 else None

    def _centre(item):
        corners = item.corners()
        xs = [x for x, _y, _z in corners]
        ys = [y for _x, y, _z in corners]
        return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)

    factor_of = {}
    for slot, (index, item) in enumerate(additive):
        share = target[slot] if slot < len(target) else current[slot]
        if current[slot] > 1e-9 and share > 1e-9:
            factor_of[index] = (share / current[slot]) ** 0.5

    from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, translation_matrix4, validate_matrix4

    order_up = sorted((index for index, _item in additive),
                      key=lambda i: form.placements[i].z_span()[0])
    for index in order_up:
        original = form.placements[index]
        base = original.z_span()[0]
        plan = _footprint(original)
        if plan is None:
            continue
        carriers = [
            (other, _footprint(form.placements[other]))
            for other in order_up
            if other != index
            and abs(form.placements[other].z_span()[1] - base) <= 1e-3
        ]
        carriers = [
            (other, plan.intersection(fp).area)
            for other, fp in carriers if fp is not None and fp.intersects(plan)
        ]
        if not carriers:
            continue
        owner = max(carriers, key=lambda pair: pair[1])[0]
        owner_was = _centre(form.placements[owner])
        # Where the owner IS, not where it was authored: bottom-up order
        # means a mid-chain carrier has already ridden its own carrier, and
        # the offset is measured in the authored frame but planted on the
        # owner's delivered centre.
        owner_now = _centre(placements[owner])
        owner_factor = factor_of.get(owner, 1.0)
        authored = _centre(original)
        wanted_centre = (
            owner_now[0] + owner_factor * (authored[0] - owner_was[0]),
            owner_now[1] + owner_factor * (authored[1] - owner_was[1]),
        )
        now = _centre(placements[index])
        dx, dy = wanted_centre[0] - now[0], wanted_centre[1] - now[1]
        if abs(dx) > 1e-6 or abs(dy) > 1e-6:
            # compose_matrix4 runs in program order (first argument first), so
            # the volume's own matrix goes first and the WORLD translation
            # second - the other order fed dx into the volume's local axes and
            # the matrix's tens-of-metres scale flung a terrace 400 m off site.
            moved = compose_matrix4(
                placements[index].matrix, translation_matrix4((dx, dy, 0.0)))
            placements[index] = _replace(
                placements[index], matrix=validate_matrix4(moved))

    # Tell the growth loop a brief exists and how large it asks the building to
    # be. Without this it grows toward the statutory ceiling, which is a
    # ceiling and not a target - and overshooting the 면적표 by more than five
    # percent costs marks before a juror has looked at the drawing.
    extra = {**dict(form.extra), "programme_target": schedule.gross_m2}
    return _replace(form, placements=tuple(placements), extra=extra)



__all__ = [
    "CLEAR_HEIGHT_M",
    "GROSS_UP",
    "Room",
    "Schedule",
    "blended",
    "resized_to",
    "schedule_from_record",
    "volume_shares",
]
