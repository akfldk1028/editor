"""Program portfolio entry hints shared by generation and reporting.

Height and floor values describe the historical smoke brief.  They are inputs
to program dimensional adaptation only and never legal/capacity authority.
"""

from typing import NamedTuple


class ProgramPortfolioHint(NamedTuple):
    slug: str
    building_type: str
    dimensional_height_hint_m: float
    occupiable_floor_hint: int


PROGRAMS = (
    ProgramPortfolioHint("neighborhood", "근린생활시설", 15.0, 5),
    ProgramPortfolioHint("gymnasium", "체육관", 18.0, 3),
    ProgramPortfolioHint("cultural", "미술관", 15.0, 4),
)


__all__ = ["PROGRAMS", "ProgramPortfolioHint"]
