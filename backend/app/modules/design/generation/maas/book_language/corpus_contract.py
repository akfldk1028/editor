"""Page-faithful structural contract for the 69-page architectural BOOK.

This module contains evidence transcribed from the scanned pages only.  It is
deliberately separate from the executable registry: changing search policy or
compiler behaviour must not silently rewrite what the source book says.
"""

from __future__ import annotations

from dataclasses import dataclass


BOOK_PAGE_COUNT = 69
BOOK_VARIATION_COUNT = 11
BOOK_ORIENTATIONS = ("long_axis", "short_axis", "vertical")
BASE_VOLUME_FRACTIONS: tuple[tuple[str, float], ...] = (
    ("1/1", 1.0),
    ("3/8", 3.0 / 8.0),
    ("1/2", 1.0 / 2.0),
    ("1/4", 1.0 / 4.0),
    ("1/8", 1.0 / 8.0),
    ("1/16", 1.0 / 16.0),
)


@dataclass(frozen=True)
class BaseOperative:
    verb: str
    page: int
    transformation: str
    cardinality: str

    @property
    def principle_id(self) -> str:
        return f"book:operative:{self.verb}"


@dataclass(frozen=True)
class CombinationContract:
    page: int
    first: str
    second: str


@dataclass(frozen=True)
class AggregationContract:
    page: int
    methods: tuple[str, ...]
    operative: str

    @property
    def execution_verbs(self) -> tuple[str, ...]:
        # BOOK headings put the aggregation method first, but the diagrams
        # execute the operative before the aggregation method.
        return (self.operative, *self.methods)


@dataclass(frozen=True)
class CaseStudyContract:
    page: int
    project: str
    verbs: tuple[str, ...]
    implementation_elements: tuple[str, str, str]

    @property
    def label(self) -> str:
        return f"{self.project} | {' + '.join(verb.title() for verb in self.verbs)}"


BASE_OPERATIVES: tuple[BaseOperative, ...] = (
    BaseOperative("expand", 6, "add", "single"),
    BaseOperative("extrude", 7, "add", "single"),
    BaseOperative("inflate", 8, "add", "single"),
    BaseOperative("branch", 9, "add", "multiple"),
    BaseOperative("merge", 10, "add", "multiple"),
    BaseOperative("nest", 11, "add", "multiple"),
    BaseOperative("offset", 12, "add", "multiple"),
    BaseOperative("bend", 14, "displace", "single"),
    BaseOperative("skew", 15, "displace", "single"),
    BaseOperative("split", 16, "displace", "single"),
    BaseOperative("twist", 17, "displace", "single"),
    BaseOperative("interlock", 18, "displace", "multiple"),
    BaseOperative("intersect", 19, "displace", "multiple"),
    BaseOperative("lift", 20, "displace", "multiple"),
    BaseOperative("lodge", 21, "displace", "multiple"),
    BaseOperative("overlap", 22, "displace", "multiple"),
    BaseOperative("rotate", 23, "displace", "multiple"),
    BaseOperative("shift", 24, "displace", "multiple"),
    BaseOperative("carve", 26, "subtract", "single"),
    BaseOperative("compress", 27, "subtract", "single"),
    BaseOperative("fracture", 28, "subtract", "single"),
    BaseOperative("grade", 29, "subtract", "single"),
    BaseOperative("notch", 30, "subtract", "single"),
    BaseOperative("pinch", 31, "subtract", "single"),
    BaseOperative("shear", 32, "subtract", "single"),
    BaseOperative("taper", 33, "subtract", "single"),
    BaseOperative("embed", 34, "subtract", "multiple"),
    BaseOperative("extract", 35, "subtract", "multiple"),
    BaseOperative("inscribe", 36, "subtract", "multiple"),
    BaseOperative("puncture", 37, "subtract", "multiple"),
)


COMBINATION_CONTRACTS: tuple[CombinationContract, ...] = tuple(
    CombinationContract(*record) for record in (
        (39, "inscribe", "inscribe"), (39, "intersect", "intersect"),
        (40, "split", "split"), (40, "embed", "embed"),
        (41, "taper", "taper"), (41, "bend", "bend"),
        (42, "branch", "branch"), (42, "expand", "expand"),
        (43, "shift", "shift"), (43, "notch", "notch"),
        (44, "inscribe", "intersect"), (44, "intersect", "split"),
        (45, "split", "embed"), (45, "embed", "taper"),
        (46, "taper", "bend"), (46, "bend", "branch"),
        (47, "branch", "expand"), (47, "expand", "shift"),
        (48, "shift", "notch"), (48, "notch", "twist"),
    )
)


AGGREGATION_CONTRACTS: tuple[AggregationContract, ...] = tuple(
    AggregationContract(page, methods, operative) for page, methods, operative in (
        (50, ("reflect",), "expand"),
        (51, ("reflect", "pack"), "skew"),
        (52, ("pack",), "inflate"),
        (53, ("pack", "stack"), "branch"),
        (54, ("stack",), "bend"),
        (55, ("array", "stack"), "rotate"),
        (56, ("array",), "taper"),
        (57, ("join", "array"), "pinch"),
        (58, ("join",), "split"),
    )
)


CASE_STUDY_CONTRACTS: tuple[CaseStudyContract, ...] = (
    CaseStudyContract(60, "Poli House", ("carve", "offset"), (
        "Offset Program", "Perimeter Services", "Punctured Openings",
    )),
    CaseStudyContract(61, "Villa 1", ("embed", "branch"), (
        "Branched Programs", "Volume Wrapper", "Embedded Entry",
    )),
    CaseStudyContract(62, "Casa para un Carpintero", ("embed", "overlap"), (
        "Overlapping Program", "Circulation Core", "Embedded Entry",
    )),
    CaseStudyContract(63, "House N", ("expand", "nest"), (
        "Expanded Outer Volume", "Nested Private Program", "Nested Living + Dining",
    )),
    CaseStudyContract(64, "House in Minamimachi 2", ("overlap", "expand"), (
        "Overlapping Light Wells", "Stacked Program", "Expanded Volumes",
    )),
    CaseStudyContract(65, "Nursing Home", ("bend", "shift"), (
        "Shifted Volumes", "Bent Massing", "Embedded Massing",
    )),
    CaseStudyContract(66, "Leimondo Nursery School", ("embed", "taper"), (
        "Tapered Volumes", "Thickened Roof", "Embedded Program",
    )),
    CaseStudyContract(67, "Gouveia Law Courts", ("lift", "carve"), (
        "Carved Massing", "Lifted Program", "Carved Plinth",
    )),
    CaseStudyContract(68, "Carabanchel Housing", ("lift", "extrude"), (
        "Extruded Living Spaces", "Lifted Massing", "Carved Plinth",
    )),
    CaseStudyContract(69, "Ironbank", ("overlap", "rotate"), (
        "Rotated Volumes", "Stacked Utility and Circulation Cores", "Plinth and Street Facade",
    )),
)


# Compatibility tuple views for existing audits and callers.
COMBINATIONS = tuple((item.page, item.first, item.second) for item in COMBINATION_CONTRACTS)
AGGREGATIONS = tuple((item.page, item.methods, item.operative) for item in AGGREGATION_CONTRACTS)
CASE_STUDIES = tuple((item.page, item.label, item.verbs) for item in CASE_STUDY_CONTRACTS)
BOOK_EXECUTABLE_PRINCIPLE_COUNT = (
    len(BASE_OPERATIVES)
    + len(COMBINATION_CONTRACTS)
    + len(AGGREGATION_CONTRACTS)
    + len(CASE_STUDY_CONTRACTS)
)
BOOK_COMPOSITION_PATH_COUNT = (
    len(BASE_VOLUME_FRACTIONS)
    * len(BOOK_ORIENTATIONS)
    * BOOK_VARIATION_COUNT
    * BOOK_EXECUTABLE_PRINCIPLE_COUNT
)


PAGE_SECTIONS: tuple[tuple[range, str], ...] = (
    (range(1, 3), "introduction"),
    (range(3, 4), "base_volume"),
    (range(4, 6), "operative_index"),
    (range(6, 13), "base_operative"),
    # pp.13 and 25 continue the taxonomy tree before the Displace and
    # Subtract operative leaves. They are not operative result pages.
    (range(13, 14), "operative_index"),
    (range(14, 25), "base_operative"),
    (range(25, 26), "operative_index"),
    (range(26, 38), "base_operative"),
    (range(38, 39), "combination_index"),
    (range(39, 49), "combination"),
    (range(49, 50), "aggregation_index"),
    (range(50, 59), "aggregation"),
    (range(59, 60), "case_study_index"),
    (range(60, 70), "case_study"),
)


def page_section(page: int) -> str:
    return next(section for pages, section in PAGE_SECTIONS if page in pages)


__all__ = [
    "AGGREGATIONS", "AGGREGATION_CONTRACTS", "BASE_OPERATIVES", "BASE_VOLUME_FRACTIONS",
    "BOOK_COMPOSITION_PATH_COUNT", "BOOK_EXECUTABLE_PRINCIPLE_COUNT",
    "BOOK_ORIENTATIONS", "BOOK_PAGE_COUNT", "BOOK_VARIATION_COUNT",
    "BaseOperative", "CASE_STUDIES", "CASE_STUDY_CONTRACTS",
    "COMBINATIONS", "COMBINATION_CONTRACTS", "PAGE_SECTIONS", "page_section",
]
