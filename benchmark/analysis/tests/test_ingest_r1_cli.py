"""Offline CLI regressions using only temporary, synthetic run files.

Run from the repository root with:
    python -m unittest discover -s benchmark/analysis/tests -v
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "ingest-r1-revision.py"
CAVEAT = (
    "\nCaveat: us-east-1 has mock-only data; "
    "Binance geo-blocks live API in this region.\n"
)


class IngestionCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cwd = Path(self.temporary.name)
        self.root = self.cwd / "synthetic input"
        self.root.mkdir()

    def run_cli(self, root=None):
        arguments = [] if root is None else [str(root)]
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=self.cwd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def write_run(self, relative_path, contents=None):
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if contents is None:
            contents = json.dumps({
                "metrics": {
                    "http_req_duration": {"values": {
                        "avg": 10, "min": 5, "max": 20, "med": 9,
                        "p(90)": 15, "p(95)": 18, "p(99)": 19,
                    }},
                    "http_reqs": {"values": {"count": 10, "rate": 2}},
                    "http_req_failed": {"values": {"rate": 0}},
                },
                "state": {"testRunDurationMs": 5000},
                "testMetadata": {"timestamp": "SYNTHETIC"},
            })
        path.write_text(contents, encoding="utf-8")
        return path

    def assert_empty_diagnostic(self, result, supplied_root):
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.endswith("Loaded 0 run files\n"))
        self.assertIn(f"no eligible run files found in {str(supplied_root)!r}", result.stderr)
        self.assertIn("{client}/{cloudflare|vercel}/{warm|burst|cold}/*.json", result.stderr)
        self.assertIn("excluding *.summary.json", result.stderr)
        self.assertIn("warnings above", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("KeyError", result.stderr)
        self.assertNotIn("Caveat:", result.stdout)

    def test_empty_explicit_root(self):
        result = self.run_cli(self.root)
        self.assert_empty_diagnostic(result, self.root)
        self.assertEqual(result.stdout, "Loaded 0 run files\n")

    def test_empty_default_root(self):
        default_root = "benchmark/results/r1-revision"
        (self.cwd / default_root).mkdir(parents=True)
        self.assert_empty_diagnostic(self.run_cli(), default_root)

    def test_excluded_noop_only(self):
        self.write_run("local/cloudflare/noop/warm-noop-cloudflare-run1-SYNTHETIC.json")
        self.assert_empty_diagnostic(self.run_cli(self.root), self.root)

    def test_summary_only(self):
        self.write_run("local/cloudflare/warm/run.summary.json")
        self.assert_empty_diagnostic(self.run_cli(self.root), self.root)

    def test_wrong_hierarchy_only(self):
        self.write_run("warm-cloudflare-paid-mock-run1-SYNTHETIC.json")
        self.assert_empty_diagnostic(self.run_cli(self.root), self.root)

    def test_malformed_only_preserves_warning(self):
        path = self.write_run(
            "local/cloudflare/warm/warm-cloudflare-paid-mock-run1-SYNTHETIC.json",
            "{\n",
        )
        result = self.run_cli(self.root)
        self.assert_empty_diagnostic(result, self.root)
        self.assertTrue(result.stdout.startswith(f"Warning: Failed to load {path}: "))

    def test_valid_run_preserves_output(self):
        self.write_run("local/cloudflare/warm/warm-cloudflare-paid-mock-run1-SYNTHETIC.json")
        result = self.run_cli(self.root)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            result.stdout,
            "Loaded 1 run files\n"
            "scenario  client  platform    mode\n"
            "warm      local   cloudflare  mock    1\n" + CAVEAT,
        )

    def test_mixed_valid_and_malformed_preserves_success(self):
        self.write_run("local/cloudflare/warm/warm-cloudflare-paid-mock-run1-SYNTHETIC.json")
        path = self.write_run(
            "local/cloudflare/warm/warm-cloudflare-paid-mock-run2-SYNTHETIC.json",
            "{\n",
        )
        result = self.run_cli(self.root)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertTrue(result.stdout.startswith(f"Warning: Failed to load {path}: "))
        self.assertTrue(result.stdout.endswith(
            "Loaded 1 run files\n"
            "scenario  client  platform    mode\n"
            "warm      local   cloudflare  mock    1\n" + CAVEAT
        ))


if __name__ == "__main__":
    unittest.main()
