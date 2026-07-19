from sportsmodel.ingest.mlb_rosters import sync_active_mlb_rosters


def main() -> None:
    summary = sync_active_mlb_rosters()

    print("Active MLB roster synchronization complete.")
    print(f"Teams received: {summary.teams_received}")
    print(f"Teams processed: {summary.teams_processed}")
    print(f"Teams skipped: {summary.teams_skipped}")
    print(
        "Roster entries received: "
        f"{summary.roster_entries_received}"
    )
    print(
        "Unique players discovered: "
        f"{summary.unique_players_discovered}"
    )
    print(
        "Team mappings created: "
        f"{summary.team_mappings_created}"
    )
    print(
        "Assignments created: "
        f"{summary.assignments_created}"
    )
    print(
        "Assignments updated: "
        f"{summary.assignments_updated}"
    )
    print(
        "Assignments transferred: "
        f"{summary.assignments_transferred}"
    )
    print(
        "Assignments skipped: "
        f"{summary.assignments_skipped}"
    )
    print(
        "Players received: "
        f"{summary.player_sync.players_received}"
    )
    print(
        "Players created: "
        f"{summary.player_sync.players_created}"
    )
    print(
        "Players updated: "
        f"{summary.player_sync.players_updated}"
    )
    print(
        "Players skipped: "
        f"{summary.player_sync.players_skipped}"
    )


if __name__ == "__main__":
    main()