import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bili_bridge.cli import main, manifest, serve
from bili_bridge.fixtures import FIXTURE_BVID
from bili_bridge.kernel import Kernel
from bili_bridge.plugins import FixtureVideoPlugin


class CliTests(unittest.TestCase):
    def test_manifest_honest(self):
        value = manifest()
        self.assertEqual(value["mode"], "offline_fixture")
        self.assertIn("writes", value["disabled"])
        self.assertFalse(value["grant_issuer_exposed"])

    def test_inspect_defaults_to_offline_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "journal.db")
            output = io.StringIO()
            with patch("bili_bridge.plugins.anonymous_html_transport", side_effect=AssertionError("network forbidden")), contextlib.redirect_stdout(output):
                code = main(["--db", db, "inspect", FIXTURE_BVID, "--part", "2", "--operation-id", "fixture-op"])
            value = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(value["data"]["source"], "offline_fixture")
            self.assertEqual(value["data"]["evidence"]["part"], 2)
            with contextlib.redirect_stdout(io.StringIO()) as status:
                self.assertEqual(main(["--db", db, "status", "fixture-op"]), 0)
            self.assertIsNotNone(json.loads(status.getvalue())["record"])

    def test_jsonl_rejects_grants_and_mutations(self):
        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(str(Path(directory) / "journal.db"), min_interval=0)
            kernel.register(FixtureVideoPlugin())
            base = {"operation_id": "one", "capability": "video.metadata", "target": FIXTURE_BVID}
            lines = ["not-json", json.dumps({**base, "grant_token": "no"}), json.dumps({**base, "capability": "video.like"}), json.dumps({**base, "operation_id": "two"})]
            output = io.StringIO()
            try:
                serve(kernel, stdin=io.StringIO("\n".join(lines) + "\n"), stdout=output)
            finally:
                kernel.close()
            values = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual([value["status"] for value in values], ["rejected", "rejected", "unsupported", "applied"])

    def test_live_error_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as directory, patch("bili_bridge.plugins.anonymous_html_transport", side_effect=OSError("secret")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--db", str(Path(directory) / "j.db"), "inspect", FIXTURE_BVID, "--live"]), 1)
        value = json.loads(output.getvalue())
        self.assertEqual(value["data"]["source"], "public_html")
        self.assertEqual(value["status"], "blocked")
        self.assertNotIn("secret", output.getvalue())

    def test_live_replay_of_fixture_is_not_presented_as_live(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ["--db", str(Path(directory) / "j.db"), "inspect", FIXTURE_BVID, "--operation-id", "same"]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
            with patch("bili_bridge.plugins.anonymous_html_transport", side_effect=AssertionError("must not send")), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args + ["--live"]), 1)
            self.assertEqual(json.loads(output.getvalue())["error"], "operation_provenance_mismatch")


if __name__ == "__main__":
    unittest.main()
