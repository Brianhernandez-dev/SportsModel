# NFL Historical-Market Provider Amendment 0.2.5 — Draft

**DRAFT — NOT ACTIVE — NOT ACQUISITION AUTHORITY**

Draft identity: `nfl_historical_market_provider_amendment_0.2.5_draft`

Parent protocol: `nfl_historical_market_research_0.2.5`

This draft neither replaces nor modifies the frozen base protocol. It does not
change model hypotheses, cohorts, thresholds, statistical decision rules,
settlement mathematics, or leakage controls. It does not authorize provider
access, purchase, acquisition, persistence, normalization, joining, analysis, or
production execution. It cannot be cited as an active analysis-bundle component.

Revision note (2026-10-01): pre-revision SHA-256 was
`C6A8C74658CE46BB27E2FD2ED5046EF4FA20A3066BBEA1DF94FDCB8ECC1884A8`.
Kickoff authority is supplied by the sufficient external reconciliation package
`NFL_Kickoff_Authority_Reconciliation_0.2.0.zip` (SHA-256
`2422D97F2A21D9171286AD6F62D5F7D1957993476872AAD936DC627474A2D971`)
and authority ledger SHA-256
`4A1C2962FF2526924FFA8AFC0275788B423B4848318043609BFF194C0049063D`.

Pilot-design 0.1.2 correction note (2026-10-01): the immediately preceding
candidate SHA-256 was
`4AC83B24C11E886225BC599F5CAAE3328CDEF1A6FECE780E7F49695CFB6661D0`.
This draft remains inactive; the correction narrows pilot claims and makes
historical market-level `last_update` field presence explicitly empirical.

## 1. Evidence basis and status

This draft operationalizes only provider-specific parameters supported by:

- `docs/architecture/nfl_historical_market_provider_feasibility_2026-09-28.md`;
- provider correspondence supplied by the project owner on 2026-09-14;
- The Odds API official public documentation retrieved 2026-09-28 and rechecked
  2026-09-29; and
- the frozen protocol and repository governance boundary.

All correspondence facts are paraphrases, not direct quotations. This draft must
receive independent review, have every unresolved normative parameter completed,
be assigned a non-draft immutable identity and hash, and receive an explicit
freeze record before it can become active.

Correspondence-only paraphrases must not be the sole normative authority for a
final rule unless the underlying original correspondence is retained as
immutable evidence. Final normative authority should come, wherever possible,
from retained official public documentation and/or immutable bounded-pilot
evidence. Facts needed only as context may remain non-normative.

## 2. Draft provider selection

Candidate provider: The Odds API V4.

Candidate source identity:

```text
provider_name = the_odds_api
api_version = v4
sport_key = americanfootball_nfl
endpoint_family = /v4/historical/sports/{sport}/odds
market = h2h
odds_format = decimal
```

Decimal is the candidate canonical acquisition format because observations before
2022-09-18 were originally captured only as decimal odds. Any American odds for
that period are provider-derived and may contain rounding differences. Derived
American prices must never replace the retained decimal source values.

Historical event-odds is not the candidate acquisition endpoint for the primary
featured `h2h` market because the featured historical odds endpoint is simpler
and avoids the event-level credit multiplier.

## 3. Historical scope

The source advertises NFL historical availability beginning
`2020-06-06T10:05:00Z`. The parent protocol controls the actual eligible
population: the frozen Phase 4C1A historical probability evidence and its
2021–2025 cohort roles. This amendment must not synthesize games, widen seasons,
or treat provider availability as canonical population authority.

## 4. Timestamp mapping

For each canonical target game:

```text
requested_date = authoritative historical canonical kickoff - 60 minutes
```

The following roles are distinct:

| Role | Field/source | Draft rule |
| --- | --- | --- |
| Requested decision time | Request `date` | Exact protocol T-60 in UTC. |
| Returned provider snapshot | Response wrapper `timestamp` | Must be the provider snapshot equal to or earlier than requested T-60. |
| Adjacent provider snapshots | `previous_timestamp`, `next_timestamp` | Retain when supplied; neither replaces the selected snapshot. |
| Historical bookmaker-market observation | Market-level `last_update` | Candidate authoritative quote/update timestamp based on retained official documentation and provider correspondence; sampled historical presence and behavior remain subject to the bounded pilot. |
| Retrieval | SportsModel response-receipt time | Acquisition provenance only. |
| Request start | SportsModel request-start time | Acquisition provenance only. |
| Provider kickoff | Event `commence_time` | Reconciliation evidence only; cannot override canonical historical schedule authority. |
| Bookmaker update | Bookmaker-level `last_update` | Deprecated and non-authoritative. |

For an observation containing a valid market-level `last_update`, eligibility
requires:

```text
response.timestamp <= requested_date
market.last_update <= requested_date
snapshot_age = requested_date - market.last_update
snapshot_age <= maximum_snapshot_age
```

If a selected bookmaker/market is present but market-level `last_update` is
missing or type-invalid, the affected observation fails closed as
`MARKET_TIMESTAMP_FIELD_MISSING_OR_INVALID` and is timestamp-ineligible. Retain
the raw response and any bookmaker-level `last_update`, but treat the latter as
non-authoritative contextual evidence only and never substitute it. This
condition may require revision of this amendment.

Market-level `last_update` is therefore the candidate authoritative historical
market timestamp based on retained official documentation and provider
correspondence. The bounded pilot must establish its actual presence and
behavior across the sampled historical response set.

`maximum_snapshot_age` is unresolved. The final value must be selected
outcome-blind from documented cadence and bounded-pilot age/coverage evidence.

The exact simultaneous-observation tie-break is unresolved. It must be frozen as
one deterministic rule using adequate outcome-blind evidence. The bounded pilot
may describe the response shape only if simultaneous observations naturally
occur; absence must be reported as `NOT_OBSERVED_IN_PILOT`, not
`DOES_NOT_OCCUR`. No result or performance information may inform the rule.

## 5. Provider event and canonical identity

Retain provider event ID, sport key, participants, orientation, `commence_time`,
requested date, and response wrapper timestamps for every acquired observation.
Map only to an existing canonical SportsModel NFL game under the parent
protocol's fail-closed identity and historical kickoff-version rules.

Provider correspondence reports that `commence_time` may change for reschedules
and that the provider's event-ID replacement threshold was once as low as about
eight hours and is currently 24 hours. Those values are provider behavior, not a
SportsModel matching tolerance, and remain contextual unless stronger retained
evidence is accepted. One T-60 call per game cannot certify replacement or
stability across historical revisions. Ambiguous, conflicting, replacement, or
insufficiently proven identities must be excluded, never heuristically repaired.

## 6. Bookmaker universe and coverage

Candidate books for the bounded feasibility pilot are:

```text
draftkings
fanduel
betmgm
betrivers
```

Current public listing confirms current presence. Correspondence reports
continuous historical coverage, but no season-by-season table was provided.
Therefore:

- no final designated book is selected;
- no final consensus universe is selected;
- no book may enter a frozen universe solely because it is currently listed;
- no game-by-game shrinking or substitution is permitted after a universe is
  frozen; and
- the final choice must use only outcome-blind coverage, timestamp, continuity,
  licensing, reliability, and reproducibility evidence.

The exact reference-market construction remains unresolved among the three
methods bounded by the parent protocol.

## 7. Missing, stale, suspended, and incomplete markets

Market-level `last_update` stops advancing when a market is suspended or closed,
and public documentation says the market is removed after about 15 minutes.
Accordingly:

- retain and evaluate the actual market-level `last_update`;
- when it is missing or type-invalid, retain the full raw response, classify the
  affected observation `MARKET_TIMESTAMP_FIELD_MISSING_OR_INVALID`, mark it
  timestamp-ineligible, and record the schema/coverage deficiency;
- retain bookmaker-level `last_update`, if returned, only as descriptive,
  non-authoritative schema evidence; it is never a fallback and cannot make an
  observation timestamp-eligible;
- never equate response-wrapper time with a fresh book quote;
- reject observations older than the eventually frozen
  `maximum_snapshot_age`;
- do not impute missing sides or books;
- require both full-game `h2h` sides from a book in one eligible provider
  snapshot; and
- use the parent protocol's `REFERENCE_MARKET_UNAVAILABLE` and
  `REFERENCE_MARKET_INCOMPLETE` outcomes as applicable.

## 8. Executable-price evidence

The provider response supplies offered prices and bookmaker identities. The
final executable-price policy remains unresolved among the parent protocol's
bounded alternatives. The final amendment must freeze both the policy and its
eligible book universe before any join.

Prices must be parsed from canonical decimal text without pre-rounding. For
pre-2022-09-18 observations, reconstructed American odds are presentation or
reconciliation data only; calculations must use retained decimal source values.

## 9. Settlement provenance

The Odds API market response is not authoritative evidence of each sportsbook's
void, tie, cancellation, postponement, or reschedule settlement rules. Before
this amendment can become final, every eligible executable book must have a
deterministic settlement table backed by retained authoritative sportsbook rules
or equivalent evidence, as required by the parent protocol.

This does not require another Odds API email. It remains an unresolved amendment
gate.

## 10. Immutable raw evidence and revisions

SportsModel's immutable evidence object is the exact response received in one
authorized acquisition, not the mutable result of a future repeat query.

Every acquisition must retain:

- exact response bytes/body, unchanged;
- secret-free canonical request representation;
- endpoint, API version, sport, books/region, market, odds format, and requested
  date;
- request-start and response-receipt timestamps;
- HTTP status and non-secret quota metadata;
- response wrapper timestamps;
- provider event, participant, kickoff, bookmaker, market, update, outcome, and
  price facts;
- SHA-256 of the raw bytes;
- immutable artifact/version ID; and
- manifest linkage to repository revision, amendment identity, and acquisition
  configuration.

An earlier artifact must never be overwritten. If a later separately authorized
request differs for the same logical request, preserve a new immutable version
with a new hash and explicit predecessor/revision linkage. Normalized records
must reference exactly one raw version. Later upstream corrections cannot
silently mutate evidence used by an activated bundle.

This rule controls even though correspondence described original historical
versions as retained, because current public documentation contemplates future
removal of known errors from historical snapshots.

## 11. Licensing and retention

The provider terms dated 2026-08-31 currently permit indefinite retention,
research and analytical dashboards, derived calculations, user-facing display
including commercial use, and statistical/ML training. They prohibit resale,
repackaging, or redistribution of raw data as a standalone competing data feed.

The terms must be revalidated and retained as acquisition-time evidence before
any separately authorized purchase or request. This amendment does not broaden
the parent protocol's model-freeze and leakage restrictions.

## 12. Credit envelope

For the frozen 1,187-row historical probability population, one `h2h` market and
one US-region equivalent:

```text
maximum one-request-per-target envelope = 1,187 × 10 = 11,870 credits
20K plan nominal headroom               = 20,000 - 11,870 = 8,130 credits
```

The 20K plan covers the conservative single-pass envelope and leaves 8,130
credits. Overall sufficiency for the pilot, retries, and validation remains
conditional on the separately frozen call/credit ceilings. This draft neither
recommends nor authorizes purchase.

## 13. Required bounded pilot

The inactive design-only pilot contract is
`docs/architecture/nfl_historical_market_provider_pilot_spec_0.1.2.md`. It is not
provider-access authority. Any future execution requires separate explicit
authorization and must follow its frozen population rule, call/credit ceiling,
retry policy, access boundary, and immutable evidence contract.

The pilot may empirically assess only:

1. historical response mechanics and schema;
2. observed wrapper timestamps and actual market-level `last_update` presence,
   behavior, and eligible-observation age;
3. observed four-book presence and complete two-sided `h2h` presence;
4. sampled missing, suspended, stale, and schema-deficient observations;
5. provider event ID and `commence_time` observed at the selected T-60 snapshot;
6. duplicate or simultaneous eligible-observation shapes only if they naturally
   occur; and
7. chain-of-custody behavior.

The pilot cannot by itself certify pre-2022 American reconstruction from
decimal-only requests, event-ID replacement or stability across multiple
historical revisions from one T-60 call per game, the existence of simultaneous
observations if none occur, season-long continuous coverage, the final bookmaker
universe, or final `maximum_snapshot_age`. The pre-2022 reconstruction statement
remains a retained provider-document fact unless separately tested under a later
authorized design. Absence of simultaneous observations is
`NOT_OBSERVED_IN_PILOT`, not `DOES_NOT_OCCUR`.

The pilot may not inspect profitability or choose a book based on outcomes,
model results, edges, wager qualification, ROI, or historical performance. Pilot
completion and retained evidence precede final-amendment freeze.

## 14. Unresolved normative parameters

This draft deliberately leaves unresolved:

- final reference-market construction;
- final reference-book universe or designated book;
- final executable-price policy and universe;
- `maximum_snapshot_age`;
- simultaneous-observation tie-break;
- exact full-acquisition timestamp-deduplication and retry rules;
- settlement tables and authoritative evidence for eligible executable books;
- final-acquisition raw-artifact schema and any extension beyond the bounded
  pilot's frozen canonical request, manifest, and revision-link contract;
- exact acquisition cost ceiling; and
- every normative-analysis-specification item outside this provider amendment.

No convenient value is selected for an unresolved parameter.

## 15. Activation gates

This draft remains inactive unless all of the following later occur under
separate authorization:

1. the bounded outcome-blind pilot is separately authorized, completed under
   the design-only pilot specification, and its evidence is retained;
2. all unresolved provider parameters are specified;
3. settlement evidence is retained;
4. a non-draft successor is independently reviewed;
5. the reviewed successor receives immutable version, commit, file hash, review,
   predecessor, and freeze records;
6. the normative analysis specification is independently reviewed and frozen;
7. the complete active-bundle identities are recorded; and
8. acquisition and any later join receive their own explicit authorizations.

Until then:

**DRAFT — NOT ACTIVE — NOT ACQUISITION AUTHORITY**

Historical market-performance joining remains `NOT AUTHORIZED`.
