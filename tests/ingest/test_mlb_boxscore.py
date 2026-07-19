from unittest.mock import Mock, patch

from sportsmodel.ingest.mlb_boxscore import (
    fetch_boxscore,
    fetch_live_feed,
)


@patch("sportsmodel.ingest.mlb_boxscore.requests.get")
def test_fetch_boxscore(mock_get: Mock) -> None:
    response = Mock()
    response.json.return_value = {"gamePk": 12345}

    mock_get.return_value = response

    result = fetch_boxscore(12345)

    mock_get.assert_called_once_with(
        "https://statsapi.mlb.com/api/v1/game/12345/boxscore",
        timeout=30,
    )

    response.raise_for_status.assert_called_once()

    assert result == {"gamePk": 12345}


@patch("sportsmodel.ingest.mlb_boxscore.requests.get")
def test_fetch_live_feed(mock_get: Mock) -> None:
    response = Mock()
    response.json.return_value = {"gamePk": 12345}

    mock_get.return_value = response

    result = fetch_live_feed(12345)

    mock_get.assert_called_once_with(
        "https://statsapi.mlb.com/api/v1.1/game/12345/feed/live",
        timeout=30,
    )

    response.raise_for_status.assert_called_once()

    assert result == {"gamePk": 12345}