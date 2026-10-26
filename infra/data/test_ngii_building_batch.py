import json
from pathlib import Path
import unittest
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, LineString, shape
from ngii_building_adapter import NgiiBuildingAdapter, HeightPolicy
from ngii_building_batch import adapt_batch


class BatchTests(unittest.TestCase):
    def test_exact_scalar_bytes_for_real_fixture_and_geometry_edge_cases(self):
        fixture=json.loads(Path(__file__).with_name('ngii-b021-jeju.fixture.json').read_text(encoding='utf-8'))
        adapter=NgiiBuildingAdapter(fixture['manifest'])
        records=[(i,f['properties'],shape(f['geometry'])) for i,f in enumerate(fixture['features'])]
        small=Polygon([(950000,1950000),(950001,1950000),(950001,1950001),(950000,1950001)])
        hole=Polygon([(950000,1950000),(950010,1950000),(950010,1950010),(950000,1950010)],
                     [[(950002,1950002),(950003,1950002),(950003,1950003),(950002,1950003)]])
        bowtie=Polygon([(950000,1950000),(950002,1950002),(950000,1950002),(950002,1950000)])
        for g in [small,small.reverse(),hole,MultiPolygon([small,Polygon([(950020,1950000),(950021,1950000),(950021,1950001),(950020,1950001)])]),bowtie,GeometryCollection([small,LineString([(0,0),(1,1)])]),Polygon(),None]:
            records.append((len(records),{'UFID':'edge','NMLY':0},g))
        scalar=[adapter.adapt(p,g,row=i) for i,p,g in records]
        self.assertEqual(json.dumps(adapt_batch(adapter,records)),json.dumps(scalar))

    def test_same_height_policy_and_empty_batch(self):
        fixture=json.loads(Path(__file__).with_name('ngii-b021-jeju.fixture.json').read_text(encoding='utf-8'))
        adapter=NgiiBuildingAdapter(fixture['manifest'],HeightPolicy(metric_field='H',metric_field_contract='fixture'))
        geometry=shape(fixture['features'][0]['geometry']);records=[(2,{'H':11,'NMLY':3},geometry)]
        self.assertEqual(json.dumps(adapt_batch(adapter,records)),json.dumps([adapter.adapt(records[0][1],geometry,row=2)]))
        self.assertEqual(adapt_batch(adapter,[]),[])


if __name__=='__main__':unittest.main()
