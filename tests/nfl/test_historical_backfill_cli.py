import csv
import hashlib
from io import StringIO
import json
from pathlib import Path
import socket
import urllib.request

import pytest

from sportsmodel.nfl.historical_backfill_cli import (
    APPROVED_SCHEDULE_ROWS,
    HistoricalBackfillInputError,
    build_historical_backfill_report,
    deterministic_json,
    main,
    prepare_historical_backfill,
)


RETRIEVED_AT = "2026-08-14T12:00:00Z"


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames=None) -> bytes:
    if fieldnames is None:
        fieldnames = list(rows[0])
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    content = ("\ufeff" + stream.getvalue()).encode("utf-8")
    path.write_bytes(content)
    return content


def _schedule(**changes):
    row = {
        "game_id": "2023_01_DAL_PHI", "season": 2023,
        "game_type": "REG", "week": 1, "gameday": "2023-09-10",
        "gametime": "13:00", "away_team": "DAL", "away_score": 17,
        "home_team": "PHI", "home_score": 24, "location": "Home",
        "overtime": 0,
    }
    row.update(changes)
    return row


def _stat(team="DAL", opponent="PHI", **changes):
    row = {
        "game_id": "2023_01_DAL_PHI", "season": 2023,
        "season_type": "REG", "week": 1, "team": team,
        "opponent_team": opponent, "completions": 20, "attempts": 30,
        "passing_yards": 200, "passing_tds": 2,
        "passing_interceptions": 1, "sacks_suffered": 2, "carries": 25,
        "rushing_yards": 100, "rushing_tds": 1,
        "fumbles_lost_total": 0, "penalties": 5, "penalty_yards": 40,
    }
    row.update(changes)
    return row


def _team(abbreviation, identity, name):
    return {
        "team_id": identity, "team_abbr": abbreviation,
        "team_name": name, "team_nick": name,
        "team_conf": "NFC", "team_division": "NFC East",
    }


def _assets(tmp_path, *, season_from=2023, season_to=2023, stats=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    schedules = tmp_path / "schedules.csv"
    teams = tmp_path / "teams.csv"
    stats_dir = tmp_path / "stats"
    stats_dir.mkdir()
    _write_csv(schedules, [_schedule()])
    _write_csv(teams, [_team("DAL", "dal", "Dallas"), _team("PHI", "phi", "Philadelphia")])
    stat_rows = stats if stats is not None else [_stat(), _stat("PHI", "DAL")]
    for season in range(season_from, season_to + 1):
        rows = stat_rows if season == 2023 else []
        fields = list(_stat())
        _write_csv(stats_dir / f"stats_team_week_{season}.csv", rows, fields)
    return schedules, teams, stats_dir


def _args(assets, *extra, retrieved_at=RETRIEVED_AT):
    schedules, teams, stats_dir = assets
    return [
        "--schedules", str(schedules), "--teams", str(teams),
        "--team-stats-dir", str(stats_dir), "--retrieved-at", retrieved_at,
        "--season-from", "2023", "--season-to", "2023", *extra,
    ]


def test_valid_local_assets_exit_zero_and_are_ready(tmp_path, capsys):
    exit_code = main(_args(_assets(tmp_path)))
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "NFL Historical Backfill Dry Run" in output
    assert "BACKFILL READY: YES" in output


def test_json_output_is_generated(tmp_path):
    assets = _assets(tmp_path)
    output = tmp_path / "report.json"
    assert main(_args(assets, "--json-output", str(output))) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["backfill_ready"] is True
    assert output.read_text(encoding="utf-8").endswith("\n")


def test_provenance_hash_size_and_row_count_use_actual_file(tmp_path):
    assets = _assets(tmp_path)
    content = assets[0].read_bytes()
    report = build_historical_backfill_report(
        schedules_path=assets[0], teams_path=assets[1],
        team_stats_dir=assets[2], retrieved_at=RETRIEVED_AT,
        season_from=2023, season_to=2023,
    )
    schedule_asset = report["provenance"][0]
    assert schedule_asset["sha256"] == hashlib.sha256(content).hexdigest()
    assert schedule_asset["byte_size"] == len(content)
    assert schedule_asset["row_count"] == 1
    assert schedule_asset["retrieved_at"] == RETRIEVED_AT


def test_annual_stats_provenance_is_in_deterministic_season_order(tmp_path):
    assets = _assets(tmp_path, season_from=2021, season_to=2023)
    report = build_historical_backfill_report(
        schedules_path=assets[0], teams_path=assets[1],
        team_stats_dir=assets[2], retrieved_at=RETRIEVED_AT,
        season_from=2021, season_to=2023,
    )
    assert [item["season"] for item in report["provenance"][2:]] == [2021, 2022, 2023]


def test_matching_physical_annual_season_prepares_successfully(tmp_path):
    assets = _assets(tmp_path)
    prepared = prepare_historical_backfill(
        schedules_path=assets[0], teams_path=assets[1],
        team_stats_dir=assets[2], retrieved_at=RETRIEVED_AT,
        season_from=2023, season_to=2023,
    )
    assert prepared.report["backfill_ready"] is True


def test_cross_year_row_in_annual_asset_fails_explicitly(tmp_path):
    assets = _assets(tmp_path, season_from=2019, season_to=2020)
    wrong_path = assets[2] / "stats_team_week_2019.csv"
    _write_csv(wrong_path, [_stat(season=2020)], list(_stat()))
    with pytest.raises(HistoricalBackfillInputError) as raised:
        prepare_historical_backfill(
            schedules_path=assets[0], teams_path=assets[1],
            team_stats_dir=assets[2], retrieved_at=RETRIEVED_AT,
            season_from=2019, season_to=2020,
        )
    message = str(raised.value)
    assert str(wrong_path) in message
    assert "expected season 2019" in message
    assert "observed '2020'" in message


def test_missing_required_annual_stats_file_is_explicit(tmp_path, capsys):
    assets = _assets(tmp_path)
    (assets[2] / "stats_team_week_2023.csv").unlink()
    assert main(_args(assets)) == 2
    assert "Missing required team-statistics asset for 2023" in capsys.readouterr().err


def test_malformed_teams_asset_is_explicit(tmp_path, capsys):
    assets = _assets(tmp_path)
    _write_csv(assets[1], [{"team_id": "dal", "team_abbr": "DAL"}])
    assert main(_args(assets)) == 2
    assert "Invalid teams asset" in capsys.readouterr().err


def test_planner_blocking_issue_returns_nonzero(tmp_path, capsys):
    assets = _assets(tmp_path, stats=[_stat()])
    assert main(_args(assets)) == 1
    assert "BACKFILL READY: NO" in capsys.readouterr().out


def test_issue_categories_and_counts_are_in_report(tmp_path):
    assets = _assets(tmp_path, stats=[_stat()])
    report = build_historical_backfill_report(
        schedules_path=assets[0], teams_path=assets[1],
        team_stats_dir=assets[2], retrieved_at=RETRIEVED_AT,
        season_from=2023, season_to=2023,
    )
    reconciliation = report["reconciliation"]
    assert reconciliation["issue_count"] == 1
    assert reconciliation["issue_counts_by_category"] == {"one_team_statistics_row": 1}
    assert reconciliation["issues"][0]["external_game_id"] == "2023_01_DAL_PHI"
    assert report["team_statistics"]["rejected_rows"] == 0
    assert "rejected_or_blocking_rows" not in report["team_statistics"]


def test_default_range_contract_gates_readiness_and_exit_code(tmp_path, capsys):
    assets = _assets(tmp_path, season_from=2018, season_to=2025)
    report = build_historical_backfill_report(
        schedules_path=assets[0], teams_path=assets[1],
        team_stats_dir=assets[2], retrieved_at=RETRIEVED_AT,
    )
    contract = report["approved_schedule_contract"]
    assert contract["expected_schedule_rows"] == APPROVED_SCHEDULE_ROWS
    assert contract["expected_unique_historical_schedule_identities"] == APPROVED_SCHEDULE_ROWS
    assert contract["selected_schedule_rows_match"] is False
    assert contract["contract_satisfied"] is False
    assert report["backfill_ready"] is False
    default_args = [
        "--schedules", str(assets[0]), "--teams", str(assets[1]),
        "--team-stats-dir", str(assets[2]),
        "--retrieved-at", RETRIEVED_AT,
    ]
    assert main(default_args) == 1
    assert "BACKFILL READY: NO" in capsys.readouterr().out


def test_smaller_range_does_not_enforce_default_contract(tmp_path):
    assets = _assets(tmp_path)
    report = build_historical_backfill_report(
        schedules_path=assets[0], teams_path=assets[1],
        team_stats_dir=assets[2], retrieved_at=RETRIEVED_AT,
        season_from=2023, season_to=2023,
    )
    assert report["approved_schedule_contract"] is None
    assert report["backfill_ready"] is True
    assert main(_args(assets)) == 0


def test_timezone_naive_retrieved_at_is_input_error(tmp_path, capsys):
    assets = _assets(tmp_path)
    assert main(_args(
        assets, retrieved_at="2026-08-15T05:36:29"
    )) == 2
    assert "must include an explicit timezone" in capsys.readouterr().err


def test_timezone_aware_retrieved_at_accepts_utc_and_offset(tmp_path):
    for index, retrieved_at in enumerate((
        "2026-08-15T05:36:29Z",
        "2026-08-14T22:36:29-07:00",
    )):
        assets = _assets(tmp_path / str(index))
        assert main(_args(assets, retrieved_at=retrieved_at)) == 0


def test_report_json_is_deterministic(tmp_path):
    assets = _assets(tmp_path)
    kwargs = dict(
        schedules_path=assets[0], teams_path=assets[1],
        team_stats_dir=assets[2], retrieved_at=RETRIEVED_AT,
        season_from=2023, season_to=2023,
    )
    assert deterministic_json(build_historical_backfill_report(**kwargs)) == deterministic_json(
        build_historical_backfill_report(**kwargs)
    )


def test_dry_run_does_not_use_database_or_network(tmp_path, monkeypatch):
    assets = _assets(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("database/network access is forbidden")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    assert main(_args(assets)) == 0
