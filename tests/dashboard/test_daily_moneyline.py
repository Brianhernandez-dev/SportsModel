from datetime import date, datetime, timezone

from sportsmodel.dashboard.views import daily_moneyline
from sportsmodel.models.moneyline_live_dashboard import (
    MoneylineLiveSlate,
)


TARGET_DATE = date(2026, 8, 12)
STARTED_AT = datetime(2026, 8, 12, 15, tzinfo=timezone.utc)


def _slate(
    *,
    prediction_run_id: int,
    snapshot_role: str,
    run_type: str,
) -> MoneylineLiveSlate:
    return MoneylineLiveSlate(
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=200 + prediction_run_id,
        policy_version="1.0.0",
        target_date=TARGET_DATE,
        snapshot_role=snapshot_role,
        snapshot_started_at=STARTED_AT,
        run_type=run_type,
    )


def test_official_card_does_not_select_newer_preview(monkeypatch) -> None:
    official = _slate(
        prediction_run_id=44,
        snapshot_role="entry",
        run_type="official",
    )
    newer_preview = _slate(
        prediction_run_id=45,
        snapshot_role="late_night",
        run_type="preview",
    )
    monkeypatch.setattr(
        daily_moneyline,
        "_load_slates",
        lambda: (newer_preview, official),
    )

    assert daily_moneyline._find_latest_slate(
        target_date=TARGET_DATE,
    ) == official


def test_results_include_only_official_entry_slates() -> None:
    official = _slate(
        prediction_run_id=44,
        snapshot_role="entry",
        run_type="official",
    )
    preview = _slate(
        prediction_run_id=45,
        snapshot_role="late_night",
        run_type="preview",
    )

    assert daily_moneyline._latest_slate_per_date(
        (preview, official),
    ) == (official,)
