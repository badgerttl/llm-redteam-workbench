from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    prompt: str
    techniques: tuple[str, ...] = ()
    pipelines: tuple[tuple[str, ...], ...] = ()
    count: int = 25
    seed: int = 0
    intensity: str = "medium"
    min_chain_length: int = 1
    max_chain_length: int = 1
    profile: str = "baseline"
    profile_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GeneratedCase:
    id: str
    text: str
    techniques: tuple[str, ...]
    parameters: dict[str, Any]
    changed_positions: tuple[int, ...]
    producing_pipelines: tuple[tuple[str, ...], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RunResult:
    input_hash: str
    seed: int
    cases: tuple[GeneratedCase, ...]
    attempted: int
    skipped: tuple[dict[str, str], ...] = field(default_factory=tuple)
    errors: tuple[dict[str, str], ...] = field(default_factory=tuple)
