from collections.abc import Sequence

from sportsmodel.features.builders.base import (
    FeatureBuilder,
)
from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.provider import (
    FeatureDataProvider,
)
from sportsmodel.models.historical_pitcher_start import (
    HistoricalPitcherStart,
)
from sportsmodel.models.starting_pitcher_features import (
    StartingPitcherFeatures,
)


SEASON_START_LIMIT = 50
LAST_5_WINDOW_SIZE = 5


class StartingPitcherFeatureBuilder(
    FeatureBuilder[StartingPitcherFeatures],
):
    """
    Build point-in-time historical features for an expected starter.

    Season statistics use starts from the prediction game's calendar
    year. Last-five statistics use the pitcher's five most recent starts
    available before the feature cutoff, including the prior season when
    fewer than five current-season starts exist.
    """

    def __init__(
        self,
        *,
        player_id: int | None,
    ) -> None:
        if player_id is not None and player_id <= 0:
            raise ValueError(
                "Starting pitcher player ID must be greater than zero "
                "when provided."
            )

        self._player_id = player_id

    @property
    def player_id(self) -> int | None:
        """
        Return the expected starting pitcher's canonical player ID.
        """

        return self._player_id

    def build(
        self,
        context: FeatureGenerationContext,
        provider: FeatureDataProvider,
    ) -> StartingPitcherFeatures:
        """
        Generate historical features for the configured starter.
        """

        self._validate_provider_context(
            context=context,
            provider=provider,
        )

        if self._player_id is None:
            return _build_unavailable_features()

        historical_starts = (
            provider.get_completed_pitcher_starts(
                player_id=self._player_id,
                limit=SEASON_START_LIMIT,
            )
        )

        season_starts = tuple(
            start
            for start in historical_starts
            if (
                start.game_start_time.year
                == context.game_start_time.year
            )
        )

        last_5_starts = historical_starts[
            :LAST_5_WINDOW_SIZE
        ]

        return StartingPitcherFeatures(
            player_id=self._player_id,
            starter_available=True,
            starts_season=len(season_starts),
            starts_last_5=len(last_5_starts),
            innings_per_start_season=(
                _calculate_innings_per_start(
                    starts=season_starts,
                )
            ),
            earned_run_average_season=(
                _calculate_earned_run_average(
                    starts=season_starts,
                )
            ),
            earned_run_average_last_5=(
                _calculate_earned_run_average(
                    starts=last_5_starts,
                )
            ),
            whip_season=_calculate_whip(
                starts=season_starts,
            ),
            whip_last_5=_calculate_whip(
                starts=last_5_starts,
            ),
            strikeouts_per_nine_season=(
                _calculate_per_nine(
                    starts=season_starts,
                    statistic_name="strikeouts",
                )
            ),
            walks_per_nine_season=(
                _calculate_per_nine(
                    starts=season_starts,
                    statistic_name="walks_allowed",
                )
            ),
            home_runs_per_nine_season=(
                _calculate_per_nine(
                    starts=season_starts,
                    statistic_name="home_runs_allowed",
                )
            ),
            days_rest=_calculate_days_rest(
                context=context,
                starts=historical_starts,
            ),
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


def _build_unavailable_features() -> StartingPitcherFeatures:
    """
    Return features for a game without a known expected starter.
    """

    return StartingPitcherFeatures(
        player_id=None,
        starter_available=False,
        starts_season=0,
        starts_last_5=0,
        innings_per_start_season=None,
        earned_run_average_season=None,
        earned_run_average_last_5=None,
        whip_season=None,
        whip_last_5=None,
        strikeouts_per_nine_season=None,
        walks_per_nine_season=None,
        home_runs_per_nine_season=None,
        days_rest=None,
    )


def _calculate_innings_per_start(
    *,
    starts: Sequence[HistoricalPitcherStart],
) -> float | None:
    if not starts:
        return None

    pitching_outs = sum(
        start.statistics.pitching_outs
        for start in starts
    )

    innings_pitched = pitching_outs / 3

    return innings_pitched / len(starts)


def _calculate_earned_run_average(
    *,
    starts: Sequence[HistoricalPitcherStart],
) -> float | None:
    pitching_outs = _sum_pitching_outs(starts)

    if pitching_outs == 0:
        return None

    earned_runs = sum(
        start.statistics.earned_runs_allowed
        for start in starts
    )

    return earned_runs * 27 / pitching_outs


def _calculate_whip(
    *,
    starts: Sequence[HistoricalPitcherStart],
) -> float | None:
    pitching_outs = _sum_pitching_outs(starts)

    if pitching_outs == 0:
        return None

    hits_allowed = sum(
        start.statistics.hits_allowed
        for start in starts
    )

    walks_allowed = sum(
        start.statistics.walks_allowed
        for start in starts
    )

    return (
        hits_allowed
        + walks_allowed
    ) * 3 / pitching_outs


def _calculate_per_nine(
    *,
    starts: Sequence[HistoricalPitcherStart],
    statistic_name: str,
) -> float | None:
    pitching_outs = _sum_pitching_outs(starts)

    if pitching_outs == 0:
        return None

    statistic_total = sum(
        getattr(
            start.statistics,
            statistic_name,
        )
        for start in starts
    )

    return statistic_total * 27 / pitching_outs


def _sum_pitching_outs(
    starts: Sequence[HistoricalPitcherStart],
) -> int:
    return sum(
        start.statistics.pitching_outs
        for start in starts
    )


def _calculate_days_rest(
    *,
    context: FeatureGenerationContext,
    starts: Sequence[HistoricalPitcherStart],
) -> int | None:
    """
    Calculate completed calendar rest days since the latest start.

    Game days themselves are excluded. For example, a prior start on
    July 20 and the current game on July 26 represents five days rest.
    """

    if not starts:
        return None

    latest_start = starts[0]

    elapsed_calendar_days = (
        context.game_start_time.date()
        - latest_start.game_start_time.date()
    ).days

    return max(
        elapsed_calendar_days - 1,
        0,
    )
