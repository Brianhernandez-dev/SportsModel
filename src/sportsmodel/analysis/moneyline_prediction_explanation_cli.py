from __future__ import annotations

import argparse

from sportsmodel.analysis.moneyline_prediction_explanation import (
    MoneylineFeatureContribution,
    MoneylinePredictionExplanation,
    explain_moneyline_prediction,
)


TOP_CONTRIBUTION_COUNT = 15


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct and explain one persisted MLB Moneyline prediction "
            "using only historical PostgreSQL state and its frozen model."
        )
    )
    parser.add_argument(
        "--prediction-id",
        type=_parse_positive_integer,
        required=True,
        help="Persisted moneyline_game_prediction_id.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        explanation = explain_moneyline_prediction(
            prediction_id=arguments.prediction_id
        )
    except Exception as error:
        print(
            "Moneyline prediction explanation failed: "
            f"{type(error).__name__}: {error}"
        )
        return 1

    print_explanation(explanation)
    return 0


def print_explanation(explanation: MoneylinePredictionExplanation) -> None:
    prediction = explanation.prediction
    print("=" * 88)
    print("SportsModel MLB Moneyline Prediction Explanation")
    print("=" * 88)
    print(
        "Authority:               "
        + (
            "AUTHORITATIVE RECONSTRUCTION"
            if explanation.authoritative
            else "NON-AUTHORITATIVE RECONSTRUCTION"
        )
    )
    print(f"Prediction ID:           {prediction.prediction_id}")
    print(f"Prediction run ID:       {prediction.prediction_run_id}")
    print(
        f"Matchup:                 {prediction.away_team_name} "
        f"at {prediction.home_team_name}"
    )
    print(
        f"Team IDs:                away={prediction.away_team_id} "
        f"home={prediction.home_team_id}"
    )
    print(f"Game ID / MLB ID:        {prediction.game_id} / {prediction.mlb_game_id}")
    print(f"Prediction time:         {prediction.prediction_time.isoformat()}")
    print(f"Game time:               {prediction.game_start_time.isoformat()}")
    print(
        "Home starter:           "
        f"{_starter_text(prediction.home_starting_pitcher_name, prediction.home_starting_pitcher_id, prediction.home_starting_pitcher_mlb_id)}"
    )
    print(
        "Away starter:           "
        f"{_starter_text(prediction.away_starting_pitcher_name, prediction.away_starting_pitcher_id, prediction.away_starting_pitcher_mlb_id)}"
    )
    print(f"Model version:           {prediction.model_version}")
    print(f"Feature schema:          {prediction.feature_schema_version}")
    print(f"Model SHA-256:           {prediction.model_artifact_sha256}")
    training_cutoff = (
        prediction.model_training_cutoff.isoformat()
        if prediction.model_training_cutoff is not None
        else "unavailable"
    )
    print(f"Model training cutoff:   {training_cutoff}")
    print(f"Stored home probability: {float(prediction.stored_home_win_probability):.12f}")
    print(
        "Reconstructed home prob: "
        f"{explanation.reconstructed_home_win_probability:.12f}"
    )
    print(f"Probability delta:       {explanation.probability_delta:+.12g}")
    print(f"Absolute tolerance:      {explanation.reconstruction_tolerance:.1e}")
    print(f"Raw feature count:       {explanation.raw_feature_count}")
    print(
        "Raw missing count:       "
        f"stored={prediction.persisted_missing_raw_value_count} "
        f"reconstructed={explanation.regenerated_missing_raw_value_count}"
    )
    print(
        "Raw missing features:    "
        f"{_names_text(explanation.raw_missing_feature_names)}"
    )
    print(
        "Transformed missing:     "
        f"{_names_text(explanation.transformed_missing_feature_names)}"
    )

    if not explanation.authoritative:
        print()
        print("WARNING: contribution rankings are not shown as historical truth.")
        print(
            "The current point-in-time database reconstruction did not match "
            "the persisted probability and missing-value evidence within the "
            "documented tolerance."
        )
        return

    print()
    print("LOGIT RECONSTRUCTION")
    print("-" * 88)
    print(f"Model intercept:         {explanation.model_intercept:+.12f}")
    print(f"Feature-logit total:     {explanation.feature_logit_total:+.12f}")
    print(f"Final logit:             {explanation.final_logit:+.12f}")

    _print_ranked_contributions(
        title=f"TOP {TOP_CONTRIBUTION_COUNT} TOWARD {prediction.home_team_name}",
        items=explanation.home_contributions[:TOP_CONTRIBUTION_COUNT],
    )
    _print_ranked_contributions(
        title=f"TOP {TOP_CONTRIBUTION_COUNT} TOWARD {prediction.away_team_name}",
        items=explanation.away_contributions[:TOP_CONTRIBUTION_COUNT],
    )
    _print_ranked_contributions(
        title="ALL STARTING-PITCHER CONTRIBUTIONS",
        items=explanation.starting_pitcher_contributions,
    )
    print(f"Starting-pitcher total:  {explanation.starting_pitcher_total:+.12f}")

    print()
    print("CATEGORY TOTALS")
    print("-" * 88)
    for category, total in explanation.category_totals:
        direction = _direction_text(
            total,
            home_name=prediction.home_team_name,
            away_name=prediction.away_team_name,
        )
        print(f"{category:20} {total:+.12f}  {direction}")


def _print_ranked_contributions(
    *,
    title: str,
    items: tuple[MoneylineFeatureContribution, ...],
) -> None:
    print()
    print(title)
    print("-" * 88)
    if not items:
        print("(none)")
        return
    for rank, item in enumerate(items, start=1):
        indicator = " [missing indicator]" if item.is_missing_indicator else ""
        print(
            f"{rank:>2}. {item.feature_name}{indicator}\n"
            f"    contribution={item.contribution:+.12f} "
            f"coefficient={item.coefficient:+.12f} "
            f"imputed={item.imputed_value:+.12f} "
            f"standardized={item.standardized_value:+.12f}"
        )


def _direction_text(value: float, *, home_name: str, away_name: str) -> str:
    if value > 0:
        return f"toward {home_name}"
    if value < 0:
        return f"toward {away_name}"
    return "neutral"


def _starter_text(
    name: str | None,
    internal_id: int | None,
    mlb_id: int | None,
) -> str:
    if internal_id is None and mlb_id is None:
        return "unavailable"
    return f"{name or 'name unavailable'} (internal={internal_id}, MLB={mlb_id})"


def _names_text(names: tuple[str, ...]) -> str:
    return ", ".join(names) if names else "none"


def _parse_positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Prediction ID must be an integer."
        ) from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            "Prediction ID must be greater than zero."
        )
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
