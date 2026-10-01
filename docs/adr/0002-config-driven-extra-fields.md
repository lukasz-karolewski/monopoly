---
status: accepted
date: 2026-10-01
supersedes:
superseded-by:
---

# 0002. Config-driven extra fields, kept out of transactions and the safety check

## Context

Statements print useful one-off values that are not transactions: Chase
Ultimate Rewards points, credit limit, minimum payment, APR. Each existing
non-transaction value (statement date, `period_start_pattern`,
`account_pattern`, `PaymentSummaryConfig`) is a dedicated `StatementConfig`
field plus dedicated extraction code, so every new value means a core change.
Users asked for a way to extract "arbitrary stuff" per bank without that.

Constraints: fully backward compatible (no change to the CSV columns, the
`--format json` envelope or `SCHEMA_VERSION`), and a bad regex must never stop a
statement from parsing.

## Decision

Add a frozen `ExtraField(name, pattern, type)` dataclass and an
`extra_fields: list[ExtraField]` on `StatementConfig`, defaulting to empty.
The pattern must expose a `(?P<value>...)` group (validated at construction);
`type` is one of `str`, `int`, `decimal`, `date`.

`BaseStatement.extras` searches each pattern against the full `raw_text` of
every page (so labels may wrap across lines), takes the first match and coerces
it: `int`/`decimal` drop thousands separators, whitespace and currency symbols;
`date` reuses `dateparser` with the config's `statement_date_order`. No match →
the key is omitted; a coercion failure → a warning and the key is omitted. It
never raises.

Extras do not participate in `perform_safety_check`, are not written to the CSV
and are not part of the versioned JSON envelope. They are exposed via
`Pipeline.extract_extras()`, shown in `--pprint` when non-empty, and written by
the opt-in `--extras` flag to a `<output-stem>.extras.json` sidecar
(`{bank, statement_date, extras}`, with `Decimal`/`date` as strings).

Chase credit is the first user: `points_start` and `points_end`.

## Alternatives considered

- **Dedicated fields per value (e.g. `points_start_pattern`).** Rejected: every
  new value is a core change, which is exactly what users asked to avoid.
- **Add extras to the JSON envelope now.** Rejected for now: names are
  free-form per bank, so they would be an untyped, unversioned blob inside a
  versioned contract (see ADR 0001). The sidecar keeps the contract stable; this
  can be revisited as an additive optional `extras` key.
- **Include extras in the safety check.** Rejected: labels are best-guess and
  vary by vintage; a mismatch must degrade to a missing key, not a failed parse.
- **A user-supplied YAML `--extras-config`.** Deferred as a follow-up: it would
  let users add fields without editing bank classes, but adds a config format,
  loading and validation surface we do not need yet.

## Consequences

Easier: any bank can extract a new value by adding one `ExtraField` to its
config, with no core changes, and existing output is unchanged.

Harder / given up: extras are untyped from a consumer's point of view (names and
types are per-bank conventions, not a schema), and a regex that silently stops
matching on a new statement vintage just drops the key rather than failing
loudly. Fields still live in the Python bank classes, so users cannot add one
without editing or subclassing a bank — the trigger for the YAML follow-up.
