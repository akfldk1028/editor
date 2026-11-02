import unittest
from ngii_terrain_supervision import may_retry


class RetryTests(unittest.TestCase):
    def test_signed_unsigned_av_only_and_finite_budget(self):
        for code in (0xc0000005,-1073741819):
            self.assertTrue(may_retry(code,'failed',0,1))
            self.assertTrue(may_retry(code,'running',2,2))
            self.assertFalse(may_retry(code,'failed',3,1))
            self.assertFalse(may_retry(code,'failed',0,3))
            for state in ('blocked','needs_storage','complete','batch-complete'):
                self.assertFalse(may_retry(code,state,0,1))
        for code in (0,1,137,0xc0000409):self.assertFalse(may_retry(code,'failed',0,1))


if __name__=='__main__':unittest.main()
