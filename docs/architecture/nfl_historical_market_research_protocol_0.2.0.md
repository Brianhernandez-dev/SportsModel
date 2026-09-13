# NFL Historical Market Research Preregistration 0.2.0

Protocol: `nfl_historical_market_research_0.2.0`

Status: successor preregistration created before any historical odds were joined
to model outputs, outcomes, or derived betting performance.

## Version relationship and pre-join declaration

This document succeeds, but does not overwrite, the complete original
`nfl_historical_market_research_0.1.0` preregistration preserved in
[NFL Historical Market Research Preregistration](nfl_historical_market_research_protocol.md).
Both versions remain durable records. The amendments in `0.2.0` were specified
before any historical odds were joined to model probabilities, outcomes, or
derived betting performance and before any historical market analysis was run.

The successor changes the 2024 evidence label, replaces the unresolved policy
selection judgment with a deterministic algorithm, freezes the primary
uncertainty framework, expands outcome-blind provider feasibility requirements,
and strengthens reproducibility and interpretation rules. All other compatible
constraints from `0.1.0` remain effective through the explicit rules below.

## Purpose and research boundary

The primary question is whether the frozen NFL moneyline model probabilities
demonstrate economically meaningful value against historical pregame moneyline
markets under a prospectively specified betting-policy research protocol.

This protocol evaluates the betting policy, not the predictive model
specification. Historical market research must not recompute, select, or tune
model probabilities, features, routes, feature cutoffs, artifacts, schemas, or
model identities.

Provider-feasibility research may inspect outcome-blind source capabilities,
coverage, timestamp cadence, licensing, cost, and storage feasibility. Before
the final pre-join amendment is frozen, it must not join historical odds to model
outputs, outcomes, or derived performance.

## Frozen probability source

The sole probability source is the accepted Phase 4C1A historical probability
evidence contract documented in
[NFL Historical Probability Evidence Exporter](nfl_historical_probability_evidence.md).
Every analysis must preserve its:

- frozen historical probabilities and model outputs;
- outcome-blind population membership;
- early and mature route assignments;
- feature cutoffs and ordered feature values;
- canonical game and kickoff identities; and
- model, artifact, schema, routing, protocol, manifest, and source identities.

Historical market analysis must consume an accepted evidence package without
causing any probability or model component to be recomputed or retuned.

## Cohort roles

The cohort roles are frozen as follows:

| Evidence seasons | Evidence classification | Research role |
| --- | --- | --- |
| 2021-2023 | `DEVELOPMENT_OOF` | Policy development and threshold selection only |
| 2024 | `DEVELOPMENT_OOF` | `LOCKED_HISTORICAL_HOLDOUT_CHECK` |
| 2025 | `EXPOSED_MODEL_HOLDOUT` | Separately reported exposed evaluation |
| 2026+ | Forward/prospective evidence | Prospective monitoring only |

The 2024 cohort remains excluded from threshold selection and is useful as a
locked historical check. Its evidentiary strength is bounded because aggregate
2024 outcomes were previously part of the broader model-development and
evaluation history. It is not pristine confirmation and must never be described
as such.

Mature historical OOF evidence begins in 2022 under the frozen probability
protocol. The 2021 development cohort contains only available early-route
probabilities. No mature 2021 lane may be synthesized.

The 2025 cohort must be labeled `EXPOSED_MODEL_HOLDOUT` and reported separately,
never as pristine confirmation. Evidence from 2026 onward is forward/prospective
only. Neither 2024, 2025, nor 2026+ may be used to select or revise the threshold.

## Primary market scope

The primary market is NFL full-game moneyline only. The following are excluded:

- spreads;
- totals;
- first-half markets;
- team totals;
- player props;
- parlays; and
- live or in-game markets.

Postseason and neutral-site games are included when they are present in the
frozen Phase 4C1A probability population and satisfy the same market eligibility
rules as every other game. Both categories must remain separately identifiable
in descriptive diagnostics.

## Canonical game and kickoff authority

The authoritative game identity and scheduled kickoff are the canonical
SportsModel NFL identity associated with the frozen Phase 4C1A evidence.
Historical odds-provider timestamps or event metadata may not redefine the
canonical kickoff.

Provider events must map deterministically and fail closed to canonical
SportsModel NFL games using explicit provider event identity, participants,
scheduled time, source identity, and retained provenance. Discretionary manual
matching is prohibited. Ambiguous, conflicting, and unmapped events are excluded
with machine-readable reasons.

Rescheduled or flexed kickoffs must reconcile deterministically to the canonical
identity and retained schedule provenance. All time values must be timezone-aware
and normalized to UTC before comparison. If identity or kickoff reconciliation
cannot be established unambiguously, the market row is ineligible.

## Primary T-60 market snapshot

The primary decision timestamp is exactly `T-60 minutes`, where `T` is the
authoritative canonical scheduled kickoff. The deterministic selector must choose
an eligible observation at or before `T-60` and within a frozen maximum age.

These invariants are fixed now:

- the primary snapshot must be at or before `T-60`;
- an observation after `T-60` may not be substituted;
- best price observed at any time before kickoff is prohibited;
- stale-line eligibility must use a deterministic maximum age; and
- simultaneous eligible observations must use a deterministic tie-break frozen
  before the join.

The exact nearest-prior tolerance, timestamp cadence, simultaneous-observation
tie-break, and maximum staleness cutoff remain provider-feasibility parameters.
They must be frozen in the final pre-join amendment before historical market
performance is inspected.

Opening and closing prices may be studied only under separately declared
secondary analyses. They may not replace or revise the primary `T-60` result.

## Reference market and executable price

Two market roles must remain distinct:

- **Reference market:** the frozen eligible observations used to estimate the
  no-vig fair probability and model edge.
- **Executable price:** an actual eligible offered price used to calculate
  candidate EV and realized return.

The final pre-join amendment must select one primary executable-price policy:

1. a designated single-book price;
2. a fixed representative-book policy; or
3. best price across a predefined eligible-book universe.

If line-shopping is supported, future outputs must report both the
representative/single-book result and the shopped-best-price result separately.
The shopped result may be primary only if that role was frozen before performance
inspection. Book or provider selection based on historical profitability is
prohibited.

## Implied probability and no-vig method

For decimal odds `d`, implied probability is `1 / d`. For American moneyline odds
`a`, implied probability is:

```text
a > 0: 100 / (a + 100)
a < 0: (-a) / ((-a) + 100)
```

For the two eligible moneyline sides, proportional two-way normalization is
frozen:

```text
fair_home = implied_home / (implied_home + implied_away)
fair_away = implied_away / (implied_home + implied_away)
```

This method is frozen because it is simple, deterministic, transparent, and
introduces no fitted parameter or method-selection degree of freedom. No
alternate no-vig method may replace it based on historical performance.

## Selected side and model edge

The selected side is the frozen model-selected side from the Phase 4C1A
probability evidence. Historical prices may not re-select the side.

```text
edge = model_selected_side_probability
       - no_vig_market_probability_for_selected_side
```

The reference market supplies the no-vig probability. The executable-price
policy supplies the offered price used for candidate EV and realized return.

## Complete primary threshold family

The complete preregistered primary threshold family is exactly:

```text
0%, 2%, 3%, 4%, 5%, 6%, 8%, 10%
```

For each threshold:

```text
bet when edge >= threshold
```

No continuous optimizer, additional threshold, hidden threshold family, or
result-dependent threshold substitution is permitted. All eight thresholds must
be reported regardless of sample eligibility or result.

## Development sample and staking

The policy-development cohort is 2021-2023 only. A threshold is sample-eligible
only when it produces at least 100 eligible development wagers.

Every eligible wager uses a flat 1-unit stake. Kelly fractions, variable stakes,
confidence weighting, and bankroll compounding are excluded. Studying them
requires a separate preregistration and untouched evidence.

## Frozen clustered uncertainty framework

The primary uncertainty statistic is ROI. The cluster unit is canonical
season-week, represented by season, season type, and canonical week so regular
and postseason identifiers cannot collide. Every qualifying wager in a sampled
season-week cluster must remain together; individual wagers may not be resampled
independently.

The development analysis uses:

- clustered bootstrap resampling;
- 10,000 resamples;
- fixed protocol seed `20260912`;
- all eight thresholds evaluated from every shared resample; and
- simultaneous one-sided 95% familywise lower confidence bounds for ROI over the
  complete sample-eligible threshold family.

The same resampled season-week cluster multiset must be applied to every
threshold in a draw. This preserves dependence among the nested threshold
policies. A naive collection of independent threshold tests or an independent-
test Bonferroni assumption is prohibited.

Conceptually, implementation must compute each eligible threshold's observed ROI
and bootstrap ROI from each of the same 10,000 clustered draws. For each draw it
must form the worst downward ROI deviation across the complete sample-eligible
threshold family. The shared 95th percentile of that joint deviation distribution
is subtracted from each threshold's observed ROI to produce simultaneous
one-sided lower bounds. A threshold qualifies only when its resulting bound is
strictly greater than zero.

A maintained analysis specification may define exact quantile interpolation,
cluster sampling-frame construction, and numeric precision before the first
performance join. Those implementation details must preserve season-week cluster
resampling, all wagers within each sampled cluster, 10,000 draws, seed `20260912`,
the shared resamples and joint worst-deviation construction, the complete eligible
threshold family, and one-sided 95% familywise confidence. If a required ROI or
joint statistic is undefined, selection fails closed rather than substituting a
different uncertainty method.

## Deterministic primary selection algorithm

Policy selection follows exactly this order:

1. Evaluate all eight thresholds.
2. Mark thresholds with fewer than 100 development wagers as sample-ineligible.
3. Among sample-eligible thresholds, retain only those whose simultaneous
   one-sided 95% familywise lower confidence bound for ROI is strictly greater
   than zero.
4. If none qualify, return `NO_POLICY_SELECTED`.
5. If exactly one qualifies, select it.
6. If multiple qualify, select the lowest edge threshold.
7. Never override the lowest qualifying threshold because another threshold has
   a higher point-estimate ROI.
8. Report all eight thresholds regardless of eligibility or result.

Positive net return alone is not sufficient for policy selection. This algorithm
replaces the undefined `materially stronger` judgment in version `0.1.0`; no
discretionary tie-break remains.

## Null-result discipline

`NO_POLICY_SELECTED` is a valid primary research result. It must be reported
prominently and must not trigger:

- threshold expansion;
- subgroup tuning;
- alternate no-vig methods;
- alternate staking;
- alternate timestamp selection; or
- alternate provider or book selection based on profitability.

Any such follow-up is exploratory and requires a separate protocol applied to
future untouched evidence.

## Locked checks and thin-sample interpretation

The selected global threshold, if any, is frozen after 2021-2023 development and
applied unchanged to 2024 and 2025. Neither cohort may reopen selection.

If the selected policy produces fewer than 50 qualifying wagers in 2024, label
the `LOCKED_HISTORICAL_HOLDOUT_CHECK` result `LOW_SAMPLE_INCONCLUSIVE`. If it
produces fewer than 50 qualifying wagers in 2025, label the
`EXPOSED_MODEL_HOLDOUT` result `LOW_SAMPLE_INCONCLUSIVE`. These labels affect
interpretation and reporting only.

At 50 or more wagers, uncertainty must still be reported. A positive point
estimate alone is not strong confirmation. The maintained pre-join analysis
specification must apply the same season-week clustered bootstrap structure,
10,000 resamples, and fixed seed `20260912` separately to the single frozen policy
in each cohort and report its one-sided 95% ROI lower bound. This does not create a
new selection test or allow threshold revision.

## Mandatory descriptive diagnostics

Every future report must include descriptive diagnostics for:

- early route;
- mature route;
- regular season;
- postseason;
- neutral-site games; and
- non-neutral-site games.

These diagnostics do not create additional candidate-policy families and may not
change the selected global threshold. Any policy based on a diagnostic subgroup
is exploratory unless preregistered against untouched future evidence.

## Outcome-blind provider and book feasibility

Phase 4C1B-2 must evaluate providers and books without model ROI, betting return,
or other joined performance. Selection criteria are:

- historical coverage completeness;
- timestamp quality and cadence;
- continuity across seasons;
- bookmaker identity stability;
- contemporaneous historical availability of books;
- licensing and usage rights;
- data provenance; and
- reproducibility and storage feasibility.

Provider and book selection may not use historical model profitability.

Feasibility evidence must document for each sportsbook and season:

- whether the sportsbook existed and was meaningfully available;
- whether the provider history reflects current-book survivorship rather than
  contemporaneous market availability;
- major coverage gaps by season and book; and
- jurisdiction or access caveats limiting claims of executability.

## Eligibility and machine-readable exclusions

A research row is eligible only when:

- canonical game mapping is unambiguous;
- both required two-way full-game moneyline sides are present;
- frozen provider and bookmaker requirements are satisfied;
- the observation satisfies the frozen `T-60` selector and staleness rule;
- prices are valid and not suspended or placeholders; and
- the selected-side offered price exists under the frozen executable-price
  policy.

Missing prices must not be imputed. Every exclusion must retain a deterministic,
machine-readable reason together with source and mapping provenance.

## Ties, voids, cancellations, and reschedules

Settlement rules must be deterministic and frozen before joined analysis:

- **Tied NFL game:** apply the documented eligible market's frozen tie convention;
  report it separately and never silently count it as a win or loss. If the
  applicable convention is unavailable or ambiguous, exclude it with a
  machine-readable reason.
- **Voided market:** record zero realized units, classify it as a void, and keep it
  outside win/loss counts when the retained market evidence explicitly supports
  void treatment.
- **Cancelled game:** create no synthetic wager. If an offered wager is explicitly
  documented as void, report it as a void; otherwise exclude it with the applicable
  cancellation reason.
- **Postponed or rescheduled game:** retain one canonical identity, reconcile the
  provider event and observation to the authoritative canonical kickoff, and apply
  `T-60` to that kickoff. Exclude the event if the mapping or timing lineage is
  ambiguous.

The cancelled `2022_17_BUF_CIN` source event has no canonical Phase 4C1A
probability row. It therefore cannot become a market-research wager through
synthetic reconstruction.

## Multiple-testing interpretation

The eight edge thresholds form one preregistered primary family. The clustered
simultaneous confidence framework is the only primary multiplicity control.
Route, season-type, and site diagnostics are descriptive and create no additional
candidate policies. Losing, ineligible, or null thresholds may not be suppressed.

Any later threshold family, no-vig method, subgroup policy, timestamp, staking
method, or book rule chosen after performance inspection is exploratory and
cannot be relabeled as confirmation on observed evidence.

## Historical executability caveat

Every future report must state that recorded historical availability at a price
does not prove unlimited real-world stake acceptance. Sportsbook limits, account
restrictions, jurisdiction, and access may reduce forward realizability.
Backtested ROI is evidence about the recorded market policy, not a guaranteed or
necessarily scalable return.

## Reproducibility and future evidence packages

Every future historical market evidence package must preserve:

- raw provider market input files or immutable source captures when licensing
  permits;
- provider and source identifiers;
- retrieval and observation timestamps;
- hashes;
- canonical mapping evidence;
- active protocol version and file hash;
- Phase 4C1A evidence identity;
- source repository revision;
- analysis code revision and hash;
- deterministic random seed;
- environment identity with secrets redacted;
- manifest; and
- overall validation result.

If licensing prohibits retaining raw files, preserve the strongest legally
permitted immutable provenance and fingerprint evidence and document the exact
limitation. A prose reconstruction is not a substitute for available raw
evidence.

## Provider-feasibility parameters still open

The following parameters remain legitimately unresolved until Phase 4C1B-2:

- provider/source;
- actual eligible books;
- reference-market construction;
- executable-price universe and primary executable-price policy;
- exact nearest-prior tolerance;
- exact maximum staleness cutoff;
- timestamp cadence;
- simultaneous-observation tie-break;
- provider-specific settlement metadata; and
- licensing, cost, and storage terms.

These may be researched only with outcome-blind provider-feasibility evidence.
They must be resolved and frozen in a final pre-join protocol amendment before
any historical odds are joined to model outputs, outcomes, or performance.

## Amendment chain of custody

Each active protocol or amendment must have an immutable chain-of-custody record
containing:

- protocol version;
- repository commit SHA;
- protocol file SHA-256;
- creation timestamp;
- independent review timestamp;
- review status; and
- the predecessor and successor relationship, when applicable.

No joined-performance code may run unless the active protocol version and file
hash have first been recorded in the analysis configuration and retained
evidence. Any pre-join change requires a documented successor or amendment that
states exactly what changed and why; earlier versions remain preserved.

Any successor or amendment created after performance inspection is exploratory
unless it is applied only to a genuinely untouched or prospective cohort. It may
not overwrite an earlier version or claim confirmation on already observed
evidence.

## Required future outputs

Later implementation must produce at minimum:

- provider and raw-market provenance;
- deterministic canonical game mapping;
- deterministic `T-60` snapshot selection;
- reference no-vig probabilities;
- executable prices;
- model edge;
- candidate-policy eligibility;
- machine-readable exclusion reasons;
- the complete eight-threshold development table;
- clustered-bootstrap and simultaneous-bound evidence;
- the development selection result, including `NO_POLICY_SELECTED` when
  applicable;
- the 2024 `LOCKED_HISTORICAL_HOLDOUT_CHECK` result;
- the separate 2025 `EXPOSED_MODEL_HOLDOUT` result;
- mandatory route, season-type, and site diagnostics; and
- forward 2026+ tracking.

Every output must retain deterministic ordering, cohort role, protocol and source
identities, input hashes, code identity, seed, and validation result.

## Leakage prohibition

Neither historical outcomes nor historical betting returns may be used to change
the frozen model probabilities, routes, features, model artifacts, or Phase 4C1A
evidence. Historical market results may only be used within the policy-development
role assigned by this preregistered protocol.
