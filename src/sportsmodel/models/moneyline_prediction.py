from dataclasses import dataclass
from datetime import datetime
from math import isclose


VALID_STARTER_COVERAGE = {
    "both",
    "partial",
    "none",
}


@dataclass(frozen=True)
class MoneylineGamePrediction:
    """
    One immutable pregame MLB Moneyline prediction snapshot.
    """

    moneyline_prediction_run_id: int

    game_id: int

    mlb_game_id: int | None

    game_start_time: datetime

    prediction_time: datetime

    home_team_id: int

    away_team_id: int

    home_starting_pitcher_id: int | None

    away_starting_pitcher_id: int | None

    home_starting_pitcher_mlb_id: int | None

    away_starting_pitcher_mlb_id: int | None

    home_starter_features_available: bool

    away_starter_features_available: bool

    starter_coverage: str

    missing_raw_value_count: int

    home_win_probability: float

    away_win_probability: float

    predicted_team_id: int

    predicted_probability: float

    def __post_init__(self) -> None:
        self._validate_identifiers()
        self._validate_times()
        self._validate_starters()
        self._validate_probabilities()

    def _validate_identifiers(self) -> None:
        required_identifiers = (
            self.moneyline_prediction_run_id,
            self.game_id,
            self.home_team_id,
            self.away_team_id,
            self.predicted_team_id,
        )

        if any(
            identifier <= 0
            for identifier in required_identifiers
        ):
            raise ValueError(
                "Prediction identifiers must be greater than zero."
            )

        optional_identifiers = (
            self.mlb_game_id,
            self.home_starting_pitcher_id,
            self.away_starting_pitcher_id,
            self.home_starting_pitcher_mlb_id,
            self.away_starting_pitcher_mlb_id,
        )

        if any(
            identifier is not None
            and identifier <= 0
            for identifier in optional_identifiers
        ):
            raise ValueError(
                "Optional prediction identifiers must be greater "
                "than zero when provided."
            )

        if self.home_team_id == self.away_team_id:
            raise ValueError(
                "Home and away teams must be different."
            )

        if self.predicted_team_id not in {
            self.home_team_id,
            self.away_team_id,
        }:
            raise ValueError(
                "Predicted team must be the home or away team."
            )

        if self.missing_raw_value_count < 0:
            raise ValueError(
                "Missing raw-value count cannot be negative."
            )

    def _validate_times(self) -> None:
        for value, label in (
            (
                self.game_start_time,
                "Game start time",
            ),
            (
                self.prediction_time,
                "Prediction time",
            ),
        ):
            if (
                value.tzinfo is None
                or value.utcoffset() is None
            ):
                raise ValueError(
                    f"{label} must be timezone-aware."
                )

        if self.prediction_time > self.game_start_time:
            raise ValueError(
                "Prediction time cannot occur after game start."
            )

    def _validate_starters(self) -> None:
        if (
            self.starter_coverage
            not in VALID_STARTER_COVERAGE
        ):
            raise ValueError(
                "Starter coverage must be both, partial, or none."
            )

        self._validate_starter_mapping(
            side="Home",
            canonical_player_id=(
                self.home_starting_pitcher_id
            ),
            mlb_player_id=(
                self.home_starting_pitcher_mlb_id
            ),
            features_available=(
                self.home_starter_features_available
            ),
        )

        self._validate_starter_mapping(
            side="Away",
            canonical_player_id=(
                self.away_starting_pitcher_id
            ),
            mlb_player_id=(
                self.away_starting_pitcher_mlb_id
            ),
            features_available=(
                self.away_starter_features_available
            ),
        )

        starter_count = sum(
            player_id is not None
            for player_id in (
                self.home_starting_pitcher_mlb_id,
                self.away_starting_pitcher_mlb_id,
            )
        )

        expected_coverage = {
            0: "none",
            1: "partial",
            2: "both",
        }[starter_count]

        if self.starter_coverage != expected_coverage:
            raise ValueError(
                "Starter coverage does not match the available "
                "probable-pitcher IDs."
            )

    @staticmethod
    def _validate_starter_mapping(
        *,
        side: str,
        canonical_player_id: int | None,
        mlb_player_id: int | None,
        features_available: bool,
    ) -> None:
        if (
            canonical_player_id is None
        ) != (
            mlb_player_id is None
        ):
            raise ValueError(
                f"{side} starter canonical and MLB IDs must "
                "either both be present or both be absent."
            )

        if (
            features_available
            and canonical_player_id is None
        ):
            raise ValueError(
                f"{side} starter features cannot be available "
                "without a canonical player ID."
            )

    def _validate_probabilities(self) -> None:
        for probability in (
            self.home_win_probability,
            self.away_win_probability,
            self.predicted_probability,
        ):
            if not 0.0 <= probability <= 1.0:
                raise ValueError(
                    "Prediction probabilities must be between "
                    "zero and one."
                )

        if not isclose(
            (
                self.home_win_probability
                + self.away_win_probability
            ),
            1.0,
            abs_tol=1e-9,
        ):
            raise ValueError(
                "Home and away probabilities must sum to one."
            )

        expected_probability = (
            self.home_win_probability
            if self.predicted_team_id
            == self.home_team_id
            else self.away_win_probability
        )

        if not isclose(
            self.predicted_probability,
            expected_probability,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "Predicted probability must match the selected "
                "team's win probability."
            )
