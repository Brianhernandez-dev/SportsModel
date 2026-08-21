import os

import psycopg2
from psycopg2.extras import register_uuid
from dotenv import load_dotenv


register_uuid()


def load_database_environment() -> None:
    """
    Load database settings from an explicit environment file when set.
    """

    environment_file = os.getenv(
        "SPORTSMODEL_ENV_FILE"
    )

    if environment_file:
        load_dotenv(
            environment_file,
            override=True,
        )
        return

    load_dotenv()


load_database_environment()


def get_connection():
    """
    Returns a PostgreSQL connection using environment variables.
    """

    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )
