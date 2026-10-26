import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from shapely.geometry import Polygon
from ingest_ngii_buildings import open_db,ingest_batch,status
from ngii_building_adapter import NgiiBuildingAdapter
from ngii_canonical_snapshot import initialize,readonly,open_snapshot,verify_partition,verify_base


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.manifest={'family':'NGII-B021','productCode':'B021','productKind':'continuous-topographic','productReceiptSHA256':'a'*64,
                       'sourceManifestSHA256':'b'*64,'layer':'N3A_B0010000','crs':'EPSG:5179','edition':'2024','file':'fixture'}
        self.source={'id':'source','expectedRows':4,'manifest':self.manifest};self.plan={'planSHA256':'plan','expectedRows':4,'sources':[self.source]}
        self.adapter=NgiiBuildingAdapter(self.manifest);self.geometry=Polygon([(950000,1950000),(950001,1950000),(950001,1950001),(950000,1950001)])
        self.records=[(0,{'UFID':'A','NMLY':1,'BJCD':'5011000000'},self.geometry),
                      (1,{'UFID':'A','NMLY':1,'BJCD':'5011000000'},self.geometry),
                      (2,{'UFID':'B','NMLY':2,'BJCD':'5011000000'},self.geometry),
                      (3,{'UFID':'C','NMLY':3,'BJCD':'5011000000'},self.geometry)]
        self.base=self.root/'buildings.sqlite';db=open_db(self.base,self.plan);ingest_batch(db,self.source,self.adapter,self.records[:1]);db.close()
        self.base_sha=hashlib.sha256(self.base.read_bytes()).hexdigest();self.out=self.root/'delta'

    def rows(self,db):
        return {table:db.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall() for table in ('buildings','observations','issues','sources')}

    def test_exact_logical_rows_payload_provenance_and_resume(self):
        snapshot=initialize(self.plan,self.base,self.out);prior=readonly(self.base);db=open_db(self.out/'buildings.sqlite',self.plan)
        try:
            ingest_batch(db,self.source,self.adapter,self.records[1:3],prior_db=prior)
        finally:db.close();prior.close()
        snapshot=initialize(self.plan,self.base,self.out);prior=readonly(self.base);db=open_db(self.out/'buildings.sqlite',self.plan)
        try:
            ingest_batch(db,self.source,self.adapter,self.records[3:],prior_db=prior)
            self.assertEqual(status(db,self.plan,prior)['counts'],{'duplicate':1,'inserted':3})
            self.assertTrue(status(db,self.plan,prior)['complete'])
        finally:db.close();prior.close()
        full=open_db(self.root/'full.sqlite',self.plan)
        try:
            ingest_batch(full,self.source,self.adapter,self.records)
            with open_snapshot(snapshot) as combined:self.assertEqual(self.rows(combined),self.rows(full))
        finally:full.close()
        verify_partition(snapshot)
        self.assertEqual(hashlib.sha256(self.base.read_bytes()).hexdigest(),self.base_sha)

    def test_conflict_with_base_does_not_overwrite_and_blocks_complete(self):
        snapshot=initialize(self.plan,self.base,self.out);prior=readonly(self.base);db=open_db(self.out/'buildings.sqlite',self.plan)
        try:
            records=[(1,{'UFID':'A','NMLY':7,'BJCD':'5011000000'},self.geometry),*self.records[2:]]
            ingest_batch(db,self.source,self.adapter,records,prior_db=prior)
            self.assertFalse(status(db,self.plan,prior)['complete'])
            self.assertEqual(status(db,self.plan,prior)['counts']['conflict'],1)
        finally:db.close();prior.close()
        with open_snapshot(snapshot) as db:self.assertEqual(db.execute('SELECT h FROM buildings WHERE ufid=?',('A',)).fetchone()[0],3.4)

    def test_transaction_failure_keeps_cumulative_cursor_and_base(self):
        snapshot=initialize(self.plan,self.base,self.out);prior=readonly(self.base);db=open_db(self.out/'buildings.sqlite',self.plan)
        try:
            with self.assertRaisesRegex(ValueError,'Noncontiguous'):
                ingest_batch(db,self.source,self.adapter,[self.records[1],self.records[3]],prior_db=prior)
            self.assertEqual(db.execute('SELECT next_row FROM sources').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0],0)
        finally:db.close();prior.close()
        verify_partition(snapshot)

    def test_changed_base_and_self_overwrite_reject(self):
        with self.assertRaisesRegex(ValueError,'overwrite'):initialize(self.plan,self.base,self.root)
        snapshot=initialize(self.plan,self.base,self.out)
        with self.base.open('ab') as f:f.write(b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):verify_base(snapshot)


if __name__=='__main__':unittest.main()
