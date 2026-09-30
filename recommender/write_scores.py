"""Write every model's top-10 lists to Snowflake: RAW.RECOMMENDER.SCORES.

Run from the main folder:  python -m recommender.write_scores

Input: the lists file saved by run_final (model, user_id, item_id, rank, score, is_fallback).
Output: table RAW.RECOMMENDER.SCORES with one row per model, buyer and listing.
Running it again replaces the table, so it is safe to repeat.

Steps:
1. Read the lists file.
2. Connect to Snowflake (same .env and login as the other scripts).
3. Create the schema RAW.RECOMMENDER and the table. If FINN_ROLE is not allowed to,
   print the grant to run in Snowsight and stop.
4. Load the rows.
5. Print the row count per model as a check.
"""

import os
from pathlib import Path

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv
from snowflake.connector.pandas_tools import write_pandas

REPO_ROOT = Path(__file__).resolve().parents[1]
LISTS_FILE = REPO_ROOT / "analysis" / "results" / "rec_eval_test_lists.csv"
SPLIT_GROUP = "test"

DATABASE = "RAW"
SCHEMA = "RECOMMENDER"
TABLE = "SCORES"


def connect():
    load_dotenv(REPO_ROOT / ".env", override=True)
    key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    if key_path:
        credentials = {"private_key_file": os.path.expanduser(key_path)}
    else:
        credentials = {"password": os.environ["SNOWFLAKE_PASSWORD"]}
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        **credentials,
        role=os.environ.get("SNOWFLAKE_ROLE", "FINN_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "FINN_WH"),
        database=DATABASE,
    )


def main():
    # 1. Read the lists file
    lists = pd.read_csv(LISTS_FILE)
    lists["split_group"] = SPLIT_GROUP
    if "is_fallback" not in lists:
        raise SystemExit("The lists file has no is_fallback column. Run run_final again first.")
    lists.columns = [name.upper() for name in lists.columns]
    lists = lists[["SPLIT_GROUP", "MODEL", "USER_ID", "ITEM_ID", "RANK", "SCORE", "IS_FALLBACK"]]
    print("Rows in file:", len(lists))

    # 2. Connect
    connection = connect()
    try:
        cursor = connection.cursor()
        role = os.environ.get("SNOWFLAKE_ROLE", "FINN_ROLE")

        # 3. Schema and table
        try:
            cursor.execute(f"create schema if not exists {DATABASE}.{SCHEMA}")
            cursor.execute(
                f"""
                create or replace table {DATABASE}.{SCHEMA}.{TABLE} (
                    split_group varchar,
                    model       varchar,
                    user_id     number,
                    item_id     number,
                    rank        number,
                    score       float,
                    is_fallback boolean
                )
                """
            )
        except snowflake.connector.errors.ProgrammingError as error:
            print("\nCould not create the schema or table:", error.msg)
            print("Run this in Snowsight as ACCOUNTADMIN, then run this script again:")
            print(f"  grant create schema on database {DATABASE} to role {role};")
            return

        # 4. Load
        ok, n_chunks, n_rows, _ = write_pandas(
            connection, lists, TABLE, database=DATABASE, schema=SCHEMA
        )
        print("Loaded:", ok, "rows:", n_rows)

        # 5. Check
        cursor.execute(
            f"""
            select model, count(*) as rows_, count(distinct user_id) as buyers,
                   count(distinct iff(is_fallback, user_id, null)) as fallback_buyers
            from {DATABASE}.{SCHEMA}.{TABLE}
            group by model
            order by model
            """
        )
        print("\nRows per model:")
        for model, rows, buyers, fallback_buyers in cursor.fetchall():
            print(f"  {model:22s} rows {rows:>8}   buyers {buyers:>7}   fallback {fallback_buyers:>6}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
