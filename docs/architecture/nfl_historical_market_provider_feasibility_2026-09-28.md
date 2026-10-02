# NFL Historical-Market Provider Feasibility Evidence — 2026-09-28

Status: `CANDIDATE_EVIDENCE_FOR_INDEPENDENT_REVIEW`

This document is evidence consolidation only. It does not authorize historical
data acquisition, provider calls, historical market-performance joining, model
work, migrations, or production execution.

## 1. Scope

This artifact consolidates outcome-blind provider-feasibility evidence for the
frozen `nfl_historical_market_research_0.2.5` base protocol. It addresses source
availability, timestamp semantics, coverage, retention, licensing, quota cost,
and evidence preservation without inspecting game outcomes, model performance,
profitability, or historical wagering results.

Revision note (2026-10-01): pre-revision SHA-256 was
`2D7BB0F9BCC38F57F076F4577F699F0818E3E5CE97E819BA622B38212D343759`.
Kickoff authority now references the sufficient external package
`NFL_Kickoff_Authority_Reconciliation_0.2.0.zip` (SHA-256
`2422D97F2A21D9171286AD6F62D5F7D1957993476872AAD936DC627474A2D971`)
and its authority ledger (SHA-256
`4A1C2962FF2526924FFA8AFC0275788B423B4848318043609BFF194C0049063D`).

Pilot-design 0.1.2 correction note (2026-10-01): the immediately preceding
candidate SHA-256 was
`4B81C2FEC6BB46580BF434F0DB4A541C83788086AE8402815F1B9DA559DE1F87`.
This correction limits empirical claims to observations the bounded sample can
actually produce and preserves historical market-level `last_update` field
presence as an empirical question.

The governing base protocol remains
`docs/architecture/nfl_historical_market_research_protocol_0.2.5.md`, SHA-256
`09FB79F12FD9B555E4C6A362DA5E459D45F91295DB42F0582E8B1FA7E461DAA7`.
Its freeze record continues to state that historical market-performance joining
is not authorized. Historical acquisition is also outside this task's authority.

## 2. Evidence provenance

### 2.1 User-supplied provider correspondence

The correspondence facts below have this provenance:

> Provider correspondence supplied by project owner on 2026-09-14; substantive
> facts preserved from the original provider reply.

The original messages are not repository artifacts. This document preserves
paraphrased substantive facts supplied by the project owner; it does not present
them as quotations, independently verified public statements, or repository-
native evidence.

Correspondence-only paraphrases must not become the sole normative authority of
the final provider amendment unless the underlying original correspondence is
retained as immutable evidence. Wherever possible, final normative authority
must instead come from retained official public documentation and/or immutable
bounded-pilot evidence. Correspondence-only facts that are not necessary to a
final rule may remain non-normative context. No additional provider Q&A is
required by this disposition.

### 2.2 Current official public documentation

Public-documentation evidence was retrieved on 2026-09-28 and rechecked during
consolidation on 2026-09-29. The authoritative pages used were:

- [Historical Sports Odds Data API](https://the-odds-api.com/historical-odds-data/)
- [Odds API Documentation V4](https://the-odds-api.com/liveapi/guides/v4/)
- [Bookmaker APIs](https://the-odds-api.com/sports-odds-data/bookmaker-apis.html)
- [Sports Odds API pricing](https://the-odds-api.com/)
- [Terms and Conditions](https://the-odds-api.com/terms-and-conditions.html),
  last updated 2026-08-31

Public documentation is versioned only by the provider's live website unless a
date is stated. Its facts must therefore be revalidated before any future
authorized acquisition.

### 2.3 Repository evidence

Repository sources include the frozen 0.2.5 protocol, freeze record, independent
review, `ROADMAP.md`, the NFL Phase 4 market audit, NFL forward-operations
documentation, migrations 027–031, and the historical-probability evidence
architecture. Existing prospective NFL Odds API captures are not historical
provider-feasibility proof and were not joined to outcomes or model performance.

## 3. Provider comparison

| Provider | Technical feasibility | Commercial/access feasibility | Evidence disposition |
| --- | --- | --- | --- |
| The Odds API | Supports historical NFL featured-market snapshots and the frozen protocol's full-game moneyline scope | Historical access is available on paid self-service plans; no purchase is authorized here | Candidate provider for an independently reviewed amendment and a separately authorized bounded pilot |
| SportsDataIO | Correspondence indicates a T-60 reconstruction was technically supportable | Historical sportsbook sales were selective and unavailable to the project's current individual/non-LLC owner | Commercially inaccessible for the present project identity; not the candidate source |

## 4. The Odds API correspondence findings

Under the user-supplied correspondence provenance above:

1. Market-level `last_update` represents the last successful observation for
   that bookmaker market.
2. Historical `last_update` values are retained from the historical observation
   rather than recomputed at query time.
3. Bookmaker-level `last_update` is deprecated in favor of market-level
   `last_update`.
4. The provider did not supply a season-by-season coverage table, but reported
   continuous historical coverage for DraftKings, FanDuel, BetRivers, and
   BetMGM, among other books.
5. When a market is suspended or removed, its existing observation becomes stale
   and the market disappears after approximately 15 minutes.
6. `commence_time` may change when an event is rescheduled.
7. The event-ID reschedule threshold was historically as low as approximately
   eight hours; the provider reported that the current threshold is 24 hours.
8. Historical snapshots were described as immutable, with original historical
   versions retained when revisions occur.
9. Before 2022-09-18, only decimal odds were originally captured. American odds
   for those observations are reconstructed from decimal values and can differ
   slightly because of rounding.

The continuous-coverage and historical-version claims remain correspondence
claims. They are not replaced by current bookmaker listings or treated as a
season-by-season empirical audit.

## 5. Current public-documentation findings

The current official documentation establishes:

- historical featured-market data is available from 2020-06-06;
- the NFL key `americanfootball_nfl` begins at `2020-06-06T10:05:00Z`;
- featured-market snapshots were initially taken every 10 minutes and are
  available every 5 minutes from September 2022 onward;
- the historical endpoint returns the closest provider snapshot equal to or
  earlier than the requested ISO-8601 `date`;
- historical access is available only on paid plans;
- historical featured-market requests cost `10 × regions × markets` credits;
- historical event-odds requests cost
  `10 × regions × markets × events` credits;
- the response wrapper exposes `timestamp`, `previous_timestamp`, and
  `next_timestamp`;
- market-level `last_update` is the last time the provider system saw odds for
  that market from the bookmaker;
- on suspension or closure, market-level `last_update` stops advancing and the
  market is removed after about 15 minutes;
- bookmaker-level `last_update` is deprecated;
- current US listings include `draftkings`, `fanduel`, `betmgm`, and
  `betrivers`; this does not prove historical continuity;
- before 2022-09-18, historical snapshots originally captured decimal odds and
  American odds are calculated from those values with possible small rounding
  differences; and
- bookmakers, sports, and markets exist in history only from the time each was
  added to the provider's current API.

The V4 documentation also warns that errors can remain in historical snapshots
and that the provider may remove known errors from those snapshots later. That
public caveat prevents SportsModel from treating repeated upstream queries as an
immutable evidence store.

Current listed plans are:

| Monthly credits | Price (USD/month) |
| ---: | ---: |
| 20,000 | $30 |
| 100,000 | $59 |
| 5,000,000 | $119 |
| 15,000,000 | $249 |

No purchase recommendation or authorization follows from this table.

## 6. SportsDataIO correspondence findings

Under the user-supplied correspondence provenance:

1. `Created` is SportsDataIO's original live-ingestion timestamp, not necessarily
   the sportsbook's own publication timestamp.
2. A T-60 reconstruction use case was technically supportable.
3. Historical sportsbook-data sales are selective.
4. The required historical sportsbook dataset would not be sold to an
   individual.
5. An LLC or other qualifying business presence was required, with no
   individual-user exception offered.
6. Pricing depended on qualification and the use case.
7. Schedule and reschedule handling depends on the Schedules feed.
8. Licensing is governed by the applicable SportsDataIO rights/licensing
   documentation.

SportsDataIO is therefore technically viable but commercially inaccessible for
SportsModel's current individual/non-LLC situation.

## 7. Protocol 0.2.5 open-parameter reconciliation

| Parameter | Classification | Evidence-constrained conclusion |
| --- | --- | --- |
| Historical source/provider identity | `RESOLVED_BY_BOTH` | Candidate source is The Odds API V4; the draft remains inactive. |
| NFL historical availability window | `RESOLVED_BY_CURRENT_PUBLIC_DOCS` | NFL history starts `2020-06-06T10:05:00Z`, covering the protocol's 2021–2025 population in principle. |
| Historical snapshot cadence | `RESOLVED_BY_CURRENT_PUBLIC_DOCS` | 10-minute initial cadence; 5-minute cadence from September 2022. |
| Requested timestamp semantics | `RESOLVED_BY_CURRENT_PUBLIC_DOCS` | `date` requests a historical snapshot in ISO-8601. |
| Returned snapshot timestamp | `RESOLVED_BY_CURRENT_PUBLIC_DOCS` | Wrapper `timestamp` is the closest available provider snapshot at or before requested `date`. |
| Quote/update timestamp semantics | `RESOLVED_BY_BOTH` | When present and valid, market-level `last_update` means the provider's last successful/sighted bookmaker-market observation. This classification addresses semantics, not historical-field presence. |
| Retrieval timestamp semantics | `REQUIRES_PROTOCOL_SPECIFICATION` | SportsModel must record its own request-start and response-receipt timestamps; neither is historical quote time. |
| Historical market-level `last_update` field presence | `REQUIRES_SMALL_EMPIRICAL_PILOT` | Current V4 semantics and correspondence support market-level authority, but the retained historical example shows an older bookmaker-level-only shape. The pilot must measure actual presence and behavior across sampled eras/books. Bookmaker-level `last_update` is never a fallback. |
| Event identity | `RESOLVED_BY_CURRENT_PUBLIC_DOCS` | Historical responses carry provider event ID, participants, sport key, and `commence_time`; canonical mapping remains fail-closed under 0.2.5. |
| `commence_time` changes | `RESOLVED_BY_PROVIDER_CORRESPONDENCE` | It can change after rescheduling; canonical historical kickoff-version provenance remains authoritative. |
| Reschedule/event-ID behavior | `RESOLVED_BY_PROVIDER_CORRESPONDENCE` | Threshold reportedly changed from as low as about 8 hours to 24 hours. This is contextual evidence; one T-60 call per game cannot certify event-ID replacement or stability across historical revisions. |
| Sportsbook universe | `REQUIRES_PROTOCOL_SPECIFICATION` | Public docs list the four candidates, but the final frozen universe depends on historical feasibility. |
| Historical sportsbook coverage | `REQUIRES_SMALL_EMPIRICAL_PILOT` | Correspondence reports continuity for four books; no season-by-season coverage table exists. |
| Suspended/missing market behavior | `RESOLVED_BY_BOTH` | Stale `last_update` stops advancing; market disappears after about 15 minutes. Missing data cannot be imputed. |
| Executable-price evidence | `REQUIRES_PROTOCOL_SPECIFICATION` | Provider supplies offered prices, but the final executable-book universe and designated/representative/best-price policy remain open. |
| Snapshot age | `RESOLVED_BY_BOTH` | Draft calculation is `T-60 - market.last_update`, after validating wrapper timestamp and timestamp ordering. |
| `maximum_snapshot_age` | `REQUIRES_PROTOCOL_SPECIFICATION` | No value is selected by provider facts. It must be frozen outcome-blind after cadence/coverage pilot evidence. |
| Simultaneous-observation tie-break | `REQUIRES_PROTOCOL_SPECIFICATION` | Provider facts do not select the exact deterministic tie-break required by 0.2.5. The bounded pilot may describe simultaneous observations only if they naturally occur; absence is `NOT_OBSERVED_IN_PILOT`, not evidence that they do not occur. |
| Settlement/void provenance | `REQUIRES_AUTHORITATIVE_BOOK_RULE_EVIDENCE` | Retained authoritative rules are required for every sportsbook that ultimately enters the executable-price universe; Odds API market data does not establish settlement. |
| Data retention | `RESOLVED_BY_CURRENT_PUBLIC_DOCS` | Current terms permit indefinite retention. |
| Raw-evidence immutability | `REQUIRES_PROTOCOL_SPECIFICATION` | Upstream history may later change; SportsModel must freeze each acquired response as a separately hashed immutable object. |
| Licensing | `RESOLVED_BY_CURRENT_PUBLIC_DOCS` | Current terms permit the contemplated research and retention, subject to revalidation before acquisition. |
| Commercial/model usage | `RESOLVED_BY_CURRENT_PUBLIC_DOCS` | Current terms permit UI/commercial display, research, derived values, and statistical/ML training. The frozen study still prohibits model retraining from these results. |
| Redistribution restrictions | `RESOLVED_BY_CURRENT_PUBLIC_DOCS` | Raw-data resale/repackaging as a competing feed is prohibited. |
| Request-credit mechanics | `RESOLVED_BY_CURRENT_PUBLIC_DOCS` | Featured history costs 10 credits per region per market; event history adds the per-event multiplier. |
| Estimated acquisition cost | `REQUIRES_PROTOCOL_SPECIFICATION` | A conservative envelope is calculable, but exact calls depend on the frozen request schedule, deduplication, pilot, and retry budget. |
| American-odds reconstruction before 2022-09-18 | `RESOLVED_BY_BOTH` | Retained provider documentation/correspondence says original decimal values are authoritative and derived American values may contain rounding differences. A decimal-only pilot cannot independently certify that reconstruction behavior; separate authorized testing would be required. |

## 8. Timestamp and provenance conclusions

For the candidate source, the protocol's timestamp roles map as follows:

| Role | Candidate field/evidence | Rule |
| --- | --- | --- |
| Requested target | Historical request `date` | Exactly canonical historical kickoff minus 60 minutes. |
| Returned provider snapshot | Wrapper `timestamp` | Must be at or before requested `date`; retain adjacent wrapper timestamps when supplied. |
| Bookmaker-market observation/update | Market-level `last_update` | Candidate authoritative market observation time based on retained official documentation and provider correspondence. The bounded pilot must establish actual field presence and behavior across its sampled historical responses. |
| Retrieval | SportsModel response-receipt timestamp | Acquisition provenance only; never substitute for historical quote time. |
| Request initiation | SportsModel request-start timestamp | Acquisition provenance only. |
| Bookmaker-level update | Deprecated bookmaker `last_update` | Do not use as authority. |
| Kickoff | Canonical historical SportsModel schedule state | Provider `commence_time` is reconciliation evidence, not authority to rewrite canonical identity or kickoff history. |

An otherwise eligible observation with a valid market-level timestamp must
satisfy both `wrapper.timestamp <= T-60` and `market.last_update <= T-60`.
Snapshot age is provisionally measured from that market-level timestamp because
it represents when the provider last successfully observed that bookmaker
market. If market-level `last_update` is missing or type-invalid, the affected
observation fails closed as timestamp-ineligible; bookmaker-level
`last_update`, if returned, is retained only as non-authoritative context and is
never substituted. The exact `maximum_snapshot_age` remains open.

## 9. Immutable SportsModel raw-evidence rule

The provider's statement that original historical versions are retained is
useful feasibility evidence but is not a sufficient immutability boundary. The
public documentation contemplates later removal of known errors. The frozen
protocol remains point-in-time safe only if SportsModel makes its own acquisition
artifact immutable:

1. Retain the exact provider response bytes/body received at acquisition.
2. Retain the secret-free canonical request parameters and endpoint identity.
3. Retain SportsModel request-start and response-receipt timestamps.
4. Retain requested `date`, returned `timestamp`, `previous_timestamp`, and
   `next_timestamp` when present.
5. Retain market-level `last_update`, provider event identity, participants,
   `commence_time`, bookmaker keys, market key, outcomes, and original prices.
6. Hash the exact raw response bytes with SHA-256 and bind the hash to a manifest.
7. Never overwrite, normalize in place, or relabel an earlier raw artifact.
8. If a later authorized request returns different bytes or facts for the same
   logical request, retain it as a new observation/version with its own retrieval
   time and hash, and record the relationship to its predecessor.
9. Derived normalized records must point back to one exact raw artifact/version.
10. Provider corrections must never silently change evidence already used under
    an activated analysis bundle.

This rule is consistent with 0.2.5's requirements to retain raw input or the
strongest legally permitted immutable evidence, hashes, timestamp semantics,
correction/backfill chronology, and active-bundle identity. It is sufficient as
the provider-specific immutability rule, subject to independent review and later
implementation; it does not itself authorize acquisition.

## 10. Bookmaker and coverage assessment

DraftKings, FanDuel, BetMGM, and BetRivers are current US-region books in official
public documentation. Provider correspondence additionally reports continuous
historical coverage for those books. Neither source supplies the per-season,
per-game completeness evidence demanded by 0.2.5.

A small outcome-blind pilot is therefore required before freezing any designated
book or consensus universe. It may empirically assess, without joining outcomes
or model probabilities:

- presence of each book by season and sampled T-60 timestamp;
- complete two-sided full-game `h2h` markets;
- historical response mechanics and schema, including observed wrapper
  timestamps and actual market-level `last_update` presence/behavior;
- market-level `last_update` age distributions for timestamp-eligible
  observations;
- missing/suspended/stale observations;
- provider event ID and `commence_time` observed at each selected T-60 snapshot;
- duplicates or simultaneous eligible observations only if they naturally
  occur; and
- chain-of-custody behavior.

The bounded pilot cannot by itself certify pre-2022 American reconstruction
from decimal-only requests, event-ID replacement or stability across multiple
historical revisions from one T-60 call per game, the existence of simultaneous
observations when none occur, season-long continuous coverage, the final
bookmaker universe, or final `maximum_snapshot_age`. If no simultaneous
observation occurs, report `NOT_OBSERVED_IN_PILOT`, not `DOES_NOT_OCCUR`.

The pilot must not choose books based on performance or profitability.

## 11. Licensing and retention assessment

The Odds API terms dated 2026-08-31 permit indefinite data retention, user-facing
display including commercial use, research and analytical dashboards, derived
values, and statistical/ML training. They prohibit reselling or redistributing
the raw data as a standalone competing data product.

Those terms support the contemplated internal research and immutable evidence
retention. They must be captured or revalidated immediately before any separately
authorized purchase/acquisition because live terms may change. Nothing here
changes the frozen protocol's prohibition on using historical market results to
retrain or tune the NFL model.

## 12. Acquisition-credit and cost estimate

The frozen historical probability population contains 1,187 target rows across
2021–2025. The primary market is one featured market, full-game moneyline
(`h2h`). The candidate four-book set fits within one US region or one group of up
to ten explicitly requested bookmakers. The featured historical endpoint costs
10 credits per region-equivalent per market per request.

Conservative single-pass upper envelope before timestamp deduplication:

```text
targets                  = 1,187
markets per request      = 1 (h2h)
region equivalents       = 1
credits per request      = 10 × 1 × 1 = 10
single-pass credits      = 1,187 × 10 = 11,870
20K-plan headroom        = 20,000 - 11,870 = 8,130
```

If games sharing an exact canonical T-60 timestamp can safely share one featured
historical request, the actual single-pass requirement will be lower. A small
pilot, deterministic reruns required for validation, empty responses, failures,
and any separately frozen retry budget affect the operational total. The event-
odds endpoint is not needed for the featured `h2h` use case and would introduce
an avoidable per-event multiplier.

Disposition: the 20K plan covers the conservative single-pass envelope and
leaves 8,130 credits. Overall sufficiency for the pilot, retries, and validation
remains conditional on the separately frozen call/credit ceilings. No plan
purchase is recommended or authorized by this document.

## 13. Sequenced gates and unresolved items

The pilot and final-amendment gates are intentionally separate. Empirical pilot
results are not a prerequisite to authorizing the pilot that produces them.

### 13.1 Pre-pilot gates

Before any bounded pilot may run, the project must:

1. freeze the exact outcome-blind population-selection rule;
2. freeze exact calls and canonical secret-free request construction, including
   candidate bookmakers, market, odds format, requested timestamp, and timestamp
   deduplication;
3. freeze a hard provider-credit ceiling and deterministic retry/failure policy;
4. freeze immutable raw-evidence capture, response-byte hashing, manifest,
   request-start/response-receipt timestamps, artifact identity, and revision
   linkage;
5. enforce a no-outcome/no-model/no-performance access boundary; and
6. receive separate explicit pilot-execution authorization.

The design-only contract for these gates is
`docs/architecture/nfl_historical_market_provider_pilot_spec_0.1.2.md`. It is not
provider-access authority.

### 13.2 Post-pilot / final-amendment gates

After the separately authorized pilot is complete, and before a provider
amendment can become final, the project must:

1. assess empirical season/book coverage and timestamp-age behavior;
2. freeze final reference-market construction and the reference-book universe or
   designated book;
3. freeze the executable-price policy and its eligible universe;
4. freeze `maximum_snapshot_age` and the exact simultaneous-observation tie-break;
5. retain authoritative sportsbook settlement/void rules for every book that
   enters the executable-price universe;
6. complete the final provider amendment and normative analysis specification,
   including the exact NumPy pin and locked-check cluster-frame wording required
   by the independent review;
7. obtain the required independent reviews and chain-of-custody/freeze records;
8. separately authorize any full acquisition; and
9. activate the complete reviewed active bundle before any historical market-
   performance join.

None of these items requires another provider email before independent review of
this candidate. Settlement evidence should come from authoritative sportsbook
rules; coverage and response-shape questions are better resolved by a separately
authorized bounded empirical pilot.

## 14. Acquisition-readiness disposition

`PROVIDER_FEASIBILITY_CANDIDATE_READY_FOR_INDEPENDENT_REVIEW`

The Odds API is technically and commercially feasible as the candidate source.
The evidence is sufficient to draft provider-specific rules and define a bounded
pilot, but not to activate the amendment or authorize acquisition. Historical
market-performance joining remains expressly unauthorized.

`NO_ADDITIONAL_PROVIDER_QA_REQUIRED`
