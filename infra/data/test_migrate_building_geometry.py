import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from migrate_building_geometry import building_lock


@unittest.skipUnless(os.name == 'nt', 'Compatibility test for the existing Windows byte lock')
class GeometryMigrationLockTests(unittest.TestCase):
    def test_existing_writer_prevents_migration_and_release_allows_retry(self):
        with tempfile.TemporaryDirectory() as root:
            code = 'from migrate_building_geometry import building_lock\nimport sys\nwith building_lock(sys.argv[1]): print("acquired")'
            cmd = [sys.executable, '-c', code, root]
            with building_lock(root):
                held = subprocess.run(cmd, cwd=Path(__file__).parent, capture_output=True, text=True)
                self.assertNotEqual(held.returncode, 0)
                self.assertIn('already running', held.stderr)
                self.assertNotIn('acquired', held.stdout)
            free = subprocess.run(cmd, cwd=Path(__file__).parent, capture_output=True, text=True)
            self.assertEqual(free.returncode, 0, free.stderr)
            self.assertEqual(free.stdout.strip(), 'acquired')


if __name__ == '__main__':
    unittest.main()
