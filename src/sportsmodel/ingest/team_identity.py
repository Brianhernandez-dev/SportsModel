"""
Canonical team-name handling shared by ingestion sources.
"""


_CANONICAL_TEAM_NAMES_BY_ALIAS = {
    "athletics": "Athletics",
    "oakland athletics": "Athletics",
}


def normalize_team_name(team_name: str) -> str:
    """
    Return the canonical name used by the SportsModel database.

    Source APIs can use different display names for the same franchise.
    Normalization prevents those aliases from creating duplicate canonical
    teams.
    """

    normalized_whitespace = " ".join(team_name.split())

    if not normalized_whitespace:
        raise ValueError("team_name cannot be blank.")

    return _CANONICAL_TEAM_NAMES_BY_ALIAS.get(
        normalized_whitespace.casefold(),
        normalized_whitespace,
    )
