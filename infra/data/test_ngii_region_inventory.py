import json
from pathlib import Path
import tempfile
import unittest
from shapely.geometry import Polygon, MultiPolygon
from ingest_ngii_buildings import open_db, ingest_batch, region_inventory, digest, packed
from ngii_building_adapter import NgiiBuildingAdapter


class RegionInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);raw=root/'source.zip';raw.write_bytes(b'fixture')
        receipt=raw.with_suffix('.zip.receipt.json')
        receipt.write_text(json.dumps({'bytes':7,'sha256':digest(b'fixture')}))
        manifest={'family':'NGII-B021','productCode':'B021','productKind':'continuous-topographic',
                  'productReceiptSHA256':'a'*64,'sourceManifestSHA256':'b'*64,'layer':'N3A_B0010000',
                  'crs':'EPSG:5179','edition':'2024','file':'fixture'}
        self.source={'id':'source','expectedRows':2,'manifest':manifest,'bindings':[{'path':str(raw),
            'bytes':7,'mtimeNs':raw.stat().st_mtime_ns,'sha256':digest(b'fixture'),'receiptSHA256':digest(receipt.read_bytes())}]}
        self.plan={'expectedRows':2,'sources':[self.source]}
        self.plan['planSHA256']=digest(packed(self.plan).encode())
        self.db=open_db(root/'test.sqlite',self.plan);self.addCleanup(self.db.close)
        self.adapter=NgiiBuildingAdapter(manifest)
        g=Polygon([(950000,1950000),(950001,1950000),(950001,1950001),(950000,1950001)])
        g2=Polygon([(950010,1950000),(950011,1950000),(950011,1950001),(950010,1950001)])
        self.records=[(0,{'UFID':'a','BJCD':'5011000000','NMLY':1},g),(1,{'UFID':'b','BJCD':'5011000000','NMLY':2},MultiPolygon([g,g2]))]

    def test_incomplete_rejected_then_counts_parts_not_rows(self):
        ingest_batch(self.db,self.source,self.adapter,self.records[:1])
        with self.assertRaisesRegex(ValueError,'incomplete'):region_inventory(self.db,self.plan)
        ingest_batch(self.db,self.source,self.adapter,self.records[1:])
        result=region_inventory(self.db,self.plan)
        self.assertEqual(result['buildingCount'],2)
        self.assertEqual(sum(r['components'] for r in result['regions']),3)
        self.assertEqual(result['bjcdPrefixes'],{'50':2})

    def test_changed_receipt_and_unresolved_issues_block(self):
        ingest_batch(self.db,self.source,self.adapter,self.records)
        self.db.execute('INSERT INTO issues VALUES(?,?,?,?)',('source',3,'conflict','{}'))
        with self.assertRaisesRegex(ValueError,'issues'):region_inventory(self.db,self.plan)
        self.db.execute('DELETE FROM issues')
        Path(self.source['bindings'][0]['path']).with_suffix('.zip.receipt.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):region_inventory(self.db,self.plan)

    def test_plan_tampering_blocked(self):
        with self.assertRaisesRegex(ValueError,'hash'):region_inventory(self.db,{**self.plan,'expectedRows':3})


if __name__=='__main__':unittest.main()
