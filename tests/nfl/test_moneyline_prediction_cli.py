from types import SimpleNamespace
from uuid import UUID

import pytest

import sportsmodel.nfl.moneyline_prediction_cli as cli
from sportsmodel.nfl.moneyline_prediction import NFLMoneylinePredictionRunType


RUN_KEY = "b8eebca7-44f1-4e64-a821-01876b4db323"


@pytest.mark.parametrize(
    ("flag", "expected_type"),
    [
        ("--official", NFLMoneylinePredictionRunType.OFFICIAL),
        ("--preview", NFLMoneylinePredictionRunType.PREVIEW),
    ],
)
def test_cli_persists_explicit_mode(monkeypatch, capsys, flag, expected_type) -> None:
    calls = []
    monkeypatch.setattr(
        cli,
        "execute_nfl_moneyline_prediction_run",
        lambda **values: calls.append(values) or _result(dry_run=False),
    )
    arguments = [
        "--season", "2026",
        "--slate-start", "2026-09-10T00:00:00Z",
        "--slate-end", "2026-09-11T00:00:00+00:00",
        flag,
        "--run-key", RUN_KEY,
    ]
    if flag == "--official":
        arguments.append("--confirm-official")
    assert cli.main(arguments) == 0
    assert calls[0]["run_type"] is expected_type
    assert calls[0]["run_key"] == UUID(RUN_KEY)
    assert calls[0]["dry_run"] is False
    assert "PERSISTED" in capsys.readouterr().out


def test_cli_dry_run_needs_no_run_key_and_passes_zero_write_mode(
    monkeypatch, capsys,
) -> None:
    calls = []
    monkeypatch.setattr(
        cli,
        "execute_nfl_moneyline_prediction_run",
        lambda **values: calls.append(values) or _result(dry_run=True),
    )
    assert cli.main([
        "--season", "2026",
        "--slate-start", "2026-09-10T00:00:00Z",
        "--slate-end", "2026-09-11T00:00:00Z",
        "--official", "--preflight",
    ]) == 0
    assert calls[0]["run_key"] is None
    assert calls[0]["dry_run"] is True
    output = capsys.readouterr().out
    assert "PREFLIGHT" in output
    assert "route=early" in output
    assert "model=early-model-v1" in output
    assert "away_team=AWAY home_team=HOME" in output
    assert "official_exists=False" in output
    assert "READY FOR OFFICIAL RUN" in output


def test_cli_blocks_existing_official_observation(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "execute_nfl_moneyline_prediction_run",
        lambda **values: _result(
            dry_run=True,
            official_existing_game_ids=(1,),
        ),
    )

    assert cli.main([
        "--season", "2026",
        "--slate-start", "2026-09-10T00:00:00Z",
        "--slate-end", "2026-09-11T00:00:00Z",
        "--official", "--preflight",
    ]) == 2
    output = capsys.readouterr().out
    assert "official observations already exist" in output
    assert output.rstrip().endswith("OFFICIAL RUN BLOCKED")


def test_cli_generates_and_prints_run_key(monkeypatch, capsys) -> None:
    calls = []
    generated = UUID(RUN_KEY)
    monkeypatch.setattr(cli, "uuid4", lambda: generated)
    monkeypatch.setattr(
        cli,
        "execute_nfl_moneyline_prediction_run",
        lambda **values: calls.append(values) or _result(dry_run=False),
    )

    assert cli.main([
        "--season", "2026",
        "--slate-start", "2026-09-10T00:00:00Z",
        "--slate-end", "2026-09-11T00:00:00Z",
        "--preview", "--generate-run-key",
    ]) == 0
    assert calls[0]["run_key"] == generated
    assert f"GENERATED RUN KEY: {generated}" in capsys.readouterr().out


def test_official_write_requires_deliberate_confirmation() -> None:
    with pytest.raises(SystemExit):
        cli.main([
            "--season", "2026",
            "--slate-start", "2026-09-10T00:00:00Z",
            "--slate-end", "2026-09-11T00:00:00Z",
            "--official", "--run-key", RUN_KEY,
        ])


def test_cli_rejects_non_utc_window_and_missing_write_run_key() -> None:
    with pytest.raises(SystemExit):
        cli.main([
            "--season", "2026",
            "--slate-start", "2026-09-10T00:00:00-07:00",
            "--slate-end", "2026-09-11T00:00:00Z",
            "--official", "--dry-run",
        ])
    with pytest.raises(SystemExit):
        cli.main([
            "--season", "2026",
            "--slate-start", "2026-09-10T00:00:00Z",
            "--slate-end", "2026-09-11T00:00:00Z",
            "--preview",
        ])


def _result(*, dry_run, official_existing_game_ids=()):
    inference = SimpleNamespace(
        game_id=1,
        target_kickoff=cli._utc_datetime("2026-09-10T20:00:00Z"),
        away_team_id=2,
        home_team_id=1,
        home_current_prior_games=0,
        away_current_prior_games=1,
        selected_route=SimpleNamespace(value="early"),
        model_specification_version="early-model-v1",
        feature_schema_version="early-schema-v1",
        model_home_win_probability=0.6,
        predicted_side=SimpleNamespace(value="home"),
        feature_vector_fingerprint="d" * 64,
    )
    return SimpleNamespace(
        dry_run=dry_run,
        run=None,
        predictions=(),
        inference_results=(inference,),
        slate_fingerprint="a" * 64,
        source_snapshot_sha256="b" * 64,
        prediction_set_sha256="c" * 64,
        official_existing_game_ids=official_existing_game_ids,
        team_abbreviations=((1, "HOME"), (2, "AWAY")),
    )
