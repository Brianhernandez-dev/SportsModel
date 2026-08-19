# NFL Phase 3A3 early-season frozen candidate

## Status and purpose

The early-route candidate is frozen as `nfl_moneyline_early_frozen_0.1.0`
for prospective evaluation beginning with the 2026 NFL season. It is separate
from the mature `nfl_moneyline_frozen_0.1.0` model.

This is a parsimony decision, not a claim that retrospective optimization found
a winner. The predefined Phase 3A2 prior-season-only diagnostic was at least as
good descriptively as the larger 11-feature model, while the 0–2-game current
season features did not demonstrate clear incremental probability value. The
smaller candidate therefore avoids additional tuning against exposed history.

## Learned contract

Feature schema: `nfl_moneyline_early_0.1.0`.

The fitted vector contains exactly four ordered matchup differences:

1. `prior_season_games_played_difference`
2. `prior_season_win_percentage_difference`
3. `prior_season_average_point_differential_difference`
4. `prior_season_average_turnover_differential_difference`

Current-season aggregates, minimum current history, and neutral-site status do
not enter learned X. They remain available as routing or audit metadata. No
manual neutral-site adjustment exists.

The pipeline is fixed as training-row median imputation, training-row standard
scaling, and logistic regression with `C=1.0`, `solver="lbfgs"`,
`max_iter=5000`, and `random_state=42`. Training uses all 285 eligible early
targets from NFL seasons 2019–2024. Season 2018 is excluded because complete
2017 prior-season inputs are unavailable. Season 2025 is excluded.

The deterministic metadata artifact is
`artifacts/nfl_moneyline_early_frozen_0.1.0.json`. It records the source dataset
hash, specification hash, fitted preprocessing statistics, coefficients,
intercept, training home-win baseline, and model hash. It is not a binary model
pickle.

## Evidence status

**2019–2025 historical evidence is exposed for this model family. The next
genuinely unseen evidence is 2026 forward performance.**

Any Phase 3A3 reproduction over 2019–2024 is labeled `RETROSPECTIVE CONSISTENCY
ONLY — NOT VALIDATION`. It verifies deterministic implementation and artifact
identity. It is not independent evidence, a holdout, or a reason to revise the
specification. No 2025 outcomes are used for the new fit or model selection.

The historical sample is small—approximately 47–48 early targets per season—so
one forward season will remain uncertain. Multiple forward seasons may be
needed before drawing strong conclusions.

## Routing relationship

Routing uses actual PIT-safe current-season prior-game counts, never scheduled
week:

```text
if home_current_prior_games >= 3 and away_current_prior_games >= 3:
    model = nfl_moneyline_frozen_0.1.0
else:
    model = nfl_moneyline_early_frozen_0.1.0
```

The estimators remain independently versioned and fitted.

## 2026 forward protocol

Predictions must be generated and durably identified before target outcomes are
known. Each future record must retain game and kickoff identity, teams, both PIT
prior-game counts, route, model and feature versions, cutoff, probability,
predicted side, eventual result/tie status, and prediction timestamp/run ID.

Report accuracy, log loss, Brier score, ROC-AUC when both classes occur,
predicted mean, actual home-win rate, calibration, and ECE against the frozen
training-derived empirical home baseline on the exact same rows. Report early
and mature routes separately; combined reporting must not hide either route.
Early history states 0, 1, and 2 are descriptive and cannot drive midseason
changes.

Once forward predictions begin, this specification must not be modified in
place. Successors require a new version and must preserve original predictions.
Do not tune after Week 1, Week 2, or Week 3. Forward evaluation is evidence
collection, not continuous adaptation.

## Probability validation before market validation

The MLB architecture correctly separates stored model probabilities from later
odds capture, expected-value policy, paper candidates, and settlement. A future
NFL pipeline should use the same conceptual boundary:

- **Model validation:** evaluate the frozen pregame probabilities independently
  of sportsbook prices.
- **Market validation:** only after separate odds ingestion exists, evaluate
  whether those frozen probabilities create value at contemporaneous prices.

Phase 3A3 implements no NFL odds ingestion, market features, betting policy,
settlement, scheduler, or live orchestration. Probability-forward validation
comes first.

## Known limitations

The frozen candidate has no quarterback, injury, roster-turnover, coaching,
weather, travel, Elo, EPA, or market-odds information. It deliberately excludes
current-season 0–2-game statistics from learned X. The turnover feature may be
noisy but remains because removing it after observing Phase 3A2 would create a
new selection experiment. Nothing here establishes profitable betting
performance.
