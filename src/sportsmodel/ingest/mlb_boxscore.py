from __future__ import annotations

from typing import Any

import requests


_BASE_URL = "https://statsapi.mlb.com/api/v1"


def fetch_boxscore(game_pk: int) -> dict[str, Any]:
    """
    Fetch the MLB box score for a completed or scheduled game.

    Args:
        game_pk:
            MLB Stats API game identifier.

    Returns:
        Parsed JSON response.

    Raises:
        requests.HTTPError:
            If the request was unsuccessful.
    """

    response = requests.get(
        f"{_BASE_URL}/game/{game_pk}/boxscore",
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def fetch_live_feed(game_pk: int) -> dict[str, Any]:
    """
    Fetch the MLB live feed for a game.

    Args:
        game_pk:
            MLB Stats API game identifier.

    Returns:
        Parsed JSON response.

    Raises:
        requests.HTTPError:
            If the request was unsuccessful.
    """

    response = requests.get(
        f"{_BASE_URL}.1/game/{game_pk}/feed/live",
        timeout=30,
    )

    response.raise_for_status()

    return response.json()