"""Offline public upload packaging checks; not installation acceptance."""
import importlib.util
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_dot_plugin', ROOT / 'scripts/build_dot_plugin.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PluginBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'plugin'
        shutil.copytree(ROOT / 'plugin', self.source)

    def test_deterministic_minimal_root_archive(self):
        a, b = self.root / 'a.zip', self.root / 'b.zip'
        first = builder.build(self.source, a)
        second = builder.build(self.source, b)
        self.assertEqual(first['sha256'], second['sha256'])
        self.assertLess(first['bytes'], 100_000_000)
        with zipfile.ZipFile(a) as archive:
            self.assertEqual(archive.namelist(), list(builder.MEMBERS))
            self.assertIsNone(archive.testzip())
            manifest = json.loads(archive.read('plugin.json'))
            self.assertEqual(manifest['name'], 'dot-bilibili')
            self.assertNotIn('mcpServers', manifest)

    def test_public_read_examples_match_runtime_contracts(self):
        from facade.contracts import validate as validate_search
        from bili_video_reference.contracts import validate as validate_video
        skill = (self.source / 'skills/bilibili/SKILL.md').read_text()
        examples = [json.loads(raw) for raw in re.findall(r'```json\n(.*?)\n```', skill, re.S)]
        read_examples = [item for item in examples if item['tool'] != 'bili_status']
        self.assertEqual({item['tool'] for item in read_examples},
                         {'bili_search_read', 'bili_read_video'})
        for item in read_examples:
            validator = validate_video if item['tool'] == 'bili_read_video' else validate_search
            normalized = validator(item['arguments'])
            self.assertFalse(normalized['comments'])
            if item['tool'] == 'bili_read_video':
                self.assertEqual(normalized['query'], normalized['select'])

    def test_documented_bootstrap_commands_have_complete_resources(self):
        for action in ('diagnose', 'instructions'):
            result = json.loads(subprocess.check_output(
                [sys.executable, '-m', 'bili_distribution.cli', action], cwd=ROOT))
            self.assertTrue(result['resource_closure']['ok'])
            if action == 'instructions':
                self.assertEqual(result['recipe_version'], 'host-capture-v1')
                self.assertEqual(Path(result['resources']['capture_recipe']).name,
                                 'host_capture_recipes.js')
                self.assertTrue(Path(result['resources']['projection_recipe']).is_file())
        for module in ('bili_integration.cli', 'bili_video_reference.cli'):
            schemas = json.loads(subprocess.check_output(
                [sys.executable, '-m', module, 'schemas'], cwd=ROOT))
            self.assertTrue(schemas)
        instructions = json.loads(subprocess.check_output(
            [sys.executable, '-m', 'bili_video_reference.cli', 'instructions'], cwd=ROOT))
        self.assertEqual(instructions['recipe_version'], 'host-capture-v2')
        self.assertEqual(len(instructions['components']), 3)

    def test_skill_never_routes_to_incomplete_legacy_instructions(self):
        skill = (self.source / 'skills/bilibili/SKILL.md').read_text()
        self.assertNotIn('bili_integration.cli instructions', skill)

    def test_extra_private_file_fails_closed(self):
        (self.source / 'private.sqlite3').write_bytes(b'private')
        with self.assertRaises(ValueError):
            builder.build(self.source, self.root / 'bad.zip')
        self.assertFalse((self.root / 'bad.zip').exists())

    def test_symlink_fails_closed(self):
        path = self.source / 'skills/bilibili/SKILL.md'
        content = path.read_bytes()
        path.unlink()
        outside = self.root / 'external'
        outside.write_bytes(content)
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            builder.validate(self.source)

    def test_mcp_or_hooks_manifest_fails_closed(self):
        path = self.source / 'plugin.json'
        data = json.loads(path.read_text())
        data['mcpServers'] = {'unexpected': {}}
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            builder.validate(self.source)

    def test_host_path_leak_fails_closed(self):
        path = self.source / 'skills/bilibili/SKILL.md'
        path.write_text(path.read_text() + '\n/workspace/private/runtime\n')
        with self.assertRaises(ValueError):
            builder.validate(self.source)

    def test_output_cannot_contaminate_source(self):
        with self.assertRaises(ValueError):
            builder.build(self.source, self.source / 'bundle.zip')


if __name__ == '__main__':
    unittest.main()
