"""The delivered mass keeps the program's components, only where form has them.

An authored cultural program is a composition - a gallery hall, a public hall,
an entry ramp - each with its own footprint and height band, their plan shares
landing at 0.43/0.38/0.10/0.09, inside cultural's (0.32, 0.75) hierarchy band.
What used to be delivered was one role at share 1.000 on all 128 masses.

The lobes here come from the *form*, found by eroding the delivered plan, and
the authored regions only supply their names. Splitting where an author drew a
boundary would be relabelling: any polygon can be cut anywhere.

Every rejection case below is a counterexample that broke the previous
attempt (reverted in c75ae76), which compared a shared edge with the pieces'
perimeter and could be defeated by a saw kerf, by elongation, or by rotating
the parcel.
"""

import math

from unittest import TestCase as SimpleTestCase
from shapely.affinity import rotate
from shapely.geometry import box
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.geometry_language.source_bridge import _articulated_component_parts, _articulation_cores, _component_regions_for_plan, normalized_component_layout
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceVolume


IDENTITY = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)
WEST = box(0.0, 0.0, 20.0, 20.0)
EAST = box(30.0, 0.0, 50.0, 20.0)
NECK = box(20.0, 8.0, 30.0, 12.0)
DUMBBELL = unary_union([WEST, NECK, EAST])
PLATE = box(0.0, 0.0, 50.0, 20.0)
# 0.2 m slots 6.1 m deep: 0.24% of the plan removed, still a plate.
KERFED_PLATE = PLATE.difference(unary_union([
    box(24.9, 13.9, 25.1, 20.0),
    box(24.9, 0.0, 25.1, 6.1),
]))


def _source(volumes):
    return SourceMass(
        name="component-source",
        footprint=unary_union([volume.footprint for volume in volumes]),
        volumes=tuple(volumes),
    )


def _component(role, footprint, bottom=0.0, top=1.0):
    return SourceVolume(role, footprint, bottom, top, "geometry_program")


def _two_halls(west=WEST, east=EAST):
    return _source([
        _component("west_gallery_hall", west),
        _component("east_public_hall", east),
    ])


class ArticulationIsMeasuredOnTheFormTests(SimpleTestCase):
    def _regions(self, source, *, bottom=0.0, top=0.5):
        # Placed back onto the seed's own plan, the proportional layout
        # reproduces the footprints it was read from, so these cases stay about
        # articulation rather than about the frame change.
        return _component_regions_for_plan(
            normalized_component_layout(source),
            source.footprint,
            bottom_fraction=bottom,
            top_fraction=top,
        )

    def _roles(self, part, source):
        return [
            role
            for role, _piece in _articulated_component_parts(
                part,
                self._regions(source),
                fallback_role="west_gallery_hall",
            )
        ]

    def test_two_halls_joined_by_a_neck_keep_both_roles(self):
        self.assertEqual(
            {"west_gallery_hall", "east_public_hall"},
            set(self._roles(DUMBBELL, _two_halls())),
        )

    def test_a_convex_plate_over_the_same_components_stays_one_role(self):
        self.assertEqual(["west_gallery_hall"], self._roles(PLATE, _two_halls()))

    def test_a_saw_kerf_does_not_manufacture_a_component(self):
        """0.24% of the plan removed. The previous attempt split this."""

        self.assertEqual(
            ["west_gallery_hall"],
            self._roles(KERFED_PLATE, _two_halls()),
        )

    def test_elongation_is_not_articulation(self):
        """A 16.4:1 bar split under the previous attempt with no form change."""

        bar = box(0.0, 0.0, 164.0, 10.0)
        source = _two_halls(
            west=box(0.0, 0.0, 82.0, 10.0),
            east=box(82.0, 0.0, 164.0, 10.0),
        )

        self.assertEqual(["west_gallery_hall"], self._roles(bar, source))

    def test_a_wide_opening_is_not_a_neck(self):
        wide = unary_union([WEST, box(20.0, 5.0, 30.0, 15.0), EAST])

        self.assertEqual(["west_gallery_hall"], self._roles(wide, _two_halls()))

    def test_the_answer_does_not_depend_on_parcel_orientation(self):
        """The previous attempt gave 0.634, 0.878 and one role for one body."""

        shares = []
        for angle in (0.0, 15.0, 37.0, 45.0, 90.0):
            turned = rotate(DUMBBELL, angle, origin=(0.0, 0.0))
            source = _source([
                _component("west_gallery_hall", rotate(WEST, angle, origin=(0.0, 0.0))),
                _component("east_public_hall", rotate(EAST, angle, origin=(0.0, 0.0))),
            ])
            assigned = _articulated_component_parts(
                turned,
                self._regions(source),
                fallback_role="west_gallery_hall",
            )
            self.assertEqual(2, len(assigned), f"angle={angle}")
            areas = sorted((piece.area for _role, piece in assigned), reverse=True)
            shares.append(areas[0] / sum(areas))

        self.assertLess(max(shares) - min(shares), 0.02, shares)

    def test_a_symmetric_body_is_not_decided_by_authoring_order(self):
        """51% of the plan used to follow whichever component came first."""

        source = _two_halls()
        forward = _articulated_component_parts(
            DUMBBELL, self._regions(source), fallback_role="west_gallery_hall"
        )
        reversed_source = _source(list(reversed(source.volumes)))
        backward = _articulated_component_parts(
            DUMBBELL,
            self._regions(reversed_source),
            fallback_role="west_gallery_hall",
        )

        self.assertEqual(
            {role: round(piece.area, 6) for role, piece in forward},
            {role: round(piece.area, 6) for role, piece in backward},
        )

    def test_three_lobes_keep_three_roles(self):
        form = unary_union([
            box(0.0, 0.0, 20.0, 20.0),
            box(20.0, 8.0, 30.0, 12.0),
            box(30.0, 0.0, 50.0, 20.0),
            box(50.0, 8.0, 60.0, 12.0),
            box(60.0, 0.0, 80.0, 20.0),
        ])
        source = _source([
            _component("west_gallery_hall", box(0.0, 0.0, 20.0, 20.0)),
            _component("east_public_hall", box(30.0, 0.0, 50.0, 20.0)),
            _component("entry_pavilion", box(60.0, 0.0, 80.0, 20.0)),
        ])

        self.assertEqual(3, len(set(self._roles(form, source))))

    def test_one_fat_pair_does_not_erase_the_others(self):
        """Authoring one hall as two adjacent halves used to cost both roles."""

        source = _source([
            _component("west_gallery_hall", box(0.0, 0.0, 10.0, 20.0)),
            _component("west_gallery_hall", box(10.0, 0.0, 20.0, 20.0)),
            _component("east_public_hall", EAST),
        ])

        self.assertEqual(
            {"west_gallery_hall", "east_public_hall"},
            set(self._roles(DUMBBELL, source)),
        )

    def test_the_pieces_partition_the_part_without_overlap(self):
        """Overlapping authored regions must not double-count area."""

        source = _source([
            _component("west_gallery_hall", box(0.0, 0.0, 26.0, 20.0)),
            _component("east_public_hall", box(24.0, 0.0, 50.0, 20.0)),
        ])
        assigned = _articulated_component_parts(
            DUMBBELL, self._regions(source), fallback_role="west_gallery_hall"
        )

        total = sum(piece.area for _role, piece in assigned)
        union = unary_union([piece for _role, piece in assigned])
        self.assertAlmostEqual(float(DUMBBELL.area), total, places=3)
        self.assertAlmostEqual(float(DUMBBELL.area), float(union.area), places=3)

    def test_a_component_outside_the_band_is_not_offered(self):
        source = _source([
            _component("west_gallery_hall", WEST),
            _component("entry_ramp", EAST, bottom=0.0, top=0.2),
        ])

        self.assertEqual(
            {"west_gallery_hall"},
            {role for role, _region in self._regions(source, bottom=0.5, top=1.0)},
        )


class ArticulationCoreMeasurementTests(SimpleTestCase):
    def test_convex_and_elongated_plans_have_no_lobes(self):
        for name, form in (
            ("plate", PLATE),
            ("bar", box(0.0, 0.0, 164.0, 10.0)),
            ("square", box(0.0, 0.0, 30.0, 30.0)),
            ("L", unary_union([box(0, 0, 40, 10), box(0, 0, 10, 40)])),
        ):
            cores, _ratio = _articulation_cores(form)
            self.assertLess(len(cores), 2, name)

    def test_the_neck_ratio_separates_a_waist_from_a_kerf(self):
        _neck_cores, neck_ratio = _articulation_cores(DUMBBELL)
        _kerf_cores, kerf_ratio = _articulation_cores(KERFED_PLATE)

        self.assertLess(neck_ratio, 0.35)
        self.assertGreater(kerf_ratio, 0.35)

    def test_the_neck_ratio_is_scale_free(self):
        from shapely.affinity import scale as scale_geometry

        _cores, small = _articulation_cores(DUMBBELL)
        _cores, large = _articulation_cores(
            scale_geometry(DUMBBELL, xfact=7.0, yfact=7.0)
        )

        self.assertLess(abs(small - large), 0.02)

    def test_an_empty_plan_reports_no_lobes(self):
        cores, ratio = _articulation_cores(box(0.0, 0.0, 0.0, 0.0))

        self.assertEqual((), cores)
        self.assertEqual(0.0, ratio)


class ProportionalComponentLayoutTests(SimpleTestCase):
    """A composition has to survive the AST round trip to be delivered at all.

    The authored program carries one body and one role by contract, so the
    component layout cannot be read off it. It is read off the seed, where the
    program template's components were materialized, and carried as proportions
    of that seed's own plan - which is how the templates author them in the
    first place, and what makes them independent of the frame.
    """

    def _seed(self):
        return _source([
            _component("west_gallery_hall", box(0.0, 0.0, 20.0, 20.0)),
            _component("east_public_hall", box(30.0, 0.0, 50.0, 20.0)),
            _component("entry_ramp", box(0.0, 0.0, 50.0, 4.0), top=0.2),
        ])

    def test_the_layout_is_the_same_wherever_the_seed_sits(self):
        from shapely.affinity import scale as scale_geometry, translate

        near = self._seed()
        far = _source([
            _component(
                volume.role,
                translate(
                    scale_geometry(volume.footprint, xfact=3.0, yfact=3.0, origin=(0, 0)),
                    xoff=900.0,
                    yoff=-400.0,
                ),
                volume.bottom_fraction,
                volume.top_fraction,
            )
            for volume in near.volumes
        ])

        for (role_a, unit_a, _b, _t), (role_b, unit_b, _b2, _t2) in zip(
            normalized_component_layout(near),
            normalized_component_layout(far),
        ):
            self.assertEqual(role_a, role_b)
            self.assertAlmostEqual(unit_a.area, unit_b.area, places=6)

    def test_the_layout_places_onto_any_delivered_plan(self):
        layout = normalized_component_layout(self._seed())
        plan = box(100.0, 200.0, 130.0, 220.0)

        regions = _component_regions_for_plan(
            layout, plan, bottom_fraction=0.0, top_fraction=0.5
        )

        self.assertEqual(3, len(regions))
        for _role, placed in regions:
            self.assertTrue(plan.buffer(1e-6).covers(placed))

    def test_a_component_that_stops_low_is_not_placed_upstairs(self):
        layout = normalized_component_layout(self._seed())

        upstairs = _component_regions_for_plan(
            layout, box(0.0, 0.0, 50.0, 20.0), bottom_fraction=0.5, top_fraction=1.0
        )

        self.assertEqual(
            {"west_gallery_hall", "east_public_hall"},
            {role for role, _placed in upstairs},
        )

    def test_a_seed_with_no_components_yields_no_layout(self):
        self.assertEqual((), normalized_component_layout(_source([])))


class DeliveredPiecesAreAlwaysSimplePolygonsTests(SimpleTestCase):
    """`SourceVolume.footprint` is a Polygon everywhere downstream.

    A run died in `_coherence_quality_polygon` reading `.exterior` off a
    MultiPolygon, because one role had picked up two disjoint pieces. Roles are
    re-unioned downstream anyway, so emit a volume per piece.
    """

    def _assign(self, form, source, fallback):
        return _articulated_component_parts(
            form,
            _component_regions_for_plan(
                normalized_component_layout(source),
                source.footprint,
                bottom_fraction=0.0,
                top_fraction=0.5,
            ),
            fallback_role=fallback,
        )

    def test_two_halls_hand_on_simple_polygons(self):
        assigned = self._assign(DUMBBELL, _two_halls(), "west_gallery_hall")

        self.assertTrue(assigned)
        for role, piece in assigned:
            self.assertEqual("Polygon", piece.geom_type, role)

    def test_one_role_on_both_ends_hands_on_two_polygons(self):
        form = unary_union([
            box(0.0, 0.0, 20.0, 20.0),
            box(20.0, 8.0, 30.0, 12.0),
            box(30.0, 0.0, 50.0, 20.0),
            box(50.0, 8.0, 60.0, 12.0),
            box(60.0, 0.0, 80.0, 20.0),
        ])
        source = _source([
            _component("gallery_hall", box(0.0, 0.0, 20.0, 20.0)),
            _component("public_court", box(30.0, 0.0, 50.0, 20.0)),
            _component("gallery_hall", box(60.0, 0.0, 80.0, 20.0)),
        ])

        assigned = self._assign(form, source, "gallery_hall")

        self.assertEqual({"Polygon"}, {piece.geom_type for _role, piece in assigned})
        self.assertEqual(
            2,
            sum(1 for role, _piece in assigned if role == "gallery_hall"),
        )
