"""Feature table for the LightGBM ranker: one row per (buyer, listing) pair.

Every feature comes from the buyers' first 5 interactions or from fixed listing attributes
(category, county), so no feature contains a click the model is asked to predict.
"""

import numpy as np
import pandas as pd

FEATURES = ["als_score", "popularity", "category_match", "county_match", "search_share"]

CHUNK = 200000


def als_pair_scores(model, user_index, item_index, users, items):
    """ALS score for each (buyer, listing) pair: the dot product of their ALS profiles.

    NaN when ALS has never seen the buyer or the listing. Done in chunks because each
    profile is large (256 numbers per row).
    """
    user_pos = pd.Series(users).map(user_index).to_numpy(dtype="float64")
    item_pos = pd.Series(items).map(item_index).to_numpy(dtype="float64")
    scores = np.full(len(user_pos), np.nan)
    known = ~np.isnan(user_pos) & ~np.isnan(item_pos)
    rows = np.where(known)[0]
    for start in range(0, len(rows), CHUNK):
        part = rows[start:start + CHUNK]
        u = model.user_factors[user_pos[part].astype(int)]
        i = model.item_factors[item_pos[part].astype(int)]
        scores[part] = (u * i).sum(axis=1)
    return scores


def _match(listing_value, buyer_value):
    """1 if equal, 0 if different, NaN if either is unknown."""
    result = (listing_value == buyer_value).astype("float64")
    result[listing_value.isna() | buyer_value.isna()] = np.nan
    return result


def add_features(rows, items, buyers, attributes):
    """Add the five features to `rows`, which needs user_id, item_id and als_score.

    items:      mart_rec_item_features (popularity = clicks in the first 5 interactions)
    buyers:     mart_rec_buyer_features (top category, top county, search share)
    attributes: category and county of each listing
    """
    out = rows.merge(items[["item_id", "n_clicks_first5"]], on="item_id", how="left")
    out = out.merge(attributes, on="item_id", how="left")
    out = out.merge(
        buyers[["user_id", "top_category", "top_county", "search_share"]],
        on="user_id", how="left",
    )
    out["popularity"] = out["n_clicks_first5"].fillna(0)
    out["category_match"] = _match(out["main_category"], out["top_category"])
    out["county_match"] = _match(out["county"], out["top_county"])
    return out


def candidate_frame(recs, scores):
    """One row per (buyer, candidate listing) from the ALS top-200 lists and their scores."""
    users, items, values = [], [], []
    for user in recs:
        users.extend([user] * len(recs[user]))
        items.extend(recs[user])
        values.extend(scores[user])
    return pd.DataFrame({"user_id": users, "item_id": items, "als_score": values})
