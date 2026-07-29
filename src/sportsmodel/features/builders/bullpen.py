from collections.abc import Sequence
from datetime import datetime, timedelta

from sportsmodel.features.builders.base import (
    FeatureBuilder,
)
from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.provider import (
    FeatureDataProvider,
)
from sportsmodel.models.bullpen_features import (
    BullpenFeatures,
)
from sportsmodel.models.historical_bullpen_appearance import (
    HistoricalBullpenAppearance,
)


SEASON_GAME_LIMIT = 200
LAST_10_WINDOW_SIZE = 10


class BullpenFeatureBuilder(
    FeatureBuilder[BullpenFeatures],
):
    """
    Build point-in-time bullpen performance and workload features.
    """

    def __init__(
        self,
        *,
        team_id: int,
    ) -> None:
        if team_id <= 0:
            raise ValueError(
                "Bullpen feature builder team ID must be greater "
                "than zero."
            )

        self._team_id = team_id

    @property
    def team_id(self) -> int:
        return self._team_id

    def build(
        self,
        context: FeatureGenerationContext,
        provider: FeatureDataProvider,
    ) -> BullpenFeatures:
        self._validate_context_team(context)

        self._validate_provider_context(
            context=context,
            provider=provider,
        )

        appearances = (
            provider.get_completed_relief_appearances(
                team_id=self._team_id,
            )
        )

        historical_games = provider.get_completed_team_games(
            team_id=self._team_id,
            limit=SEASON_GAME_LIMIT,
        )

        last_10_games = historical_games[
            :LAST_10_WINDOW_SIZE
        ]

        last_10_game_ids = {
            game.game_id
            for game in last_10_games
        }

        last_10_appearances = tuple(
            appearance
            for appearance in appearances
            if appearance.game_id in last_10_game_ids
        )

        previous_game_appearances = (
            _get_game_appearances(
                appearances=appearances,
                game_id=historical_games[0].game_id,
            )
            if historical_games
            else ()
        )

        back_to_back_usage_count = (
            _calculate_back_to_back_usage_count(
                appearances=appearances,
                previous_game_id=historical_games[0].game_id,
                second_previous_game_id=historical_games[1].game_id,
            )
            if len(historical_games) >= 2
            else None
        )

        return BullpenFeatures(
            relief_appearances_season=len(appearances),
            bullpen_earned_run_average_season=(
                _calculate_earned_run_average(
                    appearances=appearances,
                )
            ),
            bullpen_earned_run_average_last_10=(
                _calculate_earned_run_average(
                    appearances=last_10_appearances,
                )
            ),
            bullpen_whip_season=_calculate_whip(
                appearances=appearances,
            ),
            bullpen_whip_last_10=_calculate_whip(
                appearances=last_10_appearances,
            ),
            relief_innings_last_1_day=(
                _calculate_recent_relief_innings(
                    appearances=appearances,
                    cutoff_time=context.cutoff_time,
                    days=1,
                )
            ),
            relief_innings_last_3_days=(
                _calculate_recent_relief_innings(
                    appearances=appearances,
                    cutoff_time=context.cutoff_time,
                    days=3,
                )
            ),
            relief_innings_last_7_days=(
                _calculate_recent_relief_innings(
                    appearances=appearances,
                    cutoff_time=context.cutoff_time,
                    days=7,
                )
            ),
            relievers_used_previous_game=(
                len(previous_game_appearances)
                if historical_games
                else None
            ),
            back_to_back_usage_count=(
                back_to_back_usage_count
            ),
            games_in_last_10_window=len(last_10_games),
        )

    def _validate_context_team(
        self,
        context: FeatureGenerationContext,
    ) -> None:
        if self._team_id not in {
            context.home_team_id,
            context.away_team_id,
        }:
            raise ValueError(
                "Bullpen feature builder team ID must match the "
                "home or away team in the feature context."
            )

    @staticmethod
    def _validate_provider_context(
        *,
        context: FeatureGenerationContext,
        provider: FeatureDataProvider,
    ) -> None:
        if provider.context != context:
            raise ValueError(
                "Feature data provider context must match the "
                "builder context."
            )


def _calculate_earned_run_average(
    *,
    appearances: Sequence[HistoricalBullpenAppearance],
) -> float | None:
    pitching_outs = sum(
        appearance.statistics.pitching_outs
        for appearance in appearances
    )

    if pitching_outs == 0:
        return None

    earned_runs = sum(
        appearance.statistics.earned_runs_allowed
        for appearance in appearances
    )

    return earned_runs * 27 / pitching_outs


def _calculate_whip(
    *,
    appearances: Sequence[HistoricalBullpenAppearance],
) -> float | None:
    pitching_outs = sum(
        appearance.statistics.pitching_outs
        for appearance in appearances
    )

    if pitching_outs == 0:
        return None

    hits_and_walks = sum(
        (
            appearance.statistics.hits_allowed
            + appearance.statistics.walks_allowed
        )
        for appearance in appearances
    )

    return hits_and_walks * 3 / pitching_outs


def _calculate_recent_relief_innings(
    *,
    appearances: Sequence[HistoricalBullpenAppearance],
    cutoff_time: datetime,
    days: int,
) -> float:
    window_start = cutoff_time - timedelta(
        days=days,
    )

    pitching_outs = sum(
        appearance.statistics.pitching_outs
        for appearance in appearances
        if appearance.game_start_time >= window_start
    )

    return pitching_outs / 3


def _get_game_appearances(
    *,
    appearances: Sequence[HistoricalBullpenAppearance],
    game_id: int,
) -> tuple[HistoricalBullpenAppearance, ...]:
    return tuple(
        appearance
        for appearance in appearances
        if appearance.game_id == game_id
    )


def _calculate_back_to_back_usage_count(
    *,
    appearances: Sequence[HistoricalBullpenAppearance],
    previous_game_id: int,
    second_previous_game_id: int,
) -> int:
    previous_game_pitchers = {
        appearance.statistics.baseball_player_id
        for appearance in appearances
        if appearance.game_id == previous_game_id
    }

    second_previous_game_pitchers = {
        appearance.statistics.baseball_player_id
        for appearance in appearances
        if appearance.game_id == second_previous_game_id
    }

    return len(
        previous_game_pitchers
        & second_previous_game_pitchers
    )
