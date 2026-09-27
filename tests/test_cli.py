from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliContractTests(unittest.TestCase):
    def test_generate_emits_jsonl_and_writes_a_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "prompt_mutator.cli",
                    "generate",
                    "test this prompt",
                    "--count",
                    "2",
                    "--seed",
                    "5",
                    "--format",
                    "jsonl",
                    "--output",
                    directory,
                    "--no-history-warning",
                ],
                cwd=Path(__file__).parents[1],
                env={**os.environ, "PYTHONPATH": "src"},
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            records = [json.loads(line) for line in completed.stdout.splitlines()]
            self.assertEqual(len(records), 2)
            self.assertTrue(all(record["schema_version"] == "1.0" for record in records))
            bundles = [path for path in Path(directory).iterdir() if path.is_dir()]
            self.assertEqual(len(bundles), 1)
            self.assertTrue((bundles[0] / "manifest.json").is_file())

    def test_encoding_profile_limits_generation_and_is_embedded_in_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [
                    sys.executable, "-m", "prompt_mutator.cli", "generate",
                    "encode this prompt", "--count", "5", "--seed", "8",
                    "--profile", "encoding", "--format", "jsonl",
                    "--output", directory, "--no-history-warning",
                ],
                cwd=Path(__file__).parents[1],
                env={**os.environ, "PYTHONPATH": "src"},
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            records = [json.loads(line) for line in completed.stdout.splitlines()]
            allowed = {"base64", "hex", "url", "html_entity", "unicode_escape"}
            self.assertTrue(all(set(record["techniques"]) <= allowed for record in records))
            bundle = next(path for path in Path(directory).iterdir() if path.is_dir())
            run = json.loads((bundle / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(run["request"]["profile_config"]["version"], 1)

    def test_unknown_extension_is_rejected_without_executing_generation(self) -> None:
        completed = subprocess.run(
            [
                sys.executable, "-m", "prompt_mutator.cli", "generate",
                "test prompt", "--enable-extension", "missing:transform",
                "--no-history-warning",
            ],
            cwd=Path(__file__).parents[1],
            env={**os.environ, "PYTHONPATH": "src"},
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("extension is not installed", completed.stderr)

    def test_profiles_lists_builtins_and_their_effective_settings(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "prompt_mutator.cli", "profiles", "--format", "json"],
            cwd=Path(__file__).parents[1],
            env={**os.environ, "PYTHONPATH": "src"},
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        profiles = {item["name"]: item for item in json.loads(completed.stdout)}
        self.assertEqual(
            set(profiles),
            {"baseline", "unicode", "encoding", "comprehensive", "chained"},
        )
        self.assertEqual(profiles["comprehensive"]["max_chain_length"], 3)
        self.assertEqual(profiles["chained"]["min_chain_length"], 2)
        self.assertIn("hex", profiles["encoding"]["techniques"])

    def test_profiles_human_output_is_a_readable_table(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "prompt_mutator.cli", "profiles"],
            cwd=Path(__file__).parents[1],
            env={**os.environ, "PYTHONPATH": "src", "COLUMNS": "120"},
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Profile", completed.stdout)
        self.assertIn("Cases", completed.stdout)
        self.assertIn("Intensity", completed.stdout)
        self.assertIn("Chain length", completed.stdout)
        self.assertIn("Techniques", completed.stdout)
        self.assertNotIn("\t", completed.stdout)


if __name__ == "__main__":
    unittest.main()
