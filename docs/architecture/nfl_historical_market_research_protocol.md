# NFL Historical Market Research Preregistration

Protocol: `nfl_historical_market_research_0.1.0`

Status: preregistered before historical odds are joined to model probabilities,
game outcomes, or derived betting performance for policy design.

## Purpose and boundary

The primary research question is whether the frozen NFL moneyline model
probabilities demonstrate economically meaningful value against historical
pregame moneyline markets under a prospectively specified betting-policy
research protocol.

This protocol evaluates a betting policy. It does not evaluate, select, or alter
the predictive model specification. No historical market result may cause model
probabilities, features, routes, cutoffs, artifacts, or identities to be
recomputed, selected, or tuned.

Provider-feasibility research may inspect coverage, timestamp cadence, licensing,
cost, storage terms, and related source capabilities before acquisition. It must
not join odds to model outputs, outcomes, or derived performance. Joined
performance inspection is prohibited until every open pre-join parameter in this
document has been frozen through immutable protocol versioning.

## Frozen probability evidence

The sole probability source is the accepted Phase 4C1A historical probability
evidence contract documented in
[NFL Historical Probability Evidence Exporter](nfl_historical_probability_evidence.md).
The market study must consume its accepted evidence without recomputing or
retuning:

- historical probabilities and model outputs;
- outcome-blind population membership;
- early and mature route assignments;
- feature cutoffs and ordered feature values; or
- model, artifact, schema, routing, and protocol identities.

The Phase 4C1A package identity, manifest, hashes, source revision, and validation
result must be retained as dependencies of every later market-research output.

## Cohort roles

The cohort roles are frozen as follows:

| Evidence seasons | Evidence classification | Research role |
| --- | --- | --- |
| 2021-2023 | `DEVELOPMENT_OOF` | Policy development and threshold selection only |
| 2024 | `DEVELOPMENT_OOF` | Locked historical confirmation |
| 2025 | `EXPOSED_MODEL_HOLDOUT` | Separately reported exposed evaluation |
| 2026+ | Forward/prospective evidence | Prospective monitoring only |

Mature historical OOF evidence begins in 2022 under the frozen probability
protocol. The 2021 development cohort contains only the available early-route
probabilities. No mature 2021 lane may be synthesized.

The 2025 cohort is not pristine independent confirmation. The selected policy
must be applied unchanged and its results labeled `EXPOSED_MODEL_HOLDOUT`.
Neither 2025 nor 2026+ may be used for historical threshold selection or
retroactive policy tuning.

## Market scope

The primary market is NFL full-game moneyline only. This protocol excludes:

- spreads;
- totals;
- first-half markets;
- team totals;
- player props;
- parlays; and
- live or in-game markets.

Adding any excluded market requires a separately preregistered protocol and an
untouched evidence boundary.

## Primary decision timestamp

The primary decision timestamp is exactly `T-60 minutes`, where `T` is the
authoritative scheduled kickoff for the canonical game. Every primary market
observation must be a pre-kickoff observation.

The deterministic selector will use the nearest eligible observation at or
before `T-60`, subject to a maximum nearest-prior tolerance. The exact tolerance
and provider timestamp granularity are provider-feasibility parameters because
the available cadence is not yet known. They must be frozen before historical
odds acquisition or any joined performance inspection.

The following substitutions are prohibited:

- an observation after `T-60` may not replace the primary snapshot;
- the best price observed at any time before kickoff may not be used; and
- opening or closing prices may not replace the primary `T-60` result.

Opening and closing prices may be studied later only as separately declared
secondary analyses. They cannot revise or substitute for the primary result.

## Market and price representation

The study must keep two roles distinct:

- **Reference market:** the eligible market observations used to estimate the
  no-vig fair probability and model edge.
- **Executable price:** an actual eligible offered price used to calculate
  candidate EV and realized flat-stake return.

The eligible bookmaker universe, reference-market consensus construction, and
executable-price bookmaker universe are provider-feasibility parameters. They
must be frozen before joined performance inspection. Books may not be selected
retrospectively based on profitability.

## Implied probability and vig removal

For decimal odds `d`, implied probability is `1 / d`. For positive moneyline odds
`a`, implied probability is:

```text
a > 0: 100 / (a + 100)
a < 0: (-a) / ((-a) + 100)
```

For the two eligible full-game moneyline sides, the primary no-vig method is
proportional normalization:

```text
fair_home = implied_home / (implied_home + implied_away)
fair_away = implied_away / (implied_home + implied_away)
```

No alternate no-vig method may be tuned or substituted in the primary protocol.

## Model edge and selected side

The selected side is the frozen model-selected side from the probability
evidence. Historical prices must not be used to re-select the side.

For that selected side:

```text
edge = model_selected_side_probability
       - no_vig_market_probability_for_selected_side
```

The reference market supplies the no-vig probability. The executable price
supplies realized EV and return calculations.

## Candidate threshold family

The complete primary threshold family is frozen to exactly:

```text
0%, 2%, 3%, 4%, 5%, 6%, 8%, 10%
```

For each threshold, the candidate policy is:

```text
bet when edge >= threshold
```

No arbitrary continuous optimizer, additional threshold family, or unreported
threshold search is permitted.

## Minimum sample and staking

A threshold is eligible for primary policy selection only if it produces at
least 100 eligible bets in the 2021-2023 development cohort.

Every eligible wager uses a flat 1-unit stake. This protocol does not optimize or
use:

- Kelly fractions;
- variable stakes;
- confidence weighting; or
- bankroll compounding.

Those methods require separately preregistered research on untouched evidence.

## Primary policy selection

Selection occurs only on the 2021-2023 development cohort and selects one global
threshold. Separate thresholds may not be selected by:

- early versus mature route;
- favorite versus underdog;
- home versus away;
- team;
- season;
- sportsbook;
- conference or division;
- probability bucket; or
- any other subgroup.

Subgroup results may be descriptive diagnostics only. A subgroup policy requires
a new preregistration and untouched future evidence.

The selection framework is frozen as follows:

1. A threshold must satisfy the 100-bet minimum.
2. It must have positive development net return.
3. Every threshold must report ROI, net units, number of bets, win/loss/push/tie
   handling, average offered price, average model edge, and calibration/edge
   diagnostics.
4. The analysis must assess whether larger estimated edge generally corresponds
   to stronger realized performance.
5. Exactly one global policy may be selected using only the preregistered
   development evidence.

The winner is not automatically the threshold with the largest ROI point
estimate. If multiple thresholds remain plausible, prefer the simpler,
lower-threshold policy unless a higher threshold demonstrates materially stronger
evidence. This version intentionally does not invent a numeric definition of
`materially stronger`. If a deterministic tie-break is required, its exact rule
must be frozen in a versioned amendment before the first joined performance
inspection. Without such an amendment, an ambiguous development result must be
reported as no unique policy selection rather than resolved retrospectively.

## Historical confirmation and exposed evaluation

After one threshold is selected on 2021-2023:

1. Freeze the threshold.
2. Apply it unchanged to the locked 2024 historical confirmation cohort.
3. Do not revise it in response to the 2024 result.

If 2024 disappoints, report that result. Reopening the threshold grid and
presenting a revised threshold as confirmed is prohibited.

Apply the same selected policy unchanged to 2025 and label every result
`EXPOSED_MODEL_HOLDOUT`. Report 2025 separately and never describe it as pristine
independent confirmation.

Do not use 2026+ outcomes for policy selection or retroactive threshold tuning.
They belong only to forward/prospective monitoring.

## Eligibility and missing-market rules

A research row is eligible only when all of the following hold:

- canonical game identity mapping is unambiguous;
- both required two-way full-game moneyline sides are present;
- the frozen source and bookmaker eligibility requirements are met;
- the market timestamp satisfies the frozen PIT selector and tolerance;
- prices are valid rather than suspended or placeholders; and
- the selected-side price is available under the frozen executable-price policy.

Missing betting prices must not be imputed. Every exclusion must receive a
machine-readable reason. Provider-specific timestamp tolerance and bookmaker
requirements remain unresolved until feasibility research, but must be frozen
before the first joined performance analysis.

## Ties, pushes, voids, and cancellations

Ties, pushes, voids, and cancelled games may not be silently treated as wins or
losses. Event settlement must follow the documented convention for the historical
moneyline market. Provider/book-specific settlement metadata and deterministic
handling must be frozen before joined performance analysis. Report ties, pushes,
voids, and cancellations separately.

## Multiple testing and reporting

The eight thresholds are the complete primary testing family. Results for every
threshold must be reported, including losing and sample-ineligible thresholds.
No threshold or subgroup may be suppressed because of its result.

No additional threshold family or subgroup policy introduced after viewing
development performance may be described as confirmatory. Any such analysis must
be labeled exploratory.

## Provider-feasibility parameters still open

Only the following provider-dependent parameters remain open:

- provider/source;
- bookmaker universe;
- reference-market construction;
- executable-price bookmaker universe;
- exact `T-60` nearest-prior tolerance;
- timestamp granularity;
- historical market availability and coverage;
- provider-specific void/tie settlement metadata; and
- licensing, cost, and storage terms.

These parameters may be researched in Phase 4C1B-2 without joining odds to model
outputs, outcomes, or performance. They must be frozen in an immutable protocol
amendment or successor before historical market performance is inspected.

The numeric meaning of `materially stronger`, if required for deterministic
threshold tie-breaking, is a separate pre-join policy decision rather than a
provider-feasibility parameter. It must also be frozen before joined performance
inspection or left unresolved with no unique policy selected.

## Amendment policy

Protocol versions are immutable evidence identities. Do not overwrite the
meaning of `nfl_historical_market_research_0.1.0`.

If a rule changes before any joined performance has been observed:

1. Create a documented successor protocol version or amendment.
2. Record exactly what changed and why.
3. Preserve the prior version and its review evidence.

If a rule changes after joined performance has been observed:

- classify the revised analysis as exploratory;
- do not overwrite or relabel version `0.1.0`;
- do not present the revision as confirmatory on already observed evidence; and
- require a new untouched or prospective evidence boundary for confirmatory
  claims.

## Required future outputs

Later implementation must produce at minimum:

- provider and raw-market provenance;
- canonical game mapping;
- deterministic `T-60` snapshot selection;
- reference no-vig probabilities;
- executable prices;
- model edge;
- candidate-policy eligibility;
- machine-readable exclusion reasons;
- the complete eight-threshold table;
- the 2021-2023 development selection result;
- the untouched 2024 confirmation result;
- a separate 2025 exposed evaluation; and
- forward 2026+ tracking.

Every output must retain the applicable protocol version, source identities,
input hashes, deterministic ordering, cohort role, and validation result.

## Leakage prohibition

Neither historical outcomes nor historical betting returns may be used to change
the frozen model probabilities, routes, features, model artifacts, or Phase 4C1A
evidence. Historical market results may only be used within the policy-development
role assigned by this preregistered protocol.
