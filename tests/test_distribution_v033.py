"""Shared current route mapping without changing historical graph or dispatch."""
import hashlib
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from bili_distribution import resources as old
from bili_distribution import resources_v033 as current
from bili_distribution.capture import instructions
from bili_distribution.current_cli import tool_main
from bili_distribution.video_cli import main as video_main
from bili_distribution.cli import instructions as old_search
from bili_video_reference.cli import instructions as old_video
from scripts.compose_host_capture_v3 import compose


class CurrentDistributionTests(unittest.TestCase):
    def test_explicit_shared_v3_mapping_historical_routes_preserved(self):
        value = instructions()
        self.assertEqual(value['route_recipes'], dict(bili_search_read='host-capture-v3', bili_read_video='host-capture-v3'))
        self.assertEqual(value['composed_function_sha256'], hashlib.sha256(compose().encode()).hexdigest())
        self.assertEqual(len(value['components']), 4)
        self.assertEqual(old_search()['recipe_version'], 'host-capture-v1')
        self.assertEqual(old_video()['recipe_version'], 'host-capture-v2')
        self.assertTrue(all(Path(p).is_file() for p in value['resources'].values()))
        self.assertEqual(value['limits']['limit_parameter'], 'comments only; validated 1..3 for all kinds')

    def test_wrappers_only_delegate_business(self):
        for wrapper, target in [(tool_main,'bili_integration.cli.main'), (video_main,'bili_video_reference.cli.main')]:
            with patch(target,return_value=17) as port:
                self.assertEqual(wrapper(['schemas']),17)
                port.assert_called_once_with(['schemas'])

    def test_legacy_graph_is_strict_subset_not_rewritten(self):
        self.assertEqual(current.RESOURCE_FILES[:len(old.RESOURCE_FILES)],old.RESOURCE_FILES)
        self.assertEqual(current.check_closure()['historical_resource_count'],old.check_closure()['resource_count'])
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for relative in current.RESOURCE_FILES:
                dest=root/relative;dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(current.ROOT/relative,dest)
            (root/'docs/host-capture-recipes-v033.md').unlink()
            self.assertTrue(old.check_closure(root)['ok'])
            with self.assertRaisesRegex(ValueError,'resource_'):
                current.check_closure(root)

    def test_extra_dependency_not_silently_allowed(self):
        with self.assertRaisesRegex(ValueError,'resource_not_allowlisted'):
            current.resource_path('../private.json')


if __name__ == '__main__':
    unittest.main()
