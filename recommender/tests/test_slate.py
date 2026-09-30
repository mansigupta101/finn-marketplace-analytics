import numpy as np
import pandas as pd

from recommender import metrics


def make_slate():
    return pd.DataFrame({
        "user_id": [1, 1, 1],
        "interaction_step": [6, 6, 6],
        "item_id": [10, 11, 12],
        "display_position": [1, 2, 3],
        "clicked": [0, 1, 0],
        "score": [0.1, 0.9, 0.5],
    })


def test_finn_order_rank_of_clicked_listing():
    rows = make_slate()
    rows["finn_order"] = -rows["display_position"]
    out = metrics.slate_ndcg_by_buyer(rows, "finn_order")
    assert np.isclose(out.loc[1], 1 / np.log2(3))


def test_better_score_puts_clicked_listing_first():
    out = metrics.slate_ndcg_by_buyer(make_slate(), "score")
    assert np.isclose(out.loc[1], 1.0)


def test_ties_keep_finn_order_and_missing_scores_go_last():
    rows = make_slate()
    rows["score"] = [np.nan, 0.5, 0.5]
    out = metrics.slate_ndcg_by_buyer(rows, "score")
    # listing 11 (clicked) ties with 12 and comes first by FINN's order; 10 is missing, last
    assert np.isclose(out.loc[1], 1.0)


def test_paired_difference():
    a = pd.Series([0.5, 0.7, 0.9], index=[1, 2, 3])
    b = pd.Series([0.4, 0.6, 0.8], index=[1, 2, 3])
    mean, low, high = metrics.paired_difference(a, b)
    assert np.isclose(mean, 0.1)
    assert low <= mean <= high
