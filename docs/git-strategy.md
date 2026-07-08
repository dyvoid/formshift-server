# Git Strategy for Formshift Server

## Core Approach: Trunk-Based Development

Single `main` branch. Short-lived branches (hours, not days). Everything merges fast or gets scrapped.

Direct commits to `main` are the exception, not the norm -- see [Branch Protection](#branch-protection)
for the two cases where they're allowed.

---

## Branch Naming

```
main
task/dag-executor-topo-sort
experiment/shared-memory-transport
fix/cache-key-hash-chain-order
```

---

## Merging

- **Fast-forward only** -- no merge commits, keeps history linear
- **Rebase onto `main`** before merging, never merge `main` into your branch
- **No squashing** -- each atomic commit is a meaningful unit; squashing destroys the audit trail

---

## Commits

One commit = one AI task or prompt session. Keep commits atomic and scoped.

AI-generated code has no inherent intent -- the commit message is the only record of *why* this code
exists. Use [Conventional Commits](https://www.conventionalcommits.org):

```
feat(executor): topologically walk multi-node graphs
fix(cache): include input order in multi-input hash key
chore(deps): update uv lockfile
```

Annotate AI-assisted commits in the body, not the subject, to keep the subject readable:

```
feat(executor): topologically walk multi-node graphs

ai-assisted: <model>
```

---

## Feature Flags

Use feature flags to manage incomplete work on `main`. Without them, trunk-based development forces a
choice between blocking merges until a feature is done or shipping incomplete code. Feature flags
remove that tradeoff: merge when the code is safe, release when the feature is ready.

---

## Generated Sources

Do not commit generated source files. They create noisy diffs and painful merge conflicts. Commit
lockfiles for reproducibility; regenerate everything else from source.

---

## Code Review

Review diffs skeptically -- AI code looks clean but can be subtly wrong.

High-blast-radius files always get manual review:

- `.gitignore`
- Anything touching secrets, auth, or permissions (this server's token auth and Host/Origin
  allowlisting are security-load-bearing even on localhost — see the Security section of
  [Design](architecture/design.md))
- CI/CD config
- Any change to a frozen contract surface (HTTP API shape, module manifest format, type-string
  registry, session semantics) -- these should already have an ADR; review the ADR, not just the diff

---

## CI

CI is load-bearing for trunk-based development -- slow or weak pipelines break the entire strategy.

Before anything merges to `main`:

- All existing tests must pass
- New code must be covered by tests -- AI optimizes for code that *looks* correct, not code that *is* correct
- Build must succeed
- Lint (`ruff`) and type-check (`mypy`) must pass

---

## Branch Protection

Enforce the strategy at the repo level on GitHub:

- No direct push to `main`, with two exceptions:
  - Non-functional changes (documentation, comments, formatting) that touch no runtime behavior
  - The user has explicitly authorized a direct commit to `main` for this change
- Neither exception is a standing default -- re-evaluate every time. When in doubt, branch.
- Require fast-forward / rebase-based merges
- Require CI to pass before merge

---

## Versioning

Tag meaningful milestones (M0, M1, M2... per `docs/ROADMAP.md`), plus semantic-version tags once the
server has an external consumer beyond Vector (post-M5). Pre-M5, milestone tags are sufficient.
