import pytest

from sportsmodel.nfl.team_identity import (
    NflConference,
    NflDivision,
    NflTeamProfile,
    NflTeamSeason,
    NflTeamSource,
)


FRANCHISE_KEY = (
    "nfl_franchise_115e5e7f-0cb9-4961-a6a2-4baa5ca5c26f"
)


def test_constructs_immutable_team_identity_records() -> None:
    profile = NflTeamProfile(101, FRANCHISE_KEY, "ARI", True)
    season = NflTeamSeason(
        101,
        2026,
        "Arizona Cardinals",
        "ARI",
        NflConference.NFC,
        NflDivision.WEST,
    )
    source = NflTeamSource(
        1,
        101,
        "nflverse",
        "3800",
        "Arizona Cardinals",
    )

    assert profile.franchise_key == FRANCHISE_KEY
    assert season.conference == NflConference.NFC
    assert source.external_team_id == "3800"

    with pytest.raises(AttributeError):
        profile.current_abbreviation = "AZ"


@pytest.mark.parametrize(
    "franchise_key",
    (
        "ARI",
        "nfl_franchise_3800",
        "nfl_franchise_115E5E7F-0CB9-4961-A6A2-4BAA5CA5C26F",
    ),
)
def test_rejects_noncanonical_franchise_keys(franchise_key) -> None:
    with pytest.raises(ValueError, match="lowercase UUID"):
        NflTeamProfile(101, franchise_key, "ARI", True)


def test_seasonal_name_can_change_without_changing_franchise() -> None:
    oakland = NflTeamSeason(
        101,
        2019,
        "Oakland Raiders",
        "OAK",
        NflConference.AFC,
        NflDivision.WEST,
    )
    las_vegas = NflTeamSeason(
        101,
        2026,
        "Las Vegas Raiders",
        "LV",
        NflConference.AFC,
        NflDivision.WEST,
    )

    assert oakland.team_id == las_vegas.team_id
    assert oakland.display_name != las_vegas.display_name


def test_rejects_invalid_team_identity_values() -> None:
    with pytest.raises(ValueError, match="positive"):
        NflTeamSource(1, 0, "nflverse", "2520")

    with pytest.raises(ValueError, match="abbreviation"):
        NflTeamProfile(1, FRANCHISE_KEY, "ari", True)

    with pytest.raises(ValueError, match="season"):
        NflTeamSeason(
            1,
            1900,
            "Arizona Cardinals",
            "ARI",
            NflConference.NFC,
            NflDivision.WEST,
        )
