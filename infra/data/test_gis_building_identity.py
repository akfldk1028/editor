import unittest
from shapely.geometry import Polygon, MultiPolygon
from gis_building_identity import canonical_identity, merge_identical


class IdentityTests(unittest.TestCase):
    def record(self, geometry=None, **properties):
        if geometry is None:
            geometry = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
        return canonical_identity({"A1": "00001", "A2": "parcel", "A16": 6, "A26": 2, **properties},
                                  geometry, edition="20261009", provenance={"file": "raw.zip", "row": properties.get("row", 1)})

    def test_rotation_winding_administrative_correction_merge(self):
        a = self.record(A4="old", A23="old-code")
        b = self.record(Polygon([(2, 2), (2, 0), (0, 0), (0, 2)]), A4="new", A23="new-code", row=2)
        self.assertEqual(a["key"], b["key"])
        self.assertEqual(len(merge_identical(a, b)["provenance"]), 2)

    def test_same_id_different_geometry_is_not_duplicate(self):
        self.assertIsNone(merge_identical(self.record(), self.record(Polygon([(3, 0), (4, 0), (4, 1), (3, 1)]))))

    def test_conflicting_height_and_editions_do_not_silently_merge(self):
        with self.assertRaisesRegex(ValueError, "physical attributes"):
            merge_identical(self.record(), self.record(A16=12))
        b = self.record(); b["edition"] = "20260909"
        with self.assertRaisesRegex(ValueError, "editions"):
            merge_identical(self.record(), b)

    def test_small_positive_polygon_and_courtyard_survive(self):
        small = self.record(Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]))
        self.assertEqual(small["audit"]["areaM2"], 1)
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(2, 2), (3, 2), (3, 3), (2, 3)]])
        self.assertEqual(len(self.record(polygon)["geometry"].interiors), 1)

    def test_multipart_order_does_not_change_identity(self):
        a = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        b = Polygon([(3, 0), (4, 0), (4, 1), (3, 1)])
        self.assertEqual(self.record(MultiPolygon([a, b]))["key"], self.record(MultiPolygon([b, a]))["key"])


if __name__ == "__main__":
    unittest.main()
