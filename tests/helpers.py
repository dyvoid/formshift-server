"""Test doubles: simple counting modules over a fake "text/plain" type."""

from __future__ import annotations

from typing import Any

from formshift_server.modules import ModuleManifest, ModuleResult, PortSpec

TEXT = "text/plain"


class UpperModule:
    """One input, one output: uppercases text. Counts its runs."""

    def __init__(self) -> None:
        self.manifest = ModuleManifest(
            name="test.upper",
            version="1.0",
            description="uppercase text",
            inputs=(PortSpec("text", TEXT),),
            outputs=(PortSpec("text", TEXT),),
        )
        self.runs = 0

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        self.runs += 1
        return {"text": ModuleResult(type=TEXT, data=inputs["text"].upper())}


class SuffixModule:
    """One input, one output: appends params["suffix"]. Counts its runs."""

    def __init__(self) -> None:
        self.manifest = ModuleManifest(
            name="test.suffix",
            version="1.0",
            description="append a suffix",
            inputs=(PortSpec("text", TEXT),),
            outputs=(PortSpec("text", TEXT),),
        )
        self.runs = 0

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        self.runs += 1
        suffix = str(params.get("suffix", "")).encode()
        return {"text": ModuleResult(type=TEXT, data=inputs["text"] + suffix)}


class ConcatModule:
    """Two inputs, one output: a + b. Order-sensitive by construction."""

    def __init__(self) -> None:
        self.manifest = ModuleManifest(
            name="test.concat",
            version="1.0",
            description="concatenate two texts",
            inputs=(PortSpec("a", TEXT), PortSpec("b", TEXT)),
            outputs=(PortSpec("text", TEXT),),
        )
        self.runs = 0

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        self.runs += 1
        return {"text": ModuleResult(type=TEXT, data=inputs["a"] + inputs["b"])}
