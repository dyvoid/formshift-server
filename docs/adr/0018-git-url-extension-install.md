# ADR 0018: Git-URL extension install

- **Status:** Accepted
- **Date:** 2026-07-18

## Context

The extensions API (ADR 0013) installs from a local source directory:
`POST /v1/extensions` with `{"path": "<dir>"}`. The server copies the source, creates an isolated
venv, pip-installs requirements, and registers the modules.

ADR 0017 records that domain extensions live in their own git repositories. Under that rule,
installing an extension today requires the client to clone the repo first and then post the local
path. That works but pushes a step onto every client that should be the server's concern: the
extension's canonical home is a git URL, and "install from git" is the natural operation.

Without this, the install story is inconsistent with the repo-organization rule: extensions live
in git repos (ADR 0017), but the install API only speaks local paths (ADR 0013). The gap is
mechanical, not architectural — the install machinery after source acquisition is unchanged.

## Decision

Add a git source form to `POST /v1/extensions`. The request accepts either:

- `{"path": "<local dir>"}` — existing behavior, unchanged.
- `{"git": "<url>", "ref": "<optional>"}` — new. Server clones the URL (default ref or pinned
  ref) to a temp directory, then runs the same install path as `path`. Temp directory is removed
  after install regardless of success or failure.

No other fields change. The response shape is unchanged. `path` and `git` are mutually exclusive;
sending both is a 400.

The clone uses the server's own git, not a Python git library — keep the dependency surface flat.
Auth (private repos) is out of scope for the first cut; public repos only. Private-repo auth is a
follow-up if a real consumer needs it, and would likely involve a server-side credential config
rather than embedding secrets in the request body.

## Consequences

- Install provenance matches the repo-organization rule (ADR 0017): an extension's canonical home
  is a git URL, and the API can install directly from it.
- The local-path form stays first-class — essential for dev workflows (uncommitted changes,
  testing a branch before pushing) and for airgapped environments where git isn't reachable.
- New contract surface on `POST /v1/extensions`: a `git` field and an optional `ref` field. Per
  AGENTS.md this is why the ADR exists; the field shape needs to be frozen deliberately.
- Server gains a runtime dependency on `git` being on PATH. Documented in CLI help; failure is a
  clear 422 at install time, not a silent misbehavior.
- Clone happens synchronously inside the existing install lock (ADR 0013's synchronous install
  trade-off applies). Large repos with full history could be slow; shallow clone (`--depth 1`) is
  the obvious mitigation and probably the default.
- No effect on the manifest format, isolation model, or worker lifecycle. The source-acquisition
  step is the only new code; everything after is reused.
- Discovery (searching a registry, listing available extensions) remains out of scope, per
  ADR 0017. This ADR is about installing from a known URL, not finding URLs to install from.
