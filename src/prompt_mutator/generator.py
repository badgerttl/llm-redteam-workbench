from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from itertools import permutations

from .models import GeneratedCase, GenerationRequest, RunResult
from .transforms import Transform, mutate, technique_names


class PromptGenerator:
    """Generate deterministic prompt mutations through a stable public seam."""

    def __init__(self, extensions: dict[str, Transform] | None = None) -> None:
        self._extensions = dict(extensions or {})

    @staticmethod
    def techniques() -> tuple[str, ...]:
        return technique_names()

    def available_techniques(self) -> tuple[str, ...]:
        return technique_names() + tuple(sorted(self._extensions))

    def generate(self, request: GenerationRequest) -> RunResult:
        if request.intensity not in {"low", "medium", "high", "max"}:
            raise ValueError(f"unknown intensity: {request.intensity}")
        if request.count < 1:
            raise ValueError("count must be at least 1")
        if not 1 <= request.min_chain_length <= request.max_chain_length <= 3:
            raise ValueError("chain lengths must satisfy 1 <= min <= max <= 3")
        if any(len(pipeline) not in {2, 3} for pipeline in request.pipelines):
            raise ValueError("explicit pipelines must contain exactly 2 or 3 techniques")

        input_hash = hashlib.sha256(request.prompt.encode("utf-8")).hexdigest()
        cases: list[GeneratedCase] = []
        seen: dict[str, int] = {}
        skipped: list[dict[str, str]] = []
        errors: list[dict[str, str]] = []
        attempted = 0
        selected = request.techniques or technique_names()

        def append_case(
            text: str,
            pipeline: tuple[str, ...],
            parameters: dict[str, object],
            positions: tuple[int, ...],
        ) -> None:
            if text == request.prompt:
                skipped.append({"pipeline": " -> ".join(pipeline), "reason": "unchanged"})
                return
            if not self._safe_text(text):
                skipped.append({"pipeline": " -> ".join(pipeline), "reason": "forbidden-control"})
                return
            maximum = min(1_000_000, max(10, len(request.prompt) * 10))
            if len(text) > maximum:
                skipped.append({"pipeline": " -> ".join(pipeline), "reason": "case-size-limit"})
                return
            if text in seen:
                index = seen[text]
                existing = cases[index]
                if pipeline not in existing.producing_pipelines:
                    cases[index] = replace(
                        existing,
                        producing_pipelines=existing.producing_pipelines + (pipeline,),
                    )
                return
            case_id = self._case_id(input_hash, pipeline, parameters, request.seed, text)
            seen[text] = len(cases)
            cases.append(
                GeneratedCase(
                    id=case_id,
                    text=text,
                    techniques=pipeline,
                    parameters=parameters,
                    changed_positions=positions,
                    producing_pipelines=(pipeline,),
                )
            )

        max_rounds = max(8, request.count * 2)
        for sample in range(max_rounds):
            if request.pipelines:
                for pipeline in request.pipelines:
                    if len(cases) >= request.count:
                        break
                    attempted += 1
                    text = request.prompt
                    changed: set[int] = set()
                    steps: list[dict[str, object]] = []
                    try:
                        for step, technique in enumerate(pipeline):
                            mutation = mutate(
                                technique,
                                text,
                                request.seed + step,
                                request.intensity,
                                variant_index=sample,
                                extensions=self._extensions,
                            )
                            text = mutation.text
                            changed.update(mutation.positions)
                            steps.append({"technique": technique, **mutation.parameters})
                    except Exception as exc:
                        errors.append(
                            {
                                "pipeline": " -> ".join(pipeline),
                                "error": type(exc).__name__,
                                "message": str(exc),
                            }
                        )
                        continue
                    append_case(text, pipeline, {"steps": steps}, tuple(sorted(changed)))
                if len(cases) >= request.count:
                    break
                continue

            for technique in selected:
                if len(cases) >= request.count:
                    break
                if request.min_chain_length > 1:
                    continue
                attempted += 1
                try:
                    mutation = mutate(
                        technique,
                        request.prompt,
                        request.seed,
                        request.intensity,
                        variant_index=sample,
                        extensions=self._extensions,
                    )
                except Exception as exc:
                    errors.append({"pipeline": technique, "error": type(exc).__name__, "message": str(exc)})
                    continue
                append_case(mutation.text, (technique,), mutation.parameters, mutation.positions)

            if sample == 0 and request.max_chain_length > 1 and len(cases) < request.count:
                for length in range(max(2, request.min_chain_length), request.max_chain_length + 1):
                    for pipeline in permutations(selected, length):
                        if len(cases) >= request.count:
                            break
                        if not self._compatible(pipeline):
                            skipped.append({"pipeline": " -> ".join(pipeline), "reason": "incompatible"})
                            continue
                        attempted += 1
                        text = request.prompt
                        changed: set[int] = set()
                        steps: list[dict[str, object]] = []
                        try:
                            for step, technique in enumerate(pipeline):
                                mutation = mutate(
                                    technique,
                                    text,
                                    request.seed + step,
                                    request.intensity,
                                    variant_index=sample,
                                    extensions=self._extensions,
                                )
                                text = mutation.text
                                changed.update(mutation.positions)
                                steps.append({"technique": technique, **mutation.parameters})
                        except Exception as exc:
                            errors.append({"pipeline": " -> ".join(pipeline), "error": type(exc).__name__, "message": str(exc)})
                            continue
                        append_case(text, pipeline, {"steps": steps}, tuple(sorted(changed)))
                    if len(cases) >= request.count:
                        break
            if len(cases) >= request.count:
                break
        return RunResult(
            input_hash=input_hash,
            seed=request.seed,
            cases=tuple(cases),
            attempted=attempted,
            skipped=tuple(skipped),
            errors=tuple(errors),
        )

    @staticmethod
    def _compatible(pipeline: tuple[str, ...]) -> bool:
        terminal = {"base64", "reverse", "url"}
        return not any(technique in terminal for technique in pipeline[:-1])

    @staticmethod
    def _safe_text(text: str) -> bool:
        forbidden = {
            "\x00", "\x1b", "\u061c", "\u200e", "\u200f",
            "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
            "\u2066", "\u2067", "\u2068", "\u2069",
        }
        return not any(character in text for character in forbidden)

    @staticmethod
    def _case_id(
        input_hash: str,
        techniques: tuple[str, ...],
        parameters: dict[str, object],
        seed: int,
        text: str,
    ) -> str:
        material = json.dumps(
            {
                "generator": "1",
                "input_hash": input_hash,
                "techniques": techniques,
                "parameters": parameters,
                "seed": seed,
                "text": text,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()
