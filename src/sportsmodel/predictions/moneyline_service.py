from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import requests

from sportsmodel.database.connection import (
    get_connection,
)
from sportsmodel.database.moneyline_prediction_repository import (
    create_moneyline_prediction_run,
    insert_moneyline_game_prediction,
    mark_moneyline_prediction_run_completed,
    mark_moneyline_prediction_run_failed,
)
from sportsmodel.database.player_repository import (
    get_player_ids_by_source,
)
from sportsmodel.features.datasets.feature_flattener import (
    flatten_game_feature_vector,
)
from sportsmodel.features.generation_service import (
    FeatureGenerationService,
)
from sportsmodel.ingest.mlb_players import (
    SOURCE_NAME as PLAYER_SOURCE_NAME,
    sync_mlb_players,
)
from sportsmodel.ingest.mlb_schedule import (
    sync_mlb_schedule,
)
from sportsmodel.ingest.mlb_stats import (
    MLB_SCHEDULE_URL,
    parse_game_datetime,
)
from sportsmodel.models.baseball_game import (
    BaseballGame,
)
from sportsmodel.models.moneyline_prediction import (
    MoneylineGamePrediction,
)
from sportsmodel.training import (
    load_trained_matchup_moneyline_model,
)


DEFAULT_MODEL_DIRECTORY = Path(
    "data/models/mlb_moneyline_v1"
)

GAME_SOURCE_NAME = "mlb_stats"

REGULAR_SEASON_GAME_TYPE = "R"


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class LoadedMoneylineModelPackage:
    """
    Validated frozen model and manifest metadata.
    """

    model: Any

    model_version: str

    feature_schema_version: str

    model_artifact_sha256: str

    model_training_cutoff: datetime


@dataclass(frozen=True)
class HydratedScheduleGame:
    """
    One valid regular-season MLB game with probable pitchers.
    """

    mlb_game_id: int

    game_datetime: datetime

    home_team_name: str

    away_team_name: str

    home_starting_pitcher_mlb_id: int | None

    away_starting_pitcher_mlb_id: int | None

    home_starting_pitcher_name: str | None

    away_starting_pitcher_name: str | None


@dataclass(frozen=True)
class MoneylinePredictionResult:
    """
    Display details for one persisted Moneyline prediction.
    """

    game_id: int

    mlb_game_id: int

    game_start_time: datetime

    home_team_name: str

    away_team_name: str

    home_starting_pitcher_name: str | None

    away_starting_pitcher_name: str | None

    starter_coverage: str

    home_win_probability: float

    away_win_probability: float

    predicted_team_name: str

    predicted_probability: float

    missing_raw_value_count: int


@dataclass(frozen=True)
class MoneylinePredictionRunResult:
    """
    Completed daily Moneyline prediction-run summary.
    """

    moneyline_prediction_run_id: int

    target_date: date

    prediction_time: datetime

    model_version: str

    feature_schema_version: str

    games_received: int

    predictions_created: int

    games_skipped: int

    predictions: tuple[
        MoneylinePredictionResult,
        ...,
    ]


def fetch_hydrated_schedule_for_date(
    target_date: date,
) -> dict[str, Any]:
    """
    Fetch one MLB schedule date with probable pitchers hydrated.
    """

    response = requests.get(
        MLB_SCHEDULE_URL,
        params={
            "sportId": 1,
            "date": target_date.isoformat(),
            "hydrate": "probablePitcher",
        },
        timeout=30,
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError(
            "MLB schedule response was not a JSON object."
        )

    return payload


def load_current_probable_starters(
    target_date: date,
) -> dict[int, tuple[int | None, int | None]]:
    """Load current MLB probable starters keyed by MLB game ID.

    This is a point-in-time MLB Stats schedule read. Missing probable
    pitchers are preserved as unavailable rather than inferred.
    """

    payload = fetch_hydrated_schedule_for_date(target_date)
    starters: dict[int, tuple[int | None, int | None]] = {}

    for raw_game in _extract_schedule_games(payload):
        game = _parse_hydrated_schedule_game(raw_game)
        if game is None:
            continue
        starters[game.mlb_game_id] = (
            game.home_starting_pitcher_mlb_id,
            game.away_starting_pitcher_mlb_id,
        )

    return starters


def load_moneyline_model_package(
    model_directory: Path = DEFAULT_MODEL_DIRECTORY,
) -> LoadedMoneylineModelPackage:
    """
    Load and validate one frozen Moneyline model package.
    """

    manifest_path = (
        model_directory
        / "manifest.json"
    )
    model_path = (
        model_directory
        / "model.joblib"
    )

    if not manifest_path.exists():
        raise FileNotFoundError(
            "Moneyline model manifest was not found: "
            f"{manifest_path}"
        )

    if not model_path.exists():
        raise FileNotFoundError(
            "Moneyline model artifact was not found: "
            f"{model_path}"
        )

    manifest = json.loads(
        manifest_path.read_text(
            encoding="utf-8",
        )
    )

    if not isinstance(manifest, dict):
        raise ValueError(
            "Moneyline model manifest must be a JSON object."
        )

    model_version = _require_nonempty_string(
        manifest.get("model_version"),
        field_name="model_version",
    )

    feature_schema_version = (
        _require_nonempty_string(
            manifest.get(
                "feature_schema_version"
            ),
            field_name=(
                "feature_schema_version"
            ),
        )
    )

    artifacts = manifest.get("artifacts")

    if not isinstance(artifacts, dict):
        raise ValueError(
            "Model manifest is missing artifacts."
        )

    model_record = artifacts.get("model")

    if not isinstance(model_record, dict):
        raise ValueError(
            "Model manifest is missing its model artifact record."
        )

    expected_model_hash = (
        _require_nonempty_string(
            model_record.get("sha256"),
            field_name=(
                "artifacts.model.sha256"
            ),
        )
    )

    actual_model_hash = (
        _calculate_sha256(model_path)
    )

    if actual_model_hash != expected_model_hash:
        raise RuntimeError(
            "Moneyline model artifact checksum does not match "
            "the frozen manifest."
        )

    training = manifest.get("training")

    if not isinstance(training, dict):
        raise ValueError(
            "Model manifest is missing training metadata."
        )

    model_training_cutoff = (
        _parse_aware_datetime(
            _require_nonempty_string(
                training.get("end_time"),
                field_name=(
                    "training.end_time"
                ),
            ),
            field_name=(
                "training.end_time"
            ),
        )
    )

    model = (
        load_trained_matchup_moneyline_model(
            model_path
        )
    )

    if (
        model.model.feature_schema_version
        != feature_schema_version
    ):
        raise RuntimeError(
            "Loaded model feature schema does not match "
            "the frozen manifest."
        )

    return LoadedMoneylineModelPackage(
        model=model,
        model_version=model_version,
        feature_schema_version=(
            feature_schema_version
        ),
        model_artifact_sha256=(
            actual_model_hash
        ),
        model_training_cutoff=(
            model_training_cutoff
        ),
    )


def run_moneyline_predictions(
    *,
    target_date: date,
    model_directory: Path = (
        DEFAULT_MODEL_DIRECTORY
    ),
    prediction_time: datetime | None = None,
    run_type: str = "official",
    connection_factory: ConnectionFactory = (
        get_connection
    ),
    feature_generation_service: (
        FeatureGenerationService | None
    ) = None,
) -> MoneylinePredictionRunResult:
    """
    Generate and persist one daily MLB Moneyline prediction run.
    """

    resolved_prediction_time = (
        datetime.now(timezone.utc)
        if prediction_time is None
        else prediction_time
    )

    _validate_aware_datetime(
        resolved_prediction_time,
        field_name="Prediction time",
    )

    normalized_run_type = run_type.strip().lower()

    if normalized_run_type not in {
        "official",
        "preview",
    }:
        raise ValueError(
            "Prediction run type must be official or preview."
        )

    model_package = (
        load_moneyline_model_package(
            model_directory
        )
    )

    connection = connection_factory()

    run_id: int | None = None
    games_received = 0
    predictions_created = 0
    games_skipped = 0

    prediction_results: list[
        MoneylinePredictionResult
    ] = []

    try:
        create_run_arguments = {
            "target_date": target_date,
            "model_version": model_package.model_version,
            "feature_schema_version": (
                model_package.feature_schema_version
            ),
            "model_artifact_sha256": (
                model_package.model_artifact_sha256
            ),
            "model_training_cutoff": (
                model_package.model_training_cutoff
            ),
        }

        if normalized_run_type == "preview":
            create_run_arguments["run_type"] = "preview"

        run_id = (
            create_moneyline_prediction_run(
                connection,
                **create_run_arguments,
            )
        )

        schedule_payload = (
            fetch_hydrated_schedule_for_date(
                target_date
            )
        )

        schedule_summary = sync_mlb_schedule(
            start_date=target_date,
            days_ahead=0,
            progress_callback=None,
            schedule_fetcher=(
                lambda _: schedule_payload
            ),
        )

        if schedule_summary.dates_failed > 0:
            raise RuntimeError(
                "Canonical schedule synchronization failed "
                f"for {target_date}."
            )

        raw_schedule_games = (
            _extract_schedule_games(
                schedule_payload
            )
        )

        games_received = len(
            raw_schedule_games
        )

        prediction_games: list[
            HydratedScheduleGame
        ] = []

        for raw_game in raw_schedule_games:
            schedule_game = (
                _parse_hydrated_schedule_game(
                    raw_game
                )
            )

            if schedule_game is None:
                games_skipped += 1
                continue

            if (
                schedule_game.game_datetime
                <= resolved_prediction_time
            ):
                games_skipped += 1
                continue

            prediction_games.append(
                schedule_game
            )

        probable_pitcher_ids = sorted(
            {
                player_id
                for game in prediction_games
                for player_id in (
                    game
                    .home_starting_pitcher_mlb_id,
                    game
                    .away_starting_pitcher_mlb_id,
                )
                if player_id is not None
            }
        )

        player_ids_by_mlb_id = (
            get_player_ids_by_source(
                PLAYER_SOURCE_NAME,
                probable_pitcher_ids,
            )
        )

        missing_player_ids = sorted(
            set(probable_pitcher_ids)
            - set(player_ids_by_mlb_id)
        )

        if missing_player_ids:
            sync_mlb_players(
                missing_player_ids
            )

            player_ids_by_mlb_id = (
                get_player_ids_by_source(
                    PLAYER_SOURCE_NAME,
                    probable_pitcher_ids,
                )
            )

        unresolved_player_ids = sorted(
            set(probable_pitcher_ids)
            - set(player_ids_by_mlb_id)
        )

        if unresolved_player_ids:
            raise LookupError(
                "Unable to resolve probable pitcher IDs: "
                + ", ".join(
                    str(player_id)
                    for player_id
                    in unresolved_player_ids
                )
            )

        resolved_feature_service = (
            feature_generation_service
            if feature_generation_service
            is not None
            else FeatureGenerationService()
        )

        for schedule_game in prediction_games:
            canonical_game = (
                _get_canonical_game(
                    connection,
                    mlb_game_id=(
                        schedule_game.mlb_game_id
                    ),
                )
            )

            if canonical_game is None:
                raise LookupError(
                    "No canonical game mapping exists for "
                    f"MLB game "
                    f"{schedule_game.mlb_game_id}."
                )

            home_pitcher_id = (
                player_ids_by_mlb_id.get(
                    schedule_game
                    .home_starting_pitcher_mlb_id
                )
                if (
                    schedule_game
                    .home_starting_pitcher_mlb_id
                    is not None
                )
                else None
            )

            away_pitcher_id = (
                player_ids_by_mlb_id.get(
                    schedule_game
                    .away_starting_pitcher_mlb_id
                )
                if (
                    schedule_game
                    .away_starting_pitcher_mlb_id
                    is not None
                )
                else None
            )

            feature_vector = (
                resolved_feature_service
                .generate_for_game_record(
                    game=canonical_game,
                    cutoff_time=(
                        resolved_prediction_time
                    ),
                    home_starting_pitcher_id=(
                        home_pitcher_id
                    ),
                    away_starting_pitcher_id=(
                        away_pitcher_id
                    ),
                )
            )

            if (
                feature_vector
                .feature_schema_version
                != model_package
                .feature_schema_version
            ):
                raise RuntimeError(
                    "Live feature schema does not match "
                    "the frozen model package."
                )

            flattened_features = (
                flatten_game_feature_vector(
                    feature_vector
                )
            )

            expected_feature_names = (
                model_package
                .model
                .transformer
                .source_feature_names
            )

            if (
                tuple(flattened_features)
                != expected_feature_names
            ):
                raise RuntimeError(
                    "Live feature columns do not match "
                    "the frozen model contract."
                )

            home_probability = (
                model_package
                .model
                .predict_home_win_probability(
                    flattened_features
                )
            )

            away_probability = (
                1.0 - home_probability
            )

            if (
                home_probability
                >= away_probability
            ):
                predicted_team_id = (
                    canonical_game.home_team_id
                )
                predicted_team_name = (
                    schedule_game.home_team_name
                )
                predicted_probability = (
                    home_probability
                )
            else:
                predicted_team_id = (
                    canonical_game.away_team_id
                )
                predicted_team_name = (
                    schedule_game.away_team_name
                )
                predicted_probability = (
                    away_probability
                )

            starter_coverage = (
                _determine_starter_coverage(
                    home_pitcher_mlb_id=(
                        schedule_game
                        .home_starting_pitcher_mlb_id
                    ),
                    away_pitcher_mlb_id=(
                        schedule_game
                        .away_starting_pitcher_mlb_id
                    ),
                )
            )

            missing_raw_value_count = sum(
                value is None
                for value
                in flattened_features.values()
            )

            prediction = MoneylineGamePrediction(
                moneyline_prediction_run_id=(
                    run_id
                ),
                game_id=canonical_game.game_id,
                mlb_game_id=(
                    schedule_game.mlb_game_id
                ),
                game_start_time=(
                    canonical_game
                    .game_start_time
                ),
                prediction_time=(
                    resolved_prediction_time
                ),
                home_team_id=(
                    canonical_game.home_team_id
                ),
                away_team_id=(
                    canonical_game.away_team_id
                ),
                home_starting_pitcher_id=(
                    home_pitcher_id
                ),
                away_starting_pitcher_id=(
                    away_pitcher_id
                ),
                home_starting_pitcher_mlb_id=(
                    schedule_game
                    .home_starting_pitcher_mlb_id
                ),
                away_starting_pitcher_mlb_id=(
                    schedule_game
                    .away_starting_pitcher_mlb_id
                ),
                home_starter_features_available=(
                    feature_vector
                    .home_starting_pitcher
                    .starter_available
                ),
                away_starter_features_available=(
                    feature_vector
                    .away_starting_pitcher
                    .starter_available
                ),
                starter_coverage=(
                    starter_coverage
                ),
                missing_raw_value_count=(
                    missing_raw_value_count
                ),
                home_win_probability=(
                    home_probability
                ),
                away_win_probability=(
                    away_probability
                ),
                predicted_team_id=(
                    predicted_team_id
                ),
                predicted_probability=(
                    predicted_probability
                ),
            )

            with connection.cursor() as cursor:
                insert_moneyline_game_prediction(
                    cursor,
                    prediction,
                )

            predictions_created += 1

            prediction_results.append(
                MoneylinePredictionResult(
                    game_id=(
                        canonical_game.game_id
                    ),
                    mlb_game_id=(
                        schedule_game.mlb_game_id
                    ),
                    game_start_time=(
                        canonical_game
                        .game_start_time
                    ),
                    home_team_name=(
                        schedule_game.home_team_name
                    ),
                    away_team_name=(
                        schedule_game.away_team_name
                    ),
                    home_starting_pitcher_name=(
                        schedule_game
                        .home_starting_pitcher_name
                    ),
                    away_starting_pitcher_name=(
                        schedule_game
                        .away_starting_pitcher_name
                    ),
                    starter_coverage=(
                        starter_coverage
                    ),
                    home_win_probability=(
                        home_probability
                    ),
                    away_win_probability=(
                        away_probability
                    ),
                    predicted_team_name=(
                        predicted_team_name
                    ),
                    predicted_probability=(
                        predicted_probability
                    ),
                    missing_raw_value_count=(
                        missing_raw_value_count
                    ),
                )
            )

        with connection.cursor() as cursor:
            mark_moneyline_prediction_run_completed(
                cursor,
                moneyline_prediction_run_id=(
                    run_id
                ),
                games_received=games_received,
                predictions_created=(
                    predictions_created
                ),
                games_skipped=games_skipped,
            )

        connection.commit()

        return MoneylinePredictionRunResult(
            moneyline_prediction_run_id=run_id,
            target_date=target_date,
            prediction_time=(
                resolved_prediction_time
            ),
            model_version=(
                model_package.model_version
            ),
            feature_schema_version=(
                model_package
                .feature_schema_version
            ),
            games_received=games_received,
            predictions_created=(
                predictions_created
            ),
            games_skipped=games_skipped,
            predictions=tuple(
                prediction_results
            ),
        )

    except Exception as error:
        connection.rollback()

        if run_id is not None:
            mark_moneyline_prediction_run_failed(
                connection,
                moneyline_prediction_run_id=(
                    run_id
                ),
                games_received=games_received,
                predictions_created=0,
                games_skipped=games_skipped,
                error_message=_format_error(
                    error
                ),
            )

        raise

    finally:
        connection.close()


def _extract_schedule_games(
    schedule_payload: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    date_blocks = schedule_payload.get(
        "dates"
    )

    if not isinstance(date_blocks, list):
        return ()

    games: list[dict[str, Any]] = []

    for date_block in date_blocks:
        if not isinstance(date_block, dict):
            continue

        date_games = date_block.get(
            "games"
        )

        if not isinstance(date_games, list):
            continue

        games.extend(
            game
            for game in date_games
            if isinstance(game, dict)
        )

    return tuple(games)


def _parse_hydrated_schedule_game(
    game: dict[str, Any],
) -> HydratedScheduleGame | None:
    if (
        game.get("gameType")
        != REGULAR_SEASON_GAME_TYPE
    ):
        return None

    mlb_game_id = game.get("gamePk")
    game_datetime = parse_game_datetime(
        game
    )
    teams = game.get("teams")

    if (
        not isinstance(mlb_game_id, int)
        or mlb_game_id <= 0
        or game_datetime is None
        or not isinstance(teams, dict)
    ):
        return None

    home = teams.get("home")
    away = teams.get("away")

    home_team_name = (
        _extract_team_name(home)
    )
    away_team_name = (
        _extract_team_name(away)
    )

    if (
        home_team_name is None
        or away_team_name is None
    ):
        return None

    (
        home_pitcher_id,
        home_pitcher_name,
    ) = _extract_probable_pitcher(home)

    (
        away_pitcher_id,
        away_pitcher_name,
    ) = _extract_probable_pitcher(away)

    return HydratedScheduleGame(
        mlb_game_id=mlb_game_id,
        game_datetime=game_datetime,
        home_team_name=home_team_name,
        away_team_name=away_team_name,
        home_starting_pitcher_mlb_id=(
            home_pitcher_id
        ),
        away_starting_pitcher_mlb_id=(
            away_pitcher_id
        ),
        home_starting_pitcher_name=(
            home_pitcher_name
        ),
        away_starting_pitcher_name=(
            away_pitcher_name
        ),
    )


def _extract_team_name(
    side: Any,
) -> str | None:
    if not isinstance(side, dict):
        return None

    team = side.get("team")

    if not isinstance(team, dict):
        return None

    team_name = team.get("name")

    if (
        not isinstance(team_name, str)
        or not team_name.strip()
    ):
        return None

    return team_name.strip()


def _extract_probable_pitcher(
    side: Any,
) -> tuple[int | None, str | None]:
    if not isinstance(side, dict):
        return None, None

    pitcher = side.get(
        "probablePitcher"
    )

    if not isinstance(pitcher, dict):
        return None, None

    player_id = pitcher.get("id")
    player_name = pitcher.get(
        "fullName"
    )

    if (
        not isinstance(player_id, int)
        or player_id <= 0
    ):
        return None, None

    normalized_name = (
        player_name.strip()
        if (
            isinstance(player_name, str)
            and player_name.strip()
        )
        else None
    )

    return player_id, normalized_name


def _determine_starter_coverage(
    *,
    home_pitcher_mlb_id: int | None,
    away_pitcher_mlb_id: int | None,
) -> str:
    starter_count = sum(
        player_id is not None
        for player_id in (
            home_pitcher_mlb_id,
            away_pitcher_mlb_id,
        )
    )

    return {
        0: "none",
        1: "partial",
        2: "both",
    }[starter_count]


def _get_canonical_game(
    connection: Any,
    *,
    mlb_game_id: int,
) -> BaseballGame | None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                game.game_id,
                game.game_date,
                game.home_team_id,
                game.away_team_id
            FROM game_sources AS source
            JOIN games AS game
              ON game.game_id = source.game_id
            WHERE source.source_name = %s
              AND source.external_game_id = %s
              AND game.home_team_id IS NOT NULL
              AND game.away_team_id IS NOT NULL;
            """,
            (
                GAME_SOURCE_NAME,
                str(mlb_game_id),
            ),
        )

        row = cursor.fetchone()

    if row is None:
        return None

    return BaseballGame(
        game_id=row[0],
        game_start_time=row[1],
        home_team_id=row[2],
        away_team_id=row[3],
    )


def _calculate_sha256(
    path: Path,
) -> str:
    digest = sha256()

    with path.open("rb") as input_file:
        for chunk in iter(
            lambda: input_file.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def _require_nonempty_string(
    value: Any,
    *,
    field_name: str,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
    ):
        raise ValueError(
            f"Model manifest field "
            f"{field_name} is missing."
        )

    return value.strip()


def _parse_aware_datetime(
    value: str,
    *,
    field_name: str,
) -> datetime:
    try:
        parsed = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError as error:
        raise ValueError(
            f"{field_name} is not a valid "
            "ISO-8601 datetime."
        ) from error

    _validate_aware_datetime(
        parsed,
        field_name=field_name,
    )

    return parsed


def _validate_aware_datetime(
    value: datetime,
    *,
    field_name: str,
) -> None:
    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{field_name} must be timezone-aware."
        )


def _format_error(
    error: Exception,
) -> str:
    return (
        f"{type(error).__name__}: "
        f"{error}"
    )
