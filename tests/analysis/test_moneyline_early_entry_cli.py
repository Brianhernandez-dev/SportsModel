from datetime import date
from types import SimpleNamespace

from sportsmodel.analysis import moneyline_early_entry_cli as cli


def test_reports_skipped_market_coverage(monkeypatch, capsys) -> None:
    evaluation_result = SimpleNamespace(
        predictions_loaded=14,
        skipped_missing_market_game_ids=(8284, 8285, 8289),
        evaluations=(),
    )
    capture_result = SimpleNamespace(
        target_date=date(2026, 8, 14),
        prediction_run_id=20,
        odds_ingestion_run_id=222,
        evaluations_saved=11,
        early_entry_candidates=0,
        evaluation_result=evaluation_result,
    )
    monkeypatch.setattr(
        cli,
        "capture_moneyline_early_entry",
        lambda **arguments: capture_result,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "capture_moneyline_early_entry.py",
            "--target-date",
            "2026-08-14",
        ],
    )

    cli.main()

    output = capsys.readouterr().out
    assert "Predictions loaded:   14" in output
    assert "Evaluations saved:     11" in output
    assert "Missing markets skipped: 3" in output
    assert "Skipped game IDs:    8284, 8285, 8289" in output
