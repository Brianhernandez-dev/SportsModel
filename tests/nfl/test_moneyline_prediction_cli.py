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
    assert cli.main([
        "--season", "2026",
        "--slate-start", "2026-09-10T00:00:00Z",
        "--slate-end", "2026-09-11T00:00:00+00:00",
        flag,
        "--run-key", RUN_KEY,
    ]) == 0
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
        "--official", "--dry-run",
    ]) == 0
    assert calls[0]["run_key"] is None
    assert calls[0]["dry_run"] is True
    assert "DRY RUN" in capsys.readouterr().out


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


def _result(*, dry_run):
    return SimpleNamespace(
        dry_run=dry_run,
        run=None,
        predictions=(),
        inference_results=(),
        slate_fingerprint="a" * 64,
        source_snapshot_sha256="b" * 64,
        prediction_set_sha256="c" * 64,
    )
