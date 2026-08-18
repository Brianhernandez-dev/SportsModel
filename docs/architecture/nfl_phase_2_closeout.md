# NFL Phase 2 Closeout

## Status

**NFL Phase 2: COMPLETE**

The Phase 2D baseline specification was frozen and source-controlled before
the one-time 2025 historical holdout evaluation. The holdout was subsequently
exposed once, using that frozen specification, and the first result is now a
permanent project checkpoint.

## Frozen baseline

| Contract | Frozen value |
|---|---|
| Specification | `nfl_moneyline_frozen_0.1.0` |
| Feature schema | `nfl_moneyline_0.2.0` |
| Target | `home_win`; tied targets excluded |
| Training population | NFL seasons 2018-2024, by NFL season identifier |
| Final historical holdout | NFL season 2025, by NFL season identifier |
| Eligibility | Both teams have at least 3 prior same-season eligible games |
| Representation | Exact ordered 19-feature symmetric matchup representation |
| Classifier | `LogisticRegression(C=1.0, solver="lbfgs", max_iter=5000, random_state=42)` |
| Preprocessing | Training-only median imputation, then training-only `StandardScaler` |

The baseline does not cover games where either team has fewer than three
same-season prior eligible games. Those games were excluded, not silently
imputed into eligibility. The frozen baseline is not intended to solve the
opening portion of the NFL season.

## Development evidence

Development policy selection used only the 2022 and 2023 validation folds.
Minimum-history-3 was selected before the 2024 confirmation fold was exposed
to that policy decision.

| Development view | Rows | Accuracy | Log loss | Brier | ROC-AUC |
|---|---:|---:|---:|---:|---:|
| Policy selection, 2022-2023 | 472 | 0.616525 | 0.664243 | 0.236089 | 0.621360 |
| Fixed-policy confirmation, 2024 | 237 | 0.687764 | 0.619581 | 0.214610 | 0.721645 |
| Post-selection descriptive aggregate, 2022-2024 | 709 | 0.640339 | 0.649314 | 0.228909 | 0.656497 |

The aggregate development figures are descriptive and are not an independent
holdout estimate because the earlier folds participated in policy selection.

## First untouched 2025 holdout result

The immutable local report is
`artifacts/nfl_2025_final_holdout.json`. Its official report fingerprint is:

```text
29a7a790b6039c12edd276ceabfafe72c4845bc6ac2310d7874ee5da5e715dd3
```

The generated JSON remains local rather than source-controlled. This document
preserves the frozen specification, fingerprint, and material result metadata.

Population:

| Available | Eligible | Excluded |
|---:|---:|---:|
| 284 | 236 | 48 |

Model performance on the eligible population:

| Metric | Estimate | Deterministic 95% bootstrap CI |
|---|---:|---:|
| Accuracy | 0.6313559322033898 | [0.576271186440678, 0.6886652542372881] |
| Log loss | 0.637767349023574 | [0.5962375904074968, 0.678377671696293] |
| Brier score | 0.22404653075048422 | [0.20504830108752214, 0.24271545766965494] |
| ROC-AUC | 0.6875 | [0.6185925764897808, 0.7468469468888994] |

Additional diagnostics:

- expected calibration error: `0.033694679524236576`;
- mean predicted home-win probability: `0.5500723376294806`; and
- actual home-win rate: `0.5254237288135594`.

The training-only empirical home baseline was evaluated on the exact same 236
eligible games:

| Metric | Baseline | Model minus baseline | Deterministic 95% paired CI |
|---|---:|---:|---:|
| Accuracy | 0.5254237288135594 | +0.10593220338983045 | [+0.0316737288135593, +0.17796610169491528] |
| Log loss | 0.6931205839738949 | -0.05535323495032085 | [-0.09588084902260088, -0.015737216209662334] |
| Brier score | 0.24998239085704307 | -0.02593586010655885 | [-0.04456529764557289, -0.007414504943291525] |

Regular-season performance was 223 games, accuracy
`0.6233183856502242`, log loss `0.6417911936789941`, Brier score
`0.22600945140578352`, and ROC-AUC `0.676271186440678`. The postseason
population contained only 13 eligible games and is intentionally too small
for meaningful standalone interpretation.

## Interpretation

The baseline passed its first untouched historical generalization test. It
demonstrated predictive information beyond the training-only empirical
home-team baseline on the frozen eligible population: all three paired
intervals above exclude zero in the favorable direction.

This result does **not** demonstrate:

- profitable betting performance;
- positive expected value against sportsbook prices;
- complete-season coverage;
- early-season predictive ability;
- postseason reliability; or
- superiority to future richer NFL models.

No market odds were evaluated, so probability discrimination must not be
translated into a profitability or betting-edge claim.

## Holdout exposure rule

**2025 IS NOW EXPOSED.**

NFL season 2025 may never again be described as an untouched holdout for a
model developed after this checkpoint. Future models may report 2025 results
descriptively, but feature, model, hyperparameter, eligibility, or policy
decisions informed by those results cannot claim independent validation from
2025.

The next genuinely unseen evidence must come from future forward NFL seasons,
beginning with the 2026 NFL season.

Any modification after this checkpoint is new model development. The frozen
Phase 2 baseline and its result must remain unchanged as the historical
reference.

## Next phase

**NFL Phase 3A — Early-Season Coverage**

Design and validate a separate point-in-time-safe strategy for games where one
or both teams have fewer than three current-season prior eligible games. This
work should address the frozen baseline's coverage limitation without
altering, retuning, or replacing the Phase 2 checkpoint. Phase 3A is not part
of this closeout.
