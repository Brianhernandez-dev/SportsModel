# NFL Historical Market Research Preregistration 0.2.4

Protocol: `nfl_historical_market_research_0.2.4`

Status: successor preregistration created before any historical odds were joined
to model outputs, outcomes, or derived betting performance.

## Version relationship and pre-join declaration

This document succeeds, but does not overwrite, protocol
`nfl_historical_market_research_0.2.3`. The complete `0.1.0`, `0.2.0`, `0.2.1`,
`0.2.2`, and `0.2.3` preregistrations remain immutable historical records in
[NFL Historical Market Research Preregistration 0.1.0](nfl_historical_market_research_protocol.md),
[NFL Historical Market Research Preregistration 0.2.0](nfl_historical_market_research_protocol_0.2.0.md),
[NFL Historical Market Research Preregistration 0.2.1](nfl_historical_market_research_protocol_0.2.1.md),
[NFL Historical Market Research Preregistration 0.2.2](nfl_historical_market_research_protocol_0.2.2.md),
and
[NFL Historical Market Research Preregistration 0.2.3](nfl_historical_market_research_protocol_0.2.3.md).

These amendments were specified before any historical odds were joined to model
outputs, outcomes, or derived betting performance. Version `0.2.4` narrowly
closes settlement-provenance terminal-state propagation, zero-wager degeneracy
in 2024/2025 locked-check bootstraps, threshold-nesting validation ordering,
bounded reference-market construction choices, and explicit terminal-state
treatment at the active-bundle one-way door. It does not redesign `0.2.3`. All
compatible predecessor constraints remain effective through the explicit rules
below.

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
outputs, outcomes, or derived performance. Open provider parameters do not
authorize a historical performance join.

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

## Cohort roles and exposure boundaries

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

Repository evidence explicitly documents the mechanism by which 2025 became
exposed. The Phase 2D baseline was source-controlled before a one-time 2025
historical holdout evaluation, after which the result became a permanent project
checkpoint. The repository therefore prohibits treating 2025 as untouched for
later model development. This mechanism is recorded in
[NFL Phase 2 Closeout](nfl_phase_2_closeout.md), especially its status and
`Holdout exposure rule`, and is reinforced by
[NFL Moneyline Forward Operations](../operations/nfl_moneyline_forward_operations.md),
`Historical evidence retirement`. No model outcome or performance value is
needed or incorporated into this protocol rationale.

The 2025 cohort must remain labeled `EXPOSED_MODEL_HOLDOUT` and reported
separately, never as pristine confirmation. Evidence from 2026 onward is
forward/prospective only. Neither 2024, 2025, nor 2026+ may be used to select or
revise the threshold.

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

## Canonical game and historical kickoff-version authority

The authoritative game identity is the canonical SportsModel NFL identity
associated with the frozen Phase 4C1A evidence. Historical odds-provider event
metadata may not redefine that identity.

The scheduled kickoff used to construct `T-60` must be the canonical scheduled
kickoff whose effective schedule state can be established by retained provenance
as applicable to that historical game. A later correction, reschedule, flex, or
final historical kickoff value may not be projected backward into a time at which
it was not yet effective. Actual game-start time must not be substituted for
scheduled kickoff.

For a rescheduled or flexed game, retained schedule provenance must establish the
effective kickoff chronology sufficiently to determine the authoritative
decision-time `T-60` anchor. This evidence must identify the relevant schedule
versions, their effective or observation chronology, and the kickoff state
applicable to the historical decision. If the chronology or applicable kickoff
cannot be established unambiguously, fail closed and exclude the row with a
machine-readable `KICKOFF_PROVENANCE_FAILURE` reason.

Provider events must map deterministically and fail closed to canonical
SportsModel NFL games using explicit provider event identity, participants,
scheduled time, source identity, and retained provenance. Discretionary manual
matching is prohibited. Ambiguous, conflicting, and unmapped events are excluded
with machine-readable reasons.

All time values must be timezone-aware and normalized to UTC before comparison.
If identity or historical kickoff-version reconciliation cannot be established
unambiguously, the market row is ineligible.

## Historical market timestamp authority

The following timestamps have distinct meanings and must not be conflated:

- **Contemporaneous market observation or quote timestamp:** when the quoted
  market state was historically available according to documented provider
  semantics and retained provenance.
- **Provider update timestamp:** when the provider reports that its record or
  event was updated; this is not automatically the quote-observation time.
- **Retrieval or ingestion timestamp:** when SportsModel or another consumer
  retrieved or loaded the record.
- **File creation timestamp:** when an export or local file was created.
- **Correction timestamp:** when a later correction was issued or recorded.
- **Reconstructed or backfilled timestamp:** when historical data was assembled,
  regenerated, or backfilled after the original market observation.

Only a timestamp with documented provider semantics or retained provenance
establishing contemporaneous historical market availability is eligible for
primary `T-60` selection. Retrieval time, ingestion time, file-generation time,
later correction time, or a backfill/reconstruction timestamp must not be treated
as the historical quote timestamp merely because it is present in provider data.

The final provider amendment must identify and freeze:

- the authoritative market timestamp field;
- its provider-documented semantics;
- timezone behavior;
- precision and cadence;
- correction and backfill behavior; and
- retained evidence supporting those conclusions.

If the historical timestamp semantics cannot be established, the source is
ineligible for the primary `T-60` analysis.

## Primary T-60 market snapshot and age eligibility

The primary decision timestamp is exactly `T-60 minutes`, where `T` is the
authoritative historical canonical scheduled kickoff established under the
kickoff-version rules above:

```text
target_timestamp = authoritative historical canonical kickoff - 60 minutes
```

The deterministic selector is:

```text
selected_observation = latest eligible contemporaneous market observation whose
                       authoritative quote timestamp is <= target_timestamp

snapshot_age = target_timestamp - selected_observation_timestamp
```

Primary eligibility requires:

```text
snapshot_age <= frozen maximum_snapshot_age
```

These invariants are frozen:

- the observation must be at or before `T-60`;
- the selected observation is the latest eligible observation satisfying that
  ordering;
- an observation after `T-60` may not be substituted;
- best price observed at any time before kickoff is prohibited;
- if the latest eligible observation at or before `T-60` is older than
  `maximum_snapshot_age`, exclude the row with a deterministic machine-readable
  stale-market reason;
- after that stale result, do not search farther backward; and
- simultaneous eligible observations must use a deterministic tie-break frozen
  before the join.

`maximum_snapshot_age` is the sole primary observation-age parameter. There is
no separate nearest-prior tolerance. Its exact value, provider timestamp cadence,
and the simultaneous-observation tie-break remain provider-feasibility
parameters and must be frozen in the final pre-join amendment before historical
market performance is inspected.

A provider-specific `last updated` field is provenance only unless its semantics
are independently validated and explicitly frozen as the authoritative
contemporaneous market timestamp in that amendment.

Opening and closing prices may be studied only under separately declared
secondary analyses. They may not replace or revise the primary `T-60` result.

## Reference market and executable price

Two market roles must remain distinct:

- **Reference market:** the frozen eligible observations used to estimate the
  no-vig fair probability and model edge.
- **Executable price:** the actual eligible offered price used for price-dependent
  eligibility, settlement, and realized-return calculations.

The final provider amendment must choose exactly one primary reference-market
construction from this bounded family:

### A. `DESIGNATED_SINGLE_BOOK`

Use the two-way moneyline from one predefined eligible sportsbook and apply the
frozen proportional no-vig calculation to that book's two sides. The exact
sportsbook must be selected outcome-blind in the final provider amendment.

### B. `EQUAL_WEIGHT_NO_VIG_CONSENSUS`

For every sportsbook in the predefined eligible reference-book universe:

1. calculate that sportsbook's two-way proportional no-vig probability; and
2. take the arithmetic mean of the resulting selected-side no-vig probabilities
   using equal weight per eligible sportsbook.

No sportsbook may receive discretionary or performance-based weight.

### C. `MEDIAN_NO_VIG_CONSENSUS`

For every sportsbook in the predefined eligible reference-book universe:

1. calculate that sportsbook's two-way proportional no-vig probability; and
2. use the deterministic median of the resulting selected-side no-vig
   probabilities.

The normative analysis specification must define deterministic median handling
for even book counts before any joined-performance computation.

The final provider amendment must choose exactly one of A, B, or C using only
outcome-blind factors such as timestamp semantics, historical coverage,
continuity, contemporaneous sportsbook availability, source reliability,
licensing, and reproducibility. Historical model profitability, historical
wagering ROI, result-dependent weighting, discretionary `sharp book` weighting,
provider or book weights optimized from joined performance, and any fourth
reference-market construction invented after performance exposure are
prohibited.

The eligible reference-book universe must be frozen before the join. The
reference-market and executable-price book universes need not be identical unless
the final provider amendment explicitly freezes that relationship.

The final pre-join amendment must select one primary executable-price policy:

1. a designated single-book price;
2. a fixed representative-book policy; or
3. best price across a predefined eligible-book universe.

If line-shopping is supported, future outputs must report both the
representative/single-book result and the shopped-best-price result separately.
The shopped result may be primary only if that role was frozen before performance
inspection. Book or provider selection based on historical profitability is
prohibited.

## Deterministic numeric arithmetic

Primary market, edge, settlement, and ROI calculations must use Python
`decimal.Decimal` with a context of:

```text
precision = 28 decimal digits
rounding = ROUND_HALF_EVEN
```

Canonical textual probability and price inputs must be parsed without prior
display rounding. Do not quantize or round intermediate implied probabilities,
no-vig probabilities, model edges, wager net units, ROI values, bootstrap ROI
values, deviations, the critical value, or familywise lower bounds. Rounding is
presentation-only.

The strict `familywise_lower_bound > 0` comparison must use the unrounded retained
value. If implementation evidence obtained before performance joining shows a
technical incompatibility with this exact contract, stop and return for protocol
review; do not silently substitute binary floating-point arithmetic.

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
policy supplies the actual offered price used for price-dependent eligibility,
settlement, and realized-return calculations.

## Complete primary threshold family and rationale

The complete preregistered primary threshold family is exactly:

```text
0%, 2%, 3%, 4%, 5%, 6%, 8%, 10%
```

For each threshold:

```text
bet when edge >= threshold
```

The grid provides a zero-edge baseline, denser coverage over modest 2-6
percentage-point model edges, and higher 8-10 percentage-point filters for
stronger-edge policies. This rationale is structural and non-performance-based;
the spacing must not be described as data-optimized.

Selection of the 0% threshold means only that the primary policy requires no
positive edge buffer beyond nonnegative model edge under the frozen
reference-market calculation. It is not proof that the model universally
"beats the market."

No continuous optimizer, additional threshold, hidden threshold family, or
result-dependent threshold substitution is permitted. All eight thresholds must
be reported for primary development metrics regardless of sample eligibility or
result.

## Counted wagers, staking, settlement units, and ROI

A **counted wager** is a wager that, at decision time, satisfies:

- canonical identity requirements;
- frozen market eligibility;
- valid `T-60` snapshot requirements;
- executable-price requirements;
- selected-side requirements; and
- the applicable frozen edge threshold.

A counted wager remains a counted wager regardless of later settlement. Every
counted wager has a flat stake of exactly `1.0` unit.

Settlement net units for a counted wager are:

```text
win:                                                    decimal_odds - 1
loss:                                                   -1
documented push / tied-game refund / documented void:   0
```

A row excluded before a valid wager exists contributes zero wagers, zero staked
units, and zero realized units.

Primary ROI is:

```text
ROI = sum(realized_net_units for counted wagers)
      / sum(staked_units for counted wagers)
```

Because every counted wager has a `1.0`-unit stake:

```text
ROI = total_net_units / counted_wager_count
```

Documented void, push, and tied-game-refund wagers count toward the 100-wager
development threshold and the 50-wager thin-sample threshold. They contribute
zero net units but remain in the counted-wager count and ROI exposure denominator.
Settlement information may not retrospectively remove a valid decision-time
wager from sample counts or ROI exposure.

## Development sample eligibility

The policy-development cohort is 2021-2023 only. The minimum-sample gate is
evaluated exactly once on the observed 2021-2023 development population before
bootstrap resampling. A threshold is sample-eligible only when it produces at
least 100 counted development wagers in that observed population.

The 100-wager gate is not reevaluated within bootstrap draws. A draw may contain
fewer than 100 counted wagers for a sample-eligible threshold without changing
that threshold's observed sample-eligibility status.

Kelly fractions, variable stakes, confidence weighting, and bankroll compounding
are excluded. Studying them requires a separate preregistration and untouched
evidence.

## Frozen season-stratified clustered bootstrap

The primary development bootstrap population is 2021-2023. Before applying any
edge threshold, construct one common cluster sampling frame from canonical
season-week clusters represented in the market-eligible development analysis
population. For this purpose, `market-eligible` means that a row satisfies every
decision-time counted-wager requirement except the edge-threshold test. Cluster
identity is:

```text
(season, season_type, canonical_week)
```

Do not construct threshold-specific cluster frames. Order the retained common
frame by season ascending, then the canonical `season_type` text in ascending
UTF-8 code-point order, then `canonical_week` ascending. Preserve that exact
ordered frame as evidence.

For every bootstrap draw:

1. Partition the common clusters by season: 2021, 2022, and 2023.
2. Within each season separately, sample clusters with replacement.
3. Draw exactly the observed number of clusters for that season.
4. Concatenate the three season-specific sampled cluster multisets.
5. Use this exact shared cluster multiset for all eight thresholds.
6. If a cluster is sampled multiple times, replicate every counted wager in that
   cluster the same number of times.
7. For each threshold, calculate bootstrap ROI using only counted wagers meeting
   that threshold within the shared sampled clusters.

Every qualifying wager in a sampled cluster remains together; individual wagers
may not be resampled independently.

A bootstrap draw may contain fewer than 100 counted wagers for a threshold; do
not reapply the observed sample-size gate. If a required sample-eligible threshold
has zero counted wagers in a draw, its bootstrap ROI is undefined and the frozen
joint simultaneous statistic cannot be computed. Primary threshold selection
must stop and emit the machine-readable terminal state
`BOOTSTRAP_DEGENERATE_FAIL_CLOSED`. This state is not `NO_POLICY_SELECTED`; no
threshold is selected, and no 2024 `LOCKED_HISTORICAL_HOLDOUT_CHECK` or 2025
`EXPOSED_MODEL_HOLDOUT` policy-performance analysis is generated.

Do not drop the draw, redraw it, smooth the denominator, substitute an alternate
statistic, or reinterpret this state as a failure of statistical significance.

## Conditional bootstrap estimand

The season-stratified season-week resampling conditions on the observed 2021,
2022, and 2023 season composition. The primary uncertainty procedure estimates
sampling variability associated with season-week clusters within that fixed
historical development composition.

It does not claim that three observed seasons identify unrestricted
between-season superpopulation variability. The 2024 cohort remains a separate
`LOCKED_HISTORICAL_HOLDOUT_CHECK`; it must not be folded into development to
estimate between-season variance.

## Frozen bootstrap RNG, seed provenance, and draw evidence

Generate the bootstrap cluster indices using exactly:

```python
numpy.random.Generator(
    numpy.random.PCG64(20260912)
)
```

The seed `20260912` was selected ex ante as the calendar date of this
preregistration work, before any historical market-performance joining. No
alternative random seeds were evaluated or selected based on historical betting
performance.

The bootstrap uses exactly 10,000 draws. Future evidence packages must retain:

- RNG algorithm identity;
- seed `20260912`;
- NumPy version;
- the canonical ordered cluster frame;
- the generated bootstrap cluster-index matrix or an immutable canonical
  representation of the draws; and
- SHA-256 of that retained draw evidence.

The seed alone is not sufficient reproducibility evidence. NumPy supplies only
the deterministic cluster indices; all primary numeric calculations over those
indices remain subject to the `Decimal` contract.

## Simultaneous familywise lower-bound calculation

For every sample-eligible threshold `t`, define:

```text
observed_ROI[t]
```

For bootstrap draw `b`, define:

```text
bootstrap_ROI[b,t]

deviation[b,t] = observed_ROI[t] - bootstrap_ROI[b,t]
```

For every shared draw:

```text
joint_deviation[b] = maximum deviation[b,t]
                     across the complete sample-eligible threshold family
```

Sort all 10,000 joint deviations in ascending order. Use the deterministic
nearest-rank 95th percentile:

```text
rank = ceil(0.95 * 10000) = 9500

critical_value = 9500th ordered joint deviation
```

Do not interpolate. For each sample-eligible threshold:

```text
familywise_lower_bound[t] = observed_ROI[t] - critical_value
```

A threshold qualifies only when its unrounded retained bound satisfies:

```text
familywise_lower_bound[t] > 0
```

A naive collection of independent threshold tests or an independent-test
Bonferroni assumption is prohibited.

## Threshold-nesting validation invariant

Future implementation must validate the following nesting both on the identical
observed market-eligible development population and on threshold wager membership
produced within every shared bootstrap draw:

```text
wagers(edge >= 10%) subset of
wagers(edge >= 8%)  subset of
wagers(edge >= 6%)  subset of
wagers(edge >= 5%)  subset of
wagers(edge >= 4%)  subset of
wagers(edge >= 3%)  subset of
wagers(edge >= 2%)  subset of
wagers(edge >= 0%)
```

Bootstrap nesting is expected because every threshold uses the same sampled
cluster multiset and differs only by its frozen edge threshold.

Any violation indicates eligibility, threshold, or numeric-contract drift. It
must set overall package and analysis validation to failed, emit a deterministic
machine-readable `THRESHOLD_NESTING_VALIDATION_FAILURE`, block primary
threshold-selection reporting, and block 2024/2025 locked-check
policy-performance reporting. It must never be treated as a warning-only
condition. This invariant is a validation rule, not a new policy-selection rule.

## Deterministic primary selection algorithm

Policy selection follows exactly this order:

1. Evaluate all eight thresholds on the identical observed market-eligible
   development population.
2. Mark thresholds with fewer than 100 counted development wagers as
   sample-ineligible.
3. Validate threshold nesting on the observed development population and all
   required shared bootstrap-draw memberships.
4. If any nesting violation exists, stop, emit
   `THRESHOLD_NESTING_VALIDATION_FAILURE`, retain the diagnostic evidence, and do
   not proceed to settlement validation, zero-wager degeneracy checking, or
   confidence-bound qualification.
5. Verify settlement provenance for every counted development wager relevant to
   any sample-eligible threshold. If unresolved realized units exist, stop, emit
   `SETTLEMENT_PROVENANCE_FAILURE`, and apply the development terminal-state
   rules in `Settlement governance`.
6. Determine whether any sample-eligible threshold has zero counted wagers in any
   required bootstrap draw.
7. If zero-wager degeneracy exists, stop, emit
   `BOOTSTRAP_DEGENERATE_FAIL_CLOSED`, select no threshold, and generate no 2024
   or 2025 policy-performance analysis.
8. Otherwise compute the frozen simultaneous familywise bounds.
9. Among sample-eligible thresholds, retain only those whose simultaneous
   one-sided 95% familywise lower confidence bound for ROI is strictly greater
   than zero.
10. If none qualify, return `NO_POLICY_SELECTED`.
11. If exactly one qualifies, select it.
12. If multiple qualify, select the lowest edge threshold.
13. Never override the lowest qualifying threshold because another threshold has
    a higher point-estimate ROI.
14. Report observed primary development metrics for all eight thresholds
    regardless of eligibility or result. A fail-closed terminal state blocks
    selection, confidence-bound qualification, and locked-check reporting; it does
    not authorize suppression of already-valid observed metrics or failure
    diagnostics. A validation failure must clearly mark affected metrics invalid
    rather than present them as valid primary results.

Threshold-nesting validation has precedence over bootstrap zero-wager degeneracy
when both conditions appear in the same analysis because nesting is an
implementation and correctness precondition.

Positive net return alone is not sufficient for policy selection. No
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

`NO_POLICY_SELECTED` is reserved only for a successfully computable, fully valid
primary analysis in which no sample-eligible threshold has a strictly positive
simultaneous familywise lower bound. No terminal or validation failure may be
reported under this label.

If `NO_POLICY_SELECTED` is returned, no betting policy is applied to 2024 or
2025, and no 2024 or 2025 policy-performance result is generated. Descriptive
data-coverage, mapping, and market-quality diagnostics may still be reported,
but they must not imply that a wagering policy was selected.

`BOOTSTRAP_DEGENERATE_FAIL_CLOSED` is a distinct terminal failure, not a null
policy-selection result and not evidence that thresholds failed statistical
significance. It blocks primary threshold-selection reporting and all 2024/2025
policy-performance analysis. Only failure diagnostics that do not imply a
selected policy or valid primary result may be reported.

Development-scoped `SETTLEMENT_PROVENANCE_FAILURE` and
`THRESHOLD_NESTING_VALIDATION_FAILURE` are likewise terminal primary-analysis
failures rather than null research results. Cohort-scoped
`SETTLEMENT_PROVENANCE_FAILURE` and
`LOCKED_CHECK_BOOTSTRAP_DEGENERATE_FAIL_CLOSED` invalidate only the affected
locked-check result when development selection was already valid, subject to the
rules in their governing sections.

Any result-dependent follow-up is exploratory and requires a separate protocol
applied to future untouched evidence.

## Locked checks and thin-sample interpretation

If a global threshold is selected, it is frozen after 2021-2023 development and
applied unchanged to 2024 and 2025. Neither cohort may reopen selection.

If the selected policy produces fewer than 50 counted wagers in 2024, assign the
2024 `LOCKED_HISTORICAL_HOLDOUT_CHECK` an interpretation status of
`LOW_SAMPLE_INCONCLUSIVE`. If it produces fewer than 50 counted wagers in 2025,
assign the 2025 `EXPOSED_MODEL_HOLDOUT` result the same interpretation status.
This status supplements rather than replaces the cohort's evidence
classification and research role.

The 50-wager rule is a preregistered thin-sample interpretation guardrail. It is
not a statistical-significance threshold, a power guarantee, or evidence of
adequate power at exactly 50 wagers. It exists to prevent very small historical
cohort results from being described with excessive confidence.

At 50 or more counted wagers, uncertainty must still be reported. A positive
point estimate alone is not strong confirmation. The normative pre-join analysis
specification must apply the same season-week cluster structure, 10,000 draws,
Decimal arithmetic contract, and retained-draw requirements separately to the
single frozen policy in each cohort. For each applicable cohort independently,
initialize a fresh generator exactly as follows:

```python
numpy.random.Generator(
    numpy.random.PCG64(20260912)
)
```

Generate exactly 10,000 draws per applicable cohort. Fresh initialization makes
each cohort's result independent of execution order. For each cohort retain the
NumPy version, canonical ordered cluster frame, generated cluster-index matrix or
canonical draw representation, and SHA-256 of the draw evidence. Use the same
deviation and nearest-rank critical-value calculation specialized to a one-policy
family and report the resulting one-sided 95% ROI lower bound.

For each cohort independently, if any required draw has zero counted wagers under
the already-selected frozen policy, that draw's bootstrap ROI is undefined and
the cohort's lower-bound computation must stop. Do not drop or redraw the draw,
smooth the denominator, or substitute another uncertainty method. Emit the
cohort-scoped terminal state
`LOCKED_CHECK_BOOTSTRAP_DEGENERATE_FAIL_CLOSED` and identify the affected cohort
as `2024_LOCKED_HISTORICAL_HOLDOUT_CHECK` or
`2025_EXPOSED_MODEL_HOLDOUT`.

This state invalidates the affected cohort's uncertainty result. It does not
retroactively invalidate the valid 2021-2023 selected policy and does not
automatically invalidate the other holdout cohort. It must not be interpreted as
`NO_POLICY_SELECTED`, a negative holdout result, or a failure of statistical
significance.

Using the same fixed seed for these separate single-policy cohort checks is a
deterministic reproducibility choice. It does not merge 2024 and 2025 or create a
joint inferential family. These checks create no new selection test and cannot
revise the threshold.

## Diagnostic reporting scope

All eight thresholds must be reported for primary development metrics. Do not
create threshold-by-threshold subgroup policy families.

Detailed betting-performance diagnostics apply only to the final selected global
policy and must separately include:

- early route;
- mature route;
- regular season;
- postseason;
- neutral-site games; and
- non-neutral-site games.

These diagnostics are descriptive. They may not alter the selected policy,
become new policy-selection criteria, or be promoted to confirmatory subgroup
claims. Future reports must clearly separate diagnostic discussion from the
primary result.

When there is no selected policy, only descriptive data-coverage, mapping, and
market-quality diagnostics may be reported for 2024 and 2025; no subgroup
betting-performance result may imply a selected wagering policy.

## Outcome-blind provider and book feasibility

Provider and book feasibility must be evaluated without model ROI, betting
return, or other joined performance. Selection criteria are:

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

A research row can become a counted wager only when:

- canonical game mapping is unambiguous;
- historical kickoff-version authority is established;
- both required two-way full-game moneyline sides are present;
- frozen provider and bookmaker requirements are satisfied;
- the observation has verified contemporaneous historical quote-time semantics;
- the observation satisfies the frozen `T-60` selector and
  `maximum_snapshot_age`;
- prices are valid and not suspended or placeholders;
- the selected-side offered price exists under the frozen executable-price
  policy; and
- the selected-side edge satisfies the applicable frozen threshold.

Missing prices must not be imputed. Every pre-wager exclusion must retain a
deterministic, machine-readable reason together with source, timestamp, schedule,
and mapping provenance.

## Settlement governance

This protocol does not invent a universal bookmaker settlement convention. The
final provider/book amendment must contain a deterministic settlement table for
every eligible executable book, covering:

- an NFL tied game;
- a void;
- a cancellation; and
- a postponement or reschedule where relevant.

Each normative settlement rule must be supported by retained provider/book rules
or equivalent authoritative evidence. Expected ordinary two-way moneyline
behavior may be recorded only as non-normative context.

If the required settlement convention for a counted wager cannot be verified,
the wager must not be retrospectively removed from the counted-wager or exposure
denominator. Instead, retain the counted wager, mark its realized units as
unresolved, report a machine-readable `SETTLEMENT_PROVENANCE_FAILURE`, and fail
closed for every affected ROI, bound, selection, or package validation result.
Do not impute settlement or silently drop the row.

For the 2021-2023 development cohort, if any counted wager relevant to any
sample-eligible threshold has unresolved realized units for this reason,
`SETTLEMENT_PROVENANCE_FAILURE` is a terminal failure of the primary development
analysis. Mark the development analysis and package invalid. Do not treat the
unresolved units as numeric, impute zero, drop the wager, drop or redraw affected
bootstrap draws, calculate or report a valid simultaneous familywise bound,
select a threshold, report `NO_POLICY_SELECTED`, or run 2024/2025
policy-performance checks.

If a global policy was validly selected from 2021-2023 but a counted wager in the
2024 or 2025 locked-check cohort has unresolved realized units, emit
`SETTLEMENT_PROVENANCE_FAILURE` for the affected cohort and identify that cohort
in machine-readable output. Invalidate that cohort's ROI and lower-bound
calculation without imputing, excluding, redrawing, or substituting. This does not
retroactively invalidate the valid development policy-selection result and does
not automatically invalidate the other holdout cohort when it is unaffected.

For postponed or rescheduled games, retain one canonical identity, establish the
authoritative historical scheduled-kickoff version and its effective chronology,
reconcile the provider event and observation to that evidence, and apply `T-60`
to the resulting authoritative anchor. Exclude the event before a wager exists if
mapping, kickoff-version, or timing lineage is ambiguous. Never substitute actual
game-start time.

The cancelled `2022_17_BUF_CIN` source event has no canonical Phase 4C1A
probability row. It therefore cannot become a market-research wager through
synthetic reconstruction.

## Multiple-testing interpretation

The eight edge thresholds form one preregistered primary family. The
season-stratified clustered simultaneous confidence framework is the only
primary multiplicity control. Route, season-type, and site diagnostics are
descriptive and create no additional candidate policies. Losing, ineligible, or
null thresholds may not be suppressed.

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
- authoritative quote timestamps and their documented semantics;
- retrieval, ingestion, update, correction, and backfill timestamps when present;
- historical scheduled-kickoff versions and effective chronology;
- hashes;
- canonical mapping evidence;
- active protocol version and file hash;
- active normative analysis-specification version and file hash;
- active final provider-amendment version and file hash;
- Phase 4C1A evidence identity;
- source repository revision;
- analysis code revision and configuration identity;
- RNG algorithm identity, seed, and NumPy version;
- canonical ordered cluster frame;
- bootstrap cluster-index matrix or immutable canonical draw representation;
- SHA-256 of the retained draw evidence;
- decimal context and arithmetic implementation identity;
- environment identity with secrets redacted;
- manifest; and
- overall validation result.

If licensing prohibits retaining raw files, preserve the strongest legally
permitted immutable provenance and fingerprint evidence and document the exact
limitation. A prose reconstruction is not a substitute for available raw
evidence.

## Provider-feasibility parameters still open

Only the following provider-dependent parameters remain open:

- provider/source;
- actual eligible books;
- eligible reference-book universe;
- selection of exactly one primary reference-market construction from
  `DESIGNATED_SINGLE_BOOK`, `EQUAL_WEIGHT_NO_VIG_CONSENSUS`, or
  `MEDIAN_NO_VIG_CONSENSUS`;
- executable-price universe;
- primary executable-price policy;
- `maximum_snapshot_age`;
- simultaneous-observation tie-break;
- verified provider/book settlement metadata and rules;
- authoritative historical market timestamp field and its semantics;
- timestamp timezone behavior, precision, and cadence;
- timestamp correction and backfill behavior;
- coverage quality;
- licensing;
- cost; and
- storage terms.

These parameters may be researched only with outcome-blind provider-feasibility
evidence. They must be resolved and frozen in a final pre-join provider amendment
before historical odds are joined to model outputs, outcomes, or performance.
There is no separate open nearest-prior-tolerance parameter. Their intentionally
open status does not authorize a historical performance join.

## Independent review governance

An **independent protocol reviewer** is a reviewer or agent that:

- did not author the candidate protocol version being reviewed;
- was not supplied joined historical market performance for purposes of the
  review; and
- evaluates the frozen text rather than optimizing it toward a favorable result.

For every independent review, retain:

- protocol version;
- reviewed file SHA-256;
- reviewer or system identity;
- review date and time;
- review disposition; and
- review artifact or immutable review-summary identity when retained.

External timestamping or signing is not required by this version. Repository
history and retained hashes must make subsequent alteration detectable.

## Protocol and normative-analysis-specification chain of custody

Any normative analysis specification or final provider amendment referenced by
this protocol is part of the preregistration boundary. Before joined-performance
code runs, each active protocol, normative analysis specification, and final
provider amendment must have an immutable chain-of-custody record containing:

- version identifier;
- repository commit SHA;
- file SHA-256;
- creation timestamp;
- independent review timestamp and status; and
- predecessor/successor relationship when applicable.

The analysis configuration must jointly record:

- active protocol version and hash;
- active normative analysis-specification version and hash; and
- active final provider-amendment version and hash.

## Active-bundle one-way door

Before any joined-performance computation, successor protocols, normative
analysis specifications, and provider amendments may be created under the
immutable chain-of-custody and independent-review rules above.

At the moment the first historical market data are joined to model probabilities,
outcomes, or derived betting performance under the active configuration, these
exact identities become permanently locked for the primary historical study:

- protocol version and hash;
- normative analysis-specification version and hash;
- final provider-amendment version and hash;
- provider and source universe; and
- analysis-code revision and configuration identities required by the protocol.

No later change to a locked normative rule may retain primary or confirmatory
status against already exposed historical evidence. Any later methodology change
is exploratory unless applied only to genuinely untouched or prospective
evidence. A successor may not overwrite an earlier version or claim confirmation
on already exposed evidence.

The material failure states governed by this one-way door include:

- `BOOTSTRAP_DEGENERATE_FAIL_CLOSED`;
- `LOCKED_CHECK_BOOTSTRAP_DEGENERATE_FAIL_CLOSED`;
- `THRESHOLD_NESTING_VALIDATION_FAILURE`; and
- `SETTLEMENT_PROVENANCE_FAILURE`.

After historical market data cross the exposure boundary, no protocol rewrite,
methodology amendment, replacement statistic, settlement substitution, alternate
reference-market construction, alternate bootstrap handling, or other change to
a locked normative rule may rescue primary or confirmatory status on already
exposed evidence. Any such post-exposure alternative is exploratory unless
applied solely to genuinely untouched or prospective evidence.

The cohort scope of the original failure remains part of the retained evidence.
A 2024-only or 2025-only locked-check failure does not erase a valid 2021-2023
selection or automatically invalidate the unaffected holdout cohort. A
development-scoped terminal or validation failure prevents primary policy
selection entirely.

No joined-performance code may run unless the complete active-bundle identities
have first been recorded in the analysis configuration and retained evidence.

## Required future outputs and validations

Later implementation must produce at minimum:

- provider and raw-market provenance;
- deterministic canonical game mapping;
- historical scheduled-kickoff version and effective chronology;
- authoritative market timestamp field and semantic evidence;
- deterministic `T-60` snapshot selection and snapshot age;
- reference no-vig probabilities;
- executable prices;
- model edge;
- candidate-policy and counted-wager eligibility;
- machine-readable exclusion and settlement-provenance reasons;
- the complete eight-threshold development table;
- threshold-nesting validation evidence;
- retained bootstrap-frame, draw, ROI, deviation, critical-value, and
  simultaneous-bound evidence;
- overall validation result;
- cohort-specific validation result when applicable;
- terminal state and deterministic machine-readable reason;
- affected cohort;
- affected wager identifiers when applicable;
- affected thresholds when applicable;
- explicit support for `BOOTSTRAP_DEGENERATE_FAIL_CLOSED`,
  `LOCKED_CHECK_BOOTSTRAP_DEGENERATE_FAIL_CLOSED`,
  `THRESHOLD_NESTING_VALIDATION_FAILURE`, and
  `SETTLEMENT_PROVENANCE_FAILURE`;
- the development selection result, including `NO_POLICY_SELECTED` when
  applicable;
- the 2024 `LOCKED_HISTORICAL_HOLDOUT_CHECK` result only if a policy was selected;
- the separate 2025 `EXPOSED_MODEL_HOLDOUT` result only if a policy was selected;
- selected-policy route, season-type, and site diagnostics; and
- forward 2026+ tracking.

Every output must retain deterministic ordering, cohort role, protocol and source
identities, complete active-bundle identities, input hashes, RNG and draw
evidence, decimal context, and validation result.

## Leakage prohibition

Neither historical outcomes nor historical betting returns may be used to change
the frozen model probabilities, routes, features, model artifacts, or Phase 4C1A
evidence. Historical market results may only be used within the policy-development
role assigned by this preregistered protocol.
