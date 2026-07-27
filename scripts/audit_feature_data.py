from sportsmodel.database.feature_data_audit import (
    audit_feature_data,
)


def main() -> None:
    report = audit_feature_data()

    print("MLB Feature Data Readiness Audit")
    print("=" * 72)

    for check in report.checks:
        status = "AVAILABLE" if check.available else "MISSING"

        row_count_text = ""

        if check.row_count is not None:
            row_count_text = f" | Rows: {check.row_count:,}"

        print(
            f"[{status}] {check.name}{row_count_text}"
        )
        print(f"  {check.detail}")
        print()

    print("=" * 72)
    print(
        f"Available checks: {report.available_count}"
    )
    print(
        f"Missing checks: {report.missing_count}"
    )
    print(
        "Training data ready: "
        f"{'YES' if report.is_training_data_ready else 'NO'}"
    )


if __name__ == "__main__":
    main()
