from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from prompt_mutator import GenerationRequest, PromptGenerator
from prompt_mutator.audit import AuditBundle


class AuditBundleContractTests(unittest.TestCase):
    def test_written_bundle_round_trips_and_verifies(self) -> None:
        pipeline = ("leetspeak", "homoglyph", "hex")
        request = GenerationRequest(
            prompt="Café internal test",
            techniques=pipeline,
            pipelines=(pipeline,),
            count=4,
            seed=31,
            min_chain_length=3,
            max_chain_length=3,
        )
        result = PromptGenerator().generate(request)

        with tempfile.TemporaryDirectory() as directory:
            bundle = AuditBundle.write(Path(directory), request, result)
            loaded_request, loaded_result = AuditBundle.load(bundle.path)

            self.assertEqual(loaded_request, request)
            self.assertEqual(loaded_result, result)
            self.assertTrue(AuditBundle.verify(bundle.path).valid)
            self.assertTrue((bundle.path / "report.html").is_file())

    def test_verify_rejects_files_added_after_finalization(self) -> None:
        request = GenerationRequest(prompt="audit me", count=2, seed=4)
        result = PromptGenerator().generate(request)

        with tempfile.TemporaryDirectory() as directory:
            bundle = AuditBundle.write(Path(directory), request, result)
            (bundle.path / "injected.txt").write_text("not in manifest", encoding="utf-8")

            verification = AuditBundle.verify(bundle.path)

            self.assertFalse(verification.valid)
            self.assertIn("unexpected:injected.txt", verification.mismatches)

    def test_report_escapes_prompt_markup_and_supports_local_search(self) -> None:
        request = GenerationRequest(prompt='<script>alert("x")</script> café', count=3, seed=2)
        result = PromptGenerator().generate(request)

        with tempfile.TemporaryDirectory() as directory:
            bundle = AuditBundle.write(Path(directory), request, result)
            report = (bundle.path / "report.html").read_text(encoding="utf-8")

            self.assertIn('id="search"', report)
            self.assertNotIn('<script>alert("x")</script>', report)
            self.assertIn("&lt;", report)


if __name__ == "__main__":
    unittest.main()
