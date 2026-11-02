import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ngii_terrain_targets import freeze


class FrozenTargetsTests(unittest.TestCase):
    def test_only_activated_filled_keys_are_removed_and_count_is_guarded(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            values={'points':[{'key':k,'point':[127.1,37.7]} for k in ['a','b','c']],
                    'provinces':{'keyProvinces':{'a':'41','b':'41'}},'filled':{'newlyFilledKeys':['a']}}
            for name,value in values.items():(root/f'{name}.json').write_text(json.dumps(value))
            with patch('ngii_terrain_targets.reserve'):
                report=freeze(root/'points.json',root/'provinces.json',root/'filled.json',root/'output',1)
                self.assertEqual(json.loads(Path(report['points']).read_text())[0]['key'],'b')
                with self.assertRaisesRegex(ValueError,'cohort changed'):
                    freeze(root/'points.json',root/'provinces.json',root/'filled.json',root/'output',2)


if __name__=='__main__':unittest.main()
