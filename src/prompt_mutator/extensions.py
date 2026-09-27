from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points

from .transforms import Transform


ENTRY_POINT_GROUP = "prompt_mutator.transforms"


@dataclass(frozen=True, slots=True)
class ExtensionInfo:
    name: str
    package: str
    version: str

    def resolved(self) -> dict[str, str]:
        return {"name": self.name, "package": self.package, "version": self.version}


def discover_extensions() -> tuple[ExtensionInfo, ...]:
    return tuple(_info(point) for point in _entry_points())


def load_extensions(names: tuple[str, ...]) -> tuple[dict[str, Transform], tuple[ExtensionInfo, ...]]:
    available = {point.name: point for point in _entry_points()}
    loaded: dict[str, Transform] = {}
    details: list[ExtensionInfo] = []
    for name in names:
        point = available.get(name)
        if point is None:
            raise ValueError(f"extension is not installed: {name}")
        candidate = point.load()
        transform = candidate if callable(candidate) else getattr(candidate, "transform", None)
        if not callable(transform):
            raise ValueError(f"extension does not expose a callable transform: {name}")
        loaded[name] = transform
        details.append(_info(point))
    return loaded, tuple(details)


def _entry_points() -> tuple[EntryPoint, ...]:
    return tuple(entry_points(group=ENTRY_POINT_GROUP))


def _info(point: EntryPoint) -> ExtensionInfo:
    distribution = getattr(point, "dist", None)
    package = getattr(distribution, "name", None) or point.module.split(".")[0]
    version = getattr(distribution, "version", None) or "unknown"
    return ExtensionInfo(point.name, package, version)
