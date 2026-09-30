"""Read query results from Snowflake into pandas.

Uses the same .env file as the loader. The dbt models are read from the DEV database by
default; set FINN_DATABASE=PROD to read the production build instead.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]


def database() -> str:
    return os.environ.get("FINN_DATABASE", "DEV")


def query(sql: str) -> pd.DataFrame:
    """Runs a query and returns the result with lowercase column names."""
    import snowflake.connector
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=True)

    key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    credentials = (
        {"private_key_file": os.path.expanduser(key_path)}
        if key_path
        else {"password": os.environ["SNOWFLAKE_PASSWORD"]}
    )
    connection = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        **credentials,
        role=os.environ.get("SNOWFLAKE_ROLE", "FINN_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "FINN_WH"),
        database=database(),
    )
    try:
        cursor = connection.cursor()
        cursor.execute(sql)
        columns = [column[0].lower() for column in cursor.description]
        frame = pd.DataFrame(cursor.fetchall(), columns=columns)
    finally:
        connection.close()

    # Snowflake returns NUMBER columns as Python Decimals; turn them into ordinary numbers.
    for column in frame.columns:
        converted = pd.to_numeric(frame[column], errors="coerce")
        if converted.notna().sum() == frame[column].notna().sum():
            frame[column] = converted
    return frame
