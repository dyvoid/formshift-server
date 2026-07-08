# ADR 0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-07-08

## Context

This project is developed with AI assistance. An AI agent (or a new contributor) reading the code
has no access to the conversations where decisions were made. Without a written record, deliberate
choices look like arbitrary ones, and get silently undone in the next refactor.

This is especially sharp for this server: the Build Strategy section of
[Design](../architecture/design.md)
distinguishes contracts (protocol, manifest format, type strings, session/auth semantics — final
shape from day one, evolved additively only) from implementations behind them (minimal, stubbed,
filled in linearly). An ADR is how a contract decision gets frozen on record, and how a future
agent tells "the shape is deliberate" apart from "nobody's gotten to this yet."

## Decision

We record significant architecture decisions as ADRs in `docs/adr/`, numbered sequentially. Each
captures the context, the decision, and the consequences. AGENTS.md instructs agents not to change
architecture, and specifically not to freeze or alter any contract surface, without adding one.

## Consequences

- Decisions are durable and discoverable; the reasoning survives past the chat that produced it.
- There's a small overhead per decision. Worth it for anything an agent might otherwise reverse,
  and especially for anything that becomes a forward-only contract once shipped.
- Superseded decisions stay in the log with status `Superseded by ADR XXXX`, not deleted.

---

<!-- Copy the block below for each new decision. Number sequentially. -->

## Template (copy for new ADRs)

```
# ADR NNNN: <short title>

- **Status:** Proposed | Accepted | Superseded by ADR XXXX
- **Date:** YYYY-MM-DD

## Context
What forces are at play? What problem or constraint prompted this?

## Decision
What we decided, stated plainly.
For Proposed ADRs, describe the option under consideration, not a final decision.

## Consequences
What this makes easier, harder, or rules out. Include the trade-offs you accepted.
```

> **Note on `Proposed` status:** ADRs are not just for decisions already made. A `Proposed` ADR is
> the right place to capture full context for a feature under consideration — before the decision
> is taken. Link to it from `docs/ROADMAP.md`. When the decision is made, flip the status to
> `Accepted` (or `Rejected`, with a note on why) and update the ROADMAP entry accordingly.
