import unittest
import json
from pathlib import Path
from shapely.geometry import Polygon, MultiPolygon, shape
from ngii_building_adapter import NgiiBuildingAdapter, HeightPolicy


class AdapterTests(unittest.TestCase):
    manifest = {"family": "NGII-B020", "layer": "N3A_B0010000", "crs": "EPSG:5179", "edition": "fixture",
                "sourceManifestSHA256": "a"*64, "file": "building.shp", "productCode": "B020",
                "productKind": "continuous-topographic", "productReceiptSHA256": "b"*64}
    polygon = Polygon([(950000, 1950000), (950001, 1950000), (950001, 1950001), (950000, 1950001)])

    def test_tiny_geometry_identity_and_stream(self):
        adapter = NgiiBuildingAdapter(self.manifest)
        a, b = list(adapter.stream([(0, {"ufid": "001", "nmly": 2}, self.polygon),
                                    (1, {"UFID": "001", "NMLY": 2}, self.polygon.reverse())]))
        self.assertEqual(a["canonicalBuildingId"], b["canonicalBuildingId"])
        self.assertEqual(a["h"], 6.8)
        self.assertEqual(a["geometryAudit"]["areaM2"], 1)
        self.assertEqual(a["sourceUFID"], "001")

    def test_holes_and_multipart_preserved(self):
        outer = Polygon([(950000, 1950000), (950010, 1950000), (950010, 1950010), (950000, 1950010)],
                        [[(950002, 1950002), (950003, 1950002), (950003, 1950003), (950002, 1950003)]])
        remote = Polygon([(950020, 1950000), (950021, 1950000), (950021, 1950001), (950020, 1950001)])
        result = NgiiBuildingAdapter(self.manifest).adapt({}, MultiPolygon([outer, remote]), row=0)
        geom = shape(result["geomWGS84"])
        self.assertEqual(len(geom.geoms), 2)
        self.assertEqual(sum(len(g.interiors) for g in geom.geoms), 1)
        self.assertTrue(geom.contains(shape({"type": "Point", "coordinates": result["anchorWGS84"]})))

    def test_height_field_never_guessed(self):
        adapter = NgiiBuildingAdapter(self.manifest)
        result = adapter.adapt({"HEIGHT": 100, "NMLY": 0}, self.polygon, row=0)
        self.assertEqual(result["h"], 3.4)
        self.assertEqual(result["heightSource"]["kind"], "declared-default")
        with self.assertRaises(ValueError): HeightPolicy(metric_field="HEIGHT")
        verified = NgiiBuildingAdapter(self.manifest, HeightPolicy(metric_field="HEIGHT", metric_field_contract="verified-fixture-metre-field"))
        self.assertEqual(verified.adapt({"HEIGHT": 12, "NMLY": 2}, self.polygon, row=0)["h"], 12)

    def test_same_ufid_different_geometry_retained_and_empty_reported(self):
        adapter = NgiiBuildingAdapter(self.manifest)
        a = adapter.adapt({"UFID": "same"}, self.polygon, row=0)
        b = adapter.adapt({"UFID": "same"}, self.polygon.buffer(.1), row=1)
        self.assertNotEqual(a["canonicalBuildingId"], b["canonicalBuildingId"])
        self.assertIn("rejected", adapter.adapt({}, Polygon(), row=2))

    def test_gis_source_and_wrong_projection_rejected(self):
        with self.assertRaises(ValueError): NgiiBuildingAdapter({**self.manifest, "family": "GIS"})
        with self.assertRaises(ValueError): NgiiBuildingAdapter({**self.manifest, "crs": "EPSG:5186"})

    def test_b021_keeps_actual_product_identity_and_rejects_sheets(self):
        manifest = {**self.manifest, "family": "NGII-B021", "productCode": "B021"}
        result = NgiiBuildingAdapter(manifest).adapt({"UFID": "1"}, self.polygon, row=0)
        self.assertEqual(result["provenance"]["productCode"], "B021")
        self.assertEqual(result["provenance"]["family"], "NGII-B021")
        with self.assertRaises(ValueError): NgiiBuildingAdapter({**manifest, "family": "NGII-B020"})
        with self.assertRaises(ValueError): NgiiBuildingAdapter({**manifest, "productKind": "individual-sheet"})
        with self.assertRaises(ValueError): NgiiBuildingAdapter({**manifest, "productReceiptSHA256": None})

    def test_actual_official_jeju_b021_fixture(self):
        fixture = json.loads(Path(__file__).with_name("ngii-b021-jeju.fixture.json").read_text(encoding="utf-8"))
        adapter = NgiiBuildingAdapter(fixture["manifest"])
        results = [adapter.adapt(f["properties"], shape(f["geometry"]), row=i) for i, f in enumerate(fixture["features"])]
        self.assertEqual(len({r["canonicalBuildingId"] for r in results}), 4)
        self.assertEqual([r["h"] for r in results], [3.4, 3.4, 3.4, 6.8])
        self.assertTrue(all(125 < r["anchorWGS84"][0] < 128 and 32 < r["anchorWGS84"][1] < 35 for r in results))
        self.assertTrue(all(r["provenance"]["productCode"] == "B021" for r in results))


if __name__ == "__main__": unittest.main()
