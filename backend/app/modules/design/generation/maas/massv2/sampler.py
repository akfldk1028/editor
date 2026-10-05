"""Draw sentences from the parcel instead of writing them by hand.

Seventy-six sentences was the whole vocabulary, and every one of them was
written against one parcel's facts - a skewed 2,500 m² plot that affords 4.2
storeys. Run on a 497 m² commercial site that affords sixteen, they filled ten
of the sixteen grid cells and their stated reasons were about a low building.
The masses adapted because the executor owns the metres; the reasoning did not,
because a person wrote it about somewhere else.

So the sentence is generated too. Not the geometry - that is still the
executor's, and not the syntax - that is still the corpus's. What is generated
is the choice: which operations, aimed at what, and why on this parcel. Every
magnitude here is read off the site (storeys the limits afford, how skewed the
plot is, how many boundaries a neighbour is already built against) and every
`why` quotes the number it came from, so a sentence is true where it was drawn
and nowhere else by accident.

This is the "sample more, reflect less" half of the harness. The literature is
consistent that for open-ended quality no critique loop beats simply drawing
more candidates against a sound verifier at equal budget, and the verifier here
- legal fit, physics, connectivity - is the part of this system that already
works.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Iterator

from backend.app.modules.design.generation.maas.massv2.grammar import MAX_OFFSET_RATIO, MIN_OFFSET_RATIO, MIN_TIER_CONTRAST


# The frame is already turned to the parcel's open side, so a direction is a
# name relative to that: `open` runs toward it, `back` away from it into the
# neighbours, `cross` runs along the short axis.
_AIMS = ("open", "back", "cross")
_AIM_KOREAN = {"open": "열린 면", "back": "이웃에 막힌 뒷면", "cross": "짧은 축"}


@dataclass(frozen=True)
class SiteFacts:
    """What the parcel says about itself, in the numbers a sentence can cite."""

    storeys_allowed: float
    bcr_limit_pct: float
    far_limit_pct: float
    parcel_area_m2: float
    buildable_m2: float
    skew: float
    party_edges: int
    open_side: str

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.massv2_site_facts.v1",
            "storeys_allowed": round(self.storeys_allowed, 2),
            "bcr_limit_pct": round(self.bcr_limit_pct, 1),
            "far_limit_pct": round(self.far_limit_pct, 1),
            "parcel_area_m2": round(self.parcel_area_m2, 1),
            "skew": round(self.skew, 3),
            "party_edges": self.party_edges,
            "open_side": self.open_side,
        }


def read_facts(site) -> SiteFacts:
    """Measure the parcel. Nothing here is a constant from somewhere else."""

    buildable = site.plan_at(0.0)
    buildable_area = float(buildable.area) if buildable is not None else 0.0
    box = float(buildable.minimum_rotated_rectangle.area) if buildable is not None else 0.0
    parcel = site.parcel_area_m2
    return SiteFacts(
        storeys_allowed=site.far_capacity_m2 / max(site.ground_capacity_m2, 1e-9),
        bcr_limit_pct=site.ground_capacity_m2 / max(parcel, 1e-9) * 100.0,
        far_limit_pct=site.far_capacity_m2 / max(parcel, 1e-9) * 100.0,
        parcel_area_m2=parcel,
        buildable_m2=buildable_area,
        # How much of its own bounding box the buildable area actually is. A
        # low number means an imposed figure will lose its corners to the
        # boundary, which is a reason to inherit the plot instead.
        skew=buildable_area / box if box > 1e-9 else 1.0,
        party_edges=len(site.shared_edges),
        open_side=(
            "한 면" if len(site.shared_edges) >= 3
            else "두 면" if len(site.shared_edges) == 2
            else "여러 면"
        ),
    )


def _tier_counts(facts: SiteFacts) -> tuple[int, ...]:
    """How many tiers this parcel can carry without each becoming a sliver.

    용적률 ÷ 건폐율 again - the number that bounds slenderness and stops the
    growth loop. A parcel affording four storeys cannot read as six tiers; one
    affording sixteen has room for more than three.
    """

    ceiling = int(max(2, min(6, round(facts.storeys_allowed / 1.6))))
    return tuple(range(2, ceiling + 1)) or (2,)


def _object_counts(facts: SiteFacts) -> tuple[int, ...]:
    """A field needs ground. On a small plot its objects become sticks."""

    if facts.buildable_m2 < 400.0:
        return (2, 3)
    if facts.buildable_m2 < 900.0:
        return (3, 4)
    return (4, 5, 6)


def _why_extrude(facts: SiteFacts, share: float) -> str:
    return (
        f"이 필지는 용적률÷건폐율로 {facts.storeys_allowed:.1f}층을 허용한다 — "
        f"부피는 한 덩어리로 잡고 높이의 {share:.0%}만 쓴다."
    )


def _why_stack(facts: SiteFacts, count: int, contrast: float, align: str) -> str:
    return (
        f"{facts.storeys_allowed:.1f}층이 허용되므로 {count}단으로 나눈다. "
        f"각 단은 {contrast:.2f}배씩 작아지고 {_AIM_KOREAN[align]}을 붙잡는다 — "
        f"네 면이 동시에 물러나면 셋백 규정이 만든 웨딩케이크지 건축가가 그린 형태가 아니다."
    )


def _why_split(facts: SiteFacts, ratio: float, along: str) -> str:
    return (
        f"{_AIM_KOREAN[along]} 방향으로 {ratio:.0%} 대 {1 - ratio:.0%}로 가른다. "
        f"대등한 두 덩어리는 실작품에 한 번도 없으므로 불균등하게."
    )


def _why_shear(facts: SiteFacts, ratio: float, toward: str) -> str:
    return (
        f"위 볼륨을 {_AIM_KOREAN[toward]} 쪽으로 자기 평면깊이의 {ratio:.2f}만큼 민다 — "
        f"절대치가 아니라 비율이라 대지가 바뀌면 이동량도 바뀐다."
    )


def _why_carve(facts: SiteFacts, size: float, at: str) -> str:
    if at == "back":
        return (
            f"이웃이 붙은 변이 {facts.party_edges}개다. 막힌 뒷면에 평면의 {size:.0%}를 "
            f"파서 그쪽 실의 채광을 만든다."
        )
    return (
        f"{_AIM_KOREAN[at]}에서 평면의 {size:.0%}를 파낸다 — "
        f"판 방향과 열린 방향을 같게 해 중정이 바깥과 이어지게."
    )


def _why_lift(facts: SiteFacts, clearance: float) -> str:
    return (
        f"건폐율 한도가 {facts.bcr_limit_pct:.0f}%라 지면을 비워도 층수로 되찾을 수 있다. "
        f"높이의 {clearance:.0%}를 비워 {facts.open_side}뿐인 접근을 필지 안쪽까지 들인다."
    )


def _why_loop(facts: SiteFacts, bar: float) -> str:
    return (
        f"평면 깊이의 {bar:.0%}짜리 바 넷이 중정을 감싼다. 구멍 뚫린 한 덩어리가 아니라 "
        f"만나는 링이라 추력이 반대편 다리로 돌아간다."
    )


def _why_aggregate(facts: SiteFacts, count: int) -> str:
    return (
        f"건폐 가능 면적 {facts.buildable_m2:.0f} m²에 크기가 서로 다른 {count}개를 놓고 "
        f"한 판이 묶는다 — 같은 크기로 반복하면 막사가 된다. 필드는 누워서 면적을 번다."
    )


def _base_moves(facts: SiteFacts) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """How the mass first arrives. Everything else acts on what is standing."""

    for share in (0.72, 0.9):
        yield f"body{int(share * 100)}", [
            {"op": "extrude", "height": share, "why": _why_extrude(facts, share)}
        ]
    for count, align in product(_tier_counts(facts), ("open", "back")):
        contrast = MIN_TIER_CONTRAST + 0.1
        yield f"stack{count}{align}", [{
            "op": "stack", "n": count, "contrast": contrast, "align": align,
            "height": 0.95, "why": _why_stack(facts, count, contrast, align),
        }]
    for bar in (0.22, 0.3):
        yield f"ring{int(bar * 100)}", [
            {"op": "loop", "bar": bar, "height": 0.9, "why": _why_loop(facts, bar)}
        ]
    for count in _object_counts(facts):
        yield f"field{count}", [{
            "op": "aggregate", "n": count, "spread": 1.7, "height": 0.8, "tie": 0.18,
            "why": _why_aggregate(facts, count),
        }]


def _cuts(facts: SiteFacts) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Divide first, so later verbs have somewhere to aim that is not everywhere."""

    yield "whole", []
    for ratio, along in product((0.62, 0.7), ("open", "cross")):
        yield f"split{int(ratio * 100)}{along}", [{
            "op": "split", "ratio": ratio, "along": along,
            "first": "fore", "second": "aft", "gap": 0.0,
            "why": _why_split(facts, ratio, along),
        }]


def _modifiers(facts: SiteFacts) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """The move that makes it this building rather than a lawful volume.

    Unscoped first. A verb that reaches everything standing is still a sentence
    - `stack` then `shear` is a shifted stack - and emitting only scoped moves
    left every draw needing a `split` to say anything, which silently deleted
    the whole undivided half of the grammar.
    """

    for scope in (None, "fore", "aft"):
        tag = f"@{scope}" if scope else ""
        for ratio, toward in product((MIN_OFFSET_RATIO + 0.11, MAX_OFFSET_RATIO), _AIMS):
            op = {"op": "shear", "ratio": ratio, "toward": toward,
                  "why": _why_shear(facts, ratio, toward)}
            if scope:
                op["on"] = scope
            yield f"shear{toward}{tag}", [op]
        for clearance in (0.18, 0.3):
            op = {"op": "lift", "clearance": clearance, "why": _why_lift(facts, clearance)}
            if scope:
                op["on"] = scope
            yield f"lift{int(clearance * 100)}{tag}", [op]
        for ratio in (0.62, 0.78):
            op = {"op": "taper", "ratio": ratio,
                  "why": f"맨 위를 {ratio:.0%}로 줄여 하늘로 갈수록 가늘어지게 한다."}
            if scope:
                op["on"] = scope
            yield f"taper{int(ratio * 100)}{tag}", [op]


def _voids(facts: SiteFacts) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """`carve` reaches the whole mass, so it is not scoped - it is a room taken
    out of the building, aimed at a side."""

    yield "closed", []
    for size, at in product((0.24, 0.36), _AIMS):
        yield f"carve{at}", [{
            "op": "carve", "size": size, "at": at, "reach": 0.55,
            "why": _why_carve(facts, size, at),
        }]


_LANGUAGE = {
    "loop": ("open_figure", "ring"),
    "aggregate": ("porous_field", "objects under one plate"),
    "lift": ("open_figure", "released ground"),
    "carve": ("carved_body", "court"),
}


def _language(ops: list[dict[str, Any]]) -> tuple[str, str]:
    verbs = {op["op"] for op in ops}
    for verb, pair in _LANGUAGE.items():
        if verb in verbs:
            return pair
    return ("solid_body", "one worked mass")


def _interleave(groups: list[list[Any]]) -> list[Any]:
    """Round-robin several ordered groups into one, so a prefix covers them all."""

    pools = [list(group) for group in groups]
    out: list[Any] = []
    while any(pools):
        for pool in pools:
            if pool:
                out.append(pool.pop(0))
    return out


def sample_sentences(facts: SiteFacts, *, limit: int = 200) -> list[dict[str, Any]]:
    """Enumerate the grammar against this parcel, deterministically.

    Enumerated rather than drawn at random so a rerun on the same parcel gives
    the same vocabulary, and interleaved rather than taken in order so that a
    truncated run is still spread across the families instead of being all
    stacks.
    """

    buckets: dict[str, list[dict[str, Any]]] = {}
    for (base_tag, base), (cut_tag, cut), (mod_tag, mod), (void_tag, void) in product(
        _base_moves(facts), _cuts(facts), _modifiers(facts), _voids(facts)
    ):
        ops = base + cut + mod + void
        # A modifier aimed at a part the sentence never cut is silent by
        # design, and a silent sentence is the base mass again.
        if any(op.get("on") for op in mod) and not cut:
            continue
        primary, secondary = _language(ops)
        name = f"sampled_{base_tag}_{cut_tag}_{mod_tag}_{void_tag}".replace("@", "_at_")
        # Bucketed by how the mass arrives and whether it was divided, not only
        # by what it does about void. `product` varies its first iterable
        # slowest, so one base move owns hundreds of consecutive combinations:
        # round-robining on void alone drew every sentence from `extrude`, and
        # leaving the cut out of the key drew all but 6% of them undivided.
        buckets.setdefault((primary, base_tag, cut_tag), []).append({
            "name": name,
            "primary_language": primary,
            "secondary_language": secondary,
            "formal_principle": f"{base_tag} · {cut_tag} · {mod_tag} · {void_tag}",
            "reference_basis": "sampled from the parcel",
            "ops": ops,
        })

    # Lay the buckets out so every axis alternates before any of them repeats.
    # Taking them in key order instead means whichever axis sorts first owns
    # the front of the draw: sorted keys gave sixteen carved bodies, and
    # sorting inside a language gave forty `extrude` sentences with no `stack`
    # or `loop` among them.
    nested: dict[str, dict[str, list[list[dict[str, Any]]]]] = {}
    for (primary, base_tag, _cut), items in sorted(buckets.items()):
        nested.setdefault(primary, {}).setdefault(base_tag, []).append(items)

    lanes = [
        iter(bucket)
        for bucket in _interleave([
            _interleave([bases[base] for base in sorted(bases)])
            for _language, bases in sorted(nested.items())
        ])
    ]

    ordered: list[dict[str, Any]] = []
    while lanes and len(ordered) < limit:
        for lane in list(lanes):
            item = next(lane, None)
            if item is None:
                lanes.remove(lane)
                continue
            ordered.append(item)
            if len(ordered) >= limit:
                break
    return ordered


__all__ = ["SiteFacts", "read_facts", "sample_sentences"]
