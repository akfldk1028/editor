import unittest
from national_original_acquisition_loop import should_resume_order

class AcquisitionLoopTests(unittest.TestCase):
    def test_does_not_duplicate_running_or_finished_order_lane(self):
        self.assertFalse(should_resume_order('running'))
        self.assertFalse(should_resume_order('finished'))
        self.assertTrue(should_resume_order('requires_reconciliation'))
        self.assertTrue(should_resume_order('login_required'))

if __name__=='__main__':unittest.main()
