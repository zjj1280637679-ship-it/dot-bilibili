"""Finite relation gate plus sampled implementation correspondence; no browser/ledger."""
import unittest
from unittest.mock import patch
from formal import video_reference_model as model
from scripts.check_video_reference_model import run
from bili_video_reference import adapter


class RelationTests(unittest.TestCase):
    def test_bounded_model_and_mutants(self):
        result = run()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['model']['states'], 193)
        self.assertLess(result['model']['elapsed_seconds'], 5)
        self.assertLess(result['model']['peak_traced_bytes'], 32 * 1024 * 1024)

    def test_budget_exhaustion_not_success(self):
        result = run(max_states=2)
        self.assertFalse(result['ok'])
        self.assertEqual(result['model']['status'], 'budget_exceeded')

    def test_alias_independent_abstract_intent(self):
        groups = {}
        for _, s in model.transitions(model.State()):
            if not s.valid:
                continue
            _, pending = next(model.transitions(s))
            groups.setdefault((s.bvid, s.comments, s.host_id), set()).add(model.intent(pending))
        self.assertEqual(len(groups), 8)
        self.assertTrue(all(len(intents) == 1 for intents in groups.values()))

    def test_sampled_implementation_port_relation(self):
        for bvid in ('BV1xx411c7mD', 'BV2xx411c7mD'):
            for video in (bvid, 'https://www.bilibili.com/video/'+bvid, 'https://www.bilibili.com/video/'+bvid+'/'):
                for comments in (False, True):
                    for host_id in ('host-one', '主机二'):
                        for outcome in model.OUTCOMES:
                            result = {'status': outcome}
                            profile = object()
                            with patch.object(adapter, 'search_read', return_value=result) as port:
                                actual = adapter.read_video(dict(video=video, comments=comments), profile=profile, invocation_id=host_id)
                            self.assertIs(actual, result)
                            port.assert_called_once_with(dict(query=bvid, select=bvid, comments=comments), profile=profile, invocation_id=host_id)

    def test_rejection_has_no_port_or_fallback(self):
        for video in (None, 1, [], 'av1', 'https://b23.tv/x', 'BV1xx411c7mD\n', 'https://www.bilibili.com/video/BV1xx411c7mD?p=1'):
            with patch.object(adapter, 'search_read') as port:
                result = adapter.read_video({'video': video}, profile=None, invocation_id='host')
            port.assert_not_called()
            self.assertEqual(result['error']['code'], 'unsupported_video_reference')


if __name__ == '__main__':
    unittest.main()
