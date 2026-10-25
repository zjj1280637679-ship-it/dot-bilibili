"""Offline public upload packaging checks; not installation acceptance."""
import importlib.util
import json
from pathlib import Path
import shutil
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
