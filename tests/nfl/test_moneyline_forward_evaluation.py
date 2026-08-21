from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
from types import SimpleNamespace
from uuid import UUID

import pytest

import sportsmodel.nfl.moneyline_forward_evaluation as evaluation
import sportsmodel.nfl.moneyline_forward_evaluation_cli as cli
from sportsmodel.database.nfl_moneyline_forward_evaluation_repository import (
    NFLMoneylineForwardEvidence,
)


KICKOFF = datetime(2026, 9, 10, 20, tzinfo=timezone.utc)


class FakeCursor:
    def execute(self, query, parameters=None):
        self.query = query
        self.parameters = parameters

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self):
        self.sessions = []
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor()

    def set_session(self, **values):
        self.sessions.append(values)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_evaluation_is_read_only_official_by_default_and_filters_protocol(
    monkeypatch,
) -> None:
    connection = FakeConnection()
    calls = []
    monkeypatch.setattr(
        evaluation,
        "list_nfl_moneyline_forward_evidence",
        lambda cursor, **values: calls.append(values) or (),
    )

    report = evaluation.evaluate_nfl_moneyline_forward(
        season=2026,
        protocol_version="protocol-v1",
        connection_factory=lambda: connection,
    )

    assert report.run_type == "official"
    assert calls == [{
        "season": 2026,
        "protocol_version": "protocol-v1",
        "run_type": "official",
        "slate_start_time": None,
        "slate_end_time": None,
        "route": None,
    }]
    assert connection.sessions == [{
        "isolation_level": "REPEATABLE READ",
        "readonly": True,
    }]
    assert connection.rollbacks == 1
    assert connection.closed


def test_preview_requires_explicit_filter(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        evaluation,
        "list_nfl_moneyline_forward_evidence",
        lambda cursor, **values: calls.append(values) or (),
    )
    evaluation.evaluate_nfl_moneyline_forward(
        season=2026,
        run_type="preview",
        connection_factory=FakeConnection,
    )
    assert calls[0]["run_type"] == "preview"


def test_metrics_pending_ties_routes_baseline_auc_and_ece() -> None:
    evidence = (
        _evidence(1, route="early", probability="0.8000000000000000",
                  home_score=24, away_score=17, home_prior=0, away_prior=2),
        _evidence(2, route="early", probability="0.3000000000000000",
                  home_score=14, away_score=21, home_prior=1, away_prior=1),
        _evidence(3, route="mature", probability="0.7000000000000000",
                  status="unplayed", home_score=None, away_score=None,
                  home_prior=3, away_prior=4),
        _evidence(4, route="mature", probability="0.6000000000000000",
                  home_score=20, away_score=20, home_prior=4, away_prior=4),
    )

    group = evaluation._evaluate_group("combined", evidence)

    assert (group.total, group.resolved, group.pending, group.ties_excluded) == (
        4, 2, 1, 1
    )
    assert group.model.accuracy == 1.0
    assert group.model.log_loss == pytest.approx(
        -(math.log(0.8) + math.log(0.7)) / 2
    )
    assert group.model.brier_score == pytest.approx(0.065)
    assert group.model.roc_auc == 1.0
    assert group.model.mean_home_win_probability == pytest.approx(0.55)
    assert group.model.actual_home_win_rate == 0.5
    assert group.model.expected_calibration_error == pytest.approx(0.25)
    assert group.baseline.accuracy == 0.5
    assert group.log_loss_difference == pytest.approx(
        group.model.log_loss - group.baseline.log_loss
    )
    assert group.model_confidence_intervals is not None
    assert group.difference_confidence_intervals is not None


def test_auc_is_unavailable_with_one_class_and_empty_groups_are_supported() -> None:
    one_class = evaluation._evaluate_group(
        "one", (_evidence(1, home_score=24, away_score=17),)
    )
    empty = evaluation._evaluate_group("empty", ())

    assert one_class.model.roc_auc is None
    assert empty.model.count == 0
    assert empty.model.accuracy is None


def test_persisted_probability_and_prediction_time_integrity_are_authoritative() -> None:
    item = _evidence(
        1,
        probability="0.1234567890123456",
        home_score=7,
        away_score=21,
    )
    group = evaluation._evaluate_group("persisted", (item,))
    assert group.model.mean_home_win_probability == pytest.approx(
        0.1234567890123456
    )

    with pytest.raises(ValueError, match="strictly before kickoff"):
        evaluation._validate_evidence(replace(
            item,
            prediction_created_at=item.target_kickoff,
        ))


def test_route_and_early_history_breakouts(monkeypatch) -> None:
    rows = (
        _evidence(1, route="early", home_prior=0, away_prior=2),
        _evidence(2, route="early", home_prior=1, away_prior=2),
        _evidence(3, route="mature", home_prior=3, away_prior=3),
    )
    monkeypatch.setattr(
        evaluation,
        "list_nfl_moneyline_forward_evidence",
        lambda *args, **kwargs: rows,
    )

    report = evaluation.evaluate_nfl_moneyline_forward(
        season=2026,
        connection_factory=FakeConnection,
    )

    assert [(item.label, item.total) for item in report.routes] == [
        ("early", 2), ("mature", 1)
    ]
    assert report.route_distribution.total == 3
    assert report.route_distribution.early_count == 2
    assert report.route_distribution.mature_count == 1
    assert report.route_distribution.early_percentage == pytest.approx(200 / 3)
    assert report.route_distribution.mature_percentage == pytest.approx(100 / 3)
    assert [item.total for item in report.early_history_groups] == [1, 1, 0]


def test_forward_season_and_window_validation() -> None:
    with pytest.raises(ValueError, match="2026 or later"):
        evaluation.evaluate_nfl_moneyline_forward(
            season=2025,
            connection_factory=FakeConnection,
        )
    report = evaluation.evaluate_nfl_moneyline_forward(
        season=2026,
        connection_factory=FakeConnection,
    )
    assert report.season == 2026


def test_report_output_is_deterministic_and_labels_preview(monkeypatch) -> None:
    report = SimpleNamespace(
        season=2026,
        protocol_version="protocol-v1",
        run_type="preview",
        route_filter=None,
        slate_start_time=None,
        slate_end_time=None,
        run_keys=("key-1",),
        prediction_set_sha256s=("a" * 64,),
        model_specification_versions=("model-v1",),
        model_fingerprints=("b" * 64,),
        route_distribution=evaluation.NFLForwardRouteDistribution(
            total=3,
            early_count=2,
            mature_count=1,
            early_percentage=200 / 3,
            mature_percentage=100 / 3,
        ),
        overall=evaluation._evaluate_group("combined", ()),
        routes=(),
        early_history_groups=(),
    )
    monkeypatch.setattr(
        cli,
        "evaluate_nfl_moneyline_forward",
        lambda **kwargs: report,
    )

    assert cli.main(["--season", "2026", "--preview"]) == 0
    first = cli.format_nfl_moneyline_forward_report(report)
    second = cli.format_nfl_moneyline_forward_report(report)
    assert first == second
    assert "run_type=preview" in first
    assert "READ ONLY" in first
    assert (
        "routing_distribution total=3 early=2 early_pct=66.666667 "
        "mature=1 mature_pct=33.333333"
    ) in first


def test_empty_route_distribution_uses_na_percentages() -> None:
    distribution = evaluation._route_distribution(())

    assert distribution.total == 0
    assert distribution.early_count == 0
    assert distribution.mature_count == 0
    assert distribution.early_percentage is None
    assert distribution.mature_percentage is None


def _evidence(
    prediction_id: int,
    *,
    route: str = "early",
    probability: str = "0.6000000000000000",
    baseline: str = "0.5500000000000000",
    status: str = "final",
    home_score: int | None = 24,
    away_score: int | None = 17,
    home_prior: int = 0,
    away_prior: int = 0,
) -> NFLMoneylineForwardEvidence:
    return NFLMoneylineForwardEvidence(
        prediction_id=prediction_id,
        prediction_run_id=10,
        run_key=UUID("b8eebca7-44f1-4e64-a821-01876b4db323"),
        run_type="official",
        protocol_version="nfl_moneyline_forward_0.1.0",
        prediction_set_sha256="a" * 64,
        game_id=prediction_id,
        season=2026,
        target_kickoff=KICKOFF,
        prediction_created_at=KICKOFF - timedelta(hours=1),
        home_team_id=1,
        away_team_id=2,
        canonical_kickoff=KICKOFF,
        canonical_home_team_id=1,
        canonical_away_team_id=2,
        game_status=status,
        home_score=home_score,
        away_score=away_score,
        home_prior_games=home_prior,
        away_prior_games=away_prior,
        route=route,
        routing_contract_version="routing-v1",
        model_specification_version=f"{route}-model-v1",
        feature_schema_version=f"{route}-schema-v1",
        specification_fingerprint="b" * 64,
        model_fingerprint="c" * 64,
        home_win_probability=Decimal(probability),
        baseline_home_win_probability=Decimal(baseline),
        classification_threshold=Decimal("0.5000000000000000"),
        predicted_side=("home" if Decimal(probability) >= Decimal("0.5") else "away"),
    )
