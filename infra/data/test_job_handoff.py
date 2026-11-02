import unittest
from pathlib import Path
from handoff_idle_job import matches

class Process:
    def create_time(self):return 123.5
    def cmdline(self):return ['python','-u','C:/data/job.py']

class HandoffTests(unittest.TestCase):
    def test_pid_reuse_or_other_script_is_not_authorized(self):
        self.assertTrue(matches(Process(),123.5,Path('C:/data/job.py')))
        self.assertFalse(matches(Process(),123.6,Path('C:/data/job.py')))
        self.assertFalse(matches(Process(),123.5,Path('C:/data/other.py')))

if __name__=='__main__':unittest.main()
