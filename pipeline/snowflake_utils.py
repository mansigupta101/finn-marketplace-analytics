"""Shared Snowflake helpers for the pipeline scripts: connecting, reading a query, loading Parquet."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pyarrow as pa

REPO_ROOT = Path(__file__).resolve().parents[1]

SNOWFLAKE_TYPES = {
    pa.bool_(): "BOOLEAN",
    pa.int8(): "NUMBER(3,0)",
    pa.int16(): "NUMBER(5,0)",
    pa.int32(): "NUMBER(10,0)",
    pa.int64(): "NUMBER(19,0)",
    pa.float64(): "FLOAT",
    pa.string(): "VARCHAR",
}


def connect(database: str | None = None, schema: str | None = None):
    """Connects with the settings in .env: a private key if configured, otherwise a password or token."""
    import snowflake.connector
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=True)
    key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    credentials = (
        {"private_key_file": os.path.expanduser(key_path)}
        if key_path
        else {"password": os.environ["SNOWFLAKE_PASSWORD"]}
    )
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        **credentials,
        role=os.environ.get("SNOWFLAKE_ROLE", "FINN_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "FINN_WH"),
        database=database,
        schema=schema,
    )


def read_query(sql: str, database: str | None = None) -> pd.DataFrame:
    """Runs a query and returns the result with lowercase column names."""
    connection = connect(database=database)
    try:
        cursor = connection.cursor()
        cursor.execute(sql)
        try:
            frame = cursor.fetch_pandas_all()
        except Exception:  # pandas extra not available: fall back to plain rows
            columns = [column[0] for column in cursor.description]
            frame = pd.DataFrame(cursor.fetchall(), columns=columns)
    finally:
        connection.close()
    frame.columns = [column.lower() for column in frame.columns]
    for column in frame.columns:
        converted = pd.to_numeric(frame[column], errors="coerce")
        if converted.notna().sum() == frame[column].notna().sum():
            frame[column] = converted
    return frame


def create_table_sql(database: str, schema: str, table: str, arrow_schema: pa.Schema) -> str:
    columns = ",\n    ".join(
        f"{field.name.upper()} {SNOWFLAKE_TYPES[field.type]}" for field in arrow_schema
    )
    return f"CREATE OR REPLACE TABLE {database}.{schema}.{table.upper()} (\n    {columns}\n)"


def load_parquet(cursor, database: str, schema: str, table: str, path: Path, arrow_schema: pa.Schema,
                 expected_rows: int) -> None:
    """Recreates a table, loads one Parquet file into it and checks the row count."""
    table = table.upper()
    cursor.execute(create_table_sql(database, schema, table, arrow_schema))
    cursor.execute(f"PUT 'file://{path.resolve().as_posix()}' @%{table} OVERWRITE = TRUE AUTO_COMPRESS = FALSE")
    cursor.execute(
        f"""COPY INTO {table}
            FROM @%{table}
            FILE_FORMAT = (TYPE = PARQUET)
            MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
            ON_ERROR = ABORT_STATEMENT
            PURGE = TRUE"""
    )
    loaded = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    if loaded != expected_rows:
        raise RuntimeError(f"{table}: expected {expected_rows} rows, loaded {loaded}")
