from __future__ import annotations

import re
import unittest

from prompt_mutator import GenerationRequest, PromptGenerator
from prompt_mutator.profiles import load_profile


class GeneratorContractTests(unittest.TestCase):
    def test_same_request_and_seed_produce_the_same_leetspeak_case(self) -> None:
        request = GenerationRequest(
            prompt="a secure test",
            techniques=("leetspeak",),
            count=1,
            seed=7,
            intensity="high",
        )

        first = PromptGenerator().generate(request)
        second = PromptGenerator().generate(request)

        self.assertEqual(first.cases, second.cases)
        self.assertEqual(first.cases[0].techniques, ("leetspeak",))
        self.assertNotEqual(first.cases[0].text, request.prompt)

    def test_hex_can_encode_only_spaces(self) -> None:
        result = PromptGenerator().generate(
            GenerationRequest(
                prompt="allow this request",
                techniques=("hex",),
                count=1,
                seed=11,
                intensity="medium",
            )
        )

        self.assertEqual(result.cases[0].text, r"allow\x20this\x20request")
        self.assertEqual(result.cases[0].parameters["variant"], "spaces")

    def test_every_builtin_technique_produces_valid_unicode(self) -> None:
        generator = PromptGenerator()

        for technique in generator.techniques():
            with self.subTest(technique=technique):
                result = generator.generate(
                    GenerationRequest(
                        prompt="Café Attack test 42!",
                        techniques=(technique,),
                        count=1,
                        seed=19,
                        intensity="medium",
                    )
                )
                self.assertEqual(len(result.cases), 1)
                result.cases[0].text.encode("utf-8", errors="strict")
                self.assertNotIn("\x00", result.cases[0].text)
                self.assertNotIn("\x1b", result.cases[0].text)

    def test_default_request_balances_twenty_five_unique_cases(self) -> None:
        result = PromptGenerator().generate(
            GenerationRequest(
                prompt="Review this café prompt and its carefully formatted internal security controls.",
                count=25,
                seed=23,
            )
        )

        self.assertEqual(len(result.cases), 25)
        self.assertEqual(len({case.text for case in result.cases}), 25)
        covered = {case.techniques[0] for case in result.cases}
        self.assertEqual(covered, set(PromptGenerator().techniques()))

    def test_comprehensive_generation_includes_bounded_chains(self) -> None:
        result = PromptGenerator().generate(
            GenerationRequest(
                prompt="attack this test prompt",
                techniques=("leetspeak", "hex"),
                count=4,
                seed=9,
                max_chain_length=2,
                profile="comprehensive",
            )
        )

        chained = [case for case in result.cases if len(case.techniques) == 2]
        self.assertTrue(chained)
        self.assertTrue(all(len(case.techniques) <= 2 for case in result.cases))
        self.assertTrue(all(case.producing_pipelines for case in chained))

    def test_unicode_families_expose_distinct_agreed_variants(self) -> None:
        generator = PromptGenerator()
        normalization = generator.generate(
            GenerationRequest(
                prompt="① café",
                techniques=("normalization",),
                count=4,
                seed=1,
            )
        )
        styles = generator.generate(
            GenerationRequest(
                prompt="Attack123",
                techniques=("unicode_style",),
                count=4,
                seed=1,
                intensity="high",
            )
        )
        escapes = generator.generate(
            GenerationRequest(
                prompt="Attack",
                techniques=("unicode_escape",),
                count=4,
                seed=1,
                intensity="medium",
            )
        )

        self.assertEqual(
            {case.parameters["variant"] for case in normalization.cases},
            {"NFD", "NFKD", "NFKC"},
        )
        self.assertTrue(
            {"mathematical-bold", "circled", "superscript", "subscript"}
            <= {case.parameters["variant"] for case in styles.cases}
        )
        self.assertIn(
            "unicode-name",
            {case.parameters["variant"] for case in escapes.cases},
        )

    def test_leetspeak_exposes_basic_symbol_and_mixed_variants(self) -> None:
        result = PromptGenerator().generate(
            GenerationRequest(
                prompt="a serious test situation",
                techniques=("leetspeak",),
                count=3,
                seed=6,
                intensity="high",
            )
        )

        self.assertEqual(
            {case.parameters["variant"] for case in result.cases},
            {"basic", "symbol-heavy", "mixed"},
        )

    def test_percent_encoding_belongs_to_url_and_never_hex(self) -> None:
        generator = PromptGenerator()
        hex_result = generator.generate(
            GenerationRequest(
                prompt="Review this prompt",
                techniques=("hex",),
                count=10,
                seed=0,
            )
        )
        url_result = generator.generate(
            GenerationRequest(
                prompt="Review",
                techniques=("url",),
                count=4,
                seed=0,
            )
        )

        self.assertFalse(
            any(re.search(r"%[0-9A-Fa-f]{2}", case.text) for case in hex_result.cases)
        )
        self.assertTrue(
            any(re.search(r"%[0-9A-Fa-f]{2}", case.text) for case in url_result.cases)
        )

    def test_chained_profile_emits_no_single_technique_cases(self) -> None:
        profile = load_profile("chained")
        result = PromptGenerator().generate(
            GenerationRequest(
                prompt="Chain this café security prompt",
                techniques=profile.techniques,
                count=25,
                seed=3,
                intensity=profile.intensity,
                min_chain_length=profile.min_chain_length,
                max_chain_length=profile.max_chain_length,
                profile=profile.name,
                profile_config=profile.resolved(),
            )
        )

        self.assertEqual(len(result.cases), 25)
        self.assertTrue(all(2 <= len(case.techniques) <= 3 for case in result.cases))

    def test_exact_pipeline_preserves_user_selected_order_and_length(self) -> None:
        pipeline = ("leetspeak", "homoglyph", "hex")
        result = PromptGenerator().generate(
            GenerationRequest(
                prompt="Apply this exact café chain",
                techniques=pipeline,
                pipelines=(pipeline,),
                count=8,
                seed=12,
                intensity="medium",
                min_chain_length=3,
                max_chain_length=3,
                profile="custom_chain",
            )
        )

        self.assertGreater(len(result.cases), 1)
        self.assertTrue(all(case.techniques == pipeline for case in result.cases))


if __name__ == "__main__":
    unittest.main()
