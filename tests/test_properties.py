from __future__ import annotations

from hypothesis import given, settings, strategies as st

from prompt_mutator import GenerationRequest, PromptGenerator


UNICODE_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=80,
)


@settings(max_examples=60, deadline=None)
@given(prompt=UNICODE_TEXT, seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_generation_is_deterministic_for_valid_unicode(prompt: str, seed: int) -> None:
    request = GenerationRequest(prompt=prompt, count=8, seed=seed)

    first = PromptGenerator().generate(request)
    second = PromptGenerator().generate(request)

    assert first == second


@settings(max_examples=60, deadline=None)
@given(prompt=UNICODE_TEXT, seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_generated_cases_respect_unicode_and_size_guards(prompt: str, seed: int) -> None:
    request = GenerationRequest(prompt=prompt, count=12, seed=seed)
    result = PromptGenerator().generate(request)
    maximum = min(1_000_000, max(10, len(prompt) * 10))

    assert len({case.id for case in result.cases}) == len(result.cases)
    for case in result.cases:
        case.text.encode("utf-8", errors="strict")
        assert len(case.text) <= maximum
        assert "\x00" not in case.text
        assert "\x1b" not in case.text
