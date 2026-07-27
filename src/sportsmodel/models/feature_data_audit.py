from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureDataAuditCheck:
    """
    Result of one feature-data readiness check.
    """

    name: str

    available: bool

    detail: str

    row_count: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError(
                "Audit check name cannot be empty."
            )

        if not self.detail.strip():
            raise ValueError(
                "Audit check detail cannot be empty."
            )

        if self.row_count is not None and self.row_count < 0:
            raise ValueError(
                "Audit check row count cannot be negative."
            )


@dataclass(frozen=True)
class FeatureDataAuditReport:
    """
    Complete database-readiness report for feature engineering.
    """

    checks: tuple[FeatureDataAuditCheck, ...]

    @property
    def available_count(self) -> int:
        return sum(
            1
            for check in self.checks
            if check.available
        )

    @property
    def missing_count(self) -> int:
        return sum(
            1
            for check in self.checks
            if not check.available
        )

    @property
    def is_training_data_ready(self) -> bool:
        required_names = {
            "Historical game results",
            "Canonical game timestamps",
            "Canonical team linkage",
            "Team game batting statistics",
            "Team game pitching statistics",
            "Player game pitching statistics",
            "Historical starting pitchers",
            "Bullpen appearance identification",
        }

        required_checks = tuple(
            check
            for check in self.checks
            if check.name in required_names
        )

        return (
            len(required_checks) == len(required_names)
            and all(
                check.available
                for check in required_checks
            )
        )
