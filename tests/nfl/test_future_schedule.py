import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pytest

from sportsmodel.nfl.future_schedule import build_future_schedule_plan
from sportsmodel.nfl import future_schedule_cli as cli


ROOT = Path(__file__).parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "nflverse" / "phase_1_source_rows.json"


class _Cursor:
    def __init__(self, known_ids=("3200", "4600")) -> None:
        self.known_ids = known_ids
        self.rows = []

    def execute(self, sql, _params=()):
        if "SELECT external_team_id" in sql:
            self.rows = [(value,) for value in self.known_ids]
        else:
            self.rows = []

    def fetchall(self):
        return self.rows


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _row(**changes):
    result = dict(_fixture()["schedule_cases"][-1]["row"])
    result.update(changes)
    return result


def test_clean_future_regular_schedule_is_proposed_as_new_and_aware() -> None:
    source = _fixture()
    plan = build_future_schedule_plan(
        _Cursor(),
        schedule_rows=[_row()],
        team_rows=source["teams"],
        season=2026,
    )

    assert plan.ready
    assert plan.count("new") == 1
    assert plan.count("update") == plan.count("existing") == 0
    assert plan.earliest_kickoff.tzinfo is not None
    assert plan.earliest_kickoff.astimezone(timezone.utc) == datetime(
        2026, 9, 10, 0, 20, tzinfo=timezone.utc
    )


def test_preseason_is_reported_but_excluded_from_a5b_regular_import() -> None:
    source = _fixture()
    plan = build_future_schedule_plan(
        _Cursor(),
        schedule_rows=[_row(), _row(game_id="2026_00_NE_SEA", game_type="PRE")],
        team_rows=source["teams"],
        season=2026,
    )

    assert plan.ready
    assert plan.source_game_type_counts == (("PRE", 1), ("REG", 1))
    assert plan.excluded_non_regular_rows == 1
    assert len(plan.candidates) == 1


@pytest.mark.parametrize(
    "rows,category",
    [
        ([_row(), _row()], "duplicate_or_missing_source_id"),
        ([_row(home_score="1", away_score="0", overtime="0")], "not_future_unplayed"),
        ([_row(gametime="")], "invalid_kickoff"),
        ([_row(home_team="UNKNOWN")], "unknown_team"),
    ],
)
def test_future_schedule_failures_are_explicit(rows, category) -> None:
    source = _fixture()
    plan = build_future_schedule_plan(
        _Cursor(),
        schedule_rows=rows,
        team_rows=source["teams"],
        season=2026,
    )

    assert not plan.ready
    assert category in {issue.category for issue in plan.issues}


def test_confirmed_cli_requires_pinned_hashes_before_connection(tmp_path) -> None:
    source = _fixture()
    schedules = tmp_path / "schedules.csv"
    teams = tmp_path / "teams.csv"
    _write_csv(schedules, [_row()])
    _write_csv(teams, source["teams"])
    calls = []

    result = cli.main(
        [
            "--schedules", str(schedules),
            "--teams", str(teams),
            "--retrieved-at", "2026-08-22T17:08:36Z",
            "--season", "2026",
            "--confirm-persist",
        ],
        connection_factory=lambda: calls.append(True),
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert result == cli.INPUT_ERROR
    assert calls == []


def _write_csv(path, rows):
    import csv

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
