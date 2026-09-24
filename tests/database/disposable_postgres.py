"""Fail-closed identity checks for disposable PostgreSQL test targets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import os
import re
import socket
from typing import Any, Mapping

import psycopg2
from psycopg2.extensions import parse_dsn


TEST_DATABASE_URL = "SPORTSMODEL_TEST_DATABASE_URL"
DESTRUCTIVE_ACKNOWLEDGEMENT = "SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB"
DISPOSABLE_MARKER = "SPORTSMODEL_TEST_DATABASE_MARKER"
DISPOSABLE_INSTANCE_ID = "SPORTSMODEL_TEST_DATABASE_INSTANCE_ID"
PRODUCTION_SYSTEM_IDENTIFIER = "SPORTSMODEL_PRODUCTION_DATABASE_SYSTEM_IDENTIFIER"

_DATABASE_NAME = re.compile(r"sportsmodel_test_[0-9a-f]{12,32}")
_INSTANCE_ID = re.compile(r"[0-9a-f]{64}")
_MARKER = re.compile(r"[A-Za-z0-9_-]{32,128}")
_MARKER_QUERY = """
    SELECT marker, instance_id, system_identifier
    FROM sportsmodel_test_guard.instance_identity
    ORDER BY marker
"""
_SERVER_QUERY = """
    SELECT
        current_database(),
        current_user,
        inet_server_addr()::text,
        inet_server_port(),
        current_setting('server_version_num')::integer,
        pg_is_in_recovery(),
        system_identifier::text
    FROM pg_control_system()
"""


class DisposableDatabaseSafetyError(RuntimeError):
    """Raised before destructive work when disposable identity is unproven."""


@dataclass(frozen=True)
class DisposableDatabaseConfiguration:
    database_url: str
    host: str
    resolved_addresses: tuple[str, ...]
    port: int
    database: str
    user: str
    marker: str
    instance_id: str
    production_system_identifier: str

    @property
    def marker_sha256(self) -> str:
        return hashlib.sha256(self.marker.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DisposableServerIdentity:
    database: str
    user: str
    server_address: str
    server_port: int
    server_version_number: int
    system_identifier: str
    instance_id: str
    marker_sha256: str


@dataclass(frozen=True)
class VerifiedDisposableDatabase:
    configuration: DisposableDatabaseConfiguration
    identity: DisposableServerIdentity
    connection: Any


def require_disposable_database_configuration(
    environment: Mapping[str, str] | None = None,
) -> DisposableDatabaseConfiguration:
    """Resolve only explicit test configuration; never load application defaults."""

    values = os.environ if environment is None else environment
    database_url = values.get(TEST_DATABASE_URL, "").strip()
    if not database_url:
        raise DisposableDatabaseSafetyError(
            f"{TEST_DATABASE_URL} is required; application DB fallback is forbidden"
        )
    if values.get(DESTRUCTIVE_ACKNOWLEDGEMENT) != "1":
        raise DisposableDatabaseSafetyError(
            f"{DESTRUCTIVE_ACKNOWLEDGEMENT}=1 is required"
        )

    marker = values.get(DISPOSABLE_MARKER, "").strip()
    if not _MARKER.fullmatch(marker):
        raise DisposableDatabaseSafetyError(
            f"{DISPOSABLE_MARKER} must be an explicit 32-128 character token"
        )
    instance_id = values.get(DISPOSABLE_INSTANCE_ID, "").strip()
    if not _INSTANCE_ID.fullmatch(instance_id):
        raise DisposableDatabaseSafetyError(
            f"{DISPOSABLE_INSTANCE_ID} must be the full Docker container ID"
        )
    production_system_identifier = values.get(
        PRODUCTION_SYSTEM_IDENTIFIER,
        "",
    ).strip()
    if not production_system_identifier.isdecimal():
        raise DisposableDatabaseSafetyError(
            f"{PRODUCTION_SYSTEM_IDENTIFIER} is required for production separation"
        )

    try:
        parameters = parse_dsn(database_url)
    except Exception as error:
        raise DisposableDatabaseSafetyError(
            f"{TEST_DATABASE_URL} is malformed"
        ) from error

    host = parameters.get("host", "").strip().lower()
    port_text = parameters.get("port", "").strip()
    database = parameters.get("dbname", "").strip()
    user = parameters.get("user", "").strip()
    if not host or not port_text or not database or not user:
        raise DisposableDatabaseSafetyError(
            "test URL must explicitly contain one host, port, database, and user"
        )
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise DisposableDatabaseSafetyError(
            "test database host must be an explicit loopback endpoint"
        )
    if "," in host or "," in port_text:
        raise DisposableDatabaseSafetyError("test URL must identify one endpoint")
    if parameters.get("hostaddr") or parameters.get("service"):
        raise DisposableDatabaseSafetyError(
            "alternate PostgreSQL routing parameters are forbidden"
        )
    try:
        port = int(port_text)
    except ValueError as error:
        raise DisposableDatabaseSafetyError("test URL port is invalid") from error
    if port == 5432:
        raise DisposableDatabaseSafetyError(
            "port 5432 is reserved for native SportsModel production"
        )
    if not 1 <= port <= 65535:
        raise DisposableDatabaseSafetyError("test URL port is out of range")
    if database.casefold() == "sportsmodel":
        raise DisposableDatabaseSafetyError(
            "production database name sportsmodel is forbidden"
        )
    if not _DATABASE_NAME.fullmatch(database):
        raise DisposableDatabaseSafetyError(
            "test database must use generated sportsmodel_test_<hex> identity"
        )
    if user != "sportsmodel_test":
        raise DisposableDatabaseSafetyError(
            "disposable database user must be sportsmodel_test"
        )

    addresses = _resolve_loopback_addresses(host, port)
    configuration = DisposableDatabaseConfiguration(
        database_url=database_url,
        host=host,
        resolved_addresses=addresses,
        port=port,
        database=database,
        user=user,
        marker=marker,
        instance_id=instance_id,
        production_system_identifier=production_system_identifier,
    )
    _reject_application_target_overlap(configuration, values)
    return configuration


def open_verified_disposable_database(
    environment: Mapping[str, str] | None = None,
) -> VerifiedDisposableDatabase:
    """Connect after config checks, then positively verify the server identity."""

    configuration = require_disposable_database_configuration(environment)
    connection = psycopg2.connect(configuration.database_url)
    try:
        identity = verify_disposable_database_connection(
            connection,
            configuration,
        )
    except BaseException:
        connection.close()
        raise
    _log_verified_identity(configuration, identity)
    return VerifiedDisposableDatabase(configuration, identity, connection)


def verify_disposable_database_connection(
    connection: Any,
    configuration: DisposableDatabaseConfiguration,
) -> DisposableServerIdentity:
    """Require independent in-server proof before destructive SQL is possible."""

    try:
        with connection.cursor() as cursor:
            cursor.execute(_SERVER_QUERY)
            server_rows = cursor.fetchall()
            cursor.execute(_MARKER_QUERY)
            marker_rows = cursor.fetchall()
    except Exception as error:
        raise DisposableDatabaseSafetyError(
            "disposable server identity/marker could not be verified"
        ) from error

    if len(server_rows) != 1:
        raise DisposableDatabaseSafetyError("unexpected PostgreSQL server identity")
    (
        database,
        user,
        server_address,
        server_port,
        server_version_number,
        in_recovery,
        system_identifier,
    ) = server_rows[0]
    if database != configuration.database or user != configuration.user:
        raise DisposableDatabaseSafetyError(
            "connected PostgreSQL database/user identity mismatch"
        )
    if in_recovery or int(server_version_number) < 140000:
        raise DisposableDatabaseSafetyError("unexpected PostgreSQL server identity")
    if str(system_identifier) == configuration.production_system_identifier:
        raise DisposableDatabaseSafetyError(
            "connected server has the production PostgreSQL system identity"
        )
    if len(marker_rows) != 1:
        raise DisposableDatabaseSafetyError(
            "exactly one disposable instance marker is required"
        )
    marker, instance_id, marker_system_identifier = marker_rows[0]
    if marker != configuration.marker:
        raise DisposableDatabaseSafetyError("disposable marker mismatch")
    if instance_id != configuration.instance_id:
        raise DisposableDatabaseSafetyError("Docker container identity mismatch")
    if str(marker_system_identifier) != str(system_identifier):
        raise DisposableDatabaseSafetyError("PostgreSQL system identity mismatch")

    return DisposableServerIdentity(
        database=str(database),
        user=str(user),
        server_address=str(server_address),
        server_port=int(server_port),
        server_version_number=int(server_version_number),
        system_identifier=str(system_identifier),
        instance_id=str(instance_id),
        marker_sha256=configuration.marker_sha256,
    )


def _resolve_loopback_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise DisposableDatabaseSafetyError("test database host is unresolvable") from error
    addresses = tuple(sorted({row[4][0] for row in rows}))
    if not addresses or any(
        not ipaddress.ip_address(address).is_loopback for address in addresses
    ):
        raise DisposableDatabaseSafetyError(
            "test database host must resolve only to loopback addresses"
        )
    return addresses


def _reject_application_target_overlap(
    configuration: DisposableDatabaseConfiguration,
    environment: Mapping[str, str],
) -> None:
    application_url = environment.get("DATABASE_URL", "").strip()
    if application_url:
        try:
            application = parse_dsn(application_url)
        except Exception as error:
            raise DisposableDatabaseSafetyError(
                "application DATABASE_URL is malformed; separation is ambiguous"
            ) from error
        if _same_endpoint(configuration, application):
            raise DisposableDatabaseSafetyError(
                "test target overlaps application DATABASE_URL"
            )

    application_values = {
        name: environment.get(name, "").strip()
        for name in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB")
    }
    populated = [value for value in application_values.values() if value]
    if populated and len(populated) != len(application_values):
        raise DisposableDatabaseSafetyError(
            "application POSTGRES_* identity is partial; separation is ambiguous"
        )
    if populated:
        application = {
            "host": application_values["POSTGRES_HOST"],
            "port": application_values["POSTGRES_PORT"],
            "dbname": application_values["POSTGRES_DB"],
        }
        if _same_endpoint(configuration, application):
            raise DisposableDatabaseSafetyError(
                "test target overlaps application POSTGRES_* identity"
            )


def _same_endpoint(
    configuration: DisposableDatabaseConfiguration,
    other: Mapping[str, str],
) -> bool:
    try:
        other_port = int(other.get("port", ""))
    except (TypeError, ValueError):
        return False
    if (
        other_port != configuration.port
        or other.get("dbname", "").casefold() != configuration.database.casefold()
    ):
        return False
    other_host = other.get("host", "").strip().lower()
    if not other_host or "," in other_host:
        return False
    try:
        other_addresses = set(_resolve_loopback_addresses(other_host, other_port))
    except DisposableDatabaseSafetyError:
        return other_host == configuration.host
    return bool(other_addresses.intersection(configuration.resolved_addresses))


def _log_verified_identity(
    configuration: DisposableDatabaseConfiguration,
    identity: DisposableServerIdentity,
) -> None:
    print(
        "verified disposable PostgreSQL target: "
        f"host={configuration.host} port={configuration.port} "
        f"database={identity.database} user={identity.user} "
        f"server_address={identity.server_address} "
        f"server_port={identity.server_port} "
        f"system_identifier={identity.system_identifier} "
        f"container_id={identity.instance_id} "
        f"marker_sha256={identity.marker_sha256}"
    )
