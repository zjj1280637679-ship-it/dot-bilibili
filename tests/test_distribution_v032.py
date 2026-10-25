"""Resource graph checks independent of browser operation semantics."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from bili_distribution import resources
from bili_distribution.cli import instructions, tool_main

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('v032_builder', ROOT / 'scripts/check_installed_integration_v032.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ResourceClosureTests(unittest.TestCase):
    def test_source_closure_contains_required_protocols(self):
        result = resources.check_closure()
        self.assertTrue(result['ok'])
        required = {'docs/browser-public-search.md', 'docs/browser-usage.md',
                    'docs/browser-video-open.md', 'docs/browser-comments.md'}
        self.assertLessEqual(required, {e['target'] for e in result['edges']})

    def test_missing_transitive_protocol_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            for relative in resources.RESOURCE_FILES:
                target = base / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            (base / 'docs/browser-comments.md').unlink()
            with self.assertRaisesRegex(ValueError, 'resource_(closure_)?missing'):
                resources.check_closure(base)

    def test_unlisted_new_dependency_fails_not_implicitly_copied(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            for relative in resources.RESOURCE_FILES:
                target = base / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            target = base / 'docs/read-workflow.md'
            target.write_text(target.read_text() + '\n[secret](../private.json)\n')
            (base / 'private.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'resource_closure_missing'):
                resources.check_closure(base)

    def test_link_normalization_and_parser(self):
        self.assertEqual(resources.normalize_link('docs/a.md', '../README.md'), 'README.md')
        self.assertEqual(resources.normalize_link('docs/a.md', './b.md'), 'docs/b.md')
        for target in ['../../private', '/tmp/private', '..\\private']:
            with self.assertRaises(ValueError):
                resources.normalize_link('docs/a.md', target)
        text = '[a](one.md#part) [b](https://example.org/a) [c](#part)\n[x]: two.md\n'
        self.assertEqual(list(resources.relative_links(text)), ['one.md', 'two.md'])

    def test_resource_lookup_closed(self):
        with self.assertRaises(ValueError):
            resources.resource_path('../../private')
        self.assertTrue(resources.resource_path('docs/browser-comments.md').is_file())

    def test_staging_allowlist_excludes_nonruntime_files(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            paths = builder.stage_runtime(base)
            self.assertIn('bili_video_reference/cli.py', paths)
            self.assertIn('scripts/compose_host_capture_v2.py', paths)
            self.assertFalse((base / 'tests').exists())
            self.assertFalse((base / 'dist').exists())
            self.assertFalse((base / 'bili_integration/resources').exists())
            resources.check_closure(base / 'bili_distribution/resources')

    def test_new_wrapper_delegates_business_without_mutating_frozen_module(self):
        with patch('bili_integration.cli.main', return_value=17) as old:
            self.assertEqual(tool_main(['schemas']), 17)
            old.assert_called_once_with(['schemas'])

    def test_legacy_and_video_recipe_paths_are_explicitly_separate(self):
        from bili_video_reference.cli import instructions as video_instructions
        legacy, video = instructions(), video_instructions()
        self.assertEqual(legacy['recipe_version'], 'host-capture-v1')
        self.assertEqual(Path(legacy['resources']['capture_protocol']).name, 'host-capture-recipes.md')
        self.assertEqual(Path(legacy['resources']['capture_recipe']).name, 'host_capture_recipes.js')
        self.assertEqual(Path(legacy['resources']['projection_recipe']).name, 'host_projection_recipe.js')
        self.assertEqual(video['recipe_version'], 'host-capture-v2')
        self.assertEqual(Path(video['resources']['capture_protocol']).name, 'host-capture-recipes-v2.md')
        with self.assertRaises(ValueError):
            resources.legacy_recipe_path('scripts/host_capture_recipes_v2.js')

    def test_legacy_recipe_pin_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'scripts').mkdir()
            (root / 'scripts/host_capture_recipes.js').write_text('changed')
            with patch.object(resources, 'ROOT', root), self.assertRaisesRegex(ValueError, 'digest_mismatch'):
                resources.legacy_recipe_path('scripts/host_capture_recipes.js')

    def test_current_instructions_resource_closure(self):
        result = instructions()
        self.assertTrue(result['resource_closure']['ok'])
        self.assertTrue(all(Path(p).is_file() for p in result['resources'].values()))
        self.assertFalse(result['native_tool_registration'])


if __name__ == '__main__':
    unittest.main()
