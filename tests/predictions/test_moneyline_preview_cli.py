from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from sportsmodel.predictions import moneyline_cli
from sportsmodel.predictions import moneyline_preview_cli as preview_cli
from sportsmodel.predictions.moneyline_service import (
    DEFAULT_MODEL_DIRECTORY,
)


def _result(*, target_date: date) -> SimpleNamespace:
    return SimpleNamespace(
        moneyline_prediction_run_id=44,
        target_date=target_date,
        prediction_time=datetime(
            2026,
            8,
            13,
            18,
            45,
            tzinfo=timezone.utc,
        ),
        model_version="mlb_moneyline_v1",
        feature_schema_version="1.2.0",
        games_received=0,
        predictions_created=0,
        games_skipped=0,
        predictions=(),
    )


def test_preview_uses_explicit_date_current_model_and_preview_type(
    monkeypatch,
) -> None:
    calls = []
    target_date = date(2026, 8, 14)
    monkeypatch.setattr(
        preview_cli,
        "run_moneyline_predictions",
        lambda **arguments: calls.append(arguments)
        or _result(target_date=target_date),
    )

    exit_code = preview_cli.main(
        ["--target-date", target_date.isoformat()]
    )

    assert exit_code == 0
    assert calls == [
        {
            "target_date": target_date,
            "model_directory": DEFAULT_MODEL_DIRECTORY,
            "run_type": "preview",
        }
    ]


def test_preview_allows_explicit_model_directory(monkeypatch) -> None:
    calls = []
    target_date = date(2026, 8, 14)
    model_directory = Path("approved-model")
    monkeypatch.setattr(
        preview_cli,
        "run_moneyline_predictions",
        lambda **arguments: calls.append(arguments)
        or _result(target_date=target_date),
    )

    assert preview_cli.main(
        [
            "--target-date",
            target_date.isoformat(),
            "--model-directory",
            str(model_directory),
        ]
    ) == 0
    assert calls[0]["model_directory"] == model_directory


def test_preview_failure_returns_nonzero(monkeypatch, capsys) -> None:
    def fail(**arguments):
        raise RuntimeError("prediction failed")

    monkeypatch.setattr(
        preview_cli,
        "run_moneyline_predictions",
        fail,
    )

    assert preview_cli.main(["--target-date", "2026-08-14"]) == 1
    assert "prediction failed" in capsys.readouterr().out


def test_official_cli_does_not_opt_into_preview(monkeypatch) -> None:
    calls = []
    target_date = date(2026, 8, 14)
    monkeypatch.setattr(
        moneyline_cli,
        "run_moneyline_predictions",
        lambda **arguments: calls.append(arguments)
        or _result(target_date=target_date),
    )

    assert moneyline_cli.main(
        ["--target-date", target_date.isoformat()]
    ) == 0
    assert calls == [
        {
            "target_date": target_date,
            "model_directory": DEFAULT_MODEL_DIRECTORY,
        }
    ]
