"""Explicit offline-evidence operator CLI, not a scheduled/live provider runner."""
import argparse
from datetime import date
import getpass
from pathlib import Path
import warnings

from sportsmodel.database.mlb_operator_guard import (
    OperatorRefusal, OperatorTarget, aware, canonical_json, strict_json,
)


def _write_output(path, report):
    # Evidence cannot write into either source checkout, production or .env.
    resolved = path.resolve()
    roots = (Path(__file__).resolve().parents[3], Path(r"D:\SportsModel"))
    if any(resolved == root or root in resolved.parents for root in roots) or resolved.name == ".env":
        raise OperatorRefusal("Operator evidence must be outside source/production checkout")
    if path.exists() or not path.parent.is_dir():
        raise OperatorRefusal("Exclusive output in existing evidence directory required")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(report) + "\n")


def main(argv=None, *, connector=None, password_reader=None):
    # Existing repositories import the ambient connection module. This standalone
    # operator invocation disables its env discovery; every actual connection is
    # instead explicit/authenticated/guarded. Restore the caller's loader on exit.
    import dotenv
    original = dotenv.load_dotenv
    try:
        dotenv.load_dotenv = lambda *args, **kwargs: False
        return _main(argv, connector=connector, password_reader=password_reader)
    finally:
        dotenv.load_dotenv = original


def _main(argv=None, *, connector=None, password_reader=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("history", "preview", "execute"))
    parser.add_argument("--target", type=Path, required=True, help="Pinned non-secret endpoint/epoch/schema guard JSON")
    parser.add_argument("--db-user", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--acknowledge-db-read", action="store_true", required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--game-ids", type=int, nargs="+")
    parser.add_argument("--starter-ids", type=int, nargs="+")
    parser.add_argument("--cutoff", type=aware)
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--allowlist", type=Path)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--approved-preview-sha256")
    parser.add_argument("--acknowledge-writes", action="store_true")
    args = parser.parse_args(argv)
    try:
        target = OperatorTarget.from_dict(strict_json(args.target.read_bytes()))
        if args.output.exists() or not args.output.parent.is_dir():
            raise OperatorRefusal("Output precheck failed")
        # Apply protected-path precheck BEFORE credential prompt, connection or mutation.
        resolved = args.output.resolve()
        for root in (Path(__file__).resolve().parents[3], Path(r"D:\SportsModel")):
            if resolved == root or root in resolved.parents or resolved.name == ".env":
                raise OperatorRefusal("Protected evidence output path")
        if args.mode == "history":
            if not args.game_ids or not args.starter_ids or args.cutoff is None:
                raise OperatorRefusal("History requires date, canonical targets, starters and cutoff")
        else:
            from sportsmodel.operations.mlb_reconcile import validate_inputs
            if args.payload is None or args.allowlist is None:
                raise OperatorRefusal("Pinned payload and exact allowlist required")
            payload, allowlist = args.payload.read_bytes(), args.allowlist.read_bytes()
            day, _ = validate_inputs(payload, allowlist)
            if day != args.date:
                raise OperatorRefusal("CLI date differs from pinned allowlist")
            if args.mode == "execute" and (args.preview is None or not args.approved_preview_sha256 or not args.acknowledge_writes):
                raise OperatorRefusal("Exact preview approval and separate writes acknowledgement required")
        if connector is None:
            import psycopg2
            connector = psycopg2.connect
        if password_reader is None:
            password_reader = getpass.getpass
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = password_reader("Database password (not retained): ")
        if not isinstance(password, str) or not password:
            raise OperatorRefusal("Secure explicit database authentication required")
        def factory():
            return connector(host=target.host, port=target.port, dbname=target.database,
                             user=args.db_user, password=password, connect_timeout=10,
                             options="-c default_transaction_read_only=on -c statement_timeout=60000 -c lock_timeout=5000 -c search_path=public")
        try:
            if args.mode == "history":
                from sportsmodel.operations.mlb_history_check import check_feature_history
                report = check_feature_history(target_date=args.date, target_game_ids=args.game_ids,
                    starting_pitcher_ids=args.starter_ids, cutoff_time=args.cutoff, target=target, connection_factory=factory)
            else:
                from sportsmodel.operations.mlb_reconcile import preview_reconciliation, execute_reconciliation
                if args.mode == "preview":
                    report = preview_reconciliation(payload_bytes=payload, allowlist_bytes=allowlist,
                                                    target=target, connection_factory=factory)
                else:
                    report = execute_reconciliation(payload_bytes=payload, allowlist_bytes=allowlist,
                        preview=strict_json(args.preview.read_bytes()), approved_preview_sha256=args.approved_preview_sha256,
                        acknowledge_writes=args.acknowledge_writes, target=target, connection_factory=factory)
        finally:
            password = None  # Python string zeroization is not guaranteed.
        print(canonical_json(report))
        _write_output(args.output, report)
        return 1 if report.get("status") == "FAIL" else 0
    except OperatorRefusal as error:
        print(canonical_json({"status": "FAIL", "reason": str(error)}))
        return 1
    except Exception as error:
        # DB/parser errors may carry connection strings: retain only safe class.
        print(canonical_json({"status": "FAIL", "error_type": type(error).__name__}))
        return 1
