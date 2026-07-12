from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from sportsmodel.database.connection import get_connection


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIRECTORY = PROJECT_ROOT / "database" / "migrations"
MIGRATION_FILENAME_PATTERN = re.compile(
    r"^(?P<version>\d{3})_(?P<name>[a-z0-9_]+)\.sql$"
)


@dataclass(frozen=True)
class Migration:
    version: int
    filename: str
    path: Path
    checksum: str
    sql: str


def calculate_checksum(sql: str) -> str:
    """Return a SHA-256 checksum for migration SQL."""

    return sha256(sql.encode("utf-8")).hexdigest()


def discover_migrations(
    migrations_directory: Path = MIGRATIONS_DIRECTORY,
) -> list[Migration]:
    """Discover and validate ordered SQL migration files."""

    if not migrations_directory.exists():
        raise FileNotFoundError(
            f"Migration directory does not exist: {migrations_directory}"
        )

    migrations: list[Migration] = []
    versions_seen: set[int] = set()

    for path in migrations_directory.glob("*.sql"):
        match = MIGRATION_FILENAME_PATTERN.fullmatch(path.name)

        if match is None:
            raise ValueError(
                "Invalid migration filename. Expected format "
                f"'NNN_description.sql': {path.name}"
            )

        version = int(match.group("version"))

        if version in versions_seen:
            raise ValueError(
                f"Duplicate migration version detected: {version:03d}"
            )

        sql = path.read_text(encoding="utf-8-sig")

        migrations.append(
            Migration(
                version=version,
                filename=path.name,
                path=path,
                checksum=calculate_checksum(sql),
                sql=sql,
            )
        )

        versions_seen.add(version)

    migrations.sort(key=lambda migration: migration.version)

    return migrations


def ensure_schema_migrations_table(connection) -> None:
    """Create the migration tracking table when it does not exist."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                filename TEXT NOT NULL UNIQUE,
                checksum CHAR(64) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def get_applied_migrations(connection) -> dict[int, tuple[str, str]]:
    """Return applied migrations keyed by version."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT version, filename, checksum
            FROM schema_migrations
            ORDER BY version
            """
        )

        return {
            version: (filename, checksum)
            for version, filename, checksum in cursor.fetchall()
        }


def validate_applied_migrations(
    migrations: list[Migration],
    applied_migrations: dict[int, tuple[str, str]],
) -> None:
    """Ensure previously applied migration files have not changed."""

    discovered_by_version = {
        migration.version: migration
        for migration in migrations
    }

    for version, (applied_filename, applied_checksum) in applied_migrations.items():
        migration = discovered_by_version.get(version)

        if migration is None:
            raise RuntimeError(
                "An applied migration file is missing from disk: "
                f"{version:03d} ({applied_filename})"
            )

        if migration.filename != applied_filename:
            raise RuntimeError(
                f"Migration {version:03d} filename changed from "
                f"'{applied_filename}' to '{migration.filename}'."
            )

        if migration.checksum != applied_checksum:
            raise RuntimeError(
                f"Migration {version:03d} was changed after being applied: "
                f"{migration.filename}"
            )


def baseline_migrations(
    connection,
    migrations: list[Migration],
    through_version: int,
) -> int:
    """
    Record existing migrations without executing them.

    This is intended only for adopting an existing database whose schema
    changes were applied before migration tracking was introduced.
    """

    available_versions = {
        migration.version
        for migration in migrations
    }

    if through_version not in available_versions:
        raise ValueError(
            f"Baseline target {through_version:03d} does not exist."
        )

    applied_migrations = get_applied_migrations(connection)
    baseline_count = 0

    with connection.cursor() as cursor:
        for migration in migrations:
            if migration.version > through_version:
                break

            if migration.version in applied_migrations:
                continue

            cursor.execute(
                """
                INSERT INTO schema_migrations (
                    version,
                    filename,
                    checksum
                )
                VALUES (%s, %s, %s)
                """,
                (
                    migration.version,
                    migration.filename,
                    migration.checksum,
                ),
            )

            baseline_count += 1
            print(
                f"Baselined {migration.version:03d}: "
                f"{migration.filename}"
            )

    return baseline_count


def apply_pending_migrations(
    connection,
    migrations: list[Migration],
) -> int:
    """Execute each pending migration in its own transaction."""

    applied_migrations = get_applied_migrations(connection)
    applied_count = 0

    for migration in migrations:
        if migration.version in applied_migrations:
            continue

        print(
            f"Applying {migration.version:03d}: "
            f"{migration.filename}"
        )

        try:
            with connection.cursor() as cursor:
                cursor.execute(migration.sql)

                cursor.execute(
                    """
                    INSERT INTO schema_migrations (
                        version,
                        filename,
                        checksum
                    )
                    VALUES (%s, %s, %s)
                    """,
                    (
                        migration.version,
                        migration.filename,
                        migration.checksum,
                    ),
                )

            connection.commit()

        except Exception:
            connection.rollback()
            print(
                f"Migration {migration.version:03d} failed and "
                "was rolled back."
            )
            raise

        applied_count += 1

    return applied_count


def run_migrations(
    baseline_through: int | None = None,
) -> None:
    """Discover, validate, baseline, or apply database migrations."""

    migrations = discover_migrations()

    if not migrations:
        print("No migration files were found.")
        return

    connection = get_connection()

    try:
        ensure_schema_migrations_table(connection)
        connection.commit()

        applied_migrations = get_applied_migrations(connection)

        if applied_migrations:
            validate_applied_migrations(
                migrations,
                applied_migrations,
            )

        if baseline_through is not None:
            baseline_count = baseline_migrations(
                connection,
                migrations,
                baseline_through,
            )
            connection.commit()

            print(
                f"Baseline complete. "
                f"Migrations recorded: {baseline_count}"
            )
            return

        applied_count = apply_pending_migrations(
            connection,
            migrations,
        )

        if applied_count == 0:
            print("Database is current. No pending migrations.")
        else:
            print(
                f"Migration run complete. "
                f"Migrations applied: {applied_count}"
            )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()
