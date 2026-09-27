from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    version: int
    techniques: tuple[str, ...]
    count: int
    intensity: str
    min_chain_length: int
    max_chain_length: int
    source: str

    def resolved(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "techniques": list(self.techniques),
            "count": self.count,
            "intensity": self.intensity,
            "min_chain_length": self.min_chain_length,
            "max_chain_length": self.max_chain_length,
            "source": self.source,
        }


def load_profile(name: str = "baseline", explicit: Path | None = None) -> Profile:
    if explicit is not None:
        return _read_profile(Path(explicit), expected_name=None)
    candidates = [Path.cwd() / ".prompt-mutator" / "profiles" / f"{name}.toml"]
    try:
        from platformdirs import user_config_path

        candidates.append(Path(user_config_path("prompt-mutator", appauthor=False)) / "profiles" / f"{name}.toml")
    except ImportError:
        candidates.append(Path.home() / ".config" / "prompt-mutator" / "profiles" / f"{name}.toml")
    for candidate in candidates:
        if candidate.is_file():
            return _read_profile(candidate, expected_name=name)
    resource = files("prompt_mutator").joinpath("builtin_profiles", f"{name}.toml")
    if not resource.is_file():
        raise ValueError(f"unknown profile: {name}")
    data = tomllib.loads(resource.read_text(encoding="utf-8"))
    return _from_data(data, f"builtin:{name}", expected_name=name)


def available_profiles() -> tuple[Profile, ...]:
    """Return effective named profiles after applying normal lookup precedence."""
    names: set[str] = set()
    builtin_directory = files("prompt_mutator").joinpath("builtin_profiles")
    names.update(
        item.name.removesuffix(".toml")
        for item in builtin_directory.iterdir()
        if item.is_file() and item.name.endswith(".toml")
    )
    search_directories = [Path.cwd() / ".prompt-mutator" / "profiles"]
    try:
        from platformdirs import user_config_path

        search_directories.append(Path(user_config_path("prompt-mutator", appauthor=False)) / "profiles")
    except ImportError:
        search_directories.append(Path.home() / ".config" / "prompt-mutator" / "profiles")
    for directory in search_directories:
        if directory.is_dir():
            names.update(path.stem for path in directory.glob("*.toml") if path.is_file())
    preferred = {name: index for index, name in enumerate(("baseline", "unicode", "encoding", "comprehensive", "chained"))}
    ordered = sorted(names, key=lambda name: (preferred.get(name, len(preferred)), name))
    return tuple(load_profile(name) for name in ordered)


def _read_profile(path: Path, expected_name: str | None) -> Profile:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read profile {path}: {exc}") from exc
    return _from_data(data, str(path.resolve()), expected_name)


def _from_data(data: dict[str, Any], source: str, expected_name: str | None) -> Profile:
    try:
        name = str(data["name"])
        version = int(data["version"])
        techniques = tuple(str(item) for item in data["techniques"])
        count = int(data.get("count", 25))
        intensity = str(data.get("intensity", "medium"))
        min_chain_length = int(data.get("min_chain_length", 1))
        max_chain_length = int(data.get("max_chain_length", 1))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid profile {source}: {exc}") from exc
    if expected_name is not None and name != expected_name:
        raise ValueError(f"profile name {name!r} does not match requested name {expected_name!r}")
    if (
        version < 1
        or count < 1
        or intensity not in {"low", "medium", "high", "max"}
        or not 1 <= min_chain_length <= max_chain_length <= 3
    ):
        raise ValueError(f"invalid profile settings in {source}")
    return Profile(
        name,
        version,
        techniques,
        count,
        intensity,
        min_chain_length,
        max_chain_length,
        source,
    )
