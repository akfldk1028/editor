import tempfile
from pathlib import Path
import unittest
import zlib
import json
import sys
import itertools
from unittest.mock import patch
from shapely.geometry import Polygon, MultiPolygon
from shapely.affinity import translate
from ingest_ngii_buildings import open_db, ingest_batch, status, region_inventory, packed, digest
from ngii_building_adapter import NgiiBuildingAdapter
from ngii_building_batch import adapt_batch


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source={'id':'source','expectedRows':3}
        self.plan={'planSHA256':'plan','expectedRows':3,'sources':[self.source]}
        self.db=open_db(Path(self.temp.name)/'test.sqlite',self.plan);self.addCleanup(self.db.close)
        self.adapter=NgiiBuildingAdapter({'family':'NGII-B021','productCode':'B021','productKind':'continuous-topographic',
            'productReceiptSHA256':'a'*64,'sourceManifestSHA256':'b'*64,'layer':'N3A_B0010000','crs':'EPSG:5179','edition':'2024','file':'fixture'})
        self.geom=Polygon([(950000,1950000),(950001,1950000),(950001,1950001),(950000,1950001)])

    def record(self,row,floors=1):return row,{'UFID':'same','NMLY':floors,'BJCD':'5011000000'},self.geom

    def test_region_inventory_progress_is_sparse_and_does_not_change_result_bytes(self):
        payload=zlib.compress(b'{"geomWGS84":{"type":"Polygon"}}')
        class ReadOnlyRows:
            def execute(self,query):
                if query!='SELECT region14,bjcd,payload FROM buildings':raise AssertionError(query)
                return itertools.repeat(('14/1/2','5011000000',payload),1_000_002)
        ticks=[];plan={'planSHA256':'fixture','expectedRows':1_000_002}
        with patch('ingest_ngii_buildings.completed_source_gate',lambda *_:None):
            reported=region_inventory(ReadOnlyRows(),plan,progress=ticks.append)
            quiet=region_inventory(ReadOnlyRows(),plan)
        self.assertEqual(ticks,[1_000_000])
        self.assertEqual(reported['buildingCount'],1_000_002)
        self.assertEqual(packed(reported).encode(),packed(quiet).encode())

    def test_region_inventory_fast_parser_and_optional_fallback_are_byte_identical(self):
        try:
            import orjson
        except ImportError:
            self.skipTest('Optional orjson is not installed')
        source={**self.source,'bindings':[],'manifest':{}}
        plan={'expectedRows':3,'sources':[source]};plan['planSHA256']=digest(packed(plan).encode())
        db=open_db(Path(self.temp.name)/'inventory.sqlite',plan)
        try:
            multi=MultiPolygon([self.geom,translate(self.geom,xoff=30)])
            ingest_batch(db,source,self.adapter,[self.record(0),(1,{'UFID':'second','NMLY':2,'BJCD':'4111000000'},multi),self.record(2)])
            calls=[]
            def fast(value):calls.append(value);return orjson.loads(value)
            with patch.dict(sys.modules,{'orjson':type('Parser',(),{'loads':staticmethod(fast)})}):
                optimized=region_inventory(db,plan)
            self.assertEqual(len(calls),2)
            with patch.dict(sys.modules,{'orjson':None}):fallback=region_inventory(db,plan)
            self.assertEqual(packed(optimized).encode(),packed(fallback).encode())
            self.assertEqual(optimized['buildingCount'],2)
            self.assertEqual(sum(r['components'] for r in optimized['regions']),3)
            self.assertEqual(optimized['bjcdPrefixes'],{'50':1,'41':1})
        finally:db.close()

    def test_exact_duplicate_resume_and_conflict(self):
        ingest_batch(self.db,self.source,self.adapter,[self.record(0),self.record(1)])
        self.assertEqual(self.db.execute('SELECT count(*) FROM buildings').fetchone()[0],1)
        ingest_batch(self.db,self.source,self.adapter,[self.record(2,2)])
        result=status(self.db,self.plan)
        self.assertEqual(result['counts'],{'conflict':1,'duplicate':1,'inserted':1})
        self.assertFalse(result['complete'])
        value=json.loads(zlib.decompress(self.db.execute('SELECT payload FROM buildings').fetchone()[0]))
        self.assertEqual(value['h'],3.4)

    def test_batch_failure_rolls_back_cursor_and_outputs(self):
        with self.assertRaisesRegex(ValueError,'Noncontiguous'):
            ingest_batch(self.db,self.source,self.adapter,[self.record(0),self.record(2)])
        self.assertEqual(self.db.execute('SELECT count(*) FROM buildings').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT next_row FROM sources').fetchone()[0],0)

    def test_plan_change_and_noncontiguous_resume_rejected(self):
        with self.assertRaisesRegex(ValueError,'plan mismatch'):
            open_db(Path(self.temp.name)/'test.sqlite',{**self.plan,'planSHA256':'changed'})
        ingest_batch(self.db,self.source,self.adapter,[self.record(0)])
        with self.assertRaisesRegex(ValueError,'Noncontiguous'):
            ingest_batch(self.db,self.source,self.adapter,[self.record(0)])

    def test_batch_geometry_preserves_duplicates_conflicts_and_resume(self):
        records=[self.record(0),self.record(1)]
        ingest_batch(self.db,self.source,self.adapter,records,values=adapt_batch(self.adapter,records))
        records=[self.record(2,2)]
        ingest_batch(self.db,self.source,self.adapter,records,values=adapt_batch(self.adapter,records))
        self.assertEqual(status(self.db,self.plan)['counts'],{'conflict':1,'duplicate':1,'inserted':1})
        self.assertEqual(self.db.execute('SELECT next_row FROM sources').fetchone()[0],3)

    def test_batch_geometry_rejection_and_rollback(self):
        records=[self.record(0),(2,{},Polygon())]
        with self.assertRaisesRegex(ValueError,'Noncontiguous'):
            ingest_batch(self.db,self.source,self.adapter,records,values=adapt_batch(self.adapter,records))
        self.assertEqual(self.db.execute('SELECT count(*) FROM observations').fetchone()[0],0)
        records=[(0,{},Polygon())]
        ingest_batch(self.db,self.source,self.adapter,records,values=adapt_batch(self.adapter,records))
        self.assertEqual(status(self.db,self.plan)['counts'],{'rejected':1})
        self.assertFalse(status(self.db,self.plan)['complete'])

    def test_bounded_wal_configuration_keeps_full_sync_and_memory_limit(self):
        c=open_db(Path(self.temp.name)/'wal.sqlite',self.plan,16384)
        try:
            self.assertEqual(c.execute('PRAGMA wal_autocheckpoint').fetchone()[0],16384)
            self.assertEqual(c.execute('PRAGMA journal_size_limit').fetchone()[0],256*1024**2)
            self.assertEqual(c.execute('PRAGMA cache_size').fetchone()[0],-32768)
            self.assertEqual(c.execute('PRAGMA synchronous').fetchone()[0],2)
            ingest_batch(c,self.source,self.adapter,[self.record(0)])
            self.assertEqual(c.execute('SELECT next_row FROM sources').fetchone()[0],1)
        finally:c.close()
        for pages in [0,49153,-1]:
            with self.assertRaisesRegex(ValueError,'WAL checkpoint'):
                open_db(Path(self.temp.name)/'invalid.sqlite',self.plan,pages)


if __name__=='__main__':unittest.main()
