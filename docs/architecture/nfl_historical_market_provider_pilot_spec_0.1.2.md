# NFL Historical-Market Provider Bounded Pilot Specification 0.1.2

**DRAFT — DESIGN ONLY — PROVIDER ACCESS NOT AUTHORIZED**

Draft identity: `nfl_historical_market_provider_pilot_spec_0.1.2`

Parent protocol: `nfl_historical_market_research_0.2.5`

Predecessor: `nfl_historical_market_provider_pilot_spec_0.1.1`, SHA-256 `1EB98A79BE82C9C5D7658E3539854591A299B9CA4BB989A994A6857E4978C649`

This preserves the 0.1.1 independent-review remediation and applies the bounded
corrections recorded by the 0.1.1 ChatGPT review. It authorizes no provider call,
plan purchase, credential use, acquisition, persistence, normalization, database
or migration change, join, model work, production action, or Git action.
Execution requires a separate single-use authorization satisfying Section 13.

## 1. Purpose and prohibited information

The pilot may test only outcome-blind provider mechanics, schema, identity, bookmaker presence, two-sided full-game `h2h` presence, timestamp consistency, sampled staleness, gross sampled coverage gaps, and chain-of-custody behavior.

Selection, execution, evidence, and reports must not query, load, receive, derive, expose, or contain scores, winners, settlements, predictions, model probabilities, edges, wagers, profit/loss, ROI, performance, thresholds, or training data. No outcome/model/performance table may be joined or present in the pilot process. Accidental exposure is a terminal integrity failure.

## 2. Frozen kickoff authority and eligible population

The only normative selection input is the retained 0.2.0 authority ledger in `NFL_Kickoff_Authority_Reconciliation_0.2.0.zip`:

```text
reconciliation ZIP SHA-256 = 2422D97F2A21D9171286AD6F62D5F7D1957993476872AAD936DC627474A2D971
authority ledger SHA-256   = 4A1C2962FF2526924FFA8AFC0275788B423B4848318043609BFF194C0049063D
kickoff field              = historical_scheduled_kickoff_effective_at_decision_time
authority disposition      = KICKOFF_AUTHORITY_RESOLVED
```

The named kickoff field is the single kickoff concept used below. It is the scheduled kickoff version that was effective for the historical decision under frozen 0.2.5. Publication versions are ordered by retained `authority_effective_at`; a later correction, flex, finalization, or reschedule is applied only when its publication preceded that version's resulting T-60 boundary. The final/current kickoff is never projected backward.

Eligibility is frozen before sampling to ledger rows with `authority_disposition=KICKOFF_AUTHORITY_RESOLVED`. Protocol 0.2.5 expressly requires ambiguous kickoff provenance to fail closed and be excluded. There are zero such exclusions in package 0.2.0; no replacement or substitution is permitted if a later review invalidates a row.

Regular season means `game_type=REG` in the canonical SportsModel identity. Season is the canonical NFL season field, not calendar year. Canonical IDs are UTF-8 strings such as `2024_16_DEN_LAC` and are ordered by unsigned UTF-8 byte/ordinal order. Kickoffs are UTC whole seconds. Civil-window classification uses `America/New_York`, tzdata `2026.2`. Postseason is excluded. No neutral-site row is excluded merely for being neutral; the frozen population contains the retained regular-season rows.

Population hashes use this exact byte contract. Project each authority-ledger row
to these fields in this order:

```text
canonical_game_id, season, week, away_team, home_team, kickoff_utc,
authority_disposition, authority_versions
```

`kickoff_utc` is copied as RFC3339 UTC at whole-second precision with uppercase
`Z`; `authority_versions` preserves ledger array order and its timestamp strings.
Serialize each projected row as one JSON object using UTF-8 without BOM, keys at
every object level sorted by ordinal Unicode code point, separators `,` and `:`
with no added whitespace, JSON literals in lowercase, and one LF byte (`0A`)
after every row including the last. Order projected rows by unsigned UTF-8 bytes
of `canonical_game_id`. The per-source-row SHA-256 hashes that complete one-row
byte sequence. The source-population SHA-256 hashes the concatenation of all
1,359 row sequences. The eligible-population SHA-256 hashes the concatenation,
in the same order, of rows whose `authority_disposition` is exactly
`KICKOFF_AUTHORITY_RESOLVED`. No platform newline conversion is permitted.

## 3. Frozen outcome-blind selection

For each season 2021-2025, partition eligible rows by the named kickoff field converted to Eastern civil time:

- `SUNDAY_EARLY`: Sunday at or after 12:00 and before 15:00.
- `SUNDAY_LATE`: Sunday at or after 15:00 and before 18:00.
- `OTHER_STANDALONE_OR_WINDOW`: every other kickoff.

Sort each stratum by `(kickoff UTC, canonical game ID)` and select the lower median at zero-based index `floor((n-1)/2)`. An empty stratum is a specification failure; do not substitute.

For the schedule-change case in each season, consider only rows with at least two exact retained authoritative kickoff versions and nonzero absolute difference between the earliest exact version and the named kickoff field. Select greatest absolute change; break ties by canonical ID ordinal. Select at most one per season. If it duplicates a base target, retain one target with both reasons. If none exists, record `NO_RETAINED_SCHEDULE_CHANGE_CASE`; do not replace.

The frozen companion manifest is `nfl_historical_market_provider_pilot_selection_manifest_0.1.2.json`. Once hashed, selection may not be recomputed against later schedule state. Invalidation requires a new reviewed design and authorization; post-selection replacement is forbidden.

For every selected game:

```text
requested_date = named kickoff field - 60 minutes
```

Exact-equal requested timestamps are deduplicated after UTC whole-second conversion. One request may return multiple events. Non-target events are retained in raw evidence but excluded from pilot analytical output.

## 4. Proposed provider request

The only proposed request family is:

```text
GET /v4/historical/sports/americanfootball_nfl/odds
markets=h2h
oddsFormat=decimal
bookmakers=draftkings,fanduel,betmgm,betrivers
date={requested_date RFC3339 UTC whole seconds}
regions omitted
```

The four books are pilot scope only. Adding a book requires separate outcome-blind evidence and a new reviewed selection/configuration identity. The API key exists only at the future secret-loading boundary and never appears in a command, URL artifact, exception, log, manifest, or report.

Secret-free canonical request bytes are UTF-8 without BOM, LF-separated, with no terminal whitespace:

```text
GET
/v4/historical/sports/americanfootball_nfl/odds
bookmakers=draftkings%2Cfanduel%2Cbetmgm%2Cbetrivers&date={RFC3339_UTC}&markets=h2h&oddsFormat=decimal
```

Keys are ASCII-sorted; RFC 3986 encoding uses uppercase hex; bookmaker order is fixed; the secret parameter is omitted. The as-sent URL is retained only with the secret name/value redacted and is linked to these canonical bytes.

## 5. Durable append-only attempt ledger

The implementation must use a durable append-only ledger in an evidence store named by the execution authorization. Exactly one process may hold the pilot lease. A database transaction or equivalently atomic durable primitive must persist and fsync the reservation before network send. Counters are reconstructed from the ledger after restart, never from memory.

States and allowed transitions:

```text
RESERVED -> PROVABLE_PRE_SEND_FAILURE
RESERVED -> SENT
RESERVED -> SENT_UNKNOWN
SENT -> RESPONSE_CAPTURED
SENT -> SENT_UNKNOWN
any nonterminal state -> TERMINAL_STOP
```

`RESERVED` consumes one attempt and 10 conservative credits before send. `PROVABLE_PRE_SEND_FAILURE` may be eligible for the single retry only when evidence proves no bytes left the host. `SENT` is durably appended immediately after the send boundary. `RESPONSE_CAPTURED` requires the complete application-visible body and required headers to be durably captured and hashed. If bytes may have left the host and response capture is incomplete, append `SENT_UNKNOWN` permanently; it consumes the reservation and credits and is never automatically retried.

Every terminal stop ends that execution and authorization. There is no automatic resume. A later continuation requires a new explicit authorization and preserves every prior attempt and credit reservation.

## 6. Deterministic retry taxonomy

At most one retry per logical requested timestamp, with identical canonical request bytes:

| Condition | Classification | Action |
| --- | --- | --- |
| DNS failure proven before socket send | `PROVABLE_PRE_SEND_FAILURE` | One retry permitted inside the window. |
| TLS negotiation failure proven before HTTP bytes | `PROVABLE_PRE_SEND_FAILURE` | One retry permitted. |
| Connection failure proven before send | `PROVABLE_PRE_SEND_FAILURE` | One retry permitted. |
| Reset/timeout after possible send | `SENT_UNKNOWN` | Terminal stop; no retry. |
| Partial headers or body | `SENT_UNKNOWN` | Terminal stop; no retry. |
| 1xx without a complete final response | `SENT_UNKNOWN` | Terminal stop. |
| 3xx | `RESPONSE_CAPTURED` | Terminal stop; redirects are not followed. |
| 204 | `RESPONSE_CAPTURED` | Terminal schema stop. |
| Non-transient 4xx other than 408/429 | `RESPONSE_CAPTURED` | Terminal stop. |
| 408 with complete captured response | `RESPONSE_CAPTURED` | One retry permitted. |
| 429 with complete captured response | `RESPONSE_CAPTURED` | One retry permitted only after valid `Retry-After`. |
| 5xx with complete captured response | `RESPONSE_CAPTURED` | One retry permitted. |
| HTTP 200 with provider error body | `RESPONSE_CAPTURED` | Terminal schema stop; no retry. |
| Complete 200 with no target/market | `RESPONSE_CAPTURED` | Evidence; record and continue. |
| Invalid/missing `Retry-After` when required | `RESPONSE_CAPTURED` | Terminal stop. |
| Wait or retry would cross execution window | `TERMINAL_STOP` | No retry. |

Retry permission never overrides the attempt, credit, authorization-window, or single-flight gates.

## 7. Call, quota, and cost accounting

```text
maximum primary calls = 20
maximum retry calls   = 20
maximum attempts      = 40
conservative charge   = 10 credits per reservation
hard pilot ceiling    = 400 credits
```

Calls are strictly sequential. Before each reservation, reconcile prior complete responses using `x-requests-used`, `x-requests-remaining`, and `x-requests-last`, including before/after values. Stop before reserving if the next reservation could exceed any ceiling.

Terminal unexpected-cost conditions include `x-requests-last > 10`, a quota delta inconsistent with the request shape, or missing required quota evidence when charge attribution cannot otherwise be proved. Pilot quota must be attributable through a dedicated credential/account identity or a documented quiet window with no other quota-consuming process. No MLB task, credential, service, or production workflow may be stopped or modified to create that window.

## 8. Timestamp taxonomy

For each complete response and each selected market containing a valid
market-level `last_update`, compute in integer milliseconds:

- `requested_date - response.timestamp`;
- `requested_date - market.last_update`;
- `market.last_update - response.timestamp`; and
- when supplied, `previous_timestamp < response.timestamp <= requested_date < next_timestamp`.

Exact equality is allowed for `response.timestamp=requested_date` and
`market.last_update=requested_date`; equality of previous/current or current/next
is an anomaly. A missing, type-invalid, timezone-invalid, or undecodable wrapper
`timestamp` is a terminal schema failure. Optional adjacent timestamps may be
null but must be recorded as null. Negative age, market update after wrapper
snapshot, wrapper ordering failure, invalid market-timestamp timezone/precision,
or undecodable market timestamp is `TERMINAL_STOP` when a timestamp value was
supplied. A valid but cadence-deviating adjacent interval is
`RECORD_AND_CONTINUE`.

If a selected bookmaker/market is present but its market-level `last_update` is
missing or type-invalid, retain the full raw response, classify that observation
`MARKET_TIMESTAMP_FIELD_MISSING_OR_INVALID`, mark it timestamp-ineligible, and
record the deficiency in schema and coverage outputs. Retain bookmaker-level
`last_update`, if present, only as non-authoritative contextual evidence. Never
substitute it for market-level `last_update`; it cannot make an observation
timestamp-eligible. This condition alone is not a whole-run terminal failure,
and processing continues for other books and targets when every other integrity
condition holds.

Outcome-blind market-age bins are `[0,5m]`, `(5m,10m]`, `(10m,15m]`, `(15m,30m]`, `(30m,60m]`, `(60m,180m]`, and `(180m,+infinity)`. These are descriptive only and do not define market eligibility or `maximum_snapshot_age`.

## 9. Exact raw-evidence and schema contract

The raw body is the exact application-visible HTTP entity body after transfer/content decoding and before JSON parsing, normalization, or reserialization. Retain it unchanged with byte length and uppercase SHA-256. Also retain full redacted response headers, server `Date`, `Content-Type`, `Content-Encoding`, all quota headers, redacted as-sent URL, canonical request bytes/hash, request-start and response-receipt times, and linkage between request forms.

Canonical JSON artifacts use UTF-8, no BOM, sorted keys by ordinal Unicode code point, separators `,` and `:`, LF, exactly one terminal LF, JSON `null`, decimal integers without leading zeros, and RFC3339 UTC timestamps at whole-millisecond precision. Provider decimal odds remain their original lexical JSON number tokens and are never round-tripped through binary floating point.

Required successful-wrapper fields and types are `timestamp:string`,
`previous_timestamp:string|null`, `next_timestamp:string|null`, and `data:array`.
Required event fields are `id:string`, `sport_key:string`,
`commence_time:string`, `home_team:string`, `away_team:string`, and
`bookmakers:array`. Required bookmaker fields are `key:string`, `markets:array`;
bookmaker-level `last_update`, if present, is retained descriptively but is
deprecated and non-authoritative. Required selected market fields are
`key:string` and `outcomes:array`; a present market-level `last_update` must be a
valid string timestamp. Required outcomes are `name:string` and
`price:number-token`. Unknown fields are retained raw and do not fail
validation. Missing/type-invalid fields other than selected-market
`last_update` are terminal when they prevent deterministic interpretation.
Selected-market `last_update` follows the record-and-continue classification in
Section 8 and is never silently replaced.

The trusted acquisition clock identity, OS synchronization source/status, offset evidence, monotonic timer identity, runtime/dependency identity, repository HEAD, timezone database, and evidence-store identity are captured before the first reservation. A retry predecessor is labeled `RETRY`; a separately authorized later observation of the same logical request is labeled `UPSTREAM_REVISION`. Neither overwrites the predecessor.

SportsModel chain of custody begins at acquisition. It does not prove provider immutability before acquisition, absence of historical backfill, or undocumented bookmaker publication time.

## 10. Mapping and analytical outputs

Provider events map only to one existing selected canonical game using sport, participants, orientation, provider ID evidence, `commence_time`, and retained kickoff versions. Zero/multiple candidates, participant or orientation conflict, unexpected identity replacement, or inadequate provenance fails closed. Provider `commence_time` cannot invent or rewrite canonical identity or kickoff.

Reports may state, by season and candidate book, observed target presence, complete two-sided `h2h` presence, missing/incomplete counts, sampled timestamp-age distributions, gross sampled gaps, identity anomalies, and artifact lineage. Rates show numerator and deterministic denominator.

The pilot cannot certify season-long continuous coverage, the final book universe, postseason or neutral-site coverage, final `maximum_snapshot_age`, upstream immutability before acquisition, absence of backfilling, pre-2022 American-odds reconstruction from a decimal-only pilot, or historical event-ID replacement/stability across revisions from one T-60 call per game. Provider event ID and `commence_time` are observations at the selected T-60 snapshot; event-ID threshold/history correspondence is contextual unless stronger retained evidence is accepted. It may not enlarge the call set to force those observations. Duplicate or simultaneous shapes may be reported only if they naturally occur; when none occur, report `NOT_OBSERVED_IN_PILOT`, not `DOES_NOT_OCCUR`.

The mixed `OTHER_STANDALONE_OR_WINDOW` stratum is a known small-sample limitation. Successful execution cannot freeze a final reference-book universe. A later outcome-blind coverage census may be required before full acquisition; this document does not design it.

## 11. Deterministic stops and disposition

Any secret exposure, prohibited-data access, authorization mismatch, raw/hash failure or corruption, identity ambiguity, missing required event identity, malformed top-level schema preventing deterministic interpretation, missing/type-invalid/undecodable wrapper timestamp, cost/quota terminal condition, evidence-store collision, or unaccounted attempt produces `PILOT_PROVIDER_FEASIBILITY_FAILED` and stops. An affected observation classified `MARKET_TIMESTAMP_FIELD_MISSING_OR_INVALID` under Section 8 is expressly not, by itself, a whole-run terminal condition.

If every authorized attempt is durably accounted, every required artifact is hash-valid, all required invariants and reports are produced, execution stayed within authorization/credit bounds, no unresolved terminal integrity condition exists, and no observation is classified `MARKET_TIMESTAMP_FIELD_MISSING_OR_INVALID`, return `PILOT_PROVIDER_EVIDENCE_SUFFICIENT`. This means only that the evidence package is procedurally complete enough for post-pilot review; it does not prove coverage or market policy.

Otherwise, when integrity and authorization remain intact but captured response mechanics, mapping, timestamps, or sampled coverage require design/amendment revision, return `PILOT_PROVIDER_EVIDENCE_REVISION_REQUIRED`. Presence of one or more `MARKET_TIMESTAMP_FIELD_MISSING_OR_INVALID` observations sets this disposition as the minimum severity unless a more severe terminal failure controls. No disposition authorizes further calls or downstream work.

## 12. Evidence precedence and provider documents

1. Frozen 0.2.5 controls modeling/statistical semantics.
2. A future reviewed and activated provider amendment controls provider-specific operations within 0.2.5.
3. Retained official provider documentation and immutable pilot evidence support those decisions.
4. Project-owner-supplied correspondence paraphrases are contextual unless original evidence is retained and accepted.
5. Material conflict fails closed for explicit review.

Official public documentation relied upon for history semantics, snapshot cadence, bookmaker filtering, request cost, quota headers, market `last_update`, decimal-history notes, pricing, and terms must be retained and hashed. Failure to capture a page is retained as an access failure, never fabricated.

## 13. Single-use execution authorization

Any future execution authorization must name and hash: this specification; the frozen selection manifest; kickoff package and ledger; execution implementation revision; execution configuration; repository HEAD and clean-tree identity; secret-free account/credential identity; evidence-store identity; clock identity; execution window; target count; primary/retry/attempt ceilings; 400-credit ceiling; authorizer; authorization timestamp; and unique single-use authorization ID.

The authorization expires on completion or any terminal stop. There is no automatic resume. A new authorization must preserve prior accounting. Pilot retry/credit policy creates no precedent for full acquisition. No MLB modification and no historical settlement-result access is authorized.

## 14. Independent-review remediation map

| Finding | Remediation |
| --- | --- |
| H-1 | Sections 2-3 pin the authority ZIP/ledger, one kickoff field, ordering, T-60, population, IDs, timezone, and immutable selection. |
| H-2 | Section 5 defines durable pre-send reservation, single flight, crash states, restart reconstruction, and no auto-resume. |
| M-1 | Section 6 gives mutually exclusive retry classes and ambiguous-send handling. |
| M-2 | Section 7 reconciles quota headers and actual charge after every complete response. |
| M-3 | Section 8 freezes equations, null/equality rules, bins, and terminal versus record-only anomalies. |
| M-4 | Section 9 freezes byte boundaries, serialization, schema, decimal tokens, clocks, and predecessor types. |
| M-5 | Section 10 limits claims to observations this sample can support. |
| M-6 | Section 11 makes `SUFFICIENT` procedural and maps terminal conditions deterministically. |
| M-7 | Section 12 freezes official-document retention and evidence precedence. |
| M-8 | Section 13 specifies the complete single-use authorization record. |

The 0.1.2 correction additionally resolves the 0.1.1 ChatGPT review's three
remaining findings: Sections 1 and 10 bound cross-document pilot claims;
Sections 8, 9, and 11 make historical market-level `last_update` presence and
failure handling empirical; and Section 2 freezes the population-hash byte
contract.

## 15. Post-pilot boundary

Pilot completion precedes any final provider-amendment freeze. Remaining post-pilot decisions include final reference-market construction, reference-book universe/designated book, executable-price rule and universe, `maximum_snapshot_age`, simultaneous-observation tie-break, settlement tables, and any full-acquisition policy. All require outcome-blind evidence, review, freeze, active-bundle activation, and separate authorization. Historical market-performance joining remains `NOT AUTHORIZED`.

**DRAFT — DESIGN ONLY — PROVIDER ACCESS NOT AUTHORIZED**
