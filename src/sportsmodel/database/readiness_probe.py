from __future__ import annotations

import argparse
from dataclasses import dataclass
import ipaddress
import os
from typing import Any, Callable, Mapping, Sequence

import psycopg2

from sportsmodel.database.connection import get_connection


READY_EXIT_CODE = 0
TRANSIENT_EXIT_CODE = 10
PERMANENT_EXIT_CODE = 20

_TRANSIENT_SQLSTATES = {
    "57P03",  # cannot_connect_now
}
_TRANSIENT_MESSAGE_MARKERS = (
    "connection refused",
    "connection reset",
    "connection timed out",
    "could not connect to server",
    "network is unreachable",
    "server closed the connection unexpectedly",
    "timeout expired",
)


@dataclass(frozen=True)
class DatabaseReadinessProbeResult:
    exit_code: int
    message: str


def is_loopback_host(host: str) -> bool:
    normalized_host = host.strip().lower()
    if normalized_host == "localhost":
        return True

    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        return False

    return address in {
        ipaddress.ip_address("127.0.0.1"),
        ipaddress.ip_address("::1"),
    }


def is_transient_connection_error(error: BaseException) -> bool:
    sqlstate = getattr(error, "pgcode", None)
    if sqlstate is None:
        diagnostic = getattr(error, "diag", None)
        sqlstate = getattr(diagnostic, "sqlstate", None)

    if sqlstate is not None:
        return (
            str(sqlstate).startswith("08")
            or sqlstate in _TRANSIENT_SQLSTATES
        )

    message = str(error).lower()
    return any(
        marker in message
        for marker in _TRANSIENT_MESSAGE_MARKERS
    )


def check_database_readiness(
    *,
    expected_port: int = 5432,
    expected_database: str = "sportsmodel",
    environment: Mapping[str, str] = os.environ,
    connection_factory: Callable[[], Any] = get_connection,
) -> DatabaseReadinessProbeResult:
    configured_host = environment.get("POSTGRES_HOST", "")
    if not is_loopback_host(configured_host):
        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message="Configured PostgreSQL host is not a loopback endpoint.",
        )

    try:
        configured_port = int(environment.get("POSTGRES_PORT", ""))
    except ValueError:
        configured_port = -1

    if configured_port != expected_port:
        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message=(
                "Configured PostgreSQL port does not match the expected "
                f"production port {expected_port}."
            ),
        )

    if environment.get("POSTGRES_DB") != expected_database:
        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message=(
                "Configured PostgreSQL database does not match the "
                f"expected production database {expected_database}."
            ),
        )

    try:
        connection = connection_factory()
    except psycopg2.OperationalError as error:
        if is_transient_connection_error(error):
            return DatabaseReadinessProbeResult(
                exit_code=TRANSIENT_EXIT_CODE,
                message="Native PostgreSQL is temporarily unavailable.",
            )

        error_text = str(error).lower()
        if (
            "authentication failed" in error_text
            or "no pg_hba.conf entry" in error_text
        ):
            message = (
                "PostgreSQL authentication or client access configuration "
                "was rejected."
            )
        elif "database" in error_text and "does not exist" in error_text:
            message = "The configured PostgreSQL database does not exist."
        else:
            message = (
                "PostgreSQL rejected the connection with a non-transient "
                "configuration or authentication error."
            )

        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message=message,
        )
    except Exception:
        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message=(
                "The PostgreSQL connection probe failed with a "
                "non-transient configuration error."
            ),
        )

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_database(),
                    inet_server_port(),
                    pg_is_in_recovery(),
                    current_setting('transaction_read_only'),
                    current_setting('default_transaction_read_only');
                """
            )
            row = cursor.fetchone()
    except psycopg2.OperationalError as error:
        if is_transient_connection_error(error):
            return DatabaseReadinessProbeResult(
                exit_code=TRANSIENT_EXIT_CODE,
                message=(
                    "PostgreSQL became temporarily unavailable during "
                    "the readiness query."
                ),
            )

        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message=(
                "PostgreSQL connected but rejected the readiness query "
                "with a non-transient error."
            ),
        )
    except Exception:
        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message="PostgreSQL connected but the readiness query failed.",
        )
    finally:
        connection.close()

    if row is None or len(row) != 5:
        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message="PostgreSQL returned an invalid readiness response.",
        )

    (
        actual_database,
        actual_port,
        is_in_recovery,
        transaction_read_only,
        default_transaction_read_only,
    ) = row

    if actual_database != expected_database:
        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message="Connected database identity is not the production database.",
        )

    if actual_port != expected_port:
        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message="Connected PostgreSQL port is not the production port.",
        )

    if is_in_recovery:
        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message="Connected PostgreSQL is a recovery replica.",
        )

    if str(transaction_read_only).lower() != "off":
        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message="Connected PostgreSQL transaction state is read-only.",
        )

    if str(default_transaction_read_only).lower() != "off":
        return DatabaseReadinessProbeResult(
            exit_code=PERMANENT_EXIT_CODE,
            message="Connected PostgreSQL server default is read-only.",
        )

    return DatabaseReadinessProbeResult(
        exit_code=READY_EXIT_CODE,
        message="Native PostgreSQL production primary is ready.",
    )


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the SportsModel production PostgreSQL primary."
    )
    parser.add_argument("--expected-port", type=int, default=5432)
    parser.add_argument(
        "--expected-database",
        default="sportsmodel",
    )
    parsed_arguments = parser.parse_args(arguments)
    result = check_database_readiness(
        expected_port=parsed_arguments.expected_port,
        expected_database=parsed_arguments.expected_database,
    )
    print(result.message)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
