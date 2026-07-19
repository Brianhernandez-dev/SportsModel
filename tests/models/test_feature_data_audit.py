import pytest

from sportsmodel.models.feature_data_audit import (
    FeatureDataAuditCheck,
    FeatureDataAuditReport,
)


def test_audit_check_stores_result() -> None:
    check = FeatureDataAuditCheck(
        name="Historical game results",
        available=True,
        detail="527 completed games exist.",
        row_count=527,
    )

    assert check.name == "Historical game results"
    assert check.available is True
    assert check.row_count == 527


@pytest.mark.parametrize(
    "name",
    [
        "",
        " ",
    ],
)
def test_audit_check_rejects_empty_name(
    name: str,
) -> None:
    with pytest.raises(ValueError):
        FeatureDataAuditCheck(
            name=name,
            available=False,
            detail="Missing.",
        )


def test_audit_check_rejects_negative_row_count() -> None:
    with pytest.raises(ValueError):
        FeatureDataAuditCheck(
            name="Test",
            available=False,
            detail="Missing.",
            row_count=-1,
        )


def test_audit_report_counts_results() -> None:
    report = FeatureDataAuditReport(
        checks=(
            FeatureDataAuditCheck(
                name="Available",
                available=True,
                detail="Available.",
            ),
            FeatureDataAuditCheck(
                name="Missing",
                available=False,
                detail="Missing.",
            ),
        ),
    )

    assert report.available_count == 1
    assert report.missing_count == 1


def test_audit_report_requires_all_training_inputs() -> None:
    required_names = (
        "Historical game results",
        "Canonical game timestamps",
        "Canonical team linkage",
        "Team game batting statistics",
        "Team game pitching statistics",
        "Player game pitching statistics",
        "Historical starting pitchers",
        "Bullpen appearance identification",
    )

    report = FeatureDataAuditReport(
        checks=tuple(
            FeatureDataAuditCheck(
                name=name,
                available=True,
                detail="Available.",
            )
            for name in required_names
        ),
    )

    assert report.is_training_data_ready is True


def test_audit_report_detects_missing_training_input() -> None:
    report = FeatureDataAuditReport(
        checks=(
            FeatureDataAuditCheck(
                name="Historical game results",
                available=True,
                detail="Available.",
            ),
        ),
    )

    assert report.is_training_data_ready is False
