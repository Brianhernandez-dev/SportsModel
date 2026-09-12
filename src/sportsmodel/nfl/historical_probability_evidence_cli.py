"""CLI for a future read-only NFL historical probability evidence export."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import subprocess
from typing import Sequence

from sportsmodel.database.connection import get_connection
from sportsmodel.database.nfl_historical_probability_evidence_repository import (
    load_historical_evidence_input,
)
from sportsmodel.nfl.historical_probability_evidence import (
    build_historical_evidence,
    evidence_package_documents,
    record_deterministic_rerun_pass,
    reconcile_optional_2025_holdout,
    write_historical_evidence_package,
)
from sportsmodel.nfl.moneyline_frozen import fingerprint_payload


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export leakage-safe NFL historical probability evidence from one "
            "read-only repeatable PostgreSQL snapshot."
        )
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--reconcile-2025-holdout",
        type=Path,
        help=(
            "Optional ignored holdout report; SHA-256 and all 236 mature "
            "non-tie probabilities are verified but outcome fields are not copied."
        ),
    )
    parser.add_argument(
        "--allow-repository-output",
        action="store_true",
        help="Explicitly allow the otherwise-refused output location in this repository.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    connection_factory=get_connection,
) -> int:
    arguments = build_parser().parse_args(argv)
    _preflight_output_path(
        arguments.output_dir,
        allow_repository_output=arguments.allow_repository_output,
    )

    connection = connection_factory()
    try:
        connection.set_session(isolation_level="REPEATABLE READ", readonly=True)
        with connection.cursor() as cursor:
            source = load_historical_evidence_input(
                cursor,
                repository_revision=_repository_revision(),
            )
        connection.rollback()
    finally:
        connection.close()

    first = build_historical_evidence(source)
    second = build_historical_evidence(source)
    if arguments.reconcile_2025_holdout is not None:
        first = replace(
            first,
            holdout_reconciliation=reconcile_optional_2025_holdout(
                first, arguments.reconcile_2025_holdout
            ),
        )
        second = replace(
            second,
            holdout_reconciliation=reconcile_optional_2025_holdout(
                second, arguments.reconcile_2025_holdout
            ),
        )
    first_documents = evidence_package_documents(first)
    second_documents = evidence_package_documents(second)
    first_sha = fingerprint_payload({
        path: content.decode("utf-8")
        for path, content in sorted(first_documents.items())
    })
    second_sha = fingerprint_payload({
        path: content.decode("utf-8")
        for path, content in sorted(second_documents.items())
    })
    if first_sha != second_sha:
        raise RuntimeError("identical pinned input did not produce identical package content")
    bundle = record_deterministic_rerun_pass(
        first,
        first_render_sha256=first_sha,
        second_render_sha256=second_sha,
    )
    manifest = write_historical_evidence_package(
        bundle,
        arguments.output_dir,
        repository_root=REPOSITORY_ROOT,
        allow_repository_output=arguments.allow_repository_output,
    )
    print("NFL HISTORICAL PROBABILITY EVIDENCE EXPORT COMPLETE")
    print("Database snapshot: READ ONLY / REPEATABLE READ")
    print(f"Canonical probability rows: {len(bundle.probabilities)}")
    print(f"Manifest SHA-256: {manifest['manifest_payload_sha256']}")
    print(f"Output directory: {arguments.output_dir.resolve()}")
    return 0


def _preflight_output_path(
    output_directory: Path,
    *,
    allow_repository_output: bool,
) -> None:
    output = output_directory.resolve()
    repository = REPOSITORY_ROOT.resolve()
    if (output == repository or repository in output.parents) and not allow_repository_output:
        raise ValueError("refusing historical evidence output inside the repository")
    if output.exists() and any(output.iterdir()):
        raise ValueError("historical evidence output directory must be empty")


def _repository_revision() -> str:
    """Resolve the exact repository revision recorded in package metadata."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError("unable to resolve repository revision") from error
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
