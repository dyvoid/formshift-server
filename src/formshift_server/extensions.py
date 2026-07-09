"""Extensions: installable module bundles running in isolated venvs (ADR 0012).

An extension is a source directory containing an ``extension.toml`` manifest
plus the Python files implementing its modules. Installation copies the source
under the server's extensions directory, creates a private venv with the
server's own interpreter, installs the extension's pinned requirements into
it, and registers one `IsolatedModule` per declared module. Runs go to a
persistent per-extension worker process (extension_runner.py) speaking
newline-delimited JSON over stdio (ADR 0015); the engine stays blind to
what's inside, exactly as with core modules.

Only ``isolation = "isolated"`` is implemented for installed extensions.
Sharing an environment (workspace grouping) is M5; anything else is an
explicit not-implemented error, never a silent shared install.
"""

from __future__ import annotations

import atexit
import base64
import json
import re
import shutil
import subprocess
import sys
import threading
import tomllib
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .modules import ModuleError, ModuleManifest, ModuleRegistry, ModuleResult, PortSpec

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_ENTRY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")

_PIP_TIMEOUT_SECONDS = 900
_RUN_TIMEOUT_SECONDS = 600

_STATE_FILE = "installed.json"
_SRC_DIR = "src"
_VENV_DIR = "venv"

_RUNNER_PATH = Path(__file__).with_name("extension_runner.py")


class ExtensionError(Exception):
    """Extension install/load failed; message is safe to surface to the client."""


class ExtensionConflictError(ExtensionError):
    """The extension, or one of its module names, is already present."""


@dataclass(frozen=True)
class ExtensionModuleSpec:
    manifest: ModuleManifest
    entry: str  # "file_module:callable" inside the extension's src directory


@dataclass(frozen=True)
class ExtensionManifest:
    name: str
    version: str
    description: str
    isolation: str
    requirements: tuple[str, ...]
    modules: tuple[ExtensionModuleSpec, ...]


def _ports(raw: Any, extension: str, module: str, direction: str) -> tuple[PortSpec, ...]:
    if not isinstance(raw, list) or not raw:
        raise ExtensionError(f"extension {extension!r} module {module!r}: no {direction} ports")
    ports = []
    for port in raw:
        if not isinstance(port, dict) or not port.get("name") or not port.get("type"):
            raise ExtensionError(
                f"extension {extension!r} module {module!r}: each {direction} port "
                "needs 'name' and 'type'"
            )
        ports.append(PortSpec(name=str(port["name"]), type=str(port["type"])))
    return tuple(ports)


def parse_extension_manifest(source: Path) -> ExtensionManifest:
    """Parse and validate ``extension.toml`` from an extension source directory."""
    manifest_path = source / "extension.toml"
    if not manifest_path.is_file():
        raise ExtensionError(f"no extension.toml in {source}")
    try:
        data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ExtensionError(f"could not read extension.toml: {exc}") from exc

    header = data.get("extension")
    if not isinstance(header, dict):
        raise ExtensionError("extension.toml has no [extension] table")
    name = str(header.get("name", ""))
    version = str(header.get("version", ""))
    if not _NAME_RE.match(name):
        raise ExtensionError(f"invalid extension name {name!r} (want {_NAME_RE.pattern})")
    if not version:
        raise ExtensionError(f"extension {name!r}: missing version")

    isolation = str(header.get("isolation", "isolated"))
    if isolation != "isolated":
        # Manifest field exists from day one (build strategy); only "isolated"
        # is implemented for installed extensions until workspace grouping (M5).
        raise NotImplementedError(
            f"extension {name!r} declares isolation={isolation!r}; "
            "only 'isolated' is implemented in this version"
        )

    requirements = header.get("requirements", [])
    if not isinstance(requirements, list) or any(not isinstance(r, str) for r in requirements):
        raise ExtensionError(f"extension {name!r}: requirements must be a list of strings")

    raw_modules = data.get("modules")
    if not isinstance(raw_modules, list) or not raw_modules:
        raise ExtensionError(f"extension {name!r} declares no modules")
    modules = []
    seen_names: set[str] = set()
    for raw in raw_modules:
        if not isinstance(raw, dict):
            raise ExtensionError(f"extension {name!r}: each module must be a [[modules]] table")
        module_name = str(raw.get("name", ""))
        entry = str(raw.get("entry", ""))
        if not module_name:
            raise ExtensionError(f"extension {name!r}: module without a name")
        if module_name in seen_names:
            # Caught at parse time so a bad manifest can never half-register.
            raise ExtensionError(f"extension {name!r}: duplicate module name {module_name!r}")
        seen_names.add(module_name)
        if not _ENTRY_RE.match(entry):
            raise ExtensionError(
                f"extension {name!r} module {module_name!r}: entry must be "
                f"'file_module:callable', got {entry!r}"
            )
        modules.append(
            ExtensionModuleSpec(
                manifest=ModuleManifest(
                    name=module_name,
                    version=version,  # module cache keys track the extension release
                    description=str(raw.get("description", "")),
                    inputs=_ports(raw.get("inputs"), name, module_name, "input"),
                    outputs=_ports(raw.get("outputs"), name, module_name, "output"),
                    isolation="isolated",
                ),
                entry=entry,
            )
        )

    return ExtensionManifest(
        name=name,
        version=version,
        description=str(header.get("description", "")),
        isolation=isolation,
        requirements=tuple(str(r) for r in requirements),
        modules=tuple(modules),
    )


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


class ExtensionWorker:
    """One long-lived runner process per extension (ADR 0015).

    Spawned lazily on first request, restarted on the next request after a
    crash or timeout. Requests are serialized on one lock: modules of one
    extension never run concurrently in it (single copy of model memory);
    different extensions' workers are independent, so cross-extension
    parallelism is unaffected.
    """

    def __init__(self, python: Path, name: str) -> None:
        self._python = python
        self._name = name
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        atexit.register(self.stop)

    def _ensure_started(self) -> subprocess.Popen[str]:
        if self._process is None or self._process.poll() is not None:
            try:
                self._process = subprocess.Popen(
                    [str(self._python), str(_RUNNER_PATH)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                )
            except OSError as exc:
                raise ModuleError(
                    f"failed to start worker for extension {self._name!r}: {exc}"
                ) from exc
        return self._process

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    def request(self, payload: dict[str, Any], *, timeout: float, context: str) -> dict[str, Any]:
        """Send one JSON request; kill and report if the worker hangs or dies."""
        with self._lock:
            process = self._ensure_started()
            stdin, stdout = process.stdin, process.stdout
            assert stdin is not None and stdout is not None
            timed_out = threading.Event()

            def kill_hung_worker() -> None:
                timed_out.set()
                process.kill()

            watchdog = threading.Timer(timeout, kill_hung_worker)
            watchdog.start()
            try:
                stdin.write(json.dumps(payload) + "\n")
                stdin.flush()
                line = stdout.readline()
            except (OSError, ValueError) as exc:
                self.stop()
                raise ModuleError(f"{context}: worker pipe failed: {exc}") from exc
            finally:
                watchdog.cancel()
            if not line:
                exit_code = process.poll()
                self.stop()
                if timed_out.is_set():
                    raise ModuleError(f"{context}: timed out after {timeout:.0f}s")
                raise ModuleError(f"{context}: worker exited with {exit_code}")
            try:
                response: dict[str, Any] = json.loads(line)
            except ValueError as exc:
                self.stop()  # protocol out of sync; start clean next time
                raise ModuleError(f"{context}: worker returned invalid output") from exc
            return response


class IsolatedModule:
    """Module protocol adapter: runs execute in the extension's worker process."""

    def __init__(
        self, manifest: ModuleManifest, entry: str, src_dir: Path, worker: ExtensionWorker
    ) -> None:
        self.manifest = manifest
        self._entry = entry
        self._src_dir = src_dir
        self._worker = worker

    def run(
        self, inputs: dict[str, bytes], params: dict[str, Any], *, draft: bool = False
    ) -> dict[str, ModuleResult]:
        response = self._worker.request(
            {
                "src": str(self._src_dir),
                "entry": self._entry,
                "inputs": {
                    port: base64.b64encode(data).decode("ascii") for port, data in inputs.items()
                },
                "params": params,
                "draft": draft,
            },
            timeout=_RUN_TIMEOUT_SECONDS,
            context=f"module {self.manifest.name!r}",
        )
        if not response.get("ok"):
            raise ModuleError(f"module {self.manifest.name!r} failed: {response.get('error')}")
        return {
            port: ModuleResult(type=out["type"], data=base64.b64decode(out["data"]))
            for port, out in response["outputs"].items()
        }


@dataclass(frozen=True)
class InstalledExtension:
    manifest: ExtensionManifest
    root: Path  # extensions_dir/<name>, containing src/, venv/, installed.json


class ExtensionManager:
    """Installs extensions into per-extension venvs and registers their modules."""

    def __init__(self, extensions_dir: Path, registry: ModuleRegistry) -> None:
        self._dir = extensions_dir
        self._registry = registry
        self._installed: dict[str, InstalledExtension] = {}

    def installed(self) -> list[InstalledExtension]:
        return list(self._installed.values())

    def install(self, source: Path) -> InstalledExtension:
        """Install from a source directory: copy, venv, pip, register. Synchronous."""
        source = source.expanduser().resolve()
        if not source.is_dir():
            raise ExtensionError(f"extension source {source} is not a directory")
        manifest = parse_extension_manifest(source)
        if manifest.name in self._installed:
            raise ExtensionConflictError(f"extension {manifest.name!r} is already installed")
        for spec in manifest.modules:
            # Check collisions before the expensive venv work, so a failed
            # install never leaves a partially-registered extension behind.
            if self._registry.get(spec.manifest.name) is not None:
                raise ExtensionConflictError(
                    f"module {spec.manifest.name!r} is already registered"
                )

        root = self._dir / manifest.name
        if root.exists():
            raise ExtensionConflictError(
                f"extension directory {root} already exists (remove it to reinstall)"
            )
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, root / _SRC_DIR)
            self._create_venv(manifest, root / _VENV_DIR)
            state = {"installed_with": sys.version, "manifest_source": "extension.toml"}
            (root / _STATE_FILE).write_text(json.dumps(state), encoding="utf-8")
        except (ExtensionError, OSError) as exc:
            shutil.rmtree(root, ignore_errors=True)  # no half-installed leftovers
            if isinstance(exc, ExtensionError):
                raise
            raise ExtensionError(f"could not install {manifest.name!r}: {exc}") from exc

        return self._register(manifest, root)

    def load_installed(self) -> list[InstalledExtension]:
        """Register every completely-installed extension under the extensions directory."""
        loaded: list[InstalledExtension] = []
        if not self._dir.is_dir():
            return loaded
        for root in sorted(p for p in self._dir.iterdir() if p.is_dir()):
            if root.name in self._installed or not (root / _STATE_FILE).is_file():
                continue  # never installed to completion; ignore debris
            manifest = parse_extension_manifest(root / _SRC_DIR)
            loaded.append(self._register(manifest, root))
        return loaded

    def _register(self, manifest: ExtensionManifest, root: Path) -> InstalledExtension:
        # One worker per extension, shared by all its modules (ADR 0015).
        worker = ExtensionWorker(_venv_python(root / _VENV_DIR), manifest.name)
        for spec in manifest.modules:
            self._registry.register_isolated(
                IsolatedModule(spec.manifest, spec.entry, root / _SRC_DIR, worker)
            )
        installed = InstalledExtension(manifest=manifest, root=root)
        self._installed[manifest.name] = installed
        return installed

    def _create_venv(self, manifest: ExtensionManifest, venv_dir: Path) -> None:
        # The venv gets the server's own interpreter version; pip only exists
        # (and only runs) when there is something to install.
        try:
            venv.create(venv_dir, with_pip=bool(manifest.requirements))
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ExtensionError(f"could not create venv for {manifest.name!r}: {exc}") from exc
        if not manifest.requirements:
            return
        command = [
            str(_venv_python(venv_dir)),
            "-m",
            "pip",
            "install",
            "--no-input",
            "--disable-pip-version-check",
            "--quiet",
            *manifest.requirements,
        ]
        try:
            proc = subprocess.run(
                command, capture_output=True, timeout=_PIP_TIMEOUT_SECONDS, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise ExtensionError(
                f"dependency install for {manifest.name!r} timed out "
                f"after {_PIP_TIMEOUT_SECONDS}s"
            ) from exc
        if proc.returncode != 0:
            stderr_tail = proc.stderr.decode(errors="replace").strip()[-2000:]
            raise ExtensionError(
                f"dependency install for {manifest.name!r} failed "
                f"(exit {proc.returncode}): {stderr_tail}"
            )
