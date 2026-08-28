import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import sportsmodel.nfl.manual_market_evaluation as manual_module
import sportsmodel.nfl.manual_market_evaluation_cli as cli_module
from sportsmodel.nfl.manual_market_evaluation import (
    ManualMarketEvaluationGuardError,
    ManualMarketEvaluationResult,
    execute_manual_market_evaluation,
)
from sportsmodel.nfl.market_evaluation import (
    OfficialMarketEvaluationConflictError,
    OfficialMarketEvaluationError,
    OfficialMarketEvaluationPreview,
    OfficialMarketEvaluationProviderDisplay,
)


NOW = datetime(2099, 9, 10, 19, 45, tzinfo=timezone.utc)


def _preview() -> OfficialMarketEvaluationPreview:
    provider = OfficialMarketEvaluationProviderDisplay(
        provider_identity_id=70,
        provider_name="odds_api",
        provider_bookmaker_key="book_a",
        sportsbook_name="Book A",
    )
    return OfficialMarketEvaluationPreview(
        prediction_id=10,
        prediction_run_id=20,
        prediction_protocol_version="nfl_moneyline_forward_0.1.0",
        prediction_protocol_fingerprint="a" * 64,
        selected_route="mature",
        routing_contract_version="nfl_moneyline_routing_0.1.0",
        model_specification_version="nfl_moneyline_mature_0.1.0",
        feature_schema_version="nfl_moneyline_features_0.1.0",
        game_id=30,
        home_team_id=40,
        home_team_name="Kansas City Chiefs",
        home_team_abbreviation="KC",
        away_team_id=50,
        away_team_name="Denver Broncos",
        away_team_abbreviation="DEN",
        selected_team_id=40,
        selected_team_name="Kansas City Chiefs",
        selected_team_abbreviation="KC",
        selected_side="home",
        selected_model_probability=Decimal("0.6000000000000000"),
        prediction_created_at=NOW - timedelta(minutes=10),
        odds_ingestion_run_id=60,
        request_started_at=NOW - timedelta(seconds=1),
        response_received_at=NOW,
        prediction_to_receipt_seconds=Decimal("600"),
        kickoff=NOW + timedelta(minutes=15),
        contributor_count=5,
        exclusions=(),
        consensus_no_vig_selected_probability=Decimal("0.5100000000000000"),
        best_price_provider=provider,
        best_price_evidence_id=80,
        best_american_price=110,
        best_decimal_odds=Decimal("2.1000000000000000"),
        market_edge=Decimal("0.0900000000000000"),
        model_expected_value=Decimal("0.2600000000000000"),
        source_graph_fingerprint="b" * 64,
        market_evaluation_protocol_version=(
            "nfl_moneyline_market_evaluation_0.1.0"
        ),
        market_evaluation_protocol_fingerprint="c" * 64,
        existing_evaluation_id=None,
    )


def test_default_cli_is_read_only_and_reports_eligible_preview(
    monkeypatch,
    capsys,
) -> None:
    captured = {}

    def execute(**kwargs):
        captured.update(kwargs)
        return ManualMarketEvaluationResult(_preview(), None)

    monkeypatch.setattr(cli_module, "execute_manual_market_evaluation", execute)
    exit_code = cli_module.main([
        "--prediction-id", "10", "--odds-run-id", "60",
    ])
    assert exit_code == cli_module.EXIT_DRY_RUN_ELIGIBLE
    assert captured == {
        "prediction_id": 10,
        "odds_ingestion_run_id": 60,
        "live": False,
        "confirm_create_evaluation": False,
    }
    output = capsys.readouterr().out
    assert "MODE: DRY RUN - READ ONLY" in output
    assert "ELIGIBILITY: PASS" in output
    assert "Database writes: ZERO" in output
    assert "Provider calls: ZERO" in output
    assert "CREATE ONE NEW IMMUTABLE EVALUATION" in output


@pytest.mark.parametrize(
    ("live", "confirmed"),
    [(True, False), (False, True)],
)
def test_manual_service_requires_both_live_guards_before_database_access(
    monkeypatch,
    live,
    confirmed,
) -> None:
    monkeypatch.setattr(
        manual_module,
        "preview_official_nfl_moneyline_market",
        lambda **unused: pytest.fail("guard failure opened the database"),
    )
    with pytest.raises(ManualMarketEvaluationGuardError):
        execute_manual_market_evaluation(
            prediction_id=10,
            odds_ingestion_run_id=60,
            live=live,
            confirm_create_evaluation=confirmed,
        )


def test_cli_rejects_authoritative_values_other_than_identifiers() -> None:
    with pytest.raises(SystemExit) as captured:
        cli_module.main([
            "--prediction-id", "10",
            "--odds-run-id", "60",
            "--model-probability", "0.99",
        ])
    assert captured.value.code == cli_module.EXIT_INVALID_OPERATOR_ARGUMENTS


@pytest.mark.parametrize(
    ("error", "expected_exit"),
    [
        (
            OfficialMarketEvaluationError(
                "prediction_ineligible", "preview prediction rejected"
            ),
            cli_module.EXIT_PROTOCOL_INELIGIBLE,
        ),
        (
            OfficialMarketEvaluationError(
                "insufficient_coverage", "only four complete books"
            ),
            cli_module.EXIT_INSUFFICIENT_MARKET_COVERAGE,
        ),
        (
            OfficialMarketEvaluationError(
                "schema_incompatible", "migration 031 missing"
            ),
            cli_module.EXIT_DATABASE_OR_INFRASTRUCTURE_FAILURE,
        ),
        (
            OfficialMarketEvaluationConflictError(
                "source_graph_conflict", "different immutable graph"
            ),
            cli_module.EXIT_SOURCE_GRAPH_CONFLICT,
        ),
    ],
)
def test_cli_error_exit_contract(monkeypatch, capsys, error, expected_exit) -> None:
    def fail(**unused):
        raise error

    monkeypatch.setattr(cli_module, "execute_manual_market_evaluation", fail)
    exit_code = cli_module.main([
        "--prediction-id", "10", "--odds-run-id", "60",
    ])
    assert exit_code == expected_exit
    output = capsys.readouterr().out
    assert "ELIGIBILITY: FAIL" in output
    assert f"Failure code: {error.code}" in output
    assert "Provider calls: ZERO" in output
    assert "Database writes: ZERO" in output


def test_unexpected_failure_does_not_print_secret_values(
    monkeypatch,
    capsys,
) -> None:
    secret = "postgresql://user:password@example.invalid/database"

    def fail(**unused):
        raise RuntimeError(secret)

    monkeypatch.setattr(cli_module, "execute_manual_market_evaluation", fail)
    exit_code = cli_module.main([
        "--prediction-id", "10", "--odds-run-id", "60",
    ])
    assert exit_code == cli_module.EXIT_DATABASE_OR_INFRASTRUCTURE_FAILURE
    output = capsys.readouterr().out
    assert secret not in output
    assert "RuntimeError" in output


def test_manual_evaluation_modules_have_no_provider_or_http_imports() -> None:
    root = Path(__file__).parents[2]
    modules = (
        root / "src" / "sportsmodel" / "nfl" / "manual_market_evaluation.py",
        root / "src" / "sportsmodel" / "nfl" / "manual_market_evaluation_cli.py",
        root / "src" / "sportsmodel" / "nfl" / "market_evaluation.py",
    )
    forbidden = {
        "requests",
        "httpx",
        "urllib",
        "sportsmodel.nfl.manual_odds_capture",
        "sportsmodel.ingest.odds_api",
    }
    imported = set()
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert imported.isdisjoint(forbidden)
