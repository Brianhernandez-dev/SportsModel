from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from sportsmodel.database.connection import get_connection
from sportsmodel.database.moneyline_live_dashboard_repository import (
    list_moneyline_live_slates,
)


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class DashboardStartupProbeResult:
    slate_count: int
    latest_prediction_run_id: int
    latest_odds_ingestion_run_id: int
    latest_target_date: str


def probe_dashboard_production_read(
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> DashboardStartupProbeResult:
    """Read the persisted Daily Card slate boundary in a read-only session."""

    def read_only_connection_factory() -> Any:
        connection = connection_factory()
        connection.set_session(
            readonly=True,
            autocommit=False,
        )
        return connection

    slates = list_moneyline_live_slates(
        connection_factory=read_only_connection_factory,
    )

    if not slates:
        raise LookupError(
            "No persisted MLB Moneyline slates were available to the "
            "Dashboard startup identity."
        )

    latest_slate = slates[0]
    return DashboardStartupProbeResult(
        slate_count=len(slates),
        latest_prediction_run_id=latest_slate.prediction_run_id,
        latest_odds_ingestion_run_id=(
            latest_slate.odds_ingestion_run_id
        ),
        latest_target_date=latest_slate.target_date.isoformat(),
    )


def main(arguments: Sequence[str] | None = None) -> int:
    del arguments

    try:
        result = probe_dashboard_production_read()
    except Exception:
        print(
            "Dashboard production read probe: FAILED. The persisted "
            "Daily Card data boundary could not be read."
        )
        return 1

    print(
        "Dashboard production read probe: READY. "
        f"Persisted slates={result.slate_count}; "
        f"latest prediction run={result.latest_prediction_run_id}; "
        f"latest odds run={result.latest_odds_ingestion_run_id}; "
        f"latest target date={result.latest_target_date}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
