import numpy as np
import pandas as pd

from recommender import features, lgbm


class FakeAls:
    user_factors = np.array([[1.0, 0.0], [0.0, 2.0]])
    item_factors = np.array([[3.0, 1.0], [1.0, 1.0]])


class FakeRanker:
    def predict(self, x):
        return x["als_score"].to_numpy()


def test_match_values():
    listing = pd.Series(["a", "a", None, "b"])
    buyer = pd.Series(["a", "b", "a", None])
    out = features._match(listing, buyer)
    assert out.iloc[0] == 1.0
    assert out.iloc[1] == 0.0
    assert np.isnan(out.iloc[2])
    assert np.isnan(out.iloc[3])


def test_als_pair_scores_dot_product_and_nan_for_unknown():
    out = features.als_pair_scores(
        FakeAls(), {10: 0, 20: 1}, {100: 0, 200: 1},
        pd.Series([10, 20, 99]), pd.Series([100, 200, 100]),
    )
    assert out[0] == 3.0
    assert out[1] == 2.0
    assert np.isnan(out[2])


def test_add_features_keeps_rows_and_order():
    rows = pd.DataFrame({"user_id": [1, 1, 2], "item_id": [10, 11, 10],
                         "als_score": [0.5, np.nan, 0.1]})
    items = pd.DataFrame({"item_id": [10], "n_clicks_first5": [7]})
    buyers = pd.DataFrame({"user_id": [1, 2], "top_category": ["car", None],
                           "top_county": ["Oslo", "Oslo"], "search_share": [0.4, 1.0]})
    attributes = pd.DataFrame({"item_id": [10, 11], "main_category": ["car", "boat"],
                               "county": ["Oslo", "Viken"]})
    out = features.add_features(rows, items, buyers, attributes)
    assert list(out["item_id"]) == [10, 11, 10]
    assert list(out["popularity"]) == [7, 0, 7]
    assert out["category_match"].iloc[0] == 1.0
    assert out["category_match"].iloc[1] == 0.0
    assert np.isnan(out["category_match"].iloc[2])
    assert list(out["county_match"]) == [1.0, 0.0, 1.0]


def test_rank_candidates_orders_by_score_and_cuts_at_k():
    candidates = pd.DataFrame({"user_id": [1, 1, 1, 2], "item_id": [5, 6, 7, 8],
                               "als_score": [0.1, 0.9, 0.5, 0.3]})
    for name in features.FEATURES:
        if name not in candidates:
            candidates[name] = 0.0
    assert lgbm.rank_candidates(FakeRanker(), candidates, k=2) == {1: [6, 7], 2: [8]}
