from backend.app.core.geometry.access import (
    bounding_box_aspect_ratio,
    orthogonal_min_width,
    shared_boundary_segments,
)
from backend.app.core.geometry.distance import segment_to_segment_distance
from backend.app.core.geometry.polygon import (
    GEOMETRY_DECIMALS,
    snap_coordinate,
    snap_ring,
)

__all__ = [
    "GEOMETRY_DECIMALS",
    "bounding_box_aspect_ratio",
    "orthogonal_min_width",
    "segment_to_segment_distance",
    "shared_boundary_segments",
    "snap_coordinate",
    "snap_ring",
]
