"""The axes an architect chooses along.

The pipeline's job is not to return the best mass. It is to return a spread an
architect can choose from, and a spread only exists if the axes it spreads over
are ones that show up in the delivered building.

Today's portfolio already enforces a spread - it requires six BOOK base volume
scopes to be filled - but that axis is an authoring abstraction and does not
survive into the form. Measured on PNU 4115011300106840001: all six scopes
delivered masses with hierarchy 0.66-0.77 and, more tellingly, 67 percent of
128 masses sat within one percent of the coverage cap, median exactly 1.000.
Every candidate fills the plan to the legal maximum, so every silhouette is the
same envelope and the operative only ruffles its surface.

Filling the plan is one proposal among many, not the answer. A scheme that
holds a courtyard, or spreads thin pavilions over a low footprint, is a
different proposal - and today it cannot even be built, because plan area is
derived from floor area rather than chosen, so it is always maximal.

This package names the axes explicitly so they can be spread over.
"""

from backend.app.modules.design.generation.maas.design_space.axes import COVERAGE_BANDS, CoverageBand, capacities_under_band, coverage_band, delivered_ground_take_band, delivered_stature_band, delivered_void_band, coverage_band_ids, plan_area_for_band, STATURE_BANDS, StatureBand, stature_band_ids, VOID_BANDS, VoidBand, void_band, void_band_ids

__all__ = [
    "COVERAGE_BANDS",
    "CoverageBand",
    "capacities_under_band",
    "coverage_band",
    "delivered_ground_take_band",
    "delivered_stature_band",
    "delivered_void_band",
    "STATURE_BANDS",
    "StatureBand",
    "stature_band_ids",
    "VOID_BANDS",
    "VoidBand",
    "void_band",
    "void_band_ids",
    "coverage_band_ids",
    "plan_area_for_band",
]
