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

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        """Execute with all input ports materialized; return one result per output port.

        A module with no special draft behavior ignores `draft` and runs at
        full cost — the defined behavior (design doc, Draft and quality modes).
        """
        ...


class ModuleError(Exception):
    """A module failed to execute; message is safe to surface to the client."""


@dataclass
class ModuleRegistry:
    _modules: dict[str, Module] = field(default_factory=dict)

    def register(self, module: Module) -> None:
        """Register an in-process module. Its manifest must declare isolation="core"."""
        manifest = module.manifest
        if manifest.isolation != "core":
            raise NotImplementedError(
                f"module {manifest.name!r} declares isolation={manifest.isolation!r}; "
                "in-process registration only implements 'core'"
            )
        self._add(module)

    def register_isolated(self, module: Module) -> None:
        """Register a module backed by an isolated environment (extensions.IsolatedModule).

        Kept separate from `register` so an isolation declaration is honored by
        construction: in-process modules can't claim isolation, and isolated
        backends can't be registered as core (ADR 0012).
        """
        manifest = module.manifest
        if manifest.isolation != "isolated":
            raise NotImplementedError(
                f"module {manifest.name!r} declares isolation={manifest.isolation!r}; "
                "isolated registration only implements 'isolated'"
            )
        self._add(module)

    def _add(self, module: Module) -> None:
        name = module.manifest.name
        if name in self._modules:
            raise ValueError(f"module {name!r} already registered")
        self._modules[name] = module

    def unregister(self, name: str) -> None:
        """Remove a module if present (rollback of a failed extension install)."""
        self._modules.pop(name, None)

    def get(self, name: str) -> Module | None:
        return self._modules.get(name)

    def manifests(self) -> list[ModuleManifest]:
        return [m.manifest for m in self._modules.values()]
