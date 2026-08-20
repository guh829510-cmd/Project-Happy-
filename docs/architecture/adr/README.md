# Architecture decision records

One file per decision, numbered, never edited after acceptance — a decision that
turns out to be wrong is superseded by a later ADR rather than quietly rewritten,
because the reasoning that looked sound at the time is the useful part.

The full list of accepted decisions is the table in `../ARCHITECTURE_V2.md` §10.
A record is written here when the decision is implemented, so an ADR in this
directory describes code that exists.

| ADR | Decision | Status |
|---|---|---|
| [0002](0002-governance-kernel-is-a-mandatory-interceptor.md) | Governance kernel is a mandatory interceptor; the container never yields a raw adapter | Accepted — load-bearing |
