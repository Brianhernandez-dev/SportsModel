from sportsmodel.nfl.coverage_audit import (
    audit,
    coverage_matrix,
    external_id_integrity,
    validate_rows,
)


TEAMS = [
    {"team_abbr": "OAK", "team_name": "Oakland Raiders", "team_id": "2520"},
    {"team_abbr": "LV", "team_name": "Las Vegas Raiders", "team_id": "2520"},
    {"team_abbr": "KC", "team_name": "Kansas City Chiefs", "team_id": "2310"},
]


def row(**updates):
    value = {
        "game_id": "2019_01_OAK_KC", "season": "2019", "game_type": "REG",
        "week": "1", "gameday": "2019-09-15", "gametime": "13:00",
        "away_team": "OAK", "away_score": "10", "home_team": "KC",
        "home_score": "28", "location": "Home", "overtime": "0",
    }
    value.update(updates)
    return value


def test_coverage_counts_are_derived_from_rows():
    rows = [row(), row(game_id="2019_02_KC_OAK", week="2", away_team="KC", home_team="OAK", away_score="20", home_score="20", overtime="1", location="Neutral")]
    coverage = coverage_matrix(rows)[0]
    assert coverage.total_rows == 2
    assert coverage.tied_games == coverage.overtime_games == 1
    assert coverage.neutral_site_games == 1


def test_validation_groups_partial_scores_and_bad_matchup_by_season():
    findings = validate_rows([row(away_score="", home_team="OAK")], {"OAK", "KC"})
    assert findings["partial_score_state"][2019] == ["2019_01_OAK_KC"]
    assert findings["identical_home_away_team"][2019] == ["2019_01_OAK_KC"]


def test_external_id_integrity_detects_duplicate_conflict():
    rows = [row(), row(home_team="LV")]
    findings = external_id_integrity(rows)
    assert findings["duplicate_ids"] == {"2019_01_OAK_KC": 2}
    assert "2019_01_OAK_KC" in findings["conflicting_id_matchups"]


def test_full_audit_proves_aliases_share_one_canonical_provider_id():
    result = audit([row()], TEAMS, season_from=2019, season_to=2019, canonical_ids={"2520", "2310"})
    assert result["parser"]["succeeded"] == 1
    assert result["teams"]["aliases"]["2520"][0]["abbreviation"] == "LV"
    assert result["teams"]["provider_ids_not_in_canonical_seed"] == []


def test_full_audit_flags_semantically_suspicious_neutral_time():
    suspicious = row(gametime="21:30", location="Neutral")
    result = audit([suspicious], TEAMS, season_from=2019, season_to=2019, canonical_ids={"2520", "2310"})
    assert result["timezone"]["suspicious_neutral_kickoff_ids"] == ["2019_01_OAK_KC"]
