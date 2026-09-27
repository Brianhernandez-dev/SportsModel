from pathlib import Path
import re


ROOT = Path(__file__).parents[2]

EFFECTIVE_IDENTITY_READERS = (
    "src/sportsmodel/analysis/market.py",
    "src/sportsmodel/analysis/moneyline_market_evaluation_service.py",
    "src/sportsmodel/analysis/moneyline_movement_service.py",
    "src/sportsmodel/analysis/moneyline_preview_dashboard_service.py",
    "src/sportsmodel/auditing/moneyline_live_pipeline.py",
    "src/sportsmodel/database/feature_data_audit.py",
    "src/sportsmodel/database/repository.py",
)

RAW_PROVENANCE_READERS = (
    "src/sportsmodel/nfl/official_pregame_evidence.py",
    "scripts/invoke_native_postgresql_backup_restore_acceptance.ps1",
)

UNAFFECTED_DIRECT_READERS = (
    "src/sportsmodel/database/control_center_repository.py",
    "src/sportsmodel/database/moneyline_dashboard_status_repository.py",
)


def _normalized(path: str) -> str:
    return " ".join((ROOT / path).read_text(encoding="utf-8-sig").split())


def test_every_canonical_identity_reader_uses_the_central_effective_view() -> None:
    for path in EFFECTIVE_IDENTITY_READERS:
        source = _normalized(path)
        assert "odds_market_snapshots_effective" in source, path


def test_direct_base_table_reader_inventory_is_exhaustive() -> None:
    direct_reader = re.compile(r"\b(?:from|join)\s+odds_market_snapshots\b", re.I)
    found: set[str] = set()

    for directory in (ROOT / "src", ROOT / "scripts"):
        for path in directory.rglob("*"):
            if path.suffix.lower() not in {".py", ".ps1"}:
                continue
            if direct_reader.search(_normalized(path.relative_to(ROOT).as_posix())):
                found.add(path.relative_to(ROOT).as_posix())

    assert found == set(RAW_PROVENANCE_READERS + UNAFFECTED_DIRECT_READERS)


def test_raw_provenance_and_integrity_readers_keep_the_base_table() -> None:
    for path in RAW_PROVENANCE_READERS:
        source = _normalized(path)
        assert "odds_market_snapshots" in source, path
        assert "odds_market_snapshots_effective" not in source, path


def test_market_snapshot_exposes_raw_identity_separately() -> None:
    source = _normalized("src/sportsmodel/models/snapshot.py")
    assert "game_id: int" in source
    assert "raw_acquisition_game_id: int | None = None" in source
