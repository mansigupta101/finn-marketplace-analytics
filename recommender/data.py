"""Load Part 3 inputs from Snowflake.

Results are cached in recommender/cache/ so repeated runs don't query Snowflake again.
Pass refresh=True (or delete the cache folder) after rebuilding the dbt models.
"""

from pathlib import Path

import pandas as pd

from analysis.snowflake_io import database, query

CACHE_DIR = Path(__file__).resolve().parent / "cache"
STAGING = "analytics_staging"
INTERMEDIATE = "analytics_intermediate"
MARTS = "analytics_marts"


def _cached(name, sql, refresh=False):
    CACHE_DIR.mkdir(exist_ok=True)
    path = CACHE_DIR / f"{database().lower()}_{name}.pkl"
    if path.exists() and not refresh:
        return pd.read_pickle(path)
    frame = query(sql)
    frame.to_pickle(path)
    return frame


def first5_clicks(refresh=False):
    """Clicks in every buyer's first 5 interactions (all surfaces). Used to learn preferences."""
    return _cached(
        "first5_clicks",
        f"""
        select user_id, split_group, interaction_seq, interaction_type,
               clicked_item_id as item_id
        from {INTERMEDIATE}.int_rec_split
        where period = 'first5' and has_click
        """,
        refresh,
    )


def later_clicks(refresh=False):
    """Clicks after the first 5 interactions (all surfaces, all groups).

    Validation/test: evaluation targets. Train: labels for LightGBM option B.
    """
    return _cached(
        "later_clicks",
        f"""
        select user_id, split_group, interaction_seq, interaction_type,
               clicked_item_id as item_id
        from {INTERMEDIATE}.int_rec_split
        where period = 'later' and has_click
        """,
        refresh,
    )


def buyer_features(refresh=False):
    return _cached(
        "buyer_features", f"select * from {MARTS}.mart_rec_buyer_features", refresh
    )


def item_features(refresh=False):
    """Also the catalogue for coverage: known listings shown in the first 5 interactions."""
    return _cached(
        "item_features", f"select * from {MARTS}.mart_rec_item_features", refresh
    )


def item_attributes(refresh=False):
    """Category and county of every known listing shown in the data.

    These are fixed properties of a listing, so using them for all listings is not leakage.
    """
    return _cached(
        "item_attributes",
        f"""
        select distinct s.item_id, s.main_category, s.county
        from {STAGING}.stg_items as s
        inner join (select distinct item_id from {MARTS}.mart_rec_train) as t
            on t.item_id = s.item_id
        """,
        refresh,
    )


def train_impressions(refresh=False):
    """Training rows for LightGBM option A.

    Every known listing shown in the train buyers' later recommendation slates, with
    clicked = 1 or 0. Slates with a removed item are left out: the click in those slates
    points to the removed listing, which is not a shown row, so every shown listing would
    wrongly get label 0.
    """
    return _cached(
        "train_impressions",
        f"""
        select user_id, interaction_step, item_id, clicked
        from {MARTS}.mart_rec_train
        where split_group = 'train'
          and period = 'later'
          and interaction_type = 'recommendation'
          and not has_removed_item
        """,
        refresh,
    )


def slate_rows(group, refresh=False):
    """Known listings shown in a group's later recommendation slates, in FINN's order.

    group is 'train', 'validation' or 'test'. Slates with a removed item are left out,
    because their click points to a listing that is not among the shown rows.
    """
    return _cached(
        f"slate_rows_{group}",
        f"""
        select user_id, interaction_step, item_id, display_position, clicked
        from {MARTS}.mart_rec_train
        where split_group = '{group}'
          and period = 'later'
          and interaction_type = 'recommendation'
          and not has_removed_item
        """,
        refresh,
    )
