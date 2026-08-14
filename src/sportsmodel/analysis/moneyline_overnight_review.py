from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sportsmodel.models.moneyline_live_dashboard import (
    MoneylineLiveGame,
)
from sportsmodel.models.moneyline_preview_dashboard import (
    MoneylinePreviewGame,
)


SURVIVED_TO_MORNING = "SURVIVED TO MORNING"
VALUE_LOST_OVERNIGHT = "VALUE LOST OVERNIGHT"
NEW_MORNING_VALUE = "NEW MORNING VALUE"
MODEL_LEAN_CHANGED = "MODEL LEAN CHANGED"
STILL_POLICY_BLOCKED = "STILL POLICY BLOCKED"
NO_VALUE = "NO VALUE"


@dataclass(frozen=True)
class MoneylineOvernightReviewGame:
    """
    Read-only 11 PM preview vs morning official comparison.
    """

    game_id: int
    game_start_time: datetime

    away_team_name: str
    home_team_name: str

    late_night_selection_name: str
    official_selection_name: str

    late_night_model_probability: Decimal
    official_model_probability: Decimal

    late_night_price: int
    official_price: int

    late_night_sportsbook_name: str
    official_sportsbook_name: str

    late_night_model_expected_value: Decimal
    official_model_expected_value: Decimal

    late_night_model_market_edge: Decimal
    official_model_market_edge: Decimal

    late_night_policy_pass: bool
    official_policy_pass: bool

    late_night_value_signal: bool

    official_disqualification_reasons: tuple[str, ...]

    status: str

    @property
    def selection_changed(self) -> bool:
        return (
            self.late_night_selection_name
            != self.official_selection_name
        )


def classify_moneyline_overnight_status(
    *,
    late_night_selection_name: str,
    official_selection_name: str,
    late_night_policy_pass: bool,
    official_policy_pass: bool,
    late_night_value_signal: bool,
) -> str:
    """
    Describe how an overnight preview changed by morning.
    """

    if (
        late_night_selection_name
        != official_selection_name
    ):
        return MODEL_LEAN_CHANGED

    if (
        late_night_policy_pass
        and official_policy_pass
    ):
        return SURVIVED_TO_MORNING

    if (
        late_night_policy_pass
        and not official_policy_pass
    ):
        return VALUE_LOST_OVERNIGHT

    if (
        not late_night_policy_pass
        and official_policy_pass
    ):
        return NEW_MORNING_VALUE

    if late_night_value_signal:
        return STILL_POLICY_BLOCKED

    return NO_VALUE


def build_moneyline_overnight_review(
    *,
    late_night_games: tuple[
        MoneylinePreviewGame,
        ...,
    ],
    official_games: tuple[
        MoneylineLiveGame,
        ...,
    ],
) -> tuple[MoneylineOvernightReviewGame, ...]:
    """
    Compare matched games from the 11 PM preview and official card.
    """

    official_by_game = {
        game.game_id: game
        for game in official_games
    }

    review: list[
        MoneylineOvernightReviewGame
    ] = []

    for late_game in late_night_games:
        official = official_by_game.get(
            late_game.game_id
        )

        if official is None:
            continue

        status = classify_moneyline_overnight_status(
            late_night_selection_name=(
                late_game.predicted_team_name
            ),
            official_selection_name=(
                official.predicted_team_name
            ),
            late_night_policy_pass=(
                late_game.preview_policy_pass
            ),
            official_policy_pass=(
                official.qualifies_as_paper_candidate
            ),
            late_night_value_signal=(
                late_game.preview_value_signal
            ),
        )

        review.append(
            MoneylineOvernightReviewGame(
                game_id=late_game.game_id,
                game_start_time=(
                    official.game_start_time
                ),
                away_team_name=(
                    official.away_team_name
                ),
                home_team_name=(
                    official.home_team_name
                ),
                late_night_selection_name=(
                    late_game.predicted_team_name
                ),
                official_selection_name=(
                    official.predicted_team_name
                ),
                late_night_model_probability=(
                    late_game.model_probability
                ),
                official_model_probability=(
                    official.model_probability
                ),
                late_night_price=(
                    late_game.price
                ),
                official_price=(
                    official.price
                ),
                late_night_sportsbook_name=(
                    late_game.sportsbook_name
                ),
                official_sportsbook_name=(
                    official.sportsbook_name
                ),
                late_night_model_expected_value=(
                    late_game.model_expected_value
                ),
                official_model_expected_value=(
                    official.model_expected_value
                ),
                late_night_model_market_edge=(
                    late_game.model_market_edge
                ),
                official_model_market_edge=(
                    official.model_market_edge
                ),
                late_night_policy_pass=(
                    late_game.preview_policy_pass
                ),
                official_policy_pass=(
                    official
                    .qualifies_as_paper_candidate
                ),
                late_night_value_signal=(
                    late_game.preview_value_signal
                ),
                official_disqualification_reasons=(
                    official
                    .disqualification_reasons
                ),
                status=status,
            )
        )

    priority = {
        VALUE_LOST_OVERNIGHT: 0,
        NEW_MORNING_VALUE: 1,
        SURVIVED_TO_MORNING: 2,
        MODEL_LEAN_CHANGED: 3,
        STILL_POLICY_BLOCKED: 4,
        NO_VALUE: 5,
    }

    review.sort(
        key=lambda row: (
            priority[row.status],
            -row.official_model_expected_value,
            row.game_start_time,
        )
    )

    return tuple(review)
