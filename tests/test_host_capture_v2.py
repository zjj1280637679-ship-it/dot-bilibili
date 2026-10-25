"""Additive fixed-source composition and new-route instructions; offline only."""
import hashlib
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from bili_video_reference import cli
from bili_integration import cli as legacy_cli
from scripts import compose_host_capture_v2 as composer

ROOT = Path(__file__).resolve().parents[1]


class CaptureV2Tests(unittest.TestCase):
    def test_instructions_pins_components_and_composed_function(self):
        result = cli.instructions()
        self.assertEqual(result['recipe_version'], 'host-capture-v2')
        self.assertEqual(result['composed_function_sha256'],
                         hashlib.sha256(composer.compose().encode()).hexdigest())
        self.assertEqual(len(result['components']), 3)
        for item in result['components']:
            self.assertEqual(hashlib.sha256(Path(item['path']).read_bytes()).hexdigest(), item['sha256'])
        for path in result['resources'].values():
            self.assertTrue(Path(path).is_file())
        self.assertEqual(result['capture_recipe_sha256'], composer.PINNED_SHA256['host_capture_recipes_v2.js'])

    def test_old_instructions_and_frozen_recipe_unchanged(self):
        old = legacy_cli.instructions()
        self.assertTrue(old['resources']['capture_recipe'].endswith('/host_capture_recipes.js'))
        self.assertEqual(hashlib.sha256((ROOT/'scripts/host_capture_recipes.js').read_bytes()).hexdigest(),
                         '1cdaa1666863524647f1fd8dcc5a3e88010429820067752c6bac331a8b14b64a')

    def test_tampering_fails_before_emitting_code(self):
        original = Path.read_bytes
        for component in composer.PINNED_SHA256:
            def read(path):
                raw = original(path)
                return raw + b'\n// changed' if path.name == component else raw
            with patch.object(Path, 'read_bytes', read):
                with self.assertRaisesRegex(ValueError, 'capture_recipe_hash_mismatch'):
                    composer.compose()

    def test_actual_composed_dom_and_relation_contract(self):
        result = subprocess.run(['node', str(ROOT/'scripts/host_capture_v2_smoke.cjs')],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
