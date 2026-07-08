"""Module contract: manifests, the module protocol, and the registry.

A module is defined purely by its I/O type contract (design doc, Modules).
The engine sees manifests and bytes; internals are a black box. Core modules
implement the Python protocol below and dispatch in-process (transport tier 1);
out-of-process tiers arrive in later milestones behind the same manifest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class PortSpec:
    name: str
    type: str  # type string, e.g. "raster/png" — open namespace, strict matching


@dataclass(frozen=True)
class ModuleManifest:
    name: str
    version: str
    description: str
    inputs: tuple[PortSpec, ...]
    outputs: tuple[PortSpec, ...]
    # Isolation is part of the manifest contract from day one (build strategy);
    # "core" is the only implemented value. Anything else must be rejected
    # explicitly, never silently accepted.
    isolation: str = "core"

    def input_port(self, name: str) -> PortSpec | None:
        return next((p for p in self.inputs if p.name == name), None)

    def output_port(self, name: str) -> PortSpec | None:
        return next((p for p in self.outputs if p.name == name), None)


@dataclass(frozen=True)
class ModuleResult:
    """One output port's produced value."""

    type: str
    data: bytes


class Module(Protocol):
    manifest: ModuleManifest

    def run(self, inputs: dict[str, bytes], params: dict[str, Any]) -> dict[str, ModuleResult]:
        """Execute with all input ports materialized; return one result per output port."""
        ...


class ModuleError(Exception):
    """A module failed to execute; message is safe to surface to the client."""


@dataclass
class ModuleRegistry:
    _modules: dict[str, Module] = field(default_factory=dict)

    def register(self, module: Module) -> None:
        manifest = module.manifest
        if manifest.isolation != "core":
            raise NotImplementedError(
                f"module {manifest.name!r} declares isolation={manifest.isolation!r}; "
                "only 'core' is implemented in this version"
            )
        if manifest.name in self._modules:
            raise ValueError(f"module {manifest.name!r} already registered")
        self._modules[manifest.name] = module

    def get(self, name: str) -> Module | None:
        return self._modules.get(name)

    def manifests(self) -> list[ModuleManifest]:
        return [m.manifest for m in self._modules.values()]
