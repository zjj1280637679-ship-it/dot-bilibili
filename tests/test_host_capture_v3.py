"""Opt-in mixed-card capture: offline finite correspondence, not live acceptance."""
import hashlib
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from scripts import compose_host_capture_v2 as old
from scripts import compose_host_capture_v3 as new

ROOT = Path(__file__).resolve().parents[1]


class CaptureV3Tests(unittest.TestCase):
    def test_historical_pins_still_verify(self):
        self.assertIn('HOST_CAPTURE_RECIPES_V2.capture', old.compose())
        for name, digest in old.PINNED_SHA256.items():
            self.assertEqual(hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest(), digest)

    def test_v3_fixed_closure_and_tampering(self):
        self.assertEqual(len(new.PINNED_SHA256), 4)
        self.assertIn('HOST_CAPTURE_RECIPES_V3.capture', new.compose())
        original = Path.read_bytes
        for component in new.PINNED_SHA256:
            def read(path):
                raw = original(path)
                return raw + b'\n// changed' if path.name == component else raw
            with patch.object(Path, 'read_bytes', read):
                with self.assertRaisesRegex(ValueError, 'capture_recipe_hash_mismatch'):
                    new.compose()

    def test_composed_bounds_correspondence_and_mutants(self):
        # Engineering wall-clock/process-memory limits, not formal proof budgets.
        # Node heap cap excludes VM/native RSS; timeout exhaustion is a failed gate.
        result = subprocess.run(['node', '--max-old-space-size=64',
                                 str(ROOT/'scripts/host_capture_v3_smoke.cjs')],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('1364', result.stdout)
        self.assertIn('5/5 killed', result.stdout)
        self.assertIn('8188 representative', result.stdout)

    def test_complete_ten_card_quotient_gate(self):
        from scripts.check_search_card_scope_model import run
        result = run()
        self.assertEqual(result['states'], 2048)
        self.assertEqual(result['edges'], 8192)
        self.assertEqual(len(result['mutants_killed']), 5)


if __name__ == '__main__':
    unittest.main()
