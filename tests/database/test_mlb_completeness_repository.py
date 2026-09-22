from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.database import mlb_completeness_repository as repository
from sportsmodel.features.builders import (
    bullpen,
    starting_pitcher,
    team_batting,
    team_pitching,
)


NOW = datetime(2026, 9, 20, 16, 0, tzinfo=timezone.utc)


def test_completeness_window_matches_team_feature_windows() -> None:
    assert repository.FEATURE_TEAM_GAME_LIMIT == (
        team_batting.SEASON_GAME_LIMIT
    )
    assert repository.FEATURE_TEAM_GAME_LIMIT == (
        team_pitching.SEASON_GAME_LIMIT
    )
    assert repository.FEATURE_TEAM_GAME_LIMIT == bullpen.SEASON_GAME_LIMIT
    assert repository.FEATURE_START_LIMIT == (
        starting_pitcher.SEASON_START_LIMIT
    )


def _complete_snapshot(
    *,
    game_pk: int = 800001,
    game_id: int = 101,
    created_at: datetime = NOW - timedelta(days=1),
) -> repository.MlbGameCompletenessSnapshot:
    return repository.MlbGameCompletenessSnapshot(
        game_pk=game_pk,
        mapping_game_ids=(game_id,),
        home_team_id=10,
        away_team_id=20,
        canonical_mlb_game_pks=(str(game_pk),),
        results=(
            repository.HistoricalResultRecord(
                game_id=game_id,
                mlb_game_id=game_pk,
                home_score=5,
                away_score=3,
            ),
        ),
        team_statistics=(
            repository.TeamStatisticsRecord(
                team_id=10,
                is_home=True,
                runs=5,
                pitching_outs=27,
                runs_allowed=3,
                earned_runs_allowed=3,
                hits_allowed=7,
                home_runs_allowed=1,
                walks_allowed=2,
                strikeouts_recorded=10,
                created_at=created_at,
            ),
            repository.TeamStatisticsRecord(
                team_id=20,
                is_home=False,
                runs=3,
                pitching_outs=27,
                runs_allowed=5,
                earned_runs_allowed=4,
                hits_allowed=9,
                home_runs_allowed=2,
                walks_allowed=4,
                strikeouts_recorded=8,
                created_at=created_at,
            ),
        ),
        pitching_statistics=(
            repository.PitchingStatisticsRecord(
                team_id=10,
                appearance_order=1,
                is_starter=True,
                pitching_outs=27,
                hits_allowed=7,
                runs_allowed=3,
                earned_runs_allowed=3,
                home_runs_allowed=1,
                walks_allowed=2,
                strikeouts=10,
                created_at=created_at,
            ),
            repository.PitchingStatisticsRecord(
                team_id=20,
                appearance_order=1,
                is_starter=True,
                pitching_outs=27,
                hits_allowed=9,
                runs_allowed=5,
                earned_runs_allowed=4,
                home_runs_allowed=2,
                walks_allowed=4,
                strikeouts=8,
                created_at=created_at,
            ),
        ),
    )


def test_complete_event_passes() -> None:
    assert repository.validate_mlb_game_completeness(
        (_complete_snapshot(),),
        as_of=NOW,
    ) == ()


def test_missing_interior_result_is_detected() -> None:
    snapshot = replace(_complete_snapshot(), results=())

    assert repository.validate_mlb_game_completeness(
        (snapshot,),
        as_of=NOW,
    ) == (
        "gamePk 800001: historical result coverage is missing or conflicting",
    )


def test_missing_team_statistics_are_detected() -> None:
    complete = _complete_snapshot()
    snapshot = replace(
        complete,
        team_statistics=complete.team_statistics[:1],
    )

    assert any(
        "team-stat coverage is incomplete"
        in issue
        for issue in repository.validate_mlb_game_completeness(
            (snapshot,),
            as_of=NOW,
        )
    )


def test_missing_pitching_statistics_are_detected() -> None:
    complete = _complete_snapshot()
    snapshot = replace(
        complete,
        pitching_statistics=complete.pitching_statistics[:1],
    )

    assert any(
        "pitching-stat coverage is incomplete"
        in issue
        for issue in repository.validate_mlb_game_completeness(
            (snapshot,),
            as_of=NOW,
        )
    )


@pytest.mark.parametrize(
    "pitcher_field",
    (
        "pitching_outs",
        "runs_allowed",
        "hits_allowed",
        "home_runs_allowed",
        "walks_allowed",
        "strikeouts",
    ),
)
def test_other_pitching_aggregate_disagreement_is_detected(
    pitcher_field,
) -> None:
    complete = _complete_snapshot()
    altered_home = replace(
        complete.pitching_statistics[0],
        **{
            pitcher_field: (
                getattr(complete.pitching_statistics[0], pitcher_field)
                + 1
            ),
        },
    )
    snapshot = replace(
        complete,
        pitching_statistics=(
            altered_home,
            complete.pitching_statistics[1],
        ),
    )

    assert any(
        "pitching-stat aggregates disagree"
        in issue
        for issue in repository.validate_mlb_game_completeness(
            (snapshot,),
            as_of=NOW,
        )
    )


@pytest.mark.parametrize("reliever_earned_runs", (3, 4))
def test_rule_9_16i_pitcher_earned_runs_need_not_equal_team_total(
    reliever_earned_runs,
) -> None:
    complete = _complete_snapshot(game_pk=822888, game_id=235)
    home_starter = replace(
        complete.pitching_statistics[0],
        pitching_outs=18,
        hits_allowed=4,
        runs_allowed=1,
        earned_runs_allowed=1,
        walks_allowed=1,
        strikeouts=6,
    )
    home_reliever = replace(
        complete.pitching_statistics[0],
        appearance_order=2,
        is_starter=False,
        pitching_outs=9,
        hits_allowed=3,
        runs_allowed=2,
        earned_runs_allowed=reliever_earned_runs,
        home_runs_allowed=0,
        walks_allowed=1,
        strikeouts=4,
    )
    snapshot = replace(
        complete,
        pitching_statistics=(
            home_starter,
            home_reliever,
            complete.pitching_statistics[1],
        ),
    )

    assert repository.validate_mlb_game_completeness(
        (snapshot,),
        as_of=NOW,
    ) == ()


@pytest.mark.parametrize(
    ("replacement", "expected_issue"),
    (
        (
            {"is_starter": False},
            "pitching-stat coverage is incomplete",
        ),
        (
            {"appearance_order": 2},
            "pitching appearance order is incomplete",
        ),
        (
            {"team_id": 999},
            "pitching-stat coverage is incomplete",
        ),
    ),
)
def test_pitching_structure_corruption_still_fails_closed(
    replacement,
    expected_issue,
) -> None:
    complete = _complete_snapshot()
    corrupted = replace(
        complete.pitching_statistics[0],
        **replacement,
    )
    snapshot = replace(
        complete,
        pitching_statistics=(
            corrupted,
            complete.pitching_statistics[1],
        ),
    )

    assert any(
        expected_issue in issue
        for issue in repository.validate_mlb_game_completeness(
            (snapshot,),
            as_of=NOW,
        )
    )


@pytest.mark.parametrize("mapping_game_ids", [(), (101, 102)])
def test_identity_ambiguity_fails_closed(mapping_game_ids) -> None:
    snapshot = replace(
        _complete_snapshot(),
        mapping_game_ids=mapping_game_ids,
    )

    assert repository.validate_mlb_game_completeness(
        (snapshot,),
        as_of=NOW,
    ) == (
        "gamePk 800001: expected exactly one raw MLB identity mapping",
    )


def test_multiple_mlb_ids_cannot_share_one_canonical_game() -> None:
    first = _complete_snapshot(game_pk=800001, game_id=101)
    second = _complete_snapshot(game_pk=800002, game_id=101)

    issues = repository.validate_mlb_game_completeness(
        (first, second),
        as_of=NOW,
    )

    assert len(issues) == 2
    assert all("mapped by multiple requested MLB IDs" in issue for issue in issues)


def test_conflicting_mlb_source_on_canonical_game_fails_closed() -> None:
    snapshot = replace(
        _complete_snapshot(),
        canonical_mlb_game_pks=("800001", "800099"),
    )

    assert repository.validate_mlb_game_completeness(
        (snapshot,),
        as_of=NOW,
    ) == (
        "gamePk 800001: canonical game has conflicting MLB source mappings",
    )


def test_point_in_time_boundary_excludes_later_statistics() -> None:
    snapshot = _complete_snapshot(
        created_at=NOW + timedelta(seconds=1),
    )

    issues = repository.validate_mlb_game_completeness(
        (snapshot,),
        as_of=NOW,
    )

    assert any("team-stat coverage is incomplete" in issue for issue in issues)
    assert any("pitching-stat coverage is incomplete" in issue for issue in issues)


def test_feature_guard_checks_only_selected_history_window(
    monkeypatch,
) -> None:
    target = replace(
        _complete_snapshot(game_pk=900001, game_id=201),
        results=(),
        team_statistics=(),
        pitching_statistics=(),
    )
    required = (
        _complete_snapshot(game_pk=800001, game_id=101),
        _complete_snapshot(game_pk=800002, game_id=102),
    )
    loads = []
    required_loads = []

    def load(game_pks, **unused):
        loads.append(game_pks)
        return (target,) if game_pks == (900001,) else required

    monkeypatch.setattr(repository, "_load_completeness_snapshots", load)
    monkeypatch.setattr(
        repository,
        "_load_required_feature_game_pks",
        lambda **arguments: (
            required_loads.append(arguments)
            or (800001, 800002)
        ),
    )

    repository.assert_mlb_feature_history_complete(
        target_game_pks=(900001,),
        starting_pitcher_ids=(301, 302),
        cutoff_time=NOW,
        connection_factory=lambda: None,
    )

    assert loads == [(900001,), (800001, 800002)]
    assert required_loads[0]["team_ids"] == (10, 20)
    assert required_loads[0]["starting_pitcher_ids"] == (301, 302)


def test_feature_guard_blocks_interior_gap_despite_complete_newest_game(
    monkeypatch,
) -> None:
    target = replace(
        _complete_snapshot(game_pk=900001, game_id=201),
        results=(),
        team_statistics=(),
        pitching_statistics=(),
    )
    newest = _complete_snapshot(game_pk=800002, game_id=102)
    interior_gap = replace(
        _complete_snapshot(game_pk=800001, game_id=101),
        results=(),
    )

    monkeypatch.setattr(
        repository,
        "_load_completeness_snapshots",
        lambda game_pks, **unused: (
            (target,)
            if game_pks == (900001,)
            else (newest, interior_gap)
        ),
    )
    monkeypatch.setattr(
        repository,
        "_load_required_feature_game_pks",
        lambda **unused: (800002, 800001),
    )

    with pytest.raises(
        repository.MlbCompletenessError,
        match="gamePk 800001.*historical result coverage",
    ):
        repository.assert_mlb_feature_history_complete(
            target_game_pks=(900001,),
            cutoff_time=NOW,
            connection_factory=lambda: None,
        )
