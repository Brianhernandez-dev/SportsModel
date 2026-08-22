"""Operator CLI for one guarded manual NFL H2H capture."""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
from typing import Any

import psycopg2

from sportsmodel.database.connection import get_connection
from sportsmodel.nfl.manual_odds_capture import (
    MARKETS,
    NFL_SPORT_KEY,
    ODDS_FORMAT,
    REGIONS,
    NflCaptureAudit,
    NflProviderResponse,
    call_odds_api_once,
    execute_manual_nfl_capture,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one manual NFL Odds API H2H capture. The default is a "
            "no-network, no-write dry run."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--mock-fixture",
        type=Path,
        help="Persist one mocked response only to the explicitly guarded test DB.",
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help="Explicitly opt in to one billable live provider request.",
    )
    parser.add_argument(
        "--confirm-one-request",
        action="store_true",
        help="Required with --live; confirms exactly one intentional request attempt.",
    )
    parser.add_argument(
        "--target-date",
        type=date.fromisoformat,
        help="Required for mock/live modes; UTC calendar date of NFL kickoffs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if not arguments.live and arguments.mock_fixture is None:
        print("DRY RUN - no database writes and no provider request")
        print(f"Sport: {NFL_SPORT_KEY}")
        print(f"Market: {MARKETS}")
        print(f"Regions: {REGIONS}")
        print(f"Odds format: {ODDS_FORMAT}")
        print("Use --mock-fixture for disposable rehearsal persistence.")
        print("Live mode additionally requires --live --confirm-one-request.")
        return 0

    if arguments.target_date is None:
        parser.error("--target-date is required for mock and live modes")

    connection = None
    try:
        if arguments.mock_fixture is not None:
            connection = _mock_connection()
            response = _load_mock_response(arguments.mock_fixture)
            provider_call = lambda _request: response
            mode_name = "MOCK"
        else:
            if not arguments.confirm_one_request:
                parser.error("--live requires --confirm-one-request")
            api_key = os.getenv("ODDS_API_KEY")
            if not api_key:
                parser.error("--live requires ODDS_API_KEY")
            connection = get_connection()
            provider_call = lambda request: call_odds_api_once(
                request,
                api_key=api_key,
            )
            mode_name = "LIVE - ONE REQUEST ATTEMPT"

        audit = execute_manual_nfl_capture(
            connection,
            target_date=arguments.target_date,
            provider_call=provider_call,
        )
    except Exception as error:
        print(
            "NFL H2H capture failed: "
            f"{type(error).__name__}: {error}"
        )
        return 1
    finally:
        if connection is not None:
            connection.close()

    _print_audit(mode_name, audit)
    return 0


def _mock_connection() -> Any:
    database_url = os.getenv("SPORTSMODEL_TEST_DATABASE_URL")
    if not database_url:
        raise RuntimeError("mock mode requires SPORTSMODEL_TEST_DATABASE_URL")
    if os.getenv("SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB") != "1":
        raise RuntimeError(
            "mock mode requires SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB=1"
        )
    if database_url == os.getenv("DATABASE_URL"):
        raise RuntimeError("mock database URL must differ from DATABASE_URL")
    return psycopg2.connect(database_url)


def _load_mock_response(path: Path) -> NflProviderResponse:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(fixture, dict):
        raise ValueError("mock response fixture must be a JSON object")
    body = fixture.get("body")
    headers = fixture.get("headers")
    status_code = fixture.get("status_code")
    if not isinstance(status_code, int):
        raise ValueError("mock response status_code must be an integer")
    if not isinstance(headers, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in headers.items()
    ):
        raise ValueError("mock response headers must be a text mapping")
    return NflProviderResponse(
        status_code=status_code,
        headers=headers,
        body=json.dumps(body),
    )


def _print_audit(mode_name: str, audit: NflCaptureAudit) -> None:
    print("=" * 72)
    print(f"SportsModel NFL H2H Capture - {mode_name}")
    print("=" * 72)
    print(f"Ingestion run ID: {audit.odds_ingestion_run_id}")
    print(f"Target UTC date: {audit.target_date}")
    print(f"HTTP status: {audit.status_code}")
    print(f"Requests remaining: {audit.remaining_requests}")
    print(f"Requests used: {audit.used_requests}")
    print(f"Games returned/processed: {audit.games_returned}/{audit.games_processed}")
    print(f"Event observations: {audit.provider_event_observation_ids}")
    print(f"Event mappings: {audit.provider_event_mapping_ids}")
    print(f"Sportsbook identities: {audit.sportsbook_provider_identity_ids}")
    print(f"Raw snapshot IDs: {audit.raw_snapshot_ids}")
    print(f"Official evidence IDs: {audit.official_pregame_evidence_ids}")
    print(f"Official pregame skipped: {audit.official_pregame_skipped}")


if __name__ == "__main__":
    raise SystemExit(main())
