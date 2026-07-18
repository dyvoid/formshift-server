# ADR 0019: Auto-scan an extension source directory on boot

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

The server's `--extensions-dir` (ADR 0013) holds installed extensions: each subdirectory contains
`src/`, `venv/`, and an `installed.json` state file. On boot, `load_installed()` walks the dir and
registers anything with a state file. A directory dropped in without going through the install API
is silently skipped (no state file).

The dev workflow today is: boot the server with `--extensions-dir`, then `POST /v1/extensions`
once with `{"path": "<dev checkout>"}` to install it. After that it auto-loads on every boot.
This works but is awkward for the "drop a folder in a directory and it shows up" workflow that's
natural for development and testing — especially with ADR 0017's rule that extension repos are
independent, so a developer commonly has several local checkouts they want to swap in and out.

The friction is real but small. The current mechanism is correct for production (installed
extensions have venvs and state; auto-installing arbitrary source on boot would conflate "installed"
with "lying around"). The question is whether to add a separate, clearly-labeled dev path.

## Decision

Add a separate CLI flag, e.g. `--extensions-source-dir`, distinct from `--extensions-dir`. On
boot, the server scans that directory for subdirectories containing `extension.toml` and
auto-installs them (creating the venv, registering modules) before serving requests. No
`installed.json` required — presence of `extension.toml` is the trigger.

Key properties:

- **Separate flag, not a mode of `--extensions-dir`.** Conflating installed and source dirs would
  make "what's actually running" ambiguous. Two flags, two clear meanings: `--extensions-dir` for
  installed state, `--extensions-source-dir` for dev source that gets installed on boot.
- **Installed into `--extensions-dir`.** Auto-scan installs *into* the install dir (creating the
  venv there), so the dev source dir stays clean checkouts and the install dir stays the runtime
  state. Re-booting re-installs if the install dir was cleared, or skips if already present.
- **Reinstall detection.** If a source extension's `extension.toml` version bumps, the server
  reinstalls (venv recreated, modules re-registered). If unchanged, skip. This lets a developer
  bump version to force a clean reinstall.
- **Failure is loud.** A bad manifest or failed venv creation in source-dir mode fails server
  startup with a clear error, rather than silently skipping — same as the existing
  corrupted-extension-dir behavior (PICKUP notes, 2026-07-09). Dev workflows benefit from loud
  failures, not silent skips.
- **Off by default.** Both flags are opt-in; the server ships with nothing installed and no source
  dir scanned.

## Consequences

- Dev workflow becomes: point `--extensions-source-dir` at a folder of extension checkouts, boot
  the server, done. No per-extension `POST /v1/extensions` step.
- The "what's running" question stays answerable: `--extensions-dir` is the source of truth for
  installed state, `--extensions-source-dir` is a dev convenience that installs into it.
- New CLI flag is new contract surface (the server's startup contract). Per AGENTS.md this is why
  the ADR exists.
- Reinstall-on-version-bump is a heuristic, not a guarantee — a developer who changes source
  without bumping version won't see the change picked up unless they clear the install dir. This
  is a known trade-off; the alternative (hash the source tree on every boot) is expensive and
  fragile. Documented in CLI help.
- No effect on the manifest format, isolation model, install API, or worker lifecycle. This is a
  boot-time convenience layer over the existing install machinery.
- Pairs naturally with ADR 0018 (git install): a dev workflow could clone several extension repos
  into a source dir and boot the server with `--extensions-source-dir` pointing at it. The two
  ADRs are independent but complementary.
- Production deployments would not use `--extensions-source-dir`; they'd install via the API
  (with `path` or `git`) into `--extensions-dir` and let `load_installed()` handle boot. The
  source-dir flag is a dev affordance, not a production path.
